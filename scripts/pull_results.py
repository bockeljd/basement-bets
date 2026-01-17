
import sys
import os
import datetime

# Ensure root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.espn_client import EspnClient
# from src.football_data_client import FootballDataClient # If implemented for EPL

def pull_results():
    print("--- Starting Daily Results Ingestion ---")
    
    # 1. ESPN Ingestion (NFL, NCAAM, EPL via ESPN?)
    # EspnClient has LEAGUES map including EPL -> 'soccer/eng.1'
    client = EspnClient()
    
    # Ingest Yesterday and Today
    today = datetime.datetime.now()
    yesterday = today - datetime.timedelta(days=1)
    
    dates = [yesterday, today]
    
    for date in dates:
        print(f"\nProcessing Date: {date.strftime('%Y-%m-%d')}")
        
        # NFL
        client.ingest_nfl(date=date)
        
        # NCAAM
        client.ingest_ncaam(date=date)
        
        # EPL (via ESPN)
        client.ingest_league('EPL', date=date)
        
        # NBA (Optional but listed in LEAGUES)
        client.ingest_league('NBA', date=date)

    print("\n--- Daily Results Ingestion Complete ---")

if __name__ == "__main__":
    pull_results()
