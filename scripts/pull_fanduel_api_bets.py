#!/usr/bin/env python3
"""Pull settled FanDuel bets via API and upsert into bets table.

Purpose: correct bad wager/profit rows created from earlier parsing (e.g., betType SGL with wager=0).

Requirements:
- DATABASE_URL set in repo .env (gitignored)
- FANDUEL_AUTH_TOKEN set in environment (recommended: add to .env locally; do NOT commit)

Usage:
  source .venv311/bin/activate
  export FANDUEL_AUTH_TOKEN='...'
  python scripts/pull_fanduel_api_bets.py --pages 10 --page-size 50

Notes:
- We do a targeted cleanup: if an existing FanDuel row has wager=0 for the same (date, description), delete it before inserting the corrected row.
- Token is never printed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure repo root is on sys.path so `import src.*` works regardless of CWD
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.api_clients.fanduel_client import FanDuelAPIClient
from src.database import insert_bet, get_db_connection, _exec

USER_ID = "00000000-0000-0000-0000-000000000000"


def cleanup_bad_row(provider: str, date: str, description: str) -> int:
    # Remove the known-bad variant where wager=0.0 so the corrected upsert doesn't leave duplicates.
    with get_db_connection() as conn:
        cur = _exec(
            conn,
            """
            delete from bets
            where provider = %(provider)s
              and date = %(date)s
              and description = %(description)s
              and wager = 0
            """,
            {"provider": provider, "date": date, "description": description},
        )
        conn.commit()
        return cur.rowcount or 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page-size", type=int, default=50)
    ap.add_argument("--pages", type=int, default=10)
    ap.add_argument("--region", type=str, default="OH")
    args = ap.parse_args()

    # Load repo-local env (DB URL etc.)
    load_dotenv(".env")

    token = os.environ.get("FANDUEL_AUTH_TOKEN")
    if not token:
        raise SystemExit("Missing FANDUEL_AUTH_TOKEN in environment. Set it locally (do not commit).")

    client = FanDuelAPIClient(auth_token=token, region=args.region)

    inserted = 0
    deleted_bad = 0

    for page in range(args.pages):
        from_record = page * args.page_size + 1
        to_record = (page + 1) * args.page_size
        bets = client.fetch_bets(from_record=from_record, to_record=to_record)
        if not bets:
            break

        for b in bets:
            # Minimal normalization for DB insert
            bet = {
                "user_id": USER_ID,
                "account_id": None,
                "provider": b.get("provider", "FanDuel"),
                "date": b.get("date") or "",
                "sport": b.get("sport") or "Unknown",
                "bet_type": b.get("bet_type") or "Straight",
                "wager": float(b.get("wager") or 0.0),
                "profit": float(b.get("profit") or 0.0),
                "status": b.get("status") or "UNKNOWN",
                "description": b.get("description") or b.get("selection") or "(no description)",
                "selection": b.get("selection"),
                "odds": b.get("odds"),
                "closing_odds": None,
                "is_live": bool(b.get("is_live") or False),
                "is_bonus": bool(b.get("is_bonus") or False),
                "raw_text": b.get("raw_text"),
            }

            # Remove broken duplicate (wager=0) if present
            if bet["wager"] > 0:
                deleted_bad += cleanup_bad_row(bet["provider"], bet["date"], bet["description"])

            insert_bet(bet)
            inserted += 1

    print(f"FanDuel API pull complete. Inserted/updated: {inserted}. Cleaned bad rows: {deleted_bad}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
