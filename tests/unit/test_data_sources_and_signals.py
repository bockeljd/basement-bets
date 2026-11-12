from datetime import datetime
from unittest.mock import MagicMock

import brotli
import pytest
from fastapi.testclient import TestClient

from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
from src.scripts.ingest_kenpom import parse_kenpom_csv_text
from src.services.action_enrichment_service import ActionEnrichmentService
from src.services.espn_ncaa_client import ESPNNCAAClient
from src.services.haslametrics_client import (
    _decode_response_bytes,
    compute_matchup_projection,
    parse_haslametrics_xml,
)
from src.services.injury_service import InjuryService
from scripts.build_winprob_calibration_ncaam import Obs, fit_calibration_artifact


def test_haslametrics_xml_parse_brotli_and_projection():
    xml_sample = """<?xml version="1.0" encoding="utf-8"?>
    <ratings>
      <dt md="1111" />
      <av e="109.5" u="70.0" />
      <ha e="4.2" u="0.1" />
      <mr rk="1" t="Texas A&amp;M" c="SEC" w="2" l="0" oe="122.0" de="94.0" ou="72.0" du="70.0" ap="-999" sos="999" mom="0.2" inc="0.1" />
      <mr rk="45" t="Montana St." c="BigSky" w="1" l="1" oe="105.0" de="108.0" ou="68.0" du="68.0" ap="0.4" sos="-0.1" mom="0.0" inc="0.0" />
    </ratings>"""

    compressed = brotli.compress(xml_sample.encode("utf-8"))
    decoded = _decode_response_bytes(compressed, headers={"Content-Encoding": "br"})
    assert "<mr " in decoded

    parsed = parse_haslametrics_xml(decoded, fallback_date="2026-11-11")
    assert parsed["asof_date"].endswith("-11-11")
    assert len(parsed["teams"]) == 2
    home = parsed["teams"][0]
    away = parsed["teams"][1]
    assert home["team_name"] == "Texas A&M"
    assert home["ap"] is None
    assert home["sos"] is None
    assert home["net_eff"] == pytest.approx(28.0)

    proj = compute_matchup_projection(home, away, neutral_site=False)
    assert proj is not None
    assert proj["margin"] > 20.0
    assert proj["total"] > 140.0
    assert "-" in proj["projected_score"]

    with pytest.raises(ValueError):
        parse_haslametrics_xml("<!DOCTYPE html><html><body>Sorry, you have been blocked</body></html>")


def test_action_splits_v2_pregame_preference_and_v1_fallback():
    v2_game = {
        "id": 123456,
        "markets": {
            "15": {
                "event": {
                    "spread": [
                        {
                            "side": "home",
                            "value": -5.5,
                            "is_live": True,
                            "bet_info": {"tickets": {"percent": 80}, "money": {"percent": 80}},
                        },
                        {
                            "side": "home",
                            "value": -4.5,
                            "is_live": False,
                            "bet_info": {"tickets": {"percent": 32}, "money": {"percent": 68}},
                        },
                        {
                            "side": "away",
                            "value": 4.5,
                            "is_live": False,
                            "bet_info": {"tickets": {"percent": 68}, "money": {"percent": 32}},
                        },
                    ],
                    "total": [
                        {
                            "side": "over",
                            "value": 152.5,
                            "is_live": False,
                            "bet_info": {"tickets": {"percent": 55}, "money": {"percent": 72}},
                        },
                        {
                            "side": "under",
                            "value": 152.5,
                            "is_live": False,
                            "bet_info": {"tickets": {"percent": 45}, "money": {"percent": 28}},
                        },
                    ],
                }
            }
        },
    }

    rows = ActionEnrichmentService.parse_splits_from_game(v2_game)
    by_key = {(r["market"], r["selection"]): r for r in rows}

    # Pregame row (-4.5, is_live=False) wins over live row
    assert by_key[("SPREAD", "HOME")]["line"] == -4.5
    assert by_key[("SPREAD", "HOME")]["bet_pct"] == 32
    assert by_key[("SPREAD", "HOME")]["handle_pct"] == 68
    assert by_key[("SPREAD", "HOME")]["sharp_indicator"] == "RLM"
    assert by_key[("TOTAL", "OVER")]["sharp_indicator"] == "SHARP_MONEY"

    v1_legacy_game = {
        "id": 999,
        "odds": [
            {
                "spread_home": -3.0,
                "total": 144.0,
                "spread_home_public": 40,
                "spread_away_public": 60,
                "spread_home_money": 62,
                "spread_away_money": 38,
                "ml_home_public": 55,
                "ml_away_public": 45,
                "ml_home_money": 50,
                "ml_away_money": 50,
            }
        ],
    }
    legacy_rows = ActionEnrichmentService.parse_splits_from_game(v1_legacy_game)
    assert any(r["market"] == "SPREAD" and r["selection"] == "HOME" and r["handle_pct"] == 62 for r in legacy_rows)


