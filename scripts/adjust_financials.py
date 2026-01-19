
import sys
import os
import uuid
from decimal import Decimal

# Add path
sys.path.append(os.getcwd())
from src.database import get_db_connection, _exec

def main():
    print("Calculating Financial Adjustments...")
    
    # User Targets (Abs Values)
    # DraftKings: Net Dep 747.38, Net With (1,035.38)
    # Barstool: Net Dep 58.36, Net With (89.76)
    # FanDuel: Net Dep 120.00, Net With (491.34)
    # Other: Net Dep 0, Net With (210.00)
    
    targets = {
        'DraftKings': {'Deposit': 747.38, 'Withdrawal': 1035.38},
        'Barstool': {'Deposit': 58.36, 'Withdrawal': 89.76},
        'FanDuel': {'Deposit': 120.00, 'Withdrawal': 491.34},
        'Other': {'Deposit': 0.0, 'Withdrawal': 210.00}
    }
    
    with get_db_connection() as conn:
        # Get Current Totals
        # Note: withdrawals are stored as signed numbers?
        # Check check_real_db output: 
        # Txn: DraftKings Wager -10.0 (Type: Wager)
        # We only care about Type 'Deposit' and 'Withdrawal'
        
        sql = """
        SELECT provider, type, SUM(ABS(amount)) as total
        FROM transactions
        WHERE type IN ('Deposit', 'Withdrawal')
        GROUP BY provider, type
        """
        
        cursor = _exec(conn, sql)
        rows = cursor.fetchall()
        
        current = {}
        for r in rows:
            p = r['provider']
            t = r['type']
            amt = float(r['total'])
            if p not in current: current[p] = {'Deposit': 0.0, 'Withdrawal': 0.0}
            current[p][t] = amt
            
        print("Current Totals vs Targets:")
        
        adjustments = []
        
        for prov, tgt in targets.items():
            curr = current.get(prov, {'Deposit': 0.0, 'Withdrawal': 0.0})
            
            # Check Deposit
            diff_dep = tgt['Deposit'] - curr['Deposit']
            if abs(diff_dep) > 0.01:
                adjustments.append({
                    'provider': prov,
                    'type': 'Deposit',
                    'amount': diff_dep # Positive means add deposit
                })
                
            # Check Withdrawal
            # Target is 1035.38. Current is X.
            # If Target > Current, we need to ADD withdrawals.
            # In DB, Withdrawals are typically NEGATIVE signed or just marked Type=Withdrawal?
            # analytics.py sums ABS(amount) for withdrawal.
            # So I should insert a transaction with Type='Withdrawal'. 
            # The AMOUNT sign: usually Withdrawal is negative cash flow.
            # But here I'm calculating the ABSOLUTE Magnitude adjustment.
            # If I need 100 more withdrawal, I insert -100 Amount, Type=Withdrawal.
            
            diff_with = tgt['Withdrawal'] - curr['Withdrawal']
            if abs(diff_with) > 0.01:
                 # If diff is positive (need MORE withdrawal), amount should be negative?
                 # Wait.
                 # Seed script used: Withdrawal, Amount = -1035.38.
                 # So yes, Withdrawal transactions have Negative amount.
                 # If I need to increase total withdrawal magnitude by 100, I insert -100.
                 # If I have too much withdrawal (Target < Current), I need to decrease magnitude?
                 # Can I insert a POSITIVE withdrawal? That's weird.
                 # Or insert a "Contra" transaction?
                 # Let's assume standard case: User entered history, forgot some. So usually Current < Target.
                 # If Current > Target, it means duplicate entries?
                 
                 amt_to_insert = -diff_with # Increase magnitude (negative number)
                 
                 adjustments.append({
                    'provider': prov,
                    'type': 'Withdrawal',
                    'amount': amt_to_insert
                 })
                 
        print(f"Generating {len(adjustments)} adjustments...")
        
        # Get existing User ID
        cursor = _exec(conn, "SELECT user_id FROM transactions LIMIT 1")
        row = cursor.fetchone()
        if row and row['user_id']:
            target_user_id = row['user_id']
        else:
             # Fallback to random UUID if table is empty (unlikely)
             target_user_id = str(uuid.uuid4())
             
        print(f"Using User ID: {target_user_id}")
        
        ins_sql = """
        INSERT INTO transactions (txn_id, user_id, provider, date, type, amount, description, balance)
        VALUES (:txn_id, :user_id, :provider, :date, :type, :amount, :desc, :bal)
        """
        
        count = 0
        for adj in adjustments:
            if abs(adj['amount']) < 0.01: continue
            
            print(f"Adjusting {adj['provider']} {adj['type']}: {adj['amount']:.2f}")
            
            params = {
                'txn_id': str(uuid.uuid4()),
                'user_id': target_user_id,
                'provider': adj['provider'],
                'date': '2023-01-01', 
                'type': adj['type'],
                'amount': adj['amount'],
                'desc': 'Manual Adjustment - Balance Correction',
                'bal': 0.0
            }
            _exec(conn, ins_sql, params)
            count += 1
            
        conn.commit()
        print(f"Adjustments Complete. Inserted {count} transactions.")

if __name__ == "__main__":
    main()
