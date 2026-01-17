
import pytest
from src.models.ncaam_model import NCAAMModel
from src.models.schemas import MarketSnapshot, Signal

def test_ncaam_v1_inputs():
    model = NCAAMModel()
    
    # Mock data directly in the model for testing
    model.team_stats = {
        "Duke": {"eff_off": 115.0, "eff_def": 95.0, "tempo": 70.0},
        "UNC": {"eff_off": 112.0, "eff_def": 98.0, "tempo": 72.0}
    }
    
    # Input
    market = MarketSnapshot(
        spread_home=-5.5,
        total_line=150.5,
        moneyline_home=-250,
        moneyline_away=200
    )
    
    # Signal (Optional)
    signals = [
        Signal(category="INJURY", target="HOME", impact_points=-1.5, confidence=0.8, description="Star PG out")
    ]
    
    # Predict
    output = model.predict_v1("Duke", "UNC", market, signals)
    
    # Verify Structure
    assert output is not None
    assert output.prediction is not None
    assert output.market_snapshot.spread_home == -5.5
    assert output.torvik_metrics.adj_oe_home == 115.0
    
    # Verify Canonicalization (Identity for now)
    assert output.market_snapshot == market
    
    # Verify Math
    # Manual Calc:
    # Blend = 4.392
    
    assert output.prediction.mu_final_margin == pytest.approx(4.392, abs=0.01)
    assert output.prediction.prob_cover < 0.5 # Expect ~0.46
