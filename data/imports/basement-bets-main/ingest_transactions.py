import os
from dotenv import load_dotenv

load_dotenv('.env.local')

from src.parsers.transactions import (
    TransactionParser, DraftKingsHTMLTransactionParser, DraftKingsTransactionParser,
    FanDuelTransactionParser, DraftKingsManualFinancialsParser, LegacyFinancialsParser
)
from src.database import init_transactions_tab, insert_transaction

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
        txns = parser.parse(path_to_use)
        for txn in txns:
            txn['user_id'] = '00000000-0000-0000-0000-000000000000'
            txn['account_id'] = None 
            insert_transaction(txn)
        print(f"Inserted {len(txns)} DK HTML transactions.")

    # 2b. Ingest DK Manual Financials
    dk_manual_path = "data/imports/dk_financials_manual.txt"
    if os.path.exists(dk_manual_path):
        print(f"Ingesting DK Manual: {dk_manual_path}...")
        parser = DraftKingsManualFinancialsParser()
        txns = parser.parse(dk_manual_path)
        for txn in txns:
             txn['user_id'] = '00000000-0000-0000-0000-000000000000'
             txn['account_id'] = None
             insert_transaction(txn)
        print(f"Inserted {len(txns)} DK Manual transactions.")

    # 2c. Ingest Legacy 2023
    legacy_path = "data/imports/legacy_financials_2023.csv"
    if os.path.exists(legacy_path):
        print(f"Ingesting Legacy: {legacy_path}...")
        parser = LegacyFinancialsParser()
        txns = parser.parse(legacy_path)
        for txn in txns:
             txn['user_id'] = '00000000-0000-0000-0000-000000000000'
             txn['account_id'] = None
             insert_transaction(txn)
        print(f"Inserted {len(txns)} Legacy transactions.")

    # 3. Ingest FanDuel
    fd_path = "data/imports/Basement Bets - Fanduel Transactions.csv"
    if os.path.exists(fd_path):
        print(f"Ingesting {fd_path}...")
        parser = FanDuelTransactionParser()
        txns = parser.parse(fd_path)
        for txn in txns:
            txn['user_id'] = '00000000-0000-0000-0000-000000000000'
            txn['account_id'] = None
            insert_transaction(txn)
        print(f"Inserted {len(txns)} FD transactions.")
    else:
        print(f"Missing {fd_path}")

if __name__ == "__main__":
    ingest_all()
