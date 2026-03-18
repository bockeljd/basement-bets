from datetime import datetime

from src.services.ncaam_tournament_service import NCAAMTournamentPredictionService, TournamentGamePrediction


def test_simulate_bracket_deterministic_respects_locked_matchups():
    service = NCAAMTournamentPredictionService()

    # Patch predict_game so the bracket is deterministic: team_a always wins.
    def _predict_game(game_input, conn=None):
        return TournamentGamePrediction(
            team_a=game_input.team_a,
            team_b=game_input.team_b,
            winner=game_input.team_a,
            winner_side="team_a",
            projected_spread_a=-1.0,
            projected_total=150.0,
            win_prob_a=60.0,
            win_prob_b=40.0,
            confidence_0_100=60.0,
            model_type="tournament_ensemble_v1",
            neutral_site=True,
            market_data_used=False,
            fallback_used=False,
            reason_codes=[],
            risk_flags=[],
            debug={},
            scheduled_tip_et=None,
            tv_network=None,
            site=None,
        )

    service.predict_game = _predict_game  # type: ignore

    south_seeds = [
        {"seed": 1, "team_name": "Florida Gators"},
        {"seed": 16, "team_name": "Seed16"},
        {"seed": 8, "team_name": "Seed8"},
        {"seed": 9, "team_name": "Seed9"},
        {"seed": 5, "team_name": "Vanderbilt Commodores"},
        {"seed": 12, "team_name": "Seed12"},
        {"seed": 4, "team_name": "Seed4"},
        {"seed": 13, "team_name": "Seed13"},
        {"seed": 6, "team_name": "Seed6"},
        {"seed": 11, "team_name": "Seed11"},
        {"seed": 3, "team_name": "Seed3"},
        {"seed": 14, "team_name": "Seed14"},
        {"seed": 7, "team_name": "Seed7"},
        {"seed": 10, "team_name": "Seed10"},
        {"seed": 2, "team_name": "Seed2"},
        {"seed": 15, "team_name": "Seed15"},
    ]

    seeds = {
        "South": south_seeds,
        # Provide empty regions to keep the simulator happy.
        "East": [],
        "West": [],
        "Midwest": [],
    }

    locked = [
        {"team_a": "Florida Gators", "team_b": "Vanderbilt Commodores", "winner": "Vanderbilt Commodores"}
    ]

    sim = service.simulate_bracket(seeds, simulations=10, locked_matchups=locked)
    payload = sim.model_dump()

    # Deterministic path: Sweet 16 should include Florida vs Vanderbilt.
    s16 = payload["regions"]["South"]["sweet_16"]
    assert any(
        {m["team_a"], m["team_b"]} == {"Florida Gators", "Vanderbilt Commodores"}
        for m in s16
    )

    # Locked winner should prevent Florida from appearing in Elite 8.
    e8 = payload["regions"]["South"]["elite_8"]
    assert e8, "Expected an Elite 8 matchup"
    assert "Florida Gators" not in {e8[0]["team_a"], e8[0]["team_b"]}
