import os
import sqlite3
from src.parsers.draftkings_text import DraftKingsTextParser
from src.database import get_db_connection

def main():
    filepath = 'data/imports/2026-01-11_draftkings.txt'
    if not os.path.exists(filepath):
        print(f"Error: {filepath} not found.")
        return

    with open(filepath, 'r') as f:
        content = f.read()

    parser = DraftKingsTextParser()
    bets = parser.parse(content)

    print(f"Parsed {len(bets)} bets from {filepath}.")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        for bet in bets:
            # We use a combined key or just trust the parser/db to handle duplicates
            # The 'bets' table has columns like date, sport, bet_type, wager, profit, status, etc.
            # Let's check the schema or use a generic insert.
            
            # Note: The 'bets' table structure usually matches:
            # (date, sport, bet_type, selection, odds, wager, status, profit, provider, is_live, is_bonus, raw_text)
            
            query = """
            INSERT OR IGNORE INTO bets 
            (date, sport, bet_type, selection, odds, wager, status, profit, provider, is_live, is_bonus, raw_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            cursor.execute(query, (
                bet['date'],
                bet['sport'],
                bet['bet_type'],
                bet['selection'],
                bet['odds'],
                bet['wager'],
                bet['status'],
                bet['profit'],
                bet['provider'],
                bet.get('is_live', 0),
                bet.get('is_bonus', 0),
                bet.get('raw_text', '')
            ))
        
        conn.commit()
        print(f"Successfully processed {len(bets)} bets.")

if __name__ == "__main__":
    main()
