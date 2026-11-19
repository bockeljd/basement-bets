"""Backfill ESPN neutral_site and venue metadata onto NCAAM events across a date range.

Matches both direct (home, away) and swapped (away, home) team pairs so neutral-site
tournaments (MTEs, Feast Week, conference/NCAA tournaments) are flagged accurately.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.database import get_db_connection, _exec, init_events_db
from src.services.espn_ncaa_client import ESPNNCAAClient
from src.services.injury_service import _team_names_match
from src.utils.team_matcher import TeamMatcher


def backfill_neutral_sites(days_back: int = 21, include_tomorrow: bool = True) -> dict:
    init_events_db()
    now_et = datetime.now(ZoneInfo("America/New_York"))
    end_offset = 1 if include_tomorrow else 0
    dates = [
        now_et - timedelta(days=offset)
        for offset in range(days_back, -end_offset - 1, -1)
    ]
    dates_compact = [d.strftime("%Y%m%d") for d in dates]
    dates_iso = [d.strftime("%Y-%m-%d") for d in dates]

    with get_db_connection() as conn:
        rows = _exec(
            conn,
            """
            SELECT id, home_team, away_team,
                   COALESCE(neutral_site, FALSE) AS neutral_site,
                   DATE(start_time AT TIME ZONE 'America/New_York')::text AS day_et
            FROM events
            WHERE league = 'NCAAM'
              AND DATE(start_time AT TIME ZONE 'America/New_York')::text = ANY(%s)
            """,
            (dates_iso,),
        ).fetchall()
    db_events = [dict(r) for r in rows] if rows else []

    by_day: dict[str, list[dict]] = {}
    for row in db_events:
        by_day.setdefault(row["day_et"], []).append(row)

    espn = ESPNNCAAClient()
    matcher = TeamMatcher()
    updated = 0
    newly_neutral = 0
    total_neutral = 0

    with get_db_connection() as conn:
        for d_dt, d_compact, d_iso in zip(dates, dates_compact, dates_iso):
            # Include +/- 1 day candidates for late-night tipoffs near midnight ET
            day_candidates = []
            for delta in (-1, 0, 1):
                k = (d_dt + timedelta(days=delta)).strftime("%Y-%m-%d")
                day_candidates.extend(by_day.get(k, []))
            if not day_candidates:
                continue

            sb = espn.get_scoreboard(date=d_compact)
            for ev in (sb or {}).get("events", []):
                comps = ev.get("competitions") or []
                if not comps:
                    continue
                comp0 = comps[0]
                competitors = comp0.get("competitors") or []
                h_team = next((c.get("team", {}).get("displayName") for c in competitors if c.get("homeAway") == "home"), None)
                a_team = next((c.get("team", {}).get("displayName") for c in competitors if c.get("homeAway") == "away"), None)
                if not h_team or not a_team:
                    continue

                ns_flag = bool(comp0.get("neutralSite", False))
                venue_obj = comp0.get("venue") or {}
                venue_addr = venue_obj.get("address") or {}
                venue_name = venue_obj.get("fullName")
                venue_city = venue_addr.get("city")
                venue_state = venue_addr.get("state")

                matches = [
                    row
                    for row in day_candidates
                    if (
                        _team_names_match(matcher, row["home_team"], h_team)
                        and _team_names_match(matcher, row["away_team"], a_team)
                    )
                    or (
                        _team_names_match(matcher, row["home_team"], a_team)
                        and _team_names_match(matcher, row["away_team"], h_team)
                    )
                ]
                for row in matches:
                    _exec(
                        conn,
                        """
                        UPDATE events
                        SET neutral_site = %s,
                            venue = COALESCE(%s, venue),
                            venue_city = COALESCE(%s, venue_city),
                            venue_state = COALESCE(%s, venue_state),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (ns_flag, venue_name, venue_city, venue_state, row["id"]),
                    )
                    updated += 1
                    if ns_flag:
                        total_neutral += 1
                        if not row.get("neutral_site"):
                            newly_neutral += 1
                            row["neutral_site"] = True
        conn.commit()

    stats = {
        "days_back": days_back,
        "db_events_scanned": len(db_events),
        "events_updated": updated,
        "total_neutral_events": total_neutral,
        "newly_flagged_neutral": newly_neutral,
    }
    print(f"[neutral_backfill] Complete: {stats}")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill NCAAM neutral_site flags from ESPN")
    parser.add_argument("--days", type=int, default=21, help="Days back to backfill (default: 21)")
    args = parser.parse_args()
    backfill_neutral_sites(days_back=args.days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
