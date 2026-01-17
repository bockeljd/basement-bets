
import asyncio
from unittest.mock import MagicMock
from src.api import ingest_odds

async def run_test():
    print("Testing /api/ingest/odds/NCAAM ...")
    
    # Mock Request
    req = MagicMock()
    async def json_mock():
        return {"date": "20260112"} # Known historical date if available or just test flow
    req.json = json_mock
    
    try:
        # We need to mock the Fetcher inside the function? 
        # Integration test: Let it try to fetch real data (it might fail or return 0 if no games)
        # But for robustness, let's just run it. 
        # If network calls are allowed from dev env.
        
        # Actually, let's use a date that might have data or just current date
        # 2026-01-12 was used in previous tasks.
        
        resp = await ingest_odds("NCAAM", req)
        print("Response:", resp)
        
    except Exception as e:
        print(f"Test Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_test())
