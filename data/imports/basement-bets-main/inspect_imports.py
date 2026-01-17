import csv

files = [
    "data/imports/Basement Bets - DraftKings Transactions.csv",
    "data/imports/Basement Bets - Fanduel Transactions.csv"
]

for fpath in files:
    print(f"\n--- Inspecting {fpath} ---")
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            content = f.read(1000)
            print(f"First 1000 chars:\n{repr(content)}")
            
            f.seek(0)
            sniffer = csv.Sniffer()
            has_header = sniffer.has_header(content)
            dialect = sniffer.sniff(content)
            print(f"Detected delimiter: {repr(dialect.delimiter)}")
            print(f"Has Header: {has_header}")
    except Exception as e:
        print(f"Error: {e}")
