import json
from datetime import datetime, timezone

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
            "locked_at": datetime(2026, 11, 22, 18, 50, tzinfo=timezone.utc),
            "created_at": datetime(2026, 11, 22, 18, 50, tzinfo=timezone.utc),
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
            "locked_at": datetime(2026, 11, 21, 17, 50, tzinfo=timezone.utc),
            "created_at": datetime(2026, 11, 21, 17, 50, tzinfo=timezone.utc),
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
            "locked_at": datetime(2026, 11, 20, 17, 50, tzinfo=timezone.utc),
            "created_at": datetime(2026, 11, 20, 17, 50, tzinfo=timezone.utc),
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
