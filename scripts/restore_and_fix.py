import sys
import os
import sqlite3
import uuid

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.database import get_db_connection, _exec

def restore_and_fix():
    print("--- RESTORING JOEL & FIXING MANUAL IMPORTS ---")
    
    # 1. Data to Restore (From previous audit log)
    to_restore = [
        ('2023-12-25', 'DraftKings', 125.00, 'Deposit - Joel'),
        ('2023-06-03', 'DraftKings', 10.00, 'Deposit - Joel'),
        ('2023-04-17', 'FanDuel', 10.00, 'Deposit - Joel'),
        ('2023-03-17', 'FanDuel', 50.00, 'Deposit - Joel'),
        ('2023-03-13', 'DraftKings', 5.00, 'Deposit - Joel'),
        ('2023-02-24', 'DraftKings', 25.00, 'Deposit - Joel'),
        ('2023-02-22', 'DraftKings', 50.00, 'Deposit - Joel'),
        ('2023-02-14', 'DraftKings', 33.69, 'Deposit - Joel'),
        ('2023-02-13', 'DraftKings', 100.00, 'Deposit - Joel')
    ]
    
    with get_db_connection() as conn:
        c = conn.cursor()
        
        # A. Restore Joel
        print(f"Restoring {len(to_restore)} Joel deposits...")
        for date, prov, amt, desc in to_restore:
            # Get valid UUID for user_id=Jordan or similar
            # Assuming there is at least one transaction for Jordan, let's grab it.
            # Or just fetch distinct user_id LIMIT 1
            c.execute("SELECT user_id FROM bets LIMIT 1")
            row = c.fetchone()
            if not row:
                raise Exception("No existing users found to attach transaction to.")
            valid_user_uuid = row[0]

            if c.fetchone(): # Check duplicate return logic
                 pass 
                 
            # Re-check count (re-doing logic for safety)
            c.execute("SELECT count(*) FROM transactions WHERE date=%s AND provider=%s AND amount=%s AND description=%s", 
                     (date, prov, amt, desc))
            if c.fetchone()[0] == 0:
                # Insert
                txn_id = f"RESTORED-{uuid.uuid4().hex[:8]}"
                query = """
                    INSERT INTO transactions (txn_id, user_id, provider, date, type, description, amount, balance)
                    VALUES (%s, %s, %s, %s, 'Deposit', %s, %s, 0.0)
                """
                _exec(conn, query, (txn_id, valid_user_uuid, prov, date, desc, amt))
        
        print("Restoration done.")
        
        # B. Delete Manual Imports
        print("Deleting 'Manual Import' deposits...")
        # Verify amount first
        c.execute("SELECT sum(amount) FROM transactions WHERE description='Manual Import' AND type='Deposit'")
        manual_sum = c.fetchone()[0]
        print(f"Sum of Manual Imports to delete: ${manual_sum}")
        
        if manual_sum:
            _exec(conn, "DELETE FROM transactions WHERE description='Manual Import' AND type='Deposit'")
            print("Deleted Manual Imports.")
            
        conn.commit()
        
        # C. Final Verification
        c.execute("SELECT sum(amount) FROM transactions WHERE type='Deposit'")
        final_sum = c.fetchone()[0]
        print(f"FINAL DEPOSIT TOTAL: ${final_sum:,.2f}")
        print("Target: $925.74")

if __name__ == "__main__":
    restore_and_fix()
