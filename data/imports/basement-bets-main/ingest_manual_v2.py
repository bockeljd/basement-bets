from src.parsers.manual_financials_v2 import ManualFinancialsParserV2
from src.database import insert_transaction, get_db_connection
import os

def main():
    filepath = os.path.join('data', 'imports', 'manual_history_additions.txt')
    parser = ManualFinancialsParserV2(filepath)
    transactions = parser.parse()
    
    print(f"Parsed {len(transactions)} transactions.")
    
    with get_db_connection() as conn:
        for t in transactions:
            data = {
                "id": t['id'],
                "provider": t['provider'],
                "date": t['date'],
                "type": t['type'],
                "description": t['description'],
                "amount": t['amount'],
                "balance": t['balance'],
                "raw_data": str(t)
            }
            # Inline insert to allow executemany or just loop
            query = """
            INSERT OR IGNORE INTO transactions
            (txn_id, provider, date, type, description, amount, balance, raw_data)
            VALUES (:id, :provider, :date, :type, :description, :amount, :balance, :raw_data)
            """
            conn.execute(query, data)
            print(f"Inserted/Ignored {t['type']} {t['amount']} for {t['provider']} on {t['date']}")
        
        conn.commit()
    
    print("Changes committed to database.")

if __name__ == "__main__":
    main()
