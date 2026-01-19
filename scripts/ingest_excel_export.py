import pandas as pd
import uuid
import hashlib
import sys
import os
sys.path.append(os.getcwd())
from src.database import get_db_connection, _exec
from datetime import datetime

print("Step 1: Start", flush=True)

def generate_id():
    return str(uuid.uuid4())

def generate_fingerprint(*args):
    s = "|".join(str(a) for a in args)
    return hashlib.sha256(s.encode()).hexdigest()

def ingest(filepath):
    print(f"Ingesting {filepath}...", flush=True)
    try:
        df = pd.read_excel(filepath)
    except Exception as e:
        print(f"Failed to read: {e}")
        return
        
    print(f"Rows: {len(df)}", flush=True)
    
    inserted = 0
    skipped = 0
    
    # Default User ID (Zero UUID)
    default_user_id = "00000000-0000-0000-0000-000000000000"

    with get_db_connection() as conn:
        print("[DB] Connected.", flush=True)
        for idx, row in df.iterrows():
            try:
                date_val = row['Date']
                if isinstance(date_val, str):
                    date_str = date_val
                else:
                    date_str = date_val.strftime("%Y-%m-%d")
                    
                sportsbook = row['Sportsbook']
                sport_val = str(row['Sport']).strip() if pd.notna(row['Sport']) else 'UNKNOWN'
                sport = sport_val.upper() if sport_val not in ['0', '0.0'] else 'UNKNOWN'
                
                bet_type_raw = row['Bet Type']
                bet_type = "STRAIGHT"
                if "Parlay" in str(bet_type_raw) or "SGP" in str(bet_type_raw):
                    bet_type = "PARLAY"
                    
                selection = str(row['Selection'])
                
                odds_raw = str(row['Odds']).replace("'", "").replace('+', '')
                try:
                    price = int(float(odds_raw))
                except:
                    price = -110 
                    
                wager = float(row['Wager'])
                pnl = float(row['Profit/Loss'])
                
                status_raw = str(row['Status']).upper()
                # Schema expects? 'LOSE', 'WIN'? Or 'LOST', 'WON'? 
                # Keeping normalized WIN/LOSE/VOID/PENDING usually best.
                status = "PENDING"
                if "LOST" in status_raw or "LOSE" in status_raw:
                    status = "LOSE"
                elif "WON" in status_raw or "WIN" in status_raw:
                    status = "WIN"
                elif "VOID" in status_raw:
                    status = "VOID"
                
                ins = """
                INSERT INTO bets (
                    user_id, date, sport, provider, bet_type, 
                    description, wager, profit, status, 
                    odds
                ) VALUES (
                    :uid, :date, :sport, :prov, :type,
                    :desc, :wager, :profit, :status,
                    :odds
                )
                """
                
                params = {
                    "uid": default_user_id,
                    "date": date_str,
                    "sport": sport,
                    "prov": sportsbook,
                    "type": bet_type,
                    "desc": selection,
                    "wager": wager,
                    "profit": pnl,
                    "status": status,
                    "odds": price
                }
                
                try:
                    _exec(conn, ins, params)
                    inserted += 1
                except Exception as e:
                    # Likely duplicate unique constraint
                    if "unique" in str(e).lower():
                        skipped += 1
                    else:
                        print(f"Insert Error row {idx}: {e}")
                
            except Exception as e:
                print(f"Error row {idx}: {e}")
                
        conn.commit()
    print(f"Done. Inserted: {inserted}, Skipped (Duplicate): {skipped}", flush=True)

if __name__ == "__main__":
    ingest("data/imports/bets_combined_export.xlsx")
