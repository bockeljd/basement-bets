from src.parsers.draftkings_financials import DraftKingsFinancialsParser
from src.database import get_db_connection

def main():
    with open('data/imports/dk_financials_manual.txt', 'r') as f:
        content = f.read()
        
    parser = DraftKingsFinancialsParser()
    txs = parser.parse(content)
    
    print(f"Parsed {len(txs)} transactions.")
    
    with get_db_connection() as conn:
        for t in txs:
            # Upsert based on txn_id
            conn.execute("""
                INSERT OR IGNORE INTO transactions 
                (txn_id, provider, date, type, description, amount, balance)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                t['transaction_id'],
                t['provider'],
                t['date'],
                t['type'],
                t['description'],
                t['amount'],
                0.0 # Balance not provided
            ))
            print(f"inserted {t['type']} {t['amount']} for {t['date']}")
        
        conn.commit()
        print("Changes committed to database.")
            
if __name__ == "__main__":
    main()
