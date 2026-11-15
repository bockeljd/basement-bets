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


def load_sync_env() -> None:
    """Load workspace .env and ~/.basement_bets_kenpom.env without overwriting explicit env vars."""
    for env_path in (Path.home() / ".basement_bets_kenpom.env", REPO_ROOT / ".env"):
        try:
            if env_path.exists():
                load_dotenv(env_path, override=False)
        except OSError:
            pass


# Allow API-only sync runs (without local Postgres) when DATABASE_URL is not configured.
load_sync_env()
if not (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("POSTGRES_PRISMA_URL")):
    os.environ.setdefault("REQUIRE_DATABASE", "0")

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


def build_kenpom_bundle_from_session(sess: requests.Session, sleep_s: float = 1.8) -> dict:
    """Fetch all 7 KenPom pages using an authenticated session and return a _kp_bundle dict."""
    bundle: dict[str, object] = {"_kp_bundle": 1}
    for key, paths, max_rows in KENPOM_ENDPOINTS:
        tsv = ""
        for path in paths:
            try:
                html = fetch_html(sess, path)
                if "register-kenpom" in (html or "").lower() or (
                    key != "ratings" and 'id="login"' in (html or "") and "logout" not in (html or "").lower()
                ):
                    print(f"[mac-kenpom] {key} ({path}) requires active subscriber login; skipping fallbacks")
                    break
                tsv = _html_table_to_tsv(html, max_rows=max_rows)
                if tsv and (key != "ratings" or len(tsv.splitlines()) >= 10):
                    break
            except Exception as exc:
                msg = str(exc)
                print(f"[mac-kenpom] {key} ({path}) warning: {msg}")
                if "429" in msg:
                    # Back off politely instead of hammering fallback URLs on rate-limit
                    if sleep_s > 0:
                        time.sleep(max(sleep_s * 2.0, 3.0))
                    break
        bundle[key] = tsv
        if sleep_s > 0 and key != KENPOM_ENDPOINTS[-1][0]:
            time.sleep(sleep_s)
    return bundle


