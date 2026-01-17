import sys
import os
import csv
import json

# Ensure src is in path
sys.path.append(os.path.abspath("."))

from src.database import get_db_connection

from datetime import datetime

def load_db_transactions():
    query = "SELECT txn_id, provider, date, amount, type, description FROM transactions"
    txns = []
    with get_db_connection() as conn:
        try:
           # PG compatible fetch
           cur = conn.cursor()
           cur.execute(query)
           cols = [d[0] for d in cur.description]
           rows = cur.fetchall()
           for r in rows:
               txns.append(dict(zip(cols, r)))
        except Exception as e:
            print(f"[DB] Error: {e}")
    return txns

def parse_legacy_date(date_str):
    # Format: 13-Feb-23
    try:
        dt = datetime.strptime(date_str, "%d-%b-%y")
        return dt.strftime("%Y-%m-%d")
    except:
        return date_str

def audit_legacy_csv():
    path = "data/imports/legacy_financials_2023.csv"
    if not os.path.exists(path):
        return []
    
    print(f"\n--- Auditing {path} ---")
    rows = []
    with open(path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
             # Normalize
             amt_str = row.get('Amount', '0').replace('$','').replace(',','')
             try:
                 amt = float(amt_str)
             except:
                 amt = 0.0
             
             date_raw = row.get('Date', '')
             date_norm = parse_legacy_date(date_raw)
             
             rows.append({
                 "date": date_norm,
                 "amount": amt,
                 "desc": f"{row.get('Method')} - {row.get('Person')}", # Approx desc match
                 "raw": str(row)
             })
    print(f"Found {len(rows)} source rows.")
    return rows

def audit_manual_dk():
    path = "data/imports/dk_financials_manual.txt"
    if not os.path.exists(path):
        return []
        
    print(f"\n--- Auditing {path} ---")
    items = []
    with open(path, 'r') as f:
        lines = [l.strip() for l in f if l.strip()]
        
    # Chunk by 3
    # Deposit, 9:21pm 10/05/24, +$100
    i = 0
    while i < len(lines):
        try:
            typ = lines[i]
            if i+2 >= len(lines): break
            date_raw = lines[i+1] # 9:21pm 10/05/24
            amt_raw = lines[i+2] # +$100 or -$200
            
            # Parse Date: 10/05/24
            # We only really care about YYYY-MM-DD for matching often
            # But DB might store full time? Let's try matching Day first.
            try:
                # Extract date part 10/05/24
                # 9:21pm 10/05/24
                parts = date_raw.split(' ')
                d_part = parts[-1]
                dt = datetime.strptime(d_part, "%m/%d/%y")
                date_norm = dt.strftime("%Y-%m-%d")
            except:
                date_norm = date_raw
            
            # Parse Amount
            try:
                clean_amt = amt_raw.replace('$','').replace('+','').replace(',','')
                amt = float(clean_amt)
            except:
                amt = 0.0
                
            # If line 1 was regex 'Withdrawal', ensure amt is negative?
            # txt has -$200 so float is -200. +$100 is 100.
            
            items.append({
                "date": date_norm,
                "amount": amt,
                "desc": "Manual Import",
                "raw": f"{typ} {date_raw} {amt_raw}"
            })
            
            i += 3
        except:
            i += 1
            
    print(f"Parsed {len(items)} manual items.")
    return items

def verify_db_contains(source_name, source_items, db_txns):
    print(f"\n[Validation] Checking if DB contains items from {source_name}...")
    
    # Create a mutable list of DB txns to "consume" matches (handle duplicates)
    # Filter DB txns to relevant ones? Or keep all.
    
    # We need to match Date (YYYY-MM-DD) and Amount (Float)
    # DB Date is "YYYY-MM-DD HH:MM:SS" or similar.
    
    db_pool = []
    for t in db_txns:
        try:
            d_str = str(t['date']).split('T')[0].split(' ')[0]
            amt = float(t['amount'])
            db_pool.append({'id': t['txn_id'], 'date': d_str, 'amount': amt, 'matched': False, 'desc': t.get('description','')})
        except: pass
        
    matched_count = 0
    missing_items = []
    
    for item in source_items:
        src_date = item['date']
        src_amt = item['amount']
        
        found_idx = -1
        
        # 1. Exact Match (Date + Amount)
        for idx, db_t in enumerate(db_pool):
            if not db_t['matched']:
                if db_t['date'] == src_date and abs(db_t['amount'] - src_amt) < 0.01:
                    found_idx = idx
                    break
        
        if found_idx != -1:
            db_pool[found_idx]['matched'] = True
            matched_count += 1
        else:
            missing_items.append(item)

    print(f"  Matched: {matched_count} / {len(source_items)}")
    
    if missing_items:
        print(f"  WARNING: {len(missing_items)} MISSING items:")
        for m in missing_items[:10]:
            print(f"    Missing: {m['date']} | {m['amount']} | {m['desc']}")
    else:
        print(f"  SUCCESS: All items from {source_name} accounted for in DB.")

if __name__ == "__main__":
    db_txns = load_db_transactions()
    print(f"Loaded {len(db_txns)} transactions from DB.")
    
    # 1. Audit Legacy CSV
    legacy_rows = audit_legacy_csv()
    if legacy_rows:
        verify_db_contains("Legacy CSV", legacy_rows, db_txns)
        
    # 2. Audit Manual DK
    dk_rows = audit_manual_dk()
    if dk_rows:
        verify_db_contains("Manual DK TXT", dk_rows, db_txns)

