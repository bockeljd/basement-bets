import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from src.api import app
from src.config import settings
from src.utils.model_performance import normalize_history_row, normalize_market_type


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_fetch_recommended_history_canonical_preserves_snapshot_and_smart_risk(monkeypatch):
    import src.database as db

    ts = datetime(2026, 11, 20, 22, 0, tzinfo=timezone.utc)
    slate_rows = [
        {
            "day_et": "2026-11-20",
            "rank": 1,
            "prediction_id": "pred_sr_1",
            "event_id": "action:ncaam:sr1",
            "market_type": "SPREAD",
            "selection": "Drake +5.5",
            "bet_line": 5.5,
            "bet_price": -108,
            "price": -108,
            "sport": "NCAAM",
            "home_team": "Creighton",
            "away_team": "Drake",
            "start_time": ts,
            "score": "72-70",
            "final": True,
            "id": "pred_sr_1",
            "analyzed_at": ts,
            "ev_per_unit": 0.064,
            "confidence_0_100": 72,
            "outcome": "WON",
            "source": "cached",
            "snapshot": {
                "is_smart_risk": True,
                "risk_tier": "SMART_RISK",
                "movement_tags": ["sharp_backing", "smart_risk_high_return"],
                "bet_timing": {"action": "BET_NOW", "reason": "Sharp backing"},
                "suggested_units": 0.5,
                "win_prob_lb10": 0.535,
            },
        }
    ]
    dtp_rows = [
        {
            "day_et": "2026-11-21",
            "event_id": "action:ncaam:sr2",
            "computed_at": ts,
            "rec_json": {
                "bet_type": "SPREAD_1H",
                "side": "away",
                "selection": "Vermont 1H +3.5",
                "market_line": 3.5,
                "price": -110,
                "ev": 0.055,
                "confidence": 66,
                "is_smart_risk": True,
                "risk_tier": "SMART_RISK",
                "suggested_units": 0.5,
                "bet_timing": {"action": "MONITOR"},
                "movement_tags": ["smart_risk_high_return"],
            },
            "sport": "NCAAM",
            "home_team": "UConn",
            "away_team": "Vermont",
            "start_time": ts,
            "score": "65-80",
            "home_score_1h": 38,
            "away_score_1h": 36,
            "final": True,
            "id": "pred_sr_2",
            "prediction_id": "pred_sr_2",
            "analyzed_at": ts,
            "pred_ev": 0.055,
            "pred_conf": 66,
            "pred_outcome": "PENDING",
            "pred_market": "SPREAD_1H",
        }
    ]

    def fake_exec(_conn, sql, params=None):
        s = " ".join(sql.split()).lower()
        if "from winner_slates" in s:
            return _FakeCursor(slate_rows)
        if "from daily_top_picks" in s:
            return _FakeCursor(dtp_rows)
        return _FakeCursor([])

    monkeypatch.setattr(db, "get_db_connection", lambda: _FakeConn())
    monkeypatch.setattr(db, "_exec", fake_exec)

    rows = db.fetch_recommended_history_canonical(limit=50, league="NCAAM", lookback_days=30)
    assert len(rows) == 2

    slate_row = next(r for r in rows if r["event_id"] == "action:ncaam:sr1")
    assert slate_row["is_smart_risk"] is True
    assert slate_row["risk_tier"] == "SMART_RISK"
    assert "sharp_backing" in slate_row["movement_tags"]
    assert slate_row["bet_timing_action"] == "BET_NOW"
    assert slate_row["suggested_units"] == 0.5
    assert slate_row["win_prob_lb10"] == 0.535
    assert "snapshot" not in slate_row

    dtp_row = next(r for r in rows if r["event_id"] == "action:ncaam:sr2")
    assert dtp_row["market_type"] == "SPREAD_1H"
    assert dtp_row["is_smart_risk"] is True
    assert dtp_row["risk_tier"] == "SMART_RISK"
    assert dtp_row["suggested_units"] == 0.5
    assert dtp_row["bet_timing_action"] == "MONITOR"
    # 1H margin: Vermont 36 vs UConn 38 with +3.5 => 39.5 > 38 => WON
    assert dtp_row["outcome"] == "WON"


