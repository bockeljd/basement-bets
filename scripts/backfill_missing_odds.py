#!/usr/bin/env python3
"""Backfill missing odds for settled bets.

Goals:
- For settled bets, odds should be present when it exists in raw payload/text.
- Fill only when odds is NULL or 0.

Strategies:
1) FanDuel:
   - raw_text is often a python dict repr of the API bet payload.
   - If bet-level odds missing, compute parlay odds from legs.parts[].americanPrice.
     (convert american -> decimal, multiply, convert back to american)
   - For straight bets, use the single part americanPrice.

2) DraftKings:
   - raw_text/selection/description often contains odds like +254 or -130.
   - Extract the last +/-\d{3,} as bet-level odds.

Usage:
  source .venv311/bin/activate
  python scripts/backfill_missing_odds.py --dry-run
  python scripts/backfill_missing_odds.py
"""

from __future__ import annotations

import argparse
import ast
import re
from typing import Optional, Iterable

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.database import get_db_connection, _exec


def american_to_decimal(odds: int) -> float:
    if odds > 0:
        return 1.0 + (odds / 100.0)
    return 1.0 + (100.0 / abs(odds))


def decimal_to_american(dec: float) -> Optional[int]:
    if dec is None or dec <= 1.0:
        return None
    # For dec >= 2.0 => positive odds
    if dec >= 2.0:
        return int(round((dec - 1.0) * 100))
    # For 1.0 < dec < 2.0 => negative odds
    return int(round(-100.0 / (dec - 1.0)))


def parse_fanduel_raw(raw_text: str) -> Optional[dict]:
    if not raw_text:
        return None
    # raw_text is stored as str(bet) in fanduel_client.py (python dict repr)
    try:
        return ast.literal_eval(raw_text)
    except Exception:
        return None


def extract_fd_part_prices(bet_obj: dict) -> list[int]:
    prices: list[int] = []
    legs = bet_obj.get('legs') or []
    for leg in legs:
        for part in (leg.get('parts') or []):
            ap = part.get('americanPrice')
            if ap is None:
                continue
            try:
                prices.append(int(ap))
            except Exception:
                pass
    return prices


def compute_fd_bet_odds(bet_obj: dict) -> Optional[int]:
    # Prefer bet-level american if present
    try:
        o = bet_obj.get('odds', {}).get('american')
        if o:
            return int(o)
    except Exception:
        pass

    prices = extract_fd_part_prices(bet_obj)
    if not prices:
        return None

    # If only one price, that's the bet
    if len(prices) == 1:
        return int(prices[0])

    # Compute parlay odds by multiplying decimal odds for each leg part
    dec = 1.0
    for p in prices:
        dec *= american_to_decimal(int(p))

    return decimal_to_american(dec)


DK_ODDS_RE = re.compile(r'([+-]\d{3,})')


def extract_dk_odds(text: str) -> Optional[int]:
    if not text:
        return None
    matches = DK_ODDS_RE.findall(text)
    if not matches:
        return None
    try:
        return int(matches[-1])
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--limit', type=int, default=5000)
    args = ap.parse_args()

    with get_db_connection() as conn:
        cur = _exec(conn, """
            select id, provider, bet_type, date, selection, description, raw_text
            from bets
            where (odds is null or odds=0)
              and (status is null or upper(status) not in ('PENDING','OPEN'))
            order by date desc
            limit %s
        """, (args.limit,))
        rows = cur.fetchall()

        updates: list[tuple[int, int]] = []
        for r in rows:
            provider = r['provider']
            new_odds = None

            if provider == 'FanDuel':
                bet_obj = parse_fanduel_raw(r.get('raw_text') or '')
                if bet_obj:
                    new_odds = compute_fd_bet_odds(bet_obj)
            elif provider == 'DraftKings':
                text = (r.get('raw_text') or '') + "\n" + (r.get('selection') or '') + "\n" + (r.get('description') or '')
                new_odds = extract_dk_odds(text)

            if new_odds is None:
                continue

            updates.append((int(new_odds), int(r['id'])))

        print('candidates', len(rows))
        print('updatable', len(updates))
        if args.dry_run:
            print('sample', updates[:20])
            return 0

        for o, bid in updates:
            _exec(conn, "update bets set odds=%s where id=%s and (odds is null or odds=0)", (o, bid))
        conn.commit()
        print('updated', len(updates))

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
