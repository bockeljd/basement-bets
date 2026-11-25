from datetime import datetime, timedelta, timezone

from src.services.ncaam_holdout import score_published
from src.utils.ncaam_quotes import recent_retail_quote


def test_recent_retail_quote_requires_a_named_book_and_past_capture():
    now = datetime.now(timezone.utc)
    quote = {"book": "FanDuel", "captured_at": now.isoformat()}
    assert recent_retail_quote(quote, now)
    for stamp in (None, now + timedelta(seconds=1), now - timedelta(minutes=91)):
        assert not recent_retail_quote({**quote, "captured_at": stamp}, now)
    assert not recent_retail_quote({**quote, "book": "Consensus"}, now)


def test_holdout_scores_identical_observations_for_all_three_methods():
    now = datetime.now(timezone.utc)
    snap = {"win_prob": 0.54, "raw_win_prob": 0.56, "opposite_price": -110,
            "calibration": {"source": "database", "fit_completed_at": (now-timedelta(days=1)).isoformat()}}
    row = {"published_at": now, "start_time": now+timedelta(hours=2), "outcome": "WON",
           "market_type": "TOTAL", "bet_price": -110, "snapshot": snap}
    report = score_published([row, {**row, "outcome": "PUSH"}, {**row, "start_time": now}])
    assert report["coverage"] == {"published": 3, "scored": 1, "pending_push_or_void": 1, "late_publication": 1}
    for method, prob in (("raw", 0.56), ("calibrated", 0.54), ("market", 0.5)):
        assert report["markets"]["TOTAL"][method]["brier"] == (1-prob)**2


