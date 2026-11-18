import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.api import app
from src.config import settings
from src.utils.model_performance import (
    dedupe_and_merge_history,
    format_matchup,
    normalize_confidence_pct,
    normalize_history_row,
    normalize_market_type,
    normalize_sport,
    sport_query_aliases,
)


def test_normalization_and_dedupe_helpers():
    assert normalize_market_type("h2h") == "MONEYLINE"
    assert normalize_market_type("ML") == "MONEYLINE"
    assert normalize_market_type("spreads") == "SPREAD"
    assert normalize_market_type("totals") == "TOTAL"
    assert normalize_market_type(None) == "OTHER"
    assert normalize_market_type("AUTO") == "OTHER"
    assert normalize_market_type("spread", is_parlay=True) == "PARLAY"

    assert normalize_confidence_pct(0.84) == 84.0
    assert normalize_confidence_pct(76) == 76.0
    assert normalize_confidence_pct(None) is None

    assert format_matchup({"away_team": "Duke", "home_team": "UNC"}) == "Duke @ UNC"
    assert format_matchup({"matchup": "Kansas @ Baylor"}) == "Kansas @ Baylor"

    row = normalize_history_row(
        {
            "event_id": "evt_1",
            "market_type": "h2h",
            "away_team": "Duke",
            "home_team": "UNC",
            "pick": "Duke",
            "price": 135,
            "confidence_0_100": 0.78,
            "outcome": "win",
        }
    )
    assert row["market_type"] == "MONEYLINE"
    assert row["matchup"] == "Duke @ UNC"
    assert row["selection"] == "Duke"
    assert row["bet_price"] == 135
    assert row["price"] == 135
    assert row["confidence_0_100"] == 78.0
    assert row["outcome"] == "WON"

    legacy_home = normalize_history_row(
        {
            "event_id": "evt_home",
            "market_type": "SPREAD",
            "away_team": "Yale Bulldogs",
            "home_team": "Harvard Crimson",
            "selection": "home",
            "pick": "home",
        }
    )
    assert legacy_home["selection"] == "Harvard Crimson"

    canonical = [
        {
            "id": "p_1",
            "event_id": "evt_1",
            "market_type": "h2h",
            "away_team": "Duke",
            "home_team": "UNC",
            "selection": "Duke",
            "outcome": "WON",
        }
    ]
    # Later rerun on same event + market produces p_2 != p_1; semantic dedupe must prevent double counting
    fallback = [
        {
            "id": "p_2",
            "event_id": "evt_1",
            "market_type": "MONEYLINE",
            "away_team": "Duke",
            "home_team": "UNC",
            "selection": "Duke",
            "outcome": "WON",
        },
        {
            "id": "p_3",
            "event_id": "evt_2",
            "market_type": "SPREAD",
            "away_team": "Kansas",
            "home_team": "Baylor",
            "selection": "Kansas",
            "bet_line": -3.5,
            "outcome": "LOST",
        },
    ]
    merged = dedupe_and_merge_history(canonical, fallback)
    assert len(merged) == 2
    assert merged[0]["source_type"] == "canonical_slate"
    assert merged[0]["market_type"] == "MONEYLINE"
    assert merged[1]["id"] == "p_3"
    assert merged[1]["source_type"] == "fallback_prediction"


