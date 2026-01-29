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
    """Fetch schedule/projections using Selenium.

    Torvik's `json=1` endpoint is frequently blocked or returns HTML.
    In a real browser session, the schedule page contains the official
    T-Rank line and projected score in the table. We scrape that.

    Intended for trusted local machines only (NOT serverless).
    Returns (payload, error) where payload is a list[dict].
    """

    import re

    def _clean_team(s: str) -> str:
        s = (s or "").strip()
        # strip leading rank like "19 Tennessee"
        s = re.sub(r"^\d+\s+", "", s)
        return s.strip()

    try:
        from bs4 import BeautifulSoup
        from src.selenium_client import SeleniumClient

        url = f"https://barttorvik.com/schedule.php?date={date_yyyymmdd}"

        # Headful tends to pass bot checks more reliably than headless.
        client = SeleniumClient(headless=False)
        try:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC

            d = client.driver
            d.get(url)

            # Wait for the schedule table to render
            try:
                WebDriverWait(d, 25).until(EC.presence_of_element_located((By.TAG_NAME, 'table')))
            except Exception:
                pass

            html = d.page_source or ""
            if "Verifying Browser" in html or "Verifying your browser" in html:
                return None, "Selenium saw Torvik bot-check (Verifying Browser)"

            soup = BeautifulSoup(html, "html.parser")
            table = soup.find("table")
            if not table:
                return None, "No schedule table found"

            payload: list[dict] = []
            for tr in table.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) < 3:
                    continue

                line_text = tds[2].get_text(" ", strip=True)

                # Prefer <a> anchor texts for team names (avoids TV network suffixes).
                matchup_links = [a.get_text(" ", strip=True) for a in tds[1].find_all('a') if a.get_text(strip=True)]
                if len(matchup_links) >= 2:
                    away = _clean_team(matchup_links[0])
                    home = _clean_team(matchup_links[1])
                else:
                    matchup_text = tds[1].get_text(" ", strip=True)
                    if " at " not in matchup_text:
                        continue
                    away_raw, home_raw = matchup_text.split(" at ", 1)
                    away = _clean_team(away_raw)
                    home = _clean_team(re.split(r"\s{2,}", home_raw)[0])

                # Line/projection cell like:
                # "Auburn -6.5 , 84-78 (72%)" OR "Tennessee -0.9 , 80-79 (53%)"
                fav_m = re.search(r"^(.+?)\s+([+-]?\d+(?:\.\d+)?)\s*,", line_text)
                score_m = re.search(r",\s*(\d+)-(\d+)\s*\(", line_text)
                if not fav_m or not score_m:
                    continue

                favored_team = _clean_team(fav_m.group(1))
                spread = float(fav_m.group(2))
                s1 = float(score_m.group(1))
                s2 = float(score_m.group(2))

                # Convert to home-relative spread.
                if favored_team.lower() == home.lower():
                    home_spread = spread  # negative
                    home_score, away_score = s1, s2
                else:
                    home_spread = abs(spread)  # home is underdog
                    away_score, home_score = s1, s2

                total = home_score + away_score

                payload.append(
                    {
                        "away": away,
                        "home": home,
                        "home_spread": home_spread,
                        "away_score": away_score,
                        "home_score": home_score,
                        "total": total,
                        "line_text": line_text,
                    }
                )

            if not payload:
                return None, "Parsed 0 games from schedule table"

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
    from psycopg2.extras import Json

    with get_db_connection() as conn:
        _exec(
            conn,
            """
            INSERT INTO bt_daily_schedule_raw (date, payload_json, status, error, fingerprint)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (fingerprint) DO NOTHING
            """,
            (date_yyyymmdd, Json(payload) if payload is not None else None, status, (error or None), fp),
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
