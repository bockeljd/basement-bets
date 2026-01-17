
from src.services.barttorvik import BartTorvikClient
import sys
import datetime

def main():
    print(f"[{datetime.datetime.now()}] Starting BartTorvik Ingestion...")
    client = BartTorvikClient()
    
    # 1. Team Efficiency
    # Current behavior: get_efficiency_ratings actually persists to DB inside itself.
    ratings = client.get_efficiency_ratings()
    if ratings:
        print(f"Successfully ingested ratings for {len(ratings)} teams.")
    else:
        print("Failed to fetch/ingest ratings.")
        sys.exit(1)

    # 2. Daily Projections (Optional for DB per user request, but good to test fetch)
    # The client has fetch_daily_projections but doesn't persist them yet (User: "Persist: Team efficiency..."). 
    # Projections persist is optional or transient. 
    # Let's just log count.
    projections = client.fetch_daily_projections()
    print(f"Fetcher returned {len(projections)} projections for today.")

if __name__ == "__main__":
    main()
