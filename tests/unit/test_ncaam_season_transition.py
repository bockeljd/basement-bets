from datetime import date
import os
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.utils.ncaam_season import (
    current_ncaam_calendar_year,
    current_ncaam_season_end_year,
    current_ncaam_season_long,
    current_ncaam_season_short,
    format_ncaam_season_long,
    format_ncaam_season_short,
    ncaam_season_compact_bounds,
    ncaam_season_date_bounds,
    parse_ncaam_season_end_year,
)
from src.services.edge_engine_ncaab import load_config, load_models
from src.services.ncaam_bracket_seed_loader import (
    _snake_seed_teams,
    get_seed_source_metadata,
    load_manual_bracket_seeds,
)


class TestNCAAMSeasonHelpers(unittest.TestCase):
    def test_season_rollover_dates(self):
        self.assertEqual(current_ncaam_season_end_year(date(2026, 11, 11)), 2027)
        self.assertEqual(current_ncaam_season_short(date(2026, 11, 11)), "2026-27")
        self.assertEqual(current_ncaam_season_long(date(2026, 11, 11)), "2026-2027")
        self.assertEqual(ncaam_season_date_bounds(ref_date=date(2026, 11, 11)), ("2026-11-01", "2027-05-01"))
        self.assertEqual(ncaam_season_compact_bounds(ref_date=date(2026, 11, 11)), ("20261101", "20270501"))

        # Spring belongs to the same season; July 1 flips to upcoming season
        self.assertEqual(current_ncaam_season_end_year(date(2027, 3, 20)), 2027)
        self.assertEqual(current_ncaam_season_end_year(date(2026, 6, 30)), 2026)
        self.assertEqual(current_ncaam_season_end_year(date(2026, 7, 1)), 2027)
        self.assertEqual(current_ncaam_calendar_year(date(2026, 11, 11)), 2026)

    def test_format_and_parse(self):
        self.assertEqual(format_ncaam_season_short(2027), "2026-27")
        self.assertEqual(format_ncaam_season_long(2027), "2026-2027")
        self.assertEqual(parse_ncaam_season_end_year(2027), 2027)
        self.assertEqual(parse_ncaam_season_end_year("2027"), 2027)
        self.assertEqual(parse_ncaam_season_end_year("2026-27"), 2027)
        self.assertEqual(parse_ncaam_season_end_year("2026-2027"), 2027)
        self.assertEqual(parse_ncaam_season_end_year("current", default=2027), 2027)


class TestEdgeEngineSeasonArtifacts(unittest.TestCase):
    def test_load_2027_config_and_fallback_models(self):
        cfg = load_config(2027)
        self.assertEqual(cfg.get("season_end_year"), 2027)
        self.assertIn("learned", cfg)

        # Future year without bespoke file falls back cleanly to baseline config
        future_cfg = load_config(2099)
        self.assertIn("learned", future_cfg)

        models = load_models(2027)
        self.assertTrue({"SPREAD", "TOTAL", "ML"}.issubset(models.keys()))


