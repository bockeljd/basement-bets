"""Ingest daily Haslametrics D1 ratings XML into Postgres and update data_health.

Usage:
  python src/scripts/ingest_haslametrics.py
  python src/scripts/ingest_haslametrics.py --if-stale-hours 4
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.database import _exec, get_admin_db_connection, get_db_connection, init_haslametrics_db
from src.scripts.update_data_health import upsert as upsert_health
from src.services.haslametrics_client import HaslametricsClient


def _hours_since_last_ingest() -> float | None:
    try:
        with get_db_connection() as conn:
            row = _exec(
                conn,
                "SELECT MAX(updated_at) AS ts FROM haslametrics_ratings_daily",
            ).fetchone()
            ts = (dict(row).get("ts") if isinstance(row, dict) or hasattr(row, "keys") else row[0]) if row else None
            if not ts:
                return None
            if getattr(ts, "tzinfo", None) is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Haslametrics XML ratings")
    parser.add_argument(
        "--if-stale-hours",
        type=float,
        default=None,
        help="Skip fetch if last DB ingest occurred within this many hours.",
    )
    args = parser.parse_args()

    init_haslametrics_db()

    if args.if_stale_hours is not None:
        age_h = _hours_since_last_ingest()
        if age_h is not None and age_h < float(args.if_stale_hours):
            print(f"[haslametrics] Skipping ingest; latest snapshot is {age_h:.2f}h old (< {args.if_stale_hours}h)")
            return 0

    client = HaslametricsClient()
    try:
        data = client.fetch_live_ratings()
        teams = data.get("teams") or []
        asof_date = data.get("asof_date")
        if len(teams) < 300:
            raise RuntimeError(f"Expected >=300 D1 teams from Haslametrics XML, got {len(teams)}")

        sql = """
        INSERT INTO haslametrics_ratings_daily(
            asof_date, team_name, rank, conf, record, oe, de, net_eff,
            ou, du, tempo, ap, sos, mom, inc, av_eff, av_pace, hca_eff, hca_pace,
            raw, updated_at
        )
        VALUES (
            %(asof_date)s, %(team_name)s, %(rank)s, %(conf)s, %(record)s, %(oe)s, %(de)s, %(net_eff)s,
            %(ou)s, %(du)s, %(tempo)s, %(ap)s, %(sos)s, %(mom)s, %(inc)s,
            %(av_eff)s, %(av_pace)s, %(hca_eff)s, %(hca_pace)s,
            %(raw)s::jsonb, NOW()
        )
        ON CONFLICT (asof_date, team_name) DO UPDATE SET
            rank=EXCLUDED.rank,
            conf=EXCLUDED.conf,
            record=EXCLUDED.record,
            oe=EXCLUDED.oe,
            de=EXCLUDED.de,
            net_eff=EXCLUDED.net_eff,
            ou=EXCLUDED.ou,
            du=EXCLUDED.du,
            tempo=EXCLUDED.tempo,
            ap=EXCLUDED.ap,
            sos=EXCLUDED.sos,
            mom=EXCLUDED.mom,
            inc=EXCLUDED.inc,
            av_eff=EXCLUDED.av_eff,
            av_pace=EXCLUDED.av_pace,
            hca_eff=EXCLUDED.hca_eff,
            hca_pace=EXCLUDED.hca_pace,
            raw=EXCLUDED.raw,
            updated_at=NOW();
        """
        with get_admin_db_connection() as conn:
            for row in teams:
                _exec(conn, sql, {**row, "raw": json.dumps(row.get("raw") or {})})
            conn.commit()

        upsert_health(
            "haslametrics",
            "ok",
            row_count=len(teams),
            notes=f"haslametrics_ratings_daily asof={asof_date} rows={len(teams)}",
        )
        print(f"[haslametrics] Ingested {len(teams)} teams (asof={asof_date})")
        return 0

    except Exception as exc:
        upsert_health("haslametrics", "error", notes=f"ingest failed: {str(exc)[:220]}")
        print(f"[haslametrics] ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
