"""Local sync worker for sportsbook bet history.

This is intended to run on the Mac (not in Vercel serverless) because it may
need an interactive browser session for DraftKings.

Usage:
  python scripts/sync_worker.py --once
  python scripts/sync_worker.py --loop

Environment:
  Uses DATABASE_URL / DATABASE_URL_UNPOOLED from src.config.settings.
"""

from __future__ import annotations

import argparse
import os
import sys
import socket
import time
from typing import Optional

# Allow running from repo root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.sync_jobs import (
    DEFAULT_USER_ID,
    claim_next_job,
    mark_job_done,
    mark_job_error,
    mark_job_needs_login,
)


def _worker_id() -> str:
    host = socket.gethostname()
    pid = os.getpid()
    return f"{host}:{pid}"


def _extract_job_account_id(job: dict) -> str:
    import json as _json
    from src.services.bet_sync_service import normalize_account_id

    meta = job.get("meta") or {}
    payload_raw = job.get("payload_json") or {}
    if isinstance(payload_raw, str):
        try:
            payload_raw = _json.loads(payload_raw)
        except Exception:
            payload_raw = {}
    return normalize_account_id(payload_raw.get("account_id") or meta.get("account_id"), default="Main")


def _ingest_bets_v2(user_id: str, provider_label: str, bets: list[dict], account_id: str = "Main", source: str = "sync_worker") -> int:
    """Ingest parsed bet dicts into canonical `bets` via shared bet_sync_service."""
    from src.services.bet_sync_service import ingest_normalized_bets

    res = ingest_normalized_bets(
        bets,
        user_id=str(user_id),
        default_provider=provider_label,
        default_account_id=account_id or "Main",
        source=source,
    )
    return int(res.get("saved", 0))


def _run_fanduel_job(job: dict) -> dict:
    """FanDuel sync using stored token preference (open + settled bets)."""
    from src.database import get_user_preference
    from src.api_clients.fanduel_client import FanDuelAPIClient

    user_id = job.get("user_id")
    account_id = _extract_job_account_id(job)
    token = get_user_preference(str(user_id), "fanduel_token")
    if not token:
        raise RuntimeError("No stored FanDuel token. Use Add Bet -> Sync -> FanDuel Token to save your token first.")

    client = FanDuelAPIClient(auth_token=token)
    bets = client.fetch_all_recent_bets(settled_limit=100, open_limit=50)
    saved = _ingest_bets_v2(
        user_id=str(user_id),
        provider_label="FanDuel",
        bets=bets,
        account_id=account_id,
        source="fanduel_worker",
    )
    return {"bets_fetched": len(bets), "bets_saved": saved, "account_id": account_id}


def _run_draftkings_job(job: dict) -> dict:
    """DraftKings sync via interactive browser automation on the Mac (open + settled bets)."""
    from src.scrapers.user_draftkings import DraftKingsScraper
    from src.parsers.draftkings_text import DraftKingsTextParser

    user_id = job.get("user_id")
    account_id = _extract_job_account_id(job)

    scraper = DraftKingsScraper()
    if hasattr(scraper, "scrape_settled_bets_automated"):
        raw_text = scraper.scrape_settled_bets_automated(include_open=True)
    else:
        raw_text = scraper.scrape()

    parser = DraftKingsTextParser()
    parsed = parser.parse(raw_text)

    saved = _ingest_bets_v2(
        user_id=str(user_id),
        provider_label="DraftKings",
        bets=parsed,
        account_id=account_id,
        source="dk_worker",
    )
    return {"bets_fetched": len(parsed), "bets_saved": saved, "account_id": account_id}


def _run_dk_ingest_job(job: dict) -> dict:
    """
    Automated DraftKings settled-bets ingest using DraftKingsIngestService.
    Claimed by the local worker when job_type='DK_INGEST'.

    Notes:
      - Ensures DK ingest schema exists (book_ingest_runs + sync_jobs columns).
    """
    from src.services.dk_ingest_service import DraftKingsIngestService
    from src.database import init_dk_ingest_db
    import json as _json

    try:
        init_dk_ingest_db()
    except Exception as e:
        print(f"[sync-worker] init_dk_ingest_db warn: {e}")

    meta = job.get("meta") or {}
    # payload_json may be a dict already (psycopg2 JSONB) or a JSON string
    payload_raw = job.get("payload_json") or {}
    if isinstance(payload_raw, str):
        try:
            payload_raw = _json.loads(payload_raw)
        except Exception:
            payload_raw = {}

    user_id = str(payload_raw.get("user_id") or job.get("user_id") or DEFAULT_USER_ID)
    account_id = str(payload_raw.get("account_id") or meta.get("account_id") or "Main")

    svc = DraftKingsIngestService()
    result = svc.run_draftkings_ingest(user_id=user_id, account_id=account_id)
    return result


def process_one(provider: Optional[str] = None) -> bool:
    wid = _worker_id()
    job = claim_next_job(worker_id=wid, provider=provider)
    if not job:
        return False

    job_id = int(job["id"])
    prov = job.get("provider")

    try:
        job_type = job.get("job_type") or ""
        if job_type == "DK_INGEST":
            meta = _run_dk_ingest_job(job)
            mark_job_done(job_id, meta=meta)
            print(f"[sync-worker] DONE DK_INGEST job={job_id} meta={meta}")
        elif prov == "fanduel":
            meta = _run_fanduel_job(job)
            mark_job_done(job_id, meta=meta)
            print(f"[sync-worker] DONE job={job_id} provider={prov} meta={meta}")
        elif prov == "draftkings":
            meta = _run_draftkings_job(job)
            mark_job_done(job_id, meta=meta)
            print(f"[sync-worker] DONE job={job_id} provider={prov} meta={meta}")
        else:
            raise RuntimeError(f"Unknown provider/job_type: {prov}/{job_type}")
        return True

    except Exception as e:
        msg = str(e)
        needs_auth = (
            "NeedsHumanAuth" in type(e).__name__
            or "login timeout" in msg.lower()
            or "login wall" in msg.lower()
            or "please log in" in msg.lower()
            or "login required" in msg.lower()
            or "needs_auth" in msg.lower()
        )
        if needs_auth:
            mark_job_needs_login(job_id, message=msg)
            print(f"[sync-worker] NEEDS_LOGIN job={job_id} err={msg}")
        else:
            mark_job_error(job_id, msg)
            print(f"[sync-worker] ERROR job={job_id} err={msg}")
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--provider", default=None, help="draftkings|fanduel")
    ap.add_argument("--sleep", type=float, default=10.0)
    args = ap.parse_args()

    if not args.once and not args.loop:
        args.loop = True

    if args.once:
        process_one(provider=args.provider)
        return

    while True:
        did = process_one(provider=args.provider)
        if not did:
            time.sleep(args.sleep)


if __name__ == "__main__":
    main()
