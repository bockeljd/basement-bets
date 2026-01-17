from src.parsers.manual_financials_v3 import ManualFinancialsParserV3
from src.database import insert_transaction, get_db_connection
import os

def main():
    filepath = os.path.join('data', 'imports', 'manual_history_attributed.txt')
    parser = ManualFinancialsParserV3(filepath)
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
            query = """
            INSERT OR IGNORE INTO transactions
            (txn_id, provider, date, type, description, amount, balance, raw_data)
            VALUES (:id, :provider, :date, :type, :description, :amount, :balance, :raw_data)
            """
            conn.execute(query, data)
            print(f"Computed ID: {t['id']} -> {t['description']} {t['amount']}")
        
        conn.commit()
    
    print("Changes committed to database.")

if __name__ == "__main__":
    main()
