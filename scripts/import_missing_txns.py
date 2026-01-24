
import sys
import os
import re
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from src.database import get_db_connection, _exec

FILE_PATH = "data/imports/manual_history_additions.txt"

def parse_line(line):
    # Split by tab or multiple spaces
    parts = re.split(r'\t+', line.strip())
    if len(parts) < 4:
        return None
    
    date_str, provider, type_str, amount_str = parts[0], parts[1], parts[2], parts[3]
    
    # Clean amount: "$ (63.69)" -> -63.69, "$ 100.00" -> 100.00
    amount_str = amount_str.replace('$', '').replace(',', '').strip()
    is_negative = False
    if '(' in amount_str and ')' in amount_str:
        is_negative = True
        amount_str = amount_str.replace('(', '').replace(')', '')
    
    try:
        amount = float(amount_str)
        if is_negative:
            amount = -amount
    except:
        return None

    # Parse date: 13-Feb-23 -> 2023-02-13
    try:
        dt = datetime.strptime(date_str, "%d-%b-%y")
        iso_date = dt.strftime("%Y-%m-%d")
    except:
        return None

    return {
        "date": iso_date,
        "provider": provider.strip(),
        "type": type_str.strip(),
        "amount": amount,
        "description": f"Manual Import - {type_str} - {provider}"
    }

def import_transactions():
    if not os.path.exists(FILE_PATH):
        print(f"File not found: {FILE_PATH}")
        return

    print(f"Reading {FILE_PATH}...")
    with open(FILE_PATH, 'r') as f:
        lines = f.readlines()

    added = 0
    skipped = 0
    
    with get_db_connection() as conn:
        # Get a fallback user_id
        user_id = "00000000-0000-0000-0000-000000000000"
        try:
            r = _exec(conn, "SELECT user_id FROM bets LIMIT 1").fetchone()
            if r: user_id = r['user_id']
        except: pass

        for i, line in enumerate(lines):
            if i == 0 and "Date" in line: continue # Skip header
            if not line.strip(): continue
            
            txn = parse_line(line)
            if not txn:
                print(f"Skipping invalid line {i+1}: {line.strip()}")
                continue
            
            # Check for existence using txn_id column
            q_check = """
            SELECT txn_id FROM transactions 
            WHERE provider = %s 
              AND type = %s 
              AND date = %s 
              AND ABS(amount - %s) < 0.01
            """
            exists = _exec(conn, q_check, (txn['provider'], txn['type'], txn['date'], txn['amount'])).fetchone()
            
            if exists:
                skipped += 1
            else:
                # Generate deterministic ID
                # Clean amount for ID
                amt_clean = str(txn['amount']).replace('.', '')
                txn_id = f"MANUAL-{txn['date']}-{txn['provider'][:3].upper()}-{amt_clean}"
                
                # Check if specific ID exists (collision avoidance)
                if _exec(conn, "SELECT 1 FROM transactions WHERE txn_id = %s", (txn_id,)).fetchone():
                    txn_id += f"-{i}"

                q_insert = """
                INSERT INTO transactions (txn_id, user_id, provider, date, type, amount, description, balance)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 0.0)
                """
                _exec(conn, q_insert, (txn_id, user_id, txn['provider'], txn['date'], txn['type'], txn['amount'], txn['description']))
                print(f"ADDED: {txn['date']} {txn['provider']} {txn['type']} ${txn['amount']}")
                added += 1
        
        conn.commit()
    
    print(f"\nSummary: Added {added} transactions. Skipped {skipped} duplicates.")

if __name__ == "__main__":
    import_transactions()
