
import sys
import os
sys.path.append(os.getcwd())

from src.database import get_db_connection

def backfill_validation():
    print("--- Backfilling Validation Flags ---")
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        # Fetch all bets
        cur.execute("SELECT id, sport, status, profit, odds FROM bets")
        bets = cur.fetchall()
        
        updates = []
        for b in bets:
            bid, sport, status, profit, odds = b
            errors = []
            
            if sport == 'Unknown':
                errors.append("Unknown Sport")
            if status == 'WON' and profit <= 0:
                errors.append("Invalid Profit (WON <= 0)")
            if odds is None:
                errors.append("Missing Odds")
                
            if bid == 4531:
                print(f"[DEBUG] ID 4531 Errors: {errors}")
                
            val_str = ", ".join(errors) if errors else None
            
            # Add to batch if needs update
            # We update if val_str is not None OR (if existing is something, clear it? Maybe just overwrite)
            updates.append((val_str, bid))
            
        print(f"Processing {len(updates)} records...")
        
        # Batch update
        for val, bid in updates:
            cur.execute("UPDATE bets SET validation_errors = %s WHERE id = %s", (val, bid))
            
        conn.commit()
        
        # Verify 4531 immediately
        cur.execute("SELECT validation_errors FROM bets WHERE id = 4531")
        print(f"Post-Update Verify ID 4531: {cur.fetchone()}")
        
    print("Backfill Complete.")

if __name__ == "__main__":
    backfill_validation()
