"""Unit tests for injury pricing, RLM split confirmation, correlation Decimal safety,
today-scoped board health, Moneyline CLV SQL, walk-forward weight tuning, and JSON sanitization.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
from src.scripts.backtest_ncaam_model import recommend_weights_walkforward
from src.scripts.board_health import status_from_health
from src.scripts.build_daily_top_picks import upsert_pick
from src.services.correlation.ncaam_correlation_engine import NCAAMCorrelationEngine
from src.services.grading_service import GradingService
from src.services.injury_service import InjuryService


def test_injury_service_kenpom_player_impact_and_bounds():
    svc = InjuryService()

    # Star home scorer OUT with KenPom player metrics shifts spread + toward home dog & lowers total
    res = svc.evaluate_injuries(
        [{"team": "Duke", "player": "Cooper Flagg", "status": "Out", "position": "F"}],
        "Duke",
        "North Carolina",
        home_players=[
            {"player_name": "Cooper Flagg", "metrics": {"min_pct": 85, "usg": 32, "ortg": 124, "ppg": 20.5}},
        ],
    )
    assert res["has_injuries"] is True
    assert res["home_impact_pts"] > 2.0
    assert res["away_impact_pts"] == 0.0
    assert 0.0 < res["spread_adj"] <= 3.0
    assert -3.0 <= res["total_adj"] < 0.0
    assert res["impact_players"][0]["player"] == "Cooper Flagg"

    # Multi-star out cannot exceed +/- 3.0 spread or -3.0 total guardrail
    capped = svc.evaluate_injuries(
        [
            {"team": "Duke", "player": "Starter One", "status": "Out", "position": "G"},
            {"team": "Duke", "player": "Starter Two", "status": "Out", "position": "C"},
            {"team": "Duke", "player": "Starter Three", "status": "Out", "position": "F"},
        ],
        "Duke",
        "North Carolina",
        home_players=[
            {"player_name": "Starter One", "metrics": {"min_pct": 85, "usg": 30, "ppg": 20.0}},
            {"player_name": "Starter Two", "metrics": {"min_pct": 80, "usg": 27, "ppg": 17.5}},
            {"player_name": "Starter Three", "metrics": {"min_pct": 75, "usg": 24, "ppg": 15.0}},
        ],
    )
    assert -3.0 <= capped["spread_adj"] <= 3.0
    assert -3.0 <= capped["total_adj"] <= 0.0

    # Positional fallback works when no KenPom roster metrics are supplied
    fallback = svc.evaluate_injuries(
        [{"team": "North Carolina", "player": "Reserve Guard", "status": "Questionable", "position": "G"}],
        "Duke",
        "North Carolina",
    )
    assert fallback["away_impact_pts"] > 0.0
    assert fallback["spread_adj"] < 0.0


def test_split_and_rlm_confirmation_boost_and_injury_tag():
    model = NCAAMMarketFirstModelV2()
    recs = [{"market": "SPREAD", "side": "AWAY", "ev": 0.03, "movement_tags": []}]
    splits = {
        "SPREAD": {
            "AWAY": {"bet_pct": 26, "handle_pct": 66},
            "HOME": {"bet_pct": 74, "handle_pct": 34},
        }
    }
    mc_info = {"open_spread_home": -4.5, "current_spread_home": -3.5}  # Moved +1.0 toward AWAY

    out = model._apply_split_and_injury_signals(
        recs,
        action_splits=splits,
        injury_context={"spread_adj": 0.9, "has_injuries": True},
        market_consensus=mc_info,
    )
    assert len(out) == 1
    assert "sharp_backing" in out[0]["movement_tags"]
    assert "rlm_confirmed" in out[0]["movement_tags"]
    assert "injury_line_adjusted" in out[0]["movement_tags"]
    assert out[0]["ev"] == pytest.approx(0.035, abs=1e-4)


def test_correlation_engine_handles_postgres_decimals():
    eng = NCAAMCorrelationEngine()
    eng.MIN_SAMPLE_SIZE = 2

    df = pd.DataFrame([
        {
            "home_pace": Decimal("71.5"),
            "away_pace": Decimal("70.5"),
            "home_net_eff": Decimal("21.0"),
            "away_net_eff": Decimal("12.0"),
            "close_spread": Decimal("-5.5"),
            "close_total": Decimal("145.5"),
            "margin": Decimal("8"),
            "total_score": Decimal("150"),
        },
        {
            "home_pace": Decimal("71.5"),
            "away_pace": Decimal("70.5"),
            "home_net_eff": Decimal("21.0"),
            "away_net_eff": Decimal("12.0"),
            "close_spread": Decimal("-5.5"),
            "close_total": Decimal("145.5"),
            "margin": Decimal("2"),
            "total_score": Decimal("138"),
        },
    ])
    binned = eng.build_archetype_bins(df)
    assert len(binned) == 2
    metrics = eng.compute_metrics(binned)
    assert isinstance(metrics, dict)
    assert any(v.get("status") == "valid" for v in metrics.values())


def test_board_health_separates_today_from_three_day_window():
    # Today (days=1) 100% covered even if future 3-day window has >40% missing totals -> OK
    h_ok = {
        "events_total": 40,
        "with_spread": 20,
        "with_total": 20,
        "missing_total_pct": 0.50,
        "today_events_total": 10,
        "today_with_spread": 10,
        "today_with_total": 10,
        "today_missing_total_pct": 0.0,
    }
    assert status_from_health(h_ok) == "ok"

    # Today missing > 40% totals -> ALERT
    h_alert = {
        **h_ok,
        "today_events_total": 10,
        "today_with_spread": 10,
        "today_with_total": 4,
        "today_missing_total_pct": 0.60,
    }
    assert status_from_health(h_alert) == "alert"


def test_grading_clv_sql_includes_moneyline_implied_prob():
    svc = GradingService()
    mock_conn = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_conn

    with patch("src.services.grading_service.get_db_connection", return_value=mock_ctx), \
         patch("src.services.grading_service._exec") as mock_exec:
        mock_exec.return_value.rowcount = 2
        updated = svc._compute_clv_for_started_games(max_rows=100, lookback_days=3)

    assert updated == 2
    sql_executed = mock_exec.call_args[0][1]
    assert "m.market_type='MONEYLINE' AND m.close_price IS NULL" in sql_executed
    assert "odds_snapshot_ml_prob_before_tip" in sql_executed


def test_walkforward_weight_recommendation_thresholds_and_folds():
    # Insufficient sample stays strictly non-destructive
    small = recommend_weights_walkforward(
        [{"start_time": "2026-11-01T18:00:00Z", "close_spread": -4.5, "final_margin": 6.0}] * 20,
        min_bets=75,
    )
    assert small["status"] == "insufficient_sample"
    assert small["non_destructive"] is True
    assert small["recommended_weights"] is None

    # Synthetic 100-game edge series where KenPom carries true signal
    records = []
    for idx in range(100):
        day = (idx % 28) + 1
        sign = 1.0 if idx % 2 == 0 else -1.0
        records.append({
            "event_id": f"g_{idx}",
            "start_time": f"2026-11-{day:02d}T19:00:00Z",
            "close_spread": -4.0,
            "mu_market_spread": -4.0,
            "diff_torvik": 0.0,
            "diff_kenpom": -10.0 * sign,
            "diff_hasla": -6.0 * sign,
            "other_adj": 0.0,
            "spread_price_home": -110,
            "spread_price_away": -110,
            "final_margin": 4.0 + (7.0 * sign),
        })

    out = recommend_weights_walkforward(records, min_bets=75, min_edge=1.5)
    assert out["non_destructive"] is True
    assert out["n_games"] == 100
    assert len(out["folds"]) == 3


def test_upsert_pick_sanitizes_raw_datetime_serialization_errors():
    mock_conn = MagicMock()
    res = {
        "model_version": "ncaam_market_first_v2",
        "recommendations": [],
        "block_reason": "Object of type datetime is not JSON serializable",
        "context_json": {"captured_at": datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)},
    }
    with patch("src.scripts.build_daily_top_picks._exec") as mock_exec:
        upsert_pick("2026-11-13", "evt_err_1", res, conn=mock_conn)

    params = mock_exec.call_args[0][2]
    assert "JSON serializable" not in (params["reason"] or "")
    assert "unavailable" in (params["reason"] or "").lower()


def test_correlations_game_endpoint_sql_has_no_unescaped_percent_and_returns_200(monkeypatch):
    from fastapi.testclient import TestClient
    from src.api import app
    from src.config import settings

    row_data = {
        "id": "action:ncaam:297763",
        "start_time": datetime(2026, 11, 13, 23, 0, tzinfo=timezone.utc),
        "close_spread": Decimal("-6.5"),
        "home_pace": Decimal("71.2"),
        "home_net_eff": Decimal("22.4"),
        "away_pace": Decimal("68.8"),
        "away_net_eff": Decimal("9.6"),
    }
    mock_conn = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_conn
    captured_sql = []

    def _fake_exec(conn, sql, params=None):
        captured_sql.append(sql)
        cur = MagicMock()
        cur.fetchone.return_value = row_data
        return cur

    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")
    with patch("src.database.get_db_connection", return_value=mock_ctx), \
         patch("src.database._exec", side_effect=_fake_exec):
        client = TestClient(app)
        resp = client.get(
            "/api/ncaam/correlations/game?event_id=action:ncaam:297763",
            headers={"X-BASEMENT-KEY": "test-secret"},
        )

    assert resp.status_code == 200
    assert captured_sql and "'%'" not in captured_sql[0]
    body = resp.json()
    assert body["archetype"]["key"]

