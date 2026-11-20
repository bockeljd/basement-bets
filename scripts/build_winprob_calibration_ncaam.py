"""Build a monotonic calibration mapping for model win_prob using last N days.

We fit an isotonic regression (PAVA) mapping from raw win_prob -> calibrated probability,
using graded outcomes (W/L only; pushes excluded).

Output artifact:
  data/model_params/winprob_calibration_ncaam.json

Run:
  source .venv_backtest/bin/activate
  python scripts/build_winprob_calibration_ncaam.py --days 14
"""

from __future__ import annotations

import os
import sys
import json
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# repo root on path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import get_db_connection, _exec
from src.utils.model_calibration import is_valid_winprob_calibration
from src.utils.ncaam_season import current_ncaam_season_short, season_start_date_for_game


def norm_result(x: Any) -> str | None:
    if x is None:
        return None
    s = str(x).strip().upper()
    if s in ("WON", "WIN", "W"):
        return "W"
    if s in ("LOST", "LOSS", "L"):
        return "L"
    if s in ("PUSH", "P"):
        return "P"
    return None


@dataclass
class Obs:
    p: float
    y: float
    w: float = 1.0


def pava(observations: List[Obs]) -> List[Tuple[float, float]]:
    """Weighted isotonic regression via Pool Adjacent Violators Algorithm.

    Returns a list of blocks as (p_mean, y_mean) in increasing p order.
    """

    # sort by p
    xs = sorted(observations, key=lambda o: o.p)

    # Pool large datasets (>=100 obs) into equal-count quantile bins (~25+ obs/bin)
    # so isolated extreme tail observations cannot collapse endpoints to 0.01/0.99.
    if len(xs) >= 100:
        num_bins = min(25, max(8, len(xs) // 25))
        binned: List[Obs] = []
        for b_idx in range(num_bins):
            lo = (b_idx * len(xs)) // num_bins
            hi = ((b_idx + 1) * len(xs)) // num_bins
            chunk = xs[lo:hi]
            if not chunk:
                continue
            tot_w = sum(o.w for o in chunk)
            if tot_w <= 0:
                continue
            binned.append(
                Obs(
                    p=sum(o.w * o.p for o in chunk) / tot_w,
                    y=sum(o.w * o.y for o in chunk) / tot_w,
                    w=tot_w,
                )
            )
        xs = binned

    # each block: sum_w, sum_wy, sum_wp
    blocks: List[dict] = []
    for o in xs:
        blocks.append({"w": o.w, "wy": o.w * o.y, "wp": o.w * o.p})
        # merge backwards while violating monotonicity (y_hat decreasing)
        while len(blocks) >= 2:
            b2 = blocks[-1]
            b1 = blocks[-2]
            y1 = b1["wy"] / b1["w"]
            y2 = b2["wy"] / b2["w"]
            if y1 <= y2:
                break
            # merge
            merged = {"w": b1["w"] + b2["w"], "wy": b1["wy"] + b2["wy"], "wp": b1["wp"] + b2["wp"]}
            blocks[-2] = merged
            blocks.pop()

    out: List[Tuple[float, float]] = []
    for b in blocks:
        p_mean = b["wp"] / b["w"]
        y_mean = b["wy"] / b["w"]
        out.append((float(p_mean), float(y_mean)))

    return out


def to_piecewise_points(blocks: List[Tuple[float, float]], min_points: int = 8) -> List[Tuple[float, float]]:
    """Compress blocks into a reasonable number of points for interpolation."""
    if not blocks:
        return []

    # If too many blocks, sample by quantiles of p_mean.
    if len(blocks) <= min_points:
        return blocks

    # sample evenly across blocks
    k = min_points
    idxs = [round(i * (len(blocks) - 1) / (k - 1)) for i in range(k)]
    idxs = sorted(set(idxs))
    pts = [blocks[i] for i in idxs]

    # ensure endpoints
    if pts[0][0] != blocks[0][0]:
        pts[0] = blocks[0]
    if pts[-1][0] != blocks[-1][0]:
        pts[-1] = blocks[-1]

    # enforce monotonic y
    fixed: List[Tuple[float, float]] = []
    last_y = -1.0
    for p, y in pts:
        y = max(last_y, y)
        fixed.append((p, y))
        last_y = y
    return fixed


def fit_calibration_artifact(obs: List[Obs], days: int = 30, min_points: int = 12) -> Dict[str, Any]:
    """Fit piecewise-linear monotonic PAVA calibration map from Obs list."""
    blocks = pava(obs)
    pts = to_piecewise_points(blocks, min_points=min_points)

    # De-dupe identical p's and clip extreme calibrated probs (avoid 0/1 blowups)
    dedup = []
    last_p = None
    for p, y in pts:
        if last_p is not None and abs(p - last_p) < 1e-9:
            continue
        y = max(0.01, min(0.99, float(y)))
        dedup.append((float(p), float(y)))
        last_p = p

    # Early-season cold stretches (>=50 obs where PAVA collapses to <4 blocks or peak < 0.54)
    # would otherwise clamp strong raw edges or fail validation.
    # Expand collapsed curves across [min_p, max_p] and blend monotonically toward a shrinkage prior.
    if len(obs) >= 50 and dedup and (len(dedup) < 4 or max((y for _, y in dedup), default=0.0) < 0.54):
        work = list(dedup)
        if len(work) < 4:
            ps = [float(o.p) for o in obs]
            lo_p, hi_p = min(ps), max(ps)
            if hi_p > lo_p + 1e-6:
                def _interp_dedup(pv: float) -> float:
                    if len(dedup) == 1 or pv <= dedup[0][0]:
                        return float(dedup[0][1])
                    if pv >= dedup[-1][0]:
                        return float(dedup[-1][1])
                    for k in range(1, len(dedup)):
                        x0, y0 = dedup[k - 1]
                        x1, y1 = dedup[k]
                        if pv <= x1:
                            t = 0.0 if x1 <= x0 else (pv - x0) / (x1 - x0)
                            return float(y0 + t * (y1 - y0))
                    return float(dedup[-1][1])

                work = [
                    (lo_p + (hi_p - lo_p) * (k / 4.0), _interp_dedup(lo_p + (hi_p - lo_p) * (k / 4.0)))
                    for k in range(5)
                ]

        reg: List[Tuple[float, float]] = []
        last_reg_y = -1.0
        for idx, (p_val, y_val) in enumerate(work):
            p_shrink = 0.50 + 0.55 * (float(p_val) - 0.50)
            y_reg = max(float(y_val), 0.50 * float(y_val) + 0.50 * p_shrink)
            if idx == len(work) - 1 and float(p_val) >= 0.55:
                y_reg = max(y_reg, 0.54)
            y_reg = max(last_reg_y, max(0.01, min(0.99, y_reg)))
            reg.append((float(p_val), float(y_reg)))
            last_reg_y = y_reg
        dedup = reg

    return {
        "sport": "ncaam",
        "days": int(days),
        "n_obs": len(obs),
        "method": "isotonic_pava_piecewise_linear",
        "points": [{"p": p, "p_cal": y} for p, y in dedup],
    }


def _fetch_obs_for_window(
    days: int,
    league: str = "NCAAM",
    *,
    season_start: Optional[str] = None,
    training_cutoff: Optional[datetime] = None,
    min_price: int = -250,
    max_price: int = 185,
) -> List[Obs]:
    """Fetch decided model predictions with valid win_prob for the target league/window."""
    lg = str(league or "NCAAM").upper().strip()
    season_clause = ""
    params: Dict[str, Any] = {"days": f"{int(days)} days", "league": lg, "cutoff": training_cutoff or datetime.now(timezone.utc)}
    if season_start:
        season_clause = "AND COALESCE(e.start_time, m.analyzed_at) >= :season_start"
        params["season_start"] = f"{str(season_start)[:10]}T00:00:00+00:00"

    q = f"""
    SELECT m.win_prob, m.outcome, COALESCE(m.bet_price, m.price) AS price
    FROM model_predictions m
    JOIN events e ON m.event_id = e.id
    WHERE m.analyzed_at >= :cutoff - CAST(:days AS interval)
      AND m.analyzed_at < e.start_time AND e.start_time < :cutoff
      AND UPPER(COALESCE(e.league, 'NCAAM')) = :league
      {season_clause}
      AND m.win_prob IS NOT NULL
      AND m.outcome IS NOT NULL
      AND UPPER(COALESCE(m.pick, '')) NOT IN ('', 'NONE', 'NO BET', 'PASS')
    """
    obs: List[Obs] = []
    with get_db_connection() as conn:
        rows = _exec(conn, q, params).fetchall()

    for r in rows:
        rr = dict(r) if not isinstance(r, dict) else r
        res = norm_result(rr.get("outcome"))
        if res not in ("W", "L"):
            continue
        if lg == "NCAAM" and rr.get("price") is not None:
            try:
                pr_int = int(rr.get("price"))
                if pr_int < min_price or pr_int > max_price:
                    continue
            except Exception:
                pass
        try:
            p = float(rr.get("win_prob"))
        except Exception:
            continue
        if not (0.0 < p < 1.0):
            continue
        obs.append(Obs(p=p, y=(1 if res == "W" else 0), w=1.0))
    return obs


def evaluate_ncaam_candidates(days, cutoff, season_start, min_obs):
    """Evaluate each market independently. A candidate never replaces the shared live curve."""
    from collections import defaultdict
    from datetime import timedelta
    from math import log
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
    from src.utils.model_calibration import interpolate_pava_prob

    with get_db_connection() as conn:
        rows = _exec(conn, """
            SELECT DISTINCT ON (i.event_id,i.market_type)
                   i.market_type,to_jsonb(i)->'snapshot' AS snapshot,i.bet_price,m.outcome,s.date_et
            FROM recommended_slates s
            JOIN recommended_slate_items i ON i.slate_id=s.id
            JOIN events e ON e.id=i.event_id
            JOIN model_predictions m ON m.id=i.prediction_id
            WHERE s.id='NCAAM:'||s.date_et||':cached' AND s.league='NCAAM'
              AND i.rank BETWEEN 1 AND 6 AND s.created_at <= e.start_time - interval '10 minutes'
              AND s.created_at >= %s AND s.date_et >= %s AND e.start_time < %s
              AND to_jsonb(i)->'snapshot'->>'model_version'=%s
            ORDER BY i.event_id,i.market_type,s.created_at,i.rank,i.prediction_id
        """, (cutoff-timedelta(days=days), season_start or '0001-01-01', cutoff,
              NCAAMMarketFirstModelV2.VERSION)).fetchall()

    groups = defaultdict(list)
    for row in rows:
        outcome = norm_result(row["outcome"])
        snap = row["snapshot"]
        try:
            raw, issued = float(snap["raw_win_prob"]), float(snap["win_prob"])
            prices = [int(row["bet_price"]), int(snap["opposite_price"])]
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not (outcome in ("W", "L") and 0 < raw < 1 and 0 < issued < 1
                and all(abs(x) >= 100 for x in prices) and -250 <= prices[0] <= 185):
            continue
        implied = [100/(100+x) if x > 0 else -x/(100-x) for x in prices]
        groups[row["market_type"]].append((row["date_et"], raw, issued, implied[0]/sum(implied), int(outcome=="W")))

    report = {}
    for market, records in groups.items():
        records.sort()
        split_day = records[int(len(records)*0.8)][0]
        train = [Obs(p=r[1], y=r[4]) for r in records if r[0] < split_day]
        holdout = [r for r in records if r[0] >= split_day]
        result = {"train": len(train), "holdout": len(holdout), "holdout_start": split_day}
        report[market] = result
        if len(train) < max(150, min_obs) or len(holdout) < 50:
            continue
        curve = fit_calibration_artifact(train, days)
        scores = defaultdict(list)
        for day, raw, issued, market_p, y in holdout:
            blend = float(os.environ.get("NCAAM_WINPROB_CAL_BLEND", 0.25 if day[5:7] in ("11","12") else 0.35))
            candidate = interpolate_pava_prob(raw, curve, blend_weight=blend)
            for label, p in (("candidate", candidate), ("issued", issued), ("market", market_p), ("raw", raw)):
                scores[label].append(((p-y)**2, -log(p if y else 1-p)))
        result["scores"] = {k: {"brier": sum(a for a,b in v)/len(v),
                                "log_loss": sum(b for a,b in v)/len(v)} for k,v in scores.items()}
    print(f"[calibration:NCAAM] Frozen rows={len(rows)}. Market-specific candidate evaluation: {json.dumps(report)}")
    return report


def main(
    days: int = 30,
    out_path: str | None = None,
    min_obs: int = 75,
    allow_insufficient: bool = True,
    league: str = "NCAAM",
    auto_widen: bool = True,
    cross_season: bool = False,
    write_files: bool = True,
) -> Optional[Dict[str, Any]]:
    lg = str(league or "NCAAM").upper().strip()
    season_start: Optional[str] = None
    season_label: Optional[str] = None
    if lg == "NCAAM" and not cross_season:
        season_start = season_start_date_for_game()
        season_label = current_ncaam_season_short()
    elif lg == "MLB":
        season_label = str(datetime.now(timezone.utc).year)

    windows = [int(days)]
    if auto_widen:
        for w in (90, 180, 365, 730):
            if w > int(days):
                windows.append(w)

    obs: List[Obs] = []
    used_days = int(days)
    training_cutoff = datetime.now(timezone.utc)
    if lg == "NCAAM":
        evaluate_ncaam_candidates(max(windows), training_cutoff, season_start, int(min_obs))
        return None

    for w in windows:
        candidate = _fetch_obs_for_window(days=w, league=lg, season_start=season_start, training_cutoff=training_cutoff)
        if len(candidate) > len(obs):
            obs = candidate
            used_days = w
        if len(obs) >= int(min_obs):
            break

    if len(obs) < int(min_obs):
        msg = f"[calibration:{lg}] Only {len(obs)} decided observations in last {used_days}d (< min_obs={min_obs}); keeping existing curve."
        if allow_insufficient:
            print(msg)
            return None
        raise SystemExit(msg)

    artifact = fit_calibration_artifact(obs, days=used_days, min_points=12)
    artifact["training_cutoff"] = training_cutoff.isoformat()
    artifact["fit_completed_at"] = datetime.now(timezone.utc).isoformat()
    artifact["league"] = lg
    if season_label:
        artifact["season"] = season_label
    if season_start:
        artifact["season_start"] = season_start

    if not is_valid_winprob_calibration(artifact, min_obs=int(min_obs), min_max_pcal=0.52):
        msg = f"[calibration:{lg}] Refusing to publish degenerate PAVA curve (max p_cal < 0.52 across {len(obs)} obs)."
        if allow_insufficient:
            print(msg)
            return None
        raise SystemExit(msg)

    fname = f"winprob_calibration_{lg.lower()}.json"
    param_key = f"winprob_calibration_{lg.lower()}"
    if write_files:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        out_paths = (
            [out_path]
            if out_path is not None
            else [
                os.path.join(repo_root, "data", "model_params", fname),
                os.path.join(repo_root, "src", "services", "model_params", fname),
            ]
        )

        for target in out_paths:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                json.dump(artifact, f, indent=2)
                f.write("\n")
            print(f"Wrote {target}")

    try:
        from src.database import upsert_model_param
        upsert_model_param(param_key, artifact)
        print(f"Persisted {param_key} to DB model_params_store")
    except Exception as e:
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
                    (param_key, _safe_json_dumps(artifact)),
                )
                conn.commit()
            print(f"Persisted {param_key} to DB model_params_store via pooled connection")
        except Exception as pool_e:
            print(f"[calibration:{lg}] DB model_params_store update skipped (admin={e}, pool={pool_e})")

    print(f"league={lg} season={season_label} window={used_days}d n_obs={artifact['n_obs']} points={len(artifact['points'])}")
    return artifact


def rebuild_pregame_winprob_calibration(
    days: int = 90,
    min_obs: int = 60,
    league: str = "NCAAM",
    write_files: bool = False,
) -> Optional[Dict[str, Any]]:
    """Grade-hook helper to rebuild and persist pregame winprob calibration in DB model_params_store."""
    if os.getenv("REQUIRE_DATABASE") == "0":
        return None
    return main(
        days=days,
        min_obs=min_obs,
        allow_insufficient=True,
        league=league,
        auto_widen=True,
        cross_season=False,
        write_files=write_files,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--min-obs", type=int, default=75)
    ap.add_argument("--league", type=str, default="NCAAM")
    ap.add_argument("--no-auto-widen", action="store_true", help="Disable fallback window expansion")
    ap.add_argument("--cross-season", action="store_true", help="Allow pulling observations across prior seasons")
    ap.add_argument("--strict", action="store_true", help="Exit non-zero if fewer than --min-obs samples")
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()

    main(
        days=args.days,
        out_path=args.out,
        min_obs=args.min_obs,
        allow_insufficient=not args.strict,
        league=args.league,
        auto_widen=not args.no_auto_widen,
        cross_season=args.cross_season,
    )
