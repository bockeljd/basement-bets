
import sys
import os
import re
from collections import defaultdict

# Add path
sys.path.append(os.getcwd())
from src.database import get_db_connection, _exec

def normalize_bet_type(raw_type):
    if not raw_type:
        return "Unknown"
        
    raw = raw_type
    norm = raw.strip()
    check = norm.lower()

    # 1. Moneyline
    if check in ["winner (ml)", "straight", "moneyline", "ml"]:
        norm = "Winner (ML)"
    
    # 2. Spread
    elif "spread" in check or "point spread" in check:
        norm = "Spread"

    # 3. Totals
    elif any(x in check for x in ["over", "under", "total"]):
        norm = "Over / Under"

    # 4. Props
    elif "prop" in check:
        norm = "Prop"

    # 5. SGP (Same Game Parlay)
    elif "sgp" in check or "same game" in check:
        norm = "SGP"

    # 6. Parlays
    elif "parlay" in check or "leg" in check or "picks" in check:
        match = re.search(r'(\d+)', check)
        if match:
            count = int(match.group(1))
            if count == 2:
                norm = "2 Leg Parlay"
            elif count == 3:
                norm = "3 Leg Parlay"
            elif count >= 4:
                norm = "4+ Parlay"
            else:
                norm = "2 Leg Parlay"
        elif "4+" in check:
            norm = "4+ Parlay"
        else:
             norm = "2 Leg Parlay" 

    return norm

def main():
    print("Normalizing Bet Types in REAL Database...")
    
    with get_db_connection() as conn:
        # 1. Select all bets
        try:
             # Standard cursor logic via _exec wrapper or direct
             # Postgres uses RealDictCursor usually via src.database context
             # Helper _exec returns cursor
             cursor = _exec(conn, "SELECT id, bet_type FROM bets")
             rows = cursor.fetchall() # List of dicts if PG, Row if Sqlite
             
             updates = 0
             stats = defaultdict(int)
             
             print(f"Processing {len(rows)} bets...")
             
             for row in rows:
                 bet_id = row['id']
                 old_type = row['bet_type']
                 new_type = normalize_bet_type(old_type)
                 
                 if old_type != new_type:
                     # Update
                     _exec(conn, "UPDATE bets SET bet_type = :matches WHERE id = :id", {"matches": new_type, "id": bet_id})
                     updates += 1
                     stats[new_type] += 1
                     
             conn.commit()
             
             print(f"Normalization Complete. Updated {updates} records.")
             print("Breakdown of upgrades:")
             for k, v in stats.items():
                 print(f"  {k}: {v}")

        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
