"""BartTorvik schedule/projection ingestion.

We want BOTH:
- Official Torvik daily schedule/projection JSON (schedule.php?date=YYYYMMDD&json=1)
- Our own computed Torvik-style projections from bt_team_metrics_daily

Problem:
- BartTorvik often returns a bot-check HTML page to plain requests.

Solution:
- In serverless environments: best-effort requests only (record BLOCKED)
- On a trusted machine (macOS cron): allow a Selenium/undetected_chromedriver fallback
  to retrieve the JSON, then store it in Postgres so Vercel can read it.

This module is intentionally standalone so modeling doesn't hang.
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime
from typing import Any, Optional

import requests

from src.database import get_db_connection, _exec


def ensure_bt_schedule_tables() -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS bt_daily_schedule_raw (
      id BIGSERIAL PRIMARY KEY,
      date TEXT NOT NULL,
      payload_json JSONB,
      status TEXT NOT NULL,
      error TEXT,
      fingerprint TEXT UNIQUE,
      created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_bt_sched_date ON bt_daily_schedule_raw(date);
    """
    from src.database import get_admin_db_connection
    with get_admin_db_connection() as conn:
        for stmt in [s.strip() for s in ddl.split(';') if s.strip()]:
            _exec(conn, stmt)
        conn.commit()


def _fingerprint(date: str, payload: Any, status: str) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str) if payload is not None else ""
    return hashlib.sha256(f"{date}|{status}|{raw}".encode()).hexdigest()


def fetch_bt_schedule_json(date_yyyymmdd: str) -> tuple[Optional[Any], Optional[str]]:
    """Fetch schedule JSON via requests. Returns (payload, error)."""
    url = f"https://barttorvik.com/schedule.php?date={date_yyyymmdd}&json=1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://barttorvik.com/trank.php",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"
        try:
            return resp.json(), None
        except Exception:
            text = (resp.text or "")[:200]
            return None, f"Non-JSON response: {text!r}"
    except Exception as e:
        return None, str(e)


def fetch_bt_schedule_selenium(date_yyyymmdd: str) -> tuple[Optional[Any], Optional[str]]:
    """Fetch schedule JSON using Selenium/undetected_chromedriver.

    Intended for trusted local machines only (NOT serverless).
    Returns (payload, error).
    """
    try:
        from src.selenium_client import SeleniumClient
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        url = f"https://barttorvik.com/schedule.php?date={date_yyyymmdd}&json=1"
        client = SeleniumClient(headless=True)
        try:
            d = client.driver
            d.get(url)

            # If the response is JSON, it often renders in <pre>.
            # Wait for pre and parse.
            pre = WebDriverWait(d, 20).until(EC.presence_of_element_located((By.TAG_NAME, 'pre')))
            txt = pre.text
            payload = json.loads(txt)
            return payload, None
        finally:
            try:
                client.quit()
            except Exception:
                pass

    except Exception as e:
        return None, str(e)


def record_bt_schedule_raw(date_yyyymmdd: str, payload: Any, status: str, error: Optional[str] = None) -> None:
    ensure_bt_schedule_tables()
    fp = _fingerprint(date_yyyymmdd, payload, status)
    with get_db_connection() as conn:
        _exec(
            conn,
            """
            INSERT INTO bt_daily_schedule_raw (date, payload_json, status, error, fingerprint)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (fingerprint) DO NOTHING
            """,
            (date_yyyymmdd, payload, status, (error or None), fp),
        )
        conn.commit()


def ingest_daily_schedule(date_yyyymmdd: str, allow_selenium: bool = False) -> dict:
    """Ingest Torvik daily schedule/projections.

    - Always tries requests first.
    - If blocked and allow_selenium=True, tries Selenium fallback.
    """
    payload, err = fetch_bt_schedule_json(date_yyyymmdd)
    if payload is None and allow_selenium:
        payload, err = fetch_bt_schedule_selenium(date_yyyymmdd)

    if payload is None:
        record_bt_schedule_raw(date_yyyymmdd, None, status="BLOCKED", error=err)
        return {"status": "blocked", "date": date_yyyymmdd, "error": err}

    record_bt_schedule_raw(date_yyyymmdd, payload, status="OK", error=None)
    return {"status": "ok", "date": date_yyyymmdd, "games": len(payload) if isinstance(payload, list) else None}
