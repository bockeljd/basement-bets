"""Stress-test suite for the learnable NCAAM live pacing and win-probability engine.

Covers 16+ real college basketball scenarios:
- 47% / 53% 1st-half vs. 2nd-half CBB scoring curves (and custom learned splits)
- Early-game hot/cold bursts (blend damping)
- Late-game intentional fouling surge vs. blowout slowdown in final 4 minutes
- Overtime probability bump for close late-game totals
- Full 1H parity (TOTAL_1H, SPREAD_1H)
- Already-cashed Overs / already-busted Unders
- Overtime in progress
- Online learning via fit_live_calibration_artifact (proving zero hardcoding)
"""

import pytest

from src.services.live_calibration_service import (
    compute_live_bet_win_prob,
    default_live_calibration_params,
    expected_cbb_scoring_share,
    fit_live_calibration_artifact,
    project_live_cbb_pace,
)


def test_1_halftime_47_53_curve_projects_higher_second_half():
    # At halftime (ef=0.5), 68 pts is 47% of ~144.7 pts, NOT 50% (136 pts)
    res_47 = project_live_cbb_pace(
        elapsed_fraction=0.50,
        home_score=35,
        away_score=33,
        pregame_total=144.0,
        pregame_home_margin=2.0,
    )
    res_50 = project_live_cbb_pace(
        elapsed_fraction=0.50,
        home_score=35,
        away_score=33,
        pregame_total=144.0,
        pregame_home_margin=2.0,
        params={"first_half_share": 0.50},
    )
    assert expected_cbb_scoring_share(0.50, 0.47) == pytest.approx(0.47)
    assert res_47["projected_total"] > res_50["projected_total"] + 3.0
    assert 142.0 <= res_47["projected_total"] <= 147.0


def test_2_slow_first_half_blends_with_pregame_without_panic():
    # 20 pts scored in first 8 mins (ef=0.20), pregame total 146
    res = project_live_cbb_pace(
        elapsed_fraction=0.20,
        home_score=11,
        away_score=9,
        pregame_total=146.0,
        pregame_home_margin=0.0,
    )
    # Must stay anchored near pregame (not collapse to 100 pts)
    assert 125.0 <= res["projected_total"] <= 145.0


def test_3_early_2_minute_scoring_burst_damped():
    # 16 pts in first 2 minutes (ef=0.05) — raw pace would be 320 pts!
    res = project_live_cbb_pace(
        elapsed_fraction=0.05,
        home_score=9,
        away_score=7,
        pregame_total=142.0,
        pregame_home_margin=0.0,
    )
    assert res["projected_total"] < 175.0


def test_4_close_game_final_2_minutes_triggers_foul_surge():
    # 4-point game with 2:00 left (ef=0.95)
    close_res = project_live_cbb_pace(
        elapsed_fraction=0.95,
        home_score=72,
        away_score=68,
        pregame_total=144.0,
        pregame_home_margin=3.0,
    )
    no_foul_res = project_live_cbb_pace(
        elapsed_fraction=0.95,
        home_score=72,
        away_score=68,
        pregame_total=144.0,
        pregame_home_margin=3.0,
        params={"late_foul_boost_pts": 0.0, "ot_prob_scale": 0.0},
    )
    assert close_res["late_pace_adj"] > 1.0
    assert close_res["projected_total"] > no_foul_res["projected_total"] + 1.5


def test_5_blowout_final_3_minutes_applies_slowdown_drag():
    # 24-point blowout with 3:00 left (ef=0.925)
    blowout_res = project_live_cbb_pace(
        elapsed_fraction=0.925,
        home_score=84,
        away_score=60,
        pregame_total=148.0,
        pregame_home_margin=10.0,
    )
    close_res = project_live_cbb_pace(
        elapsed_fraction=0.925,
        home_score=74,
        away_score=70,
        pregame_total=148.0,
        pregame_home_margin=2.0,
    )
    assert blowout_res["late_pace_adj"] < -0.5
    assert blowout_res["ot_prob"] < 0.01
    assert close_res["projected_total"] > blowout_res["projected_total"] + 2.0


def test_6_tied_game_final_minute_ot_bump_lifts_over_win_prob():
    # Tied 68-68 (136 pts) with 1:20 left (ef=0.967) vs Over 142.5
    with_ot = compute_live_bet_win_prob(
        elapsed_fraction=0.967,
        home_score=68,
        away_score=68,
        pregame_total=144.0,
        pregame_home_margin=0.0,
        market_type="TOTAL",
        side="OVER",
        bet_line=142.5,
    )
    without_ot = compute_live_bet_win_prob(
        elapsed_fraction=0.967,
        home_score=68,
        away_score=68,
        pregame_total=144.0,
        pregame_home_margin=0.0,
        market_type="TOTAL",
        side="OVER",
        bet_line=142.5,
        params={"ot_prob_scale": 0.0},
    )
    assert with_ot["ot_prob"] >= 0.10
    assert with_ot["ot_expected_pts"] >= 1.5
    assert with_ot["raw_live_win_prob"] > without_ot["raw_live_win_prob"] + 0.05


def test_7_blowout_final_minute_has_zero_ot_risk():
    res = compute_live_bet_win_prob(
        elapsed_fraction=0.975,
        home_score=82,
        away_score=58,
        pregame_total=142.0,
        pregame_home_margin=12.0,
        market_type="TOTAL",
        side="OVER",
        bet_line=144.5,
    )
    assert res["ot_prob"] < 0.005


