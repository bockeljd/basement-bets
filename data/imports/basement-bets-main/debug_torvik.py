import sys
import os
sys.path.append(os.path.abspath("."))
from src.services.barttorvik import BartTorvikClient
# Correct import
from src.services.barttorvik import BartTorvikClient

def test_ratings():
    client = BartTorvikClient()
    # Use 2026 or 2025? Torvik uses ending year.
    # Current date is 2026-01-14. So we are in 2026 season.
    ratings = client.get_efficiency_ratings(year=2026)
    
    print(f"Fetched ratings for {len(ratings)} teams.")
    if ratings:
        # Print top 5 keys
        keys = list(ratings.keys())[:5]
        for k in keys:
            print(f"{k}: {ratings[k]}")
            
        # Check specific teams
        check_teams = ["Duke", "Kansas", "North Carolina", "UConn"]
        for t in check_teams:
            # Fuzzy check or exact
            found = False
            for k in ratings:
                if t in k:
                    print(f"Found {t} as '{k}': {ratings[k]}")
                    found = True
                    break
            if not found:
                print(f"Could not find {t}")

if __name__ == "__main__":
    test_ratings()
