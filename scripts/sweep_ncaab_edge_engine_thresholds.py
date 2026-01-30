#!/usr/bin/env python3
"""Sweep EV thresholds for the NCAAB edge engine walk-forward backtest.

We optimize for max ROI but also enforce minimum activity so we don't overfit on
tiny bet counts.

Run:
  cd /Users/basementai/clawd/repos/basement-bets
  source .venv311/bin/activate
  python scripts/sweep_ncaab_edge_engine_thresholds.py --season 2026

Outputs:
  data/model_params/edge_engine_sweep_ncaab_2026.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.backtest_ncaab_edge_engine_walkforward import load_games_agg, spread_row, total_row, ml_row
from scripts.backtest_ncaab_edge_engine_walkforward import (
    logit,
    sigmoid,
    american_to_decimal,
    ev_per_unit,
    confidence_from_ev,
    units_from_conf,
    standardize_fit,
    standardize_apply,
    train_residual_logreg,
)

import numpy as np


def _prepare_training_cache(games, steps: int, lr: float, l2: float):
    """Train one set of per-day models once; re-use for threshold sweeps."""
    dates = sorted({g.date_et for g in games})
    cache = {}

    for day in dates:
        train_games = [g for g in games if g.date_et < day]
        test_games = [g for g in games if g.date_et == day]
        if len(train_games) < 200:
            continue

        models = {}
        for kind, row_fn in [("SPREAD", spread_row), ("TOTAL", total_row), ("ML", ml_row)]:
            Xs = []
            ys = []
            offs = []
            for gg in train_games:
                rr = row_fn(gg)
                if not rr:
                    continue
                X, y, p_mkt, _odds = rr
                Xs.append(X)
                ys.append(y)
                offs.append(logit(p_mkt))

            if len(Xs) < 300:
                continue

            Xtr = np.stack(Xs, axis=0)
            ytr = np.array(ys, dtype=np.float64)
            off = np.array(offs, dtype=np.float64)

            Ztr, mu, sd = standardize_fit(Xtr)
            w, b = train_residual_logreg(Ztr, ytr, off, l2=float(l2), lr=float(lr), steps=int(steps))
            models[kind] = {"w": w, "b": b, "mu": mu, "sd": sd}

        cache[day] = {"models": models, "games": test_games}

    return cache


def run_backtest_with_cache(day_cache, min_ev: float, max_units_day: int, max_units_game: int):
    daily_profit = {}
    total_units = 0.0
    total_bets = 0

    for day, payload in day_cache.items():
        models = payload["models"]
        test_games = payload["games"]

        candidates = []
        for gg in test_games:
            for kind, row_fn in [("SPREAD", spread_row), ("TOTAL", total_row), ("ML", ml_row)]:
                if kind not in models:
                    continue
                rr = row_fn(gg)
                if not rr:
                    continue
                X, y_true, p_mkt, odds = rr

                m = models[kind]
                Z = standardize_apply(X.reshape(1, -1), m['mu'], m['sd'])
                z_adj = float((Z @ m['w'])[0] + m['b'])
                z = logit(p_mkt) + z_adj
                p_model = float(sigmoid(np.array([z]))[0])

                ev = ev_per_unit(p_model, odds)
                if ev is None or ev < min_ev:
                    continue

                conf = confidence_from_ev(ev, p_model, p_mkt)
                units = units_from_conf(conf)
                if units <= 0:
                    continue

                candidates.append({
                    "g": gg,
                    "kind": kind,
                    "y": y_true,
                    "odds": odds,
                    "ev": ev,
                    "units": units,
                    "score": ev * units,
                })

        candidates.sort(key=lambda r: r['score'], reverse=True)

        units_left = max_units_day
        units_by_game = {}
        profit = 0.0
        bets = 0

        for c in candidates:
            if units_left <= 0:
                break
            gid = c['g'].game_id
            used_game = units_by_game.get(gid, 0)
            if used_game >= max_units_game:
                continue
            u = min(c['units'], units_left, max_units_game - used_game)
            if u <= 0:
                continue
            win = bool(c['y'] >= 0.5)
            dec = american_to_decimal(c['odds'])
            if win:
                profit += u * ((dec - 1.0) if dec else 0.0)
            else:
                profit -= u
            bets += 1
            units_left -= u
            units_by_game[gid] = used_game + u
            total_units += u
            total_bets += 1

        daily_profit[day] = {"profit_units": profit, "bets": bets, "units": (max_units_day - units_left)}

    total_profit = sum(v['profit_units'] for v in daily_profit.values())
    roi = (total_profit / total_units * 100.0) if total_units else 0.0
    return {
        "min_ev": min_ev,
        "total_bets": total_bets,
        "total_units": round(total_units, 3),
        "total_profit_units": round(total_profit, 3),
        "roi_pct": round(roi, 2),
        "active_days": sum(1 for v in daily_profit.values() if v['bets'] > 0),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, default=2026)
    ap.add_argument('--steps', type=int, default=400)
    ap.add_argument('--lr', type=float, default=0.05)
    ap.add_argument('--l2', type=float, default=0.5)
    ap.add_argument('--max-units-day', type=int, default=10)
    ap.add_argument('--max-units-game', type=int, default=5)
    ap.add_argument('--min-bets', type=int, default=25, help='Minimum total bets required to consider threshold')
    ap.add_argument('--min-active-days', type=int, default=8, help='Minimum days with >=1 bet to consider threshold')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    games = load_games_agg(int(args.season))
    thresholds = [0.00, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10]

    # Train walk-forward models once, then sweep thresholds cheaply
    day_cache = _prepare_training_cache(games, steps=int(args.steps), lr=float(args.lr), l2=float(args.l2))

    results = []
    for t in thresholds:
        r = run_backtest_with_cache(
            day_cache,
            min_ev=float(t),
            max_units_day=int(args.max_units_day),
            max_units_game=int(args.max_units_game),
        )
        r['eligible'] = (r['total_bets'] >= args.min_bets) and (r['active_days'] >= args.min_active_days)
        results.append(r)
        print(r)

    # pick best ROI among eligible; fallback to best ROI overall
    eligible = [r for r in results if r['eligible']]
    best = max(eligible, key=lambda r: r['roi_pct']) if eligible else max(results, key=lambda r: r['roi_pct'])

    out = {
        "ran_at": datetime.now().isoformat(),
        "season_end_year": int(args.season),
        "constraints": {
            "max_units_day": int(args.max_units_day),
            "max_units_game": int(args.max_units_game),
            "min_bets": int(args.min_bets),
            "min_active_days": int(args.min_active_days),
        },
        "grid": results,
        "best": best,
    }

    out_path = args.out or f"data/model_params/edge_engine_sweep_ncaab_{int(args.season)}.json"
    out_path = os.path.join(REPO_ROOT, out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2)

    print("\nBEST:")
    print(best)
    print(f"wrote: {out_path}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
