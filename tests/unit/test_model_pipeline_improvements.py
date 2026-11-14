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
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot: tot)
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
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot: tot)
    monkeypatch.setattr(model, "_get_archetype_stats", lambda key: {"n": 80, "mean": 0.02, "sd": 0.90})

    snapshot = {
        "spread_home": -4.5,
        "spread_price_home": -110,
        "total": 137.0,
        "total_over_price": -110,
        "book_spread": "DraftKings",
        "book_total": "DraftKings",
        "_best_spread_home": {"line_value": -4.5, "price": -110, "book": "DraftKings"},
        "_best_spread_away": {"line_value": 4.5, "price": -110, "book": "DraftKings"},
        "_best_total_over": {"line_value": 137.0, "price": -110, "book": "DraftKings"},
        "_best_total_under": {"line_value": 137.0, "price": -110, "book": "DraftKings"},
    }
    res = model.analyze(
        "action:ncaam:999999",
        market_snapshot=snapshot,
        event_context=ev_ctx,
        persist=False,
    )
    ctx = res["context"]
    assert ctx["conviction_sources"] == 3
    assert ctx["efficiency_weight"] >= 0.40
    assert ctx["fair_spread_home"] < -5.8
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
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot: tot)
    monkeypatch.setattr(model, "_get_archetype_stats", lambda key: {"n": 80, "mean": 0.0, "sd": 0.90})

    snapshot = {
        "spread_home": -37.5,
        "spread_price_home": -110,
        "total": 146.5,
        "total_over_price": -110,
        "book_spread": "DraftKings",
        "book_total": "DraftKings",
        "_best_spread_home": {"line_value": -37.5, "price": -110, "book": "DraftKings"},
        "_best_spread_away": {"line_value": 37.5, "price": -110, "book": "DraftKings"},
        "_best_total_over": {"line_value": 146.5, "price": -110, "book": "DraftKings"},
        "_best_total_under": {"line_value": 146.5, "price": -110, "book": "DraftKings"},
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

    assert NCAAMMarketFirstModelV2.VERSION == "2.3.0-calibrated"
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
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot: tot)
    monkeypatch.setattr(model, "_get_archetype_stats", lambda key: {"n": 80, "mean": 0.0, "sd": 0.90})

    # Consensus total is 142.5, while best Over book offers 143.5 — selection & market_line must both reflect 143.5
    snapshot = {
        "spread_home": -4.5,
        "spread_price_home": -110,
        "total": 142.5,
        "total_over_price": -110,
        "book_spread": "DraftKings",
        "book_total": "DraftKings",
        "_best_spread_home": {"line_value": -4.5, "price": -110, "book": "DraftKings"},
        "_best_spread_away": {"line_value": 4.5, "price": -110, "book": "DraftKings"},
        "_best_total_over": {"line_value": 143.5, "price": -105, "book": "FanDuel"},
        "_best_total_under": {"line_value": 142.5, "price": -115, "book": "DraftKings"},
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
    assert adj["fatigue_adj"] == pytest.approx(0.4, abs=0.05)
    assert adj["spot_adj"] == pytest.approx(-0.1, abs=0.15)
    assert adj["shooting_adj"] == pytest.approx(0.15, abs=0.2)
    assert res["context"]["fatigue_adj"] == pytest.approx(0.4, abs=0.05)
    assert "w_base" in res["context"] and "w_hasla" in res["context"]



