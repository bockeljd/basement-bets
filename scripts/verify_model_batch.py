
import sys
import os
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2

def run_test():
    model = NCAAMMarketFirstModelV2()
    
    # IDs mapped from previous context
    # Michigan vs Michigan St
    # Villanova vs Providence
    # Saint Louis vs Dayton
    game_ids = [
        "action:ncaam:275042", 
        "action:ncaam:267447",
        "action:ncaam:276152"
    ]
    
    print(f"{'GAME':<30} | {'MKT':<6} | {'TORVIK':<6} | {'FAIR':<6} | {'REC':<30}")
    print("-" * 100)
    
    for gid in game_ids:
        try:
            res = model.analyze(gid)
            
            home = res.get('home_team', 'Unknown')
            away = res.get('away_team', 'Unknown')
            matchup = f"{away} @ {home}"
            
            # Debug values
            # Torvik Margin: positive = home favors, negative = away favors
            # BUT Torvik Line is usually presented as favorite minus.
            # Check inputs_json or debug
            
            inputs = json.loads(res.get('inputs_json', '{}')) if res.get('inputs_json') else {}
            torvik_margin = inputs.get('torvik', {}).get('margin')
            
            # Convert Margin to Spread for Comparison
            # Margin = Home - Away. Positive = Home Wins.
            # Spread = Away - Home (standard US). Negative = Home Favored.
            # So Spread = -Margin.
            if torvik_margin is not None:
                torvik_spread = -torvik_margin
            else:
                torvik_spread = None
            
            # Model Debug
            debug = res.get('debug', {})
            mu_market = debug.get('mu_market_spread') # or mu_market
            if mu_market is None: mu_market = debug.get('mu_market')
            
            # Check inputs for market line
            input_market = inputs.get('market_lines', {}).get('spread', {}).get('line')
            
            mu_final = debug.get('mu_spread_final') # or mu_final
            
            narrative = res.get('narrative', {}).get('recommendation', 'No Rec')
            
            # Format
            t_str = f"{torvik_spread:+.1f}" if torvik_spread is not None else "N/A"
            m_str = f"{mu_market:+.1f}" if mu_market is not None else (f"{input_market:+.1f}?" if input_market else "N/A")
            f_str = f"{mu_final:+.1f}" if mu_final is not None else "N/A"
            
            print(f"{matchup:<30} | {m_str:<6} | {t_str:<6} | {f_str:<6} | {narrative:<30}")
            
        except Exception as e:
            print(f"Error analyzing {gid}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    run_test()