class TestBracketSeedSeasonGating(unittest.TestCase):
    def test_no_2026_seed_leakage_into_2027(self):
        self.assertEqual(load_manual_bracket_seeds("2026-27"), {})
        hist = load_manual_bracket_seeds("2025-26")
        self.assertEqual(set(hist.keys()), {"East", "South", "West", "Midwest"})

    def test_snake_seeding_shape(self):
        teams = [f"Team {i}" for i in range(1, 65)]
        grouped = _snake_seed_teams(teams)
        self.assertEqual(set(grouped.keys()), {"South", "East", "West", "Midwest"})
        for region, entries in grouped.items():
            self.assertEqual(len(entries), 16, msg=f"region={region}")
            self.assertEqual([e["seed"] for e in entries], list(range(1, 17)))

    def test_seed_metadata_variants(self):
        proj = get_seed_source_metadata("2026-27", source="projected_ratings")
        self.assertEqual(proj["season"], "2026-27")
        self.assertEqual(proj["source"], "projected_ratings")
        self.assertTrue(proj["projected"])

        pre = get_seed_source_metadata("2026-27", source="preseason_unseeded")
        self.assertEqual(pre["season"], "2026-27")
        self.assertEqual(pre["source"], "preseason_unseeded")
        self.assertFalse(pre["projected"])

    def test_correlation_engine_season_bounds(self):
        from src.services.correlation.ncaam_correlation_engine import NCAAMCorrelationEngine
        expected_start, expected_end = ncaam_season_date_bounds()
        self.assertEqual(NCAAMCorrelationEngine.SEASON_START, expected_start)
        self.assertEqual(NCAAMCorrelationEngine.SEASON_END, expected_end)

    def test_profile_generator_ignores_2026_static_rosters_in_2027(self):
        with open("src/services/profile_generator.py", "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("master_rosters_{current_ncaam_season_end_year()}.json", src)
        self.assertNotIn('"data/static/master_rosters_2026.json"', src)

    def test_barttorvik_defaults_to_current_season_url(self):
        from unittest.mock import MagicMock
        from src.services.barttorvik import BartTorvikClient

        client = BartTorvikClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        with patch("src.services.barttorvik.requests.get", return_value=mock_resp) as mock_get:
            client.get_efficiency_ratings()
            called_url = mock_get.call_args[0][0]
            self.assertEqual(called_url, f"https://barttorvik.com/{current_ncaam_season_end_year()}_team_results.json")

    def test_bracket_state_preseason_unseeded_payload(self):
        from unittest.mock import MagicMock
        from src.services.ncaam_bracket_state_service import NCAAMBracketStateService

        with patch.object(NCAAMBracketStateService, "_load_seed_rows", return_value=[]):
            svc = NCAAMBracketStateService(season="2026-27")
            svc.seed_source = "preseason_unseeded"
            payload = svc.build_bracket_payload()
            self.assertEqual(payload["season"], "2026-27")
            self.assertEqual(payload["status"], "preseason")
            self.assertEqual(payload["regions"], {})
            self.assertEqual(payload["seed_metadata"]["source"], "preseason_unseeded")

    def test_projected_bracket_seeds_filters_by_season_window(self):
        from src.services.ncaam_bracket_seed_loader import build_projected_bracket_seeds
        queries = []

        class _FakeCursor:
            def fetchall(self):
                return []

        def _fake_exec(conn, sql, params=None):
            queries.append((sql, params))
            return _FakeCursor()

        with patch("src.database.get_db_connection") as mock_db, \
             patch("src.database._exec", side_effect=_fake_exec):
            mock_db.return_value.__enter__.return_value = object()
            mock_db.return_value.__exit__.return_value = False
            res = build_projected_bracket_seeds(season="2026-27")

        self.assertEqual(res, {})
        self.assertEqual(len(queries), 3)
        for _, params in queries:
            self.assertEqual(params[:2], ("2026-11-01", "2027-05-01"))

    def test_simulate_bracket_disables_and_restores_news_fetch(self):
        from types import SimpleNamespace
        from src.services.ncaam_tournament_service import NCAAMTournamentPredictionService

        service = NCAAMTournamentPredictionService()
        service._model = SimpleNamespace(
            news_service=SimpleNamespace(skip_fetch=False),
        )
        observed_skip_fetch = []

        def _fake_analyze(*args, **kwargs):
            observed_skip_fetch.append(service._model.news_service.skip_fetch)
            ta, tb = kwargs["team_a"], kwargs["team_b"]
            return {
                "team_a": ta,
                "team_b": tb,
                "winner": ta,
                "winner_side": "team_a",
                "projected_spread_a": -2.0,
                "projected_total": 140.0,
                "win_prob_a": 60.0,
                "win_prob_b": 40.0,
                "confidence_0_100": 60.0,
                "market_data_used": False,
                "fallback_used": False,
                "reason_codes": [],
                "risk_flags": [],
                "debug": {},
            }

        service._model.analyze_tournament_game = _fake_analyze
        seeds = {
            r: [{"seed": i + 1, "team_name": f"{r}{i + 1}"} for i in range(16)]
            for r in ["East", "West", "South", "Midwest"]
        }
        with patch("src.database.get_db_connection") as mock_db, \
             patch.object(service, "preheat_cache"):
            mock_db.return_value.__enter__.return_value = object()
            mock_db.return_value.__exit__.return_value = False
            res = service.simulate_bracket(seeds, simulations=2, season="2026-27")

        self.assertEqual(res.season, "2026-27")
        self.assertTrue(observed_skip_fetch and all(observed_skip_fetch))
        self.assertFalse(service._model.news_service.skip_fetch)


class TestSeasonApiRoutes(unittest.TestCase):
    def test_bracket_current_and_2027_and_correlations_routes(self):
        from fastapi.testclient import TestClient
        from src.api import app

        tc = TestClient(app)
        expected_season = current_ncaam_season_short()
        expected_year = current_ncaam_season_end_year()

        # Correlations summary defaults cleanly to current 2026-2027 cache file
        with patch("src.api.settings.BASEMENT_PASSWORD", "test"):
            corr_res = tc.get("/api/ncaam/correlations/summary", headers={"X-BASEMENT-KEY": "test"})
        self.assertEqual(corr_res.status_code, 200)
        self.assertEqual(corr_res.json()["metadata"]["season"], "2026-2027")

        # Bracket /current and /{season_year} work publicly & pass active season
        mock_payload = {"season": expected_season, "status": "preseason", "regions": {}, "seed_metadata": {"source": "preseason_unseeded"}}
        with patch("src.api_extensions.ncaam_bracket_api._get_db_cache", return_value=None), \
             patch("src.api_extensions.ncaam_bracket_api.NCAAMBracketStateService") as mock_svc:
            mock_svc.return_value.build_bracket_payload.return_value = mock_payload

            res_cur = tc.get("/api/ncaam/bracket/current?refresh=true")
            self.assertEqual(res_cur.status_code, 200)
            self.assertEqual(res_cur.json()["season"], expected_season)
            mock_svc.assert_called_with(season=expected_season)

            res_yr = tc.get(f"/api/ncaam/bracket/{expected_year}?refresh=true")
            self.assertEqual(res_yr.status_code, 200)
            self.assertEqual(res_yr.json()["season"], expected_season)

        # Edge recommendations defaults season to current season_end_year (2027)
        with patch("src.api.settings.BASEMENT_PASSWORD", "test"), \
             patch("src.services.edge_engine_ncaab.recommend_for_date", return_value={"season_end_year": expected_year, "picks": []}) as mock_rec:
            edge_res = tc.get("/api/edge/ncaab/recommendations?date=2026-11-11", headers={"X-BASEMENT-KEY": "test"})
        self.assertEqual(edge_res.status_code, 200)
        self.assertEqual(edge_res.json()["season_end_year"], expected_year)
        mock_rec.assert_called_once_with(date_et="2026-11-11", season_end_year=expected_year)


if __name__ == "__main__":
    unittest.main()
