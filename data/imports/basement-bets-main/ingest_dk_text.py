import os
import sqlite3
from dotenv import load_dotenv

load_dotenv('.env.local')

from src.parsers.draftkings_text import DraftKingsTextParser
from src.database import get_db_connection, _exec

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

    # Default user for ingestion
    user_id = "00000000-0000-0000-0000-000000000000"

    with get_db_connection() as conn:
        # Use _exec helper if available, or direct cursor depending on DB type
        # But here valid SQL for both is needed.
        # src.database usually handles connection.
        
        for bet in bets:
            # We use a combined key or just trust the parser/db to handle duplicates
            # The 'bets' table has columns like date, sport, bet_type, wager, profit, status, etc.
            # Let's check the schema or use a generic insert.
            
            # Note: The 'bets' table structure usually matches:
            # (date, sport, bet_type, selection, odds, wager, status, profit, provider, is_live, is_bonus, raw_text)
            
            query = """
            INSERT OR IGNORE INTO bets 
            (user_id, date, sport, bet_type, selection, odds, wager, status, profit, provider, is_live, is_bonus, raw_text, description)
            VALUES (:user_id, :date, :sport, :bet_type, :selection, :odds, :wager, :status, :profit, :provider, :is_live, :is_bonus, :raw_text, :description)
            """
            
            # Note: description is NOT NULL in schema, parser might not provide it?
            # Parser likely provides event name as description or selection.
            # Check bet dict keys.
            description = bet.get('description') or bet.get('selection') or "Unknown Event"
            
            params = {
                "user_id": user_id,
                "date": bet['date'],
                "sport": bet['sport'],
                "bet_type": bet['bet_type'],
                "selection": bet['selection'],
                "odds": bet['odds'],
                "wager": bet['wager'],
                "status": bet['status'],
                "profit": bet['profit'],
                "provider": 'DraftKings',
                "is_live": bet.get('is_live', 0),
                "is_bonus": bet.get('is_bonus', 0),
                "raw_text": bet.get('raw_text', ''),
                "description": description
            }
            
            _exec(conn, query, params)
        
        conn.commit()
        print(f"Successfully processed {len(bets)} bets.")

if __name__ == "__main__":
    main()
