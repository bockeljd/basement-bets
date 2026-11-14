#!/usr/bin/env python3
"""Build archetype ROI stats from Action Network historical games.

This is intended to be run out-of-band (GitHub Actions or local cron) and committed
as a JSON artifact used by the Vercel API/model at runtime.

Outputs:
  data/model_params/action_network_archetype_stats_ncaam.json

Bins:
  key = "{MARKET}:{SIDE}:{EDGE_BUCKET}:{SPREAD_BUCKET}"

Where:
  MARKET in {SPREAD,TOTAL}
  SIDE in {home,away,over,under}
  EDGE_BUCKET = round(clamp(|fair-market|, 0..10))
  SPREAD_BUCKET in {close,mid,big,na}

ROI per unit:
  WON -> +payout (from American odds)
  LOST -> -1
  PUSH -> 0

Note: fair lines are computed via TorvikProjectionService.compute_torvik_projection
(DB-backed heuristic only; no external fetch).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_PATH = os.path.join(REPO_ROOT, "data", "model_params", "action_network_archetype_stats_ncaam.json")

# Ensure repo root is on path when run as a script
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.database import get_db_connection, _exec
from src.services.torvik_projection import TorvikProjectionService


def american_payout_per_unit(price: int) -> float:
    # payout for 1 unit risk
    if price > 0:
        return price / 100.0
    return 100.0 / abs(price)


def roi_per_unit(outcome: str, price: int) -> Optional[float]:
    o = (outcome or "").upper()
    if o == "PUSH":
        return 0.0
    if o not in ("WON", "LOST"):
        return None
    payout = american_payout_per_unit(int(price))
    return payout if o == "WON" else -1.0


def spread_bucket(home_spread: float) -> str:
    v = abs(float(home_spread or 0.0))
    if v <= 3.0:
        return "close"
    if v <= 7.0:
        return "mid"
    return "big"


def edge_bucket(edge_pts: float) -> int:
    try:
        v = float(edge_pts)
    except Exception:
        v = 0.0
    v = max(0.0, min(10.0, v))
    return int(round(v))


@dataclass
class Welford:
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def add(self, x: float) -> None:
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        delta2 = x - self.mean
        self.m2 += delta * delta2

    @property
    def sd(self) -> float:
        if self.n < 2:
            return 0.0
        return (self.m2 / (self.n - 1)) ** 0.5


def main() -> None:
    # Use DB-backed Torvik heuristic to compute a coarse fair line (no external fetch).
    # For speed, we intentionally use *latest* team metrics (date=None) and cache per-team stats.
    torvik = TorvikProjectionService()

    team_cache: Dict[str, Optional[Dict[str, Any]]] = {}
    _orig_get_latest = torvik._get_latest_metrics

    def _cached_get_latest(team_name: str, date: str = None) -> Optional[Dict[str, Any]]:
        if team_name in team_cache:
            return team_cache[team_name]
        val = _orig_get_latest(team_name, date=None)
        team_cache[team_name] = val
        return val

    torvik._get_latest_metrics = _cached_get_latest  # type: ignore

    window_days = int(os.getenv('ACTION_ARCH_WINDOW_DAYS', '1095'))  # 3 years
    limit_rows = int(os.getenv('ACTION_ARCH_LIMIT', '20000'))

    q = f"""
    WITH latest AS (
      SELECT game_id, MAX(date_scraped) AS max_scraped
      FROM historical_games_action_network
      WHERE sport='ncaab'
        AND status='complete'
        AND home_score IS NOT NULL AND away_score IS NOT NULL
        AND home_spread IS NOT NULL AND total_score IS NOT NULL
      GROUP BY game_id
    )
    SELECT h.*
    FROM historical_games_action_network h
    JOIN latest l
      ON l.game_id=h.game_id AND l.max_scraped=h.date_scraped
    WHERE h.sport='ncaab'
      AND h.start_time > NOW() - INTERVAL '{window_days} days'
    ORDER BY h.start_time DESC
    LIMIT {limit_rows}
    """

    aggs: Dict[str, Welford] = {}
    proj_cache: Dict[str, Dict[str, Any]] = {}

    print(f"[arch] window_days={window_days} limit={limit_rows}", flush=True)
    with get_db_connection() as conn:
        rows = _exec(conn, q).fetchall()

    print(f"[arch] fetched {len(rows)} rows", flush=True)

    for i, r in enumerate(rows, start=1):
        if i % 250 == 0:
            print(f"processed {i}/{len(rows)}", flush=True)
        home = r.get("home_team")
        away = r.get("away_team")
        # NOTE: For speed and stability, we intentionally use *latest* Torvik-style
        # efficiency metrics (date=None) rather than reconstructing per-day metrics.
        # This still yields a useful coarse edge bucket for archetype stats.
        if not home or not away:
            continue

        ck = f"{home}||{away}"

        mkt_spread_home = float(r.get("home_spread"))
        mkt_total = float(r.get("total_score"))

        # Compute coarse fair line from DB-backed Torvik heuristic (no selenium/external fetch).
        # - TorvikProjectionService.compute_torvik_projection returns margin = (home_score - away_score)
        # - Betting spread line is home-relative (negative means home favored), so fair spread line = -margin
        # For speed, do not attempt historical date reconstruction here.
        # (Team metrics are cached for date=None.)
        if ck not in proj_cache:
            try:
                proj_cache[ck] = torvik.compute_torvik_projection(home, away, date=None)
            except Exception:
                proj_cache[ck] = {"margin": 0.0, "total": 0.0}

        proj = proj_cache.get(ck) or {}
        if proj.get('lean') == 'No Data' or proj.get('total') is None:
            continue
        fair_spread_home = -float(proj.get('margin') or 0.0)
        fair_total = float(proj.get('total') or 0.0)

        ep_spread = abs(fair_spread_home - mkt_spread_home)
        ep_total = abs(fair_total - mkt_total)

        sb = spread_bucket(mkt_spread_home)

        # realized
        hs = float(r.get("home_score") or 0)
        aw = float(r.get("away_score") or 0)
        margin = hs - aw
        total_actual = hs + aw

        # Spread home/away
        for side in ("home", "away"):
            price = r.get("home_spread_odds") if side == "home" else r.get("away_spread_odds")
            if price is None:
                continue
            v = (margin + mkt_spread_home) if side == "home" else ((-margin) + (-mkt_spread_home))
            outcome = "WON" if v > 0 else ("LOST" if v < 0 else "PUSH")
            roi = roi_per_unit(outcome, int(price))
            if roi is None:
                continue
            key = f"SPREAD:{side}:{edge_bucket(ep_spread)}:{sb}"
            aggs.setdefault(key, Welford()).add(float(roi))

        # Total over/under
        for side in ("over", "under"):
            price = r.get("over_odds") if side == "over" else r.get("under_odds")
            if price is None:
                continue
            v = (total_actual - mkt_total) if side == "over" else (mkt_total - total_actual)
            outcome = "WON" if v > 0 else ("LOST" if v < 0 else "PUSH")
            roi = roi_per_unit(outcome, int(price))
            if roi is None:
                continue
            key = f"TOTAL:{side}:{edge_bucket(ep_total)}:na"
            aggs.setdefault(key, Welford()).add(float(roi))

    out: Dict[str, Any] = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "window_days": window_days,
        "limit_rows": limit_rows,
        "bins": {k: {"n": v.n, "mean": v.mean, "sd": v.sd} for k, v in aggs.items()},
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)

    print("wrote", OUT_PATH, "bins", len(out["bins"]))


if __name__ == "__main__":
    main()