def test_espn_extract_officials_and_injuries():
    summary = {
        "gameInfo": {
            "officials": [
                {"displayName": "Ted Valentine"},
                {"fullName": "Roger Ayers"},
                {"displayName": "Doug Sirmons"},
            ]
        },
        "injuries": [
            {
                "team": {"displayName": "Michigan State Spartans"},
                "injuries": [
                    {
                        "athlete": {"displayName": "Jeremy Fears", "position": {"abbreviation": "G"}},
                        "status": "Out",
                        "shortComment": "Ankle",
                    }
                ],
            }
        ],
    }

    refs = ESPNNCAAClient.extract_officials_from_summary(summary)
    assert refs == ["Ted Valentine", "Roger Ayers", "Doug Sirmons"]

    injs = ESPNNCAAClient.extract_injuries_from_summary(summary)
    assert len(injs) == 1
    assert injs[0]["player"] == "Jeremy Fears"
    assert injs[0]["team"] == "Michigan State Spartans"
    assert injs[0]["status"] == "Out"


def test_injury_service_disambiguation_and_sigma_mult():
    svc = InjuryService()
    raw = [
        {"player_name": "Star Guard", "team_id": "Michigan State", "status": "Out", "description": "Knee"},
        {"player_name": "Reserve F", "team_id": "Michigan", "status": "Questionable", "description": "Illness"},
    ]

    # Home = Michigan State Spartans, Away = Duke Blue Devils -> only MSU player counts as Out; Michigan must NOT false-match MSU
    res = svc.evaluate_injuries(raw, home_team="Michigan State Spartans", away_team="Duke Blue Devils")
    assert res["has_injuries"] is True
    assert res["home_out_count"] == 1
    assert res["away_out_count"] == 0
    assert res["sigma_mult"] == pytest.approx(1.04)
    sides = {i["player"]: i["side"] for i in res["injuries"]}
    assert sides["Star Guard"] == "home"
    assert sides["Reserve F"] is None


def test_parse_kenpom_csv_and_tsv_with_seeds():
    csv_summary = (
        "Season,TeamName,RankAdjEM,Conf,Wins,Losses,AdjEM,AdjOE,AdjDE,AdjTempo\n"
        "2026,Duke,2,ACC,25,3,31.4,124.2,92.8,68.9\n"
        "2026,Houston,1,B12,26,2,32.1,121.0,88.9,63.5\n"
    )
    rows_csv = parse_kenpom_csv_text(csv_summary)
    assert len(rows_csv) == 2
    assert rows_csv[0]["team_name"] == "Duke"
    assert rows_csv[0]["adj_em"] == pytest.approx(31.4)
    assert rows_csv[0]["record"] == "25-3"

    tsv_paste = (
        "Rk\tTeam\tConf\tW-L\tNetRtg\tORtg\tDRtg\tAdjT\n"
        "1\tDuke 1\tACC\t25-3\t+31.40\t124.2\t92.8\t68.9\n"
        "12\tN.C. State 11\tACC\t19-10\t+18.25\t116.4\t98.1\t70.1\n"
    )
    rows_tsv = parse_kenpom_csv_text(tsv_paste)
    assert len(rows_tsv) == 2
    assert rows_tsv[0]["team_name"] == "Duke"
    assert rows_tsv[1]["team_name"] == "N.C. State"
    assert rows_tsv[1]["adj_em"] == pytest.approx(18.25)


