from bs4 import BeautifulSoup
import os

filepath = "data/imports/Account Center _ DraftKings.html"
if not os.path.exists(filepath):
    print(f"File not found: {filepath}")
    exit(1)

print(f"Reading {filepath}...")
with open(filepath, 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f, 'html.parser')

print("Looking for tables...")
tables = soup.find_all('table')
print(f"Found {len(tables)} tables.")

for i, table in enumerate(tables):
    print(f"\n--- Table {i} ---")
    headers = [th.get_text(strip=True) for th in table.find_all('th')]
    print(f"Headers: {headers}")
    
    rows = table.find_all('tr')
    print(f"Total Rows: {len(rows)}")
    
    for r_idx, row in enumerate(rows[:5]):
        cols = [td.get_text(strip=True) for td in row.find_all('td')]
        if cols:
            print(f"Row {r_idx}: {cols}")

print("\n--- Looking for Div-based Grid (if no tables) ---")
# Sometimes React apps use divs instead of tables.
# Look for common header text
dates = soup.find_all(text=lambda t: t and "Date" in t)
print(f"Occurrences of 'Date': {len(dates)}")

amounts = soup.find_all("div", class_=lambda c: c and "FormattedCurrency" in c)
print(f"Found {len(amounts)} currency divs.")

print("\n--- Rows Analysis ---")
rows = soup.select('.BaseTable__row')
print(f"Found {len(rows)} rows.")

for i, row in enumerate(rows[:3]):
    print(f"\nRow {i}:")
    cells = row.select('.BaseTable__row-cell')
    for j, cell in enumerate(cells):
        print(f"  Cell {j}: {cell.get_text(separator='|', strip=True)}")

