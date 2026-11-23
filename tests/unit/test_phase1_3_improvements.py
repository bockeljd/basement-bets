from unittest.mock import patch

from src.services.ncaam_parlay_service import (
    build_three_leg_high_payout_parlays,
    evaluate_value_underdog_ml_leg,
    grade_parlay_leg_from_scores,
)
from src.utils.model_performance import normalize_history_row
from src.utils.naming import standardize_team_name


def test_evaluate_value_underdog_ml_leg_accepts_strong_value_dog():
    res = evaluate_value_underdog_ml_leg(
        event_id="evt-dog-1",
        home_team="Butler",
        away_team="Villanova",
        start_time="2026-03-20T23:00:00Z",
        side="HOME",
        ml_price=155,
        ml_book="DraftKings",
        fair_spread_home=1.0,  # ~46% home win prob vs 39.2% implied at +155
        sigma_spread=10.8,
        conviction_sources=2,
    )
    assert res is not None
    assert res["is_value_underdog"] is True
    assert res["is_smart_risk"] is True
    assert res["risk_tier"] == "SMART_RISK"
    assert res["ev_per_unit"] >= 0.035


def test_evaluate_value_underdog_ml_leg_rejects_longshot_or_low_conviction():
    base = dict(
        event_id="evt-dog-2",
        home_team="Butler",
        away_team="Villanova",
        start_time="2026-03-20T23:00:00Z",
        side="HOME",
        ml_book="DraftKings",
        fair_spread_home=1.0,
        sigma_spread=10.8,
    )
    # Odds too long (> +220)
    assert evaluate_value_underdog_ml_leg(**base, ml_price=280, conviction_sources=3) is None
    # Not an underdog (< +110)
    assert evaluate_value_underdog_ml_leg(**base, ml_price=100, conviction_sources=3) is None
    # Insufficient independent model conviction
    assert evaluate_value_underdog_ml_leg(**base, ml_price=155, conviction_sources=1) is None


def test_build_three_leg_high_payout_parlays_builds_valid_combo_and_enforces_caps():
    legs = [
        {
            "event_id": "g1",
            "matchup": "A @ B",
            "team_pick": "B ML",
            "price": -145,
            "win_prob": 0.66,
            "ev": 0.11,
            "ev_per_unit": 0.11,
            "risk_tier": "CORE",
            "is_smart_risk": False,
            "is_value_underdog": False,
        },
        {
            "event_id": "g2",
            "matchup": "C @ D",
            "team_pick": "D -3.5",
            "price": -110,
            "win_prob": 0.60,
            "ev": 0.14,
            "ev_per_unit": 0.14,
            "risk_tier": "CORE",
            "is_smart_risk": False,
            "is_value_underdog": False,
        },
        {
            "event_id": "g3",
            "matchup": "E @ F",
            "team_pick": "E ML",
            "price": 145,
            "win_prob": 0.46,
            "ev": 0.12,
            "ev_per_unit": 0.12,
            "risk_tier": "SMART_RISK",
            "is_smart_risk": True,
            "is_value_underdog": True,
        },
        # Duplicate event_id should never be paired with g1
        {
            "event_id": "g1",
            "matchup": "A @ B",
            "team_pick": "OVER 145.5",
            "price": -110,
            "win_prob": 0.59,
            "ev": 0.12,
            "ev_per_unit": 0.12,
            "risk_tier": "CORE",
            "is_smart_risk": False,
            "is_value_underdog": False,
        },
    ]

    combos = build_three_leg_high_payout_parlays(
        legs,
        odds_lo=300,
        odds_hi=1000,
        min_ev=0.04,
        limit=5,
    )
    assert len(combos) >= 1
    c = combos[0]
    assert len(c["legs"]) == 3
    assert 300 <= c["american_odds"] <= 1000
    assert c["ev"] >= 0.04
    assert len({leg["event_id"] for leg in c["legs"]}) == 3
    assert c["suggested_units"] <= 0.5


def test_grade_parlay_leg_from_scores_markets():
    gr = {"home_team": "Duke", "away_team": "UNC", "home_score": 78, "away_score": 70}
    assert grade_parlay_leg_from_scores({"market_type": "MONEYLINE", "team_pick": "Duke ML", "is_home_pick": True}, gr) == "WON"
    assert grade_parlay_leg_from_scores({"market_type": "SPREAD", "team_pick": "Duke -8.5", "is_home_pick": True}, gr) == "LOST"
    assert grade_parlay_leg_from_scores({"market_type": "TOTAL", "team_pick": "OVER 144.5"}, gr) == "WON"
    assert grade_parlay_leg_from_scores({"market_type": "TOTAL", "team_pick": "UNDER 148.0"}, gr) == "PUSH"


def test_normalize_history_row_exposes_risk_tier_and_clv():
    row = {
        "id": 1,
        "event_id": "evt1",
        "league": "NCAAM",
        "market_type": "SPREAD",
        "selection": "Duke -4.5",
        "bet_line": -4.5,
        "close_line": -6.0,
        "bet_price": -110,
        "ev_per_unit": 0.04,
        "outcome": "WON",
        "inputs_json": {"risk_tier": "SMART_RISK", "is_smart_risk": True},
    }
    norm = normalize_history_row(row)
    assert norm["risk_tier"] == "SMART_RISK"
    assert norm["is_smart_risk"] is True
    assert norm["clv_points"] == 1.5

    total_row = {
        "id": 2,
        "event_id": "evt2",
        "league": "NCAAM",
        "market_type": "TOTAL",
        "selection": "UNDER 148.5",
        "bet_line": 148.5,
        "close_line": 146.5,
        "bet_price": -110,
        "ev_per_unit": 0.05,
        "outcome": "WON",
        "inputs_json": {},
    }
    norm_total = normalize_history_row(total_row)
    assert norm_total["risk_tier"] == "CORE"
    assert norm_total["is_smart_risk"] is False
    assert norm_total["clv_points"] == 2.0


def test_standardize_team_name_handles_duplicate_aliases_and_accents():
    assert standardize_team_name("Delaware Fightin Blue Hens") == "Delaware"
    assert standardize_team_name("Tennessee-Martin Skyhawks") == "UT Martin"
    assert standardize_team_name("American University Eagles") == "American"
    assert standardize_team_name("Nicholls State") == "Nicholls"
    assert standardize_team_name("George Washington Revolutionaries") == "George Washington"
    assert standardize_team_name("San José State") == "San Jose St."


def test_ingest_kenpom_bundle_ingests_torvik_daily_schedules():
    from src.scripts.ingest_kenpom import ingest_kenpom_bundle

    bundle = {
        "torvik_daily_schedules": {
            "2026-03-20": [{"home": "Duke", "away": "UNC", "pred_margin": 5.5}]
        }
    }
    with patch("src.scripts.ingest_kenpom.ensure_tables"), patch(
        "src.database.upsert_bt_daily_schedule"
    ) as mock_upsert:
        res = ingest_kenpom_bundle(bundle, asof_date="2026-03-20")
        assert res["status"] == "ok"
        assert res["datasets_synced"]["torvik_daily_schedules"] == 1
        mock_upsert.assert_called_once_with(
            [{"home": "Duke", "away": "UNC", "pred_margin": 5.5}], "20260320"
        )
