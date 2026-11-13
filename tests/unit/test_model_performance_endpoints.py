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
