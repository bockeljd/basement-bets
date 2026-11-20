"""Ingest live NCAAM contextual enrichment before slate generation:
1. Action Network v2 public ticket % and money % splits.
2. ESPN pre-game referee crews (populates referee_assignments).
3. Rotowire + ESPN CBB pre-game injuries (populates action_injuries).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.database import init_enrichment_db, init_events_db, init_team_game_logs_table
from src.scripts.update_data_health import upsert as upsert_health
from src.services.action_enrichment_service import ActionEnrichmentService
from src.services.espn_ncaa_client import ESPNNCAAClient
from src.services.injury_service import InjuryService


def main() -> int:
    init_enrichment_db()
    try:
        init_events_db()
        init_team_game_logs_table()
    except Exception:
        pass

    now_et = datetime.now(ZoneInfo("America/New_York"))
    dates_compact = [
        now_et.strftime("%Y%m%d"),
        (now_et + timedelta(days=1)).strftime("%Y%m%d"),
    ]
    dates_iso = [
        now_et.strftime("%Y-%m-%d"),
        (now_et + timedelta(days=1)).strftime("%Y-%m-%d"),
    ]

    # 1. Action Network v2 public splits (today & tomorrow ET)
    an_games = 0
    an_splits = 0
    an_service = ActionEnrichmentService()
    for d in dates_compact:
        try:
            res = an_service.ingest_enrichment_for_league("NCAAM", date_str=d)
            an_games += int((res or {}).get("games_processed") or (res or {}).get("count") or 0)
            an_splits += int((res or {}).get("splits_saved") or 0)
        except Exception as exc:
            print(f"[enrich] Action Network v2 warning for {d}: {exc}")

    # 2. ESPN pre-game referee assignments, neutral-site/venue metadata & summary injuries
    espn_client = ESPNNCAAClient()
    espn_res = {"matched_events": 0, "crews_saved": 0, "neutral_synced": 0, "espn_injuries": []}
    try:
        espn_res = espn_client.sync_pregame_officials(dates_yyyymmdd=dates_compact)
    except Exception as exc:
        print(f"[enrich] ESPN officials sync warning: {exc}")

    # 2b. Completed D1 boxscore game logs (3PT% shooting regression & Top-25 letdown spots)
    game_logs_saved = 0
    try:
        days_back = int(os.getenv("ENRICH_GAME_LOGS_DAYS_BACK", "1"))
        game_logs_saved = espn_client.sync_completed_game_logs(days_back=days_back)
    except Exception as exc:
        print(f"[enrich] ESPN completed game logs sync warning: {exc}")

    # 3. Rotowire + ESPN injury persistence
    injuries_saved = 0
    try:
        injuries_saved = InjuryService().sync_injuries_for_dates(
            dates_iso=dates_iso,
            extra_espn_injuries=espn_res.get("espn_injuries"),
        )
    except Exception as exc:
        print(f"[enrich] Injuries sync warning: {exc}")

    upsert_health(
        "action_splits",
        "ok" if an_splits > 0 else ("alert" if an_games > 0 else "stale"),
        row_count=an_splits,
        notes=(
            f"games={an_games} splits={an_splits} refs={espn_res.get('crews_saved', 0)} "
            f"neutral={espn_res.get('neutral_synced', 0)} logs={game_logs_saved} injuries={injuries_saved}"
        ),
    )
    print(
        f"[enrich] Complete: action_games={an_games} splits={an_splits} "
        f"ref_crews={espn_res.get('crews_saved', 0)} neutral={espn_res.get('neutral_synced', 0)} "
        f"game_logs={game_logs_saved} injuries={injuries_saved}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
