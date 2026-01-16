from src.models.nfl_model import NFLModel
from src.models.ncaam_model import NCAAMModel
from src.models.epl_model import EPLModel
import numpy as np

def test_nfl_deterministic():
    model = NFLModel()
    # Chiefs (92.5) @ 49ers (91.0)
    # Predicted Margin = (92.5 - 91.0) + 1.8 = 3.3
    # Fair Spread = round(-3.3 * 2) / 2 = -3.5
    res = model.predict("test_nfl", "Kansas City Chiefs", "San Francisco 49ers", market_spread=-2.5)
    print(f"NFL Test (Chiefs vs 49ers): Fair Spread {res['fair_spread']}, Win Prob {res['win_prob']:.4f}")
    assert res['fair_spread'] == -3.5
    assert 0.5 < res['win_prob'] < 0.6 # Prob to beat -2.5 given margin 3.3

def test_ncaam_deterministic():
    model = NCAAMModel()
    # Houston (Eff: 118.5/87.0, Tempo: 63.5) @ Purdue (Eff: 126.0/95.0, Tempo: 66.5)
    # Possessions = (63.5 * 66.5) / 68.5 = 61.64
    # Houston Pts (Off: 118.5 vs Def: 95.0) = (118.5 * 95.0 / 105.0) * (61.64 / 100) = 107.2 * 0.6164 = 66.07
    # Purdue Pts (Off: 126.0 vs Def: 87.0) = (126.0 * 87.0 / 105.0) * (61.64 / 100) = 104.4 * 0.6164 = 64.35
    # Fair Total = 130.42
    res = model.predict("test_ncaam", "Purdue Boilermakers", "Houston Cougars", market_total=135.5)
    print(f"NCAAM Test (Houston @ Purdue): Fair Total {res['fair_total']}, Win Prob (Over) {res['win_prob']:.4f}")
    assert abs(res['fair_total'] - 130.5) < 0.1
    assert res['win_prob'] < 0.5 # Total 130.5 < 135.5

def test_epl_deterministic():
    model = EPLModel()
    # Man City (Att: 2.4, Def: 0.8) vs Liverpool (Att: 2.2, Def: 0.9)
    # Home Lambda = (2.4 * 0.9) / 1.6 = 1.35
    # Away Lambda = (2.2 * 0.8) / 1.6 = 1.10
    res = model.predict("test_epl", "Manchester City", "Liverpool")
    print(f"EPL Test (Man City vs Liverpool): Home Win Prob {res['win_prob_home']:.4f}")
    assert res['win_prob_home'] > 0.4
    assert res['win_prob_home'] < 0.6

if __name__ == "__main__":
    print("Running Deterministic Model Acceptance Tests...")
    test_nfl_deterministic()
    test_ncaam_deterministic()
    test_epl_deterministic()
    print("All Model Acceptance Tests Passed!")
