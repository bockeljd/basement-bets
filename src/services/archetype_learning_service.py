"""Closed-loop self-learning calibration & archetype ROI feedback for NCAAM.

Aggregates settled `model_predictions` + `game_results` into realized win rates,
ROI per unit, scoring bias, and Bayesian-shrunk archetype bins persisted to
`model_params_store` (`adaptive_learning_ncaam`) after every grading sweep.
"""

from __future__ import annotations

import json
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


def classify_spread_role(market: str, side: str, bet_line: Any) -> Optional[str]:
    """Classify SPREAD pick into ('away_dog', 'home_dog', 'home_fav', 'away_fav')."""
    if str(market or "").strip().upper() != "SPREAD" or bet_line is None:
        return None
    s = str(side or "").strip().lower()
    if s not in ("home", "away"):
        return None
    try:
        line_val = float(bet_line)
    except Exception:
        return None
    if line_val > 0.0:
        return "away_dog" if s == "away" else "home_dog"
    if line_val < 0.0:
        return "away_fav" if s == "away" else "home_fav"
    return None


def classify_total_zone(market: str, side: str, bet_line: Any) -> Optional[str]:
    """Classify TOTAL pick by direction & scoring environment."""
    if str(market or "").strip().upper() != "TOTAL" or bet_line is None:
        return None
    s = str(side or "").strip().lower()
    if s not in ("over", "under"):
        return None
    try:
        tot_val = abs(float(bet_line))
    except Exception:
        return None
    if tot_val < 40.0:
        return None
    if tot_val < 140.0:
        zone = "low_<140"
    elif tot_val < 152.0:
        zone = "mid_140_152"
    else:
        zone = "high_152+"
    return f"{s}_{zone}"


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


