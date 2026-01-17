
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import init_bt_team_metrics_db, upsert_team_metrics
from src.services.barttorvik import BartTorvikClient

def main():
    print("[Ingest] Initializing Torvik DB Tables...")
    init_bt_team_metrics_db()
    
    print("[Ingest] Fetching live ratings...")
    client = BartTorvikClient()
    
    # get_efficiency_ratings handles the fetch AND calls upsert_team_metrics internally if we look at service code
    # Wait, let's verify.
    # src/services/barttorvik.py: 
    #   upsert_team_metrics(metrics_payload) is called inside get_efficiency_ratings.
    # So we just need to call the method.
    
    ratings = client.get_efficiency_ratings(year=2026)
    
    if ratings:
        print(f"[Ingest] Successfully ingested {len(ratings)} teams.")
    else:
        print("[Ingest] Failed to fetch ratings.")

if __name__ == "__main__":
    main()
