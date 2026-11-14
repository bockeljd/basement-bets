"""Daily Mac background sync for all 7 KenPom subscriber datasets.

Runs from the user's residential Mac IP (so KenPom's Cloudflare firewall allows
authenticated scraping unlike shared cloud/GitHub Actions IPs), builds a compact
`_kp_bundle` JSON payload covering:
  1. Main efficiency ratings + Luck / SOS (`/`)
  2. Team Four Factors (`/stats.php`)
  3. Height, Experience, Bench & Continuity (`/height.php`)
  4. Home Court Advantage (`/hca.php`)
  5. Player Stats (`/playerstats.php?s=ORtg`)
  6. Referee Ratings (`/officials.php`)
  7. FanMatch Daily Predictions (`/fanmatch.php`)

Uploads to `BASEMENT_BETS_URL/api/admin/kenpom/upload-csv` (default:
https://basement-bets.vercel.app) and, if DATABASE_URL is configured locally,
ingests directly into Postgres as well.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.scripts.ingest_kenpom import (  # noqa: E402
    _session,
    _table_headers_and_rows,
    fetch_html,
    ingest_kenpom_csv,
)


DEFAULT_APP_URL = "https://basement-bets.vercel.app"

KENPOM_ENDPOINTS: list[tuple[str, list[str], int | None]] = [
    ("ratings", ["/"], None),
    ("stats", ["/stats.php"], None),
    ("height", ["/height.php"], None),
    ("hca", ["/hca.php", "/home.php"], None),
    ("playerstats", ["/playerstats.php?s=ORtg", "/playerstats.php"], 1500),
    ("refs", ["/officials.php", "/refs.php"], None),
    ("fanmatch", ["/fanmatch.php"], None),
]


def load_sync_env() -> None:
    """Load workspace .env and ~/.basement_bets_kenpom.env without overwriting explicit env vars."""
    home_env = Path.home() / ".basement_bets_kenpom.env"
    if home_env.exists():
        load_dotenv(home_env, override=False)
    repo_env = REPO_ROOT / ".env"
    if repo_env.exists():
        load_dotenv(repo_env, override=False)


def _html_table_to_tsv(html: str, max_rows: int | None = None) -> str:
    """Extract the primary HTML table from a KenPom page as compact tab-separated text."""
    soup = BeautifulSoup(html or "", "html.parser")
    tables = soup.find_all("table")
    if not tables:
        return ""
    table = soup.find("table", {"id": "ratings-table"}) or max(
        tables, key=lambda t: len(t.find_all("tr"))
    )
    headers, rows = _table_headers_and_rows(table)
    if max_rows is not None and max_rows > 0:
        rows = rows[:max_rows]
    lines: list[str] = []
    if headers:
        lines.append("\t".join(str(c).replace("\t", " ").strip() for c in headers))
    for row in rows:
        cleaned = [str(c).replace("\t", " ").strip() for c in row]
        if any(cleaned):
            lines.append("\t".join(cleaned))
    return "\n".join(lines)


def build_kenpom_bundle_from_session(sess: requests.Session, sleep_s: float = 0.7) -> dict:
    """Fetch all 7 KenPom pages using an authenticated session and return a _kp_bundle dict."""
    bundle: dict[str, object] = {"_kp_bundle": 1}
    for key, paths, max_rows in KENPOM_ENDPOINTS:
        tsv = ""
        for path in paths:
            try:
                html = fetch_html(sess, path)
                tsv = _html_table_to_tsv(html, max_rows=max_rows)
                if tsv and (key != "ratings" or len(tsv.splitlines()) >= 10):
                    break
            except Exception as exc:
                print(f"[mac-kenpom] {key} ({path}) warning: {exc}")
        bundle[key] = tsv
        if sleep_s > 0 and key != KENPOM_ENDPOINTS[-1][0]:
            time.sleep(sleep_s)
    return bundle


def upload_bundle_to_api(
    bundle_json: str,
    app_url: str,
    basement_password: str | None = None,
    timeout: int = 60,
) -> dict:
    """POST the `_kp_bundle` JSON payload to Basement Bets `/api/admin/kenpom/upload-csv`."""
    endpoint = app_url.rstrip("/") + "/api/admin/kenpom/upload-csv"
    headers = {"Content-Type": "application/json"}
    if basement_password:
        headers["X-BASEMENT-KEY"] = basement_password.strip()

    resp = requests.post(
        endpoint,
        headers=headers,
        json={"csv_text": bundle_json},
        timeout=timeout,
    )
    if resp.status_code == 403:
        raise RuntimeError(
            "Basement Bets API returned 403 Forbidden. Set BASEMENT_PASSWORD in ~/.basement_bets_kenpom.env."
        )
    resp.raise_for_status()
    return resp.json()


def run_mac_sync(dry_run: bool = False) -> dict:
    load_sync_env()
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting Mac KenPom full-bundle sync...")

    sess = _session()
    bundle = build_kenpom_bundle_from_session(sess)
    ratings_lines = len(str(bundle.get("ratings") or "").splitlines())
    if ratings_lines < 10:
        raise RuntimeError(
            "Could not fetch KenPom ratings table from home IP. Check KENPOM_EMAIL/KENPOM_PASSWORD or KENPOM_COOKIE in ~/.basement_bets_kenpom.env."
        )

    summary = {k: len(str(bundle.get(k) or "").splitlines()) for k, _, _ in KENPOM_ENDPOINTS}
    print(f"[mac-kenpom] Pulled line counts: {summary}")

    bundle_json = json.dumps(bundle)
    if dry_run:
        return {"status": "dry_run", "summary": summary, "payload_bytes": len(bundle_json)}

    results: dict[str, object] = {"summary": summary}

    # 1. Upload to hosted app (Vercel / Neon production DB + cache invalidation)
    app_url = (os.getenv("BASEMENT_BETS_URL") or DEFAULT_APP_URL).strip()
    basement_pw = (os.getenv("BASEMENT_PASSWORD") or "").strip() or None
    if app_url:
        api_res = upload_bundle_to_api(bundle_json, app_url=app_url, basement_password=basement_pw)
        print(f"[mac-kenpom] Uploaded to {app_url}: {api_res}")
        results["api"] = api_res

    # 2. If DATABASE_URL is configured locally and we want local DB sync too
    if os.getenv("DATABASE_URL") and os.getenv("SYNC_LOCAL_DB", "0") == "1":
        db_res = ingest_kenpom_csv(bundle_json)
        print(f"[mac-kenpom] Local DB ingest: {db_res}")
        results["local_db"] = db_res

    return results


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Daily Mac full-bundle KenPom sync")
    parser.add_argument("--dry-run", action="store_true", help="Fetch from KenPom without uploading")
    args = parser.parse_args()
    run_mac_sync(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
