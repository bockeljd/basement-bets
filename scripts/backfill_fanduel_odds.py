#!/usr/bin/env python3
"""Backfill FanDuel odds from raw_text JSON (python dict repr) when odds is missing.

This updates the bets table:
- provider='FanDuel'
- odds IS NULL
- raw_text contains 'americanPrice'

It parses raw_text using ast.literal_eval and extracts the first legs.parts[].americanPrice.

Usage:
  source .venv/bin/activate
  python scripts/backfill_fanduel_odds.py --dry-run
  python scripts/backfill_fanduel_odds.py

Safe: only fills missing odds.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.database import get_db_connection, _exec


def extract_american_price(raw_text: str):
    try:
        obj = ast.literal_eval(raw_text)
    except Exception:
        return None
    legs = obj.get('legs') or []
    for leg in legs:
        for part in (leg.get('parts') or []):
            ap = part.get('americanPrice')
            if ap is not None:
                try:
                    return int(ap)
                except Exception:
                    return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--limit', type=int, default=1000)
    args = ap.parse_args()

    with get_db_connection() as conn:
        cur = _exec(conn, """
            select id, raw_text
            from bets
            where provider='FanDuel'
              and odds is null
              and raw_text is not null
              and raw_text like %s
            limit %s
        """, ('%americanPrice%', args.limit))
        rows = cur.fetchall()
        print('candidates', len(rows))

        updates = []
        for r in rows:
            apv = extract_american_price(r['raw_text'] or '')
            if apv is None:
                continue
            updates.append((apv, r['id']))

        print('extractable', len(updates))

        if args.dry_run:
            print('sample', updates[:10])
            return 0

        for apv, bid in updates:
            _exec(conn, "update bets set odds=%s where id=%s and odds is null", (apv, bid))
        conn.commit()
        print('updated', len(updates))

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