def fetch_torvik_bundle_data(season_year: int | None = None, days_back: int = 5) -> dict:
    """Fetch BartTorvik efficiency ratings JSON + recent ESPN D1 boxscore game logs."""
    from datetime import timedelta
    from src.utils.ncaam_season import current_ncaam_season_end_year

    year_val = int(season_year or current_ncaam_season_end_year())
    out: dict[str, object] = {}

    sess = requests.Session()
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
    })

    # 1. Team efficiency ratings + luck / continuity (BartTorvik static JSON endpoint)
    try:
        url = f"https://barttorvik.com/{year_val}_team_results.json"
        resp = sess.get(url, timeout=25)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) >= 100:
                out["torvik_teams"] = data
                print(f"[mac-torvik] Pulled {len(data)} teams from {year_val}_team_results.json")
            else:
                print(f"[mac-torvik] Unexpected team_results payload size: {len(data) if isinstance(data, list) else type(data).__name__}")
        else:
            print(f"[mac-torvik] team_results HTTP {resp.status_code}")
    except Exception as exc:
        print(f"[mac-torvik] team_results warning: {exc}")

    # 2. Recent completed D1 game logs (including 3PT% for shooting regression) via public ESPN API
    logs: list[dict] = []
    seen_logs: set[tuple[str, str, str]] = set()
    today_dt = datetime.now(timezone.utc)
    espn_url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
    for offset in range(max(0, int(days_back))):
        dt = today_dt - timedelta(days=offset)
        date_compact = dt.strftime("%Y%m%d")
        date_iso = dt.strftime("%Y-%m-%d")
        try:
            r = sess.get(espn_url, params={"groups": 50, "limit": 1000, "dates": date_compact}, timeout=15)
            if r.status_code != 200:
                continue
            payload = r.json()
            for ev in payload.get("events") or []:
                status_type = ((ev.get("status") or {}).get("type") or {})
                if not status_type.get("completed"):
                    continue
                comps = ev.get("competitions") or []
                if not comps:
                    continue
                competitors = comps[0].get("competitors") or []
                if len(competitors) != 2:
                    continue

                def _stat_map(comp: dict) -> dict[str, float]:
                    smap: dict[str, float] = {}
                    for item in comp.get("statistics") or []:
                        name = item.get("name")
                        val = item.get("displayValue")
                        if name and val is not None:
                            try:
                                smap[str(name)] = float(val)
                            except (TypeError, ValueError):
                                pass
                    return smap

                parsed = []
                for comp in competitors:
                    team_info = comp.get("team") or {}
                    t_name = str(
                        team_info.get("shortDisplayName")
                        or team_info.get("location")
                        or team_info.get("displayName")
                        or ""
                    ).strip()
                    try:
                        score = int(round(float(comp.get("score"))))
                    except (TypeError, ValueError):
                        score = None
                    if not t_name or score is None:
                        continue
                    stats = _stat_map(comp)
                    fg3m = stats.get("threePointFieldGoalsMade")
                    fg3a = stats.get("threePointFieldGoalsAttempted")
                    fg3_pct_raw = stats.get("threePointFieldGoalPct")
                    fg3_pct = None
                    if fg3_pct_raw is not None:
                        fg3_pct = round(fg3_pct_raw / 100.0 if fg3_pct_raw > 1.0 else fg3_pct_raw, 4)
                    parsed.append({
                        "team": t_name,
                        "is_home": str(comp.get("homeAway") or "").lower() == "home",
                        "score": score,
                        "fg3m": int(round(fg3m)) if fg3m is not None else None,
                        "fg3a": int(round(fg3a)) if fg3a is not None else None,
                        "fg3_pct": fg3_pct,
                    })

                if len(parsed) != 2:
                    continue
                a_info, b_info = parsed[0], parsed[1]
                g_date = str(ev.get("date") or date_iso)[:10]
                for side_i, opp_i in ((a_info, b_info), (b_info, a_info)):
                    key = (side_i["team"], g_date, opp_i["team"])
                    if key in seen_logs:
                        continue
                    seen_logs.add(key)
                    logs.append({
                        "team_text": side_i["team"],
                        "game_date": g_date,
                        "opponent": opp_i["team"],
                        "points": side_i["score"],
                        "three_p_made": side_i["fg3m"],
                        "three_p_attempted": side_i["fg3a"],
                        "three_p_pct": side_i["fg3_pct"],
                        "fouls": None,
                        "opponent_rank": None,
                        "is_home": side_i["is_home"],
                        "margin": side_i["score"] - opp_i["score"],
                    })
        except Exception:
            continue
        if offset + 1 < int(days_back):
            time.sleep(0.15)

    if logs:
        out["torvik_game_logs"] = logs
        print(f"[mac-torvik] Pulled {len(logs)} completed ESPN D1 game-log rows")
    return out


def upload_bundle_to_api(
    bundle_json: str,
    app_url: str,
    basement_password: str | None = None,
    timeout: int = 90,
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

    torvik_extra = fetch_torvik_bundle_data()
    if torvik_extra:
        bundle.update(torvik_extra)
        summary["torvik_teams"] = len(torvik_extra.get("torvik_teams") or [])
        summary["torvik_game_logs"] = len(torvik_extra.get("torvik_game_logs") or [])

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


def check_setup() -> dict:
    """Return non-secret readiness status for Mac KenPom syncing."""
    home_env = Path.home() / ".basement_bets_kenpom.env"
    plist_path = Path.home() / "Library" / "LaunchAgents" / "com.basementbets.kenpom-sync.plist"
    try:
        import cloudscraper  # noqa: F401
        has_cloudscraper = True
    except ImportError:
        has_cloudscraper = False
    return {
        "has_cloudscraper": has_cloudscraper,
        "has_env_file": home_env.exists(),
        "has_credentials": bool(
            (os.getenv("KENPOM_EMAIL") and os.getenv("KENPOM_PASSWORD"))
            or os.getenv("KENPOM_COOKIE")
        ),
        "has_launchagent": plist_path.exists(),
        "app_url": (os.getenv("BASEMENT_BETS_URL") or DEFAULT_APP_URL).strip(),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Daily Mac full-bundle KenPom sync")
    parser.add_argument("--dry-run", action="store_true", help="Fetch from KenPom without uploading")
    parser.add_argument("--check", action="store_true", help="Print local setup readiness without network calls")
    args = parser.parse_args()
    if args.check:
        print(json.dumps(check_setup(), indent=2))
        return
    run_mac_sync(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
