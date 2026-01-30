#!/usr/bin/env python3
"""Ingest schedule + odds for one or more leagues.

This is intended for cron/automation on the Mac (or any environment with DB access).

It performs:
  - ESPN schedule ingestion -> events
  - Action Network odds ingestion -> odds_snapshots

Usage:
  cd /Users/basementai/clawd/repos/basement-bets
  python3 tools/ingest_board_all.py --leagues NFL NCAAM NCAAF EPL
  python3 tools/ingest_board_all.py --leagues NCAAM --date 2026-01-28

Notes:
  - date accepts YYYY-MM-DD or YYYYMMDD; default = today.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

# Ensure repo root is on sys.path so `import src.*` works when run as a script
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def norm_date(date_str: str | None) -> tuple[str, str]:
    if not date_str:
        ymd = datetime.now().strftime('%Y%m%d')
        iso = datetime.now().strftime('%Y-%m-%d')
        return ymd, iso

    d = date_str.strip()
    if '-' in d and len(d) == 10:
        return d.replace('-', ''), d
    if len(d) == 8 and d.isdigit():
        return d, f"{d[:4]}-{d[4:6]}-{d[6:8]}"

    # fallback: try parse
    try:
        dt = datetime.fromisoformat(d)
        return dt.strftime('%Y%m%d'), dt.strftime('%Y-%m-%d')
    except Exception:
        ymd = datetime.now().strftime('%Y%m%d')
        iso = datetime.now().strftime('%Y-%m-%d')
        return ymd, iso


def ingest_one(league: str, date_yyyymmdd: str) -> dict:
    """Ingest schedule + odds.

    For NCAAM, ESPN scoreboard often returns only a subset (e.g., Top-25). We therefore
    use Action Network as the canonical schedule source.
    """
    from src.services.odds_fetcher_service import OddsFetcherService
    from src.services.odds_adapter import OddsAdapter

    league = (league or '').upper().strip()

    fetcher = OddsFetcherService()
    adapter = OddsAdapter()

    # 1) Action Network (canonical board)
    raw_games = fetcher.fetch_odds(league, start_date=date_yyyymmdd)
    inserted = adapter.normalize_and_store(raw_games, league=league, provider='action_network')

    events_ingested = len(raw_games) if raw_games else 0

    # 2) Optional ESPN ingest for some leagues (results/enrichment). Skip for NCAAM schedule.
    if league != 'NCAAM':
        try:
            from src.parsers.espn_client import EspnClient
            client = EspnClient()
            events = client.fetch_scoreboard(league, date=date_yyyymmdd)
            # don't override events_ingested (we count canonical schedule from Action)
        except Exception:
            pass

    return {
        'league': league,
        'events_ingested': events_ingested,
        'odds_snapshots_inserted': inserted,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--leagues', nargs='+', default=['NFL', 'NCAAM', 'NCAAF', 'EPL'])
    ap.add_argument('--date', default=None)
    args = ap.parse_args()

    date_yyyymmdd, date_iso = norm_date(args.date)

    results = []
    for lg in args.leagues:
        try:
            r = ingest_one(lg, date_yyyymmdd)
            results.append(r)
            print(f"[board] {r['league']} date={date_iso} events={r['events_ingested']} snapshots={r['odds_snapshots_inserted']}")
        except Exception as e:
            print(f"[board] {lg}: ERROR {e}")

    # exit non-zero if all failed
    ok = any((r.get('odds_snapshots_inserted') is not None) for r in results)
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main())
