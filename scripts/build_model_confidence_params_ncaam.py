"""Build uncertainty parameters for NCAAM model confidence.

We estimate a simple model-error stddev (tau) for spreads and totals using last N days:
  tau_spread = std(close_line - mu_final) for SPREAD predictions where close_line exists
  tau_total  = std(close_line - mu_final) for TOTAL predictions where close_line exists

This tau is used to simulate uncertainty in mu when computing a confidence label.

Output:
  data/model_params/model_confidence_params_ncaam.json

Run:
  source .venv_backtest/bin/activate
  python scripts/build_model_confidence_params_ncaam.py --days 14
"""

from __future__ import annotations

import os
import sys
import json
import argparse
from typing import Any, List, Tuple

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import get_db_connection, _exec


def _to_float(x: Any):
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _std(xs: List[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / (n - 1)
    return v ** 0.5


def _fetch_tau_errors(days: int) -> tuple[List[float], List[float]]:
    q = """
    SELECT m.market_type, m.mu_final, m.close_line
    FROM model_predictions m
    JOIN events e ON m.event_id = e.id
    WHERE m.analyzed_at >= NOW() - INTERVAL :days
      AND UPPER(COALESCE(e.league, 'NCAAM')) = 'NCAAM'
      AND m.close_line IS NOT NULL
      AND m.mu_final IS NOT NULL
      AND m.market_type IN ('SPREAD', 'TOTAL')
    """
    spread_err: List[float] = []
    total_err: List[float] = []

    with get_db_connection() as conn:
        rows = _exec(conn, q, {"days": f"{int(days)} days"}).fetchall()

    for r in rows:
        rr = dict(r) if not isinstance(r, dict) else r
        mkt = str(rr.get('market_type') or '').upper()
        mu = _to_float(rr.get('mu_final'))
        cl = _to_float(rr.get('close_line'))
        if mu is None or cl is None:
            continue
        err = cl - mu
        if mkt == 'SPREAD':
            if abs(mu) <= 60.0 and abs(cl) <= 60.0 and abs(err) <= 20.0:
                spread_err.append(err)
        elif mkt == 'TOTAL':
            if 80.0 <= mu <= 240.0 and 80.0 <= cl <= 240.0 and abs(err) <= 30.0:
                total_err.append(err)
    return spread_err, total_err


def main(days: int = 14, out_path: str | None = None, min_obs: int = 20, auto_widen: bool = True):
    windows = [int(days)]
    if auto_widen:
        for w in (60, 180, 365, 730):
            if w > int(days):
                windows.append(w)

    spread_err: List[float] = []
    total_err: List[float] = []
    used_days = int(days)
    for w in windows:
        s_cand, t_cand = _fetch_tau_errors(w)
        if len(s_cand) + len(t_cand) > len(spread_err) + len(total_err):
            spread_err, total_err = s_cand, t_cand
            used_days = w
        if len(spread_err) >= min_obs and len(total_err) >= min_obs:
            break

    if len(spread_err) < 5 and len(total_err) < 5:
        print(f"[confidence] Insufficient closing-line observations in last {used_days}d (spread={len(spread_err)}, total={len(total_err)}); keeping existing params.")
        return

    tau_spread = min(12.0, _std(spread_err))
    tau_total = min(18.0, _std(total_err))

    artifact = {
        "sport": "ncaam",
        "days": int(used_days),
        "n_spread": len(spread_err),
        "n_total": len(total_err),
        "tau_spread": float(tau_spread),
        "tau_total": float(tau_total),
        "method": "std(close_line - mu_final)",
        "notes": "tau represents uncertainty in mu; used for win_prob lower-bound confidence",
    }

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out_paths = (
        [out_path]
        if out_path is not None
        else [
            os.path.join(repo_root, 'data', 'model_params', 'model_confidence_params_ncaam.json'),
            os.path.join(repo_root, 'src', 'services', 'model_params', 'model_confidence_params_ncaam.json'),
        ]
    )

    for target in out_paths:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'w', encoding='utf-8') as f:
            json.dump(artifact, f, indent=2)
            f.write('\n')
        print(f"Wrote {target}")
    print(json.dumps(artifact, indent=2))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=14)
    ap.add_argument('--min-obs', type=int, default=20)
    ap.add_argument('--no-auto-widen', action='store_true')
    ap.add_argument('--out', type=str, default=None)
    args = ap.parse_args()
    main(days=args.days, out_path=args.out, min_obs=args.min_obs, auto_widen=not args.no_auto_widen)
