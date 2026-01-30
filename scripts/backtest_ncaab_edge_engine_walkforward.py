#!/usr/bin/env python3
"""Walk-forward backtest for NCAAB Edge Engine (Phase A).

Goal: maximize ROI with realistic constraints.

Data:
- historical_games_action_network (Action Network snapshots)
- bt_team_features_daily (Torvik-style team metrics)

Season labeling: season_end_year (2026 = 2025-2026 season).

We compute per-game:
- open/close lines + odds (by date_scraped)
- splits features (tickets%, money%)
- Torvik computed margin/total as-of game date (YYYYMMDD)

Markets:
- SPREAD (home side)
- TOTAL (over side)
- ML (home side)

Modeling:
- Market-baseline residual logistic regression:
    logit(p_model) = logit(p_market_no_vig) + (X @ w + b)
  This prevents "re-learning the market" and focuses on incremental edge.

Betting:
- variable units based on confidence: 1u/2u/3u
- max 10 units/day
- allow multiple bets per game
- cap 5 units per game across all bets

Run:
  cd /Users/basementai/clawd/repos/basement-bets
  source .venv311/bin/activate
  python scripts/backtest_ncaab_edge_engine_walkforward.py --season 2026

Output:
  Prints summary + writes JSON report to data/model_params/edge_engine_backtest_ncaab_2026.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, date as dt_date

import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.database import get_db_connection, _exec


# ----------------------------
# Odds + math
# ----------------------------

def american_to_decimal(odds: float) -> float | None:
    if odds is None:
        return None
    try:
        o = float(odds)
    except Exception:
        return None
    if o == 0:
        return None
    if o > 0:
        return 1.0 + (o / 100.0)
    return 1.0 + (100.0 / abs(o))


def implied_prob_american(odds: float) -> float | None:
    dec = american_to_decimal(odds)
    if dec is None or dec <= 1.0:
        return None
    return 1.0 / dec


def devig_two_sided(home_odds: float, away_odds: float) -> tuple[float | None, float | None]:
    p1 = implied_prob_american(home_odds)
    p2 = implied_prob_american(away_odds)
    if p1 is None or p2 is None:
        return None, None
    s = p1 + p2
    if s <= 1e-9:
        return None, None
    return p1 / s, p2 / s


def logit(p: float) -> float:
    p = min(1 - 1e-9, max(1e-9, float(p)))
    return math.log(p / (1 - p))


def sigmoid(z: np.ndarray) -> np.ndarray:
    z = np.clip(z, -50, 50)
    return 1.0 / (1.0 + np.exp(-z))


def ev_per_unit(p_win: float, american_odds: float) -> float | None:
    dec = american_to_decimal(american_odds)
    if dec is None:
        return None
    return (p_win * (dec - 1.0)) - ((1.0 - p_win) * 1.0)


# ----------------------------
# Team mapping + torvik computed (cached)
# ----------------------------

LEAGUE_AVG_EFF = 106.0


def _norm(s: str) -> str:
    return re.sub(r'[^a-zA-Z0-9\s]', '', (s or '').lower()).strip()


def build_team_mapper(conn) -> callable:
    src = _exec(conn, "SELECT DISTINCT team_text FROM bt_team_features_daily").fetchall()
    source_names = [r[0] for r in src if r and r[0]]
    norm_to_source = {_norm(s): s for s in source_names if s}
    norm_sources = [(_norm(s), s) for s in source_names if s]
    norm_sources.sort(key=lambda t: len(t[0]), reverse=True)

    manual = {
        'southern miss golden eagles': 'Southern Miss',
        'miami fl hurricanes': 'Miami FL',
        'miami (fl) hurricanes': 'Miami FL',
        'uconn huskies': 'Connecticut',
        'ole miss rebels': 'Ole Miss',
        'kent state golden flashes': 'Kent St.',
    }

    def map_name(name: str) -> str:
        n = _norm(name)
        if n in norm_to_source:
            return norm_to_source[n]
        for k, v in manual.items():
            if k in n:
                vv = _norm(v)
                if vv in norm_to_source:
                    return norm_to_source[vv]
        for ns, orig in norm_sources:
            if ns and (n.startswith(ns) and (len(n) == len(ns) or n[len(ns)] == ' ')):
                return orig
        return name

    return map_name


def get_metrics_cached(conn, cache: dict, team_text: str, date_iso: str | None):
    k = (team_text, date_iso)
    if k in cache:
        return cache[k]

    if date_iso:
        row = _exec(
            conn,
            """
            SELECT adj_off, adj_def, adj_tempo
            FROM bt_team_features_daily
            WHERE team_text=:t AND date <= :d
            ORDER BY date DESC
            LIMIT 1
            """,
            {"t": team_text, "d": date_iso},
        ).fetchone()
    else:
        row = _exec(
            conn,
            """
            SELECT adj_off, adj_def, adj_tempo
            FROM bt_team_features_daily
            WHERE team_text=:t
            ORDER BY date DESC
            LIMIT 1
            """,
            {"t": team_text},
        ).fetchone()

    cache[k] = dict(row) if row else None
    return cache[k]


def compute_torvik_margin_total(conn, cache: dict, home_bt: str, away_bt: str, date_key: str | None) -> tuple[float, float]:
    date_iso = None
    if date_key and len(date_key) == 8 and date_key.isdigit():
        date_iso = f"{date_key[:4]}-{date_key[4:6]}-{date_key[6:8]}"

    h = get_metrics_cached(conn, cache, home_bt, date_iso)
    a = get_metrics_cached(conn, cache, away_bt, date_iso)
    if not h or not a:
        return 0.0, 0.0

    tempo = (float(h['adj_tempo']) + float(a['adj_tempo'])) / 2.0
    h_score = (float(h['adj_off']) * float(a['adj_def']) / LEAGUE_AVG_EFF) * (tempo / 100.0)
    a_score = (float(a['adj_off']) * float(h['adj_def']) / LEAGUE_AVG_EFF) * (tempo / 100.0)
    margin = round(h_score - a_score, 1)
    total = round(h_score + a_score, 1)
    return margin, total


# ----------------------------
# Data shapes
# ----------------------------

@dataclass
class GameAgg:
    game_id: int
    date_et: str  # YYYY-MM-DD
    start_time: datetime
    home_team: str
    away_team: str

    # outcomes
    home_score: int
    away_score: int

    # close (used for betting)
    close_home_spread: float
    close_total: float
    close_home_spread_odds: float | None
    close_away_spread_odds: float | None
    close_over_odds: float | None
    close_under_odds: float | None
    close_home_ml: float | None
    close_away_ml: float | None

    # open (features)
    open_home_spread: float | None
    open_total: float | None

    # splits (close snapshot)
    home_spread_ticket_pct: float | None
    home_spread_money_pct: float | None
    over_ticket_pct: float | None
    over_money_pct: float | None
    home_ml_ticket_pct: float | None
    home_ml_money_pct: float | None

    # torvik
    torvik_margin: float
    torvik_total: float


def load_games_agg(season_end_year: int) -> list[GameAgg]:
    """Load per-game open+close snapshots + outcomes for season."""

    q = """
    WITH open_snap AS (
      SELECT DISTINCT ON (game_id)
        game_id,
        home_spread AS open_home_spread,
        total_score AS open_total,
        date_scraped AS open_scraped
      FROM historical_games_action_network
      WHERE sport='ncaab'
        AND season_end_year=%(season)s
        AND status='complete'
        AND home_score IS NOT NULL AND away_score IS NOT NULL
        AND home_spread IS NOT NULL AND total_score IS NOT NULL
      ORDER BY game_id, date_scraped ASC
    ),
    close_snap AS (
      SELECT DISTINCT ON (game_id)
        game_id,
        start_time,
        home_team,
        away_team,
        home_score,
        away_score,
        home_spread AS close_home_spread,
        total_score AS close_total,
        home_spread_odds AS close_home_spread_odds,
        away_spread_odds AS close_away_spread_odds,
        over_odds AS close_over_odds,
        under_odds AS close_under_odds,
        home_money_line AS close_home_ml,
        away_money_line AS close_away_ml,
        home_spread_ticket_pct,
        home_spread_money_pct,
        over_ticket_pct,
        over_money_pct,
        home_ml_ticket_pct,
        home_ml_money_pct,
        date_scraped AS close_scraped
      FROM historical_games_action_network
      WHERE sport='ncaab'
        AND season_end_year=%(season)s
        AND status='complete'
        AND home_score IS NOT NULL AND away_score IS NOT NULL
        AND home_spread IS NOT NULL AND total_score IS NOT NULL
      ORDER BY game_id, date_scraped DESC
    )
    SELECT
      c.game_id,
      (DATE(c.start_time AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York'))::text AS date_et,
      c.start_time,
      c.home_team,
      c.away_team,
      c.home_score,
      c.away_score,
      c.close_home_spread,
      c.close_total,
      c.close_home_spread_odds,
      c.close_away_spread_odds,
      c.close_over_odds,
      c.close_under_odds,
      c.close_home_ml,
      c.close_away_ml,
      o.open_home_spread,
      o.open_total,
      c.home_spread_ticket_pct,
      c.home_spread_money_pct,
      c.over_ticket_pct,
      c.over_money_pct,
      c.home_ml_ticket_pct,
      c.home_ml_money_pct
    FROM close_snap c
    LEFT JOIN open_snap o USING (game_id)
    ORDER BY c.start_time ASC
    """

    out: list[GameAgg] = []

    with get_db_connection() as conn:
        rows = _exec(conn, q, {"season": season_end_year}).fetchall()
        map_team = build_team_mapper(conn)
        cache: dict = {}

        for r in rows:
            st = r['start_time']
            date_key = st.strftime('%Y%m%d') if st else None

            date_et = r['date_et']

            home = r['home_team']
            away = r['away_team']
            home_bt = map_team(home)
            away_bt = map_team(away)

            tv_margin, tv_total = compute_torvik_margin_total(conn, cache, home_bt, away_bt, date_key)

            out.append(
                GameAgg(
                    game_id=int(r['game_id']),
                    date_et=date_et,
                    start_time=st,
                    home_team=home,
                    away_team=away,
                    home_score=int(r['home_score'] or 0),
                    away_score=int(r['away_score'] or 0),
                    close_home_spread=float(r['close_home_spread']),
                    close_total=float(r['close_total']),
                    close_home_spread_odds=float(r['close_home_spread_odds']) if r['close_home_spread_odds'] is not None else None,
                    close_away_spread_odds=float(r['close_away_spread_odds']) if r['close_away_spread_odds'] is not None else None,
                    close_over_odds=float(r['close_over_odds']) if r['close_over_odds'] is not None else None,
                    close_under_odds=float(r['close_under_odds']) if r['close_under_odds'] is not None else None,
                    close_home_ml=float(r['close_home_ml']) if r['close_home_ml'] is not None else None,
                    close_away_ml=float(r['close_away_ml']) if r['close_away_ml'] is not None else None,
                    open_home_spread=float(r['open_home_spread']) if r['open_home_spread'] is not None else None,
                    open_total=float(r['open_total']) if r['open_total'] is not None else None,
                    home_spread_ticket_pct=float(r['home_spread_ticket_pct']) if r['home_spread_ticket_pct'] is not None else None,
                    home_spread_money_pct=float(r['home_spread_money_pct']) if r['home_spread_money_pct'] is not None else None,
                    over_ticket_pct=float(r['over_ticket_pct']) if r['over_ticket_pct'] is not None else None,
                    over_money_pct=float(r['over_money_pct']) if r['over_money_pct'] is not None else None,
                    home_ml_ticket_pct=float(r['home_ml_ticket_pct']) if r['home_ml_ticket_pct'] is not None else None,
                    home_ml_money_pct=float(r['home_ml_money_pct']) if r['home_ml_money_pct'] is not None else None,
                    torvik_margin=float(tv_margin),
                    torvik_total=float(tv_total),
                )
            )

    return out


# ----------------------------
# Residual logistic regression
# ----------------------------


def train_residual_logreg(X: np.ndarray, y: np.ndarray, offset_logit: np.ndarray, l2: float = 0.5, lr: float = 0.05, steps: int = 1200) -> tuple[np.ndarray, float]:
    """Train: logit(p) = offset + X@w + b"""
    n, d = X.shape
    w = np.zeros(d, dtype=np.float64)
    b = 0.0

    for _ in range(steps):
        z = offset_logit + (X @ w) + b
        p = sigmoid(z)
        err = (p - y)
        gw = (X.T @ err) / n + l2 * w
        gb = float(np.sum(err) / n)
        w -= lr * gw
        b -= lr * gb

    return w, float(b)


# ----------------------------
# Feature builders
# ----------------------------


def spread_row(g: GameAgg):
    # Need both side odds to devig
    if g.close_home_spread_odds is None or g.close_away_spread_odds is None:
        return None
    p_home, _ = devig_two_sided(g.close_home_spread_odds, g.close_away_spread_odds)
    if p_home is None:
        return None

    actual_margin = g.home_score - g.away_score
    y = 1.0 if (actual_margin + g.close_home_spread) > 0 else 0.0

    move = 0.0
    if g.open_home_spread is not None:
        move = float(g.close_home_spread) - float(g.open_home_spread)

    # features (no bias column; we standardize)
    X = np.array([
        float(g.close_home_spread),
        float(move),
        float(g.torvik_margin),
        float((-g.close_home_spread) - g.torvik_margin),
        float(g.close_total),
        float(g.torvik_total - g.close_total),
        float((g.home_spread_money_pct or 0.0) - (g.home_spread_ticket_pct or 0.0)),
    ], dtype=np.float64)

    return X, y, float(p_home), float(g.close_home_spread_odds)


def total_row(g: GameAgg):
    if g.close_over_odds is None or g.close_under_odds is None:
        return None
    p_over, _ = devig_two_sided(g.close_over_odds, g.close_under_odds)
    if p_over is None:
        return None

    actual_total = g.home_score + g.away_score
    y = 1.0 if (actual_total > g.close_total) else 0.0

    move = 0.0
    if g.open_total is not None:
        move = float(g.close_total) - float(g.open_total)

    X = np.array([
        float(g.close_total),
        float(move),
        float(g.torvik_total),
        float(g.torvik_total - g.close_total),
        float(g.torvik_margin),
        float((g.over_money_pct or 0.0) - (g.over_ticket_pct or 0.0)),
    ], dtype=np.float64)

    return X, y, float(p_over), float(g.close_over_odds)


def ml_row(g: GameAgg):
    if g.close_home_ml is None or g.close_away_ml is None:
        return None
    p_home, _ = devig_two_sided(g.close_home_ml, g.close_away_ml)
    if p_home is None:
        return None

    actual_margin = g.home_score - g.away_score
    y = 1.0 if actual_margin > 0 else 0.0

    X = np.array([
        float(g.close_home_ml),
        float(g.close_home_spread),
        float(g.torvik_margin),
        float(g.torvik_total),
        float((g.home_ml_money_pct or 0.0) - (g.home_ml_ticket_pct or 0.0)),
    ], dtype=np.float64)

    return X, y, float(p_home), float(g.close_home_ml)


# ----------------------------
# Betting policy
# ----------------------------


def confidence_from_ev(ev: float, p_model: float, p_market: float) -> float:
    # simple, monotonic heuristic (we will tune later)
    # boosts when model disagrees with market and EV is larger
    diff = abs(p_model - p_market)
    c = 50.0 + 400.0 * ev + 50.0 * diff
    return max(0.0, min(100.0, c))


def units_from_conf(conf: float) -> int:
    if conf >= 85:
        return 3
    if conf >= 70:
        return 2
    if conf >= 55:
        return 1
    return 0


def bet_narrative(kind: str, g: GameAgg, p_model: float, p_market: float, ev: float, conf: float) -> dict:
    if kind == 'SPREAD':
        line = g.close_home_spread
        odds = g.close_home_spread_odds
        win_cond = f"{g.home_team} must cover {line:+.1f} (win margin > {-line:+.1f})"
        keys = [
            ("Line move (close-open)", (g.close_home_spread - (g.open_home_spread or g.close_home_spread))),
            ("Torvik margin", g.torvik_margin),
            ("Splits (money-tickets)", (g.home_spread_money_pct or 0.0) - (g.home_spread_ticket_pct or 0.0)),
        ]
    elif kind == 'TOTAL':
        line = g.close_total
        odds = g.close_over_odds
        win_cond = f"Game total points must finish OVER {line:.1f}"
        keys = [
            ("Total move (close-open)", (g.close_total - (g.open_total or g.close_total))),
            ("Torvik total", g.torvik_total),
            ("Splits (money-tickets)", (g.over_money_pct or 0.0) - (g.over_ticket_pct or 0.0)),
        ]
    else:
        odds = g.close_home_ml
        win_cond = f"{g.home_team} must win outright"
        keys = [
            ("Torvik margin", g.torvik_margin),
            ("Spread (close)", g.close_home_spread),
            ("Splits (money-tickets)", (g.home_ml_money_pct or 0.0) - (g.home_ml_ticket_pct or 0.0)),
        ]

    drivers = []
    for k, v in keys:
        drivers.append(f"{k}: {v:+.2f}" if isinstance(v, (int, float)) else f"{k}: {v}")

    return {
        "game_id": g.game_id,
        "date": g.date_et,
        "match": f"{g.away_team} @ {g.home_team}",
        "bet_type": kind,
        "odds": odds,
        "p_market": round(p_market, 4),
        "p_model": round(p_model, 4),
        "ev_per_unit": round(ev, 4),
        "confidence": round(conf, 1),
        "why": drivers,
        "needs_to_happen": win_cond,
        "risks": ["Variance/late-game fouls", "Injuries/rotation changes", "Market steam against position"],
    }


# ----------------------------
# Walk-forward backtest
# ----------------------------


def standardize_fit(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd = np.where(sd < 1e-6, 1.0, sd)
    Z = (X - mu) / sd
    return Z, mu, sd


def standardize_apply(X: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    return (X - mu) / sd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, default=2026)
    ap.add_argument('--steps', type=int, default=1200)
    ap.add_argument('--lr', type=float, default=0.05)
    ap.add_argument('--l2', type=float, default=0.5)
    ap.add_argument('--max-units-day', type=int, default=10)
    ap.add_argument('--max-units-game', type=int, default=5)
    ap.add_argument('--min-ev', type=float, default=0.01)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    games = load_games_agg(int(args.season))
    if not games:
        print("no games")
        return 2

    # group by date
    dates = sorted({g.date_et for g in games})

    # storage
    placed = []
    daily = {}

    # track ROI
    total_units = 0.0
    total_bets = 0

    by_kind = {"SPREAD": {"units": 0.0, "bets": 0}, "TOTAL": {"units": 0.0, "bets": 0}, "ML": {"units": 0.0, "bets": 0}}

    for di, day in enumerate(dates):
        train_games = [g for g in games if g.date_et < day]
        test_games = [g for g in games if g.date_et == day]

        # need enough history
        if len(train_games) < 200:
            continue

        # train three residual models
        models = {}
        for kind, row_fn in [("SPREAD", spread_row), ("TOTAL", total_row), ("ML", ml_row)]:
            Xs = []
            ys = []
            offs = []
            for g in train_games:
                rr = row_fn(g)
                if not rr:
                    continue
                X, y, p_mkt, _odds = rr
                Xs.append(X)
                ys.append(y)
                offs.append(logit(p_mkt))

            if len(Xs) < 300:
                continue

            Xtr = np.stack(Xs, axis=0)
            ytr = np.array(ys, dtype=np.float64)
            off = np.array(offs, dtype=np.float64)

            Ztr, mu, sd = standardize_fit(Xtr)
            w, b = train_residual_logreg(Ztr, ytr, off, l2=float(args.l2), lr=float(args.lr), steps=int(args.steps))
            models[kind] = {"w": w, "b": b, "mu": mu, "sd": sd}

        # score candidate bets for the day
        candidates = []
        for g in test_games:
            for kind, row_fn in [("SPREAD", spread_row), ("TOTAL", total_row), ("ML", ml_row)]:
                if kind not in models:
                    continue
                rr = row_fn(g)
                if not rr:
                    continue
                X, y_true, p_mkt, odds = rr

                m = models[kind]
                Z = standardize_apply(X.reshape(1, -1), m['mu'], m['sd'])
                z_adj = float((Z @ m['w'])[0] + m['b'])
                z = logit(p_mkt) + z_adj
                p_model = float(sigmoid(np.array([z]))[0])

                ev = ev_per_unit(p_model, odds)
                if ev is None:
                    continue
                if ev < float(args.min_ev):
                    continue

                conf = confidence_from_ev(ev, p_model, p_mkt)
                units = units_from_conf(conf)
                if units <= 0:
                    continue

                candidates.append({
                    "kind": kind,
                    "g": g,
                    "y": y_true,
                    "p_mkt": p_mkt,
                    "p_model": p_model,
                    "odds": odds,
                    "ev": ev,
                    "conf": conf,
                    "units": units,
                    "score": ev * units,
                })

        # sort by expected profit contribution
        candidates.sort(key=lambda r: r['score'], reverse=True)

        units_left = int(args.max_units_day)
        units_by_game = {}
        day_units = 0.0
        day_bets = 0
        day_units_profit = 0.0

        for c in candidates:
            if units_left <= 0:
                break
            g = c['g']
            gid = g.game_id
            used_game = units_by_game.get(gid, 0)
            if used_game >= int(args.max_units_game):
                continue

            # clamp units to what's left
            u = min(int(c['units']), units_left, int(args.max_units_game) - used_game)
            if u <= 0:
                continue

            # settle bet (home-side only in this phase)
            win = bool(c['y'] >= 0.5)
            dec = american_to_decimal(c['odds'])
            profit = 0.0
            if win:
                profit = u * ((dec - 1.0) if dec else 0.0)
            else:
                profit = -u

            units_left -= u
            units_by_game[gid] = used_game + u

            day_units += u
            day_bets += 1
            day_units_profit += profit

            total_units += u
            total_bets += 1
            by_kind[c['kind']]["units"] += profit
            by_kind[c['kind']]["bets"] += 1

            placed.append({
                **bet_narrative(c['kind'], g, c['p_model'], c['p_mkt'], c['ev'], c['conf']),
                "units": u,
                "result": "win" if win else "loss",
                "profit_units": round(profit, 3),
            })

        daily[day] = {
            "bets": day_bets,
            "units_staked": round(day_units, 3),
            "profit_units": round(day_units_profit, 3),
        }

    roi = (sum(d["profit_units"] for d in daily.values()) / total_units * 100.0) if total_units else 0.0

    summary = {
        "season_end_year": int(args.season),
        "max_units_day": int(args.max_units_day),
        "max_units_game": int(args.max_units_game),
        "min_ev": float(args.min_ev),
        "total_bets": total_bets,
        "total_units_staked": round(total_units, 3),
        "total_profit_units": round(sum(d["profit_units"] for d in daily.values()), 3),
        "roi_pct": round(roi, 2),
        "by_market": {
            k: {"bets": v["bets"], "profit_units": round(v["units"], 3)} for k, v in by_kind.items()
        },
    }

    report = {
        "ran_at": datetime.now().isoformat(),
        "summary": summary,
        "daily": daily,
        "bets": placed,
    }

    print(json.dumps(summary, indent=2))

    # Default output includes min_ev so runs don't overwrite each other
    out_path = args.out or f"data/model_params/edge_engine_backtest_ncaab_{int(args.season)}_minev_{str(args.min_ev).replace('.', 'p')}.json"
    out_path = os.path.join(REPO_ROOT, out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    print(f"wrote: {out_path}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
