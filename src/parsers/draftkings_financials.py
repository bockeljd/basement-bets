import re
from datetime import datetime
from typing import List, Dict

class DraftKingsFinancialsParser:
    def parse(self, content: str) -> List[Dict]:
        """
        Parses blocks of 3 lines:
        Type
        Date Time
        Amount
        """
        transactions = []
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        
        # Process in chunks of 3
        # Assuming perfect structure from copy-paste
        for i in range(0, len(lines), 3):
            if i + 2 >= len(lines): break
            
            typ_raw = lines[i]      # Deposit
            date_raw = lines[i+1]   # 9:26pm 10/05/24
            amt_raw = lines[i+2]    # +$1,900
            
            # Type Mapping
            typ = "Other"
            if "Deposit" in typ_raw: typ = "Deposit"
            elif "Withdrawal" in typ_raw: typ = "Withdrawal"
            
            # Amount
            amt_clean = amt_raw.replace('$','').replace(',','')
            amount = float(amt_clean)
            
            # Date Parsing: "9:26pm 10/05/24" -> "%I:%M%p %m/%d/%y"
            try:
                dt = datetime.strptime(date_raw, "%I:%M%p %m/%d/%y")
                date_iso = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                print(f"Error parsing date {date_raw}: {e}")
                date_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
            transactions.append({
                "provider": "DraftKings",
                "date": date_iso,
                "type": typ,
                "amount": amount,
                "description": f"{typ} - Manual Import",
                "transaction_id": f"MANUAL-{dt.timestamp()}-{amount}" # unique-ish ID
            })
            
        return transactions
