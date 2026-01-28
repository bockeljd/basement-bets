"""NCAAB Edge Engine (Phase A) — training + on-demand recommendations.

Designed to be callable from FastAPI (Vercel) and from local scripts.

Uses:
- historical_games_action_network for completed games (training)
- events + odds_snapshots for today's slate (recommendations)
- ncaab_edge_engine_config_<season>.json artifact for learned thresholds/caps

Note: This keeps the implementation numpy-only (no sklearn/pandas).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.database import get_db_connection, _exec

# Reuse proven helpers from the walkforward script (kept numpy-only)
from scripts.backtest_ncaab_edge_engine_walkforward import (
    american_to_decimal,
    devig_two_sided,
    ev_per_unit,
    logit,
    sigmoid,
    confidence_from_ev,
    units_from_conf,
    bet_narrative,
    train_residual_logreg,
    standardize_fit,
    standardize_apply,
    build_team_mapper,
    compute_torvik_margin_total,
)


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_config(season_end_year: int) -> Dict[str, Any]:
    path = os.path.join(REPO_ROOT, 'data', 'model_params', f'ncaab_edge_engine_config_{season_end_year}.json')
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Missing config: {path}. Run sweep+config to generate it."
        )
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def train_models(season_end_year: int, steps: int = 400, lr: float = 0.05, l2: float = 0.5) -> Dict[str, Dict[str, Any]]:
    """Train residual models on completed NCAAB games for the season.

    Returns dict keyed by market: SPREAD/TOTAL/ML.
    """

    q = """
    WITH latest AS (
      SELECT game_id, MAX(date_scraped) AS max_scraped
      FROM historical_games_action_network
      WHERE sport='ncaab'
        AND season_end_year=%(season)s
        AND status='complete'
        AND home_score IS NOT NULL AND away_score IS NOT NULL
        AND home_spread IS NOT NULL AND total_score IS NOT NULL
      GROUP BY game_id
    )
    SELECT h.*
    FROM historical_games_action_network h
    JOIN latest l
      ON l.game_id=h.game_id AND l.max_scraped=h.date_scraped
    WHERE h.sport='ncaab'
    ORDER BY h.start_time ASC
    """

    with get_db_connection() as conn:
        rows = _exec(conn, q, {"season": season_end_year}).fetchall()
        map_team = build_team_mapper(conn)
        cache: dict = {}

        buckets = {"SPREAD": [], "TOTAL": [], "ML": []}

        for r in rows:
            st = r['start_time']
            date_key = st.strftime('%Y%m%d') if st else None

            home = r['home_team']
            away = r['away_team']
            home_bt = map_team(home)
            away_bt = map_team(away)
            tv_margin, tv_total = compute_torvik_margin_total(conn, cache, home_bt, away_bt, date_key)

            home_score = int(r['home_score'] or 0)
            away_score = int(r['away_score'] or 0)
            actual_margin = home_score - away_score
            actual_total = home_score + away_score

            # SPREAD (home)
            if r['home_spread_odds'] is not None and r['away_spread_odds'] is not None:
                p_home, _ = devig_two_sided(float(r['home_spread_odds']), float(r['away_spread_odds']))
                if p_home is not None:
                    y = 1.0 if (actual_margin + float(r['home_spread'])) > 0 else 0.0
                    X = np.array([
                        float(r['home_spread']),
                        0.0,  # movement (not in deduped training)
                        float(tv_margin),
                        float((-float(r['home_spread'])) - float(tv_margin)),
                        float(r['total_score']),
                        float(tv_total - float(r['total_score'])),
                        float((r['home_spread_money_pct'] or 0.0) - (r['home_spread_ticket_pct'] or 0.0)),
                    ], dtype=np.float64)
                    buckets['SPREAD'].append((X, y, float(p_home)))

            # TOTAL (over)
            if r['over_odds'] is not None and r['under_odds'] is not None:
                p_over, _ = devig_two_sided(float(r['over_odds']), float(r['under_odds']))
                if p_over is not None:
                    y = 1.0 if (actual_total > float(r['total_score'])) else 0.0
                    X = np.array([
                        float(r['total_score']),
                        0.0,  # movement
                        float(tv_total),
                        float(tv_total - float(r['total_score'])),
                        float(tv_margin),
                        float((r['over_money_pct'] or 0.0) - (r['over_ticket_pct'] or 0.0)),
                    ], dtype=np.float64)
                    buckets['TOTAL'].append((X, y, float(p_over)))

            # ML (home)
            if r['home_money_line'] is not None and r['away_money_line'] is not None:
                p_home, _ = devig_two_sided(float(r['home_money_line']), float(r['away_money_line']))
                if p_home is not None:
                    y = 1.0 if (actual_margin > 0) else 0.0
                    X = np.array([
                        float(r['home_money_line']),
                        float(r['home_spread']),
                        float(tv_margin),
                        float(tv_total),
                        float((r['home_ml_money_pct'] or 0.0) - (r['home_ml_ticket_pct'] or 0.0)),
                    ], dtype=np.float64)
                    buckets['ML'].append((X, y, float(p_home)))

        models: Dict[str, Dict[str, Any]] = {}
        for kind, rows_k in buckets.items():
            if len(rows_k) < 300:
                continue

            Xtr = np.stack([a[0] for a in rows_k], axis=0)
            ytr = np.array([a[1] for a in rows_k], dtype=np.float64)
            off = np.array([logit(a[2]) for a in rows_k], dtype=np.float64)

            Ztr, mu, sd = standardize_fit(Xtr)
            w, b = train_residual_logreg(Ztr, ytr, off, l2=float(l2), lr=float(lr), steps=int(steps))
            models[kind] = {"w": w, "b": b, "mu": mu, "sd": sd}

    return models


def recommend_for_date(
    date_et: str,
    season_end_year: int = 2026,
    models: Optional[Dict[str, Dict[str, Any]]] = None,
    steps: int = 400,
    lr: float = 0.05,
    l2: float = 0.5,
) -> Dict[str, Any]:
    """Recommend bets for a given ET date using latest odds_snapshots.

    Returns payload with picks + narratives.
    """

    cfg = load_config(season_end_year)
    min_ev = float(cfg['learned']['min_ev'])
    max_units_day = int(cfg['constraints']['max_units_day'])
    max_units_game = int(cfg['constraints']['max_units_game'])

    if models is None:
        models = train_models(season_end_year, steps=steps, lr=lr, l2=l2)

    with get_db_connection() as conn:
        evs = _exec(
            conn,
            """
            SELECT id, home_team, away_team, start_time
            FROM events
            WHERE league='NCAAM'
              AND DATE(start_time AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')=%s
            ORDER BY start_time ASC
            """,
            (date_et,),
        ).fetchall()

        if not evs:
            return {
                "generated_at": datetime.now().isoformat(),
                "date": date_et,
                "season_end_year": season_end_year,
                "config": cfg,
                "picks": [],
                "note": "No NCAAM events found for date",
            }

        map_team = build_team_mapper(conn)
        cache: dict = {}

        def latest(eid: str, market_type: str, side: str):
            return _exec(
                conn,
                """
                SELECT line_value, price
                FROM odds_snapshots
                WHERE event_id=%s AND market_type=%s AND side=%s
                ORDER BY captured_at DESC
                LIMIT 1
                """,
                (eid, market_type, side),
            ).fetchone()

        candidates = []

        for ev in evs:
            eid = ev['id']
            home = ev['home_team']
            away = ev['away_team']
            st = ev['start_time']
            date_key = st.strftime('%Y%m%d') if st else None

            home_bt = map_team(home)
            away_bt = map_team(away)
            tv_margin, tv_total = compute_torvik_margin_total(conn, cache, home_bt, away_bt, date_key)

            sp_h = latest(eid, 'SPREAD', 'HOME')
            sp_a = latest(eid, 'SPREAD', 'AWAY')
            tot_o = latest(eid, 'TOTAL', 'OVER')
            tot_u = latest(eid, 'TOTAL', 'UNDER')
            ml_h = latest(eid, 'MONEYLINE', 'HOME')
            ml_a = latest(eid, 'MONEYLINE', 'AWAY')

            # We build a minimal object for bet_narrative
            from types import SimpleNamespace

            base = {
                "game_id": eid,
                "date_et": date_et,
                "home_team": home,
                "away_team": away,
                "open_home_spread": float(sp_h['line_value']) if sp_h and sp_h['line_value'] is not None else 0.0,
                "open_total": float(tot_o['line_value']) if tot_o and tot_o['line_value'] is not None else 0.0,
                "home_spread_money_pct": None,
                "home_spread_ticket_pct": None,
                "over_money_pct": None,
                "over_ticket_pct": None,
                "home_ml_money_pct": None,
                "home_ml_ticket_pct": None,
                "torvik_margin": float(tv_margin),
                "torvik_total": float(tv_total),
            }

            # SPREAD home-side
            if 'SPREAD' in models and sp_h and sp_a and sp_h['line_value'] is not None and sp_h['price'] is not None and sp_a['price'] is not None:
                p_home, _ = devig_two_sided(float(sp_h['price']), float(sp_a['price']))
                if p_home is not None:
                    X = np.array([
                        float(sp_h['line_value']),
                        0.0,
                        float(tv_margin),
                        float((-float(sp_h['line_value'])) - float(tv_margin)),
                        float(tot_o['line_value']) if tot_o and tot_o['line_value'] is not None else 0.0,
                        float(tv_total - (float(tot_o['line_value']) if tot_o and tot_o['line_value'] is not None else 0.0)),
                        0.0,
                    ], dtype=np.float64)
                    m = models['SPREAD']
                    Z = standardize_apply(X.reshape(1, -1), m['mu'], m['sd'])
                    z = logit(p_home) + float((Z @ m['w'])[0] + m['b'])
                    p_model = float(sigmoid(np.array([z]))[0])
                    evu = ev_per_unit(p_model, float(sp_h['price']))
                    if evu is not None and evu >= min_ev:
                        conf = confidence_from_ev(evu, p_model, p_home)
                        units = units_from_conf(conf)
                        if units > 0:
                            g = SimpleNamespace(
                                **base,
                                close_home_spread=float(sp_h['line_value']),
                                close_total=float(tot_o['line_value']) if tot_o and tot_o['line_value'] is not None else 0.0,
                                close_home_spread_odds=float(sp_h['price']),
                                close_over_odds=float(tot_o['price']) if tot_o and tot_o['price'] is not None else None,
                                close_home_ml=float(ml_h['price']) if ml_h and ml_h['price'] is not None else None,
                            )
                            candidates.append({"units": units, "score": evu * units, "narr": bet_narrative('SPREAD', g, p_model, p_home, evu, conf)})

            # TOTAL over-side
            if 'TOTAL' in models and tot_o and tot_u and tot_o['line_value'] is not None and tot_o['price'] is not None and tot_u['price'] is not None:
                p_over, _ = devig_two_sided(float(tot_o['price']), float(tot_u['price']))
                if p_over is not None:
                    X = np.array([
                        float(tot_o['line_value']),
                        0.0,
                        float(tv_total),
                        float(tv_total - float(tot_o['line_value'])),
                        float(tv_margin),
                        0.0,
                    ], dtype=np.float64)
                    m = models['TOTAL']
                    Z = standardize_apply(X.reshape(1, -1), m['mu'], m['sd'])
                    z = logit(p_over) + float((Z @ m['w'])[0] + m['b'])
                    p_model = float(sigmoid(np.array([z]))[0])
                    evu = ev_per_unit(p_model, float(tot_o['price']))
                    if evu is not None and evu >= min_ev:
                        conf = confidence_from_ev(evu, p_model, p_over)
                        units = units_from_conf(conf)
                        if units > 0:
                            g = SimpleNamespace(
                                **base,
                                close_home_spread=float(sp_h['line_value']) if sp_h and sp_h['line_value'] is not None else 0.0,
                                close_total=float(tot_o['line_value']),
                                close_home_spread_odds=float(sp_h['price']) if sp_h and sp_h['price'] is not None else None,
                                close_over_odds=float(tot_o['price']),
                                close_home_ml=float(ml_h['price']) if ml_h and ml_h['price'] is not None else None,
                            )
                            candidates.append({"units": units, "score": evu * units, "narr": bet_narrative('TOTAL', g, p_model, p_over, evu, conf)})

            # ML home-side
            if 'ML' in models and ml_h and ml_a and ml_h['price'] is not None and ml_a['price'] is not None:
                p_home, _ = devig_two_sided(float(ml_h['price']), float(ml_a['price']))
                if p_home is not None:
                    X = np.array([
                        float(ml_h['price']),
                        float(sp_h['line_value']) if sp_h and sp_h['line_value'] is not None else 0.0,
                        float(tv_margin),
                        float(tv_total),
                        0.0,
                    ], dtype=np.float64)
                    m = models['ML']
                    Z = standardize_apply(X.reshape(1, -1), m['mu'], m['sd'])
                    z = logit(p_home) + float((Z @ m['w'])[0] + m['b'])
                    p_model = float(sigmoid(np.array([z]))[0])
                    evu = ev_per_unit(p_model, float(ml_h['price']))
                    if evu is not None and evu >= min_ev:
                        conf = confidence_from_ev(evu, p_model, p_home)
                        units = units_from_conf(conf)
                        if units > 0:
                            g = SimpleNamespace(
                                **base,
                                close_home_spread=float(sp_h['line_value']) if sp_h and sp_h['line_value'] is not None else 0.0,
                                close_total=float(tot_o['line_value']) if tot_o and tot_o['line_value'] is not None else 0.0,
                                close_home_spread_odds=float(sp_h['price']) if sp_h and sp_h['price'] is not None else None,
                                close_over_odds=float(tot_o['price']) if tot_o and tot_o['price'] is not None else None,
                                close_home_ml=float(ml_h['price']),
                            )
                            candidates.append({"units": units, "score": evu * units, "narr": bet_narrative('ML', g, p_model, p_home, evu, conf)})

        candidates.sort(key=lambda c: c['score'], reverse=True)

        units_left = max_units_day
        units_by_game: Dict[str, int] = {}
        picks: List[Dict[str, Any]] = []

        for c in candidates:
            if units_left <= 0:
                break
            gid = c['narr']['game_id']
            used = units_by_game.get(gid, 0)
            if used >= max_units_game:
                continue
            u = min(int(c['units']), units_left, max_units_game - used)
            if u <= 0:
                continue
            units_left -= u
            units_by_game[gid] = used + u
            c['narr']['units'] = u
            picks.append(c['narr'])

        return {
            "generated_at": datetime.now().isoformat(),
            "date": date_et,
            "season_end_year": season_end_year,
            "config": cfg,
            "picks": picks,
        }
