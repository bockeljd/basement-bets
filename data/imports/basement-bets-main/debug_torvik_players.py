from src.services.barttorvik import BartTorvikClient
from src.database import init_player_stats_db, get_db_connection

def test_fetch():
    print("Initializing DB...")
    init_player_stats_db()
    
    client = BartTorvikClient()
    print("Fetching Player Stats...")
    # Fetch for a small window or default
    stats = client.fetch_player_stats()
    
    print(f"\nFetched {len(stats)} records.")
    if stats:
        print("Sample:", stats[0])
        
    # Verify DB
    with get_db_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM player_stats_ncaam").fetchone()[0]
        print(f"DB Count: {count}")

if __name__ == "__main__":
    test_fetch()