def test_research_history_endpoint_dedupes_and_normalizes(monkeypatch):
    import src.database as db

    monkeypatch.setattr(
        db,
        "fetch_recommended_history_canonical",
        lambda **kwargs: [
            normalize_history_row(
                {
                    "id": "c1",
                    "event_id": "e1",
                    "day_et": "2026-11-11",
                    "market_type": "h2h",
                    "away_team": "Duke",
                    "home_team": "Army",
                    "selection": "Duke",
                    "bet_price": -145,
                    "outcome": "WON",
                    "ev_per_unit": 0.06,
                    "confidence_0_100": 82,
                    "start_time": "2026-11-11T23:00:00Z",
                }
            )
        ],
    )
    monkeypatch.setattr(
        db,
        "fetch_model_history",
        lambda **kwargs: [
            # Duplicate event+market with different prediction id must be suppressed
            normalize_history_row(
                {
                    "id": "u_dup",
                    "event_id": "e1",
                    "market_type": "MONEYLINE",
                    "away_team": "Duke",
                    "home_team": "Army",
                    "selection": "Duke",
                    "bet_price": -150,
                    "outcome": "WON",
                    "ev_per_unit": 0.05,
                    "analyzed_at": "2026-11-11T22:00:00Z",
                }
            ),
            # Distinct game/market should remain
            normalize_history_row(
                {
                    "id": "u_2",
                    "event_id": "e2",
                    "market_type": "SPREAD",
                    "away_team": "Gonzaga",
                    "home_team": "Baylor",
                    "selection": "Gonzaga",
                    "bet_line": -2.5,
                    "bet_price": -110,
                    "outcome": "LOST",
                    "ev_per_unit": 0.04,
                    "analyzed_at": "2026-11-10T21:00:00Z",
                }
            ),
        ],
    )

    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")
    client = TestClient(app)
    resp = client.get(
        "/api/research/history?limit=100&lookback_days=90",
        headers={"X-BASEMENT-KEY": "test-secret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["event_id"] == "e1"
    assert body[0]["market_type"] == "MONEYLINE"
    assert body[0]["matchup"] == "Duke @ Army"
    assert body[1]["event_id"] == "e2"
    assert body[1]["matchup"] == "Gonzaga @ Baylor"


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


def test_yesterday_slate_falls_back_to_daily_top_picks(monkeypatch):
    import src.database as db

    created_ts = datetime(2026, 11, 11, 15, 0, tzinfo=timezone.utc)

    def fake_exec(_conn, sql, params=None):
        s = " ".join(sql.split()).lower()
        if "interval '1 day'" in s:
            return _FakeCursor([("2026-11-11",)])
        if "from recommended_slates" in s:
            return _FakeCursor([])
        if "from daily_top_picks" in s:
            return _FakeCursor(
                [
                    {
                        "event_id": "evt_spread",
                        "computed_at": created_ts,
                        "rec_json": json.dumps(
                            {
                                "bet_type": "SPREAD",
                                "side": "Duke",
                                "line": -4.5,
                                "odds": -110,
                                "ev_per_unit": 0.08,
                                "confidence": 81,
                            }
                        ),
                        "away_team": "Duke",
                        "home_team": "UNC",
                        "start_time": created_ts,
                        "sport": "NCAAM",
                        "away_score": 78,
                        "home_score": 70,
                        "prediction_id": "pred_s",
                        "outcome": "WON",
                        "pred_ev": 0.08,
                        "pred_conf": 81,
                        "clv_points": 1.0,
                        "pred_line": -4.5,
                        "pred_price": -110,
                        "pred_selection": "Duke",
                        "pred_market": "SPREAD",
                        "pred_pick": "Duke",
                    },
                    {
                        "event_id": "evt_ml",
                        "computed_at": created_ts,
                        "rec_json": {
                            "bet_type": "h2h",
                            "side": "Kansas",
                            "odds": 130,
                            "ev_per_unit": 0.05,
                            "confidence": 64,
                        },
                        "away_team": "Kansas",
                        "home_team": "Baylor",
                        "start_time": created_ts,
                        "sport": "NCAAM",
                        "away_score": 65,
                        "home_score": 72,
                        "prediction_id": "pred_ml",
                        "outcome": "LOST",
                        "pred_ev": 0.05,
                        "pred_conf": 64,
                        "clv_points": -0.5,
                        "pred_line": None,
                        "pred_price": 130,
                        "pred_selection": "Kansas",
                        "pred_market": "h2h",
                        "pred_pick": "Kansas",
                    },
                ]
            )
        return _FakeCursor([])

    monkeypatch.setattr(db, "get_db_connection", lambda: _FakeConn())
    monkeypatch.setattr(db, "_exec", fake_exec)

    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")
    client = TestClient(app)
    resp = client.get(
        "/api/ncaam/recommended-slate/yesterday",
        headers={"X-BASEMENT-KEY": "test-secret"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["date_et"] == "2026-11-11"
    assert data["slate"]["source"] == "daily_top_picks"
    assert len(data["straight"]) == 1
    assert len(data["ml_parlay"]) == 1
    assert data["straight"][0]["matchup"] == "Duke @ UNC"
    assert data["straight"][0]["score"] == "78-70"
    assert data["ml_parlay"][0]["market_type"] == "MONEYLINE"
    assert data["record"]["straight"] == {"won": 1, "lost": 0, "push": 0, "decided": 1}
    assert data["record"]["ml_parlay"] == {"won": 0, "lost": 1, "push": 0, "decided": 1}


def test_yesterday_slate_falls_back_to_model_predictions(monkeypatch):
    import src.database as db

    ts = datetime(2026, 11, 11, 20, 0, tzinfo=timezone.utc)

    def fake_exec(_conn, sql, params=None):
        s = " ".join(sql.split()).lower()
        if "interval '1 day'" in s:
            return _FakeCursor([("2026-11-11",)])
        if "from daily_top_picks" in s:
            return _FakeCursor([])
        if "from model_predictions m " in s:
            return _FakeCursor(
                [
                    {
                        "prediction_id": "mp_1",
                        "event_id": "evt_tot",
                        "market_type": "TOTAL",
                        "selection": "Over",
                        "pick": "OVER",
                        "bet_line": 144.5,
                        "price": -110,
                        "ev_per_unit": 0.07,
                        "confidence_0_100": 75,
                        "clv_points": 0.5,
                        "outcome": "PUSH",
                        "analyzed_at": ts,
                        "sport": "NCAAM",
                        "away_team": "Villanova",
                        "home_team": "UConn",
                        "start_time": ts,
                        "away_score": 72,
                        "home_score": 72,
                    }
                ]
            )
        return _FakeCursor([])

    monkeypatch.setattr(db, "get_db_connection", lambda: _FakeConn())
    monkeypatch.setattr(db, "_exec", fake_exec)
    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")

    client = TestClient(app)
    resp = client.get(
        "/api/ncaam/recommended-slate/yesterday",
        headers={"X-BASEMENT-KEY": "test-secret"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["slate"]["source"] == "model_predictions"
    assert len(data["straight"]) == 1
    assert data["straight"][0]["matchup"] == "Villanova @ UConn"
    assert data["straight"][0]["bet_line"] == 144.5
    assert data["record"]["straight"] == {"won": 0, "lost": 0, "push": 1, "decided": 1}


def test_sport_normalization_and_research_history_sport_filter(monkeypatch):
    import src.database as db

    assert normalize_sport("basketball_ncaab") == "NCAAM"
    assert normalize_sport("ncaab") == "NCAAM"
    assert normalize_sport("baseball_mlb") == "MLB"
    assert normalize_sport(None, event_id="action:mlb:999") == "MLB"
    assert normalize_sport(None, event_id="espn:ncaam:123") == "NCAAM"
    assert sport_query_aliases("basketball_ncaab") == ("NCAAM", "NCAAB", "BASKETBALL_NCAAB", "CBB")
    assert sport_query_aliases("MLB") == ("MLB", "BASEBALL_MLB")

    captured_leagues = []

    sample_rows = [
        normalize_history_row(
            {
                "id": "ncaam_1",
                "event_id": "evt_cbb_1",
                "sport": "basketball_ncaab",
                "market_type": "SPREAD",
                "away_team": "Duke",
                "home_team": "UNC",
                "selection": "Duke",
                "bet_line": -3.5,
                "bet_price": -110,
                "outcome": "WON",
                "ev_per_unit": 0.06,
                "start_time": "2026-11-11T23:00:00Z",
            }
        ),
        normalize_history_row(
            {
                "id": "mlb_1",
                "event_id": "mlb:evt_1",
                "sport": "baseball_mlb",
                "market_type": "MONEYLINE",
                "away_team": "Yankees",
                "home_team": "Red Sox",
                "selection": "Yankees",
                "bet_price": -125,
                "outcome": "LOST",
                "ev_per_unit": 0.05,
                "start_time": "2026-08-15T23:00:00Z",
            }
        ),
    ]

    def fake_canonical(**kwargs):
        captured_leagues.append(("canonical", kwargs.get("league")))
        league = kwargs.get("league")
        if not league:
            return list(sample_rows)
        return [r for r in sample_rows if r["sport"] == league]

    def fake_model_history(**kwargs):
        captured_leagues.append(("fallback", kwargs.get("league")))
        return []

    monkeypatch.setattr(db, "fetch_recommended_history_canonical", fake_canonical)
    monkeypatch.setattr(db, "fetch_model_history", fake_model_history)
    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")

    client = TestClient(app)
    mlb_resp = client.get(
        "/api/research/history?sport=MLB",
        headers={"X-BASEMENT-KEY": "test-secret"},
    )
    assert mlb_resp.status_code == 200
    mlb_body = mlb_resp.json()
    assert len(mlb_body) == 1
    assert mlb_body[0]["sport"] == "MLB"
    assert mlb_body[0]["id"] == "mlb_1"
    assert ("canonical", "MLB") in captured_leagues

    ncaam_resp = client.get(
        "/api/research/history?sport=basketball_ncaab",
        headers={"X-BASEMENT-KEY": "test-secret"},
    )
    assert ncaam_resp.status_code == 200
    ncaam_body = ncaam_resp.json()
    assert len(ncaam_body) == 1
    assert ncaam_body[0]["sport"] == "NCAAM"
    assert ncaam_body[0]["id"] == "ncaam_1"
    assert ("canonical", "NCAAM") in captured_leagues

    all_resp = client.get(
        "/api/research/history?sport=ALL",
        headers={"X-BASEMENT-KEY": "test-secret"},
    )
    assert all_resp.status_code == 200
    assert len(all_resp.json()) == 2
    assert ("canonical", None) in captured_leagues


def test_season_derivation_and_history_season_filter(monkeypatch):
    import src.database as db
    from src.utils.model_performance import get_row_season

    assert get_row_season({"sport": "NCAAM", "day_et": "2026-11-12"}) == "2026-27"
    assert get_row_season({"sport": "NCAAM", "day_et": "2026-03-20"}) == "2025-26"
    assert get_row_season({"sport": "MLB", "day_et": "2026-07-04"}) == "2026"

    sample_rows = [
        normalize_history_row({
            "id": "n_27",
            "event_id": "action:ncaam:27",
            "sport": "NCAAM",
            "market_type": "SPREAD",
            "selection": "Duke",
            "bet_line": -4.5,
            "bet_price": -110,
            "outcome": "WON",
            "day_et": "2026-11-12",
            "start_time": "2026-11-13T00:00:00Z",
        }),
        normalize_history_row({
            "id": "n_26",
            "event_id": "action:ncaam:26",
            "sport": "NCAAM",
            "market_type": "SPREAD",
            "selection": "Kansas",
            "bet_line": -2.5,
            "bet_price": -110,
            "outcome": "LOST",
            "day_et": "2026-03-15",
            "start_time": "2026-03-15T18:00:00Z",
        }),
        normalize_history_row({
            "id": "m_26",
            "event_id": "action:mlb:26",
            "sport": "MLB",
            "market_type": "TOTAL",
            "selection": "OVER 8.5",
            "bet_price": -110,
            "outcome": "WON",
            "day_et": "2026-08-15",
            "start_time": "2026-08-15T23:00:00Z",
        }),
    ]
    assert sample_rows[2]["bet_line"] == 8.5

    monkeypatch.setattr(db, "fetch_recommended_history_canonical", lambda **kwargs: list(sample_rows))
    monkeypatch.setattr(db, "fetch_model_history", lambda **kwargs: [])
    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")

    client = TestClient(app)
    r27 = client.get("/api/research/history?sport=NCAAM&season=2026-27", headers={"X-BASEMENT-KEY": "test-secret"})
    assert r27.status_code == 200
    assert [r["id"] for r in r27.json()] == ["n_27"]

    r26 = client.get("/api/research/history?sport=NCAAM&season=2025-26", headers={"X-BASEMENT-KEY": "test-secret"})
    assert r26.status_code == 200
    assert [r["id"] for r in r26.json()] == ["n_26"]


def test_yesterday_total_line_inference_and_non_matching_ml_isolation():
    from src.api import _yesterday_items_from_daily_top_picks

    # Simulate daily_top_picks OVER 142.5 row where mismatched LATERAL join matched a LOST Moneyline row
    mismatched_rows = [
        {
            "event_id": "action:ncaam:297743",
            "computed_at": datetime(2026, 11, 13, 3, 24, tzinfo=timezone.utc),
            "rec_json": {
                "bet_type": "TOTAL",
                "side": "OVER",
                "selection": "OVER 142.5",
                "odds": -105,
                "ev": 0.042,
                "confidence": 64,
            },
            "away_team": "Loyola Marymount Lions",
            "home_team": "South Alabama Jaguars",
            "start_time": datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc),
            "sport": "NCAAM",
            "away_score": 72,
            "home_score": 79,
            "prediction_id": "wrong-ml-id",
            "outcome": "LOST",
            "pred_ev": 0.8298,
            "pred_conf": 32,
            "clv_points": None,
            "pred_line": None,
            "pred_price": 860,
            "pred_selection": "Loyola Marymount Lions",
            "pred_market": "MONEYLINE",
            "pred_pick": "Loyola Marymount Lions",
        }
    ]

    class _MockConn:
        pass

    import src.database as db
    orig_exec = db._exec
    try:
        db._exec = lambda conn, sql, params=None: _FakeCursor(mismatched_rows)
        slate, items = _yesterday_items_from_daily_top_picks(_MockConn(), "2026-11-12")
    finally:
        db._exec = orig_exec

    assert slate is not None
    assert len(items) == 1
    item = items[0]
    assert item["market_type"] == "TOTAL"
    assert item["bet_line"] == 142.5
    assert item["ev_per_unit"] == 0.042
    # Must re-grade OVER 142.5 cleanly from 72-79 (151 pts) as WON, not inherit LOST from MONEYLINE!
    assert item["outcome"] == "WON"


def test_fetch_recommended_history_canonical_fills_from_daily_top_picks_and_dedupes(monkeypatch):
    import src.database as db

    ts = datetime(2026, 11, 15, 22, 0, tzinfo=timezone.utc)
    slate_rows = [
        {
            "day_et": "2026-03-15",
            "rank": 1,
            "prediction_id": "legacy_p1",
            "event_id": "action:ncaam:legacy1",
            "market_type": "SPREAD",
            "selection": "Duke",
            "bet_line": -4.5,
            "bet_price": -110,
            "price": -110,
            "sport": "NCAAM",
            "home_team": "UNC",
            "away_team": "Duke",
            "start_time": datetime(2026, 3, 15, 22, 0, tzinfo=timezone.utc),
            "score": "80-72",
            "final": True,
            "id": "legacy_p1",
            "analyzed_at": datetime(2026, 3, 15, 18, 0, tzinfo=timezone.utc),
            "ev_per_unit": 0.08,
            "confidence_0_100": 82,
            "outcome": "WON",
            "source": "cached",
        }
    ]
    dtp_rows = [
        {
            "day_et": "2026-11-15",
            "event_id": "action:ncaam:pfw",
            "computed_at": ts,
            "rec_json": {
                "bet_type": "SPREAD",
                "selection": "Purdue Fort Wayne Mastodons -3.5",
                "market_line": -3.5,
                "price": -104,
                "edge": "+13.7%",
                "confidence": 80,
            },
            "sport": "NCAAM",
            "home_team": "Eastern Illinois Panthers",
            "away_team": "Purdue Fort Wayne Mastodons",
            "start_time": ts,
            "score": "86-74",
            "final": True,
            "id": "pfw_spread",
            "prediction_id": "pfw_spread",
            "analyzed_at": ts,
            "pred_ev": 0.137,
            "pred_conf": 80,
            "pred_outcome": "WON",
            "pred_market": "SPREAD",
        },
        {
            "day_et": "2026-11-15",
            "event_id": "action:ncaam:chi",
            "computed_at": ts,
            "rec_json": {
                "bet_type": "SPREAD",
                "selection": "Chicago State Cougars +17.5",
                "market_line": 17.5,
                "price": -114,
                "edge": "+9.6%",
                "confidence": 81,
            },
            "sport": "NCAAM",
            "home_team": "Loyola Marymount Lions",
            "away_team": "Chicago State Cougars",
            "start_time": ts,
            "score": "49-86",
            "final": True,
            "id": "chi_spread",
            "prediction_id": "chi_spread",
            "analyzed_at": ts,
            "pred_ev": 0.096,
            "pred_conf": 81,
            "pred_outcome": "LOST",
            "pred_market": "SPREAD",
        },
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

    canonical = db.fetch_recommended_history_canonical(limit=100, league="NCAAM", lookback_days=400)
    assert len(canonical) == 3
    dtp_canon = [r for r in canonical if r.get("canonical_source") == "daily_top_picks"]
    assert len(dtp_canon) == 2
    assert dtp_canon[0]["event_id"] == "action:ncaam:pfw"
    assert dtp_canon[0]["rank"] == 1
    assert dtp_canon[1]["event_id"] == "action:ncaam:chi"
    assert dtp_canon[1]["rank"] == 2

    # Fallback row for same event (old Moneyline rerun) must be suppressed cleanly
    fallback_old_ml = [
        normalize_history_row({
            "id": "old_pfw_ml",
            "event_id": "action:ncaam:pfw",
            "market_type": "MONEYLINE",
            "away_team": "Purdue Fort Wayne Mastodons",
            "home_team": "Eastern Illinois Panthers",
            "selection": "Purdue Fort Wayne Mastodons",
            "bet_price": -158,
            "ev_per_unit": 0.277,
            "outcome": "WON",
        }),
        normalize_history_row({
            "id": "other_game",
            "event_id": "action:ncaam:other",
            "market_type": "TOTAL",
            "selection": "OVER 141.5",
            "bet_price": -110,
            "outcome": "LOST",
        }),
    ]
    merged = dedupe_and_merge_history(canonical, fallback_old_ml)
    merged_ids = [r["id"] for r in merged]
    assert "pfw_spread" in merged_ids
    assert "old_pfw_ml" not in merged_ids
    assert "other_game" in merged_ids


def test_zero_zero_score_sanitized_in_history_and_grade_endpoint(monkeypatch):
    bad_basketball = normalize_history_row({
        "id": "af_00",
        "event_id": "action:ncaam:af1",
        "sport": "NCAAM",
        "market_type": "TOTAL",
        "selection": "UNDER 163.5",
        "bet_line": 163.5,
        "bet_price": -107,
        "score": "0-0",
        "final": True,
        "outcome": "WON",
    })
    assert bad_basketball["score"] is None
    assert bad_basketball["outcome"] == "VOID"

    epl_00 = normalize_history_row({
        "id": "epl_00",
        "event_id": "action:epl:1",
        "sport": "EPL",
        "market_type": "TOTAL",
        "selection": "UNDER 2.5",
        "bet_line": 2.5,
        "bet_price": -110,
        "score": "0-0",
        "final": True,
        "outcome": "WON",
    })
    assert epl_00["score"] == "0-0"
    assert epl_00["outcome"] == "WON"

    captured_calls = []

    class _FakeGradingService:
        def grade_predictions(self, **kwargs):
            captured_calls.append(kwargs)
            return {"status": "Success", "graded": 2, "scores_ingested": 5}

    import src.services.grading_service as gs_mod
    monkeypatch.setattr(gs_mod, "GradingService", _FakeGradingService)
    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")

    client = TestClient(app)
    resp = client.post(
        "/api/research/grade?backfill_pending=true&backfill_days=30&max_grade_rows=5000",
        headers={"X-BASEMENT-KEY": "test-secret"},
    )
    assert resp.status_code == 200
    assert resp.json()["graded"] == 2
    assert captured_calls[-1] == {"backfill_days": 30, "backfill_pending": True, "max_grade_rows": 5000}


def test_parlays_today_accepts_date_filter_and_validates_format(monkeypatch):
    import src.database as db

    seen_params = []

    def fake_exec(_conn, sql, params=None):
        s = " ".join(sql.split()).lower()
        if "with latest_preds as" in s:
            seen_params.append(params)
            return _FakeCursor([
                {
                    "event_id": "evt_1",
                    "model_version": "v2",
                    "market_type": "MONEYLINE",
                    "pick": "Duke",
                    "outcome": "WON",
                    "bet_line": None,
                    "price": -180,
                    "win_prob": 0.72,
                    "ev_per_unit": 0.12,
                    "selection": "Duke",
                    "away_team": "Siena",
                    "home_team": "Duke",
                    "start_time": "2026-11-15T23:00:00Z",
                    "day_et": "2026-11-15",
                },
                {
                    "event_id": "evt_2",
                    "model_version": "v2",
                    "market_type": "MONEYLINE",
                    "pick": "St. John's",
                    "outcome": "WON",
                    "bet_line": None,
                    "price": -150,
                    "win_prob": 0.68,
                    "ev_per_unit": 0.13,
                    "selection": "St. John's",
                    "away_team": "Quinnipiac",
                    "home_team": "St. John's",
                    "start_time": "2026-11-15T23:30:00Z",
                    "day_et": "2026-11-15",
                },
            ])
        return _FakeCursor([("2026-11-15",)])

    monkeypatch.setattr(db, "get_db_connection", lambda: _FakeConn())
    monkeypatch.setattr(db, "_exec", fake_exec)
    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")

    client = TestClient(app)

    bad_resp = client.get(
        "/api/ncaam/parlays/today?date=11-15-2026",
        headers={"X-BASEMENT-KEY": "test-secret"},
    )
    assert bad_resp.status_code == 400

    ok_resp = client.get(
        "/api/ncaam/parlays/today?date=2026-11-15",
        headers={"X-BASEMENT-KEY": "test-secret"},
    )
    assert ok_resp.status_code == 200
    body = ok_resp.json()
    assert body["date_et"] == "2026-11-15"
    assert body["legs_considered"] == 2
    assert len(body["high_confidence"]) == 1
    assert seen_params[-1]["target_date"] == "2026-11-15"


def test_history_suppresses_unpublished_fallback_predictions_on_covered_days(monkeypatch):
    import src.database as db

    canonical_2026_11_16 = [
        normalize_history_row({
            "id": "fam_pred_1",
            "event_id": "action:ncaam:fam",
            "day_et": "2026-11-16",
            "sport": "NCAAM",
            "market_type": "SPREAD",
            "away_team": "Florida A&M Rattlers",
            "home_team": "UTEP Miners",
            "selection": "Florida A&M Rattlers +20.5",
            "bet_line": 20.5,
            "bet_price": -110,
            "ev_per_unit": 0.035,
            "outcome": "LOST",
            "start_time": "2026-11-17T02:00:00Z",
        })
    ]

    leaked_fallbacks = [
        # Same covered day (2026-11-16): parlay-only ML + transient line moves must be suppressed!
        normalize_history_row({
            "id": "ml_st_thomas",
            "event_id": "action:ncaam:stthomas",
            "day_et": "2026-11-16",
            "sport": "NCAAM",
            "market_type": "MONEYLINE",
            "away_team": "St. Thomas Tommies",
            "home_team": "LIU Sharks",
            "selection": "St. Thomas Tommies",
            "bet_price": -108,
            "ev_per_unit": 0.073,
            "outcome": "WON",
            "start_time": "2026-11-17T00:00:00Z",
        }),
        # Zero-actionable evaluated day (2026-11-17) must also suppress raw fallbacks!
        normalize_history_row({
            "id": "zero_day_leak",
            "event_id": "action:ncaam:nov17",
            "day_et": "2026-11-17",
            "sport": "NCAAM",
            "market_type": "SPREAD",
            "selection": "Test +4.5",
            "bet_price": -110,
            "ev_per_unit": 0.04,
            "outcome": "PENDING",
            "start_time": "2026-11-17T23:00:00Z",
        }),
        # Older legacy day NOT covered by canonical slate or daily_top_picks is still kept
        normalize_history_row({
            "id": "legacy_uncovered",
            "event_id": "action:ncaam:legacy10",
            "day_et": "2026-11-10",
            "sport": "NCAAM",
            "market_type": "SPREAD",
            "selection": "Legacy +3.5",
            "bet_price": -110,
            "ev_per_unit": 0.05,
            "outcome": "WON",
            "start_time": "2026-11-10T23:00:00Z",
        }),
    ]

    monkeypatch.setattr(db, "fetch_recommended_history_canonical", lambda **kwargs: list(canonical_2026_11_16))
    monkeypatch.setattr(db, "fetch_model_history", lambda **kwargs: list(leaked_fallbacks))
    monkeypatch.setattr(db, "fetch_evaluated_ncaam_days", lambda **kwargs: {"2026-11-16", "2026-11-17"})
    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")

    client = TestClient(app)
    resp = client.get("/api/research/history?sport=NCAAM", headers={"X-BASEMENT-KEY": "test-secret"})
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert "fam_pred_1" in ids
    assert "ml_st_thomas" not in ids
    assert "zero_day_leak" not in ids
    assert "legacy_uncovered" in ids


def test_board_unordered_matchup_dedup_sql_and_calibration_guard():
    import pathlib
    from src.utils.model_calibration import interpolate_pava_prob, is_valid_winprob_calibration

    api_src = pathlib.Path("src/api.py").read_text(encoding="utf-8")
    board_idx = api_src.index('@app.get("/api/board")')
    board_block = api_src[board_idx : board_idx + 4000]
    assert "LEAST(home_key, away_key), GREATEST(home_key, away_key)" in board_block

    collapsed_two_knot = {
        "season": "2026-27",
        "season_start": "2026-11-01",
        "n_obs": 347,
        "points": [
            {"p": 0.505, "p_cal": 0.444},
            {"p": 0.572, "p_cal": 0.525},
        ],
    }
    assert is_valid_winprob_calibration(collapsed_two_knot, min_obs=60, min_max_pcal=0.52, min_season_start="2026-11-01") is False

    tail_curve = {
        "n_obs": 200,
        "points": [
            {"p": 0.40, "p_cal": 0.38},
            {"p": 0.50, "p_cal": 0.49},
            {"p": 0.58, "p_cal": 0.56},
        ],
    }
    assert interpolate_pava_prob(0.66, tail_curve) > 0.56
    assert interpolate_pava_prob(0.32, tail_curve) < 0.38


def test_adaptive_archetype_learning_service_and_endpoint(monkeypatch):
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
    from src.services.archetype_learning_service import (
        classify_spread_bucket,
        fit_adaptive_learning_from_rows,
    )

    assert classify_spread_bucket(-3.5) == "under_6"
    assert classify_spread_bucket(-7.0) == "mid_6_14"
    assert classify_spread_bucket(18.0) == "blowout_14_22"
    assert classify_spread_bucket(-24.0) == "blowout_22_plus"

    rows = []
    # 12 losing mid-spread ATS picks (-7.5) and 6 winning tight-spread picks (-3.5)
    for idx in range(12):
        rows.append({
            "market_type": "SPREAD",
            "pick": "Home Team",
            "home_team": "Home Team",
            "away_team": "Away Team",
            "bet_line": -7.5,
            "bet_price": -110,
            "ev_per_unit": 0.06,
            "edge_points": 2.0,
            "outcome": "LOST" if idx < 10 else "WON",
        })
    for idx in range(6):
        rows.append({
            "market_type": "SPREAD",
            "pick": "Underdog Team",
            "home_team": "Fav Team",
            "away_team": "Underdog Team",
            "bet_line": 3.5,
            "bet_price": -110,
            "ev_per_unit": 0.04,
            "edge_points": 1.5,
            "outcome": "WON" if idx < 5 else "LOST",
        })
    # Add TOTAL rows whose actual final scores ran +4 pts hotter than mu_final
    for _ in range(10):
        rows.append({
            "market_type": "TOTAL",
            "pick": "OVER",
            "bet_line": 144.5,
            "bet_price": -110,
            "ev_per_unit": 0.05,
            "edge_points": 2.0,
            "mu_final": 146.0,
            "home_score": 78,
            "away_score": 72,
            "outcome": "WON",
        })
    # Add winning ~7pt Home Favorite ML row
    rows.append({
        "market_type": "MONEYLINE",
        "pick": "Home Team",
        "home_team": "Home Team",
        "away_team": "Away Team",
        "bet_price": -275,
        "ev_per_unit": 0.025,
        "edge_points": 0.03,
        "outcome": "WON",
    })

    learned = fit_adaptive_learning_from_rows(rows, baseline_bins={"SPREAD:home:2:big": {"n": 45, "mean": 0.02, "sd": 0.95}})
    assert learned["total_graded"] == 29
    assert learned["by_spread_bucket"]["mid_6_14"]["n"] == 12
    assert learned["learned_adjustments"]["spread_bucket_ev_bump"]["mid_6_14"] > 0.0
    assert learned["learned_adjustments"]["total_bias_pts"] > 0.5
    assert learned["by_home_fav_7pt_ml"]["wins"] == 1
    assert "SPREAD:home:2:big" in learned["bins"]

    # ~7pt Home Favorite ML qualifier checks
    model = NCAAMMarketFirstModelV2()
    assert model.is_sweet_spot_home_fav_ml_leg(
        spread_home=-7.0,
        fair_spread_home=-8.2,
        win_prob_home=0.77,
        ml_price_home=-280,
        ev_home=0.025,
        is_neutral=False,
        movement_tags=["sharp_backing"],
    ) is True
    assert model.is_sweet_spot_home_fav_ml_leg(
        spread_home=-7.0,
        fair_spread_home=-8.2,
        win_prob_home=0.77,
        ml_price_home=-280,
        ev_home=-0.01,
        is_neutral=False,
    ) is False
    assert model.is_sweet_spot_home_fav_ml_leg(
        spread_home=-7.0,
        fair_spread_home=-8.2,
        win_prob_home=0.77,
        ml_price_home=-280,
        is_neutral=True,
    ) is False
    assert model.is_sweet_spot_home_fav_ml_leg(
        spread_home=-2.5,
        fair_spread_home=-4.0,
        win_prob_home=0.69,
        ml_price_home=-165,
        is_neutral=False,
    ) is False
    assert model.is_sweet_spot_home_fav_ml_leg(
        spread_home=-7.0,
        fair_spread_home=-8.2,
        win_prob_home=0.77,
        ml_price_home=-280,
        is_neutral=False,
        movement_tags=["contra_sharp_money"],
    ) is False

    import src.services.archetype_learning_service as als

    monkeypatch.setattr(als, "load_adaptive_model_learning", lambda: learned)
    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")
    client = TestClient(app)
    resp = client.get("/api/ncaam/model-learning", headers={"X-BASEMENT-KEY": "test-secret"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["total_graded"] == 29
    assert body["by_home_fav_7pt_ml"]["wins"] == 1