def test_normalize_market_type_and_1h_grading():
    assert normalize_market_type("SPREAD_1H") == "SPREAD_1H"
    assert normalize_market_type("TOTAL_1H") == "TOTAL_1H"
    assert normalize_market_type("spreads") == "SPREAD"
    assert normalize_market_type("totals") == "TOTAL"

    # TOTAL_1H must NOT grade from full-game score when 1H scores are missing
    tot_1h_missing = normalize_history_row({
        "event_id": "evt_1h_missing",
        "market_type": "TOTAL_1H",
        "selection": "1H OVER 66.5",
        "bet_line": 66.5,
        "home_team": "Duke",
        "away_team": "UNC",
        "score": "80-80",
        "final": True,
        "outcome": "PENDING",
    })
    assert tot_1h_missing["market_type"] == "TOTAL_1H"
    assert tot_1h_missing["outcome"] == "PENDING"

    # Grades accurately once home_score_1h and away_score_1h exist (36 + 35 = 71 > 66.5)
    tot_1h_ready = normalize_history_row({
        "event_id": "evt_1h_ready",
        "market_type": "TOTAL_1H",
        "selection": "1H OVER 66.5",
        "bet_line": 66.5,
        "home_team": "Duke",
        "away_team": "UNC",
        "score": "80-80",
        "home_score_1h": 36,
        "away_score_1h": 35,
        "final": True,
        "outcome": "PENDING",
    })
    assert tot_1h_ready["outcome"] == "WON"


