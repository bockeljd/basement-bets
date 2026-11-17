"""DraftKings automated ingest service (additive).

Orchestrates: DraftKingsIngestService.run_draftkings_ingest()
  1. Start book_ingest_runs row (status=running)
  2. Scrape via DraftKingsScraper.scrape_settled_bets_automated()
  3. Parse with DraftKingsTextParser
  4. Filter + cap
  5. Enrich + bulk-upsert via LedgerWriter
  6. Finalize book_ingest_runs row
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from src.database import get_db_connection, _exec
from src.parsers.draftkings_text import DraftKingsTextParser
from src.scrapers.user_draftkings import DraftKingsScraper, NeedsHumanAuth
from src.books.ledger_writer import LedgerWriter


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _start_ingest_run(conn, book: str, account_id: str) -> int:
    """Insert a book_ingest_runs row and return its id."""
    cur = _exec(
        conn,
        """
        INSERT INTO book_ingest_runs (book, account_id, run_started_at, status)
        VALUES (%s, %s, %s, 'running')
        RETURNING id
        """,
        (book, account_id, _now_utc()),
    )
    row = cur.fetchone()
    conn.commit()
    return int(row["id"])


def _finish_ingest_run(
    conn,
    run_id: int,
    status: str,
    count_parsed: int = 0,
    inserted: int = 0,
    updated: int = 0,
    message: str | None = None,
) -> None:
    _exec(
        conn,
        """
        UPDATE book_ingest_runs
        SET run_finished_at = %s,
            status          = %s,
            count_parsed    = %s,
            inserted        = %s,
            updated         = %s,
            message         = %s
        WHERE id = %s
        """,
        (_now_utc(), status, count_parsed, inserted, updated, message, run_id),
    )
    conn.commit()


def _parse_date(val: Any) -> datetime | None:
    """Robustly convert a date value to datetime (naive/local)."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    if not s:
        return None
    # Try common formats
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d",
        "%b %d, %Y, %I:%M:%S %p",
        "%b %d, %Y",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _latest_existing_dk_placed_at(user_id: str, account_id: str) -> datetime | None:
    """Find the latest placed-at timestamp we already have for DraftKings.

    We use this as an incremental cutoff to avoid duplicates and backfills.
    Falls back to None if no parsable dates exist.

    NOTE: bets.date is stored as text in many legacy rows.
    """
    try:
        with get_db_connection() as conn:
            rows = _exec(
                conn,
                """
                SELECT date
                FROM bets
                WHERE provider='DraftKings'
                  AND user_id=%s
                  AND account_id=%s
                  AND COALESCE(UPPER(status), '') NOT IN ('PENDING', 'OPEN')
                  AND date IS NOT NULL
                ORDER BY id DESC
                LIMIT 250
                """,
                (str(user_id), str(account_id)),
            ).fetchall()
        best = None
        for r in rows:
            d = r['date'] if isinstance(r, dict) else r[0]
            dt = _parse_date(d)
            if dt is None:
                continue
            if best is None or dt > best:
                best = dt
        return best
    except Exception:
        return None


class DraftKingsIngestService:
    """Automated DK settled-bets ingestion service."""

    def run_draftkings_ingest(
        self,
        user_id: str,
        account_id: str = "Main",
    ) -> dict:
        """
        Full ingest run:
          - Scrapes, parses, filters, enriches, bulk-upserts.
          - Tracks result in book_ingest_runs.
          - Uses ONE db connection for the entire write phase.

        Returns:
            dict with keys: status, count_parsed, inserted, updated, message
        """
        newer_than_days = int(os.environ.get("NEWER_THAN_DAYS", "7"))
        max_bets = int(os.environ.get("MAX_BETS_PER_RUN", "50"))

        # Incremental mode (preferred): only ingest bets placed AFTER the latest DK bet
        # already present in the DB for this user+account.
        #
        # Override:
        # - DK_SINCE_PLACED_AT can force a specific cutoff (e.g. "2026-02-20 19:24:00")
        #
        # Fallback:
        # - NEWER_THAN_DAYS window (legacy behavior)
        since_override = os.environ.get("DK_SINCE_PLACED_AT")
        since_dt = _parse_date(since_override) if since_override else None
        if since_dt is None:
            since_dt = _latest_existing_dk_placed_at(user_id=str(user_id), account_id=str(account_id))

        # Legacy safety window if we can't infer a since_dt
        cutoff = since_dt or (datetime.now() - timedelta(days=newer_than_days))

        with get_db_connection() as conn:
            run_id = _start_ingest_run(conn, "DraftKings", account_id)

        raw_text = None
        status = "error"
        count_parsed = 0
        inserted = 0
        updated = 0
        message = None

        try:
            # 1. Scrape (settled + open bets)
            scraper = DraftKingsScraper()
            raw_text = scraper.scrape_settled_bets_automated(include_open=True)

            # 2. Parse
            parser = DraftKingsTextParser()
            parsed = parser.parse(raw_text)
            count_parsed = len(parsed)

            # 3. Filter by placed-at (incremental): keep only bets newer than cutoff
            # Also filter out obvious UI artifacts (e.g. 'MY BETS', 'BET SLIP', 'POPULAR', promo shells).
            def _looks_like_artifact(b: dict) -> bool:
                try:
                    sel = str(b.get('selection') or '').strip().lower()
                    desc = str(b.get('description') or '').strip().lower()
                    rawt = str(b.get('raw_text') or '').strip().lower()
                    noise = {'my bets', 'bet slip', 'popular', 'all', 'create group', 'view picks'}
                    if sel in noise:
                        return True
                    if 'bet & get' in desc or 'bet & get' in rawt:
                        return True
                    if 'your picks will show up here' in rawt:
                        return True
                    return False
                except Exception:
                    return False

            filtered = []
            for bet in parsed:
                if _looks_like_artifact(bet):
                    continue

                dt = _parse_date(bet.get("date"))
                # If date missing/unparseable, keep it (conservative) but these should be rare.
                if dt is None:
                    filtered.append(bet)
                    continue

                # Include open bets and >= cutoff so same-timestamp PENDING bets can settle cleanly.
                if str(bet.get("status") or "").upper() in ("PENDING", "OPEN") or dt >= cutoff:
                    filtered.append(bet)

            # 4. Cap
            filtered = filtered[:max_bets]

            # 5. Enrich
            import hashlib
            for bet in filtered:
                if not bet.get("external_id"):
                    raw = bet.get("raw_text") or str(bet)
                    h = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
                    bet["external_id"] = f"dk_scrape_{h[:16]}"
                bet["provider"]   = "DraftKings"
                bet["user_id"]    = str(user_id)
                bet["account_id"] = account_id
                bet["source"]     = "dk_scrape"

            # 6. Bulk upsert
            writer = LedgerWriter()
            with get_db_connection() as conn:
                inserted, updated = writer.upsert_bets(conn, filtered)

            status = "success"
            message = (
                f"Parsed {count_parsed}, cutoff>{cutoff}, filtered to {len(filtered)}, "
                f"inserted {inserted}, updated {updated}."
            )

        except NeedsHumanAuth as e:
            status = "needs_auth"
            message = str(e)

        except Exception as e:
            status = "error"
            message = f"{type(e).__name__}: {e}"

        finally:
            with get_db_connection() as conn:
                _finish_ingest_run(
                    conn,
                    run_id,
                    status=status,
                    count_parsed=count_parsed,
                    inserted=inserted,
                    updated=updated,
                    message=message,
                )

        return {
            "status": status,
            "count_parsed": count_parsed,
            "inserted": inserted,
            "updated": updated,
            "message": message,
        }
