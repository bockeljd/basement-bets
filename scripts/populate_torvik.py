#!/usr/bin/env python3
"""
Populate Torvik Data using BartTorvikClient.

Uses the get_efficiency_ratings() method which fetches from 
2026_team_results.json and persists to bt_team_metrics_daily.

Run locally when you need a database refresh:
  python scripts/populate_torvik.py
"""
import sys
sys.path.insert(0, '.')

from datetime import datetime
from src.services.barttorvik import BartTorvikClient
from src.utils.ncaam_season import current_ncaam_season_end_year

def main():
    season_year = current_ncaam_season_end_year()
    print("=" * 50)
    print(f"Torvik Database Populator (Season {season_year})")
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 50)
    
    client = BartTorvikClient()
    
    print("\n[STEP 1] Fetching efficiency ratings...")
    print(f"(This uses {season_year}_team_results.json and auto-persists to DB)\n")
    
    ratings = client.get_efficiency_ratings(year=season_year)
    
    if ratings:
        print("=" * 50)
        print(f"✅ Loaded {len(ratings)} teams into database")
        
        # Show sample
        print("\nSample teams:")
        for name, stats in list(ratings.items())[:5]:
            print(f"  {name}: AdjOE={stats['off_rating']:.1f}, AdjDE={stats['def_rating']:.1f}, Tempo={stats['tempo']:.1f}")
    else:
        print("=" * 50)
        print("⚠️ Could not fetch ratings (Torvik may be blocking)")


if __name__ == "__main__":
    main()
