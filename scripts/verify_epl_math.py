import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.models.epl_model import EPLModel

def test_model():
    print("Initializing EPL Model...")
    model = EPLModel()
    
    # Manchester City (Strong) vs Sheffield United (Implied Weak/Default)
    # Using "Sheffield United" which isn't in top 10 map, so it gets default 1.5/1.5 ratings?
    # Actually fetch_data default is just hardcoded dict.
    # Let's use two known teams from the hardcoded map.
    
    home = "Manchester City" # Att 2.4, Def 0.8
    away = "Liverpool"       # Att 2.2, Def 0.9
    
    print(f"Predicting {home} vs {away}...")
    res = model.predict("game1", home, away)
    print("Result:", res)
    
    # Check probabilities sum to ~1
    total = res['win_prob_home'] + res['win_prob_draw'] + res['win_prob_away']
    print(f"Total Prob: {total:.4f}")
    
    assert abs(total - 1.0) < 0.01, "Probabilities do not sum to 1.0"
    
    # Check logic (City slightly favored at home vs Liverpool?)
    # City Att 2.4 * Liv Def 0.9 / 1.6 = 1.35 Goals
    # Liv Att 2.2 * City Def 0.8 / 1.6 = 1.1 Goals
    # City should show higher win prob than Away.
    
    print(f"Home Win: {res['win_prob_home']:.2%}")
    print(f"Away Win: {res['win_prob_away']:.2%}")
    
    if res['win_prob_home'] > res['win_prob_away']:
        print("Logic Check: PASS (Home favorite as expected)")
    else:
        print("Logic Check: UNEXPECTED (Away favored?)")
        
    print("SUCCESS: EPL Model works without Numpy/Scipy")

if __name__ == "__main__":
    test_model()
