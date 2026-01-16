import sys
import os
import json

# Ensure root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_db_connection, _exec

def settlement_report():
    print("--- Settlement Reconciliation Report ---")
    
    with get_db_connection() as conn:
        # 1. Settled vs Pending Stats
        pending = _exec(conn, "SELECT COUNT(*) FROM bet_legs WHERE status = 'PENDING'").fetchone()[0]
        settled = _exec(conn, "SELECT COUNT(*) FROM bet_legs WHERE status != 'PENDING'").fetchone()[0]
        
        print(f"\nLegs Status:")
        print(f"  PENDING: {pending}")
        print(f"  SETTLED: {settled}")
        
        # 2. Unlinked Legs (Missing Event)
        unlinked = _exec(conn, "SELECT COUNT(*) FROM bet_legs WHERE event_id IS NULL AND status = 'PENDING'").fetchone()[0]
        print(f"  UNLINKED: {unlinked} (Cannot be settled)")
        
        # 3. Missing Results (Linked but no game_result)
        # Count legs where event_id is NOT NULL but game_results is missing/final=false
        query_missing_res = """
        SELECT COUNT(*) 
        FROM bet_legs l
        JOIN events_v2 e ON l.event_id = e.id
        LEFT JOIN game_results r ON e.id = r.event_id
        WHERE l.status = 'PENDING'
          AND (r.final IS NULL OR r.final = FALSE)
        """
        missing_res = _exec(conn, query_missing_res).fetchone()[0]
        print(f"  WAITING FOR RESULT: {missing_res}")
        
        # 4. Grading Conflicts / Errors in Queue
        queue = _exec(conn, "SELECT COUNT(*) FROM unmatched_legs_queue").fetchone()[0]
        print(f"\nUnmatched Queue Size: {queue}")
        
        # 5. Settlement Events Summary
        events = _exec(conn, "SELECT outcome, COUNT(*) FROM settlement_events GROUP BY outcome").fetchall()
        print("\nSettlement Outcomes (Historical):")
        for row in events:
            print(f"  {row[0]}: {row[1]}")

if __name__ == "__main__":
    settlement_report()
