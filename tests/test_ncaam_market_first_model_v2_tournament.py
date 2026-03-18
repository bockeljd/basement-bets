from datetime import datetime

import pytest

from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2


class _TorvikStub:
    def __init__(self, margin: float, total: float = 150.0):
        self._margin = margin
        self._total = total

    def get_projection(self, team_a, team_b, date=None, conn=None):
        # In the model code, mu_base_spread = -(torvik_view['margin']).
        return {"lean": "A", "margin": self._margin, "total": self._total}

    def get_matchup_team_stats(self, team_a, team_b, date=None):
        return {"game_tempo": 68.0}


class _KenPomStub:
    def calculate_kenpom_adjustment(self, team_a, team_b, conn=None):
        # Return None so the model uses Torvik spread directly (no blending)
        return None


class _TournamentFeaturesStub:
    def get_tournament_modifiers(self, team, conn=None):
        return {
            "luck_adj_points": 0,
            "continuity_adj_points": 0,
            "turnover_adj_points": 0,
            "q1_adj_points": 0,
            "variance_multiplier": 1.0,
            "upset_risk_score": 0,
        }


@pytest.mark.parametrize(
    "mu_spread_final, expected_winner_side",
    [
        (-23.0, "team_a"),  # team_a heavily favored
        (23.0, "team_b"),   # team_b heavily favored
    ],
)
def test_tournament_win_prob_directionality(mu_spread_final, expected_winner_side):
    model = NCAAMMarketFirstModelV2()

    # Choose torvik margin such that mu_base_spread = -(margin) == mu_spread_final
    # (no modifiers, no market blending)
    torvik_margin = -mu_spread_final

    model.torvik_service = _TorvikStub(margin=torvik_margin)
    model.kenpom_client = _KenPomStub()
    model.tournament_features = _TournamentFeaturesStub()

    res = model.analyze_tournament_game(
        team_a="Duke Blue Devils",
        team_b="Siena Saints",
        event_context={"start_time": datetime.utcnow()},
        market_snapshot=None,
        persist=False,
        neutral_site=True,
        conn=None,
    )

    assert res["projected_spread_a"] == round(mu_spread_final, 2)
    assert res["winner_side"] == expected_winner_side

    if expected_winner_side == "team_a":
        assert res["win_prob_a"] > 50.0
        assert res["win_prob_b"] < 50.0
    else:
        assert res["win_prob_b"] > 50.0
        assert res["win_prob_a"] < 50.0
