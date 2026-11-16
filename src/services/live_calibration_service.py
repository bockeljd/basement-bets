"""Pure-Python live in-game win-probability snapshot logging, grading, and PAVA calibration.

Designed for serverless environments (no numpy/pandas/scipy dependency):
1. Captures throttled mid-game snapshots for active recommended picks (`live_trend_snapshots`).
2. Grades pending snapshots against final scores in `game_results`.
3. Fits lightweight parameters (`live_weight_scale`, `sigma_total_rem`, `sigma_spread_rem`)
   and a monotonic PAVA reliability curve once enough settled trajectories accumulate (`>= 25`),
   persisting into `model_params_store` (`live_winprob_calibration_ncaam`).
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.utils.model_calibration import (
    interpolate_pava_prob,
    is_valid_winprob_calibration,
    resolve_model_param_path,
)
from src.utils.ncaam_season import season_start_date_for_game

LIVE_CAL_PARAM_KEY = "live_winprob_calibration_ncaam"
LIVE_CAL_FILENAME = "live_winprob_calibration_ncaam.json"

DEFAULT_LIVE_WEIGHT_SCALE = 0.85
DEFAULT_SIGMA_TOTAL_REM = 13.5
DEFAULT_SIGMA_SPREAD_REM = 10.5
MIN_LIVE_CAL_OBS = 25
CALIBRATION_BLEND_WEIGHT = 0.75

_CAL_CACHE_TTL_SECONDS = 300.0
_cal_cache_payload: Optional[Dict[str, Any]] = None
_cal_cache_ts: float = 0.0
_seen_snapshot_keys: set[str] = set()
_table_initialized: bool = False


def normal_cdf(z: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(float(z) / math.sqrt(2.0)))


def default_live_calibration_params() -> Dict[str, float]:
    """Return baseline uncalibrated live projection and uncertainty parameters."""
    return {
        "live_weight_scale": DEFAULT_LIVE_WEIGHT_SCALE,
        "sigma_total_rem": DEFAULT_SIGMA_TOTAL_REM,
        "sigma_spread_rem": DEFAULT_SIGMA_SPREAD_REM,
    }


def invalidate_live_calibration_cache() -> None:
    """Clear the in-process cached live calibration payload."""
    global _cal_cache_payload, _cal_cache_ts
    _cal_cache_payload = None
    _cal_cache_ts = 0.0


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(val)))


def _norm_outcome(raw: Any) -> Optional[str]:
    s = str(raw or "").strip().upper()
    if s in ("WON", "WIN", "W"):
        return "WON"
    if s in ("LOST", "LOSS", "L"):
        return "LOST"
    if s in ("PUSH", "P"):
        return "PUSH"
    return None


def _parse_bet_line_from_text(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*$", str(text).strip())
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    m2 = re.search(r"\b(?:OVER|UNDER|O|U)\s*(\d+(?:\.\d+)?)\b", str(text), re.IGNORECASE)
    if m2:
        try:
            return float(m2.group(1))
        except Exception:
            return None
    return None


def _infer_side(market_type: str, pick: str, selection: str, home_team: str, away_team: str) -> str:
    mkt = str(market_type or "").upper().strip()
    text = f"{selection or ''} {pick or ''}".strip()
    up = text.upper()
    if mkt == "TOTAL":
        if "UNDER" in up or up.startswith("U "):
            return "UNDER"
        return "OVER"

    raw_side = up
    if raw_side in ("HOME", "AWAY"):
        return raw_side

    clean = lambda s: re.sub(r"[^a-z0-9]", "", str(s or "").lower())
    text_norm = clean(re.sub(r"\b(ML|MONEYLINE)\b", "", text, flags=re.I))
    home_norm = clean(home_team)
    away_norm = clean(away_team)
    if home_norm and home_norm in text_norm and not (away_norm and away_norm in text_norm):
        return "HOME"
    if away_norm and away_norm in text_norm and not (home_norm and home_norm in text_norm):
        return "AWAY"
    if home_norm and away_norm and home_norm in text_norm and away_norm in text_norm:
        return "HOME" if len(home_norm) >= len(away_norm) else "AWAY"
    return "HOME"


def _extract_params(cal: Optional[Dict[str, Any]]) -> Dict[str, float]:
    base = default_live_calibration_params()
    if not isinstance(cal, dict):
        return base
    params = cal.get("params") if isinstance(cal.get("params"), dict) else {}
    for k in ("live_weight_scale", "sigma_total_rem", "sigma_spread_rem"):
        if params.get(k) is not None:
            try:
                base[k] = float(params[k])
            except Exception:
                pass
    return base


def get_active_live_calibration(*, force_refresh: bool = False) -> Dict[str, Any]:
    """Load active live win-probability calibration payload (DB first, then JSON fallback, then default)."""
    global _cal_cache_payload, _cal_cache_ts
    now = time.time()
    if not force_refresh and _cal_cache_payload is not None and (now - _cal_cache_ts) < _CAL_CACHE_TTL_SECONDS:
        return _cal_cache_payload

    season_start = season_start_date_for_game()
    loaded: Optional[Dict[str, Any]] = None

    if os.getenv("REQUIRE_DATABASE") != "0":
        try:
            from src.database import get_model_param

            db_payload = get_model_param(LIVE_CAL_PARAM_KEY)
            if isinstance(db_payload, dict) and (not season_start or str(db_payload.get("season_start") or "")[:10] >= season_start[:10]):
                loaded = db_payload
        except Exception:
            loaded = None

    if loaded is None:
        path = resolve_model_param_path(LIVE_CAL_FILENAME)
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    file_payload = json.load(f)
                if isinstance(file_payload, dict) and (not season_start or str(file_payload.get("season_start") or "")[:10] >= season_start[:10]):
                    loaded = file_payload
        except Exception:
            loaded = None

    if loaded is None:
        loaded = {
            "status": "collecting",
            "active": False,
            "season_start": season_start,
            "min_obs_required": MIN_LIVE_CAL_OBS,
            "n_obs": 0,
            "params": default_live_calibration_params(),
            "points": [],
            "bins": [],
            "brier_raw": None,
            "brier_calibrated": None,
            "updated_at": None,
        }

    _cal_cache_payload = loaded
    _cal_cache_ts = now
    return loaded


def fit_pava_points(observations: List[Tuple[float, float]]) -> List[Dict[str, Any]]:
    """Run weighted monotonic Pool Adjacent Violators (PAVA) regression in pure Python."""
    if not observations:
        return []

    xs = sorted(((_clamp(p, 0.0, 1.0), _clamp(y, 0.0, 1.0), 1.0) for p, y in observations), key=lambda o: o[0])
    if len(xs) >= 60:
        num_bins = min(20, max(6, len(xs) // 12))
        binned: List[Tuple[float, float, float]] = []
        for idx in range(num_bins):
            lo = (idx * len(xs)) // num_bins
            hi = ((idx + 1) * len(xs)) // num_bins
            chunk = xs[lo:hi]
            if not chunk:
                continue
            tot_w = sum(c[2] for c in chunk)
            binned.append((
                sum(c[0] * c[2] for c in chunk) / tot_w,
                sum(c[1] * c[2] for c in chunk) / tot_w,
                tot_w,
            ))
        xs = binned

    blocks: List[Dict[str, float]] = []
    for p_val, y_val, w_val in xs:
        blocks.append({"w": w_val, "wy": w_val * y_val, "wp": w_val * p_val})
        while len(blocks) >= 2:
            b1, b2 = blocks[-2], blocks[-1]
            if (b1["wy"] / b1["w"]) <= (b2["wy"] / b2["w"]):
                break
            blocks[-2] = {
                "w": b1["w"] + b2["w"],
                "wy": b1["wy"] + b2["wy"],
                "wp": b1["wp"] + b2["wp"],
            }
            blocks.pop()

    points: List[Dict[str, Any]] = []
    for b in blocks:
        points.append({
            "p": round(b["wp"] / b["w"], 4),
            "p_cal": round(_clamp(b["wy"] / b["w"], 0.02, 0.98), 4),
            "n": int(round(b["w"])),
        })
    return points


def compute_brier_score(pairs: List[Tuple[float, float]]) -> Optional[float]:
    """Return mean squared probability error (lower is better)."""
    if not pairs:
        return None
    total = sum((_clamp(p, 0.0, 1.0) - _clamp(y, 0.0, 1.0)) ** 2 for p, y in pairs)
    return round(total / len(pairs), 4)


def build_reliability_bins(pairs: List[Tuple[float, float]]) -> List[Dict[str, Any]]:
    """Group live win-probability observations into 20% wide reliability buckets."""
    specs = [
        ("0–20%", 0, 20, 0.0, 0.20),
        ("20–40%", 20, 40, 0.20, 0.40),
        ("40–60%", 40, 60, 0.40, 0.60),
        ("60–80%", 60, 80, 0.60, 0.80),
        ("80–100%", 80, 100, 0.80, 1.01),
    ]
    buckets: List[List[Tuple[float, float]]] = [[] for _ in specs]
    for p, y in pairs:
        p_c = _clamp(p, 0.0, 1.0)
        for i, (_, _, _, lo, hi) in enumerate(specs):
            if lo <= p_c < hi:
                buckets[i].append((p_c, float(y)))
                break

    out: List[Dict[str, Any]] = []
    for (label, min_pct, max_pct, _, _), rows in zip(specs, buckets):
        n = len(rows)
        if n == 0:
            out.append({
                "label": label,
                "min_pct": min_pct,
                "max_pct": max_pct,
                "count": 0,
                "wins": 0,
                "avg_predicted_pct": None,
                "actual_win_pct": None,
            })
        else:
            wins = sum(1 for _, y in rows if y >= 0.5)
            avg_p = sum(p for p, _ in rows) / n
            actual = wins / n
            out.append({
                "label": label,
                "min_pct": min_pct,
                "max_pct": max_pct,
                "count": n,
                "wins": wins,
                "avg_predicted_pct": round(avg_p * 100.0, 1),
                "actual_win_pct": round(actual * 100.0, 1),
            })
    return out


def compute_live_bet_win_prob(
    *,
    elapsed_fraction: float,
    home_score: int,
    away_score: int,
    pregame_total: float,
    pregame_home_margin: float,
    market_type: str,
    side: str,
    bet_line: Optional[float],
    params: Optional[Dict[str, float]] = None,
    calibration: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Project remaining scoring/margin and return raw + optionally calibrated live win probability."""
    p_cfg = dict(default_live_calibration_params())
    if params:
        for k, v in params.items():
            if v is not None and k in p_cfg:
                p_cfg[k] = float(v)

    ef = _clamp(elapsed_fraction, 0.04, 0.98)
    rem_frac = max(0.03, 1.0 - ef)
    max_live_wt = 0.85 if p_cfg["live_weight_scale"] > 0.88 else 0.80
    live_weight = _clamp(ef * p_cfg["live_weight_scale"], 0.15, max_live_wt)

    total_now = int(home_score) + int(away_score)
    pre_t = float(pregame_total) if pregame_total is not None else 142.0
    pre_m = float(pregame_home_margin) if pregame_home_margin is not None else 0.0

    raw_pace_total = _clamp(total_now / ef, 75.0, 235.0)
    blended_total_rate = live_weight * raw_pace_total + (1.0 - live_weight) * pre_t
    proj_total = round(max(float(total_now), total_now + blended_total_rate * rem_frac), 1)

    current_home_margin = int(home_score) - int(away_score)
    raw_pace_margin = _clamp(current_home_margin / ef, -35.0, 35.0)
    blended_margin_rate = live_weight * raw_pace_margin + (1.0 - live_weight) * pre_m
    proj_home_margin = round(current_home_margin + blended_margin_rate * rem_frac, 1)

    mkt = str(market_type or "").upper().strip()
    s_up = str(side or "").upper().strip()
    proj_bet_margin = 0.0
    raw_prob = 0.5

    if mkt == "TOTAL" and bet_line is not None:
        line_val = float(bet_line)
        is_over = s_up == "OVER"
        if is_over and total_now > line_val:
            proj_bet_margin = round(proj_total - line_val, 1)
            raw_prob = 0.99
        elif (not is_over) and total_now > line_val:
            proj_bet_margin = round(line_val - total_now, 1)
            raw_prob = 0.01
        else:
            proj_bet_margin = round((proj_total - line_val) if is_over else (line_val - proj_total), 1)
            sigma_rem = max(2.0, p_cfg["sigma_total_rem"] * math.sqrt(rem_frac))
            raw_prob = _clamp(normal_cdf(proj_bet_margin / sigma_rem), 0.02, 0.98)
    else:
        eff_line = 0.0 if mkt in ("ML", "MONEYLINE") else float(bet_line or 0.0)
        is_home = s_up == "HOME"
        proj_pick_margin = proj_home_margin if is_home else -proj_home_margin
        proj_bet_margin = round(proj_pick_margin + eff_line, 1)
        sigma_rem = max(1.5, p_cfg["sigma_spread_rem"] * math.sqrt(rem_frac))
        raw_prob = _clamp(normal_cdf(proj_bet_margin / sigma_rem), 0.02, 0.98)

    cal_prob = raw_prob
    if calibration and is_valid_winprob_calibration(calibration, min_obs=MIN_LIVE_CAL_OBS):
        cal_prob = interpolate_pava_prob(
            raw_prob,
            calibration,
            min_obs=MIN_LIVE_CAL_OBS,
            blend_weight=CALIBRATION_BLEND_WEIGHT,
        )

    return {
        "projected_total": proj_total,
        "projected_home_margin": proj_home_margin,
        "projected_bet_margin": proj_bet_margin,
        "raw_live_win_prob": round(raw_prob, 4),
        "calibrated_live_win_prob": round(cal_prob, 4),
    }


