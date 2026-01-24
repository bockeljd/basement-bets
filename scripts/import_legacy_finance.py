
import sys
import os
import csv
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from src.database import get_db_connection, _exec

FILE_PATH = "data/imports/legacy_financials_2023.csv"

USER_MAP = {
    "Jordan": "00000000-0000-0000-0000-000000000000",
    "Joel":   "00000000-0000-0000-0000-000000000000"
}

def parse_date(date_str):
    # 13-Feb-23 -> 2023-02-13
    try:
        dt = datetime.strptime(date_str, "%d-%b-%y")
        return dt.strftime("%Y-%m-%d")
    except:
        return None

def import_transactions():
    if not os.path.exists(FILE_PATH):
        print(f"File not found: {FILE_PATH}")
        return

    print(f"Reading {FILE_PATH}...")
    
    added = 0
    skipped = 0
    
    with get_db_connection() as conn:
        with open(FILE_PATH, 'r') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                person = row['Person'].strip()
                date_str = row['Date'].strip()
                provider = row['Agency'].strip()
                method = row['Method'].strip()
                amount_str = row['Amount'].strip()
                
                user_id = USER_MAP.get(person)
                if not user_id:
                    print(f"Unknown person {person}, skipping")
                    continue
                    
                date = parse_date(date_str)
                if not date:
                    print(f"Invalid date {date_str}, skipping")
                    continue
                    
                try:
                    amount = float(amount_str)
                except:
                    print(f"Invalid amount {amount_str}, skipping")
                    continue
                
                # Generate deterministic ID first
                clean_amt = str(amount).replace('.', '')
                txn_id = f"LEGACY-{person[:3].upper()}-{date}-{provider[:3].upper()}-{clean_amt}"
                
                # Check for existence of this SPECIFIC transaction ID
                q_check = "SELECT 1 FROM transactions WHERE txn_id = %s"
                exists = _exec(conn, q_check, (txn_id,)).fetchone()
                
                if exists:
                    skipped += 1
                else:
                    # Check suffix collision just in case (though ID includes Person)
                    if _exec(conn, "SELECT 1 FROM transactions WHERE txn_id = %s", (txn_id,)).fetchone():
                         txn_id += f"-{i}"

                    q_insert = """
                    INSERT INTO transactions (txn_id, user_id, provider, date, type, amount, description, balance)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 0.0)
                    """
                    desc = f"Legacy Import - {method} - {person}"
                    _exec(conn, q_insert, (txn_id, user_id, provider, date, method, amount, desc))
                    print(f"ADDED: {person} {date} {provider} {method} ${amount}")
                    added += 1
        
        conn.commit()
    
    print(f"\nSummary: Added {added} transactions. Skipped {skipped} duplicates.")

if __name__ == "__main__":
    import_transactions()
