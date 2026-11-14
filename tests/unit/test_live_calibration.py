"""Unit tests for Step 4: live in-game win-probability calibration service & endpoints."""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("REQUIRE_DATABASE", "0")

from fastapi.testclient import TestClient

from src import api
from src.services import live_calibration_service as lcs


def test_fit_live_calibration_collecting_below_threshold():
    rows = [
        {
            "elapsed_fraction": 0.5,
            "home_score": 38,
            "away_score": 34,
            "pregame_total": 144.0,
            "pregame_home_margin": 4.0,
            "market_type": "SPREAD",
            "side": "HOME",
            "bet_line": -3.5,
            "outcome": "WON" if i % 2 == 0 else "LOST",
        }
        for i in range(10)
    ]
    res = lcs.fit_live_calibration_artifact(rows, season_start="2026-11-01", min_obs=25)
    assert res["status"] == "collecting"
    assert res["active"] is False
    assert res["n_obs"] == 10
    assert res["points"] == []
    assert len(res["bins"]) == 5


def test_fit_live_calibration_calibrates_and_produces_monotonic_points():
    rows = []
    # 36 synthetic trajectories covering SPREAD and TOTAL outcomes across confidence levels
    for i in range(36):
        is_total = i % 2 == 0
        strong_pos = i % 3 != 0
        if is_total:
            rows.append({
                "elapsed_fraction": 0.65,
                "home_score": 52 if strong_pos else 36,
                "away_score": 50 if strong_pos else 34,
                "pregame_total": 145.0,
                "pregame_home_margin": 0.0,
                "market_type": "TOTAL",
                "side": "OVER",
                "bet_line": 144.5,
                "outcome": "WON" if strong_pos else "LOST",
            })
        else:
            rows.append({
                "elapsed_fraction": 0.70,
                "home_score": 58 if strong_pos else 44,
                "away_score": 45 if strong_pos else 54,
                "pregame_total": 142.0,
                "pregame_home_margin": 3.5,
                "market_type": "SPREAD",
                "side": "HOME",
                "bet_line": -2.5,
                "outcome": "WON" if strong_pos else "LOST",
            })

    artifact = lcs.fit_live_calibration_artifact(rows, season_start="2026-11-01", min_obs=25)
    assert artifact["status"] == "calibrated"
    assert artifact["active"] is True
    assert artifact["n_obs"] == 36
    assert artifact["brier_calibrated"] is not None
    assert artifact["brier_calibrated"] <= artifact["brier_raw"] + 0.01

    pts = artifact["points"]
    assert len(pts) >= 2
    for a, b in zip(pts, pts[1:]):
        assert a["p_cal"] <= b["p_cal"] + 1e-6

    proj = lcs.compute_live_bet_win_prob(
        elapsed_fraction=0.70,
        home_score=58,
        away_score=45,
        pregame_total=142.0,
        pregame_home_margin=3.5,
        market_type="SPREAD",
        side="HOME",
        bet_line=-2.5,
        params=artifact["params"],
        calibration=artifact,
    )
    assert 0.5 < proj["calibrated_live_win_prob"] <= 0.99


def test_compute_live_bet_win_prob_total_over_cashed():
    res = lcs.compute_live_bet_win_prob(
        elapsed_fraction=0.80,
        home_score=78,
        away_score=70,
        pregame_total=142.0,
        pregame_home_margin=0.0,
        market_type="TOTAL",
        side="OVER",
        bet_line=144.5,
    )
    assert res["raw_live_win_prob"] == 0.99


def test_grade_pending_live_snapshots_with_mock_db():
    pending_row = {
        "id": 7,
        "market_type": "SPREAD",
        "side": "HOME",
        "selection": "Duke -4.5",
        "bet_line": -4.5,
        "home_team": "Duke",
        "away_team": "North Carolina",
        "actual_home_score": 82,
        "actual_away_score": 70,
    }
    mock_conn = MagicMock()
    select_cursor = MagicMock()
    select_cursor.fetchall.return_value = [pending_row]
    update_cursor = MagicMock()

    with patch.object(lcs, "_ensure_table"), patch(
        "src.database._exec", side_effect=[select_cursor, update_cursor]
    ) as mock_exec:
        graded = lcs.grade_pending_live_snapshots(conn=mock_conn)

    assert graded == 1
    assert mock_exec.call_count == 2
    assert update_cursor is not None
    # Verify UPDATE args set WON
    update_args = mock_exec.call_args_list[1][0][2]
    assert update_args[0] == "WON"
    assert update_args[1:] == (82, 70, 7)


def test_api_live_calibration_endpoint(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")
    lcs.invalidate_live_calibration_cache()
    client = TestClient(api.app)
    resp = client.get("/api/ncaam/live-calibration", headers={"X-BASEMENT-KEY": "test-secret"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("collecting", "calibrated")
    assert "params" in body
    assert "bins" in body
