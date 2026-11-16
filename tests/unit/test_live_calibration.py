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


def test_live_calibration_summary_auto_rebuilds_when_threshold_reached(monkeypatch):
    from contextlib import contextmanager

    monkeypatch.setenv("REQUIRE_DATABASE", "1")
    monkeypatch.setattr(
        lcs,
        "get_active_live_calibration",
        lambda force_refresh=False: {
            "status": "collecting",
            "active": False,
            "season_start": "2026-11-01",
            "min_obs_required": 25,
            "n_obs": 0,
            "params": lcs.default_live_calibration_params(),
            "points": [],
            "bins": [],
        },
    )

    class _FakeAggCursor:
        def fetchone(self):
            return {
                "total_snapshots": 270,
                "pending_snapshots": 8,
                "decided_snapshots": 262,
                "win_count": 120,
                "loss_count": 142,
                "push_count": 0,
            }

    class _FakeConn:
        pass

    @contextmanager
    def _fake_conn():
        yield _FakeConn()

    import src.database as db_mod
    monkeypatch.setattr(db_mod, "get_db_connection", _fake_conn)
    monkeypatch.setattr(db_mod, "_exec", lambda conn, sql, params=None: _FakeAggCursor())
    monkeypatch.setattr(lcs, "_ensure_table", lambda conn: None)

    rebuilt_calls = []

    def _fake_rebuild(*, persist=True, season_start=None):
        rebuilt_calls.append((persist, season_start))
        return {
            "status": "calibrated",
            "active": True,
            "season_start": season_start or "2026-11-01",
            "min_obs_required": 25,
            "n_obs": 262,
            "params": {"live_weight_scale": 0.95, "sigma_spread_rem": 11.5, "sigma_total_rem": 15.0},
            "points": [{"p": 0.2, "p_cal": 0.18, "n": 20}, {"p": 0.8, "p_cal": 0.72, "n": 20}],
            "bins": [{"label": "0–20%", "count": 119, "avg_predicted_pct": 7.8, "actual_win_pct": 9.2}],
            "brier_raw": 0.169,
            "brier_calibrated": 0.148,
            "updated_at": "2026-11-16T12:00:00Z",
        }

    monkeypatch.setattr(lcs, "rebuild_live_calibration", _fake_rebuild)

    summary = lcs.get_live_calibration_summary()
    assert len(rebuilt_calls) == 1
    assert summary["status"] == "calibrated"
    assert summary["active"] is True
    assert summary["n_obs"] == 262
    assert summary["brier_calibrated"] == 0.148


def test_rebuild_live_calibration_returns_active_even_if_persist_fails(monkeypatch):
    from contextlib import contextmanager
    import src.database as db_mod

    sample_rows = [
        {
            "elapsed_fraction": 0.65,
            "home_score": 54 if i % 3 != 0 else 38,
            "away_score": 52 if i % 3 != 0 else 44,
            "pregame_total": 144.0,
            "pregame_home_margin": 3.0,
            "market_type": "TOTAL" if i % 2 == 0 else "SPREAD",
            "side": "OVER" if i % 2 == 0 else "HOME",
            "bet_line": 143.5 if i % 2 == 0 else -2.5,
            "outcome": "WON" if i % 3 != 0 else "LOST",
        }
        for i in range(30)
    ]

    class _FakeCursor:
        def fetchall(self):
            return sample_rows

    class _FakeConn:
        def commit(self):
            pass

    @contextmanager
    def _fake_conn():
        yield _FakeConn()

    monkeypatch.setenv("REQUIRE_DATABASE", "1")
    monkeypatch.setattr(db_mod, "get_db_connection", _fake_conn)
    monkeypatch.setattr(db_mod, "_exec", lambda conn, sql, params=None: _FakeCursor())
    monkeypatch.setattr(db_mod, "upsert_model_param", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("readonly")))
    monkeypatch.setattr(lcs, "_ensure_table", lambda conn: None)
    monkeypatch.setattr(lcs, "grade_pending_live_snapshots", lambda conn=None: 0)

    res = lcs.rebuild_live_calibration(persist=True, season_start="2026-11-01")
    assert res["status"] == "calibrated"
    assert res["active"] is True
    assert res["n_obs"] == 30
    assert res["brier_calibrated"] is not None
