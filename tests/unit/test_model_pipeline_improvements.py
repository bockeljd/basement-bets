"""Unit tests for injury pricing, RLM split confirmation, correlation Decimal safety,
today-scoped board health, Moneyline CLV SQL, walk-forward weight tuning, and JSON sanitization.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import sys
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

    rows = [
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
    ]

    # Pure-Python list[dict] path (used on Vercel serverless runtime)
    binned_py = eng.build_archetype_bins(rows)
    assert isinstance(binned_py, list) and len(binned_py) == 2
    metrics_py = eng.compute_metrics(binned_py)
    assert any(v.get("status") == "valid" for v in metrics_py.values())

    # Legacy DataFrame path
    binned_df = eng.build_archetype_bins(pd.DataFrame(rows))
    assert len(binned_df) == 2
    metrics_df = eng.compute_metrics(binned_df)
    assert isinstance(metrics_df, dict)
    assert any(v.get("status") == "valid" for v in metrics_df.values())


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

    monkeypatch.setitem(sys.modules, "pandas", None)
    monkeypatch.setitem(sys.modules, "numpy", None)
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


def test_parse_kenpom_web_table_paste_with_unicode_minus_and_interleaved_ranks():
    from src.scripts.ingest_kenpom import parse_kenpom_csv_text

    # Mimics copying live HTML table off kenpom.com:
    # - headers omit unnamed rank sub-columns next to ORtg, DRtg, AdjT
    # - negative numbers use Unicode minus \u2212
    pasted = (
        "Rk\tTeam\tConf\tW-L\tNetRtg\tORtg\tDRtg\tAdjT\tLuck\n"
        "1\tDuke 1\tACC\t28-4\t+32.14\t126.1\t1\t94.0\t4\t68.2\t110\t+.020\n"
        "185\tBrown\tIvy\t14-14\t\u22124.15\t103.5\t195\t107.6\t180\t66.4\t240\t\u2212.012\n"
    )
    rows = parse_kenpom_csv_text(pasted)
    assert len(rows) == 2
    assert rows[0]["team_name"] == "Duke"
    assert rows[0]["adj_em"] == pytest.approx(32.14)
    assert rows[0]["adj_o"] == pytest.approx(126.1)
    assert rows[0]["adj_d"] == pytest.approx(94.0)
    assert rows[0]["adj_t"] == pytest.approx(68.2)
    assert rows[1]["team_name"] == "Brown"
    assert rows[1]["adj_em"] == pytest.approx(-4.15)
    assert rows[1]["adj_o"] == pytest.approx(103.5)
    assert rows[1]["adj_d"] == pytest.approx(107.6)
    assert rows[1]["adj_t"] == pytest.approx(66.4)


def test_get_kenpom_status_and_admin_sync_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    import src.scripts.ingest_kenpom as ik
    import src.scripts.update_data_health as udh
    from src.api import app
    from src.config import settings

    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")
    monkeypatch.setattr(settings, "CRON_SECRET", "cron-secret")
    monkeypatch.delenv("KENPOM_API_KEY", raising=False)
    monkeypatch.delenv("KENPOM_EMAIL", raising=False)
    monkeypatch.delenv("KENPOM_PASSWORD", raising=False)
    monkeypatch.delenv("KENPOM_COOKIE", raising=False)

    class _StatusCursor:
        def __init__(self, sql):
            self._sql = sql

        def fetchone(self):
            if "FROM kenpom_team_ratings_daily" in self._sql:
                return {"asof_date": "2026-04-06", "n": 365}
            if "FROM data_health" in self._sql:
                return {"status": "stale", "notes": '{"asof_date":"2026-04-06"}', "last_success_at": None}
            return None

    class _StatusConn:
        pass

    @contextmanager
    def _fake_db():
        yield _StatusConn()

    with patch("src.scripts.ingest_kenpom.get_db_connection", _fake_db), \
         patch("src.scripts.ingest_kenpom._exec", side_effect=lambda conn, sql, params=None: _StatusCursor(sql)):
        st = ik.get_kenpom_status()

    assert st["active"] is False
    assert st["latest_asof_date"] == "2026-04-06"
    assert st["team_count"] == 365
    assert "prior season" in st["human_summary"]

    sample_api_rows = [
        {
            "TeamName": f"Team {i}",
            "RankAdjEM": i,
            "ConfShort": "ACC",
            "Wins": 20,
            "Losses": 5,
            "AdjEM": 20.0 - i,
            "AdjOE": 115.0,
            "AdjDE": 95.0 + i,
            "AdjTempo": 68.0,
        }
        for i in range(1, 13)
    ]

    class _FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return sample_api_rows

    monkeypatch.setattr(ik.requests, "get", lambda *a, **kw: _FakeResp())
    monkeypatch.setattr(ik, "ensure_tables", lambda: None)
    monkeypatch.setattr(ik, "upsert_daily", lambda table, asof, rows, keys: len(rows))
    monkeypatch.setattr(udh, "upsert", lambda *a, **kw: None)

    client = TestClient(app)

    # Admin POST /api/admin/kenpom/sync succeeds with API key in body
    resp_sync = client.post(
        "/api/admin/kenpom/sync",
        headers={"X-BASEMENT-KEY": "test-secret"},
        json={"api_key": "kp-secret-test"},
    )
    assert resp_sync.status_code == 200
    body_sync = resp_sync.json()
    assert body_sync["status"] == "ok"
    assert body_sync["method"] == "official_api"
    assert body_sync["rows"] == 12

    import src.services.job_service as js

    class _FakeJobContext:
        def __init__(self, job_name: str):
            self.job_name = job_name
            self.state = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

    monkeypatch.setattr(js, "JobContext", _FakeJobContext)

    # Cron /api/jobs/ingest_kenpom uses run_kenpom_sync cleanly when env API key is set
    monkeypatch.setenv("KENPOM_API_KEY", "kp-cron-test")
    resp_cron = client.get(
        "/api/jobs/ingest_kenpom",
        headers={"Authorization": "Bearer cron-secret"},
    )
    assert resp_cron.status_code == 200
    body_cron = resp_cron.json()
    assert body_cron["status"] == "success"
    assert body_cron["teams_count"] == 12
    assert body_cron["method"] == "official_api"

    # Invalid API key (401 from KenPom) maps cleanly to HTTP 400
    class _UnauthorizedResp:
        status_code = 401
        text = "Invalid token"

    monkeypatch.setattr(ik.requests, "get", lambda *a, **kw: _UnauthorizedResp())
    resp_bad = client.post(
        "/api/admin/kenpom/sync",
        headers={"X-BASEMENT-KEY": "test-secret"},
        json={"api_key": "bad-key"},
    )
    assert resp_bad.status_code == 400
    assert "rejected" in resp_bad.json()["detail"].lower()


def test_model_v2_populates_kenpom_fair_total_and_mu_total_final(monkeypatch):
    from datetime import date

    model = NCAAMMarketFirstModelV2()
    model.torvik_service = MagicMock()
    model.torvik_service.get_projection.return_value = {
        "margin": 6.0,
        "official_margin": 6.0,
        "total": 144.0,
        "projected_score": "69-75",
        "lean": "Home",
    }
    model.torvik_service.get_matchup_team_stats.return_value = {
        "game_tempo": 68.5,
        "home": {"luck": 0.0, "continuity": 75.0, "record": "12-4"},
        "away": {"luck": 0.0, "continuity": 70.0, "record": "10-6"},
    }

    model.kenpom_client = MagicMock()
    model.kenpom_client.calculate_kenpom_adjustment.return_value = {
        "spread_adj": 7.5,
        "neutral_margin": 5.0,
        "fair_margin": 7.5,
        "total_adj": 2.4,
        "tempo_expected": 69.0,
        "summary": "Home +7.5",
    }
    model.kenpom_client.get_team_player_agg.return_value = None
    model.kenpom_client.get_team_rating.return_value = {"adj_em": 18.0, "adj_t": 69.0}
    model.kenpom_client.get_home_court.return_value = None
    model.kenpom_client.get_player_stats_for_team.return_value = []

    model.haslametrics_client = MagicMock()
    model.haslametrics_client.calculate_projection.return_value = None

    model.injury_service = MagicMock()
    model.injury_service.get_matchup_injuries.return_value = {"has_injuries": False, "injuries": []}
    model.geo_service = MagicMock()
    model.geo_service.get_altitude_adjustment.return_value = 0.0
    model.geo_service.calculate_distance.return_value = 50.0
    model.news_service = MagicMock()
    model.news_service.get_team_news.return_value = []
    model.news_service.summarize_impact.return_value = ""

    monkeypatch.setattr(model, "_calculate_shooting_regression", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_situational_spots", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_fatigue_penalty", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot, avg_ftr=None: tot)
    monkeypatch.setattr(model, "_load_winprob_calibration", lambda: {"points": []})

    event = {
        "id": "evt_kp_total_1",
        "home_team": "Clemson Tigers",
        "away_team": "Georgetown Hoyas",
        "start_time": datetime(2026, 11, 13, 19, 0, 0),
    }
    snap = {"spread_home": -5.5, "total": 146.0}
    res = model.analyze("evt_kp_total_1", event_context=event, market_snapshot=snap, relax_gates=True, persist=False)

    assert res["signals"]["kenpom"]["fair_spread_home"] == pytest.approx(-7.5, abs=0.1)
    assert res["signals"]["kenpom"]["fair_total"] == pytest.approx(148.4, abs=0.1)
    assert res["debug"]["mu_total_final"] is not None
    assert res["debug"]["mu_spread_final"] is not None


def test_parse_kenpom_saved_html_with_colspan_and_upload_clears_caches(monkeypatch):
    from fastapi.testclient import TestClient
    import src.scripts.ingest_kenpom as ik
    import src.scripts.update_data_health as udh
    import src.api as api_mod
    from src.config import settings

    def _row(rk, team, conf, wl, em, o, o_rk, d, d_rk, t, t_rk):
        return (
            f"<tr><td>{rk}</td><td><a href='#'>{team}</a></td><td>{conf}</td><td>{wl}</td>"
            f"<td>{em}</td><td>{o}</td><td>{o_rk}</td><td>{d}</td><td>{d_rk}</td>"
            f"<td>{t}</td><td>{t_rk}</td></tr>"
        )

    rows_html = [
        _row(1, "Duke 1*", "ACC", "28-4", "+32.14", "126.1", 1, "94.0", 4, "68.2", 110),
        _row(2, "Brown", "Ivy", "14-14", "\u22124.15", "103.5", 195, "107.6", 180, "66.4", 240),
    ] + [
        _row(i, f"School {i}", "BE", "15-10", "+5.10", "110.0", i, "104.9", i, "67.5", i)
        for i in range(3, 13)
    ]

    html_doc = (
        "<!doctype html><html><body>"
        "<table id='ratings-table'>"
        "<thead>"
        "<tr><th colspan='5'>Team Info</th><th colspan='6'>Efficiency</th></tr>"
        "<tr><th>Rk</th><th>Team</th><th>Conf</th><th>W-L</th><th>NetRtg</th>"
        "<th colspan='2'>ORtg</th><th colspan='2'>DRtg</th><th colspan='2'>AdjT</th></tr>"
        "</thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table></body></html>"
    )

    parsed = ik.parse_kenpom_csv_text(html_doc)
    assert len(parsed) == 12
    assert parsed[0]["team_name"] == "Duke"
    assert parsed[0]["adj_em"] == pytest.approx(32.14)
    assert parsed[0]["adj_o"] == pytest.approx(126.1)
    assert parsed[0]["adj_d"] == pytest.approx(94.0)
    assert parsed[0]["adj_t"] == pytest.approx(68.2)
    assert parsed[1]["team_name"] == "Brown"
    assert parsed[1]["adj_em"] == pytest.approx(-4.15)
    assert parsed[1]["adj_o"] == pytest.approx(103.5)
    assert parsed[1]["adj_d"] == pytest.approx(107.6)

    # scrape_team_ratings delegates to header-aware HTML parser cleanly
    fake_sess = MagicMock()
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.text = html_doc
    fake_sess.get.return_value = fake_resp
    scraped = ik.scrape_team_ratings(fake_sess)
    assert len(scraped) == 12
    assert scraped[1]["adj_em"] == pytest.approx(-4.15)

    # Multipart .html upload clears both _HTTP_CACHE and _top_picks_cache
    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")
    monkeypatch.setattr(ik, "ensure_tables", lambda: None)
    monkeypatch.setattr(ik, "upsert_daily", lambda table, asof, rows, keys: len(rows))
    monkeypatch.setattr(udh, "upsert", lambda *a, **kw: None)
    api_mod._HTTP_CACHE["stale_key"] = (9999999999.0, {"old": True}, 'W/"old"')
    api_mod._top_picks_cache["stale_tp"] = {"at": 0, "data": {}}

    client = TestClient(api_mod.app)
    resp = client.post(
        "/api/admin/kenpom/upload-csv",
        headers={"X-BASEMENT-KEY": "test-secret"},
        files={"file": ("kenpom_ratings.html", html_doc.encode("utf-8"), "text/html")},
    )
    assert resp.status_code == 200
    assert resp.json()["rows"] == 12
    assert "stale_key" not in api_mod._HTTP_CACHE
    assert "stale_tp" not in api_mod._top_picks_cache


def test_kenpom_rich_metrics_and_efficiency_total():
    import src.scripts.ingest_kenpom as ik
    from src.services.kenpom_client import KenPomClient

    html_doc = (
        "<!doctype html><html><body><table id='ratings-table'><thead>"
        "<tr><th>Rk</th><th>Team</th><th>Conf</th><th>W-L</th><th>NetRtg</th>"
        "<th colspan='2'>ORtg</th><th colspan='2'>DRtg</th><th colspan='2'>AdjT</th>"
        "<th colspan='2'>Luck</th><th colspan='2'>NetRtg</th>"
        "<th colspan='2'>ORtg</th><th colspan='2'>DRtg</th><th colspan='2'>NetRtg</th></tr>"
        "</thead><tbody>"
        "<tr><td>1</td><td>Duke</td><td>ACC</td><td>3-0</td><td>+31.4</td>"
        "<td>124.2</td><td>2</td><td>92.8</td><td>3</td><td>70.0</td><td>40</td>"
        "<td>+.042</td><td>85</td><td>+8.5</td><td>15</td><td>111.0</td><td>10</td><td>102.5</td><td>20</td><td>+6.4</td><td>22</td></tr>"
        "<tr><td>45</td><td>Brown</td><td>Ivy</td><td>1-2</td><td>-2.0</td>"
        "<td>104.0</td><td>180</td><td>106.0</td><td>175</td><td>66.0</td><td>240</td>"
        "<td>-.031</td><td>290</td><td>-3.5</td><td>210</td><td>102.0</td><td>215</td><td>105.5</td><td>195</td><td>-8.0</td><td>310</td></tr>"
        "</tbody></table></body></html>"
    )
    parsed = ik.parse_kenpom_csv_text(html_doc)
    assert len(parsed) == 2
    assert parsed[0]["luck"] == pytest.approx(0.042)
    assert parsed[0]["sos_adj_em"] == pytest.approx(8.5)
    assert parsed[0]["opp_o"] == pytest.approx(111.0)
    assert parsed[0]["opp_d"] == pytest.approx(102.5)
    assert parsed[0]["ncsos_adj_em"] == pytest.approx(6.4)
    assert parsed[1]["luck"] == pytest.approx(-0.031)
    assert parsed[1]["ncsos_adj_em"] == pytest.approx(-8.0)

    kp = KenPomClient.__new__(KenPomClient)
    kp.get_team_rating = lambda name, conn=None: (
        {
            "team": "Duke",
            "rank": 1,
            "adj_em": 31.4,
            "adj_o": 124.2,
            "adj_d": 92.8,
            "adj_t": 70.0,
            "luck": 0.042,
            "sos_adj_em": 8.5,
            "ncsos_adj_em": 6.4,
        }
        if name == "Duke"
        else {
            "team": "Brown",
            "rank": 45,
            "adj_em": -2.0,
            "adj_o": 104.0,
            "adj_d": 106.0,
            "adj_t": 66.0,
            "luck": -0.031,
            "sos_adj_em": -3.5,
            "ncsos_adj_em": -8.0,
        }
    )
    adj = kp.calculate_kenpom_adjustment("Duke", "Brown", neutral_site=False)
    assert adj["fair_total"] is not None and 130.0 < adj["fair_total"] < 170.0
    assert adj["projected_score"] is not None and "-" in adj["projected_score"]
    assert adj["luck_diff"] == pytest.approx(0.073)
    assert adj["sos_diff"] == pytest.approx(12.0)
    assert adj["sos_spread_adj"] > 0.0


def test_torvik_symmetric_hca_and_hasla_prefix_matching():
    from src.services.torvik_projection import TorvikProjectionService
    from src.services.haslametrics_client import HaslametricsClient
    from src.utils.team_matcher import TeamMatcher

    svc = TorvikProjectionService.__new__(TorvikProjectionService)
    svc.LEAGUE_AVG_EFF = 106.5
    stats_pair = {
        "home": {"adj_off": 112.0, "adj_def": 100.0, "adj_tempo": 68.0},
        "away": {"adj_off": 112.0, "adj_def": 100.0, "adj_tempo": 68.0},
        "game_tempo": 68.0,
    }
    svc.get_matchup_team_stats = lambda h, a, date=None: stats_pair
    proj_home = svc.compute_torvik_projection("Team A", "Team B", neutral_site=False)
    proj_neutral = svc.compute_torvik_projection("Team A", "Team B", neutral_site=True)
    # Symmetric HCA (+1.6 / -1.6) shifts margin by +3.2 without inflating total
    assert proj_home["margin"] == pytest.approx(proj_neutral["margin"] + 3.2)
    assert proj_home["total"] == pytest.approx(proj_neutral["total"])

    hc = HaslametricsClient.__new__(HaslametricsClient)
    hc.matcher = TeamMatcher()
    hc.matcher.find_source_name = lambda *a, **kw: None
    hc._all_names_cache = ["Geo. Washington", "Saint Mary's", "Ohio St."]
    assert hc._find_hasla_team_name(None, "George Washington Colonials") == "Geo. Washington"


def test_model_conviction_boost_and_context_fair_lines_and_job_tuple_unpack(monkeypatch):
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
    from fastapi.testclient import TestClient
    import src.api as api_mod
    from src.config import settings

    model = NCAAMMarketFirstModelV2()
    monkeypatch.setattr(model, "_get_council_verdict", lambda eid: None)
    ev_ctx = {
        "id": "action:ncaam:999999",
        "home_team": "George Washington Colonials",
        "away_team": "Harvard Crimson",
        "start_time": "2026-11-13T23:00:00+00:00",
        "neutral_site": False,
    }
    monkeypatch.setattr(
        model.torvik_service,
        "get_projection",
        lambda h, a, date=None, neutral_site=False: {
            "margin": 8.0,  # fair spread -8.0 (3.5 pts stronger than -4.5 market)
            "total": 144.0,
            "projected_score": "68-76",
            "lean": "Home",
        },
    )
    monkeypatch.setattr(
        model.torvik_service,
        "get_matchup_team_stats",
        lambda h, a, date=None: {
            "home": {"continuity": 0.72, "luck": 0.0, "record": "3-0", "adj_off": 114.0, "adj_def": 99.0},
            "away": {"continuity": 0.72, "luck": 0.0, "record": "3-0", "adj_off": 106.0, "adj_def": 103.0},
            "game_tempo": 69.0,
        },
    )
    monkeypatch.setattr(
        model.kenpom_client,
        "calculate_kenpom_adjustment",
        lambda h, a, neutral_site=False: {
            "spread_adj": 8.5,
            "fair_margin": 8.5,
            "neutral_margin": 5.3,
            "total_adj": 0.3,
            "fair_total": 145.5,
            "sos_spread_adj": 0.25,
            "summary": "KenPom: George Washington vs Harvard",
        },
    )
    monkeypatch.setattr(model.kenpom_client, "get_player_stats_for_team", lambda t, limit=50: [])
    monkeypatch.setattr(model.kenpom_client, "get_team_player_agg", lambda t: None)
    monkeypatch.setattr(model.kenpom_client, "get_team_rating", lambda t: {"adj_t": 69.0})
    monkeypatch.setattr(model.kenpom_client, "get_home_court", lambda t: None)
    monkeypatch.setattr(
        model.haslametrics_client,
        "calculate_projection",
        lambda h, a, neutral_site=False, asof_date=None: {
            "available": True,
            "margin": 8.2,
            "total": 143.5,
            "projected_score": "68-76",
            "home": {"sos": 50, "mom": 0.05, "inc": 0.08},
            "away": {"sos": 150, "mom": -0.02, "inc": 0.08},
        },
    )
    monkeypatch.setattr(model.geo_service, "get_altitude_adjustment", lambda h, neutral_site=False: 0.0)
    monkeypatch.setattr(model.geo_service, "calculate_distance", lambda h, a: 100.0)
    monkeypatch.setattr(model, "_calculate_shooting_regression", lambda t, as_of_date=None: 0.0)
    monkeypatch.setattr(model, "_calculate_situational_spots", lambda t, ev: 0.0)
    monkeypatch.setattr(model, "_calculate_fatigue_penalty", lambda t, eid, gd: 0.0)
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot, avg_ftr=None: tot)
    monkeypatch.setattr(model, "_get_archetype_stats", lambda key: {"n": 80, "mean": 0.02, "sd": 0.90})

    snapshot = {
        "spread_home": -4.5,
        "spread_price_home": -110,
        "total": 137.0,
        "total_over_price": -110,
        "book_spread": "DraftKings",
        "book_total": "DraftKings",
        "_best_spread_home": {"line_value": -4.5, "price": -110, "captured_at": datetime.now(timezone.utc), "book": "DraftKings"},
        "_best_spread_away": {"line_value": 4.5, "price": -110, "captured_at": datetime.now(timezone.utc), "book": "DraftKings"},
        "_best_total_over": {"line_value": 137.0, "price": -110, "captured_at": datetime.now(timezone.utc), "book": "DraftKings"},
        "_best_total_under": {"line_value": 137.0, "price": -110, "captured_at": datetime.now(timezone.utc), "book": "DraftKings"},
    }
    res = model.analyze(
        "action:ncaam:999999",
        market_snapshot=snapshot,
        event_context=ev_ctx,
        persist=False,
    )
    ctx = res["context"]
    assert ctx["conviction_sources"] == 3
    assert ctx["efficiency_weight"] == pytest.approx(0.354, abs=0.002)
    assert ctx["fair_spread_home"] == pytest.approx(-5.6, abs=0.05)
    assert ctx["fair_total"] > 138.0
    assert ctx["closest_lean"] is not None

    # Verify /api/jobs/build_daily_top_picks cleanly unpacks (event_id, day_et) tuples
    import src.scripts.build_daily_top_picks as bdtp
    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")
    monkeypatch.setattr(bdtp, "ensure_table", lambda: None)
    monkeypatch.setattr(
        bdtp,
        "fetch_event_ids_for_date",
        lambda date, limit_games=250, days=1: [("action:ncaam:111", "2026-11-13")],
    )
    analyzed_ids = []
    upserted = []
    monkeypatch.setattr(
        NCAAMMarketFirstModelV2,
        "analyze",
        lambda self, eid, **kw: analyzed_ids.append(eid) or {"recommendations": [], "block_reason": "Pass", "model_version": self.VERSION},
    )
    monkeypatch.setattr(bdtp, "upsert_pick", lambda d, eid, r, conn=None: upserted.append((d, eid)))

    mock_conn = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_conn
    with patch("src.database.get_db_connection", return_value=mock_ctx):
        client = TestClient(api_mod.app)
        r_job = client.post(
            "/api/jobs/build_daily_top_picks?date=2026-11-13&days=1&offset=0&max_events=10",
            headers={"X-BASEMENT-KEY": "test-secret"},
        )
    assert r_job.status_code == 200
    assert r_job.json()["ok"] == 1
    assert analyzed_ids == ["action:ncaam:111"]
    assert upserted == [("2026-11-13", "action:ncaam:111")]


def test_blowout_spread_sigma_scaling_projected_score_and_rec_normalization(monkeypatch):
    from datetime import date
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
    import src.api as api_mod

    model = NCAAMMarketFirstModelV2()
    monkeypatch.setattr(model, "_get_council_verdict", lambda eid: None)
    ev_ctx = {
        "id": "action:ncaam:888888",
        "home_team": "Florida",
        "away_team": "Merrimack",
        "start_time": "2026-11-13T23:00:00+00:00",
        "neutral_site": False,
    }
    monkeypatch.setattr(
        model.torvik_service,
        "get_projection",
        lambda h, a, date=None, neutral_site=False: {
            "margin": 31.0,  # Blowout mismatch where raw linear margin differs from -37.5 book
            "total": 146.5,
            "projected_score": "58-89",
            "lean": "Away",
        },
    )
    monkeypatch.setattr(
        model.torvik_service,
        "get_matchup_team_stats",
        lambda h, a, date=None: {
            "home": {"continuity": 0.72, "luck": 0.0, "record": "3-0", "adj_off": 122.0, "adj_def": 94.0},
            "away": {"continuity": 0.72, "luck": 0.0, "record": "3-0", "adj_off": 99.0, "adj_def": 112.0},
            "game_tempo": 69.0,
        },
    )
    monkeypatch.setattr(model.kenpom_client, "calculate_kenpom_adjustment", lambda h, a, neutral_site=False: None)
    monkeypatch.setattr(model.kenpom_client, "get_player_stats_for_team", lambda t, limit=50: [])
    monkeypatch.setattr(model.kenpom_client, "get_team_player_agg", lambda t: None)
    monkeypatch.setattr(model.kenpom_client, "get_team_rating", lambda t: None)
    monkeypatch.setattr(model.kenpom_client, "get_home_court", lambda t: None)
    monkeypatch.setattr(
        model.haslametrics_client,
        "calculate_projection",
        lambda h, a, neutral_site=False, asof_date=None: {"available": False},
    )
    monkeypatch.setattr(model.geo_service, "get_altitude_adjustment", lambda h, neutral_site=False: 0.0)
    monkeypatch.setattr(model.geo_service, "calculate_distance", lambda h, a: 100.0)
    monkeypatch.setattr(model, "_calculate_shooting_regression", lambda t, as_of_date=None: 0.0)
    monkeypatch.setattr(model, "_calculate_situational_spots", lambda t, ev: 0.0)
    monkeypatch.setattr(model, "_calculate_fatigue_penalty", lambda t, eid, gd: 0.0)
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot, avg_ftr=None: tot)
    monkeypatch.setattr(model, "_get_archetype_stats", lambda key: {"n": 80, "mean": 0.0, "sd": 0.90})

    snapshot = {
        "spread_home": -37.5,
        "spread_price_home": -110,
        "total": 146.5,
        "total_over_price": -110,
        "book_spread": "DraftKings",
        "book_total": "DraftKings",
        "_best_spread_home": {"line_value": -37.5, "price": -110, "captured_at": datetime.now(timezone.utc), "book": "DraftKings"},
        "_best_spread_away": {"line_value": 37.5, "price": -110, "captured_at": datetime.now(timezone.utc), "book": "DraftKings"},
        "_best_total_over": {"line_value": 146.5, "price": -110, "captured_at": datetime.now(timezone.utc), "book": "DraftKings"},
        "_best_total_under": {"line_value": 146.5, "price": -110, "captured_at": datetime.now(timezone.utc), "book": "DraftKings"},
    }
    res = model.analyze(
        "action:ncaam:888888",
        market_snapshot=snapshot,
        event_context=ev_ctx,
        persist=False,
    )
    ctx = res["context"]
    assert ctx["blowout_sigma_add"] > 2.5
    assert ctx["sigma_spread"] > 13.0
    assert abs(ctx["fair_spread_home"] - (-37.5)) <= 2.9
    assert ctx["projected_home_score"] > ctx["projected_away_score"]
    assert "Florida" in ctx["projected_score"] and "Merrimack" in ctx["projected_score"]

    # Verify upsert_pick normalizes string edge/confidence fields for storage
    import json
    mock_conn = MagicMock()
    with patch("src.scripts.build_daily_top_picks._exec") as mock_exec:
        upsert_pick(
            "2026-11-13",
            "evt_norm_1",
            {
                "model_version": "ncaam_market_first_v2",
                "recommendations": [
                    {
                        "bet_type": "SPREAD",
                        "selection": "Merrimack +37.5",
                        "edge": "4.2%",
                        "confidence": "MEDIUM",
                        "market_line": 37.5,
                        "fair_line": 35.1,
                        "price": -110,
                    }
                ],
            },
            conn=mock_conn,
        )
    stored_rec = json.loads(mock_exec.call_args[0][2]["rec"])
    assert stored_rec["ev"] == pytest.approx(0.042, abs=1e-5)
    assert stored_rec["ev_pct"] == pytest.approx(4.2, abs=1e-2)
    assert stored_rec["confidence_tier"] == "MEDIUM"
    assert stored_rec["confidence_0_100"] == 62

    # Verify live scoreboard enrichment matches ESPN variants to Action Network team names
    fake_sb = [
        {
            "espn_id": "401800001",
            "home_variants": {"floridagators", "florida"},
            "away_variants": {"merrimackwarriors", "merrimack"},
            "live_status": "IN_PROGRESS",
            "final": False,
            "home_score": 48,
            "away_score": 29,
            "period": 2,
            "clock": "12:14",
            "status_detail": "12:14 - 2nd",
        }
    ]
    board_items = [
        {
            "id": "action:ncaam:888888",
            "home_team": "Florida",
            "away_team": "Merrimack",
            "home_score": None,
            "away_score": None,
            "final": False,
            "status": "SCHEDULED",
        }
    ]
    with patch.object(api_mod, "_fetch_espn_live_scoreboard_date", return_value=fake_sb):
        api_mod._enrich_ncaam_board_with_live_scores(board_items, date(2026, 11, 13), date(2026, 11, 13))

    assert board_items[0]["live_status"] == "IN_PROGRESS"
    assert board_items[0]["status_detail"] == "12:14 - 2nd"
    assert board_items[0]["home_score"] == 48
    assert board_items[0]["away_score"] == 29


def test_calibrated_version_line_sync_and_adjustments_context(monkeypatch):
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2

    assert NCAAMMarketFirstModelV2.VERSION == "2.4.4-over-homefav-guard"
    model = NCAAMMarketFirstModelV2()
    monkeypatch.setattr(model, "_get_council_verdict", lambda eid: None)
    ev_ctx = {
        "id": "action:ncaam:777777",
        "home_team": "Duke",
        "away_team": "North Carolina",
        "start_time": "2026-11-13T23:00:00+00:00",
        "neutral_site": False,
    }
    monkeypatch.setattr(
        model.torvik_service,
        "get_projection",
        lambda h, a, date=None, neutral_site=False: {
            "margin": 4.5,
            "total": 152.5,
            "projected_score": "74-78",
            "lean": "Home",
        },
    )
    monkeypatch.setattr(
        model.torvik_service,
        "get_matchup_team_stats",
        lambda h, a, date=None: {
            "home": {"continuity": 0.72, "luck": 0.0, "record": "3-0", "adj_off": 116.0, "adj_def": 96.0},
            "away": {"continuity": 0.72, "luck": 0.0, "record": "3-0", "adj_off": 114.0, "adj_def": 98.0},
            "game_tempo": 71.0,
        },
    )
    monkeypatch.setattr(model.kenpom_client, "calculate_kenpom_adjustment", lambda h, a, neutral_site=False: None)
    monkeypatch.setattr(model.kenpom_client, "get_player_stats_for_team", lambda t, limit=50: [])
    monkeypatch.setattr(model.kenpom_client, "get_team_player_agg", lambda t: None)
    monkeypatch.setattr(model.kenpom_client, "get_team_rating", lambda t: None)
    monkeypatch.setattr(model.kenpom_client, "get_home_court", lambda t: None)
    monkeypatch.setattr(
        model.haslametrics_client,
        "calculate_projection",
        lambda h, a, neutral_site=False, asof_date=None: {
            "available": True,
            "margin": 5.0,
            "total": 153.0,
            "projected_score": "74-79",
            "home": {"sos": 25, "mom": 0.08, "inc": 0.05},
            "away": {"sos": 60, "mom": -0.02, "inc": 0.05},
        },
    )
    monkeypatch.setattr(model.geo_service, "get_altitude_adjustment", lambda h, neutral_site=False: 0.0)
    monkeypatch.setattr(model.geo_service, "calculate_distance", lambda h, a: 15.0)
    monkeypatch.setattr(model, "_calculate_shooting_regression", lambda t, as_of_date=None: 0.3 if t == "Duke" else 0.0)
    monkeypatch.setattr(model, "_calculate_situational_spots", lambda t, ev: -0.2 if t == "Duke" else 0.0)
    monkeypatch.setattr(model, "_calculate_fatigue_penalty", lambda t, eid, gd: 0.4 if t == "Duke" else 0.0)
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot, avg_ftr=None: tot)
    monkeypatch.setattr(model, "_get_archetype_stats", lambda key: {"n": 80, "mean": 0.0, "sd": 0.90})

    # Consensus total is 142.5, while best Over book offers 143.5 — selection & market_line must both reflect 143.5
    snapshot = {
        "spread_home": -4.5,
        "spread_price_home": -110,
        "total": 142.5,
        "total_over_price": -110,
        "book_spread": "DraftKings",
        "book_total": "DraftKings",
        "_best_spread_home": {"line_value": -4.5, "price": -110, "captured_at": datetime.now(timezone.utc), "book": "DraftKings"},
        "_best_spread_away": {"line_value": 4.5, "price": -110, "captured_at": datetime.now(timezone.utc), "book": "DraftKings"},
        "_best_total_over": {"line_value": 143.5, "price": -105, "captured_at": datetime.now(timezone.utc), "book": "FanDuel"},
        "_best_total_under": {"line_value": 142.5, "price": -115, "captured_at": datetime.now(timezone.utc), "book": "DraftKings"},
    }
    res = model.analyze(
        "action:ncaam:777777",
        market_snapshot=snapshot,
        event_context=ev_ctx,
        relax_gates=True,
        persist=False,
    )
    total_recs = [r for r in res["recommendations"] if r["bet_type"] == "TOTAL"]
    assert total_recs, "Expected TOTAL recommendation under relax_gates=True"
    t_rec = total_recs[0]
    assert t_rec["selection"] == "OVER 143.5"
    assert t_rec["market_line"] == pytest.approx(143.5)
    assert t_rec["edge_points"] == pytest.approx(round(float(t_rec["fair_line"]) - 143.5, 1))
    assert t_rec["confidence_tier"] in ("HIGH", "MEDIUM", "LOW")
    assert 15 <= int(t_rec["confidence_0_100"]) <= 95

    adj = res["signals"]["adjustments"]
    for key in (
        "sos_adj",
        "mom_adj",
        "fatigue_adj",
        "spot_adj",
        "shooting_adj",
        "blowout_sigma_add",
        "conviction_sources",
        "conviction_sources_total",
        "efficiency_weight",
    ):
        assert key in adj
    assert adj["fatigue_adj"] == pytest.approx(0.19, abs=0.05)
    assert adj["spot_adj"] == pytest.approx(-0.1, abs=0.15)
    assert adj["shooting_adj"] == pytest.approx(0.15, abs=0.2)
    assert res["context"]["fatigue_adj"] == pytest.approx(0.19, abs=0.05)
    assert "w_base" in res["context"] and "w_hasla" in res["context"]


def test_parse_kenpom_full_page_cmd_a_copy():
    from src.scripts.ingest_kenpom import parse_kenpom_csv_text

    # Simulate Chrome Cmd+A -> Cmd+C on kenpom.com with ~15 header nav lines before the table
    nav_preamble = "\n".join(
        [
            "KENPOM.COM",
            "Ratings   FanMatch   Blog   Misc",
            "Contact   Subscribe",
            "Logged in as user@example.com",
            "2027 Pomeroy College Basketball Ratings",
            "Data through games of Friday, November 13",
            "View: Teams | Conferences",
            "Strength of Schedule\t\t\t\tNCSOS",
        ]
    )
    table = "\n".join(
        [
            "Rk\tTeam\tConf\tW-L\tNetRtg\tORtg\t\tDRtg\t\tAdjT\t\tLuck\t\tNetRtg\t",
            "1\tDuke\tACC\t3-0\t+31.4\t124.2\t3\t92.8\t2\t68.9\t110\t+.021\t150\t+5.4\t40",
            "2\tHouston\tB12\t3-0\t+29.8\t120.1\t8\t90.3\t1\t64.2\t310\t-.010\t220\t+6.1\t28",
        ]
    )
    rows = parse_kenpom_csv_text(nav_preamble + "\n" + table)
    assert len(rows) == 2
    assert rows[0]["team_name"] == "Duke"
    assert rows[0]["adj_em"] == pytest.approx(31.4)
    assert rows[0]["adj_o"] == pytest.approx(124.2)
    assert rows[0]["adj_d"] == pytest.approx(92.8)
    assert rows[1]["team_name"] == "Houston"


def test_parse_kenpom_all_supplemental_datasets_and_bundle_ingest(monkeypatch):
    import json
    import src.scripts.ingest_kenpom as ik
    import src.scripts.update_data_health as udh

    ratings_rows = [
        "Rk\tTeam\tConf\tW-L\tNetRtg\tORtg\t\tDRtg\t\tAdjT\t\tLuck\t\tNetRtg\t\tORtg\t\tDRtg\t\tNetRtg",
        *[
            f"{i}\tTeam{i}\tACC\t3-0\t{25.0 - i}\t118.0\t{i}\t95.0\t{i}\t68.5\t{i}\t+.010\t50\t+4.0\t30\t108.0\t40\t104.0\t35\t+3.0\t45"
            for i in range(1, 13)
        ],
    ]
    ratings_tsv = "\n".join(ratings_rows)

    stats_html = """
    <html><body><table><thead>
      <tr><th>Team</th><th>Conf</th><th>AdjT</th><th>AdjO</th><th>eFG%</th><th>TO%</th><th>OR%</th><th>FTRate</th><th>AdjD</th><th>eFG%</th><th>TO%</th><th>OR%</th><th>FTRate</th></tr>
    </thead><tbody>
      <tr><td>Team1</td><td>ACC</td><td>68.5</td><td>40</td><td>118.0</td><td>5</td><td>57.2</td><td>8</td><td>14.5</td><td>22</td><td>34.8</td><td>15</td><td>36.0</td><td>28</td><td>95.0</td><td>6</td><td>45.1</td><td>9</td><td>21.2</td><td>18</td><td>24.0</td><td>14</td><td>26.5</td><td>19</td></tr>
      <tr><td>Team2</td><td>ACC</td><td>66.0</td><td>180</td><td>111.0</td><td>45</td><td>50.1</td><td>120</td><td>18.9</td><td>195</td><td>27.5</td><td>210</td><td>29.0</td><td>190</td><td>101.0</td><td>80</td><td>51.2</td><td>190</td><td>16.4</td><td>240</td><td>31.0</td><td>230</td><td>34.0</td><td>200</td></tr>
    </tbody></table></body></html>
    """
    ff_rows = ik.parse_kenpom_four_factors_text(stats_html)
    assert len(ff_rows) == 2
    assert ff_rows[0]["team_name"] == "Team1"
    assert ff_rows[0]["off_efg"] == pytest.approx(57.2)
    assert ff_rows[0]["off_to"] == pytest.approx(14.5)
    assert ff_rows[0]["def_efg"] == pytest.approx(45.1)
    assert ff_rows[0]["def_ftr"] == pytest.approx(26.5)
    assert ff_rows[1]["team_name"] == "Team2"
    assert ik._clean_kp_team_name("Gonzaga 1*") == "Gonzaga"

    height_tsv = "\n".join(
        [
            "Team\tConf\tAvgHgt\tEffHgt\tExp\tBench\tContinuity",
            "Team1\tACC\t77.8\t+1.6\t2.25\t34.5\t62.0",
            "Team2\tACC\t75.4\t-0.9\t1.05\t28.1\t31.5",
        ]
    )
    hgt_rows = ik.parse_kenpom_height_text(height_tsv)
    assert len(hgt_rows) == 2
    assert hgt_rows[0]["eff_hgt"] == pytest.approx(1.6)
    assert hgt_rows[0]["experience"] == pytest.approx(2.25)
    assert hgt_rows[0]["continuity"] == pytest.approx(62.0)

    hca_tsv = "\n".join(
        [
            "Rk\tTeam\tConf\tHCA",
            "1\tTeam1\tACC\t+4.4",
            "2\tTeam2\tACC\t+3.1",
        ]
    )
    hca_rows = ik.parse_kenpom_hca_text(hca_tsv)
    assert len(hca_rows) == 2
    assert hca_rows[0]["team_name"] == "Team1"
    assert hca_rows[0]["hca"] == pytest.approx(4.4)

    players_tsv = "\n".join(
        [
            "Rk\tPlayer\tTeam\tConf\tMin%\tORtg\t%Poss\teFG%\tTS%\tOR%\tDR%\tARate\tTO%\tFTRate",
            "1\tCooper Star\tTeam1\tACC\t78.4\t126.5\t26.2\t60.1\t64.0\t8.5\t17.2\t22.0\t12.5\t42.0",
        ]
    )
    p_rows = ik.parse_kenpom_player_stats_text(players_tsv)
    assert len(p_rows) == 1
    assert p_rows[0]["player_name"] == "Cooper Star"
    assert p_rows[0]["team_name"] == "Team1"
    norm_p = ik.normalize_player_rows(p_rows)
    assert norm_p[0]["usage"] == pytest.approx(26.2)
    assert norm_p[0]["ortg"] == pytest.approx(126.5)

    refs_tsv = "\n".join(
        [
            "Rk\tOfficial\tRtg\tGames\tPF/40\tHome%",
            "1\tRoger Ayers\t98.5\t12\t38.2\t64.1",
        ]
    )
    ref_rows = ik.parse_kenpom_refs_text(refs_tsv)
    assert len(ref_rows) == 1
    assert ref_rows[0]["ref_name"] == "Roger Ayers"

    fanmatch_tsv = "\n".join(
        [
            "Time (ET)\tGame\tLocation\tThrill\tPrediction",
            "7:00 PM\t12 Team2 at 4 Team1\tDurham, NC\t74.2\tTeam1 79-72 (76%)",
        ]
    )
    fm_rows = ik.parse_kenpom_fanmatch_text(fanmatch_tsv)
    assert len(fm_rows) == 1
    assert fm_rows[0]["home_team"] == "Team1"
    assert fm_rows[0]["away_team"] == "Team2"
    assert fm_rows[0]["pred_winner"] == "Team1"
    assert fm_rows[0]["winner_score"] == pytest.approx(79.0)
    assert fm_rows[0]["loser_score"] == pytest.approx(72.0)
    assert fm_rows[0]["win_prob"] == pytest.approx(76.0)
    assert fm_rows[0]["thrill_score"] == pytest.approx(74.2)

    recorded_tables = {}
    monkeypatch.setattr(ik, "ensure_tables", lambda: None)

    def _fake_upsert(table, asof, rows, keys):
        recorded_tables[table] = rows
        return len(rows)

    monkeypatch.setattr(ik, "upsert_daily", _fake_upsert)
    monkeypatch.setattr(udh, "upsert", lambda *a, **kw: None)

    bundle_json = json.dumps(
        {
            "_kp_bundle": 1,
            "ratings": ratings_tsv,
            "stats": stats_html,
            "height": height_tsv,
            "hca": hca_tsv,
            "playerstats": players_tsv,
            "refs": refs_tsv,
            "fanmatch": fanmatch_tsv,
        }
    )
    res = ik.ingest_kenpom_csv(bundle_json, asof_date="2026-11-13")
    assert res["status"] == "ok"
    assert res["rows"] == 12
    assert res["datasets_synced"] == {
        "ratings": 12,
        "four_factors": 2,
        "height_experience": 2,
        "home_court": 2,
        "player_stats": 1,
        "ref_ratings": 1,
        "fanmatch_games": 1,
    }
    team1_saved = next(r for r in recorded_tables["kenpom_team_ratings_daily"] if r["team_name"] == "Team1")
    assert team1_saved["raw"]["off_efg"] == pytest.approx(57.2)
    assert team1_saved["raw"]["experience"] == pytest.approx(2.25)
    assert team1_saved["raw"]["continuity"] == pytest.approx(62.0)
    assert "kenpom_fanmatch_daily" in recorded_tables


def test_kenpom_four_factors_and_experience_flow_into_model_v2(monkeypatch):
    from datetime import date
    from src.services.kenpom_client import KenPomClient

    kp = KenPomClient.__new__(KenPomClient)
    kp.get_team_rating = lambda name, conn=None: (
        {
            "team": "Team1",
            "rank": 5,
            "adj_em": 24.0,
            "adj_o": 119.0,
            "adj_d": 95.0,
            "adj_t": 68.0,
            "luck": 0.0,
            "sos_adj_em": 4.0,
            "ncsos_adj_em": 3.0,
            "off_efg": 57.0,
            "off_to": 14.0,
            "off_or": 35.0,
            "off_ftr": 36.0,
            "def_efg": 45.0,
            "def_to": 21.0,
            "def_or": 24.0,
            "def_ftr": 27.0,
            "experience": 2.3,
            "eff_hgt": 1.6,
            "continuity": 64.0,
        }
        if name == "Team1"
        else {
            "team": "Team2",
            "rank": 40,
            "adj_em": 14.0,
            "adj_o": 111.0,
            "adj_d": 97.0,
            "adj_t": 68.0,
            "luck": 0.0,
            "sos_adj_em": 1.0,
            "ncsos_adj_em": 0.5,
            "off_efg": 50.0,
            "off_to": 19.0,
            "off_or": 28.0,
            "off_ftr": 29.0,
            "def_efg": 51.0,
            "def_to": 16.0,
            "def_or": 31.0,
            "def_ftr": 34.0,
            "experience": 1.0,
            "eff_hgt": -0.8,
            "continuity": 32.0,
        }
    )
    adj = kp.calculate_kenpom_adjustment("Team1", "Team2", neutral_site=False)
    assert adj["four_factors_adj"] > 0.5
    assert adj["exp_height_adj"] > 0.3
    assert adj["home_continuity"] == pytest.approx(64.0)
    assert adj["away_continuity"] == pytest.approx(32.0)

    model = NCAAMMarketFirstModelV2()
    model.torvik_service = MagicMock()
    model.torvik_service.get_projection.return_value = {
        "margin": 8.0,
        "official_margin": 8.0,
        "total": 146.0,
        "projected_score": "69-77",
        "lean": "Home",
    }
    model.torvik_service.get_matchup_team_stats.return_value = {
        "game_tempo": 68.0,
        "home": {"luck": 0.0, "record": "12-2"},
        "away": {"luck": 0.0, "record": "10-4"},
    }
    model.kenpom_client = kp
    kp.get_home_court = lambda name, conn=None: {"team": name, "hca": 4.2}
    kp.get_team_player_agg = lambda name, conn=None: None
    kp.get_player_stats_for_team = lambda name, limit=50, conn=None: []
    model.haslametrics_client = None
    model.geo_service = MagicMock()
    model.geo_service.get_altitude_adjustment.return_value = 0.0
    model.geo_service.calculate_distance.return_value = 150.0
    model.news_service = MagicMock()
    model.news_service.fetch_game_context.return_value = {}
    model.injury_service = MagicMock()
    model.injury_service.get_matchup_injuries.return_value = {
        "has_injuries": False,
        "injuries": [],
        "sigma_mult": 1.0,
        "spread_adj": 0.0,
        "total_adj": 0.0,
    }
    monkeypatch.setattr(model, "_calculate_shooting_regression", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_situational_spots", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_fatigue_penalty", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot, avg_ftr=None: tot)

    event_ctx = {
        "id": "ev-kp-style-1",
        "home_team": "Team1",
        "away_team": "Team2",
        "start_time": f"{date.today().isoformat()}T19:00:00+00:00",
        "neutral_site": False,
    }
    snap = {"spread_home": -6.5, "total": 146.0}
    res = model.analyze("ev-kp-style-1", market_snapshot=snap, event_context=event_ctx, persist=False)
    sig_adj = res["signals"]["adjustments"]
    assert sig_adj["kp_style_adj"] > 0.5
    assert sig_adj["kp_hca"] == pytest.approx(0.5, abs=0.05)
    assert res["context"]["kp_style_adj"] > 0.5


def test_mac_kenpom_daily_sync_builds_7_dataset_bundle(monkeypatch):
    import sys
    from pathlib import Path
    scripts_dir = str(Path(__file__).resolve().parents[2] / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import mac_kenpom_daily_sync as mk

    sample_pages = {
        "/": "<html><body><table id='ratings-table'><thead><tr><th>Rk</th><th>Team</th><th>Conf</th><th>W-L</th><th>NetRtg</th></tr></thead><tbody>"
             + "".join(f"<tr><td>{i}</td><td>Team{i}</td><td>ACC</td><td>3-0</td><td>{20-i}</td></tr>" for i in range(1, 13))
             + "</tbody></table></body></html>",
        "/stats.php": "<html><body><table><thead><tr><th>Team</th><th>eFG%</th></tr></thead><tbody><tr><td>Team1</td><td>56.0</td></tr></tbody></table></body></html>",
        "/height.php": "<html><body><table><thead><tr><th>Team</th><th>Continuity</th></tr></thead><tbody><tr><td>Team1</td><td>61.2</td></tr></tbody></table></body></html>",
        "/hca.php": "<html><body><table><thead><tr><th>Team</th><th>HCA</th></tr></thead><tbody><tr><td>Team1</td><td>4.1</td></tr></tbody></table></body></html>",
        "/playerstats.php?s=ORtg": "<html><body><table><thead><tr><th>Player</th><th>Team</th><th>ORtg</th></tr></thead><tbody><tr><td>Star Player</td><td>Team1</td><td>125.0</td></tr></tbody></table></body></html>",
        "/officials.php": "<html><body><table><thead><tr><th>Official</th><th>PF/40</th></tr></thead><tbody><tr><td>Ref One</td><td>37.5</td></tr></tbody></table></body></html>",
        "/fanmatch.php": "<html><body><table><thead><tr><th>Game</th><th>Prediction</th></tr></thead><tbody><tr><td>Team2 at Team1</td><td>Team1 78-70 (74%)</td></tr></tbody></table></body></html>",
    }

    monkeypatch.setattr(mk, "fetch_html", lambda sess, path: sample_pages[path])
    bundle = mk.build_kenpom_bundle_from_session(object(), sleep_s=0.0)
    assert bundle["_kp_bundle"] == 1
    for key in ("ratings", "stats", "height", "hca", "playerstats", "refs", "fanmatch"):
        assert key in bundle and len(bundle[key]) > 0


def test_compute_live_game_pace_and_board_enrichment(monkeypatch):
    import src.api as api_mod
    from datetime import date

    # 1. 1st half fast pace (10 mins elapsed out of 40)
    p1 = api_mod._compute_live_game_pace(
        home_score=24,
        away_score=18,
        live_status="IN_PROGRESS",
        period=1,
        clock="10:00",
        status_detail="10:00 - 1st Half",
        total_line=144.0,
        home_spread=-6.0,
    )
    assert p1["elapsed_minutes"] == pytest.approx(10.0, abs=0.05)
    assert p1["remaining_minutes"] == pytest.approx(30.0, abs=0.05)
    assert p1["progress_pct"] == 25
    assert p1["period_label"] == "1st · 10:00"
    assert p1["points_per_minute"] == pytest.approx(4.2, abs=0.05)
    assert p1["projected_total"] > 144.0
    assert p1["projected_home_score"] > p1["projected_away_score"]

    # 2. Halftime
    p_ht = api_mod._compute_live_game_pace(
        home_score=41,
        away_score=39,
        live_status="HALFTIME",
        period=1,
        clock="0:00",
        status_detail="Halftime",
        total_line=145.5,
        home_spread=-4.5,
    )
    assert p_ht["elapsed_minutes"] == 20.0
    assert p_ht["remaining_minutes"] == 20.0
    assert p_ht["progress_pct"] == 50
    assert p_ht["period_label"] == "Halftime"
    assert p_ht["projected_total"] > 150.0  # 80 pts at half projects >145.5

    # 3. 2nd half (5 mins left, elapsed = 35m)
    p2 = api_mod._compute_live_game_pace(
        home_score=65,
        away_score=60,
        live_status="IN_PROGRESS",
        period=2,
        clock="5:00",
        status_detail="5:00 - 2nd Half",
        total_line=140.0,
        home_spread=-8.5,
    )
    assert p2["elapsed_minutes"] == pytest.approx(35.0, abs=0.05)
    assert p2["remaining_minutes"] == pytest.approx(5.0, abs=0.05)
    assert p2["progress_pct"] == 88
    assert p2["projected_total"] >= 125.0

    # 4. Overtime (period 3, 2:00 remaining in 5-min OT => 43 elapsed, 45 total)
    pot = api_mod._compute_live_game_pace(
        home_score=76,
        away_score=74,
        live_status="IN_PROGRESS",
        period=3,
        clock="2:00",
        status_detail="2:00 - OT",
        total_line=144.0,
        home_spread=-2.5,
    )
    assert pot["total_game_minutes"] == 45.0
    assert pot["elapsed_minutes"] == pytest.approx(43.0, abs=0.05)
    assert pot["remaining_minutes"] == pytest.approx(2.0, abs=0.05)
    assert pot["period_label"] == "OT · 2:00"

    # 5. Board enrichment attaches live_trend cleanly
    monkeypatch.setattr(
        api_mod,
        "_fetch_espn_live_scoreboard_date",
        lambda yyyymmdd: [
            {
                "espn_id": "401999",
                "home_variants": {"duke"},
                "away_variants": {"northcarolina"},
                "live_status": "IN_PROGRESS",
                "final": False,
                "home_score": 44,
                "away_score": 40,
                "period": 2,
                "clock": "18:00",
                "status_detail": "18:00 - 2nd Half",
            }
        ],
    )
    items = [
        {
            "id": "espn:ncaam:401999",
            "home_team": "Duke",
            "away_team": "North Carolina",
            "total_line": 149.5,
            "home_spread": -5.5,
        }
    ]
    d = date.today()
    api_mod._enrich_ncaam_board_with_live_scores(items, d, d)
    assert items[0]["live_status"] == "IN_PROGRESS"
    assert items[0]["home_score"] == 44
    assert items[0]["away_score"] == 40
    assert "live_trend" in items[0]
    assert items[0]["live_trend"]["period_label"] == "2nd · 18:00"
    assert items[0]["live_trend"]["projected_total"] > 140.0


def test_model_v2_five_improvements_isolation_calibration_totals_and_signals(monkeypatch):
    from datetime import datetime, timedelta, timezone

    model = NCAAMMarketFirstModelV2()
    assert model._tau_for_market("SPREAD") > 0.0
    assert model._tau_for_market("TOTAL") > 0.0

    # Mock external/DB collaborators cleanly
    model.torvik_service = MagicMock()
    model.kenpom_client = MagicMock()
    model.haslametrics_client = MagicMock()
    model.injury_service = MagicMock()
    model.geo_service = MagicMock()
    model.news_service = MagicMock()

    model.injury_service.get_matchup_injuries.return_value = {"has_injuries": False, "injuries": []}
    model.geo_service.get_altitude_adjustment.return_value = 0.0
    model.geo_service.calculate_distance.return_value = 100.0
    model.news_service.get_team_news.return_value = []
    model.news_service.summarize_impact.return_value = ""
    model.haslametrics_client.calculate_projection.return_value = None
    model.kenpom_client.get_home_court.return_value = None
    model.kenpom_client.get_player_stats_for_team.return_value = []
    model.kenpom_client.get_team_rating.return_value = None

    monkeypatch.setattr(model, "_get_council_verdict", lambda eid: None)
    monkeypatch.setattr(model, "_calculate_shooting_regression", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_situational_spots", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_fatigue_penalty", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot, avg_ftr=None: tot)
    monkeypatch.setattr(model, "_load_winprob_calibration", lambda: {"points": []})

    # 1. W_BASE stays immutable across consecutive calls with different dates
    model.torvik_service.get_projection.return_value = {"margin": 8.0, "total": 158.0, "lean": "Home"}
    model.torvik_service.get_matchup_team_stats.return_value = {
        "game_tempo": 70.0,
        "home": {"luck": 0.0, "continuity": 75.0, "record": "12-4"},
        "away": {"luck": 0.0, "continuity": 75.0, "record": "10-6"},
    }
    model.kenpom_client.calculate_kenpom_adjustment.return_value = {
        "spread_adj": 8.0,
        "neutral_margin": 4.8,
        "fair_margin": 8.0,
        "fair_total": 160.0,
        "total_adj": 0.0,
        "summary": "Home +8.0",
    }
    model.kenpom_client.get_team_player_agg.return_value = {"ortg_w": 112.0}

    nov_ev = {"id": "evt_nov_w", "home_team": "Duke", "away_team": "Siena", "start_time": datetime(2026, 11, 15, 19, 0)}
    feb_ev = {"id": "evt_feb_w", "home_team": "Duke", "away_team": "Siena", "start_time": datetime(2027, 2, 15, 19, 0)}

    res_nov = model.analyze("evt_nov_w", event_context=nov_ev, market_snapshot={"spread_home": -3.5, "total": 152.0}, relax_gates=True, persist=False)
    assert model.W_BASE == pytest.approx(model.DEFAULT_W_BASE)
    assert res_nov["debug"]["w_base"] < 0.20

    feb_snapshot = {"spread_home": -3.5, "total": 152.0, "_best_spread_home": {
        "line_value": -3.5, "price": -110, "book": "DraftKings", "captured_at": datetime.now(timezone.utc)}}
    res_feb = model.analyze("evt_feb_w", event_context=feb_ev, market_snapshot=feb_snapshot, relax_gates=True, persist=False)
    assert model.W_BASE == pytest.approx(model.DEFAULT_W_BASE)
    assert res_feb["debug"]["w_base"] > res_nov["debug"]["w_base"]

    # 2. kp_player_total_adj is suppressed when kp_fair_total already covers KenPom efficiency,
    #    and centered at 106.5 (not 105.0) when kp_fair_total is None.
    assert res_nov["debug"]["kenpom_player_total_adj"] == 0.0
    model.kenpom_client.calculate_kenpom_adjustment.return_value = {
        "spread_adj": 8.0,
        "neutral_margin": 4.8,
        "fair_margin": 8.0,
        "total_adj": 0.0,
        "summary": "Home +8.0",
    }
    model.kenpom_client.get_team_player_agg.return_value = {"ortg_w": 106.5}
    res_centered = model.analyze("evt_center", event_context=feb_ev, market_snapshot={"spread_home": -3.5, "total": 152.0}, relax_gates=True, persist=False)
    assert res_centered["debug"]["kenpom_player_total_adj"] == pytest.approx(0.0, abs=1e-6)

    # 3. Missing market total does NOT inject synthetic 145.0 or crash, and missing Torvik total does NOT fabricate -17 Under diff
    res_no_mkt_tot = model.analyze("evt_no_tot", event_context=feb_ev, market_snapshot={"spread_home": -3.5}, relax_gates=True, persist=False)
    assert res_no_mkt_tot["debug"]["conviction_sources_total"] == 0
    assert res_no_mkt_tot["debug"]["mu_total_final"] > 155.0
    assert all((r.get("bet_type") or r.get("market")) != "TOTAL" for r in res_no_mkt_tot["recommendations"])

    model.torvik_service.get_projection.return_value = {"margin": 3.5, "total": None, "lean": "Home"}
    model.kenpom_client.calculate_kenpom_adjustment.return_value = None
    model.kenpom_client.get_team_player_agg.return_value = None
    res_neither_tot = model.analyze("evt_no_any_tot", event_context=feb_ev, market_snapshot={"spread_home": -3.5}, relax_gates=True, persist=False)
    assert res_neither_tot["debug"]["mu_total_final"] is None

    res_no_proj_tot = model.analyze("evt_no_tv_tot", event_context=feb_ev, market_snapshot={"spread_home": -3.5, "total": 162.0}, relax_gates=True, persist=False)
    assert res_no_proj_tot["signals"]["torvik"]["fair_total"] is None
    assert res_no_proj_tot["debug"]["mu_total_final"] == pytest.approx(162.0, abs=0.5)
    assert res_no_proj_tot["debug"]["conviction_sources_total"] == 0

    # Continuous luck scaling: mild +0.04 luck applies proportional regression rather than zeroing out under a 0.05 cliff
    model.torvik_service.get_projection.return_value = {"margin": 3.5, "total": 152.0, "lean": "Home"}
    model.torvik_service.get_matchup_team_stats.return_value = {
        "game_tempo": 70.0,
        "home": {"luck": 0.04, "continuity": 75.0, "record": "12-4"},
        "away": {"luck": 0.0, "continuity": 75.0, "record": "12-4"},
    }
    res_luck = model.analyze("evt_luck", event_context=feb_ev, market_snapshot={"spread_home": -3.5, "total": 152.0}, relax_gates=True, persist=False)
    assert abs(res_luck["debug"]["mu_spread_final"] - (-3.5)) > 0.25

    # 4. mu-uncertainty bounds populate win_prob_lb10 < win_prob on edge picks
    assert res_feb["recommendations"]
    for rec in res_feb["recommendations"]:
        if rec.get("win_prob_lb10") is not None:
            assert rec["win_prob_lb10"] <= rec["win_prob"]

    # 5. Smooth shooting curve, lookahead Top-25 penalty, and probability-aligned split gates
    m_real = NCAAMMarketFirstModelV2()
    monkeypatch.setattr("src.database.get_team_recent_shooting", lambda team, num_games=3, as_of_date=None: {"games_played": 8, "delta": 0.03})
    assert m_real._calculate_shooting_regression("Duke") == pytest.approx(-0.35, abs=1e-4)
    monkeypatch.setattr("src.database.get_team_recent_shooting", lambda team, num_games=3, as_of_date=None: {"games_played": 8, "delta": 0.04})
    assert m_real._calculate_shooting_regression("Duke") == pytest.approx(-0.70, abs=1e-4)

    # Top-25 lookahead within 4 days applies -0.75 penalty
    class _FakeCur:
        def __init__(self, row):
            self._row = row
        def fetchone(self):
            return self._row
    class _FakeConn:
        def __init__(self, row):
            self._row = row
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    m_real.kenpom_client = MagicMock()
    m_real.kenpom_client.get_team_rating.return_value = {"rank": 8}
    monkeypatch.setenv("REQUIRE_DATABASE", "1")
    monkeypatch.setattr("src.database.get_team_last_game", lambda *a, **kw: None)
    monkeypatch.setattr("src.database.get_db_connection", lambda: _FakeConn({"home_team": "Duke", "away_team": "Kansas", "start_time": datetime.now(timezone.utc) + timedelta(days=2)}))
    monkeypatch.setattr("src.database._exec", lambda conn, q, p=None: _FakeCur({"home_team": "Duke", "away_team": "Kansas", "start_time": datetime.now(timezone.utc) + timedelta(days=2)}))
    assert m_real._calculate_situational_spots("Duke", {"start_time": datetime.now(timezone.utc), "home_team": "Duke", "away_team": "Siena"}) == pytest.approx(-0.75, abs=1e-4)

    # Contra sharp money adjusts win_prob + ev consistently and blocks TOTAL falling under PUBLISH_MIN_EV_TOTAL (0.035)
    full_total_rec = [{"market": "TOTAL", "side": "OVER", "win_prob": 0.544, "win_prob_lb10": 0.51, "price": -110, "ev": 0.0385, "kelly_pct": 0.9, "confidence_0_100": 62, "movement_tags": []}]
    splits_contra = {"TOTAL": {"OVER": {"bet_pct": 75, "handle_pct": 25}, "UNDER": {"bet_pct": 25, "handle_pct": 75}}}
    assert m_real._apply_split_and_injury_signals(full_total_rec, action_splits=splits_contra, injury_context={"has_injuries": False}, relax_gates=False) == []


def test_model_v2_six_edge_and_calibration_improvements(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from src.services.odds_selection_service import OddsSelectionService
    from src.services.haslametrics_client import compute_matchup_projection
    import src.scripts.ingest_kenpom as ik

    # 1. Odds deduplication + target_line selection
    selector = OddsSelectionService()
    snaps = [
        {"book": "DraftKings", "market_type": "TOTAL", "side": "OVER", "line_value": 146.5, "price": -110, "captured_at": "2026-11-15T18:00:00Z"},
        {"book": "DraftKings", "market_type": "TOTAL", "side": "OVER", "line_value": 144.0, "price": 120, "captured_at": "2026-11-15T12:00:00Z"},  # stale
        {"book": "FanDuel", "market_type": "TOTAL", "side": "OVER", "line_value": 146.0, "price": -112, "captured_at": "2026-11-15T18:05:00Z"},
        {"book": "BetMGM", "market_type": "TOTAL", "side": "OVER", "line_value": 149.0, "price": 105, "captured_at": "2026-11-15T18:05:00Z"},  # alt/worse line outside 0.5
    ]
    best_over = selector.get_best_price_for_side(snaps, "TOTAL", "OVER", target_line=146.5)
    assert best_over is not None
    # FanDuel 146.0 beats DK 146.5 on favorable OVER line; BetMGM +105 at 149.0 is ignored
    assert best_over["book"] == "FanDuel"
    assert best_over["line_value"] == 146.0

    # _get_all_recent_odds keeps latest per (book, market_type, side)
    model = NCAAMMarketFirstModelV2()
    fake_rows = [
        {"book": "DraftKings", "market_type": "SPREAD", "side": "HOME", "line_value": -4.5, "price": -110, "captured_at": "2026-11-15T18:00:00Z"},
        {"book": "DraftKings", "market_type": "SPREAD", "side": "HOME", "line_value": -3.0, "price": 105, "captured_at": "2026-11-15T10:00:00Z"},
        {"book": "FanDuel", "market_type": "SPREAD", "side": "HOME", "line_value": -4.5, "price": -108, "captured_at": "2026-11-15T17:55:00Z"},
    ]
    class _OddsCur:
        def fetchall(self):
            return fake_rows
    class _OddsConn:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    monkeypatch.setattr("src.models.ncaam_market_first_model_v2.get_db_connection", lambda: _OddsConn())
    monkeypatch.setattr("src.models.ncaam_market_first_model_v2._exec", lambda c, q, p=None: _OddsCur())
    deduped = model._get_all_recent_odds("evt_1")
    assert len(deduped) == 2
    assert deduped[0]["line_value"] == -4.5

    # 2. tau shrinkage (~0.25), deterministic bounds & lb10 publish gate
    monkeypatch.delenv("NCAAM_MU_TAU_SHRINKAGE", raising=False)
    tau_sp = model._tau_for_market("SPREAD")
    assert 0.4 < tau_sp < 1.0
    b_a = model._confidence_bounds_from_mu_uncertainty("SPREAD", mu=-6.5, sigma=11.0, line=-4.5, side="home")
    b_b = model._confidence_bounds_from_mu_uncertainty("SPREAD", mu=-6.5, sigma=11.0, line=-4.5, side="home")
    assert b_a == b_b  # deterministic analytical quantiles
    assert b_a["lb10"] is not None and b_a["lb10"] < b_a["ub90"]

    model._get_archetype_stats = lambda k: {"n": 80, "mean": 0.03, "sd": 0.10}
    assert model._passes_publish_gates({"market": "SPREAD", "side": "HOME", "ev": 0.05, "edge_points": 2.0, "win_prob_lb10": 0.49}, -4.5, True) is False
    assert model._passes_publish_gates({"market": "SPREAD", "side": "HOME", "ev": 0.05, "edge_points": 2.0, "win_prob_lb10": 0.525}, -4.5, True) is True

    # 3. Plus-money underdogs require at least 4.5 points above implied probability.
    assert model._passes_ml_persist_gates(win_prob=0.48, ev=0.09, price=125) is False
    assert model._passes_ml_persist_gates(win_prob=0.49, ev=0.09, price=125) is True
    assert model._passes_ml_persist_gates(win_prob=0.58, ev=0.06, price=-115) is True

    # 4. TOTAL OVER (+3.8% EV) vs UNDER (+3.5% EV) and Haslametrics 106.5/68.0 defaults
    assert model._passes_publish_gates({"market": "TOTAL", "side": "over", "ev": 0.036, "edge_points": 2.0}, None, True) is False
    assert model._passes_publish_gates({"market": "TOTAL", "side": "under", "ev": 0.036, "edge_points": 2.0}, None, True) is True
    proj_default = compute_matchup_projection({"oe": 106.5, "de": 106.5}, {"oe": 106.5, "de": 106.5}, neutral_site=True)
    assert proj_default is not None
    # Two average D1 teams on neutral court -> 68.0 * 1.065 * 2 = 144.84 (not ~152.5 from inflated 109.7/69.5 defaults)
    assert proj_default["total"] == pytest.approx(144.84, abs=0.2)

    # 5. Nov/Dec early-season cap damping + no duplicate persistence of best_rec
    model.torvik_service = MagicMock()
    model.torvik_service.get_projection.return_value = {"margin": 11.0, "official_margin": 11.0, "total": 152.0, "lean": "Home"}
    model.torvik_service.get_matchup_team_stats.return_value = {"game_tempo": 68.0, "home": {"luck": 0.0, "continuity": 75.0}, "away": {"luck": 0.0, "continuity": 75.0}}
    model.kenpom_client = MagicMock()
    model.kenpom_client.calculate_kenpom_adjustment.return_value = {"spread_adj": 11.0, "fair_margin": 11.0, "fair_total": 154.0, "total_adj": 0.0, "summary": "Home"}
    model.kenpom_client.get_team_player_agg.return_value = None
    model.kenpom_client.get_team_rating.return_value = None
    model.kenpom_client.get_home_court.return_value = None
    model.kenpom_client.get_player_stats_for_team.return_value = []
    model.haslametrics_client = MagicMock()
    model.haslametrics_client.calculate_projection.return_value = {"available": True, "margin": 11.0, "total": 152.0}
    model.geo_service = MagicMock()
    model.geo_service.get_altitude_adjustment.return_value = 0.0
    model.geo_service.calculate_distance.return_value = 100.0
    model.injury_service = MagicMock()
    model.injury_service.get_matchup_injuries.return_value = {"has_injuries": False, "injuries": []}
    model.news_service = MagicMock()
    model.news_service.get_team_news.return_value = []
    model.news_service.summarize_impact.return_value = ""
    monkeypatch.setattr(model, "_get_council_verdict", lambda eid: None)
    monkeypatch.setattr(model, "_calculate_shooting_regression", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_situational_spots", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_fatigue_penalty", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot, avg_ftr=None: tot)
    monkeypatch.setattr(model, "_load_winprob_calibration", lambda: {"points": []})

    persisted_docs = []
    monkeypatch.setattr("src.models.ncaam_market_first_model_v2.insert_model_prediction", lambda doc: persisted_docs.append(doc) or True)
    nov_ev = {"id": "evt_nov_cap", "home_team": "Team A", "away_team": "Team B", "start_time": datetime.now(timezone.utc) + timedelta(hours=3)}
    # Force month=11 for early-season check via explicit November timestamp (>now if 2026-11-15)
    nov_ev["start_time"] = datetime(2026, 11, 20, 19, 0, tzinfo=timezone.utc)
    res_nov = model.analyze(
        "evt_nov_cap",
        event_context=nov_ev,
        market_snapshot={"spread_home": -3.5, "total": 144.0, "moneyline_price_home": -155, "moneyline_price_away": 135},
        persist=True,
    )
    assert abs(res_nov["context"]["fair_spread_home"] - (-3.5)) <= 2.25
    assert abs(res_nov["context"]["fair_total"] - 144.0) <= 3.05
    # Guarantee no duplicate row insertion for best_rec
    spread_rows = [d for d in persisted_docs if d["market_type"] == "SPREAD"]
    assert len(spread_rows) <= 1

    # 6. ingest_kenpom_bundle supports torvik_teams + torvik_game_logs
    captured_tv = {}
    monkeypatch.setattr(ik, "ensure_tables", lambda: None)
    monkeypatch.setattr("src.database.upsert_bt_team_metrics_daily", lambda rows: captured_tv.setdefault("daily", rows))
    monkeypatch.setattr("src.database.upsert_team_metrics", lambda rows: captured_tv.setdefault("live", rows))
    monkeypatch.setattr(ik, "_ingest_game_log_rows", lambda rows: (captured_tv.setdefault("logs", rows), len(rows))[1])
    monkeypatch.setattr("src.scripts.update_data_health.upsert", lambda src_name, status, row_count=0, notes="": captured_tv.setdefault("health", {}) .__setitem__(src_name, (status, row_count)))
    res_tv = ik.ingest_kenpom_bundle(
        {
            "_kp_bundle": 1,
            "torvik_teams": [[1, "Duke", "ACC", "3-0", 125.0, 1, 90.0, 2, 0.97] + [None] * 36],
            "torvik_game_logs": [{"team_text": "Duke", "game_date": "2026-11-14", "opponent": "Kansas", "points": 80, "three_p_made": 9, "three_p_attempted": 24, "three_p_pct": 0.375, "fouls": None, "opponent_rank": None, "is_home": True, "margin": 8}],
        },
        asof_date="2026-11-15",
    )
    assert res_tv["datasets_synced"]["torvik_teams"] == 1
    assert res_tv["datasets_synced"]["torvik_game_logs"] == 1
    assert "adj_de" in captured_tv["live"][0]
    assert captured_tv["health"]["torvik"] == ("ok", 1)


def test_audit_accuracy_fixes_pace_splits_reverse_steam_and_calibration(monkeypatch):
    from datetime import datetime, timezone
    from scripts.build_winprob_calibration_ncaam import Obs, fit_calibration_artifact
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
    from src.services.haslametrics_client import compute_matchup_projection, parse_haslametrics_xml
    from src.services.kenpom_client import KenPomClient
    from src.utils.model_calibration import is_valid_winprob_calibration

    # 1. KenPom & Haslametrics 0.65x damped pace + 106.5/68.0 XML meta fallbacks
    kp = KenPomClient()
    ratings_map = {
        "Team A": {"team": "Team A", "rank": 20, "adj_em": 18.0, "adj_o": 115.0, "adj_d": 97.0, "adj_t": 74.0},
        "Team B": {"team": "Team B", "rank": 35, "adj_em": 12.0, "adj_o": 112.0, "adj_d": 100.0, "adj_t": 72.0},
    }
    monkeypatch.setattr(kp, "get_team_rating", lambda name, conn=None: ratings_map.get(name))
    monkeypatch.setattr(kp, "get_fanmatch_prediction", lambda h, a, conn=None: None)
    kp_adj = kp.calculate_kenpom_adjustment("Team A", "Team B")
    assert kp_adj["expected_tempo"] == pytest.approx(74.5, abs=0.1)

    parsed_no_av = parse_haslametrics_xml(
        '<ratings><dt md="2026-11-16" /><mr rk="1" t="Team A" c="ACC" w="3" l="0" oe="115" de="97" ou="74" du="74" /></ratings>'
    )
    assert parsed_no_av["meta"]["av_eff"] == pytest.approx(106.5, abs=1e-6)
    assert parsed_no_av["meta"]["av_pace"] == pytest.approx(68.0, abs=1e-6)

    hasla_proj = compute_matchup_projection(
        {"oe": 115.0, "de": 97.0, "tempo": 74.0},
        {"oe": 112.0, "de": 100.0, "tempo": 72.0},
        neutral_site=False,
    )
    assert hasla_proj is not None
    assert hasla_proj["game_tempo"] == pytest.approx(74.6, abs=0.1)

    # 2. Mid-blowout (-16.5 spread) receives blowout_sigma_add > 0.4
    model = NCAAMMarketFirstModelV2()
    model.torvik_service = MagicMock()
    model.torvik_service.get_projection.return_value = {"margin": 14.5, "official_margin": 14.5, "total": 144.0, "lean": "Home"}
    model.torvik_service.get_matchup_team_stats.return_value = {
        "game_tempo": 68.0,
        "home": {"luck": 0.0, "continuity": 0.72, "record": "3-0", "adj_off": 114.0, "adj_def": 99.0},
        "away": {"luck": 0.0, "continuity": 0.72, "record": "3-0", "adj_off": 102.0, "adj_def": 106.0},
    }
    model.kenpom_client = MagicMock()
    model.kenpom_client.calculate_kenpom_adjustment.return_value = None
    model.kenpom_client.get_team_player_agg.return_value = None
    model.kenpom_client.get_team_rating.return_value = None
    model.kenpom_client.get_home_court.return_value = None
    model.kenpom_client.get_player_stats_for_team.return_value = []
    model.haslametrics_client = MagicMock()
    model.haslametrics_client.calculate_projection.return_value = {"available": False}
    model.geo_service = MagicMock()
    model.geo_service.get_altitude_adjustment.return_value = 0.0
    model.geo_service.calculate_distance.return_value = 100.0
    model.injury_service = MagicMock()
    model.injury_service.get_matchup_injuries.return_value = {"has_injuries": False, "injuries": []}
    model.news_service = MagicMock()
    model.news_service.fetch_game_context.return_value = {}
    model.news_service.summarize_impact.return_value = ""
    monkeypatch.setattr(model, "_get_council_verdict", lambda eid: None)
    monkeypatch.setattr(model, "_calculate_shooting_regression", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_situational_spots", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_fatigue_penalty", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot, avg_ftr=None: tot)
    monkeypatch.setattr(model, "_load_winprob_calibration", lambda: {"points": []})
    monkeypatch.setattr(model, "_get_archetype_stats", lambda key: {"n": 80, "mean": 0.02, "sd": 0.90})

    res_mid_blowout = model.analyze(
        "evt_mid_blowout",
        event_context={
            "id": "evt_mid_blowout",
            "home_team": "Favorite",
            "away_team": "Dog",
            "start_time": datetime(2026, 11, 16, 20, 0, tzinfo=timezone.utc),
        },
        market_snapshot={"spread_home": -16.5, "total": 144.0},
        persist=False,
    )
    assert res_mid_blowout["context"]["blowout_sigma_add"] > 0.3

    # 3. Strengthened contra_sharp_money drops win_prob & caps High confidence
    contra_out = model._apply_split_and_injury_signals(
        [
            {
                "market": "TOTAL",
                "side": "OVER",
                "win_prob": 0.565,
                "win_prob_lb10": 0.555,
                "price": -110,
                "ev": 0.078,
                "confidence": "High",
                "confidence_tier": "HIGH",
                "confidence_0_100": 82,
                "movement_tags": [],
            }
        ],
        action_splits={
            "TOTAL": {"OVER": {"bet_pct": 72, "handle_pct": 25}, "UNDER": {"bet_pct": 28, "handle_pct": 75}}
        },
        injury_context={"has_injuries": False},
        relax_gates=True,
    )
    assert len(contra_out) == 1
    assert contra_out[0]["win_prob"] <= 0.553
    assert contra_out[0]["win_prob_lb10"] <= 0.548
    assert contra_out[0]["confidence"] == "Medium"
    assert contra_out[0]["confidence_tier"] == "MEDIUM"
    assert contra_out[0]["confidence_0_100"] <= 74

    # 4. Reverse steam inflates sigma_mult and recomputes win_prob & ev at sigma * sigma_mult
    raw_over_wp = round(1.0 - model._normal_cdf(141.0, 145.5, 15.0), 3)
    recs_rev = model._generate_recommendations(
        mu_s=-3.5,
        sig_s=11.0,
        mu_t=145.5,
        sig_t=15.0,
        snap={
            "spread_home": -3.5,
            "total": 141.0,
            "_best_total_over": {"line_value": 141.0, "price": -110, "book": "DraftKings", "captured_at": datetime.now(timezone.utc)},
            "total_over_price": -110,
            "_market_consensus": {
                "open_total": 143.5,
                "current_total": 141.0,
                "total_move": -2.5,
            },
        },
        event={"id": "evt_rev", "home_team": "Home", "away_team": "Away"},
        torvik_view={"lean": "Home"},
        relax_gates=True,
    )
    tot_rec = next(r for r in recs_rev if r["market"] == "TOTAL")
    assert "reverse_steam=-2.5" in (tot_rec.get("movement_tags") or [])
    assert tot_rec["sigma_mult"] > 1.0
    assert tot_rec["win_prob"] < raw_over_wp
    assert tot_rec["ev"] < tot_rec["ev_raw"]

    # 5. Canonical team name matching avoids school-name collisions
    assert model._event_team_matches("Indiana State Sycamores", "Indiana") is False
    assert model._event_team_matches("Southern Indiana Screaming Eagles", "Indiana") is False
    assert model._event_team_matches("Indiana Hoosiers", "Indiana") is True

    # 6. Cold-streak PAVA regularization keeps pregame curve valid (>= 0.525 peak)
    cold_obs = [
        Obs(p=0.45 + (i % 6) * 0.034, y=(1.0 if (i % 9 < 4) else 0.0), w=1.0)
        for i in range(60)
    ]
    cold_art = fit_calibration_artifact(cold_obs, days=30, min_points=10)
    assert is_valid_winprob_calibration(cold_art, min_obs=50, min_max_pcal=0.52) is True
    assert max(pt["p_cal"] for pt in cold_art["points"]) >= 0.525


def test_backtest_stress_improvements_one_to_three(monkeypatch):
    from datetime import datetime, timezone
    from unittest.mock import MagicMock
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
    from src.utils.model_performance import (
        compute_top6_quality_score,
        has_top6_risk_flag,
        rank_top6_items,
    )

    # 1 & 2. Contra / reverse-steam blocking & quality-weighted Top 6 ranking
    rows = [
        {
            "event_id": "e1",
            "market_type": "TOTAL",
            "selection": "OVER 152.5",
            "ev_per_unit": 0.16,
            "win_prob_lb10": 0.53,
            "movement_tags": ["contra_sharp_money"],
        },
        {
            "event_id": "e2",
            "market_type": "SPREAD",
            "selection": "Team B +3.5",
            "bet_line": 3.5,
            "ev_per_unit": 0.15,
            "win_prob_lb10": 0.525,
            "movement_tags": ["reverse_steam=-2.5"],
        },
        {
            "event_id": "e3",
            "market_type": "TOTAL",
            "selection": "OVER 148.5",
            "ev_per_unit": 0.155,
            "win_prob_lb10": 0.535,
            "movement_tags": [],
        },
        {
            "event_id": "e4",
            "market_type": "SPREAD",
            "selection": "Team D -3.5",
            "bet_line": -3.5,
            "ev_per_unit": 0.075,
            "win_prob_lb10": 0.555,
            "movement_tags": ["sharp_backing", "rlm_confirmed"],
        },
    ]
    assert has_top6_risk_flag(rows[0]) is True
    assert has_top6_risk_flag(rows[1]) is True
    assert has_top6_risk_flag(rows[2]) is False
    ranked = rank_top6_items(rows, limit=6)
    # Contra & reverse-steam rows are blocked from Top 6; sharp-backed SPREAD outranks extreme-edge TOTAL OVER
    assert [r["event_id"] for r in ranked] == ["e4", "e3"]
    assert ranked[0]["rank"] == 1
    assert compute_top6_quality_score(rows[3]) > compute_top6_quality_score(rows[2])

    # 3. Fast-tempo OVER asymmetric dampening + extreme divergence shrinkage in analyze()
    model = NCAAMMarketFirstModelV2()
    model.torvik_service = MagicMock()
    model.kenpom_client = MagicMock()
    model.kenpom_client.get_team_player_agg.return_value = None
    model.kenpom_client.get_team_rating.return_value = None
    model.kenpom_client.get_home_court.return_value = None
    model.kenpom_client.get_player_stats_for_team.return_value = []
    model.haslametrics_client = MagicMock()
    model.geo_service = MagicMock()
    model.geo_service.get_altitude_adjustment.return_value = 0.0
    model.geo_service.calculate_distance.return_value = 100.0
    model.injury_service = MagicMock()
    model.injury_service.get_matchup_injuries.return_value = {"has_injuries": False, "injuries": []}
    model.news_service = MagicMock()
    model.news_service.fetch_game_context.return_value = {}
    model.news_service.summarize_impact.return_value = ""
    monkeypatch.setattr(model, "_get_council_verdict", lambda eid: None)
    monkeypatch.setattr(model, "_calculate_shooting_regression", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_situational_spots", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_fatigue_penalty", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot, avg_ftr=None: tot)
    monkeypatch.setattr(model, "_load_winprob_calibration", lambda: {"points": []})
    monkeypatch.setattr(model, "_get_archetype_stats", lambda key: {"n": 80, "mean": 0.03, "sd": 0.90})

    # Fast-tempo +6.5 OVER projection gets damped asymmetrically vs symmetric -6.5 UNDER projection
    model.torvik_service.get_matchup_team_stats.return_value = {
        "game_tempo": 75.5,
        "home": {"luck": 0.0, "continuity": 0.72, "record": "14-4"},
        "away": {"luck": 0.0, "continuity": 0.72, "record": "12-6"},
    }
    model.torvik_service.get_projection.return_value = {"margin": 4.0, "official_margin": 4.0, "total": 162.5, "lean": "Home"}
    model.kenpom_client.calculate_kenpom_adjustment.return_value = {"spread_adj": 4.0, "fair_margin": 4.0, "fair_total": 162.5, "total_adj": 0.0, "summary": "KP"}
    model.haslametrics_client.calculate_projection.return_value = {"available": True, "margin": 4.0, "total": 162.5}
    res_over = model.analyze(
        "evt_fast_over",
        event_context={"id": "evt_fast_over", "home_team": "Home", "away_team": "Away", "start_time": datetime(2027, 1, 20, 20, 0, tzinfo=timezone.utc)},
        market_snapshot={"spread_home": -4.0, "total": 156.0},
        persist=False,
    )

    model.torvik_service.get_projection.return_value = {"margin": 4.0, "official_margin": 4.0, "total": 149.5, "lean": "Home"}
    model.kenpom_client.calculate_kenpom_adjustment.return_value = {"spread_adj": 4.0, "fair_margin": 4.0, "fair_total": 149.5, "total_adj": 0.0, "summary": "KP"}
    model.haslametrics_client.calculate_projection.return_value = {"available": True, "margin": 4.0, "total": 149.5}
    res_under = model.analyze(
        "evt_fast_under",
        event_context={"id": "evt_fast_under", "home_team": "Home", "away_team": "Away", "start_time": datetime(2027, 1, 20, 20, 0, tzinfo=timezone.utc)},
        market_snapshot={"spread_home": -4.0, "total": 156.0},
        persist=False,
    )
    over_dev = res_over["context"]["fair_total"] - 156.0
    under_dev = 156.0 - res_under["context"]["fair_total"]
    assert 0.0 < over_dev < under_dev
    assert res_over["debug"]["sigma_total"] == pytest.approx(res_under["debug"]["sigma_total"], abs=0.01)

    # Extreme 9-pt spread divergence shrinks post-cap edge and widens sigma vs normal 5.0-pt divergence
    model.torvik_service.get_matchup_team_stats.return_value = {
        "game_tempo": 68.0,
        "home": {"luck": 0.0, "continuity": 0.72, "record": "14-4"},
        "away": {"luck": 0.0, "continuity": 0.72, "record": "12-6"},
    }
    model.torvik_service.get_projection.return_value = {"margin": 8.5, "official_margin": 8.5, "total": 144.0, "lean": "Home"}
    model.kenpom_client.calculate_kenpom_adjustment.return_value = {"spread_adj": 8.5, "fair_margin": 8.5, "fair_total": 144.0, "total_adj": 0.0, "summary": "KP"}
    model.haslametrics_client.calculate_projection.return_value = {"available": True, "margin": 8.5, "total": 144.0}
    res_normal_sp = model.analyze(
        "evt_norm_sp",
        event_context={"id": "evt_norm_sp", "home_team": "Home", "away_team": "Away", "start_time": datetime(2027, 1, 20, 20, 0, tzinfo=timezone.utc)},
        market_snapshot={"spread_home": -3.5, "total": 144.0},
        persist=False,
    )
    model.torvik_service.get_projection.return_value = {"margin": 12.5, "official_margin": 12.5, "total": 144.0, "lean": "Home"}
    model.kenpom_client.calculate_kenpom_adjustment.return_value = {"spread_adj": 12.5, "fair_margin": 12.5, "fair_total": 144.0, "total_adj": 0.0, "summary": "KP"}
    model.haslametrics_client.calculate_projection.return_value = {"available": True, "margin": 12.5, "total": 144.0}
    res_extreme_sp = model.analyze(
        "evt_ext_sp",
        event_context={"id": "evt_ext_sp", "home_team": "Home", "away_team": "Away", "start_time": datetime(2027, 1, 20, 20, 0, tzinfo=timezone.utc)},
        market_snapshot={"spread_home": -3.5, "total": 144.0},
        persist=False,
    )
    assert abs(res_extreme_sp["context"]["fair_spread_home"] - (-3.5)) < abs(res_normal_sp["context"]["fair_spread_home"] - (-3.5))
    assert res_extreme_sp["debug"]["sigma_spread"] > res_normal_sp["debug"]["sigma_spread"]

    # 4. Tightened High confidence cutoff (lb10 >= 0.565) & tip-off lock guard on daily_top_picks upsert
    assert model._confidence_label_from_winprob(0.555) == "Medium"
    assert model._confidence_score_0_100(0.555, ev_per_unit=0.06) < 80
    assert model._confidence_label_from_winprob(0.568) == "High"
    assert model._confidence_score_0_100(0.568, ev_per_unit=0.08) >= 80

    import src.scripts.build_daily_top_picks as bdtp
    captured_sql = []
    monkeypatch.setattr(bdtp, "_exec", lambda c, sql, p: captured_sql.append(sql))
    bdtp.upsert_pick("2026-11-16", "action:ncaam:lock_test", {"recommendations": []}, conn=MagicMock())
    assert captured_sql and "e.start_time <= (clock_timestamp() + INTERVAL '30 minutes')" in captured_sql[0]


def test_kenpom_fanmatch_total_ff_and_hasla_pace_sigma(monkeypatch):
    from datetime import datetime, timezone
    from unittest.mock import MagicMock
    from src.services.kenpom_client import KenPomClient
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2

    kp = KenPomClient()
    ratings_map = {
        "Duke": {
            "team": "Duke",
            "rank": 4,
            "adj_em": 24.0,
            "adj_o": 120.0,
            "adj_d": 96.0,
            "adj_t": 70.0,
            "off_efg": 54.0,
            "def_efg": 47.0,
            "off_to": 15.0,
            "def_to": 19.0,
            "off_or": 32.0,
            "def_or": 26.0,
            "off_ftr": 37.0,
            "def_ftr": 29.0,
        },
        "North Carolina": {
            "team": "North Carolina",
            "rank": 12,
            "adj_em": 19.0,
            "adj_o": 116.0,
            "adj_d": 97.0,
            "adj_t": 72.0,
            "off_efg": 53.0,
            "def_efg": 48.5,
            "off_to": 15.5,
            "def_to": 18.0,
            "off_or": 30.0,
            "def_or": 27.0,
            "off_ftr": 36.0,
            "def_ftr": 31.0,
        },
    }
    monkeypatch.setattr(kp, "get_team_rating", lambda t, conn=None: ratings_map.get(t))
    monkeypatch.setattr(kp, "get_fanmatch_prediction", lambda h, a, conn=None: None)
    no_fm = kp.calculate_kenpom_adjustment("Duke", "North Carolina")
    assert no_fm["total_four_factors_adj"] > 0.0

    monkeypatch.setattr(
        kp,
        "get_fanmatch_prediction",
        lambda h, a, conn=None: {"fair_margin": 11.0, "fair_total": 160.0},
    )
    with_fm = kp.calculate_kenpom_adjustment("Duke", "North Carolina")
    assert with_fm["fair_margin"] > no_fm["fair_margin"]
    assert with_fm["fair_total"] > no_fm["fair_total"]
    assert with_fm["total_four_factors_adj"] == no_fm["total_four_factors_adj"]

    # Verify NCAAMMarketFirstModelV2 consumes total_four_factors_adj and inflates sigma_total on Haslametrics pace mismatch
    model = NCAAMMarketFirstModelV2()
    model.torvik_service = MagicMock()
    model.kenpom_client = MagicMock()
    model.haslametrics_client = MagicMock()
    model.odds_selector = MagicMock()
    model.geo_service = MagicMock()
    model.geo_service.get_altitude_adjustment.return_value = 0.0
    model.geo_service.calculate_distance.return_value = 100.0
    monkeypatch.setattr(model, "_get_council_verdict", lambda eid: None)
    monkeypatch.setattr(model, "_calculate_shooting_regression", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_situational_spots", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_fatigue_penalty", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot, avg_ftr=None: tot)
    monkeypatch.setattr(model, "_load_winprob_calibration", lambda: {"points": []})
    monkeypatch.setattr(model, "_get_archetype_stats", lambda key: {"n": 80, "mean": 0.02, "sd": 0.90})
    model.kenpom_client.get_team_rating.return_value = None
    model.kenpom_client.get_home_court.return_value = None
    model.kenpom_client.get_player_stats_for_team.return_value = []
    model.kenpom_client.get_team_player_agg.return_value = None
    model.torvik_service.get_matchup_team_stats.return_value = {
        "game_tempo": 68.0,
        "home": {"luck": 0.0, "continuity": 0.72, "record": "14-4"},
        "away": {"luck": 0.0, "continuity": 0.72, "record": "12-6"},
    }
    model.torvik_service.get_projection.return_value = {"margin": 4.0, "official_margin": 4.0, "total": 144.0, "lean": "Home"}
    model.kenpom_client.calculate_kenpom_adjustment.return_value = {
        "spread_adj": 4.0,
        "fair_margin": 4.0,
        "fair_total": 144.0,
        "total_adj": 0.0,
        "total_four_factors_adj": 1.2,
        "summary": "KP",
    }
    model.haslametrics_client.calculate_projection.return_value = {
        "available": True,
        "margin": 4.0,
        "total": 144.0,
        "game_tempo": 68.5,
    }
    res_aligned = model.analyze(
        "evt_pace_ok",
        event_context={"id": "evt_pace_ok", "home_team": "Home", "away_team": "Away", "start_time": datetime(2027, 1, 20, 20, 0, tzinfo=timezone.utc)},
        market_snapshot={"spread_home": -4.0, "total": 144.0},
        persist=False,
    )
    assert res_aligned["debug"]["kenpom_total_four_factors_adj"] == pytest.approx(1.2, abs=0.01)

    model.haslametrics_client.calculate_projection.return_value = {
        "available": True,
        "margin": 4.0,
        "total": 144.0,
        "game_tempo": 73.0,
    }
    res_mismatch = model.analyze(
        "evt_pace_gap",
        event_context={"id": "evt_pace_gap", "home_team": "Home", "away_team": "Away", "start_time": datetime(2027, 1, 20, 20, 0, tzinfo=timezone.utc)},
        market_snapshot={"spread_home": -4.0, "total": 144.0},
        persist=False,
    )
    assert res_mismatch["debug"]["sigma_total"] > res_aligned["debug"]["sigma_total"]


def test_recommended_bet_sizing_and_split_kelly_update():
    from src.utils.ev import compute_recommended_bet_size
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2

    high_s = compute_recommended_bet_size(0.585, -110, confidence_tier="HIGH", confidence_score=86, ev=0.116)
    med_s = compute_recommended_bet_size(0.545, -110, confidence_tier="MEDIUM", confidence_score=64, ev=0.04)
    low_s = compute_recommended_bet_size(0.545, 110, confidence_tier="LOW", confidence_score=45, ev=0.14)
    neg_s = compute_recommended_bet_size(0.49, -110, confidence_tier="LOW", ev=-0.06)
    parlay_s = compute_recommended_bet_size(0.34, 240, confidence_tier="MEDIUM", ev=0.156, min_units=0.25, max_units=0.75)

    assert 1.25 <= high_s["units"] <= 2.0
    assert high_s["sizing_tier"] in ("Strong Play", "Standard Play")
    assert 0.5 <= med_s["units"] <= 1.5
    assert 0.5 <= low_s["units"] <= 0.75  # Low confidence cannot size up even on dog odds
    assert neg_s["units"] == 0.0 and neg_s["sizing_tier"] == "Pass"
    assert 0.25 <= parlay_s["units"] <= 0.75

    model = NCAAMMarketFirstModelV2()
    recs = [
        {
            "market": "SPREAD",
            "side": "home",
            "line": -4.5,
            "price": -110,
            "win_prob": 0.56,
            "win_prob_lb10": 0.55,
            "ev": 0.069,
            "kelly": 0.019,
            "confidence": "Medium",
            "confidence_0_100": 68,
            "book": "FanDuel",
        }
    ]
    # Contra sharp money fades against pick and updates rec['kelly'] (previously broken by 'kelly_pct' check)
    out = model._apply_split_and_injury_signals(
        recs,
        action_splits={
            "SPREAD": {
                "HOME": {"bet_pct": 75.0, "handle_pct": 30.0},
                "AWAY": {"bet_pct": 25.0, "handle_pct": 70.0},
            }
        },
        injury_context=None,
        market_consensus={"open_spread_home": -4.5, "current_spread_home": -4.5},
        relax_gates=True,
    )
    assert len(out) == 1
    assert "contra_sharp_money" in out[0]["movement_tags"]
    assert out[0]["kelly"] < 0.019


def test_action_network_multibook_and_open_line_pipeline(monkeypatch):
    from unittest.mock import MagicMock
    from src.services.odds_fetcher_service import OddsFetcherService
    from src.services.odds_adapter import OddsAdapter
    from src.services.odds_selection_service import OddsSelectionService
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2

    sample_game = {
        "id": 999001,
        "start_time": "2026-11-16T23:00:00Z",
        "status": "scheduled",
        "home_team_id": 1,
        "away_team_id": 2,
        "teams": [
            {"id": 1, "full_name": "Duke Blue Devils"},
            {"id": 2, "full_name": "Kentucky Wildcats"},
        ],
        "markets": {
            "15": {"event": {"spread": [{"side": "home", "value": -6.5, "odds": -110}, {"side": "away", "value": 6.5, "odds": -110}], "total": [{"side": "over", "value": 152.5, "odds": -110}, {"side": "under", "value": 152.5, "odds": -110}]}},
            "30": {"event": {"spread": [{"side": "home", "value": -4.5, "odds": -108}, {"side": "away", "value": 4.5, "odds": -112}], "total": [{"side": "over", "value": 150.0, "odds": -110}, {"side": "under", "value": 150.0, "odds": -110}]}},
            "68": {"event": {"spread": [{"side": "home", "value": -6.5, "odds": -114}, {"side": "away", "value": 6.5, "odds": -108}]}},
            "69": {"event": {"spread": [{"side": "home", "value": -6.0, "odds": -110}, {"side": "away", "value": 6.0, "odds": -110}]}},
            "75": {"event": {"spread": [{"side": "home", "value": -7.5, "odds": -102}, {"side": "away", "value": 7.5, "odds": -118}]}},
        },
    }

    parsed = OddsFetcherService()._parse_game(sample_game)
    assert parsed is not None
    assert parsed["home_spread"] == -6.5
    assert parsed["open_lines"]["home_spread"] == -4.5
    assert set(parsed["book_lines"].keys()) == {"consensus", "DraftKings", "FanDuel", "BetMGM"}

    # Verify full verified Action Network book map
    full_mk = dict(sample_game)
    full_mk["markets"] = {
        **sample_game["markets"],
        "71": {"event": {"spread": [{"side": "home", "value": -6.5, "odds": -110}]}},
        "79": {"event": {"spread": [{"side": "home", "value": -6.5, "odds": -110}]}},
        "123": {"event": {"spread": [{"side": "home", "value": -6.5, "odds": -110}]}},
    }
    parsed_full = OddsFetcherService()._parse_game(full_mk)
    assert {"consensus", "DraftKings", "FanDuel", "BetRivers", "BetMGM", "bet365", "Caesars"}.issubset(
        set(parsed_full["book_lines"].keys())
    )

    adapter = OddsAdapter()
    monkeypatch.setattr(adapter, "_upsert_action_network_event", lambda league, ev, st: "action:ncaam:999001")
    snaps = adapter._from_action_network(parsed, "NCAAM", "2026-11-16T20:00:00Z")
    books_emitted = {s["book"] for s in snaps}
    assert {"consensus", "DraftKings", "FanDuel", "BetMGM", "action_open"}.issubset(books_emitted)

    selector = OddsSelectionService()
    best_home = selector.get_best_price_for_side(snaps, "SPREAD", "HOME", target_line=-6.5)
    assert best_home is not None
    # Excludes action_open and picks FanDuel -6.0 (-110) within 0.5 pt anchor (ignoring -7.5 outlier)
    assert best_home["book"] == "FanDuel"
    assert best_home["line_value"] == -6.0

    model = NCAAMMarketFirstModelV2()
    mc = model._derive_market_consensus_from_snaps(
        snaps,
        consensus_spread={"line_value": -6.5, "price": -110},
        consensus_total={"line_value": 152.5, "price": -110},
        base_mc={"open_spread_home": -6.5, "current_spread_home": -6.5, "books_count": 1},
    )
    assert mc["books_count"] == 4
    assert mc["spread_disagreement"] == pytest.approx(1.5, abs=0.01)
    assert mc["open_spread_home"] == -4.5
    assert mc["spread_move_home"] == pytest.approx(-2.0, abs=0.01)


def test_espn_neutral_venue_game_logs_and_altitude(monkeypatch):
    from src.parsers.espn_client import EspnClient
    from src.services.espn_ncaa_client import ESPNNCAAClient
    from src.services.geo_service import GeoService
    import src.database as db_mod

    geo = GeoService()
    assert geo.get_altitude_adjustment("Wyoming Cowboys", neutral_site=False, away_team="Duke Blue Devils") == 1.0
    assert geo.get_altitude_adjustment("Wyoming Cowboys", neutral_site=True, away_team="Duke Blue Devils") == 0.0
    assert geo.get_altitude_adjustment("Wyoming Cowboys", neutral_site=False, away_team="Colorado State Rams") == 0.0

    espn_client = EspnClient()
    espn_client.identity = type("StubId", (), {"get_or_create_team": lambda *a, **kw: "tid"})()
    norm = espn_client._normalize_events(
        [
            {
                "id": "401999",
                "date": "2026-11-16T23:30Z",
                "season": {"year": 2027},
                "status": {"type": {"name": "STATUS_SCHEDULED"}},
                "competitions": [
                    {
                        "neutralSite": True,
                        "venue": {"fullName": "Sanford Pentagon", "address": {"city": "Sioux Falls", "state": "SD"}},
                        "competitors": [
                            {"homeAway": "home", "team": {"id": "10", "displayName": "Nebraska Cornhuskers", "abbreviation": "NEB"}},
                            {"homeAway": "away", "team": {"id": "11", "displayName": "Boise State Broncos", "abbreviation": "BOIS"}},
                        ],
                    }
                ],
            }
        ],
        "NCAAM",
    )
    assert len(norm) == 1
    assert norm[0]["neutral_site"] is True
    assert norm[0]["venue"] == "Sanford Pentagon"
    assert norm[0]["venue_city"] == "Sioux Falls"
    assert norm[0]["venue_state"] == "SD"

    ncaa = ESPNNCAAClient()
    captured_logs = []
    monkeypatch.setattr(
        ncaa,
        "get_scoreboard",
        lambda date=None: {
            "events": [
                {
                    "id": "5001",
                    "date": "2026-11-15T20:00Z",
                    "status": {"type": {"completed": True}},
                    "competitions": [
                        {
                            "neutralSite": False,
                            "competitors": [
                                {
                                    "homeAway": "home",
                                    "score": "82",
                                    "curatedRank": {"current": 5},
                                    "team": {"shortDisplayName": "Duke", "displayName": "Duke Blue Devils"},
                                    "statistics": [
                                        {"name": "threePointFieldGoalsMade", "displayValue": "10"},
                                        {"name": "threePointFieldGoalsAttempted", "displayValue": "25"},
                                        {"name": "threePointFieldGoalPct", "displayValue": "40.0"},
                                    ],
                                },
                                {
                                    "homeAway": "away",
                                    "score": "74",
                                    "curatedRank": {"current": 99},
                                    "team": {"shortDisplayName": "Temple", "displayName": "Temple Owls"},
                                    "statistics": [
                                        {"name": "threePointFieldGoalsMade", "displayValue": "7"},
                                        {"name": "threePointFieldGoalsAttempted", "displayValue": "22"},
                                        {"name": "threePointFieldGoalPct", "displayValue": "31.8"},
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ]
        },
    )
    monkeypatch.setattr(db_mod, "upsert_team_game_logs", lambda rows: captured_logs.extend(rows) or len(rows))
    saved = ncaa.sync_completed_game_logs(days_back=1)
    assert saved == 2
    temple_row = next(r for r in captured_logs if r["team_text"] == "Temple")
    assert temple_row["opponent"] == "Duke"
    assert temple_row["opponent_rank"] == 5
    assert temple_row["three_p_pct"] == pytest.approx(0.318, abs=0.001)
    assert temple_row["margin"] == -8


def test_barttorvik_adj_tempo_index44_and_kenpom_continuity_priority(monkeypatch):
    from datetime import datetime, timezone
    from unittest.mock import MagicMock
    from src.services.barttorvik import BartTorvikClient
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2

    sample_row = [None] * 45
    sample_row[0] = 5
    sample_row[1] = "Duke"
    sample_row[2] = "ACC"
    sample_row[3] = "4-0"
    sample_row[4] = 120.44
    sample_row[6] = 90.96
    sample_row[33] = -0.1361
    sample_row[43] = 303
    sample_row[44] = 70.8956  # Live BartTorvik AdjTempo slot

    client = BartTorvikClient()
    captured_payload = []
    monkeypatch.setattr("requests.get", lambda *a, **kw: type("Resp", (), {"status_code": 200, "json": staticmethod(lambda: [sample_row])})())
    monkeypatch.setattr("src.services.barttorvik.upsert_bt_team_metrics_daily", lambda p: captured_payload.extend(p))
    monkeypatch.setattr("src.services.barttorvik.upsert_team_metrics", lambda p: None)

    ratings = client.get_efficiency_ratings(year=2027)
    assert ratings["Duke"]["tempo"] == pytest.approx(70.8956, abs=0.001)
    assert len(captured_payload) == 1
    assert captured_payload[0]["adj_tempo"] == pytest.approx(70.8956, abs=0.001)
    assert captured_payload[0]["continuity"] is None

    # Verify model ignores stale AdjT-equal Torvik continuity when KenPom reports low continuity
    model = NCAAMMarketFirstModelV2()
    model.torvik_service = MagicMock()
    model.kenpom_client = MagicMock()
    model.haslametrics_client = MagicMock()
    model.news_service = MagicMock()
    model.geo_service = MagicMock()
    model.geo_service.get_altitude_adjustment.return_value = 0.0
    model.geo_service.calculate_distance.return_value = 0.0
    model._calculate_shooting_regression = MagicMock(return_value=0.0)
    model._calculate_situational_spots = MagicMock(return_value=0.0)
    model._calculate_fatigue_penalty = MagicMock(return_value=0.0)
    model._get_action_splits = MagicMock(return_value=None)
    model._get_injuries_context = MagicMock(return_value=None)
    model._get_referee_crews_context = MagicMock(return_value=None)
    model.kenpom_client.get_home_court.return_value = None
    model.kenpom_client.get_player_stats_for_team.return_value = []
    model.kenpom_client.get_team_player_agg.return_value = None

    model.torvik_service.get_projection.return_value = {"margin": 4.0, "official_margin": 4.0, "total": 144.0, "lean": "Home"}
    model.kenpom_client.calculate_kenpom_adjustment.return_value = {
        "spread_adj": 4.0,
        "fair_margin": 4.0,
        "fair_total": 144.0,
        "total_adj": 0.0,
        "home_continuity": 0.25,
        "away_continuity": 0.25,
        "summary": "KP",
    }
    model.haslametrics_client.calculate_projection.return_value = {"available": True, "margin": 4.0, "total": 144.0}
    model.torvik_service.get_matchup_team_stats.return_value = {
        "game_tempo": 70.9,
        "home": {"luck": 0.0, "tempo": 70.9, "continuity": 70.9, "record": "3-0"},
        "away": {"luck": 0.0, "tempo": 70.9, "continuity": 70.9, "record": "3-0"},
    }
    res_low_cont = model.analyze(
        "evt_cont_low",
        event_context={"id": "evt_cont_low", "home_team": "Home", "away_team": "Away", "start_time": datetime(2026, 11, 20, 20, 0, tzinfo=timezone.utc)},
        market_snapshot={"spread_home": -4.0, "total": 144.0},
        persist=False,
    )
    model.kenpom_client.calculate_kenpom_adjustment.return_value["home_continuity"] = 0.78
    model.kenpom_client.calculate_kenpom_adjustment.return_value["away_continuity"] = 0.78
    res_high_cont = model.analyze(
        "evt_cont_high",
        event_context={
            "id": "evt_cont_high",
            "home_team": "Home",
            "away_team": "Away",
            "neutral_site": True,
            "venue": "T-Mobile Arena",
            "start_time": datetime(2026, 11, 20, 20, 0, tzinfo=timezone.utc),
        },
        market_snapshot={"spread_home": -4.0, "total": 144.0},
        persist=False,
    )
    assert res_low_cont["debug"]["sigma_spread"] > res_high_cont["debug"]["sigma_spread"]
    assert res_high_cont["neutral_site"] is True
    assert res_high_cont["venue"] == "T-Mobile Arena"


def test_calibrated_top6_quality_score_and_smart_risk_gate(monkeypatch):
    from datetime import datetime, timezone
    from unittest.mock import MagicMock
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
    from src.utils.model_performance import compute_top6_quality_score

    # 1. Spread bucket & consensus scoring
    base_sp = {
        "market_type": "SPREAD",
        "side": "home",
        "home_team": "Home Univ",
        "away_team": "Away State",
        "ev_per_unit": 0.045,
        "win_prob_lb10": 0.53,
        "movement_tags": [],
    }
    q_comp = compute_top6_quality_score({**base_sp, "market_line": -8.5})
    q_blow1 = compute_top6_quality_score({**base_sp, "market_line": -16.5})
    q_blow2 = compute_top6_quality_score({**base_sp, "market_line": -24.5})
    assert q_comp > q_blow1 > q_blow2

    q_agree1 = compute_top6_quality_score({**base_sp, "market_line": -8.5, "conviction_sources": 1})
    q_agree2 = compute_top6_quality_score({**base_sp, "market_line": -8.5, "conviction_sources": 2})
    q_agree3 = compute_top6_quality_score({**base_sp, "market_line": -8.5, "conviction_sources": 3})
    assert q_agree2 == pytest.approx(q_agree1 + 0.006)
    assert q_agree3 == pytest.approx(q_agree1 + 0.012)

    # Higher-EV OVER 155.0 outranks lower-EV UNDER 155.0 (old -0.027 penalty removed)
    q_over = compute_top6_quality_score({
        "market_type": "TOTAL",
        "side": "over",
        "selection": "OVER 155.0",
        "market_line": 155.0,
        "ev_per_unit": 0.055,
        "win_prob_lb10": 0.53,
    })
    q_under = compute_top6_quality_score({
        "market_type": "TOTAL",
        "side": "under",
        "selection": "UNDER 155.0",
        "market_line": 155.0,
        "ev_per_unit": 0.042,
        "win_prob_lb10": 0.53,
    })
    assert q_over > q_under

    # 2. Smart Risk tier in _passes_publish_gates + 0.5u cap in analyze()
    model = NCAAMMarketFirstModelV2()
    model._get_archetype_stats = lambda k: {"n": 80, "mean": 0.03, "sd": 0.10}
    monkeypatch.setattr(model, "_load_adaptive_learning", lambda: {})

    sr_sp = {
        "market": "SPREAD",
        "side": "home",
        "ev": 0.040,
        "edge_points": 2.0,
        "win_prob_lb10": 0.512,
        "_agree_count": 2,
    }
    assert model._passes_publish_gates(sr_sp, -7.5, True) is True
    assert sr_sp["is_smart_risk"] is True
    assert sr_sp["risk_tier"] == "SMART_RISK"
    assert "smart_risk_high_return" in sr_sp["movement_tags"]

    sr_tot = {
        "market": "TOTAL",
        "side": "over",
        "ev": 0.045,
        "edge_points": 2.2,
        "win_prob_lb10": 0.510,
        "_agree_count_total": 2,
    }
    assert model._passes_publish_gates(sr_tot, None, True) is True
    assert sr_tot["is_smart_risk"] is True
    assert sr_tot["risk_tier"] == "SMART_RISK"

    core_sp = {
        "market": "SPREAD",
        "side": "home",
        "ev": 0.040,
        "edge_points": 2.0,
        "win_prob_lb10": 0.528,
        "_agree_count": 2,
    }
    assert model._passes_publish_gates(core_sp, -7.5, True) is True
    assert core_sp["is_smart_risk"] is False
    assert core_sp["risk_tier"] == "CORE"

    # Low lb10 without sufficient EV/consensus stays blocked
    weak_sp = {
        "market": "SPREAD",
        "side": "home",
        "ev": 0.025,
        "edge_points": 1.2,
        "win_prob_lb10": 0.512,
        "_agree_count": 1,
    }
    assert model._passes_publish_gates(weak_sp, -7.5, True) is False

    # End-to-end analyze() caps Smart Risk plays at 0.5u
    monkeypatch.setenv("REQUIRE_DATABASE", "0")
    model2 = NCAAMMarketFirstModelV2()
    model2.torvik_service = MagicMock()
    model2.kenpom_client = MagicMock()
    model2.haslametrics_client = MagicMock()
    model2.news_service = MagicMock()
    model2.injury_service = MagicMock()
    model2.news_service.fetch_game_context.return_value = {}
    model2.news_service.summarize_impact.return_value = ""
    model2.injury_service.get_matchup_injuries.return_value = {"has_injuries": False, "injuries": []}
    model2.injury_service.get_game_injury_context.return_value = {"has_injuries": False, "spread_adj": 0.0, "total_adj": 0.0, "injuries": []}
    monkeypatch.setattr(model2, "_get_council_verdict", lambda eid: None)
    monkeypatch.setattr(model2, "_calculate_shooting_regression", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model2, "_calculate_situational_spots", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model2, "_calculate_fatigue_penalty", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model2, "_apply_referee_signal", lambda eid, tot, avg_ftr=None: tot)
    monkeypatch.setattr(model2, "_get_archetype_stats", lambda k: {"n": 80, "mean": 0.04, "sd": 0.90})
    monkeypatch.setattr(model2, "_load_winprob_calibration", lambda: {"points": []})
    monkeypatch.setattr(model2, "_load_adaptive_learning", lambda: {})
    model2.torvik_service.get_projection.return_value = {"margin": 9.5, "official_margin": 9.5, "total": 144.0, "lean": "Home"}
    model2.torvik_service.get_matchup_team_stats.return_value = {
        "game_tempo": 68.0,
        "home": {"luck": 0.0, "continuity": 0.75, "record": "14-3"},
        "away": {"luck": 0.0, "continuity": 0.75, "record": "11-6"},
    }
    model2.kenpom_client.calculate_kenpom_adjustment.return_value = {"spread_adj": 9.5, "fair_margin": 9.5, "fair_total": 144.0, "summary": "KP"}
    model2.haslametrics_client.calculate_projection.return_value = {"available": True, "margin": 9.5, "total": 144.0}
    monkeypatch.setattr(
        model2,
        "_confidence_bounds_from_mu_uncertainty",
        lambda **kw: {"lb10": 0.512, "ub90": 0.610},
    )
    now_q = datetime.now(timezone.utc)
    res_sr = model2.analyze(
        "evt_smart_risk",
        event_context={"id": "evt_smart_risk", "home_team": "Home Univ", "away_team": "Road State", "start_time": datetime(2027, 2, 14, 23, 0, tzinfo=timezone.utc)},
        market_snapshot={
            "spread_home": -3.5,
            "total": 144.0,
            "_quote_as_of": now_q,
            "_best_spread_home": {"book": "DraftKings", "line_value": -3.5, "price": -110, "captured_at": now_q},
            "_best_spread_away": {"book": "DraftKings", "line_value": 3.5, "price": -110, "captured_at": now_q},
            "_best_total_over": {"book": "DraftKings", "line_value": 144.0, "price": -110, "captured_at": now_q},
            "_best_total_under": {"book": "DraftKings", "line_value": 144.0, "price": -110, "captured_at": now_q},
        },
        persist=False,
    )
    assert res_sr["is_actionable"] is True
    assert res_sr["risk_tier"] == "SMART_RISK"
    assert res_sr["is_smart_risk"] is True
    assert res_sr["suggested_units"] <= 0.5
    assert res_sr["recommendations"][0]["sizing_tier"] == "Half-Unit Smart Risk Play"

    # 3. Audit hardening: nested rec_json matches flattened dict, contra blocks Smart Risk, RLM promotes Smart Risk -> CORE
    flat_row = {
        "market_type": "TOTAL",
        "side": "under",
        "selection": "UNDER 148.5",
        "market_line": 148.5,
        "ev": 0.055,
        "win_prob_lb10": 0.535,
        "conviction_sources_total": 3,
        "movement_tags": ["sharp_price_edge"],
    }
    nested_row = {"rec_json": dict(flat_row)}
    assert compute_top6_quality_score(nested_row) == pytest.approx(compute_top6_quality_score(flat_row))

    contra_sr = {
        "market": "SPREAD",
        "side": "home",
        "ev": 0.045,
        "edge_points": 2.0,
        "win_prob_lb10": 0.512,
        "_agree_count": 3,
        "sharp_edge_pts": -1.5,
        "movement_tags": ["contra_sharp_line"],
    }
    assert model._passes_publish_gates(contra_sr, -7.5, True) is False

    promoted = model._apply_split_and_injury_signals(
        [{
            "market": "SPREAD",
            "side": "home",
            "line": -4.5,
            "price": -110,
            "win_prob": 0.545,
            "win_prob_lb10": 0.518,
            "ev": 0.040,
            "is_smart_risk": True,
            "risk_tier": "SMART_RISK",
            "movement_tags": ["smart_risk_high_return"],
        }],
        action_splits={
            "SPREAD": {
                "HOME": {"bet_pct": 35.0, "handle_pct": 62.0},
                "AWAY": {"bet_pct": 65.0, "handle_pct": 38.0},
            }
        },
        market_consensus={"open_spread_home": -3.5, "current_spread_home": -4.5},
    )
    assert len(promoted) == 1
    assert promoted[0]["win_prob_lb10"] == pytest.approx(0.521)
    assert promoted[0]["is_smart_risk"] is False
    assert promoted[0]["risk_tier"] == "CORE"
    assert "smart_risk_high_return" not in (promoted[0].get("movement_tags") or [])











