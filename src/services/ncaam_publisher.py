"""Refresh provisional Top 6 slots and commit eligible picks at their game cutoffs."""
from datetime import datetime, timedelta

from src.database import _exec, get_db_connection, ensure_recommended_slates_tables
from src.utils.model_performance import rank_top6_items
from psycopg2.extras import Json


def _slate_items(conn, slate_id):
    rows = _exec(conn, """
        SELECT i.rank,i.event_id,i.selection,i.bet_price,i.bet_line,i.market_type,
               e.home_team,e.away_team,e.start_time,i.snapshot->>'book' AS book,
               i.snapshot->>'edge' AS edge,i.snapshot->>'confidence' AS confidence
        FROM recommended_slate_items i LEFT JOIN events e ON e.id=i.event_id
        WHERE i.slate_id=%s AND i.rank BETWEEN 1 AND 6 ORDER BY i.rank
    """, (slate_id,)).fetchall()
    return [dict(row) for row in rows]


def publish_slate(date_et=None):
    ensure_recommended_slates_tables()
    with get_db_connection() as conn:
        _exec(conn, "SET LOCAL TIME ZONE 'UTC'")
        today = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]
        day = str(date_et or today)
        slate_id = f"NCAAM:{day}:cached"
        _exec(conn, "SELECT pg_advisory_xact_lock(hashtext(%s))", (slate_id,))
        existing = _exec(conn, """
            SELECT id,rolling_board FROM recommended_slates WHERE league='NCAAM' AND date_et=%s
            AND source='cached' ORDER BY created_at,id LIMIT 1
        """, (day,)).fetchone()
        if existing and existing["rolling_board"] is None:
            items = _slate_items(conn, existing[0])
            conn.commit()
            return {"status": "already_locked", "slate_id": existing[0], "items": items}
        if day != today:
            raise ValueError("Only today's pregame slate can be published")
        rows = _exec(conn, """
            SELECT d.event_id,d.is_actionable,d.rec_json,d.computed_at,d.model_version,
                   e.start_time,e.home_team,e.away_team,p.id,p.market_type,p.selection,p.bet_line,p.bet_price,p.book,
                   quote.captured_at,quote.price AS current_price,quote.line_value AS current_line,
                   opposite.price AS opposite_price,opposite.line_value AS opposite_line,
                   opposite.captured_at AS opposite_at
            FROM daily_top_picks d JOIN events e ON e.id=d.event_id
            LEFT JOIN model_predictions p ON p.id=d.rec_json->>'prediction_id'
                AND p.event_id=d.event_id AND p.model_version=d.model_version
                AND p.analyzed_at <= NOW() AND p.analyzed_at < e.start_time
            LEFT JOIN LATERAL (
                SELECT o.captured_at,o.price,o.line_value FROM odds_snapshots o
                WHERE o.event_id=p.event_id AND LOWER(COALESCE(o.book,''))=LOWER(COALESCE(p.book,'')) AND o.market_type=p.market_type
                    AND o.side=upper(d.rec_json->>'side')
                    AND o.captured_at BETWEEN NOW()-interval '90 minutes' AND NOW()
                ORDER BY o.captured_at DESC,o.id DESC LIMIT 1
            ) quote ON TRUE
            LEFT JOIN LATERAL (
                SELECT o.price,o.line_value,o.captured_at FROM odds_snapshots o
                WHERE o.event_id=p.event_id AND LOWER(COALESCE(o.book,''))=LOWER(COALESCE(p.book,'')) AND o.market_type=p.market_type
                    AND o.side=CASE upper(d.rec_json->>'side') WHEN 'HOME' THEN 'AWAY'
                        WHEN 'AWAY' THEN 'HOME' WHEN 'OVER' THEN 'UNDER' WHEN 'UNDER' THEN 'OVER' END
                    AND o.captured_at BETWEEN NOW()-interval '90 minutes' AND NOW()
                ORDER BY o.captured_at DESC,o.id DESC LIMIT 1
            ) opposite ON TRUE
            WHERE d.date_et=%s AND d.league='NCAAM' AND e.league='NCAAM'
                AND (e.start_time AT TIME ZONE 'America/New_York')::date=%s::date
            ORDER BY d.event_id
        """, (day, day)).fetchall()
        if not rows and not existing:
            raise RuntimeError("NCAAM daily cache unavailable")
        now = _exec(conn, "SELECT clock_timestamp()").fetchone()[0]
        previous = existing["rolling_board"] if existing else {}
        if not existing:
            _exec(conn, """INSERT INTO recommended_slates(id,league,date_et,source,rolling_board)
                VALUES (%s,'NCAAM',%s,'cached','{}')""", (slate_id, day))
        locked = _slate_items(conn, slate_id)
        seen = {item["event_id"] for item in locked}
        passes = dict(previous.get("passes", {}))
        current = {row["event_id"]: row for row in rows}
        for item in sorted(previous.get("provisional", []), key=lambda p: (p["locks_at"], p["rank"])):
            eid = item["event_id"]
            cutoff = datetime.fromisoformat(item["locks_at"])
            if now < cutoff or eid in seen:
                continue
            row = current.get(eid)
            if not row or row["start_time"] - timedelta(minutes=30) != cutoff:
                continue
            reason = None
            if now >= row["start_time"]:
                reason = "Missed pregame lock"
            elif cutoff - datetime.fromisoformat(item["computed_at"]) > timedelta(minutes=90):
                reason = "Model forecast stale at cutoff"
            elif row["computed_at"] <= cutoff and (
                not row["is_actionable"] or row["id"] != item["id"]
                or row["computed_at"] > datetime.fromisoformat(item["computed_at"])
            ):
                reason = "Forecast changed before cutoff"
            quote = _exec(conn, """SELECT price,line_value,captured_at FROM odds_snapshots
                WHERE event_id=%s AND LOWER(COALESCE(book,''))=LOWER(COALESCE(%s,'')) AND market_type=%s AND side=%s
                  AND captured_at BETWEEN %s - interval '90 minutes' AND %s
                ORDER BY captured_at DESC,id DESC LIMIT 1""",
                (eid,item["book"],item["market_type"],item["side"].upper(),cutoff,cutoff)).fetchone()
            if not quote:
                reason = "Odds stale at cutoff (>90m old)"
            elif quote["price"] != item["bet_price"] or quote["line_value"] != item["bet_line"]:
                reason = "Price changed at cutoff"
            if reason:
                passes[eid] = reason
                continue
            snapshot = {**item, "locked_at": now.isoformat(),
                        "quote_captured_at": quote["captured_at"].isoformat()}
            _exec(conn, """INSERT INTO recommended_slate_items
                (slate_id,prediction_id,rank,event_id,selection,bet_price,bet_line,market_type,snapshot)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (slate_id,item["id"],len(seen)+1,eid,item["selection"],item["bet_price"],
                 item["bet_line"],item["market_type"],Json(snapshot)))
            seen.add(eid)

        candidates = []
        stale_holds = {}
        for row in rows:
            rec = row["rec_json"] or {}
            cutoff = row["start_time"] - timedelta(minutes=30)
            if now >= cutoff or row["event_id"] in seen or not row["is_actionable"] or rec.get("top6_eligible") is False:
                continue
            matchup_label = f"{row['away_team']} @ {row['home_team']}"
            if not row["id"]:
                stale_holds[row["event_id"]] = f"{matchup_label} · Model prediction awaiting persistence"
                continue
            if now - row["computed_at"] > timedelta(minutes=90):
                stale_holds[row["event_id"]] = f"{matchup_label} · Model forecast stale (>90m old)"
                continue
            if not row["captured_at"]:
                stale_holds[row["event_id"]] = f"{matchup_label} · Book odds stale (>90m since last quote for {row['book']})"
                continue
            if row["current_price"] != row["bet_price"] or row["current_line"] != row["bet_line"]:
                stale_holds[row["event_id"]] = f"{matchup_label} · Line moved since last model run — awaiting re-score"
                continue
            item = {**rec, **{k: row[k] for k in ("home_team","away_team","model_version","event_id","id",
                        "selection","book","bet_price","bet_line","market_type")}, "locks_at": cutoff.isoformat(),
                    "computed_at": row["computed_at"].isoformat(), "quote_captured_at": row["captured_at"].isoformat(),
                    "referees": (rec.get("signals") or {}).get("referees")}
            opposite_line = -item["bet_line"] if item["market_type"].startswith("SPREAD") else item["bet_line"]
            if row["opposite_price"] and row["opposite_line"] == opposite_line:
                item.update(opposite_price=row["opposite_price"], opposite_captured_at=row["opposite_at"].isoformat())
            candidates.append(item)
        provisional = rank_top6_items(candidates, limit=6-len(seen)) if len(seen)<6 else []
        board = {"provisional": provisional, "passes": passes, "stale_holds": stale_holds, "updated_at": now.isoformat(),
                 "open": len(seen)<6 and any(r["start_time"]-timedelta(minutes=30)>now for r in rows)}
        _exec(conn,"UPDATE recommended_slates SET rolling_board=%s WHERE id=%s",(Json(board),slate_id))
        items = _slate_items(conn, slate_id)
        conn.commit()
        status = "rolling" if board["open"] else ("locked" if items else "no_eligible_picks")
        return {"status": status,
                "slate_id": slate_id, "items": items, **board}
