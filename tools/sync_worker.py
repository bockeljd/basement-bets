#!/usr/bin/env python3
"""Local sync worker for Basement Bets.

This runs on your Mac (NOT Vercel). It polls Neon for queued sync jobs and executes
DraftKings/FanDuel sync using a real browser session.

Usage:
  cd /Users/basementai/clawd/repos/basement-bets
  source .venv311/bin/activate
  python tools/sync_worker.py --once
  python tools/sync_worker.py

Notes:
- Uses Chrome.
- If login is required, it will open the site and wait (best-effort).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.sync_jobs import (
    claim_next_job,
    mark_job_done,
    mark_job_error,
    mark_job_needs_login,
    DEFAULT_USER_ID,
)
from src.database import insert_bet_v2


def open_url(url: str) -> None:
    try:
        subprocess.run(["open", "-a", "Google Chrome", url], check=False)
    except Exception:
        pass


def run_draftkings(job: dict) -> dict:
    # Use persistent Chrome profile stored in repo to keep DK session.
    from src.scrapers.user_draftkings import DraftKingsScraper
    from src.parsers.draftkings_text import DraftKingsTextParser

    profile_path = os.path.join(REPO_ROOT, "chrome_profile")

    scraper = DraftKingsScraper(profile_path=profile_path)
    raw_text = scraper.scrape()

    # Quick login detection heuristic
    if raw_text and ("Log In" in raw_text and "Sign Up" in raw_text):
        open_url("https://sportsbook.draftkings.com/")
        mark_job_needs_login(job["id"], "DraftKings login required (opened Chrome)")
        # wait a bit for the user to login then retry once
        time.sleep(10)
        raw_text = scraper.scrape()

    parser = DraftKingsTextParser()
    bets = parser.parse(raw_text or "")

    inserted = 0
    for b in bets:
        b["user_id"] = job.get("user_id") or DEFAULT_USER_ID
        b["account_id"] = None
        try:
            insert_bet_v2(b)
            inserted += 1
        except Exception:
            # keep going
            pass

    return {"provider": "draftkings", "parsed": len(bets), "upserted": inserted}


def run_fanduel(job: dict) -> dict:
    from src.scrapers.user_fanduel_pw import FanDuelScraperPW
    from src.parsers.fanduel import FanDuelParser

    scraper = FanDuelScraperPW()
    raw_text = scraper.scrape()

    # If login required, the scraper already opens chrome; mark needs login if we see clear signals.
    if raw_text and ("Log in" in raw_text and "Join now" in raw_text):
        open_url("https://oh.sportsbook.fanduel.com/")
        mark_job_needs_login(job["id"], "FanDuel login required (opened Chrome)")

    parser = FanDuelParser()
    bets = parser.parse(raw_text or "")

    inserted = 0
    for b in bets:
        b["user_id"] = job.get("user_id") or DEFAULT_USER_ID
        b["account_id"] = None
        try:
            insert_bet_v2(b)
            inserted += 1
        except Exception:
            pass

    return {"provider": "fanduel", "parsed": len(bets), "upserted": inserted}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="Run a single job then exit")
    ap.add_argument("--poll-seconds", type=int, default=20)
    ap.add_argument("--worker-id", default=f"mac-{os.uname().nodename}")
    args = ap.parse_args()

    while True:
        job = claim_next_job(worker_id=args.worker_id)
        if not job:
            if args.once:
                return 0
            time.sleep(args.poll_seconds)
            continue

        try:
            provider = job.get("provider")
            if provider == "draftkings":
                meta = run_draftkings(job)
            elif provider == "fanduel":
                meta = run_fanduel(job)
            else:
                raise RuntimeError(f"Unknown provider: {provider}")

            mark_job_done(job["id"], meta=meta)
        except Exception as e:
            mark_job_error(job["id"], str(e))

        if args.once:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
