import os
import sys
import datetime

# Ensure we can import src
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from src.parsers.espn_client import EspnClient

def main():
    print("Rechecking all game times for the next 4 days...")
    client = EspnClient()
    today = datetime.date.today()
    
    total_events = 0
    for i in range(4):
        target_date = today + datetime.timedelta(days=i)
        date_str = target_date.strftime('%Y%m%d')
        print(f"\n--- Fetching NCAAM Schedule for {target_date.strftime('%Y-%m-%d')} ---")
        
        # This automatically calls EventIngestionService.process_event
        # which updates events.start_time
        events = client.fetch_scoreboard('NCAAM', date=date_str)
        print(f"Ingested and updated start times for {len(events)} events.")
        total_events += len(events)
        
    print(f"\nDone! Rechecked {total_events} total game times.")

if __name__ == "__main__":
    main()
