
import json
import requests
import datetime
from src.database import get_db_connection, _exec

BASE_URL = "http://localhost:8000"
API_KEY = "dummy-key" # Middleware bypass logic? 
# The middleware logic: if server_key (BASEMENT_PASSWORD) set, it checks. If not set, ignores.
# Assuming dev env has no password or we might need to set one.
# But verify_server.py usually hits /api/health directly.

def test_manual_bet():
    url = f"{BASE_URL}/api/bets/manual"
    
    # Payload for a known event match (e.g. recent NCAAM game we seeded/ingested?)
    # If no recent events, it might go to QUARANTINED, which is also a valid test.
    
    payload = {
        "sportsbook": "DK",
        "sport": "NCAAM", 
        "placed_at": datetime.datetime.now().isoformat(),
        "market_type": "MONEYLINE",
        "stake": 10.0,
        "event_name": "Test Manual Bet vs Data Loop",
        "selection": "Duke", # Common team that should have ID
        "odds": -150,
        "status": "PENDING"
    }
    
    print(f"Sending Manual Bet: {json.dumps(payload, indent=2)}")
    
    try:
        # We need to run the server first?
        # Assuming the user or I will run it.
        # But I can't run server in background easily and then script?
        # Actually I can just unit test the function via src.api import if I mock Request.
        pass
    except Exception as e:
        print(e)

# Instead of HTTP request, let's test the function directly to avoid spawning uvicorn
import asyncio
from unittest.mock import MagicMock
from src.api import save_manual_bet

async def run_direct_test():
    # Mock Request
    async def json_mock():
        return {
            "sportsbook": "DK",
            "sport": "NCAAM", 
            "placed_at": datetime.datetime.now().isoformat(),
            "market_type": "MONEYLINE",
            "stake": 10.0,
            "event_name": "Test Manual Bet vs Data Loop",
            "selection": "Duke",
            "odds": -150,
            "status": "PENDING"
        }
    
    req = MagicMock()
    req.json = json_mock
    
    import uuid
    test_uid = str(uuid.uuid4())
    user = {"sub": test_uid}
    
    print(f"Executing save_manual_bet for user {test_uid}...")
    try:
        resp = await save_manual_bet(req, user)
        print("Response:", resp)
        
        # Verify DB
        with get_db_connection() as conn:
            row = _exec(conn, "SELECT id, hash_id FROM bets WHERE user_id=:uid ORDER BY created_at DESC LIMIT 1", {"uid": test_uid}).fetchone()
            if row:
                bet_id = row[0]
                print(f"Bet Inserted: ID={bet_id}, Hash={row[1]}")
                
                leg = _exec(conn, "SELECT id, link_status, event_id FROM bet_legs WHERE bet_id = :bid", {"bid": bet_id}).fetchone()
                if leg:
                    print(f"Leg Inserted: ID={leg[0]}, LinkStatus={leg[1]}, EventID={leg[2]}")
                else:
                    print("ERROR: No Leg found!")
            else:
                print("ERROR: No Bet found!")
                
    except Exception as e:
        print(f"Execution Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_direct_test())
