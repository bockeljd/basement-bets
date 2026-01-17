
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.models.ncaam_model import NCAAMModel
from src.models.schemas import MarketSnapshot, Signal

def test_v1_logic():
    print("Initializing Model...")
    model = NCAAMModel()
    
    # Mock Data
    from datetime import datetime
    model.last_loaded = datetime.now().strftime("%Y-%m-%d")
    model.team_stats = {
        "Duke": {"eff_off": 118.0, "eff_def": 94.0, "tempo": 67.0},
        "North Carolina": {"eff_off": 115.0, "eff_def": 96.0, "tempo": 70.0}
    }
    
    # Scenario: Duke (Home) vs UNC (Away)
    # Duke is slightly better (+3 eff margin approx). HFA +3.2.
    # Total eff is high. Tempo is average-ish.
    
    market = MarketSnapshot(
        spread_home=-4.5, # Market likes Duke by 4.5
        total_line=152.0
    )
    
    print(f"\n[INPUT] Market: Duke -4.5, Total 152.0")
    print(f"[INPUT] Stats: Duke (118/94), UNC (115/96)")
    
    # Run Prediction
    snapshot = model.predict_v1("Duke", "North Carolina", market)
    
    if snapshot:
        pred = snapshot.prediction
        comps = snapshot.components
        print("\n--- RESULTS ---")
        print(f"Projected Score: Duke {pred.score_home:.1f} - UNC {pred.score_away:.1f}")
        print(f"Fair Margin: {pred.mu_final_margin:.2f} (Torvik: {comps.mu_torvik:.2f}, Market: {comps.mu_market:.2f})")
        print(f"Fair Total: {pred.mu_final_total:.2f} (Torvik: {comps.mu_torvik_total if hasattr(comps, 'mu_torvik_total') else 'N/A'}, Market: {market.total_line})")
        print(f"Delta Margin: {comps.delta:.2f}")
        print(f"Prob Cover (-4.5): {pred.prob_cover:.1%}")
        print(f"Prob Over (152.0): {pred.prob_over:.1%}")
        
    else:
        print("Prediction Failed.")

if __name__ == "__main__":
    test_v1_logic()
