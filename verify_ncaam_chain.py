
import sys
import os
import json

# Setup Path
sys.path.append(os.path.join(os.path.dirname(__file__)))

from src.services.game_analyzer import GameAnalyzer
from src.database import get_db_connection, _exec

def verify_ncaam_fix():
    print("[Verify] Starting NCAAM Chain Verification...")
    
    # 1. Inspect Scipy Dependency
    try:
        import scipy
        print(f"[Check] SciPy is installed: {scipy.__version__}")
    except ImportError:
        print("[FAIL] SciPy is NOT installed.")
        return

    # 2. Get a valid Event ID from DB
    query = "SELECT id, home_team, away_team, league FROM events WHERE league = 'NCAAM' LIMIT 1"
    evt = None
    with get_db_connection() as conn:
        evt = _exec(conn, query).fetchone()
        
    if not evt:
        print("[Verify] No NCAAM events found in DB to test.")
        # Try finding *any* event
        return

    print(f"[Check] Found Event: {evt['away_team']} @ {evt['home_team']} (ID: {evt['id']})")
    
    # 3. Run Analyzer
    analyzer = GameAnalyzer()
    try:
        print("[Verify] Calling analyze()...")
        result = analyzer.analyze(
            game_id=evt['id'],
            sport="NCAAM",
            home_team=evt['home_team'],
            away_team=evt['away_team']
        )
        
        # 4. Inspect Result Structure (The "UI Contract")
        print("\n[Result Inspection]")
        
        # Check Recommendations
        recs = result.get('recommendations')
        if isinstance(recs, list):
            print(f"[Pass] Recommendations is a list (len={len(recs)})")
            if len(recs) > 0:
                r = recs[0]
                expected_keys = ['bet_type', 'selection', 'edge', 'fair_line', 'confidence']
                missing = [k for k in expected_keys if k not in r]
                if not missing:
                    print(f"[Pass] Recommendation keys match UI contract: {r.keys()}")
                else:
                    print(f"[FAIL] Missing recommendation keys: {missing}. Got: {r.keys()}")
        else:
            print(f"[FAIL] Recommendations is NOT a list: {type(recs)}")

        # Check Narrative
        narr = result.get('narrative')
        if isinstance(narr, dict):
            expected_n_keys = ['market_summary', 'recommendation', 'rationale', 'risks']
            missing_n = [k for k in expected_n_keys if k not in narr]
            if not missing_n:
                print("[Pass] Narrative keys match UI contract.")
            else:
                print(f"[FAIL] Missing narrative keys: {missing_n}")
        else:
            print(f"[FAIL] Narrative is NOT a dict: {type(narr)}")
            
        print("\n[Verify] Analysis Persisted ID: ", result.get('id'))
        
    except Exception as e:
        print(f"[FAIL] Analysis Crashed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_ncaam_fix()
