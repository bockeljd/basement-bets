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
    min_price: int = -250,
    max_price: int = 185,
) -> List[Obs]:
    """Fetch decided model predictions with valid win_prob for the target league/window."""
    lg = str(league or "NCAAM").upper().strip()
    season_clause = ""
    params: Dict[str, Any] = {"days": f"{int(days)} days", "league": lg}
    if season_start:
        season_clause = "AND COALESCE(e.start_time, m.analyzed_at) >= :season_start"
        params["season_start"] = f"{str(season_start)[:10]}T00:00:00+00:00"

    q = f"""
    SELECT m.win_prob, m.outcome, COALESCE(m.bet_price, m.price) AS price
    FROM model_predictions m
    JOIN events e ON m.event_id = e.id
    WHERE m.analyzed_at >= NOW() - INTERVAL :days
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


def main(
    days: int = 30,
    out_path: str | None = None,
    min_obs: int = 75,
    allow_insufficient: bool = True,
    league: str = "NCAAM",
    auto_widen: bool = True,
    cross_season: bool = False,
):
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
    for w in windows:
        candidate = _fetch_obs_for_window(days=w, league=lg, season_start=season_start)
        if len(candidate) > len(obs):
            obs = candidate
            used_days = w
        if len(obs) >= int(min_obs):
            break

    if len(obs) < int(min_obs):
        msg = f"[calibration:{lg}] Only {len(obs)} decided observations in last {used_days}d (< min_obs={min_obs}); keeping existing curve."
        if allow_insufficient:
            print(msg)
            return
        raise SystemExit(msg)

    artifact = fit_calibration_artifact(obs, days=used_days, min_points=12)
    artifact["league"] = lg
    if season_label:
        artifact["season"] = season_label
    if season_start:
        artifact["season_start"] = season_start

    if not is_valid_winprob_calibration(artifact, min_obs=int(min_obs), min_max_pcal=0.52):
        msg = f"[calibration:{lg}] Refusing to publish degenerate PAVA curve (max p_cal < 0.52 across {len(obs)} obs)."
        if allow_insufficient:
            print(msg)
            return
        raise SystemExit(msg)

    fname = f"winprob_calibration_{lg.lower()}.json"
    param_key = f"winprob_calibration_{lg.lower()}"
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
        print(f"[calibration:{lg}] DB model_params_store update skipped: {e}")

    print(f"league={lg} season={season_label} window={used_days}d n_obs={artifact['n_obs']} points={len(artifact['points'])}")


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
