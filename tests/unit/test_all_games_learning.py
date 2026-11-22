import pytest


def test_all_games_learning_bias_sigma_and_feed_accuracy():
    from src.services.archetype_learning_service import (
        fit_adaptive_learning_from_rows,
        fit_all_games_learning,
    )

    # Simulate 50 completed lined games where:
    # - actual scoring runs +4.0 pts higher than fair_total
    # - model sigma_spread is over-inflated (15.0) vs realized spread residual SD (~9.0)
    # - KenPom is sharper than Haslametrics
    slate_rows = []
    for i in range(50):
        sign = 1.0 if i % 2 == 0 else -1.0
        # Spread residual alternates +/-9 around market (-4.0)
        mkt_sp = -4.0
        actual_margin_home = 4.0 + (sign * 9.0)  # home - away
        away_score = 70.0
        home_score = away_score + actual_margin_home
        fair_tot = (home_score + away_score) - 4.0
        mkt_tot = fair_tot + 0.5  # model leans UNDER by 0.5 while actual goes OVER
        slate_rows.append(
            {
                "event_id": f"evt:{i}",
                "home_score": home_score,
                "away_score": away_score,
                "context_json": {
                    "current_spread_home": mkt_sp,
                    "fair_spread_home": mkt_sp - (1.0 * sign),
                    "kenpom_spread_home": mkt_sp - (2.0 * sign),
                    "torvik_spread_home": mkt_sp - (1.0 * sign),
                    "hasla_spread_home": mkt_sp + (3.0 * sign),
                    "current_total": mkt_tot,
                    "fair_total": fair_tot,
                    "sigma_spread": 15.0,
                    "sigma_total": 19.0,
                },
            }
        )

    summary = fit_all_games_learning(slate_rows)
    assert summary["n_games"] == 50
    assert summary["total_bias_sample"] == 50
    # 50/(50+25) * 4.0 = 2.667 -> clamped to +2.5
    assert summary["total_bias_pts"] == pytest.approx(2.5, abs=0.01)

    sig = summary["sigma_calibration"]
    assert sig["spread_n"] == 50
    assert sig["spread_realized_sd"] < 10.0
    assert sig["spread_model_avg_sigma"] == pytest.approx(15.0, abs=0.01)
    assert 0.88 <= sig["spread_sigma_scale"] < 0.96

    feeds = summary["feed_accuracy"]
    assert feeds["kenpom"]["mae"] < feeds["haslametrics"]["mae"]
    assert feeds["kenpom"]["ats_win_rate"] == 1.0
    assert feeds["haslametrics"]["ats_win_rate"] == 0.0

    # Even with ZERO published bets (rows=[]), adaptive learning now picks up full-slate bias & sigma scale
    payload = fit_adaptive_learning_from_rows([], baseline_bins={}, all_games_rows=slate_rows)
    assert payload["total_graded"] == 0  # official published-bet count stays untouched
    la = payload["learned_adjustments"]
    assert la["total_bias_source"] == "all_completed_games"
    assert la["total_bias_sample"] == 50
    assert la["total_bias_pts"] == pytest.approx(2.5, abs=0.01)
    assert 0.88 <= la["spread_sigma_scale"] < 0.96
    assert payload["all_games_summary"]["n_games"] == 50
