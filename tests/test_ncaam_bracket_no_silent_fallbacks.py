import pytest
from src.services.ncaam_tournament_service import NCAAMTournamentPredictionService, TournamentGameInput, SimulatorDataError

def test_strict_error_on_missing_team():
    """
    Ensure the bracket simulator does NOT silently fallback to
    50% win probability and 145.0 totals for fabricated teams.
    It should explicitly raise a SimulatorDataError.
    """
    service = NCAAMTournamentPredictionService()
    
    gi = TournamentGameInput(
        team_a="Duke",
        team_b="Fake University of Data",
        round_index=0,
        neutral_site=True
    )
    
    with pytest.raises(SimulatorDataError) as exc_info:
        service.predict_game(gi)
        
    assert "Failed to predict" in str(exc_info.value) or "Missing core data" in str(exc_info.value)
