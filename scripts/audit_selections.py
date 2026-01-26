
import sys
import os

sys.path.append(os.getcwd())

from src.database import get_db_connection

def audit_bets():
    print("--- 🕵️‍♂️ Bet Auditor Agent ---")
    issues = []
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, provider, date, description, bet_type, status, profit, wager FROM bets")
        rows = cur.fetchall()
        
        for r in rows:
            bid, prov, date, desc, btype, status, profit, wager = r
            status = status.upper().strip()
            
            # Check 1: Logical Status vs Profit
            if status in ['WON', 'WIN'] and profit <= 0:
                issues.append(f"[ID {bid}] Status WON but Profit {profit} <= 0")
            elif status in ['LOST', 'LOSE'] and profit > 0:
                 # Cashouts can be 'Lost' but have partial return? Or 'Cashed Out'.
                 # If full loss, profit should be -wager.
                 issues.append(f"[ID {bid}] Status LOST but Positive Profit {profit}")
                 
            # Check 2: 'Unknown' Fields
            if 'Unknown' in str(btype) or 'Unknown' in str(desc):
                issues.append(f"[ID {bid}] Unknown Data: Type='{btype}', Desc='{desc}'")
                
            # Check 3: Suspicious Outcomes
            # (User mentioned inaccurate outcomes)
            
    print(f"Found {len(issues)} issues:")
    for i in issues[:25]: # Limit output
        print(i)
        
    if len(issues) > 25:
        print(f"... and {len(issues)-25} more.")

if __name__ == "__main__":
    audit_bets()
