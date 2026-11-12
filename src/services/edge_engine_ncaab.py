"""NCAAB Edge Engine — serverless-safe recommendations.

This module backs /api/edge/ncaab/recommendations.

IMPORTANT (Vercel/serverless):
- Do NOT depend on numpy or other heavy scientific packages.
- Load pre-trained model params from JSON artifacts in data/model_params.

We keep the same model logic as the walk-forward backtest:
    logit(p_model) = logit(p_market_no_vig) + (Z @ w + b)
where Z standardizes features using training mean/std.

Artifacts:
- data/model_params/ncaab_edge_engine_config_<season>.json
- data/model_params/ncaab_edge_model_season_<season>.json
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from src.database import get_db_connection, _exec

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_PARAMS_DIR = os.path.join(SERVICE_DIR, 'model_params')

LEAGUE_AVG_EFF = 1.0  # Torvik features are already scaled; keep as 1.0 for legacy formula


# ----------------------------
# Odds + math (no numpy)
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
    if s <= 1e-12:
        return None, None
    return p1 / s, p2 / s


def logit(p: float) -> float:
    p = min(1 - 1e-9, max(1e-9, float(p)))
    return math.log(p / (1 - p))


def sigmoid(z: float) -> float:
    z = max(-50.0, min(50.0, float(z)))
    return 1.0 / (1.0 + math.exp(-z))


def ev_per_unit(p_win: float, american_odds: float) -> float | None:
    dec = american_to_decimal(american_odds)
    if dec is None:
        return None
    b = dec - 1.0
    return float(p_win) * b - (1.0 - float(p_win))


# ----------------------------
# Betting policy
# ----------------------------

def confidence_from_ev(ev: float, p_model: float, p_market: float) -> float:
    diff = abs(float(p_model) - float(p_market))
    c = 50.0 + 400.0 * float(ev) + 50.0 * diff
    return max(0.0, min(100.0, c))


def units_from_conf(conf: float) -> int:
    conf = float(conf or 0.0)
    if conf >= 85:
        return 3
    if conf >= 70:
        return 2
    if conf >= 55:
        return 1
    return 0


# ----------------------------
# Torvik feature helpers (copied from walkforward)
# ----------------------------

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
    from src.utils.ncaam_season import normalize_iso_date, season_start_date_for_game
    d_iso = normalize_iso_date(date_iso)
    season_start = season_start_date_for_game(d_iso)
    k = (team_text, d_iso)
    if k in cache:
        return cache[k]

    row = _exec(
        conn,
        """
        SELECT adj_off, adj_def, adj_tempo
        FROM bt_team_features_daily
        WHERE team_text=:t AND date >= :season_start AND date <= :d
        ORDER BY date DESC
        LIMIT 1
        """,
        {"t": team_text, "season_start": season_start, "d": d_iso},
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
# Model params loading
# ----------------------------

def load_config(season_end_year: Optional[int] = None) -> Dict[str, Any]:
    if season_end_year is None:
        from src.utils.ncaam_season import current_ncaam_season_end_year
        season_end_year = current_ncaam_season_end_year()
    candidates = [int(season_end_year)]
    if int(season_end_year) != 2026:
        candidates.append(2026)

    # Prefer bundled params (ships with serverless function), fallback to repo data/.
    for s in candidates:
        p1 = os.path.join(BUNDLED_PARAMS_DIR, f'ncaab_edge_engine_config_{s}.json')
        p2 = os.path.join(REPO_ROOT, 'data', 'model_params', f'ncaab_edge_engine_config_{s}.json')
        path = p1 if os.path.exists(p1) else p2
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)

    missing_path = os.path.join(REPO_ROOT, 'data', 'model_params', f'ncaab_edge_engine_config_{season_end_year}.json')
    raise FileNotFoundError(f"Missing config: {missing_path}. Run sweep+config to generate it.")


def load_models(season_end_year: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
    """Load pre-trained residual models from JSON.

    File schema: data/model_params/ncaab_edge_model_season_<season>.json
    Keys: spread/total/ml

    Serverless robustness:
    - If requested season artifact is missing, fall back to 2026 baseline.
    """
    if season_end_year is None:
        from src.utils.ncaam_season import current_ncaam_season_end_year
        season_end_year = current_ncaam_season_end_year()
    candidates = [int(season_end_year)]
    if int(season_end_year) != 2026:
        candidates.append(2026)

    path = None
    raw = None
    for s in candidates:
        # Prefer bundled params (ships with serverless function), fallback to repo data/.
        p1 = os.path.join(BUNDLED_PARAMS_DIR, f'ncaab_edge_model_season_{s}.json')
        p2 = os.path.join(REPO_ROOT, 'data', 'model_params', f'ncaab_edge_model_season_{s}.json')
        p = p1 if os.path.exists(p1) else p2
        if os.path.exists(p):
            path = p
            raw = json.loads(open(p, 'r', encoding='utf-8').read())
            break

    if raw is None or path is None:
        raise FileNotFoundError(f"Missing model params: {os.path.join(REPO_ROOT, 'data', 'model_params', f'ncaab_edge_model_season_{season_end_year}.json')}")

    models = (raw.get('params') or {}).get('models') or {}

    def norm_model(m: dict) -> dict:
        return {
            'mu': [float(x) for x in (m.get('feature_mean') or [])],
            'sd': [float(x) if float(x) != 0 else 1.0 for x in (m.get('feature_std') or [])],
            'w': [float(x) for x in (m.get('weights') or [])],
            'b': float(m.get('bias') or 0.0),
        }

    out: Dict[str, Dict[str, Any]] = {}
    if 'spread' in models:
        out['SPREAD'] = norm_model(models['spread'])
    if 'total' in models:
        out['TOTAL'] = norm_model(models['total'])
    if 'ml' in models:
        out['ML'] = norm_model(models['ml'])
    return out


def _dot(a: List[float], b: List[float]) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b))


def _standardize(x: List[float], mu: List[float], sd: List[float]) -> List[float]:
    out = []
    for i, xi in enumerate(x):
        m = mu[i] if i < len(mu) else 0.0
        s = sd[i] if i < len(sd) else 1.0
        if abs(s) < 1e-9:
            s = 1.0
        out.append((float(xi) - float(m)) / float(s))
    return out


def bet_narrative(kind: str, g: Any, p_model: float, p_market: float, ev: float, conf: float) -> dict:
    # Keep schema stable for UI.
    if kind == 'SPREAD':
        line = g.close_home_spread
        odds = g.close_home_spread_odds
        if line is not None and float(line) < 0:
            selection = f"{g.away_team} +{abs(float(line)):.1f}".replace('+.0', '').replace('.0', '')
        else:
            selection = f"{g.home_team} {float(line):+.1f}".replace('+.0', '').replace('.0', '') if line is not None else g.home_team
        win_cond = f"{selection} must cover"
        keys = [
            ("Torvik margin", g.torvik_margin),
            ("Line (close)", g.close_home_spread),
        ]
    elif kind == 'TOTAL':
        line = g.close_total
        odds = g.close_over_odds
        selection = f"OVER {float(line):.1f}".replace('.0', '') if line is not None else 'OVER'
        win_cond = f"Game total points must finish {selection}"
        keys = [
            ("Torvik total", g.torvik_total),
            ("Total (close)", g.close_total),
        ]
    else:
        line = None
        odds = g.close_home_ml
        selection = g.home_team
        win_cond = f"{selection} must win outright"
        keys = [
            ("Torvik margin", g.torvik_margin),
            ("Spread (close)", g.close_home_spread),
        ]

    drivers = []
    for k, v in keys:
        drivers.append(f"{k}: {v:+.2f}" if isinstance(v, (int, float)) else f"{k}: {v}")

    return {
        'game_id': g.game_id,
        'date': g.date_et,
        'match': f"{g.away_team} @ {g.home_team}",
        'bet_type': kind,
        'selection': selection,
        'line': line,
        'odds': odds,
        'p_market': round(float(p_market), 4),
        'p_model': round(float(p_model), 4),
        'ev_per_unit': round(float(ev), 4),
        'confidence': round(float(conf), 1),
        'why': drivers,
        'needs_to_happen': win_cond,
        'risks': ["Variance/late-game fouls", "Injuries/rotation changes"],
    }


def recommend_for_date(date_et: str, season_end_year: Optional[int] = None) -> Dict[str, Any]:
    if season_end_year is None:
        from src.utils.ncaam_season import current_ncaam_season_end_year
        season_end_year = current_ncaam_season_end_year()
    cfg = load_config(season_end_year)
    min_ev = float(cfg['learned']['min_ev'])
    max_units_day = int(cfg['constraints']['max_units_day'])
    max_units_game = int(cfg['constraints']['max_units_game'])

    models = load_models(season_end_year)

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
                'generated_at': datetime.now().isoformat(),
                'date': date_et,
                'season_end_year': season_end_year,
                'config': cfg,
                'picks': [],
                'note': 'No NCAAM events found for date',
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

        candidates: List[Dict[str, Any]] = []

        for r in evs:
            eid = r['id']
            home = r['home_team']
            away = r['away_team']
            st = r['start_time']
            date_key = None
            try:
                if st and hasattr(st, 'strftime'):
                    date_key = st.strftime('%Y%m%d')
            except Exception:
                date_key = None

            home_bt = map_team(home)
            away_bt = map_team(away)
            tv_margin, tv_total = compute_torvik_margin_total(conn, cache, home_bt, away_bt, date_key)

            base = {
                'game_id': eid,
                'date_et': date_et,
                'home_team': home,
                'away_team': away,
                'torvik_margin': float(tv_margin),
                'torvik_total': float(tv_total),
                'open_home_spread': None,
                'open_total': None,
            }

            sp_h = latest(eid, 'SPREAD', 'HOME')
            sp_a = latest(eid, 'SPREAD', 'AWAY')
            tot_o = latest(eid, 'TOTAL', 'OVER')
            tot_u = latest(eid, 'TOTAL', 'UNDER')
            ml_h = latest(eid, 'ML', 'HOME')
            ml_a = latest(eid, 'ML', 'AWAY')

            # SPREAD home-side features (matches trained model)
            if 'SPREAD' in models and sp_h and sp_a and sp_h['price'] is not None and sp_a['price'] is not None and sp_h['line_value'] is not None:
                p_home, _ = devig_two_sided(float(sp_h['price']), float(sp_a['price']))
                if p_home is not None:
                    line = float(sp_h['line_value'])
                    X = [
                        line,
                        0.0,
                        float(tv_margin),
                        float((-line) - float(tv_margin)),
                        float(tot_o['line_value']) if tot_o and tot_o['line_value'] is not None else 0.0,
                        float(float(tv_total) - float(tot_o['line_value'])) if tot_o and tot_o['line_value'] is not None else 0.0,
                        0.0,
                    ]
                    m = models['SPREAD']
                    Z = _standardize(X, m['mu'], m['sd'])
                    z = logit(p_home) + (_dot(Z, m['w']) + m['b'])
                    p_model = sigmoid(z)
                    evu = ev_per_unit(p_model, float(sp_h['price']))
                    if evu is not None and evu >= min_ev:
                        conf = confidence_from_ev(evu, p_model, p_home)
                        units = units_from_conf(conf)
                        if units > 0:
                            g = SimpleNamespace(
                                **base,
                                close_home_spread=line,
                                close_total=float(tot_o['line_value']) if tot_o and tot_o['line_value'] is not None else 0.0,
                                close_home_spread_odds=float(sp_h['price']),
                                close_over_odds=float(tot_o['price']) if tot_o and tot_o['price'] is not None else None,
                                close_home_ml=float(ml_h['price']) if ml_h and ml_h['price'] is not None else None,
                            )
                            candidates.append({'units': units, 'score': float(evu) * units, 'narr': bet_narrative('SPREAD', g, p_model, p_home, evu, conf)})

            # TOTAL over-side
            if 'TOTAL' in models and tot_o and tot_u and tot_o['price'] is not None and tot_u['price'] is not None and tot_o['line_value'] is not None:
                p_over, _ = devig_two_sided(float(tot_o['price']), float(tot_u['price']))
                if p_over is not None:
                    line = float(tot_o['line_value'])
                    X = [
                        line,
                        0.0,
                        float(tv_total),
                        float(float(tv_total) - line),
                        float(tv_margin),
                        0.0,
                    ]
                    m = models['TOTAL']
                    Z = _standardize(X, m['mu'], m['sd'])
                    z = logit(p_over) + (_dot(Z, m['w']) + m['b'])
                    p_model = sigmoid(z)
                    evu = ev_per_unit(p_model, float(tot_o['price']))
                    if evu is not None and evu >= min_ev:
                        conf = confidence_from_ev(evu, p_model, p_over)
                        units = units_from_conf(conf)
                        if units > 0:
                            g = SimpleNamespace(
                                **base,
                                close_home_spread=float(sp_h['line_value']) if sp_h and sp_h['line_value'] is not None else 0.0,
                                close_total=line,
                                close_home_spread_odds=float(sp_h['price']) if sp_h and sp_h['price'] is not None else None,
                                close_over_odds=float(tot_o['price']),
                                close_home_ml=float(ml_h['price']) if ml_h and ml_h['price'] is not None else None,
                            )
                            candidates.append({'units': units, 'score': float(evu) * units, 'narr': bet_narrative('TOTAL', g, p_model, p_over, evu, conf)})

            # ML home-side
            if 'ML' in models and ml_h and ml_a and ml_h['price'] is not None and ml_a['price'] is not None:
                p_home, _ = devig_two_sided(float(ml_h['price']), float(ml_a['price']))
                if p_home is not None:
                    X = [
                        float(ml_h['price']),
                        float(sp_h['line_value']) if sp_h and sp_h['line_value'] is not None else 0.0,
                        float(tv_margin),
                        float(tv_total),
                        0.0,
                    ]
                    m = models['ML']
                    Z = _standardize(X, m['mu'], m['sd'])
                    z = logit(p_home) + (_dot(Z, m['w']) + m['b'])
                    p_model = sigmoid(z)
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
                            candidates.append({'units': units, 'score': float(evu) * units, 'narr': bet_narrative('ML', g, p_model, p_home, evu, conf)})

        candidates.sort(key=lambda c: float(c.get('score') or 0), reverse=True)

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
            'generated_at': datetime.now().isoformat(),
            'date': date_et,
            'season_end_year': season_end_year,
            'config': cfg,
            'picks': picks,
        }
