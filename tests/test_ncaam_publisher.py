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
        with pytest.raises(RuntimeError, match="cache unavailable"):
            publish_slate()
        with db.get_db_connection() as conn:
            for index in range(8):
                event_id = f"event_{index}"
                prediction_id = f"prediction_{index}"
                db._exec(conn, """INSERT INTO events(id,league,start_time) VALUES (%s,'NCAAM',
                    (date_trunc('day',NOW() AT TIME ZONE 'America/New_York') +
                     interval '1 day - 1 microsecond') AT TIME ZONE 'America/New_York')""", (event_id,))
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
        # Advance the fixtures across their cutoff. The offered quote was observed pre-cutoff.
        with db.get_db_connection() as conn:
            cutoff = db._exec(conn, "SELECT NOW()-interval '1 minute'").fetchone()[0]
            for p in initial["provisional"]:
                p["locks_at"] = cutoff.isoformat()
                p["computed_at"] = (cutoff-timedelta(minutes=5)).isoformat()
            board = {"provisional": initial["provisional"]}
            db._exec(conn, "UPDATE recommended_slates SET rolling_board=%s",(Json(board),))
            db._exec(conn, "UPDATE events SET start_time=%s",(cutoff+timedelta(minutes=30),))
            db._exec(conn, "UPDATE odds_snapshots SET captured_at=%s",(cutoff-timedelta(minutes=3),))
            db._exec(conn, "UPDATE odds_snapshots SET price=-125 WHERE event_id='event_2'")
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
        assert "event_2" in results[0]["passes"]
    finally:
        with admin.cursor() as cur:
            cur.execute(f"DROP SCHEMA {schema} CASCADE")
        admin.close()
