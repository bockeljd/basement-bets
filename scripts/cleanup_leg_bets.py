#!/usr/bin/env python3
"""Cleanup script: remove legacy leg rows incorrectly stored as standalone bets.

Problem:
- Some legacy CSV imports inserted parlay legs as separate rows in `bets` with wager=0 and bet_type like 'Leg'.
- These should be attached to the parlay parent bet, not counted in bet-based analytics.

This script deletes those standalone leg rows that match a safe signature:
- wager = 0
- bet_type contains 'leg' (case-insensitive)
- raw_text like 'Imported from CSV%'

It does NOT touch:
- real parent parlays
- API-ingested bets
- any non-zero wager rows

Usage:
  source .venv/bin/activate
  python scripts/cleanup_leg_bets.py --dry-run
  python scripts/cleanup_leg_bets.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.database import get_db_connection, _exec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Avoid literal % in SQL strings when passing params (psycopg can misinterpret it).
    like_bet_type = "%leg%"
    like_raw_text = "Imported from CSV%"

    with get_db_connection() as conn:
        cur = _exec(
            conn,
            "select count(*) as n from bets where wager = 0 and lower(bet_type) like %s and raw_text like %s",
            (like_bet_type, like_raw_text),
        )
        n = cur.fetchone()["n"]
        print(f"Matched rows: {n}")

        if args.dry_run:
            cur = _exec(
                conn,
                "select id, date, provider, bet_type, description from bets where wager = 0 and lower(bet_type) like %s and raw_text like %s order by date desc limit 20",
                (like_bet_type, like_raw_text),
            )
            for r in cur.fetchall():
                print(r["id"], r["date"], r["provider"], r["bet_type"], (r["description"] or "")[:80])
            return 0

        cur = _exec(
            conn,
            "delete from bets where wager = 0 and lower(bet_type) like %s and raw_text like %s",
            (like_bet_type, like_raw_text),
        )
        conn.commit()
        print(f"Deleted rows: {cur.rowcount}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