def test_parlay_performance_report_grades_away_ml_spread_total_and_partial_push(monkeypatch):
    import src.database as db

    parlay_rows = [
        {
            "id": "p_win",
            "date_et": "2026-11-22",
            "american_odds": 260,
            "p_win": 0.42,
            "ev": 0.08,
            "bucket": "high_confidence",
            "event_id_1": "e1",
            "event_id_2": "e2",
            "locked_at": datetime(2026, 11, 22, 18, 25, tzinfo=timezone.utc),
            "created_at": datetime(2026, 11, 22, 18, 25, tzinfo=timezone.utc),
            "parlay_json": json.dumps({
                "american_odds": 260,
                "legs": [
                    {
                        "event_id": "e1",
                        "matchup": "AwayDogs @ HomeFavs",
                        "team_pick": "AwayDogs ML",
                        "market_type": "MONEYLINE",
                        "side": "AWAY",
                        "price": 120,
                        "win_prob": 0.48,
                        "ev": 0.056,
                        "outcome": "PENDING",
                    },
                    {
                        "event_id": "e2",
                        "matchup": "Visitors @ Hosts",
                        "team_pick": "Hosts -4.5",
                        "market_type": "SPREAD",
                        "side": "HOME",
                        "market_line": -4.5,
                        "price": -110,
                        "outcome": "PENDING",
                    },
                ],
            }),
        },
        {
            "id": "p_lost",
            "date_et": "2026-11-21",
            "american_odds": 264,
            "p_win": 0.34,
            "ev": 0.06,
            "bucket": "payout_band",
            "event_id_1": "e3",
            "event_id_2": "e4",
            "locked_at": datetime(2026, 11, 21, 17, 25, tzinfo=timezone.utc),
            "created_at": datetime(2026, 11, 21, 17, 25, tzinfo=timezone.utc),
            "parlay_json": json.dumps({
                "american_odds": 264,
                "legs": [
                    {
                        "event_id": "e3",
                        "matchup": "SlowA @ SlowB",
                        "team_pick": "UNDER 145.5",
                        "market_type": "TOTAL",
                        "side": "UNDER",
                        "market_line": 145.5,
                        "price": -110,
                        "outcome": "PENDING",
                    },
                    {
                        "event_id": "e4",
                        "matchup": "RoadTeam @ HomeTeam",
                        "team_pick": "RoadTeam 1H +2.5",
                        "market_type": "SPREAD_1H",
                        "side": "AWAY",
                        "market_line": 2.5,
                        "price": -110,
                        "outcome": "PENDING",
                    },
                ],
            }),
        },
        {
            "id": "p_partial",
            "date_et": "2026-11-20",
            "american_odds": 250,
            "p_win": 0.45,
            "ev": 0.07,
            "bucket": "high_confidence",
            "event_id_1": "e5",
            "event_id_2": "e6",
            "locked_at": datetime(2026, 11, 20, 17, 25, tzinfo=timezone.utc),
            "created_at": datetime(2026, 11, 20, 17, 25, tzinfo=timezone.utc),
            "parlay_json": json.dumps({
                "american_odds": 250,
                "legs": [
                    {
                        "event_id": "e5",
                        "matchup": "RoadWinner @ HostLoser",
                        "team_pick": "RoadWinner ML",
                        "market_type": "MONEYLINE",
                        "side": "AWAY",
                        "price": -120,
                        "outcome": "PENDING",
                    },
                    {
                        "event_id": "e6",
                        "matchup": "PushAway @ PushHome",
                        "team_pick": "PushHome -3.0",
                        "market_type": "SPREAD",
                        "side": "HOME",
                        "market_line": -3.0,
                        "price": -110,
                        "outcome": "PENDING",
                    },
                ],
            }),
        },
    ]

    game_rows = [
        {"event_id": "e1", "away_team": "AwayDogs", "home_team": "HomeFavs", "start_time": datetime(2026, 11, 22, 19, 0, tzinfo=timezone.utc), "away_score": 75, "home_score": 70, "home_score_1h": 32, "away_score_1h": 36, "final": True},
        {"event_id": "e2", "away_team": "Visitors", "home_team": "Hosts", "start_time": datetime(2026, 11, 22, 19, 0, tzinfo=timezone.utc), "away_score": 72, "home_score": 80, "home_score_1h": 40, "away_score_1h": 35, "final": True},
        {"event_id": "e3", "away_team": "SlowA", "home_team": "SlowB", "start_time": datetime(2026, 11, 21, 18, 0, tzinfo=timezone.utc), "away_score": 80, "home_score": 78, "home_score_1h": 38, "away_score_1h": 38, "final": True},
        {"event_id": "e4", "away_team": "RoadTeam", "home_team": "HomeTeam", "start_time": datetime(2026, 11, 21, 18, 0, tzinfo=timezone.utc), "away_score": 70, "home_score": 72, "home_score_1h": 36, "away_score_1h": 35, "final": True},
        {"event_id": "e5", "away_team": "RoadWinner", "home_team": "HostLoser", "start_time": datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc), "away_score": 68, "home_score": 61, "home_score_1h": 30, "away_score_1h": 35, "final": True},
        {"event_id": "e6", "away_team": "PushAway", "home_team": "PushHome", "start_time": datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc), "away_score": 70, "home_score": 73, "home_score_1h": 36, "away_score_1h": 34, "final": True},
    ]

    def fake_exec(_conn, sql, params=None):
        s = " ".join(sql.split()).lower()
        if "from recommended_parlays" in s:
            return _FakeCursor(parlay_rows)
        if "from events e" in s and "left join game_results gr" in s:
            return _FakeCursor(game_rows)
        return _FakeCursor([])

    monkeypatch.setattr(db, "get_db_connection", lambda: _FakeConn())
    monkeypatch.setattr(db, "_exec", fake_exec)
    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")

    client = TestClient(app)
    resp = client.get(
        "/api/ncaam/parlays/performance-report?days=400&season=2026-27",
        headers={"X-BASEMENT-KEY": "test-secret"},
    )
    assert resp.status_code == 200
    assert "no-store" in (resp.headers.get("cache-control") or "").lower()

    data = resp.json()
    assert data["record"]["won"] == 2
    assert data["record"]["lost"] == 1
    assert data["win_rate"] == 66.7
    # +2.60 - 1.00 + 0.8333 = +2.43u
    assert data["profit_units"] == 2.43

    by_id = {x["id"]: x for x in data["items"]}
    assert by_id["p_win"]["outcome"] == "WON"
    assert [lg["outcome"] for lg in by_id["p_win"]["legs"]] == ["WON", "WON"]
    assert by_id["p_win"]["legs"][0]["win_prob"] == 0.48
    assert by_id["p_win"]["legs"][0]["ev"] == 0.056
    assert "win_prob" in by_id["p_win"]["legs"][1]
    assert "ev" in by_id["p_win"]["legs"][1]
    assert by_id["p_lost"]["outcome"] == "LOST"
    assert [lg["outcome"] for lg in by_id["p_lost"]["legs"]] == ["LOST", "WON"]
    assert by_id["p_partial"]["outcome"] == "WON (partial)"
    assert abs(by_id["p_partial"]["roi_per_unit"] - 0.8333) < 1e-3


