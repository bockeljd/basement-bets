import sys
import os

# Ensure src is in path
sys.path.append(os.path.abspath("."))

from src.models.ncaam_model import NCAAMModel
from src.services.grading_service import GradingService

def test_ncaam_edges():
    print("\n--- Testing NCAAMModel.find_edges ---")
    model = NCAAMModel()
    try:
        edges = model.find_edges()
        print(f"Found {len(edges)} edges.")
        for e in edges[:3]:
            print(f"  {e['home_team']} vs {e['away_team']}: {e['bet_on']} {e['market_line']} (Edge: {e['edge']:.1%})")
    except Exception as e:
        print(f"Error in find_edges: {e}")
        import traceback
        traceback.print_exc()

def test_grading_logic():
    print("\n--- Testing GradingService ---")
    service = GradingService()
    
    # We can try to run grade_predictions directly if DB has pending bets
    # Or mock one.
    try:
        res = service.grade_predictions()
        print(f"Grade Result: {res}")
    except Exception as e:
        print(f"Error in grading: {e}")
        import traceback
        traceback.print_exc()

from src.database import get_db_connection, _exec

def clear_cache():
    print("Clearing API Cache...")
    with get_db_connection() as conn:
        _exec(conn, "DELETE FROM api_cache")
        conn.commit()
    print("Cache Cleared.")

if __name__ == "__main__":
    clear_cache()
    test_ncaam_edges()
    test_grading_logic()