def fit_live_calibration_artifact(
    rows: List[Dict[str, Any]],
    *,
    season_start: Optional[str] = None,
    min_obs: int = MIN_LIVE_CAL_OBS,
) -> Dict[str, Any]:
    """Tune remaining-variance & pace weights and fit PAVA calibration on settled live snapshots."""
    eff_season = season_start or season_start_date_for_game()
    decided: List[Dict[str, Any]] = []
    for r in rows or []:
        out = _norm_outcome(r.get("outcome"))
        if out not in ("WON", "LOST"):
            continue
        item = dict(r)
        item["y_win"] = 1.0 if out == "WON" else 0.0
        decided.append(item)

    n_obs = len(decided)
    default_params = default_live_calibration_params()

    def _eval_rows(subset: List[Dict[str, Any]], p_cfg: Dict[str, float]) -> List[Tuple[float, float]]:
        pairs: List[Tuple[float, float]] = []
        for row in subset:
            res = compute_live_bet_win_prob(
                elapsed_fraction=float(row.get("elapsed_fraction") or 0.5),
                home_score=int(row.get("home_score") or 0),
                away_score=int(row.get("away_score") or 0),
                pregame_total=float(row.get("pregame_total") or 142.0),
                pregame_home_margin=float(row.get("pregame_home_margin") or 0.0),
                market_type=str(row.get("market_type") or "SPREAD"),
                side=str(row.get("side") or "HOME"),
                bet_line=row.get("bet_line"),
                params=p_cfg,
                calibration=None,
            )
            pairs.append((res["raw_live_win_prob"], row["y_win"]))
        return pairs

    raw_baseline_pairs = _eval_rows(decided, default_params) if decided else []
    brier_raw = compute_brier_score(raw_baseline_pairs)

    if n_obs < min_obs:
        return {
            "status": "collecting",
            "active": False,
            "season_start": eff_season,
            "min_obs_required": min_obs,
            "n_obs": n_obs,
            "params": default_params,
            "points": [],
            "bins": build_reliability_bins(raw_baseline_pairs),
            "brier_raw": brier_raw,
            "brier_calibrated": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    best_params = dict(default_params)
    best_weight_brier = brier_raw if brier_raw is not None else 1.0
    for lw in (0.55, 0.65, 0.70, 0.80, 0.85, 0.95, 1.05):
        cand = dict(best_params, live_weight_scale=lw)
        b = compute_brier_score(_eval_rows(decided, cand))
        if b is not None and b < best_weight_brier:
            best_weight_brier = b
            best_params["live_weight_scale"] = lw

    total_rows = [r for r in decided if str(r.get("market_type") or "").upper() == "TOTAL"]
    if len(total_rows) >= 10:
        best_tb = compute_brier_score(_eval_rows(total_rows, best_params)) or 1.0
        for st in (11.5, 12.5, 13.5, 15.0, 16.5, 18.0, 19.5):
            cand = dict(best_params, sigma_total_rem=st)
            b = compute_brier_score(_eval_rows(total_rows, cand))
            if b is not None and b < best_tb:
                best_tb = b
                best_params["sigma_total_rem"] = st

    spread_rows = [r for r in decided if str(r.get("market_type") or "").upper() != "TOTAL"]
    if len(spread_rows) >= 10:
        best_sb = compute_brier_score(_eval_rows(spread_rows, best_params)) or 1.0
        for ss in (8.5, 9.5, 10.5, 11.5, 13.0, 14.5, 16.0):
            cand = dict(best_params, sigma_spread_rem=ss)
            b = compute_brier_score(_eval_rows(spread_rows, cand))
            if b is not None and b < best_sb:
                best_sb = b
                best_params["sigma_spread_rem"] = ss

    tuned_pairs = _eval_rows(decided, best_params)
    pava_points = fit_pava_points(tuned_pairs)

    cal_candidate = {
        "season_start": eff_season,
        "n_obs": n_obs,
        "points": pava_points,
        "params": best_params,
    }
    calibrated_pairs = [
        (
            interpolate_pava_prob(
                p,
                cal_candidate,
                min_obs=min_obs,
                blend_weight=CALIBRATION_BLEND_WEIGHT,
            ),
            y,
        )
        for p, y in tuned_pairs
    ]
    brier_cal = compute_brier_score(calibrated_pairs)

    return {
        "status": "calibrated",
        "active": True,
        "season_start": eff_season,
        "min_obs_required": min_obs,
        "n_obs": n_obs,
        "params": best_params,
        "points": pava_points,
        "bins": build_reliability_bins(calibrated_pairs),
        "brier_raw": brier_raw,
        "brier_calibrated": brier_cal,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _ensure_table(conn) -> None:
    global _table_initialized
    if _table_initialized:
        return
    from src.database import _exec

    _exec(
        conn,
        """
        CREATE TABLE IF NOT EXISTS live_trend_snapshots (
            id SERIAL PRIMARY KEY,
            snapshot_key TEXT UNIQUE NOT NULL,
            event_id TEXT NOT NULL,
            league TEXT NOT NULL DEFAULT 'NCAAM',
            home_team TEXT,
            away_team TEXT,
            market_type TEXT NOT NULL,
            side TEXT,
            selection TEXT,
            bet_line DOUBLE PRECISION,
            elapsed_fraction DOUBLE PRECISION NOT NULL,
            progress_bucket INTEGER NOT NULL,
            home_score INTEGER NOT NULL,
            away_score INTEGER NOT NULL,
            pregame_total DOUBLE PRECISION,
            pregame_home_margin DOUBLE PRECISION,
            projected_total DOUBLE PRECISION,
            projected_home_margin DOUBLE PRECISION,
            projected_bet_margin DOUBLE PRECISION,
            raw_live_win_prob DOUBLE PRECISION,
            calibrated_live_win_prob DOUBLE PRECISION,
            outcome TEXT NOT NULL DEFAULT 'PENDING',
            actual_home_score INTEGER,
            actual_away_score INTEGER,
            captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            graded_at TIMESTAMPTZ
        )
        """,
    )
    _table_initialized = True


def maybe_record_live_snapshots(items: List[Dict[str, Any]]) -> int:
    """Persist throttled mid-game snapshots (1 per 10% game progress bucket per pick) for live games."""
    if os.getenv("REQUIRE_DATABASE") == "0" or os.getenv("DISABLE_LIVE_SNAPSHOT_LOG") == "1":
        return 0
    if not items:
        return 0

    candidates: List[Tuple[Dict[str, Any], int, float]] = []
    for item in items:
        if str(item.get("live_status") or "").upper() not in ("IN_PROGRESS", "HALFTIME"):
            continue
        trend = item.get("live_trend")
        if not isinstance(trend, dict):
            continue
        if item.get("home_score") is None or item.get("away_score") is None:
            continue
        eid = str(item.get("id") or "")
        if not eid:
            continue
        prog_pct = int(trend.get("progress_pct") or 0)
        bucket = min(90, max(0, (prog_pct // 10) * 10))
        dedup_key = f"{eid}:{bucket}"
        if dedup_key in _seen_snapshot_keys:
            continue
        elapsed_frac = float(trend.get("elapsed_minutes") or 0.0) / max(1.0, float(trend.get("total_game_minutes") or 40.0))
        candidates.append((item, bucket, _clamp(elapsed_frac, 0.04, 0.98)))

    if not candidates:
        return 0

    try:
        from src.database import get_db_connection, _exec

        cal = get_active_live_calibration()
        params = _extract_params(cal)
        event_ids = list({str(item.get("id")) for item, _, _ in candidates})

        with get_db_connection() as conn:
            _ensure_table(conn)
            pred_rows = _exec(
                conn,
                """
                SELECT DISTINCT ON (event_id)
                    event_id, market_type, pick, selection, bet_line, ev_per_unit
                FROM model_predictions
                WHERE event_id = ANY(%s)
                  AND COALESCE(ev_per_unit, 0) >= 0.02
                ORDER BY event_id, ev_per_unit DESC NULLS LAST, analyzed_at DESC NULLS LAST
                """,
                (event_ids,),
            ).fetchall()

            preds_by_eid = {str(r["event_id"]): dict(r) for r in (pred_rows or [])}
            inserted = 0
            for item, bucket, elapsed_frac in candidates:
                eid = str(item.get("id"))
                _seen_snapshot_keys.add(f"{eid}:{bucket}")
                if len(_seen_snapshot_keys) > 2500:
                    _seen_snapshot_keys.clear()

                pred = preds_by_eid.get(eid)
                if not pred:
                    continue

                mkt = str(pred.get("market_type") or "SPREAD").upper().strip()
                if mkt == "MONEYLINE":
                    mkt = "ML"
                if mkt not in ("SPREAD", "TOTAL", "ML"):
                    continue

                selection = str(pred.get("selection") or pred.get("pick") or "")
                side = _infer_side(
                    mkt,
                    str(pred.get("pick") or ""),
                    selection,
                    str(item.get("home_team") or ""),
                    str(item.get("away_team") or ""),
                )
                bet_line = pred.get("bet_line")
                if bet_line is None and mkt in ("SPREAD", "TOTAL"):
                    bet_line = _parse_bet_line_from_text(selection)

                pre_total = float(item.get("total_line") or item.get("total") or 142.0)
                pre_home_spread = item.get("home_spread") if item.get("home_spread") is not None else item.get("spread_home")
                pre_home_margin = -float(pre_home_spread) if pre_home_spread is not None else 0.0

                hs = int(item["home_score"])
                as_ = int(item["away_score"])
                proj = compute_live_bet_win_prob(
                    elapsed_fraction=elapsed_frac,
                    home_score=hs,
                    away_score=as_,
                    pregame_total=pre_total,
                    pregame_home_margin=pre_home_margin,
                    market_type=mkt,
                    side=side,
                    bet_line=bet_line,
                    params=params,
                    calibration=cal,
                )
                snap_key = f"{eid}:{mkt}:{bucket}"
                res = _exec(
                    conn,
                    """
                    INSERT INTO live_trend_snapshots (
                        snapshot_key, event_id, league, home_team, away_team,
                        market_type, side, selection, bet_line,
                        elapsed_fraction, progress_bucket, home_score, away_score,
                        pregame_total, pregame_home_margin,
                        projected_total, projected_home_margin, projected_bet_margin,
                        raw_live_win_prob, calibrated_live_win_prob
                    ) VALUES (
                        %(snapshot_key)s, %(event_id)s, 'NCAAM', %(home_team)s, %(away_team)s,
                        %(market_type)s, %(side)s, %(selection)s, %(bet_line)s,
                        %(elapsed_fraction)s, %(progress_bucket)s, %(home_score)s, %(away_score)s,
                        %(pregame_total)s, %(pregame_home_margin)s,
                        %(projected_total)s, %(projected_home_margin)s, %(projected_bet_margin)s,
                        %(raw_live_win_prob)s, %(calibrated_live_win_prob)s
                    )
                    ON CONFLICT (snapshot_key) DO NOTHING
                    """,
                    {
                        "snapshot_key": snap_key,
                        "event_id": eid,
                        "home_team": item.get("home_team"),
                        "away_team": item.get("away_team"),
                        "market_type": mkt,
                        "side": side,
                        "selection": selection,
                        "bet_line": bet_line,
                        "elapsed_fraction": elapsed_frac,
                        "progress_bucket": bucket,
                        "home_score": hs,
                        "away_score": as_,
                        "pregame_total": pre_total,
                        "pregame_home_margin": pre_home_margin,
                        "projected_total": proj["projected_total"],
                        "projected_home_margin": proj["projected_home_margin"],
                        "projected_bet_margin": proj["projected_bet_margin"],
                        "raw_live_win_prob": proj["raw_live_win_prob"],
                        "calibrated_live_win_prob": proj["calibrated_live_win_prob"],
                    },
                )
                inserted += int(getattr(res, "rowcount", 0) or 0)
            conn.commit()
            return inserted
    except Exception as exc:
        print(f"[LIVE_CAL] Snapshot capture warning: {exc}")
        return 0


def grade_pending_live_snapshots(*, conn=None, max_rows: int = 1000) -> int:
    """Grade PENDING rows in live_trend_snapshots using final scores from game_results."""
    if os.getenv("REQUIRE_DATABASE") == "0" and conn is None:
        return 0

    from src.database import get_db_connection, _exec
    from src.services.grading_backfill import grade_score_prediction

    def _run(c) -> int:
        _ensure_table(c)
        rows = _exec(
            c,
            """
            SELECT s.id, s.market_type, s.side, s.selection, s.bet_line,
                   s.home_team, s.away_team,
                   gr.home_score AS actual_home_score,
                   gr.away_score AS actual_away_score
            FROM live_trend_snapshots s
            JOIN game_results gr ON gr.event_id = s.event_id
            WHERE s.outcome = 'PENDING'
              AND gr.final = TRUE
              AND gr.home_score IS NOT NULL
              AND gr.away_score IS NOT NULL
            ORDER BY s.captured_at ASC
            LIMIT %s
            """,
            (int(max_rows),),
        ).fetchall()

        graded = 0
        for r in rows or []:
            d = dict(r)
            mkt = str(d.get("market_type") or "").upper()
            if mkt == "ML":
                mkt = "MONEYLINE"
            pick_text = d.get("selection") or d.get("side") or ""
            outcome = grade_score_prediction(
                market_type=mkt,
                pick=pick_text,
                selection=d.get("selection") or d.get("side"),
                bet_line=d.get("bet_line"),
                home_team=d.get("home_team"),
                away_team=d.get("away_team"),
                home_score=int(d["actual_home_score"]),
                away_score=int(d["actual_away_score"]),
                is_mlb=False,
            )
            if outcome not in ("WON", "LOST", "PUSH", "VOID"):
                continue
            _exec(
                c,
                """
                UPDATE live_trend_snapshots
                SET outcome = %s,
                    actual_home_score = %s,
                    actual_away_score = %s,
                    graded_at = NOW()
                WHERE id = %s
                """,
                (outcome, int(d["actual_home_score"]), int(d["actual_away_score"]), int(d["id"])),
            )
            graded += 1
        if graded:
            c.commit()
        return graded

    if conn is not None:
        return _run(conn)

    with get_db_connection() as own_conn:
        return _run(own_conn)


def rebuild_live_calibration(*, persist: bool = True, season_start: Optional[str] = None) -> Dict[str, Any]:
    """Grade pending snapshots, refit live calibration curve + parameters, and optionally persist."""
    eff_season = season_start or season_start_date_for_game()
    if os.getenv("REQUIRE_DATABASE") == "0":
        return get_active_live_calibration(force_refresh=True)

    from src.database import get_db_connection, _exec, upsert_model_param

    graded_now = 0
    rows: List[Dict[str, Any]] = []
    with get_db_connection() as conn:
        _ensure_table(conn)
        graded_now = grade_pending_live_snapshots(conn=conn)
        db_rows = _exec(
            conn,
            """
            SELECT elapsed_fraction, home_score, away_score, pregame_total, pregame_home_margin,
                   market_type, side, bet_line, outcome
            FROM live_trend_snapshots
            WHERE league = 'NCAAM'
              AND captured_at >= %s::timestamptz
              AND outcome IN ('WON', 'LOST')
            ORDER BY captured_at ASC
            """,
            (f"{eff_season[:10]}T00:00:00Z",),
        ).fetchall()
        rows = [dict(r) for r in (db_rows or [])]

    artifact = fit_live_calibration_artifact(rows, season_start=eff_season)
    artifact["newly_graded"] = graded_now

    if persist and artifact.get("active"):
        try:
            upsert_model_param(LIVE_CAL_PARAM_KEY, artifact)
        except Exception as admin_err:
            # Fallback to pooled connection if admin/DDL connection is unavailable in serverless
            try:
                from src.database import _safe_json_dumps

                with get_db_connection() as conn:
                    _exec(
                        conn,
                        """
                        INSERT INTO model_params_store(param_key, payload, updated_at)
                        VALUES (%s, %s::jsonb, NOW())
                        ON CONFLICT (param_key) DO UPDATE SET
                          payload = EXCLUDED.payload,
                          updated_at = NOW()
                        """,
                        (LIVE_CAL_PARAM_KEY, _safe_json_dumps(artifact)),
                    )
                    conn.commit()
            except Exception as pool_err:
                print(f"[LIVE_CAL] Persist warning (admin={admin_err}, pool={pool_err})")

        out_path = resolve_model_param_path(LIVE_CAL_FILENAME)
        try:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(artifact, f, indent=2)
        except Exception:
            pass

    if artifact.get("active"):
        global _cal_cache_payload, _cal_cache_ts
        _cal_cache_payload = artifact
        _cal_cache_ts = time.time()
    else:
        invalidate_live_calibration_cache()
    return artifact


def get_live_calibration_summary() -> Dict[str, Any]:
    """Return full status + snapshot counts + reliability bins for the UI dashboard."""
    cal = get_active_live_calibration()
    eff_season = str(cal.get("season_start") or season_start_date_for_game())
    min_req = int(cal.get("min_obs_required") or MIN_LIVE_CAL_OBS)

    counts = {
        "total_snapshots": 0,
        "pending_snapshots": 0,
        "decided_snapshots": 0,
        "win_count": 0,
        "loss_count": 0,
        "push_count": 0,
    }
    raw_pairs: List[Tuple[float, float]] = []

    if os.getenv("REQUIRE_DATABASE") != "0":
        try:
            from src.database import get_db_connection, _exec

            with get_db_connection() as conn:
                _ensure_table(conn)
                agg = _exec(
                    conn,
                    """
                    SELECT
                      COUNT(*) AS total_snapshots,
                      COUNT(*) FILTER (WHERE outcome = 'PENDING') AS pending_snapshots,
                      COUNT(*) FILTER (WHERE outcome IN ('WON', 'LOST')) AS decided_snapshots,
                      COUNT(*) FILTER (WHERE outcome = 'WON') AS win_count,
                      COUNT(*) FILTER (WHERE outcome = 'LOST') AS loss_count,
                      COUNT(*) FILTER (WHERE outcome = 'PUSH') AS push_count
                    FROM live_trend_snapshots
                    WHERE league = 'NCAAM'
                      AND captured_at >= %s::timestamptz
                    """,
                    (f"{eff_season[:10]}T00:00:00Z",),
                ).fetchone()
                if agg:
                    for k in counts:
                        counts[k] = int(dict(agg).get(k) or 0)
        except Exception as exc:
            print(f"[LIVE_CAL] Summary query warning: {exc}")

        # Auto-fit and persist PAVA live calibration once enough settled snapshots exist.
        if counts["decided_snapshots"] >= min_req and (
            not cal.get("active") or counts["decided_snapshots"] >= int(cal.get("n_obs") or 0) + 15
        ):
            rebuilt = None
            try:
                rebuilt = rebuild_live_calibration(persist=True, season_start=eff_season)
            except Exception as exc:
                print(f"[LIVE_CAL] Auto-rebuild persist warning: {exc}")
                try:
                    rebuilt = rebuild_live_calibration(persist=False, season_start=eff_season)
                except Exception as exc2:
                    print(f"[LIVE_CAL] Auto-rebuild fallback warning: {exc2}")
            if isinstance(rebuilt, dict) and rebuilt.get("active"):
                cal = rebuilt
                eff_season = str(cal.get("season_start") or eff_season)

        if counts["decided_snapshots"] > 0 and not cal.get("bins"):
            try:
                from src.database import get_db_connection, _exec

                with get_db_connection() as conn:
                    obs_rows = _exec(
                        conn,
                        """
                        SELECT raw_live_win_prob, calibrated_live_win_prob, outcome
                        FROM live_trend_snapshots
                        WHERE league = 'NCAAM'
                          AND captured_at >= %s::timestamptz
                          AND outcome IN ('WON', 'LOST')
                        """,
                        (f"{eff_season[:10]}T00:00:00Z",),
                    ).fetchall()
                    for r in obs_rows or []:
                        d = dict(r)
                        p = d.get("calibrated_live_win_prob") if d.get("calibrated_live_win_prob") is not None else d.get("raw_live_win_prob")
                        if p is not None:
                            raw_pairs.append((float(p), 1.0 if d.get("outcome") == "WON" else 0.0))
            except Exception as exc:
                print(f"[LIVE_CAL] Summary bins fallback warning: {exc}")

    bins = cal.get("bins") or build_reliability_bins(raw_pairs)
    brier_raw = cal.get("brier_raw") if cal.get("brier_raw") is not None else compute_brier_score(raw_pairs)

    return {
        "status": "calibrated" if cal.get("active") else "collecting",
        "active": bool(cal.get("active")),
        "season_start": eff_season,
        "min_obs_required": min_req,
        "n_obs": max(int(cal.get("n_obs") or 0), counts["decided_snapshots"]),
        **counts,
        "brier_raw": brier_raw,
        "brier_calibrated": cal.get("brier_calibrated"),
        "params": _extract_params(cal),
        "bins": bins,
        "points": cal.get("points") or [],
        "updated_at": cal.get("updated_at"),
    }
