import os
import sys
from src.database import get_db_connection, _exec
from src.parsers.legacy_sheets import LegacySheetParser

LEGACY_FILE = os.path.join(os.path.dirname(__file__), 'data', 'imports', 'legacy_history.csv')

def ingest_legacy():
    if not os.path.exists(LEGACY_FILE):
        print(f"Error: File not found: {LEGACY_FILE}")
        return

    print(f"Parsing legacy file: {LEGACY_FILE}")
    parser = LegacySheetParser(LEGACY_FILE)
    bets = parser.parse()
    
    if not bets:
        print("No bets found to ingest.")
        return

    print(f"Found {len(bets)} bets. Connecting to database...")
    
    try:
        with get_db_connection() as conn:
            # 1. Get User ID
            # Fetch a valid user_id to use. We assume single user for now or grab the first available.
            c = conn.cursor()
            c.execute("SELECT user_id FROM bets LIMIT 1")
            row = c.fetchone()
            if not row:
                # Fallback if DB is empty? Generate one?
                # Or check transactions?
                c.execute("SELECT user_id FROM transactions LIMIT 1")
                row = c.fetchone()
            
            if row:
                user_id = row[0]
            else:
                # Total fallback
                import uuid
                user_id = str(uuid.uuid4())
                print(f"Warning: No existing user found. Created temporary ID: {user_id}")

            print(f"Using User ID: {user_id}")

            inserted_count = 0
            updated_count = 0

            for bet in bets:
                # Composite Key Check
                # UNIQUE(user_id, provider, description, date, wager)
                
                check_sql = """
                    SELECT id FROM bets 
                    WHERE user_id=%s AND provider=%s AND description=%s AND date=%s AND wager=%s
                """
                params = (
                    user_id, 
                    bet['sportsbook'], 
                    bet['description'], 
                    bet['date_placed'], 
                    bet['wager']
                )
                
                # Use _exec to handle %s -> ? if sqlite
                cursor = _exec(conn, check_sql, params)
                existing = cursor.fetchone()

                if existing:
                    # Update
                    # We update mutable fields: result, profit, status, odds
                    update_sql = """
                        UPDATE bets 
                        SET profit = %s, status = %s, odds = %s, sport = %s, bet_type = %s
                        WHERE id = %s
                    """
                    update_params = (
                        bet['profit'], 
                        bet['status'], 
                        bet['odds'],
                        bet.get('sport', 'Unknown'),
                        bet['bet_type'],
                        existing[0] # The existing ID
                    )
                    _exec(conn, update_sql, update_params)
                    updated_count += 1
                else:
                    # Insert
                    insert_sql = """
                        INSERT INTO bets (
                            user_id, date, provider, bet_type, sport, 
                            wager, profit, status, description, odds, 
                            raw_text, selection
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    insert_params = (
                        user_id,
                        bet['date_placed'],
                        bet['sportsbook'],
                        bet['bet_type'],
                        bet.get('sport', 'Unknown'),
                        bet['wager'],
                        bet['profit'],
                        bet['status'],
                        bet['description'],
                        bet['odds'],
                        f"Legacy Import: {bet.get('external_id')}",
                        "" # Selection is merged into description usually
                    )
                    _exec(conn, insert_sql, insert_params)
                    inserted_count += 1
            
            conn.commit()
            print("Ingestion complete!")
            print(f"Inserted: {inserted_count}")
            print(f"Updated: {updated_count}")

    except Exception as e:
        print(f"Error during ingestion: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    ingest_legacy()
