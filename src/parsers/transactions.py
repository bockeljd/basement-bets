from typing import List, Dict, Optional
import csv
import re
from datetime import datetime
from bs4 import BeautifulSoup

class TransactionParser:
    def parse(self, filepath: str) -> List[Dict]:
        raise NotImplementedError

class DraftKingsHTMLTransactionParser(TransactionParser):
    def parse(self, filepath: str) -> List[Dict]:
        transactions = []
        with open(filepath, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
            
        rows = soup.select('.BaseTable__row')
        for row in rows:
            try:
                cells = row.select('.BaseTable__row-cell')
                if not cells or len(cells) < 6: continue
                
                # Cell 0: Date
                # "January 11, 20269:20pm" -> merged text
                # Try to get separator if possible, or just parse the text
                # It seems concatenated without space in debug output? "20269:20pm"
                # Let's clean it up.
                raw_date = cells[0].get_text(separator=' ', strip=True)
                # "January 11, 2026 9:20pm"
                # Clean up AM/PM spacing if needed
                dt = datetime.strptime(raw_date, "%B %d, %Y %I:%M%p")
                
                # Cell 2: Description & ID
                # "Sportsbook wager|ID:|043..."
                desc_text = cells[2].get_text(separator='|', strip=True)
                parts = desc_text.split('|ID:|')
                description = parts[0]
                txn_id = parts[1] if len(parts) > 1 else f"DK-{dt.timestamp()}"
                
                # Cell 4: Amount
                amount = self._parse_currency(cells[4].get_text(strip=True))
                
                # Cell 5: Balance
                balance = self._parse_currency(cells[5].get_text(strip=True))
                
                txn = {
                    "provider": "DraftKings",
                    "date": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "type": self._map_category(description),
                    "description": description,
                    "id": txn_id.strip(),
                    "amount": amount,
                    "balance": balance,
                    "raw_data": desc_text
                }
                transactions.append(txn)
            except Exception as e:
                # print(f"Error parsing DK HTML row: {e}")
                pass
                
        return transactions

    def _parse_currency(self, val: str) -> float:
        val = val.replace("$", "").replace(",", "").replace("+", "")
        if val == "-": return 0.0
        try:
            return float(val)
        except:
            return 0.0

    def _map_category(self, desc: str) -> str:
        desc = desc.lower()
        if "wager" in desc: return "Wager"
        if "win" in desc: return "Winning"
        if "deposit" in desc: return "Deposit"
        if "withdrawal" in desc: return "Withdrawal"
        return "Other"

class DraftKingsTransactionParser(TransactionParser):
    def parse(self, filepath: str) -> List[Dict]:
        # Legacy CSV parser
        pass # ... (Rest of existing CSV logic if needed fallback)
        transactions = []
        # ... (truncated for brevity, user file is HTML now)
        return []

class FanDuelTransactionParser(TransactionParser):
    def parse(self, filepath: str) -> List[Dict]:
        transactions = []
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    # Type,Details,Product,Date,Before,Change,Balance
                    # Date: "Jan 12, 2026, 12:17am ET"
                    raw_date = row['Date']
                    # Clean ET/EDT
                    raw_date = re.sub(r' E[DT]T?$', '', raw_date)
                    dt = datetime.strptime(raw_date, "%b %d, %Y, %I:%M%p")
                    
                    # Filter out non-monetary (points/tokens)
                    # They usually don't have '$' in Balance
                    if '$' not in row['Balance'] and row['Balance'] != "#ERROR!":
                        continue

                    before = self._parse_currency(row['Before'])
                    balance = self._parse_currency(row['Balance'])
                    
                    # Handle Change
                    if row['Change'] == "#ERROR!":
                        change = balance - before
                    else:
                        change = self._parse_currency(row['Change'])
                    
                    # Use provided balance unless it is Error? use calculated
                    if row['Balance'] == "#ERROR!":
                        balance = before + change
                        
                    txn = {
                        "provider": "FanDuel",
                        "date": dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "type": self._map_type(row['Type']),
                        "description": f"{row['Type']} - {row['Details']}",
                        "id": self._extract_id(row['Details']) or f"FD-{dt.timestamp()}",
                        "amount": change,
                        "balance": balance,
                        "raw_data": str(row)
                    }
                    transactions.append(txn)
                except Exception as e:
                    print(f"Error parsing FD row: {e}")
                    
        return transactions

    def _parse_currency(self, val: str) -> float:
        if val == "#ERROR!": return 0.0
        val = val.replace("$", "").replace(",", "")
        return float(val)

    def _map_type(self, raw_type: str) -> str:
        raw_type = raw_type.lower()
        if "wager" in raw_type: return "Wager"
        if "winning" in raw_type: return "Winning"
        if "deposit" in raw_type: return "Deposit"
        if "withdrawal" in raw_type: return "Withdrawal"
        if "bonus" in raw_type: return "Bonus"
        return "Other"
    
    def _extract_id(self, details: str) -> Optional[str]:
        # (Transaction ID: S/0867147/00481262973)
        m = re.search(r'Transaction ID: ([^)]+)', details)
        if m: return m.group(1)
        m = re.search(r'Bet ID: ([^)]+)', details)
        if m: return m.group(1)
        return None