def test_postgres_publisher_freezes_first_six_and_retries(monkeypatch):
    """Run against a private schema in an explicitly supplied integration database."""
    import os
    import uuid
    from concurrent.futures import ThreadPoolExecutor

    import psycopg2
    import pytest
    from psycopg2.extensions import make_dsn
    from psycopg2.extras import Json
    from src import database as db
    from src.services.ncaam_publisher import publish_slate

    dsn = os.getenv("NCAAM_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set NCAAM_TEST_DATABASE_URL to exercise PostgreSQL publication")
    schema = "publisher_test_" + uuid.uuid4().hex
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(f"CREATE SCHEMA {schema}")
        isolated = make_dsn(dsn, options=f"-c search_path={schema}")
        monkeypatch.setattr(db.settings, "DATABASE_URL", isolated)
        monkeypatch.setattr(db.settings, "DATABASE_URL_UNPOOLED", isolated)
        monkeypatch.setenv("DB_REUSE_CONNECTION", "0")
        for initialize in (db.init_events_db, db.init_game_results_db, db.init_snapshots_db,
                           db.init_daily_top_picks_db, db.init_model_history_db):
            initialize()
        from src.scripts.build_daily_top_picks import ensure_table, archive_ev_observations
        from src.services.ncaam_quote_tracking import capture_due_quotes
        ensure_table()
        with pytest.raises(RuntimeError, match="cache unavailable"):
            publish_slate()
        with db.get_db_connection() as conn:
            for index in range(8):
                event_id = f"event_{index}"
                prediction_id = f"prediction_{index}"
                db._exec(conn, """INSERT INTO events(id,home_team,away_team,league,start_time) VALUES (%s,%s,%s,'NCAAM',
                    (date_trunc('day',NOW() AT TIME ZONE 'America/New_York') +
                     interval '1 day - 1 microsecond') AT TIME ZONE 'America/New_York')""", (event_id,event_id+" home",event_id+" away"))
                db._exec(conn, """INSERT INTO model_predictions
                    (id,event_id,prediction_key,market_type,selection,model_version,bet_line,bet_price,book)
                    VALUES (%s,%s,%s,'TOTAL','OVER','test',140,-110,'DraftKings')""",
                    (prediction_id,event_id,prediction_id))
                db._exec(conn, """INSERT INTO daily_top_picks
                    (date_et,event_id,is_actionable,model_version,rec_json)
                    VALUES ((NOW() AT TIME ZONE 'America/New_York')::date,%s,true,'test',%s)""",
                    (event_id,Json({"prediction_id": prediction_id,"side": "over","ev": 0.1})))
                db._exec(conn, """INSERT INTO odds_snapshots
                    (event_id,market_type,side,line_value,price,book)
                    VALUES (%s,'TOTAL','OVER',%s,-110,'DraftKings')""",
                    (event_id, 145 if index == 0 else 140))
            conn.commit()
        initial = publish_slate()
        assert initial["status"] == "rolling"
        assert not initial["items"]
        assert [p["event_id"] for p in initial["provisional"]] == [f"event_{i}" for i in range(1,7)]
        # Enter the ten-minute publication window. One game has already missed it.
        with db.get_db_connection() as conn:
            db._exec(conn, "UPDATE events SET start_time=now()+interval '35 minutes'")
            db._exec(conn, "UPDATE events SET start_time=now()+interval '29 minutes' WHERE id='event_1'")
            db._exec(conn, """INSERT INTO odds_snapshots(event_id,market_type,side,line_value,price,book)
                SELECT id,'TOTAL','UNDER',140,-110,'DraftKings' FROM events""")
            db._exec(conn, "UPDATE odds_snapshots SET price=-125 WHERE event_id='event_2' AND side='OVER'")
            db._exec(conn, "ALTER TABLE recommended_slate_items ADD CONSTRAINT force_item_failure CHECK(rank < 2)")
            conn.commit()
        with pytest.raises(psycopg2.errors.CheckViolation):
            publish_slate()
        with db.get_db_connection() as conn:
            assert db._exec(conn, "SELECT COUNT(*) FROM recommended_slate_items").fetchone()[0] == 0
            db._exec(conn, "ALTER TABLE recommended_slate_items DROP CONSTRAINT force_item_failure")
            conn.commit()
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: publish_slate(), range(2)))
        assert results[0]["items"] == results[1]["items"]
        assert [i["rank"] for i in results[0]["items"]] == list(range(1,6))
        assert {i["event_id"] for i in results[0]["items"]} == {f"event_{i}" for i in range(3,8)}
        with db.get_db_connection() as conn:
            snapshots = db._exec(conn, "SELECT snapshot FROM recommended_slate_items").fetchall()
            assert all(row[0]["locked_at"] <= row[0]["locks_at"] for row in snapshots)
            assert all(set(row[0]["lock_quotes"]) == {"OVER","UNDER"} for row in snapshots)
            # The first qualifying quote survives line changes, a retry and a post-tip price.
            for market, side, other, line, changed in [
                ("SPREAD","HOME","AWAY",3.5,4.0), ("TOTAL","UNDER","OVER",140.,141.5),
                ("MONEYLINE","AWAY","HOME",None,None),
            ]:
                for minutes, price, point in [(45,-110,line),(40,-105,changed),(3,-115,changed),(0,-150,changed)]:
                    for team, val in ((side,point),(other,-point if market=="SPREAD" else point)):
                        db._exec(conn, """INSERT INTO odds_snapshots
                            (event_id,market_type,side,book,price,line_value,captured_at)
                            VALUES ('event_3',%s,%s,'FanDuel',%s,%s,now()-%s*interval '1 minute')""",
                            (market,team,price,val,minutes))
                    if minutes in (45,40):
                        obs = dict(market=market,side=side.lower(),line=point,price=price,book="FanDuel",
                                   gate_ev=.08,ev_cutoff=.05,win_prob=.58,cohort="qualified")
                        archive_ev_observations(conn,"event_3",{"model_version":"test","ev_observations":[obs,obs]})
            db._exec(conn,"UPDATE events SET start_time=now()-interval '1 minute' WHERE id='event_3'")
            capture_due_quotes(conn)
            capture_due_quotes(conn)
            rows = db._exec(conn,"SELECT side,price,lock_quotes,close_quotes FROM ncaam_ev_observations").fetchall()
            assert len(rows) == 3
            for side, first, lock, close in rows:
                assert first == -110
                assert len(lock["sides"]) == len(close["sides"]) == 2
                assert lock["sides"][side.upper()]["price"] == -105
                assert close["sides"][side.upper()]["price"] == -115
                assert close["sides"][side.upper()]["fresh"]
            assert db._exec(conn,"SELECT count(*) FROM ncaam_ev_quote_history").fetchone()[0] == 6
            boards = db._exec(conn,"SELECT stage,quotes FROM ncaam_market_checkpoints WHERE event_id='event_3'").fetchall()
            assert len(boards) == 2
            for stage, quotes in boards:
                assert set(quotes["fanduel"]) == {"SPREAD","TOTAL","MONEYLINE"}
                assert quotes["fanduel"]["SPREAD"]["AWAY"]["line"] == -4.
                assert quotes["fanduel"]["MONEYLINE"]["HOME"]["line"] is None
                assert quotes["fanduel"]["TOTAL"]["OVER"]["price"] == (-105 if stage=="lock" else -115)
            official = db._exec(conn,"SELECT snapshot FROM recommended_slate_items WHERE event_id='event_3'").fetchone()[0]
            assert official["close_quotes"]["book"] == "DraftKings"
    finally:
        with admin.cursor() as cur:
            cur.execute(f"DROP SCHEMA {schema} CASCADE")
        admin.close()


def test_total_odds_stay_on_their_quoted_lines(monkeypatch):
    from src.services.odds_adapter import OddsAdapter
    from src.services.odds_fetcher_service import OddsFetcherService

    lines = OddsFetcherService._extract_market_dict({"event":{"total":[
        {"side":"over","value":142.5,"odds":-105},
        {"side":"under","value":141.5,"odds":-115},
    ]}})
    adapter = OddsAdapter()
    monkeypatch.setattr(adapter, "_upsert_action_network_event", lambda *_: "test")
    rows = adapter._from_action_network({"game_id":1,"book_lines":{"FanDuel":lines}},
                                        "NCAAM",datetime.now(timezone.utc))
    assert [(s["side"],s["line_value"],s["price"]) for s in rows if s["book"]=="FanDuel"] == [
        ("OVER",142.5,-105),("UNDER",141.5,-115)]
