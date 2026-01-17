from src.services.grading_service import GradingService
from src.database import fetch_model_history
import json

def debug_grading():
    service = GradingService()
    history = fetch_model_history()
    
    # Filter for 1/13 NCAAM pending
    pending_113 = [p for p in history if p['sport'] == 'NCAAM' and '2026-01-13' in str(p['date']) and p['result'] == 'Pending']
    
    if not pending_113:
        print("No pending 1/13 NCAAM games found.")
        return

    print(f"Found {len(pending_113)} pending 1/13 NCAAM games.")
    
    # Fetch scores
    scores = service.client.get_scores('basketball_ncaab', days_from=3)
    print(f"Fetched {len(scores)} scores.")
    
    print("\nAvailable games in score data:")
    for s in scores:
        print(f"  {s.get('away_team')} @ {s.get('home_team')} ({s.get('commence_time')})")
    
    for p in pending_113:
        print(f"\nEvaluating: {p['matchup']} ({p['date']})")
        res = service._evaluate_prediction(p, scores)
        print(f"Result: {res}")

if __name__ == "__main__":
    debug_grading()
