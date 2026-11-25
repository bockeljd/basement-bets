"""Refresh provisional Top 6 slots and commit eligible picks at their game cutoffs."""
from datetime import datetime, timedelta

from src.database import _exec, get_db_connection, ensure_recommended_slates_tables
from src.utils.ncaam_quotes import is_retail_book
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
        from src.utils.ncaam_slate import SLATE_CTE
        rows = _exec(conn, SLATE_CTE + """
            SELECT d.event_id,d.is_actionable,d.rec_json,d.computed_at,d.model_version,
                   e.start_time,e.home_team,e.away_team,p.id,p.market_type,p.selection,p.bet_line,p.bet_price,p.book,
                   quote.captured_at,quote.price AS current_price,quote.line_value AS current_line,
                   opposite.price AS opposite_price,opposite.line_value AS opposite_line,
                   opposite.captured_at AS opposite_at
            FROM daily_top_picks d JOIN dedup_events e ON e.id=d.event_id
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
        """, (day, day, day, day)).fetchall()
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
        for item in previous.get("provisional", []):
            if item["event_id"] not in seen and now >= datetime.fromisoformat(item["locks_at"]):
                passes[item["event_id"]] = "Missed 30-minute publication deadline"

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
            if not is_retail_book(row["book"]):
                stale_holds[row["event_id"]] = f"{matchup_label} · Awaiting a retail sportsbook price"
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
        pending = []
        for item in provisional:
            deadline = datetime.fromisoformat(item["locks_at"])
            if deadline - now > timedelta(minutes=10):
                pending.append(item)
                continue
            # The scheduled checker runs every five minutes. Never backdate a late run.
            opposite = {"HOME": "AWAY", "AWAY": "HOME", "OVER": "UNDER", "UNDER": "OVER"}[item["side"].upper()]
            params = {**item, "slate": slate_id, "rank": len(seen)+1, "side": item["side"].upper(),
                      "opposite": opposite, "snapshot": Json(item), "deadline": deadline}
            saved = _exec(conn, """
                WITH stamp AS MATERIALIZED (SELECT clock_timestamp() AS published),
                latest AS (
                    SELECT DISTINCT ON (o.side) o.side,o.price,o.line_value,o.captured_at
                    FROM odds_snapshots o CROSS JOIN stamp
                    WHERE o.event_id=%(event_id)s AND o.market_type=%(market_type)s
                      AND lower(o.book)=lower(%(book)s)
                      AND o.captured_at BETWEEN published-interval '90 minutes' AND published
                    ORDER BY o.side,o.captured_at DESC,o.id DESC
                )
                INSERT INTO recommended_slate_items
                    (slate_id,prediction_id,rank,event_id,selection,bet_price,bet_line,market_type,snapshot)
                SELECT %(slate)s,%(id)s,%(rank)s,%(event_id)s,%(selection)s,%(bet_price)s,%(bet_line)s,
                       %(market_type)s,%(snapshot)s::jsonb || jsonb_build_object(
                         'locked_at',published,'quote_captured_at',q.captured_at,
                         'first_qualifying_quote',(
                           SELECT jsonb_build_object('book',a.book,'line',a.line,'price',a.price,
                             'quote_at',a.quote_at,'observed_at',a.observed_at,'ev_cutoff',a.ev_cutoff)
                           FROM ncaam_ev_observations a WHERE a.event_id=%(event_id)s
                             AND a.model_version=%(model_version)s AND a.market=%(market_type)s
                             AND upper(a.side)=%(side)s AND a.cohort='qualified'
                             AND a.observed_at<=published ORDER BY a.observed_at LIMIT 1),
                         'opposite_price',opp.price,'opposite_captured_at',opp.captured_at,
                         'lock_quotes',jsonb_build_object(q.side,to_jsonb(q),opp.side,to_jsonb(opp)))
                FROM stamp JOIN latest q ON q.side=%(side)s JOIN latest opp ON opp.side=%(opposite)s
                JOIN events e ON e.id=%(event_id)s
                WHERE published <= %(deadline)s AND e.start_time-interval '30 minutes'=%(deadline)s
                  AND q.price=%(bet_price)s AND abs(opp.price)>=100
                  AND q.line_value IS NOT DISTINCT FROM %(bet_line)s
                  AND opp.line_value IS NOT DISTINCT FROM
                      (CASE WHEN %(market_type)s LIKE 'SPREAD%%' THEN -q.line_value ELSE q.line_value END)
                RETURNING event_id
            """, params).fetchone()
            if saved:
                seen.add(item["event_id"])
                passes.pop(item["event_id"], None)
            else:
                pending.append(item)
                stale_holds[item["event_id"]] = "Waiting for a verified same-book pair before deadline"
        for rank, item in enumerate(pending, start=len(seen)+1):
            item["rank"] = rank
        provisional = pending
        board = {"provisional": provisional, "passes": passes, "stale_holds": stale_holds, "updated_at": now.isoformat(),
                 "open": len(seen)<6 and any(r["start_time"]-timedelta(minutes=30)>now for r in rows)}
        _exec(conn,"UPDATE recommended_slates SET rolling_board=%s WHERE id=%s",(Json(board),slate_id))
        items = _slate_items(conn, slate_id)
        conn.commit()
        status = "rolling" if board["open"] else ("locked" if items else "no_eligible_picks")
        return {"status": status,
                "slate_id": slate_id, "items": items, **board}
