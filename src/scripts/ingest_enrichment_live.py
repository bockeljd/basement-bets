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

from src.database import init_enrichment_db
from src.scripts.update_data_health import upsert as upsert_health
from src.services.action_enrichment_service import ActionEnrichmentService
from src.services.espn_ncaa_client import ESPNNCAAClient
from src.services.injury_service import InjuryService


def main() -> int:
    init_enrichment_db()

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

    # 2. ESPN pre-game referee assignments & summary injuries
    espn_res = {"matched_events": 0, "crews_saved": 0, "espn_injuries": []}
    try:
        espn_res = ESPNNCAAClient().sync_pregame_officials(dates_yyyymmdd=dates_compact)
    except Exception as exc:
        print(f"[enrich] ESPN officials sync warning: {exc}")

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
        notes=f"games={an_games} splits={an_splits} refs={espn_res.get('crews_saved', 0)} injuries={injuries_saved}",
    )
    print(
        f"[enrich] Complete: action_games={an_games} splits={an_splits} ref_crews={espn_res.get('crews_saved', 0)} injuries={injuries_saved}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