def test_fit_calibration_artifact_monotonic():
    obs = []
    for p, rate in ((0.42, 0.40), (0.50, 0.50), (0.58, 0.59), (0.66, 0.68), (0.74, 0.77)):
        wins = int(round(rate * 20))
        for idx in range(20):
            obs.append(Obs(p=p, y=(1 if idx < wins else 0), w=1.0))

    artifact = fit_calibration_artifact(obs, days=30, min_points=5)
    pts = artifact["points"]
    assert len(pts) >= 2
    for i in range(1, len(pts)):
        assert pts[i]["p"] >= pts[i - 1]["p"]
        assert pts[i]["p_cal"] >= pts[i - 1]["p_cal"]


def test_model_v2_haslametrics_blend_injuries_and_splits(monkeypatch):
    model = NCAAMMarketFirstModelV2()
    model.torvik_service = MagicMock()
    model.torvik_service.get_projection.return_value = {
        "margin": 8.0,
        "official_margin": 8.0,
        "total": 146.0,
        "projected_score": "69-77",
        "lean": "Duke",
    }
    model.torvik_service.get_matchup_team_stats.return_value = {
        "game_tempo": 69.0,
        "home": {"luck": 0.0, "continuity": 70.0, "record": "15-5"},
        "away": {"luck": 0.0, "continuity": 70.0, "record": "12-8"},
    }

    # Simulate KenPom absent -> Haslametrics 35% + Torvik 65% fallback blend
    model.kenpom_client = MagicMock()
    model.kenpom_client.calculate_kenpom_adjustment.return_value = None
    model.kenpom_client.get_team_player_agg.return_value = None
    model.kenpom_client.get_team_rating.return_value = None
    model.kenpom_client.get_home_court.return_value = None
    model.kenpom_client.get_player_stats_for_team.return_value = []

    model.haslametrics_client = MagicMock()
    model.haslametrics_client.calculate_projection.return_value = {
        "available": True,
        "asof_date": "2026-02-15",
        "margin": 12.0,
        "total": 152.0,
        "projected_score": "70-82",
    }

    model.injury_service = MagicMock()
    model.injury_service.get_matchup_injuries.return_value = {
        "has_injuries": True,
        "home_out_count": 1,
        "away_out_count": 0,
        "gtd_count": 0,
        "sigma_mult": 1.04,
        "injuries": [
            {"player": "Rotation Wing", "team": "Duke", "side": "home", "status": "Out", "severity": "OUT", "detail": "Ankle"}
        ],
    }

    model.geo_service = MagicMock()
    model.geo_service.get_altitude_adjustment.return_value = 0.0
    model.geo_service.calculate_distance.return_value = 150.0

    model.news_service = MagicMock()
    model.news_service.get_team_news.return_value = []
    model.news_service.summarize_impact.return_value = ""

    monkeypatch.setattr(model, "_calculate_shooting_regression", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_situational_spots", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_calculate_fatigue_penalty", lambda *a, **kw: 0.0)
    monkeypatch.setattr(model, "_apply_referee_signal", lambda eid, tot: tot)
    monkeypatch.setattr(model, "_load_winprob_calibration", lambda: {"points": []})

    event = {
        "id": "evt_sig_1",
        "home_team": "Duke Blue Devils",
        "away_team": "Wake Forest Demon Deacons",
        "start_time": datetime(2026, 2, 15, 19, 0, 0),
    }
    snap = {"spread_home": -3.5, "total": 148.0}
    res = model.analyze("evt_sig_1", event_context=event, market_snapshot=snap, relax_gates=True, persist=False)

    # Signals populated for UI drawer
    assert res["signals"]["haslametrics"]["fair_spread_home"] == pytest.approx(-12.0, abs=0.1)
    assert res["signals"]["haslametrics"]["fair_total"] == pytest.approx(152.0, abs=0.1)
    assert res["signals"]["kenpom"] is None
    assert len(res["signals"]["injuries"]) == 1
    assert res["recommendations"]
    assert res["recommendations"][0]["signals"]["haslametrics"]["projected_score"] == "70-82"
    # Haslametrics contributes non-zero weight in 2-way blend when KenPom is absent
    assert res["signals"]["weights"]["haslametrics"] > 0.0
    assert res["signals"]["weights"]["torvik"] > res["signals"]["weights"]["haslametrics"]
    assert res["debug"]["sigma_spread"] > 10.5

    # Sharp split vs contra-sharp logic
    annotated = model._apply_split_and_injury_signals(
        [
            {"market": "SPREAD", "side": "home", "ev": 0.06, "movement_tags": []},
            {"market": "TOTAL", "side": "over", "ev": 0.05, "movement_tags": []},
        ],
        action_splits={
            "SPREAD": {"HOME": {"bet_pct": 30, "handle_pct": 66}, "AWAY": {"bet_pct": 70, "handle_pct": 34}},
            "TOTAL": {"OVER": {"bet_pct": 72, "handle_pct": 25}, "UNDER": {"bet_pct": 28, "handle_pct": 75}},
        },
        injury_context=model.injury_service.get_matchup_injuries.return_value,
    )
    assert "sharp_backing" in annotated[0]["movement_tags"]
    assert "injury_report_active" in annotated[0]["movement_tags"]
    assert "contra_sharp_money" in annotated[1]["movement_tags"]
    assert annotated[1]["ev"] == pytest.approx(0.04, abs=1e-4)


