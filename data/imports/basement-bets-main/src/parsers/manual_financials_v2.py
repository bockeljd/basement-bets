from datetime import datetime
import re
import hashlib

class ManualFinancialsParserV2:
    def __init__(self, filepath):
        self.filepath = filepath

    def parse(self):
        """
        Parses text file with format:
        Date    Agency    Method    Amount
        13-Feb-23    DraftKings    Deposit     $ 100.00 
        """
        transactions = []
        seen_hashes = set()
        
        try:
            with open(self.filepath, 'r') as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f"File not found: {self.filepath}")
            return []
            
        # Skip header if present
        start_idx = 0
        if lines and "Date" in lines[0] and "Agency" in lines[0]:
            start_idx = 1
            
        for line in lines[start_idx:]:
            if not line.strip(): continue
            
            # Split by tabs or multiple spaces
            parts = re.split(r'\t+', line.strip())
            if len(parts) < 4:
                parts = re.split(r'\s{2,}', line.strip())
                
            if len(parts) < 4:
                print(f"Skipping malformed line: {line.strip()}")
                continue
                
            date_str, agency, method, amount_str = parts[0], parts[1], parts[2], parts[3]
            
            # Parse Date
            try:
                dt = datetime.strptime(date_str, "%d-%b-%y")
                date_iso = dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                print(f"Skipping invalid date: {date_str}")
                continue
                
            # Parse Amount
            amt_clean = amount_str.replace('$', '').replace(' ', '').replace(',', '')
            if '(' in amt_clean:
                amt_clean = amt_clean.replace('(', '').replace(')', '')
                amount = -float(amt_clean)
            else:
                amount = float(amt_clean)
            
            # Deduplication Hash (within file)
            unique_str = f"{date_iso}_{agency}_{method}_{amount}"
            txn_hash = hashlib.md5(unique_str.encode()).hexdigest()
            
            if txn_hash in seen_hashes:
                print(f"Skipping duplicate input: {date_str} {agency} {amount}")
                continue
            
            seen_hashes.add(txn_hash)
            
            txn = {
                "id": f"txn_manual_{txn_hash[:8]}",
                "provider": agency,
                "date": date_iso,
                "type": method,
                "description": f"Manual Entry - {method}",
                "amount": amount,
                "balance": 0.0
            }
            transactions.append(txn)
            
        return transactions
