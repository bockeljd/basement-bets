from src.parsers.transactions import DraftKingsTransactionParser, FanDuelTransactionParser, DraftKingsHTMLTransactionParser, TransactionParser
from src.database import init_transactions_tab, insert_transaction
import os

def ingest_all():
    # 1. Init DB
    init_transactions_tab()
    
    # 2. Ingest DraftKings (HTML preferred if exists)
    dk_html_path = "data/imports/Account Center _ DraftKings.html"
    dk_csv_path = "data/imports/Basement Bets - DraftKings Transactions.csv"
    
    parser: TransactionParser = None
    path_to_use = None
    
    if os.path.exists(dk_html_path):
        print(f"Ingesting DK HTML: {dk_html_path}...")
        parser = DraftKingsHTMLTransactionParser()
        path_to_use = dk_html_path
    elif os.path.exists(dk_csv_path):
        print(f"Ingesting DK CSV: {dk_csv_path}...")
        parser = DraftKingsTransactionParser()
        path_to_use = dk_csv_path
        
    if parser and path_to_use:
        txns = parser.parse(path_to_use)
        for txn in txns:
            insert_transaction(txn)
        print(f"Inserted {len(txns)} DK transactions.")
    else:
        print("Missing DraftKings import file.")

    # 3. Ingest FanDuel
    fd_path = "data/imports/Basement Bets - Fanduel Transactions.csv"
    if os.path.exists(fd_path):
        print(f"Ingesting {fd_path}...")
        parser = FanDuelTransactionParser()
        txns = parser.parse(fd_path)
        for txn in txns:
            insert_transaction(txn)
        print(f"Inserted {len(txns)} FD transactions.")
    else:
        print(f"Missing {fd_path}")

if __name__ == "__main__":
    ingest_all()
