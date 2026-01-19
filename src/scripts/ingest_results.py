import sys
import os
import argparse

# Allow running from root as 'python src/scripts/ingest_results.py'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.parsers.espn_client import EspnClient

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--league", type=str, help="Specific league to ingest (optional)")
    parser.add_argument("--date", type=str, help="Date YYYYMMDD (optional)")
    args = parser.parse_args()

    client = EspnClient()
    
    if args.league:
        leagues = [args.league]
    else:
        leagues = ['NFL', 'NCAAM', 'EPL']
        
    for league in leagues:
        print(f"[{league}] Ingesting results...")
        try:
            # fetch_scoreboard logic ingests data automatically
            events = client.fetch_scoreboard(league, date=args.date)
            print(f"[{league}] Processed {len(events)} events.")
        except Exception as e:
            print(f"[{league}] Error: {e}")

if __name__ == "__main__":
    main()