def test_api_smoke_run_council_and_kenpom_csv_validation(monkeypatch):
    from src.api import app
    from src.config import settings

    monkeypatch.setattr(settings, "BASEMENT_PASSWORD", "test-secret")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    client = TestClient(app)

    # 1. /api/jobs/run_council_today gracefully reports skipped when GEMINI_API_KEY unset
    resp_council = client.post(
        "/api/jobs/run_council_today",
        headers={"X-BASEMENT-KEY": "test-secret"},
    )
    assert resp_council.status_code == 200
    body_council = resp_council.json()
    assert body_council["status"] == "skipped"

    # 2. /api/admin/kenpom/upload-csv rejects empty or insufficient CSV cleanly with 400
    resp_empty = client.post(
        "/api/admin/kenpom/upload-csv",
        headers={"X-BASEMENT-KEY": "test-secret"},
        json={"csv_text": ""},
    )
    assert resp_empty.status_code == 400

    resp_short = client.post(
        "/api/admin/kenpom/upload-csv",
        headers={"X-BASEMENT-KEY": "test-secret"},
        json={"csv_text": "Team,AdjEM\nDuke,31.0\n"},
    )
    assert resp_short.status_code == 400

    # 3. /api/admin/kenpom/upload-csv multipart upload calls ingest_kenpom_csv cleanly
    import src.scripts.ingest_kenpom as ik
    monkeypatch.setattr(ik, "ingest_kenpom_csv", lambda text, asof_date=None: {"status": "ok", "asof_date": "2026-11-12", "rows": 365})
    resp_ok = client.post(
        "/api/admin/kenpom/upload-csv",
        headers={"X-BASEMENT-KEY": "test-secret"},
        files={"file": ("kenpom.csv", b"Team,AdjEM\nDuke,31.0\n", "text/csv")},
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json() == {"status": "ok", "asof_date": "2026-11-12", "rows": 365}


def test_update_data_health_records_haslametrics_and_splits(monkeypatch):
    from contextlib import contextmanager
    import src.scripts.update_data_health as udh

    recorded = {}

    class _FakeCursor:
        def __init__(self):
            self._sql = ""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, sql, params=None):
            self._sql = str(sql)

        def fetchone(self):
            if "haslametrics_ratings_daily" in self._sql:
                return (365,)
            if "action_splits" in self._sql:
                return (12,)
            if "bt_team_metrics_daily" in self._sql:
                return (360, "2026-11-12", "2026-11-12")
            return (100,)

        def fetchall(self):
            return []

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

        def commit(self):
            pass

    @contextmanager
    def _fake_conn():
        yield _FakeConn()

    monkeypatch.setattr(udh, "get_admin_db_connection", _fake_conn)
    monkeypatch.setattr(udh, "ensure_table", lambda: None)
    monkeypatch.setattr(udh, "upsert", lambda src, status, row_count=None, notes=None: recorded.__setitem__(src, (status, row_count, notes)))

    udh.main()
    assert recorded["haslametrics"] == ("ok", 365, "rows in last 48h")
    assert recorded["action_splits"] == ("ok", 12, "splits in last 24h")
