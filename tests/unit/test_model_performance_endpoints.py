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