def test_ncaam_top6_cutoffs_triggers_parlay_sync_when_unlocked(monkeypatch):
    import src.api as api_mod
    import src.database as db

    now_utc = datetime.now(timezone.utc)

    def fake_exec(_conn, sql, params=None):
        s = " ".join(sql.split()).lower()
        if "rolling_board" in s:
            return _FakeCursor([])
        if "upcoming_pre_cutoff" in s:
            return _FakeCursor([{"upcoming_pre_cutoff": 1, "latest_computed_at": now_utc, "latest_odds_at": now_utc}])
        if "from recommended_parlays" in s:
            return _FakeCursor([])
        return _FakeCursor([])

    calls = []

    def fake_compute_parlays(**kwargs):
        calls.append(kwargs)
        return {"official_daily_parlay": {"is_locked": True}}

    monkeypatch.setattr(db, "get_db_connection", lambda: _FakeConn())
    monkeypatch.setattr(db, "_exec", fake_exec)
    monkeypatch.setattr(api_mod, "_compute_ncaam_parlays_today", fake_compute_parlays)
    monkeypatch.setattr(settings, "CRON_SECRET", "cron-secret")

    client = TestClient(app)
    resp = client.get(
        "/api/jobs/ncaam_top6_cutoffs",
        headers={"Authorization": "Bearer cron-secret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "no_cutoffs_due"
    assert body["parlay_locked"] is True
    assert calls == [{"persist": False}]

    # Resilient if parlay computation raises
    def broken_parlays(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(api_mod, "_compute_ncaam_parlays_today", broken_parlays)
    resp2 = client.get(
        "/api/jobs/ncaam_top6_cutoffs",
        headers={"Authorization": "Bearer cron-secret"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["parlay_locked"] is False


def test_history_and_calibration_endpoints_set_no_store(monkeypatch):
    import src.database as db
    import src.services.archetype_learning_service as als
    import src.services.live_calibration_service as lcs

    monkeypatch.setattr(db, "fetch_recommended_history_canonical", lambda **kwargs: [])
    monkeypatch.setattr(db, "fetch_model_history", lambda **kwargs: [])
    monkeypatch.setattr(db, "fetch_evaluated_ncaam_days", lambda **kwargs: set())
    monkeypatch.setattr(db, "get_db_connection", lambda: _FakeConn())
    monkeypatch.setattr(db, "_exec", lambda _conn, sql, params=None: _FakeCursor([("2026-11-23",)] if "interval '1 day'" in sql.lower() else []))
    monkeypatch.setattr(lcs, "get_live_calibration_summary", lambda: {"active": False, "bins": [], "params": {}})
    monkeypatch.setattr(als, "load_adaptive_model_learning", lambda: {})
    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")

    client = TestClient(app)
    for path in (
        "/api/research/history",
        "/api/ncaam/recommended-slate/yesterday",
        "/api/ncaam/live-calibration",
        "/api/ncaam/model-learning",
    ):
        resp = client.get(path, headers={"X-BASEMENT-KEY": "test-secret"})
        assert resp.status_code == 200
        assert (resp.headers.get("cache-control") or "").lower() == "no-store, max-age=0"


def test_combine_parlay_bet_timing_precedence_and_started_guard():
    from src.utils.bet_timing import combine_parlay_bet_timing

    now = datetime(2026, 11, 24, 18, 0, tzinfo=timezone.utc)
    tip_300 = (now + timedelta(minutes=300)).isoformat()
    tip_180 = (now + timedelta(minutes=180)).isoformat()
    tip_45 = (now + timedelta(minutes=45)).isoformat()
    tip_past = (now - timedelta(minutes=5)).isoformat()

    leg_wait = {
        "event_id": "e_wait",
        "team_pick": "Alpha ML",
        "market_type": "MONEYLINE",
        "side": "HOME",
        "start_time": tip_300,
        "signals": {"injuries": [{"player": "Star Guard", "status": "Questionable"}]},
    }
    leg_sharp = {
        "event_id": "e_sharp",
        "team_pick": "Beta ML",
        "market_type": "MONEYLINE",
        "side": "AWAY",
        "book": "FanDuel",
        "sharp_edge_pts": 1.0,
        "movement_tags": ["sharp_price_edge"],
        "start_time": tip_180,
    }
    leg_mon1 = {
        "event_id": "e_m1",
        "team_pick": "Gamma ML",
        "market_type": "MONEYLINE",
        "side": "HOME",
        "start_time": tip_300,
    }
    leg_mon2 = {
        "event_id": "e_m2",
        "team_pick": "Delta ML",
        "market_type": "MONEYLINE",
        "side": "AWAY",
        "start_time": tip_300,
    }

    # WAIT_LINEUPS beats BET_NOW outside imminent 60m window
    t_wait = combine_parlay_bet_timing([leg_wait, leg_sharp], now_utc=now)
    assert t_wait["action"] == "WAIT_LINEUPS"
    assert "Alpha ML" in t_wait["reason"]

    # BET_NOW beats MONITOR
    t_sharp = combine_parlay_bet_timing([leg_mon1, leg_sharp], now_utc=now)
    assert t_sharp["action"] == "BET_NOW"
    assert "Beta ML" in t_sharp["reason"]

    # Two distant no-rush legs -> MONITOR
    t_mon = combine_parlay_bet_timing([leg_mon1, leg_mon2], now_utc=now)
    assert t_mon["action"] == "MONITOR"

    # Imminent tip (<= 60m) flips to BET_NOW even with injury watch
    leg_wait_soon = {**leg_wait, "start_time": tip_45}
    t_soon = combine_parlay_bet_timing([leg_wait_soon, leg_mon1], now_utc=now)
    assert t_soon["action"] == "BET_NOW"
    assert "tipoff_imminent" in t_soon["drivers"]
    assert "45 min" in t_soon["reason"]

    # Started leg -> None
    leg_started = {**leg_mon1, "start_time": tip_past}
    assert combine_parlay_bet_timing([leg_started, leg_mon2], now_utc=now) is None


def _mock_parlay_db(monkeypatch, *, today_et, ml_rows, dtp_rows, inserts_out):
    import src.database as db

    class _CommitFakeConn(_FakeConn):
        def commit(self):
            pass

        def cursor(self):
            return _FakeCursor([])

    def fake_exec(_conn, sql, params=None):
        s = " ".join(sql.split()).lower()
        if "with latest_preds as" in s:
            return _FakeCursor(ml_rows)
        if "select (now() at time zone 'america/new_york'" in s:
            return _FakeCursor([(today_et,)])
        if "from daily_top_picks d" in s and "join events e" in s:
            return _FakeCursor(dtp_rows)
        if "canon_book" in s:
            quotes = [dict(event_id=r["event_id"], market_type="MONEYLINE", side="HOME",
                           canon_book="DraftKings", line_value=None, price=r["price"]) for r in ml_rows]
            quotes += [dict(event_id=r["event_id"], market_type=r["rec_json"]["bet_type"],
                            side=r["rec_json"]["side"], canon_book="DraftKings",
                            line_value=r["rec_json"]["market_line"], price=r["rec_json"]["price"])
                       for r in dtp_rows if isinstance(r.get("rec_json"), dict) and r["rec_json"].get("market_line") is not None]
            return _FakeCursor([{**r, "captured_at": datetime.now(timezone.utc)} for r in quotes])
        if "insert into recommended_parlays" in s:
            inserts_out.append((sql, params))
            return _FakeCursor([{"locked_at": datetime.now(timezone.utc)}])
        return _FakeCursor([])

    monkeypatch.setattr(db, "get_db_connection", lambda: _CommitFakeConn())
    monkeypatch.setattr(db, "get_admin_db_connection", lambda: _CommitFakeConn())
    monkeypatch.setattr(db, "_exec", fake_exec)


def test_compute_ncaam_parlays_today_locks_on_bet_now_with_explicit_today_date(monkeypatch):
    from src.services.ncaam_parlay_service import compute_ncaam_parlays_today

    now = datetime.now(timezone.utc)
    today_et = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    tip_5h = (now + timedelta(minutes=300)).isoformat()

    ml_rows = [
        {
            "event_id": "evt_1",
            "model_version": "v2",
            "market_type": "MONEYLINE",
            "pick": "Duke",
            "outcome": "PENDING",
            "bet_line": None,
            "price": -145,
            "win_prob": 0.65,
            "ev_per_unit": 0.095,
            "selection": "Duke",
            "away_team": "Siena",
            "home_team": "Duke",
            "start_time": tip_5h,
            "day_et": today_et,
        },
    ]
    dtp_rows = [
        {
            "event_id": "evt_2",
            "is_actionable": True,
            "away_team": "Marist",
            "home_team": "Iona",
            "start_time": tip_5h,
            "rec_json": {
                "bet_type": "SPREAD",
                "side": "HOME",
                "selection": "Iona -3.5",
                "market_line": -3.5,
                "price": -110,
                "book": "DraftKings",
                "win_prob": 0.58,
                "ev": 0.105,
                "sharp_edge_pts": 1.0,
                "movement_tags": ["sharp_price_edge"],
            },
            "context_json": {},
        }
    ]
    inserts = []
    _mock_parlay_db(monkeypatch, today_et=today_et, ml_rows=ml_rows, dtp_rows=dtp_rows, inserts_out=inserts)

    res = compute_ncaam_parlays_today(date=today_et, persist=False)
    odp = res["official_daily_parlay"]
    assert odp is not None
    assert odp["is_locked"] is True
    assert odp["lock_reason"] == "bet_now"
    assert odp["bet_timing"]["action"] == "BET_NOW"
    assert len(inserts) == 1

    saved_json = json.loads(inserts[0][1][10])
    assert saved_json["lock_reason"] == "bet_now"
    assert saved_json["bet_timing"]["action"] == "BET_NOW"
    for lg in odp["legs"]:
        assert "_dk_fd_prices" not in lg
        assert "_timing_context" not in lg
        assert "_timing_payload" not in lg


def test_compute_ncaam_parlays_today_waits_on_monitor_and_locks_at_30m_cutoff(monkeypatch):
    from src.services.ncaam_parlay_service import compute_ncaam_parlays_today

    now = datetime.now(timezone.utc)
    today_et = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    tip_5h = (now + timedelta(minutes=300)).isoformat()
    tip_25m = (now + timedelta(minutes=25)).isoformat()

    ml_rows_far = [
        {
            "event_id": "evt_a",
            "model_version": "v2",
            "market_type": "MONEYLINE",
            "pick": "UConn",
            "outcome": "PENDING",
            "bet_line": None,
            "price": -150,
            "win_prob": 0.62,
            "ev_per_unit": 0.03,
            "selection": "UConn",
            "away_team": "Rider",
            "home_team": "UConn",
            "start_time": tip_5h,
            "day_et": today_et,
        },
        {
            "event_id": "evt_b",
            "model_version": "v2",
            "market_type": "MONEYLINE",
            "pick": "Kansas",
            "outcome": "PENDING",
            "bet_line": None,
            "price": -140,
            "win_prob": 0.61,
            "ev_per_unit": 0.03,
            "selection": "Kansas",
            "away_team": "Omaha",
            "home_team": "Kansas",
            "start_time": tip_5h,
            "day_et": today_et,
        },
    ]
    inserts_far = []
    _mock_parlay_db(monkeypatch, today_et=today_et, ml_rows=ml_rows_far, dtp_rows=[], inserts_out=inserts_far)

    res_far = compute_ncaam_parlays_today(date=today_et, persist=False)
    odp_far = res_far["official_daily_parlay"]
    assert odp_far is not None
    assert odp_far["is_locked"] is False
    assert odp_far["lock_reason"] is None
    assert odp_far["bet_timing"]["action"] == "MONITOR"
    assert len(inserts_far) == 0

    ml_rows_cutoff = [
        {**ml_rows_far[0], "start_time": tip_25m},
        ml_rows_far[1],
    ]
    inserts_cutoff = []
    _mock_parlay_db(monkeypatch, today_et=today_et, ml_rows=ml_rows_cutoff, dtp_rows=[], inserts_out=inserts_cutoff)

    res_cutoff = compute_ncaam_parlays_today(date=today_et, persist=False)
    odp_cutoff = res_cutoff["official_daily_parlay"]
    assert odp_cutoff is None
    assert not inserts_cutoff
    assert compute_ncaam_parlays_today(date=today_et, persist=True)["official_daily_parlay"] is None
    assert not inserts_cutoff


def test_compute_ncaam_parlays_today_excludes_started_games_contra_sharp_and_leans_from_official(monkeypatch):
    from src.services.ncaam_parlay_service import compute_ncaam_parlays_today

    now = datetime.now(timezone.utc)
    today_et = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    tip_past = (now - timedelta(minutes=20)).isoformat()
    tip_4h = (now + timedelta(minutes=240)).isoformat()

    ml_rows = [
        {
            "event_id": "evt_started",
            "model_version": "v2",
            "market_type": "MONEYLINE",
            "pick": "StartedTeam",
            "outcome": "PENDING",
            "bet_line": None,
            "price": -150,
            "win_prob": 0.90,
            "ev_per_unit": 0.25,
            "selection": "StartedTeam",
            "away_team": "Visitor",
            "home_team": "StartedTeam",
            "start_time": tip_past,
            "day_et": today_et,
        },
        {
            "event_id": "evt_contra",
            "model_version": "v2",
            "market_type": "MONEYLINE",
            "pick": "ContraTeam",
            "outcome": "PENDING",
            "bet_line": None,
            "price": -130,
            "win_prob": 0.72,
            "ev_per_unit": 0.14,
            "selection": "ContraTeam",
            "away_team": "AwayX",
            "home_team": "ContraTeam",
            "start_time": tip_4h,
            "day_et": today_et,
        },
    ]
    dtp_rows = [
        {
            "event_id": "evt_contra",
            "is_actionable": True,
            "away_team": "AwayX",
            "home_team": "ContraTeam",
            "start_time": tip_4h,
            "rec_json": {
                "bet_type": "SPREAD",
                "side": "HOME",
                "selection": "ContraTeam -2.5",
                "movement_tags": ["contra_sharp_money"],
            },
            "context_json": {},
        },
        {
            "event_id": "evt_lean1",
            "is_actionable": False,
            "away_team": "LeanA",
            "home_team": "HomeA",
            "start_time": tip_4h,
            "rec_json": None,
            "context_json": {
                "closest_lean": {
                    "bet_type": "SPREAD",
                    "side": "HOME",
                    "selection": "HomeA -4.5",
                    "market_line": -4.5,
                    "price": -110,
                    "win_prob": 0.56,
                    "ev": 0.04,
                }
            },
        },
        {
            "event_id": "evt_lean2",
            "is_actionable": False,
            "away_team": "LeanB",
            "home_team": "HomeB",
            "start_time": tip_4h,
            "rec_json": None,
            "context_json": {
                "closest_lean": {
                    "bet_type": "TOTAL",
                    "side": "UNDER",
                    "selection": "UNDER 142.5",
                    "market_line": 142.5,
                    "price": -110,
                    "win_prob": 0.57,
                    "ev": 0.05,
                }
            },
        },
    ]
    inserts = []
    _mock_parlay_db(monkeypatch, today_et=today_et, ml_rows=ml_rows, dtp_rows=dtp_rows, inserts_out=inserts)

    res = compute_ncaam_parlays_today(date=today_et, persist=False)
    all_leg_eids = {
        lg["event_id"]
        for c in (res["high_confidence"] + res["payout_band"])
        for lg in c["legs"]
    }
    assert "evt_started" not in all_leg_eids
    assert "evt_contra" not in all_leg_eids
    assert "evt_lean1" in all_leg_eids and "evt_lean2" in all_leg_eids
    assert res["official_daily_parlay"] is None
    assert len(inserts) == 0


def test_ml_win_prob_from_spread_heavy_tail_and_early_season():
    import math
    from src.services.ncaam_parlay_service import ml_win_prob_from_spread

    raw_gaussian = 0.5 * (1.0 - math.erf(-8.0 / (10.5 * math.sqrt(2.0))))
    late_prob = ml_win_prob_from_spread(
        -8.0,
        10.5,
        side="HOME",
        start_time="2027-03-10T23:00:00Z",
    )
    early_prob = ml_win_prob_from_spread(
        -8.0,
        10.5,
        side="HOME",
        start_time="2026-11-24T23:00:00Z",
    )
    away_early = ml_win_prob_from_spread(
        -8.0,
        10.5,
        side="AWAY",
        start_time="2026-11-24T23:00:00Z",
    )

    assert early_prob < late_prob < raw_gaussian
    assert abs((early_prob + away_early) - 1.0) < 1e-9

    # Symmetry preserved with nonlinear 1-arg calibrate_fn
    p_home_cal = ml_win_prob_from_spread(
        -6.0,
        10.5,
        side="HOME",
        start_time="2026-11-24T23:00:00Z",
        calibrate_fn=lambda p: 0.9 * p + 0.05,
    )
    p_away_cal = ml_win_prob_from_spread(
        -6.0,
        10.5,
        side="AWAY",
        start_time="2026-11-24T23:00:00Z",
        calibrate_fn=lambda p: 0.9 * p + 0.05,
    )
    assert abs((p_home_cal + p_away_cal) - 1.0) < 1e-9


def test_secondary_parlay_ranking_relaxes_same_book_thrashing(monkeypatch):
    from src.services.ncaam_parlay_service import compute_ncaam_parlays_today

    now = datetime.now(timezone.utc)
    today_et = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    tip_5h = (now + timedelta(minutes=300)).isoformat()

    # Strong mixed-book pair: evt_m1 + evt_m2 (p_win=0.72*0.72=0.5184, mixed books DK + FD)
    # Weak same-book pair: evt_s1 + evt_s2 (p_win=0.55*0.55=0.3025, both DraftKings)
    ml_rows = [
        {
            "event_id": "evt_m1",
            "model_version": "v2",
            "market_type": "MONEYLINE",
            "pick": "MixA",
            "outcome": "PENDING",
            "bet_line": None,
            "price": -145,
            "win_prob": 0.72,
            "ev_per_unit": 0.21,
            "selection": "MixA",
            "away_team": "Opp1",
            "home_team": "MixA",
            "start_time": tip_5h,
            "day_et": today_et,
        },
        {
            "event_id": "evt_m2",
            "model_version": "v2",
            "market_type": "MONEYLINE",
            "pick": "MixB",
            "outcome": "PENDING",
            "bet_line": None,
            "price": -145,
            "win_prob": 0.72,
            "ev_per_unit": 0.21,
            "selection": "MixB",
            "away_team": "Opp2",
            "home_team": "MixB",
            "start_time": tip_5h,
            "day_et": today_et,
        },
        {
            "event_id": "evt_s1",
            "model_version": "v2",
            "market_type": "MONEYLINE",
            "pick": "SameA",
            "outcome": "PENDING",
            "bet_line": None,
            "price": -110,
            "win_prob": 0.55,
            "ev_per_unit": 0.05,
            "selection": "SameA",
            "away_team": "Opp3",
            "home_team": "SameA",
            "start_time": tip_5h,
            "day_et": today_et,
        },
        {
            "event_id": "evt_s2",
            "model_version": "v2",
            "market_type": "MONEYLINE",
            "pick": "SameB",
            "outcome": "PENDING",
            "bet_line": None,
            "price": -110,
            "win_prob": 0.55,
            "ev_per_unit": 0.05,
            "selection": "SameB",
            "away_team": "Opp4",
            "home_team": "SameB",
            "start_time": tip_5h,
            "day_et": today_et,
        },
    ]

    import src.database as db

    class _CommitFakeConn(_FakeConn):
        def commit(self):
            pass

        def cursor(self):
            return _FakeCursor([])

    def fake_exec(_conn, sql, params=None):
        s = " ".join(sql.split()).lower()
        if "with latest_preds as" in s:
            return _FakeCursor(ml_rows)
        if "select (now() at time zone 'america/new_york'" in s:
            return _FakeCursor([(today_et,)])
        if "from odds_snapshots" in s and "canon_book" in s:
            return _FakeCursor([
                {"event_id": "evt_m1", "market_type": "MONEYLINE", "side": "HOME", "captured_at": datetime.now(timezone.utc), "canon_book": "DraftKings", "line_value": None, "price": -145},
                {"event_id": "evt_m2", "market_type": "MONEYLINE", "side": "HOME", "captured_at": datetime.now(timezone.utc), "canon_book": "FanDuel", "line_value": None, "price": -145},
                {"event_id": "evt_s1", "market_type": "MONEYLINE", "side": "HOME", "captured_at": datetime.now(timezone.utc), "canon_book": "DraftKings", "line_value": None, "price": -110},
                {"event_id": "evt_s2", "market_type": "MONEYLINE", "side": "HOME", "captured_at": datetime.now(timezone.utc), "canon_book": "DraftKings", "line_value": None, "price": -110},
            ])
        return _FakeCursor([])

    monkeypatch.setattr(db, "get_db_connection", lambda: _CommitFakeConn())
    monkeypatch.setattr(db, "get_admin_db_connection", lambda: _CommitFakeConn())
    monkeypatch.setattr(db, "_exec", fake_exec)

    res = compute_ncaam_parlays_today(date=today_et, persist=False)
    hc = res["high_confidence"]
    assert len(hc) >= 2
    # Secondary high_confidence no longer puts weak same_book ahead of strong mixed-book pair
    assert {lg["event_id"] for lg in hc[0]["legs"]} == {"evt_m1", "evt_m2"}
    assert hc[0]["same_book"] is False
    # Official daily parlay still prefers single-book executable combo when available
    odp = res["official_daily_parlay"]
    assert odp is not None
    assert odp["same_book"] is True
    assert {lg["event_id"] for lg in odp["legs"]} == {"evt_s1", "evt_s2"}


def test_publication_timing_uses_earliest_tip_and_requires_a_verified_lock():
    from src.services.ncaam_parlay_service import publication_timing

    tip = datetime(2026, 11, 25, 0, 0, tzinfo=timezone.utc)
    starts = [tip + timedelta(hours=2), tip]
    assert publication_timing(tip - timedelta(minutes=30), starts) == "on_time"
    assert publication_timing(tip - timedelta(minutes=29, seconds=59), starts) == "late_pregame"
    assert publication_timing(tip, starts) == "after_tip"
    assert publication_timing(None, starts) == "unverified"
    assert publication_timing(tip, [None, tip]) == "unverified"
