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
from typing import Any, List, Tuple

# repo root on path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import get_db_connection, _exec


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
    y: int
    w: float = 1.0


def pava(observations: List[Obs]) -> List[Tuple[float, float]]:
    """Weighted isotonic regression via Pool Adjacent Violators Algorithm.

    Returns a list of blocks as (p_mean, y_mean) in increasing p order.
    """

    # sort by p
    xs = sorted(observations, key=lambda o: o.p)

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


def main(days: int = 30, out_path: str | None = None, min_obs: int = 50, allow_insufficient: bool = True):
    q = """
    SELECT win_prob, outcome
    FROM model_predictions
    WHERE analyzed_at >= NOW() - INTERVAL :days
      AND win_prob IS NOT NULL
      AND outcome IS NOT NULL
    """

    obs: List[Obs] = []
    with get_db_connection() as conn:
        rows = _exec(conn, q, {"days": f"{int(days)} days"}).fetchall()

    for r in rows:
        rr = dict(r) if not isinstance(r, dict) else r
        res = norm_result(rr.get("outcome"))
        if res not in ("W", "L"):
            continue
        try:
            p = float(rr.get("win_prob"))
        except Exception:
            continue
        if not (0.0 < p < 1.0):
            continue
        obs.append(Obs(p=p, y=(1 if res == "W" else 0), w=1.0))

    if len(obs) < int(min_obs):
        msg = f"[calibration] Only {len(obs)} decided observations in last {days}d (< min_obs={min_obs}); keeping existing curve."
        if allow_insufficient:
            print(msg)
            return
        raise SystemExit(msg)

    artifact = fit_calibration_artifact(obs, days=days, min_points=12)

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out_paths = (
        [out_path]
        if out_path is not None
        else [
            os.path.join(repo_root, "data", "model_params", "winprob_calibration_ncaam.json"),
            os.path.join(repo_root, "src", "services", "model_params", "winprob_calibration_ncaam.json"),
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
        upsert_model_param("winprob_calibration_ncaam", artifact)
        print("Persisted winprob_calibration_ncaam to DB model_params_store")
    except Exception as e:
        print(f"[calibration] DB model_params_store update skipped: {e}")

    print(f"n_obs={artifact['n_obs']} points={len(artifact['points'])}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--min-obs", type=int, default=50)
    ap.add_argument("--strict", action="store_true", help="Exit non-zero if fewer than --min-obs samples")
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()

    main(days=args.days, out_path=args.out, min_obs=args.min_obs, allow_insufficient=not args.strict)