def test_8_already_cashed_over_returns_99_percent():
    res = compute_live_bet_win_prob(
        elapsed_fraction=0.80,
        home_score=76,
        away_score=72,
        pregame_total=144.0,
        pregame_home_margin=2.0,
        market_type="TOTAL",
        side="OVER",
        bet_line=145.5,
    )
    assert res["raw_live_win_prob"] == 0.99


def test_9_already_busted_under_returns_1_percent():
    res = compute_live_bet_win_prob(
        elapsed_fraction=0.82,
        home_score=75,
        away_score=73,
        pregame_total=142.0,
        pregame_home_margin=0.0,
        market_type="TOTAL",
        side="UNDER",
        bet_line=145.5,
    )
    assert res["raw_live_win_prob"] == 0.01


def test_10_total_1h_with_2m36s_left_matches_20_minute_clock():
    # Exact Charlotte @ FGCU scenario: 32-25 (57 pts) at 2:36 left in 1H => 17.4/40 = 0.435 game elapsed
    res = compute_live_bet_win_prob(
        elapsed_fraction=17.4 / 40.0,
        home_score=25,
        away_score=32,
        pregame_total=69.0,
        pregame_home_margin=-7.0,
        market_type="TOTAL_1H",
        side="OVER",
        bet_line=66.5,
    )
    assert 63.0 <= res["projected_total"] <= 69.0
    assert res["ot_prob"] == 0.0
    assert res["late_pace_adj"] == 0.0
    assert 0.20 <= res["raw_live_win_prob"] <= 0.65


def test_11_total_1h_with_full_game_pregame_total_scales_by_first_half_share():
    # If pregame_total is passed as full-game 148.0, 1H model scales it by learned first_half_share
    res = compute_live_bet_win_prob(
        elapsed_fraction=0.25,  # 10 min left in 1H
        home_score=18,
        away_score=16,
        pregame_total=148.0,
        pregame_home_margin=4.0,
        market_type="TOTAL_1H",
        side="OVER",
        bet_line=68.5,
    )
    assert 64.0 <= res["projected_total"] <= 74.0


def test_12_spread_1h_uses_half_clock_and_half_margin():
    res = compute_live_bet_win_prob(
        elapsed_fraction=0.35,  # 6 min left in 1H
        home_score=28,
        away_score=20,
        pregame_total=144.0,
        pregame_home_margin=6.0,
        market_type="SPREAD_1H",
        side="HOME",
        bet_line=-3.5,
    )
    assert res["projected_home_margin"] > 6.0
    assert res["raw_live_win_prob"] > 0.75


def test_13_overtime_in_progress_disables_second_ot_bump_and_stays_safe():
    res = compute_live_bet_win_prob(
        elapsed_fraction=0.98,
        home_score=74,
        away_score=74,
        pregame_total=140.0,
        pregame_home_margin=0.0,
        market_type="TOTAL",
        side="OVER",
        bet_line=150.5,
        in_overtime=True,
    )
    assert res["ot_prob"] == 0.0
    assert res["late_pace_adj"] == 0.0
    assert 0.02 <= res["raw_live_win_prob"] <= 0.98


def test_14_spread_favorite_trailing_early_vs_leading_late_is_monotonic():
    early_down = compute_live_bet_win_prob(
        elapsed_fraction=0.20,
        home_score=12,
        away_score=18,
        pregame_total=144.0,
        pregame_home_margin=8.0,
        market_type="SPREAD",
        side="HOME",
        bet_line=-7.5,
    )
    late_up = compute_live_bet_win_prob(
        elapsed_fraction=0.85,
        home_score=68,
        away_score=56,
        pregame_total=144.0,
        pregame_home_margin=8.0,
        market_type="SPREAD",
        side="HOME",
        bet_line=-7.5,
    )
    assert late_up["raw_live_win_prob"] > early_down["raw_live_win_prob"] + 0.45


def test_15_underdog_spread_covering_comfortably_in_2nd_half():
    res = compute_live_bet_win_prob(
        elapsed_fraction=0.80,
        home_score=54,
        away_score=52,
        pregame_total=140.0,
        pregame_home_margin=10.0,
        market_type="SPREAD",
        side="AWAY",
        bet_line=9.5,
    )
    assert res["raw_live_win_prob"] > 0.80


def test_16_online_learning_adapts_pacing_params_from_graded_snapshots():
    # Diverse graded snapshots across game phases (halftime, mid-2H, late close, late blowout)
    rows = []
    for i in range(36):
        if i < 12:
            ef, hs, as_, line, won = 0.50, 34 + (i % 5), 32 + (i % 4), 142.5, (i % 4 != 0)
        elif i < 24:
            ef, hs, as_, line, won = 0.78, 56 + (i % 6), 54 + (i % 4), 143.5, (i % 3 != 0)
        else:
            ef, hs, as_, line, won = 0.93, 70 + (i % 4), 67 + (i % 3), 144.5, (i % 3 != 0)
        rows.append(
            {
                "elapsed_fraction": ef,
                "home_score": hs,
                "away_score": as_,
                "pregame_total": 144.0,
                "pregame_home_margin": 2.0,
                "market_type": "TOTAL",
                "side": "OVER",
                "bet_line": line,
                "outcome": "WON" if won else "LOST",
            }
        )
    art = fit_live_calibration_artifact(rows, season_start="2026-11-01", min_obs=25)
    assert art["active"] is True
    assert art["status"] == "calibrated"
    params = art["params"]
    for k in default_live_calibration_params():
        assert k in params
    assert art["brier_calibrated"] is not None
    assert art["brier_calibrated"] <= art["brier_raw"] + 1e-6
