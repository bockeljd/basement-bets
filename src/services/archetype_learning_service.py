"""Closed-loop self-learning calibration & archetype ROI feedback for NCAAM.

Aggregates settled `model_predictions` + `game_results` into realized win rates,
ROI per unit, scoring bias, and Bayesian-shrunk archetype bins persisted to
`model_params_store` (`adaptive_learning_ncaam`) after every grading sweep.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.utils.model_performance import norm_outcome, roi_per_unit
from src.utils.ncaam_season import current_ncaam_season_short, season_start_date_for_game

ADAPTIVE_LEARNING_PARAM_KEY = "adaptive_learning_ncaam"


def classify_spread_bucket(line: Optional[float]) -> str:
    """Bucket a point spread line into ROI-relevant spread regimes."""
    try:
        if line is None:
            return "unknown"
        val = abs(float(line))
    except Exception:
        return "unknown"
    if val < 6.0:
        return "under_6"
    if val < 14.0:
        return "mid_6_14"
    if val < 22.0:
        return "blowout_14_22"
    return "blowout_22_plus"


def classify_edge_bucket(ev_per_unit: Optional[float]) -> str:
    """Bucket projected EV into selective calibration bands."""
    try:
        ev = float(ev_per_unit or 0.0)
        if abs(ev) > 1.5:
            ev /= 100.0
    except Exception:
        ev = 0.0
    if ev < 0.05:
        return "2_to_5"
    if ev < 0.08:
        return "5_to_8"
    if ev < 0.12:
        return "8_to_12"
    return "12_plus"


def _archetype_spread_band(line: Optional[float]) -> str:
    """Match NCAAMMarketFirstModelV2._spread_bucket ('close'|'mid'|'big')."""
    try:
        v = abs(float(line or 0.0))
    except Exception:
        return "mid"
    if v <= 3.0:
        return "close"
    if v <= 7.0:
        return "mid"
    return "big"


def _infer_side(row: Dict[str, Any], market: str) -> str:
    side_raw = str(row.get("side") or "").strip().lower()
    if market in ("SPREAD", "MONEYLINE"):
        if side_raw in ("home", "away"):
            return side_raw
        pick = str(row.get("pick") or row.get("selection") or "").strip().lower()
        home = str(row.get("home_team") or "").strip().lower()
        away = str(row.get("away_team") or "").strip().lower()
        if home and (pick == home or pick.startswith(home)):
            return "home"
        if away and (pick == away or pick.startswith(away)):
            return "away"
        return "home"
    if market == "TOTAL":
        if side_raw in ("over", "under"):
            return side_raw
        txt = f"{row.get('pick') or ''} {row.get('selection') or ''}".strip().upper()
        return "under" if "UNDER" in txt else "over"
    return "other"


def _init_acc() -> Dict[str, Any]:
    return {"n": 0, "wins": 0, "losses": 0, "pushes": 0, "rois": []}


def _add_acc(acc: Dict[str, Any], outcome: str, roi: float) -> None:
    acc["n"] += 1
    if outcome == "WON":
        acc["wins"] += 1
    elif outcome == "LOST":
        acc["losses"] += 1
    elif outcome == "PUSH":
        acc["pushes"] += 1
    acc["rois"].append(float(roi))


def _finalize_acc(acc: Dict[str, Any]) -> Dict[str, Any]:
    n = int(acc["n"])
    decided = acc["wins"] + acc["losses"]
    rois = acc["rois"]
    mean_roi = (sum(rois) / n) if n > 0 else 0.0
    if n > 1:
        var = sum((x - mean_roi) ** 2 for x in rois) / float(n - 1)
        sd = math.sqrt(max(0.0, var))
    else:
        sd = 0.95
    return {
        "n": n,
        "wins": int(acc["wins"]),
        "losses": int(acc["losses"]),
        "pushes": int(acc["pushes"]),
        "win_rate": round((acc["wins"] / decided), 4) if decided > 0 else 0.0,
        "roi_per_unit": round(mean_roi, 4),
        "sd": round(sd, 4),
    }


def _compute_ev_bump_from_roi(n: int, mean_roi: float, min_n: int = 10) -> float:
    """Map realized ROI to a bounded EV gate delta [-0.003, +0.015]."""
    if n < min_n:
        return 0.0
    conf = min(1.0, float(n) / 40.0)
    if mean_roi < -0.02:
        raw = min(0.015, abs(mean_roi + 0.02) * 0.14 * conf)
        return round(raw, 4)
    if mean_roi > 0.04:
        raw = -min(0.003, (mean_roi - 0.04) * 0.03 * conf)
        return round(raw, 4)
    return 0.0


def fit_adaptive_learning_from_rows(
    rows: List[Dict[str, Any]],
    baseline_bins: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute realized ROI metrics, Bayesian-shrunk archetype bins, and model adjustments."""
    by_market_side: Dict[str, Dict[str, Any]] = {}
    by_spread_bucket: Dict[str, Dict[str, Any]] = {}
    by_edge_bucket: Dict[str, Dict[str, Any]] = {}
    home_fav_7pt_acc = _init_acc()
    archetype_accs: Dict[str, Dict[str, Any]] = {}
    total_errors: List[float] = []

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        outcome = norm_outcome(row.get("outcome") or row.get("graded_result"))
        if outcome not in ("WON", "LOST", "PUSH"):
            continue

        market = str(row.get("market_type") or row.get("market") or "").strip().upper()
        if market in ("ML", "H2H"):
            market = "MONEYLINE"
        if market not in ("SPREAD", "TOTAL", "MONEYLINE"):
            continue

        price = row.get("bet_price") if row.get("bet_price") is not None else row.get("price")
        roi = float(roi_per_unit(outcome, price))
        side = _infer_side(row, market)
        ms_key = f"{market}:{side}"

        _add_acc(by_market_side.setdefault(ms_key, _init_acc()), outcome, roi)

        ev_val = row.get("ev_per_unit") if row.get("ev_per_unit") is not None else row.get("ev")
        edge_bucket = classify_edge_bucket(ev_val)
        _add_acc(by_edge_bucket.setdefault(edge_bucket, _init_acc()), outcome, roi)

        bet_line = row.get("bet_line") if row.get("bet_line") is not None else row.get("line")
        if market == "SPREAD":
            sb_roi = classify_spread_bucket(bet_line)
            if sb_roi != "unknown":
                _add_acc(by_spread_bucket.setdefault(sb_roi, _init_acc()), outcome, roi)

        if market == "MONEYLINE" and side == "home":
            try:
                p_int = int(price) if price is not None else 0
                if -380 <= p_int <= -160:
                    _add_acc(home_fav_7pt_acc, outcome, roi)
            except Exception:
                pass

        # Action Network compatible key: MARKET:side:edge_int:spread_band
        try:
            edge_pts_raw = abs(float(row.get("edge_points") or 0.0))
        except Exception:
            edge_pts_raw = 0.0
        edge_int = int(round(min(10.0, max(0.0, edge_pts_raw))))
        sb_arch = "na" if market == "TOTAL" else _archetype_spread_band(bet_line)
        arch_key = f"{market}:{side}:{edge_int}:{sb_arch}"
        _add_acc(archetype_accs.setdefault(arch_key, _init_acc()), outcome, roi)

        if market == "TOTAL":
            try:
                hs = row.get("home_score")
                as_ = row.get("away_score")
                mu_f = row.get("mu_final")
                if hs is not None and as_ is not None and mu_f is not None:
                    actual_tot = float(hs) + float(as_)
                    if actual_tot > 40.0:
                        err = actual_tot - float(mu_f)
                        if abs(err) <= 45.0:
                            total_errors.append(err)
            except Exception:
                pass

    ms_summary = {k: _finalize_acc(v) for k, v in sorted(by_market_side.items())}
    sb_summary = {k: _finalize_acc(v) for k, v in sorted(by_spread_bucket.items())}
    eb_summary = {k: _finalize_acc(v) for k, v in sorted(by_edge_bucket.items())}

    # Shrink empirical archetype bins toward Action Network baseline priors (w = n / (n + 35))
    merged_bins: Dict[str, Dict[str, Any]] = {}
    base_bins = baseline_bins if isinstance(baseline_bins, dict) else {}
    for key, base_val in base_bins.items():
        if isinstance(base_val, dict):
            merged_bins[key] = dict(base_val)

    for key, acc in archetype_accs.items():
        emp = _finalize_acc(acc)
        n_emp = emp["n"]
        if n_emp <= 0:
            continue
        prior = base_bins.get(key) if isinstance(base_bins.get(key), dict) else None
        if prior and int(prior.get("n") or 0) > 0:
            w = float(n_emp) / float(n_emp + 35.0)
            p_mean = float(prior.get("mean") or 0.0)
            p_sd = float(prior.get("sd") or 0.95)
            p_n = int(prior.get("n") or 0)
            merged_bins[key] = {
                "n": max(p_n, n_emp),
                "mean": round((1.0 - w) * p_mean + w * emp["roi_per_unit"], 6),
                "sd": round((1.0 - w) * p_sd + w * emp["sd"], 6),
                "empirical_n": n_emp,
                "empirical_mean": emp["roi_per_unit"],
            }
        else:
            merged_bins[key] = {
                "n": n_emp,
                "mean": emp["roi_per_unit"],
                "sd": emp["sd"],
                "empirical_n": n_emp,
                "empirical_mean": emp["roi_per_unit"],
            }

    # Shrink total scoring bias (positive means games scored higher than mu_final)
    n_tot = len(total_errors)
    raw_bias = (sum(total_errors) / float(n_tot)) if n_tot > 0 else 0.0
    damped_bias = (float(n_tot) / float(n_tot + 20.0)) * raw_bias
    total_bias_pts = round(max(-2.0, min(2.0, damped_bias)), 3)

    # Spread bucket EV bumps (default +0.012 prior on mid_6_14 when sample is thin)
    spread_bucket_ev_bump: Dict[str, float] = {
        "under_6": 0.0,
        "mid_6_14": 0.012,
        "blowout_14_22": 0.005,
        "blowout_22_plus": 0.0,
    }
    for sb_key, st in sb_summary.items():
        if st["n"] >= 10:
            spread_bucket_ev_bump[sb_key] = _compute_ev_bump_from_roi(st["n"], st["roi_per_unit"], min_n=10)

    market_side_ev_bump: Dict[str, float] = {}
    for ms_key, st in ms_summary.items():
        bump = _compute_ev_bump_from_roi(st["n"], st["roi_per_unit"], min_n=12)
        if bump != 0.0:
            market_side_ev_bump[ms_key] = bump

    total_n = sum(v["n"] for v in ms_summary.values())
    return {
        "league": "NCAAM",
        "season": current_ncaam_season_short(),
        "season_start": season_start_date_for_game(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_graded": total_n,
        "by_market_side": ms_summary,
        "by_spread_bucket": sb_summary,
        "by_edge_bucket": eb_summary,
        "by_home_fav_7pt_ml": _finalize_acc(home_fav_7pt_acc),
        "learned_adjustments": {
            "total_bias_pts": total_bias_pts,
            "total_bias_sample": n_tot,
            "spread_bucket_ev_bump": spread_bucket_ev_bump,
            "market_side_ev_bump": market_side_ev_bump,
        },
        "bins": merged_bins,
    }


def rebuild_adaptive_model_learning(
    days: int = 180,
    league: str = "NCAAM",
    persist: bool = True,
) -> Dict[str, Any]:
    """Rebuild adaptive learning parameters from settled DB predictions and persist to model_params_store."""
    if os.getenv("REQUIRE_DATABASE") == "0":
        return {}

    from src.database import _exec, get_db_connection, upsert_model_param
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2

    lg = str(league or "NCAAM").upper().strip()
    season_start = season_start_date_for_game()
    params: Dict[str, Any] = {
        "days": f"{int(days)} days",
        "league": lg,
        "season_start": f"{str(season_start)[:10]}T00:00:00+00:00",
    }

    q = """
    SELECT
      m.market_type,
      m.pick,
      m.selection,
      m.bet_line,
      m.bet_price,
      m.price,
      m.ev_per_unit,
      m.win_prob,
      m.edge_points,
      m.mu_final,
      m.outcome,
      e.home_team,
      e.away_team,
      gr.home_score,
      gr.away_score
    FROM model_predictions m
    JOIN events e ON m.event_id = e.id
    LEFT JOIN game_results gr ON gr.event_id = e.id AND COALESCE(gr.final, FALSE) = TRUE
    WHERE UPPER(COALESCE(e.league, 'NCAAM')) = :league
      AND m.analyzed_at >= NOW() - INTERVAL :days
      AND COALESCE(e.start_time, m.analyzed_at) >= :season_start
      AND UPPER(COALESCE(m.outcome, '')) IN ('WON', 'WIN', 'W', 'LOST', 'LOSS', 'L', 'PUSH', 'P')
      AND UPPER(COALESCE(m.pick, '')) NOT IN ('', 'NONE', 'NO BET', 'PASS')
    """
    with get_db_connection() as conn:
        rows = [dict(r) for r in _exec(conn, q, params).fetchall()]

    base_model = NCAAMMarketFirstModelV2()
    baseline_bins = (base_model._load_action_network_stats() or {}).get("bins") or {}
    payload = fit_adaptive_learning_from_rows(rows, baseline_bins=baseline_bins)

    if persist:
        upsert_model_param(ADAPTIVE_LEARNING_PARAM_KEY, payload)

    return payload


def load_adaptive_model_learning() -> Dict[str, Any]:
    """Load persisted adaptive learning state from DB model_params_store (empty dict offline)."""
    if os.getenv("REQUIRE_DATABASE") == "0":
        return {}
    try:
        from src.database import get_model_param

        data = get_model_param(ADAPTIVE_LEARNING_PARAM_KEY)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
