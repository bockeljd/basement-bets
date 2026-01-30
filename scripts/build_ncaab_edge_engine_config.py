#!/usr/bin/env python3
"""Build (and stabilize) an Edge Engine config artifact from a threshold sweep.

Purpose:
- Avoid hard-coded magic numbers.
- Persist learned gating params (min_ev, etc.) as an artifact.
- Add guardrails to prevent jitter / overfitting:
    - Minimum bet volume + active days
    - Only update if ROI improvement is meaningful

Inputs:
- data/model_params/edge_engine_sweep_ncaab_<season>.json

Outputs:
- data/model_params/ncaab_edge_engine_config_<season>.json

Run:
  cd /Users/basementai/clawd/repos/basement-bets
  source .venv311/bin/activate
  python scripts/build_ncaab_edge_engine_config.py --season 2026
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, default=2026)
    ap.add_argument('--sweep', default=None)
    ap.add_argument('--out', default=None)

    # guardrails
    ap.add_argument('--min-bets', type=int, default=20)
    ap.add_argument('--min-active-days', type=int, default=6)
    ap.add_argument('--min-roi-improvement-pp', type=float, default=2.0, help='Minimum ROI improvement in percentage points to update config')

    # business constraints (explicit, not learned)
    ap.add_argument('--max-units-day', type=int, default=10)
    ap.add_argument('--max-units-game', type=int, default=5)

    args = ap.parse_args()

    season = int(args.season)
    sweep_path = args.sweep or os.path.join(REPO_ROOT, 'data', 'model_params', f'edge_engine_sweep_ncaab_{season}.json')
    out_path = args.out or os.path.join(REPO_ROOT, 'data', 'model_params', f'ncaab_edge_engine_config_{season}.json')

    sweep = load_json(sweep_path)
    grid = sweep.get('grid') or []

    # eligible rows (re-check with provided guardrails)
    eligible = [
        r for r in grid
        if (r.get('total_bets', 0) >= args.min_bets) and (r.get('active_days', 0) >= args.min_active_days)
    ]
    if not eligible:
        # fallback: best ROI overall, but mark unsafe
        eligible = grid
        unsafe = True
    else:
        unsafe = False

    best = max(eligible, key=lambda r: r.get('roi_pct', -999))

    # existing config (for stability)
    prev = None
    if os.path.exists(out_path):
        try:
            prev = load_json(out_path)
        except Exception:
            prev = None

    chosen = {
        'min_ev': float(best['min_ev']),
        'roi_pct': float(best.get('roi_pct', 0.0)),
        'total_bets': int(best.get('total_bets', 0)),
        'active_days': int(best.get('active_days', 0)),
    }

    # stability: only update if improvement is meaningful
    if prev and prev.get('learned', {}).get('min_ev') is not None:
        prev_roi = float(prev.get('learned', {}).get('roi_pct', 0.0))
        prev_min_ev = float(prev.get('learned', {}).get('min_ev'))
        improve = chosen['roi_pct'] - prev_roi

        if improve < float(args.min_roi_improvement_pp):
            # keep previous selection
            chosen['min_ev'] = prev_min_ev
            chosen['roi_pct'] = prev_roi
            chosen['note'] = f"kept previous min_ev={prev_min_ev} (ROI improvement {improve:.2f}pp < {args.min_roi_improvement_pp}pp)"
        else:
            chosen['note'] = f"updated min_ev to {chosen['min_ev']} (ROI improvement {improve:.2f}pp)"

    config = {
        'generated_at': datetime.now().isoformat(),
        'sport': 'ncaab',
        'season_end_year': season,
        'constraints': {
            'max_units_day': int(args.max_units_day),
            'max_units_game': int(args.max_units_game),
        },
        'guardrails': {
            'min_bets': int(args.min_bets),
            'min_active_days': int(args.min_active_days),
            'min_roi_improvement_pp': float(args.min_roi_improvement_pp),
        },
        'learned': chosen,
        'unsafe_fallback': unsafe,
        'source_sweep': os.path.basename(sweep_path),
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)

    print(json.dumps(config, indent=2))
    print(f"wrote: {out_path}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
