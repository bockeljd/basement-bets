import os
from dotenv import load_dotenv
load_dotenv()

# Force Postgres via Env if not set (though .env should have it)
# os.environ['DATABASE_URL'] = ... (already in .env)

try:
    from src.database import init_db, fetch_all_bets
    from src.analytics import AnalyticsEngine
    
    print("1. Testing DB Init...")
    init_db()
    print("   Init Success.")
    
    print("2. Testing Fetch Bets...")
    bets = fetch_all_bets()
    print(f"   Fetched {len(bets)} bets.")
    
    print("3. Testing Analytics Engine Initialization...")
    engine = AnalyticsEngine()
    print("   Engine Init Success.")
    
    print("4. Testing Summary...")
    summary = engine.get_summary()
    print(f"   Summary: {summary}")
    
    print("5. Testing Financials...")
    fin = engine.get_financial_summary()
    print(f"   Financials: {fin}")
    
    print("PASSED ALL CHECKS")

except Exception as e:
    print("\nFAILED WITH ERROR:")
    import traceback
    traceback.print_exc()
