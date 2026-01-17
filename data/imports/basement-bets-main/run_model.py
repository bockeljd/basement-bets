import argparse
from src.models.monte_carlo import MonteCarloEngine
from src.services.nfl_service import NFLService
from src.services.barttorvik import BartTorvikClient

def run_nfl_model(sims=10000):
    print("\n=== Running NFL Monte Carlo Model ===")
    eng = MonteCarloEngine(simulations=sims)
    svc = NFLService()
    
    # 1. Fetch Stats
    print("[1/3] Fetching Team Stats...")
    epa_map = svc.get_team_epa(2024)
    vol_map = svc.get_team_volatility(2024)
    
    if not epa_map or not vol_map:
        print("Error: Could not fetch valid stats.")
        # return # Proceed for demo with mocks?
    
    # 2. Define Matchups (Mock or Real)
    # Ideally fetch from generic schedule service.
    # For demonstration, let's hardcode today's hypothetical or recent matchups.
    matchups = [
        {"home": "KC", "away": "BUF", "spread": -2.5, "total": 48.5},
        {"home": "BAL", "away": "HOU", "spread": -9.5, "total": 45.0},
        {"home": "SF", "away": "GB", "spread": -10.0, "total": 50.5},
        {"home": "DET", "away": "TB", "spread": -6.5, "total": 49.0}
    ]
    
    # 3. Simulate
    print(f"[2/3] Simulating {len(matchups)} games ({sims} runs each)...")
    for m in matchups:
        h = m['home']
        a = m['away']
        
        # Get Stats (Default if missing)
        h_stats = epa_map.get(h, {'off_epa': 0.05, 'def_epa': 0.0})
        a_stats = epa_map.get(a, {'off_epa': 0.05, 'def_epa': 0.0})
        
        h_vol = vol_map.get(h, 10.0)
        a_vol = vol_map.get(a, 10.0)
        
        # Calculate Projected Score (Interaction Formula)
        # Assuming 64 plays tempo standard for NFL
        tempo = 64
        h_proj = eng.calculate_interaction(h_stats['off_epa'], a_stats['def_epa'], 0.0, tempo, is_epa=True)
        a_proj = eng.calculate_interaction(a_stats['off_epa'], h_stats['def_epa'], 0.0, tempo, is_epa=True)
        
        # Run Sim
        res = eng.simulate_game(h_proj, h_vol, a_proj, a_vol, m['spread'], m['total'])
        
        # Output
        print(f"\nMatchup: {a} @ {h} (Line: {m['spread']}, Total: {m['total']})")
        print(f"  Model Fair Line: {res.fair_spread} | Win%: {res.home_win_pct}%")
        print(f"  Model Fair Total: {res.fair_total}")
        
        if res.edge_detected:
            # Determine side
            # Vegas -2.5 (Home favored by 2.5). Fair -6.0 (Favored by 6).
            # Edge on Home.
            # Vegas -2.5. Fair +1.0 (Home underdog). Edge on Away.
            
            # Simple check:
            # Model says Home Margin is X (e.g. +6 means win by 6).
            # Vegas says Home Margin is Y (e.g. +2.5).
            # Edge = Model - Vegas? 
            # Margin convention: Positive = Home Win.
            # Spread convention: Negative = Home Fav.
            # Let's use Margin.
            # Vegas Implied Margin = -Spread.
            # Model Margin = avg_home - avg_away.
            
            pass # Printed in res
            print(f"  *** EDGE DETECTED ***")
            
        if res.volatility_edge:
             print(f"  *** VOLATILITY EDGE (OVER) ***")

def run_cbb_model(sims=10000):
    print("\n=== Running NCAAM Monte Carlo Model ===")
    eng = MonteCarloEngine(simulations=sims)
    client = BartTorvikClient()
    
    # 1. Fetch Stats
    ratings = client.get_efficiency_ratings(2026)
    
    if not ratings:
        print("Error: No ratings found.")
        return

    # 2. Matchups (Mock)
    matchups = [
        {"home": "Michigan", "away": "Duke", "spread": -4.0, "total": 145.5},
        {"home": "Kansas", "away": "Houston", "spread": -1.5, "total": 138.0}
    ]
    
    for m in matchups:
        h = m['home']
        a = m['away']
        
        h_stats = ratings.get(h)
        a_stats = ratings.get(a)
        
        if not h_stats or not a_stats:
            print(f"Skipping {a}@{h} (Missing stats)")
            continue
            
        # Volatility (Default)
        h_vol = 10.5
        a_vol = 10.5
        
        # Interactions
        # Tempo is avg of both?
        game_tempo = (h_stats['tempo'] + a_stats['tempo']) / 2.0
        
        # AdjOE vs AdjDE
        # League Avg Eff ~ 106.0? 
        # Torvik's AdjOE is usually normalized to D1 avg. 
        # Let's assume 100 or checkTorvik avg.
        # Actually 2026 stats showed ~100-110.
        league_avg = 106.0 
        
        h_proj = eng.calculate_interaction(h_stats['off_rating'], a_stats['def_rating'], league_avg, game_tempo)
        a_proj = eng.calculate_interaction(a_stats['off_rating'], h_stats['def_rating'], league_avg, game_tempo)
        
        res = eng.simulate_game(h_proj, h_vol, a_proj, a_vol, m['spread'], m['total'])
        
        print(f"\nMatchup: {a} @ {h}")
        print(f"  Model: {h} {res.home_score_avg:.1f} - {a} {res.away_score_avg:.1f}")
        print(f"  Fair Line: {res.fair_spread} (Vegas: {m['spread']})")
        print(f"  Fair Total: {res.fair_total} (Vegas: {m['total']})")
        
        if res.edge_detected:
            print("  *** EDGE ***")
        if res.volatility_edge:
            print("  *** HIGH VOLATILITY OVER ***")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--sport', type=str, default='all')
    args = parser.parse_args()
    
    if args.sport in ['all', 'nfl']:
        run_nfl_model()
    if args.sport in ['all', 'cbb', 'ncaam']:
        run_cbb_model()
