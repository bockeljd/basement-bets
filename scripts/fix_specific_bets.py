import sys
import os

sys.path.append(os.getcwd())
from src.database import get_db_connection, _exec

def main():
    print("Finding and updating specific bets...")
    
    with get_db_connection() as conn:
        # Find bets matching keywords
        searches = [
            ('bijan robinson', 'Prop'),
            ('ohio state', 'Winner (ML)'),
            ('clemson', 'Winner (ML)')
        ]
        
        for keyword, target_type in searches:
            print(f"\nSearching for '{keyword}'...")
            
            # Search in selection or description
            sql = """
            SELECT id, bet_type, selection, description, status
            FROM bets
            WHERE LOWER(selection) LIKE :keyword OR LOWER(description) LIKE :keyword
            """
            
            cursor = _exec(conn, sql, {'keyword': f'%{keyword}%'})
            rows = cursor.fetchall()
            
            print(f"Found {len(rows)} bet(s) matching '{keyword}'")
            
            for row in rows:
                bet_id = row['id']
                old_type = row['bet_type']
                selection = row['selection']
                status = row['status']
                
                print(f"  ID {bet_id}: '{old_type}' -> '{target_type}' | {selection} | Status: {status}")
                
                # Update
                update_sql = "UPDATE bets SET bet_type = :new_type WHERE id = :id"
                _exec(conn, update_sql, {'new_type': target_type, 'id': bet_id})
                
        conn.commit()
        print("\n✓ Updates complete")
        
        # Now check for any bets with unusual bet_type values
        print("\n\nChecking for non-standard bet types...")
        sql = """
        SELECT DISTINCT bet_type, COUNT(*) as count
        FROM bets
        GROUP BY bet_type
        ORDER BY count DESC
        """
        cursor = _exec(conn, sql)
        rows = cursor.fetchall()
        
        standard_types = {'Winner (ML)', 'Spread', 'Over / Under', 'Prop', 'SGP', '2 Leg Parlay', '3 Leg Parlay', '4+ Parlay'}
        
        print("Bet Type Distribution:")
        for row in rows:
            bet_type = row['bet_type']
            count = row['count']
            marker = "✓" if bet_type in standard_types else "⚠"
            print(f"  {marker} {bet_type}: {count}")

if __name__ == "__main__":
    main()