def _safe_float_opt(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        v = float(val)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def fit_all_games_learning(slate_rows: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Learn full-slate scoring bias, realized sigma calibration, and feed accuracy
    across ALL completed lined games (`daily_top_picks` x `game_results`), not just published bets.
    """
    n_games = 0
    total_errors: List[float] = []
    spread_residuals: List[float] = []
    total_residuals: List[float] = []
    model_sigma_spreads: List[float] = []
    model_sigma_totals: List[float] = []

    feed_keys = [
        ("market", "current_spread_home"),
        ("blended_fair", "fair_spread_home"),
        ("torvik", "torvik_spread_home"),
        ("kenpom", "kenpom_spread_home"),
        ("haslametrics", "hasla_spread_home"),
    ]
    feed_abs_err: Dict[str, List[float]] = {name: [] for name, _ in feed_keys}
    feed_ats: Dict[str, List[int]] = {name: [0, 0] for name, _ in feed_keys if name != "market"}
    spread_buckets: Dict[str, List[int]] = {
        "under_6": [0, 0],
        "mid_6_14": [0, 0],
        "blowout_14_22": [0, 0],
        "blowout_22_plus": [0, 0],
    }
    totals_dir: Dict[str, List[int]] = {"over": [0, 0], "under": [0, 0]}

    for row in slate_rows or []:
        if not isinstance(row, dict):
            continue
        hs = _safe_float_opt(row.get("home_score"))
        as_ = _safe_float_opt(row.get("away_score"))
        if hs is None or as_ is None:
            continue
        actual_tot = hs + as_
        if actual_tot <= 40.0:
            continue
        ctx = row.get("context_json") if "context_json" in row else row.get("context")
        if isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except Exception:
                ctx = None
        if not isinstance(ctx, dict) or not ctx:
            continue

        actual_home_sp = -(hs - as_)
        mkt_sp = _safe_float_opt(ctx.get("current_spread_home"))
        fair_sp = _safe_float_opt(ctx.get("fair_spread_home"))
        mkt_tot = _safe_float_opt(ctx.get("current_total"))
        fair_tot = _safe_float_opt(ctx.get("fair_total"))
        if mkt_sp is None and mkt_tot is None:
            continue
        n_games += 1

        if mkt_sp is not None:
            sp_res = actual_home_sp - mkt_sp
            if abs(sp_res) <= 55.0:
                spread_residuals.append(sp_res)
                sig_sp = _safe_float_opt(ctx.get("sigma_spread"))
                if sig_sp is not None and 5.0 <= sig_sp <= 35.0:
                    model_sigma_spreads.append(sig_sp)

            for fname, fkey in feed_keys:
                fval = _safe_float_opt(ctx.get(fkey))
                if fval is None:
                    continue
                feed_abs_err[fname].append(abs(actual_home_sp - fval))
                if fname != "market" and abs(fval - mkt_sp) >= 0.5 and abs(actual_home_sp - mkt_sp) > 1e-9:
                    won = (actual_home_sp < mkt_sp) if (fval < mkt_sp) else (actual_home_sp > mkt_sp)
                    feed_ats[fname][0 if won else 1] += 1

            if fair_sp is not None and abs(fair_sp - mkt_sp) >= 0.5 and abs(actual_home_sp - mkt_sp) > 1e-9:
                won = (actual_home_sp < mkt_sp) if (fair_sp < mkt_sp) else (actual_home_sp > mkt_sp)
                sb = classify_spread_bucket(mkt_sp)
                if sb in spread_buckets:
                    spread_buckets[sb][0 if won else 1] += 1

        if mkt_tot is not None:
            tot_res = actual_tot - mkt_tot
            if abs(tot_res) <= 55.0:
                total_residuals.append(tot_res)
                sig_tot = _safe_float_opt(ctx.get("sigma_total"))
                if sig_tot is not None and 7.0 <= sig_tot <= 40.0:
                    model_sigma_totals.append(sig_tot)

        if fair_tot is not None:
            err = actual_tot - fair_tot
            if abs(err) <= 45.0:
                total_errors.append(err)
            if mkt_tot is not None and abs(fair_tot - mkt_tot) >= 0.5 and abs(actual_tot - mkt_tot) > 1e-9:
                if fair_tot > mkt_tot:
                    totals_dir["over"][0 if actual_tot > mkt_tot else 1] += 1
                else:
                    totals_dir["under"][0 if actual_tot < mkt_tot else 1] += 1

    # Shrink full-slate total scoring bias (positive = games scoring hotter than fair_total)
    n_tot = len(total_errors)
    raw_bias = (sum(total_errors) / float(n_tot)) if n_tot > 0 else 0.0
    damped_bias = (float(n_tot) / float(n_tot + 25.0)) * raw_bias
    total_bias_pts = round(max(-2.5, min(2.5, damped_bias)), 3)

    def _sd(xs: List[float]) -> Optional[float]:
        if len(xs) < 2:
            return None
        m = sum(xs) / float(len(xs))
        return math.sqrt(sum((x - m) ** 2 for x in xs) / float(len(xs) - 1))

    sp_real_sd = _sd(spread_residuals)
    sp_mod_avg = (sum(model_sigma_spreads) / float(len(model_sigma_spreads))) if model_sigma_spreads else None
    tot_real_sd = _sd(total_residuals)
    tot_mod_avg = (sum(model_sigma_totals) / float(len(model_sigma_totals))) if model_sigma_totals else None

    def _sigma_scale(real_sd: Optional[float], mod_avg: Optional[float], n_obs: int) -> float:
        if real_sd is None or mod_avg is None or mod_avg <= 0.0 or n_obs < 40:
            return 1.0
        raw_ratio = real_sd / mod_avg
        # Smooth shrinkage toward 1.0 (50% weight at n=80) and strict safety bounds [0.88, 1.12]
        w = min(0.60, float(n_obs) / float(n_obs + 80.0))
        scaled = 1.0 + w * (raw_ratio - 1.0)
        return round(max(0.88, min(1.12, scaled)), 4)

    spread_sigma_scale = _sigma_scale(sp_real_sd, sp_mod_avg, len(model_sigma_spreads))
    total_sigma_scale = _sigma_scale(tot_real_sd, tot_mod_avg, len(model_sigma_totals))

    feed_accuracy: Dict[str, Any] = {}
    for fname, _ in feed_keys:
        errs = feed_abs_err[fname]
        if not errs:
            continue
        entry: Dict[str, Any] = {
            "n": len(errs),
            "mae": round(sum(errs) / float(len(errs)), 3),
        }
        if fname in feed_ats:
            w, l = feed_ats[fname]
            entry["ats_wins"] = w
            entry["ats_losses"] = l
            entry["ats_win_rate"] = round(w / float(w + l), 4) if (w + l) > 0 else None
        feed_accuracy[fname] = entry

    def _fmt_wl(pair: List[int]) -> Dict[str, Any]:
        w, l = pair
        return {
            "wins": w,
            "losses": l,
            "win_rate": round(w / float(w + l), 4) if (w + l) > 0 else None,
        }

    return {
        "n_games": n_games,
        "total_bias_pts": total_bias_pts,
        "total_bias_raw_pts": round(raw_bias, 3),
        "total_bias_sample": n_tot,
        "sigma_calibration": {
            "spread_n": len(model_sigma_spreads),
            "spread_realized_sd": round(sp_real_sd, 3) if sp_real_sd is not None else None,
            "spread_model_avg_sigma": round(sp_mod_avg, 3) if sp_mod_avg is not None else None,
            "spread_sigma_scale": spread_sigma_scale,
            "total_n": len(model_sigma_totals),
            "total_realized_sd": round(tot_real_sd, 3) if tot_real_sd is not None else None,
            "total_model_avg_sigma": round(tot_mod_avg, 3) if tot_mod_avg is not None else None,
            "total_sigma_scale": total_sigma_scale,
        },
        "feed_accuracy": feed_accuracy,
        "spread_buckets": {k: _fmt_wl(v) for k, v in spread_buckets.items()},
        "totals_direction": {k: _fmt_wl(v) for k, v in totals_dir.items()},
    }


def fit_adaptive_learning_from_rows(
    rows: List[Dict[str, Any]],
    baseline_bins: Optional[Dict[str, Any]] = None,
    all_games_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compute realized ROI metrics, Bayesian-shrunk archetype bins, and model adjustments."""
    by_market_side: Dict[str, Dict[str, Any]] = {}
    by_spread_bucket: Dict[str, Dict[str, Any]] = {}
    by_edge_bucket: Dict[str, Dict[str, Any]] = {}
    by_spread_role: Dict[str, Dict[str, Any]] = {}
    by_total_zone: Dict[str, Dict[str, Any]] = {}
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
            sr_key = classify_spread_role(market, side, bet_line)
            if sr_key:
                _add_acc(by_spread_role.setdefault(sr_key, _init_acc()), outcome, roi)
        elif market == "TOTAL":
            tz_key = classify_total_zone(market, side, bet_line)
            if tz_key:
                _add_acc(by_total_zone.setdefault(tz_key, _init_acc()), outcome, roi)

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
    sr_summary = {k: _finalize_acc(v) for k, v in sorted(by_spread_role.items())}
    tz_summary = {k: _finalize_acc(v) for k, v in sorted(by_total_zone.items())}

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
    total_bias_sample = n_tot
    total_bias_source = "published_bets"

    all_games_summary = fit_all_games_learning(all_games_rows)
    if all_games_summary["total_bias_sample"] >= 15:
        total_bias_pts = all_games_summary["total_bias_pts"]
        total_bias_sample = all_games_summary["total_bias_sample"]
        total_bias_source = "all_completed_games"

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
    sig_cal = all_games_summary.get("sigma_calibration") or {}
    return {
        "league": "NCAAM",
        "season": current_ncaam_season_short(),
        "season_start": season_start_date_for_game(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_graded": total_n,
        "by_market_side": ms_summary,
        "by_spread_bucket": sb_summary,
        "by_edge_bucket": eb_summary,
        "by_spread_role": sr_summary,
        "by_total_zone": tz_summary,
        "by_home_fav_7pt_ml": _finalize_acc(home_fav_7pt_acc),
        "all_games_summary": all_games_summary,
        "learned_adjustments": {
            "total_bias_pts": total_bias_pts,
            "total_bias_sample": total_bias_sample,
            "total_bias_source": total_bias_source,
            "spread_sigma_scale": float(sig_cal.get("spread_sigma_scale") or 1.0),
            "total_sigma_scale": float(sig_cal.get("total_sigma_scale") or 1.0),
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
    q_all_games = """
    SELECT DISTINCT ON (d.event_id)
      d.event_id,
      d.context_json,
      gr.home_score,
      gr.away_score
    FROM daily_top_picks d
    JOIN events e ON d.event_id = e.id
    JOIN game_results gr ON gr.event_id = e.id AND COALESCE(gr.final, FALSE) = TRUE
    WHERE UPPER(COALESCE(d.league, e.league, 'NCAAM')) = :league
      AND d.context_json IS NOT NULL
      AND d.computed_at >= NOW() - INTERVAL :days
      AND COALESCE(e.start_time, d.computed_at) >= :season_start
      AND gr.home_score IS NOT NULL
      AND gr.away_score IS NOT NULL
    ORDER BY d.event_id, d.computed_at DESC
    """
    all_games_rows: List[Dict[str, Any]] = []
    with get_db_connection() as conn:
        rows = [dict(r) for r in _exec(conn, q, params).fetchall()]
        try:
            all_games_rows = [dict(r) for r in _exec(conn, q_all_games, params).fetchall()]
        except Exception as e:
            print(f"[ADAPTIVE_LEARNING] all-games query skipped: {e}")

    base_model = NCAAMMarketFirstModelV2()
    baseline_bins = (base_model._load_action_network_stats() or {}).get("bins") or {}
    payload = fit_adaptive_learning_from_rows(
        rows,
        baseline_bins=baseline_bins,
        all_games_rows=all_games_rows,
    )

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
