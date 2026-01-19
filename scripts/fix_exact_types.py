import sys
import os

sys.path.append(os.getcwd())
from src.database import get_db_connection, _exec

def main():
    print("Fixing exact-match bet types...")
    
    # Map exact bet_type values to standard categories
    fixes = [
        ('BIJAN ROBINSON', 'Prop'),
        ('CLEMSON−130', 'Winner (ML)'),
        ('OHIO STATE', 'Winner (ML)'),
        ('OHIO STATE−140', 'Winner (ML)')
    ]
    
    with get_db_connection() as conn:
        for old_type, new_type in fixes:
            sql = "UPDATE bets SET bet_type = :new WHERE bet_type = :old"
            cursor = _exec(conn, sql, {'new': new_type, 'old': old_type})
            
            # Check how many rows were updated (different for PG vs SQLite)
            # For Postgres, cursor.rowcount works
            # For SQLite, we'd need to query
            print(f"Updated '{old_type}' -> '{new_type}'")
            
        conn.commit()
        print("\n✓ All bet types standardized")
        
        # Verify
        print("\nVerifying bet type distribution:")
        cursor = _exec(conn, """
            SELECT bet_type, COUNT(*) as count
            FROM bets
            GROUP BY bet_type
            ORDER BY count DESC
        """)
        
        standard_types = {'Winner (ML)', 'Spread', 'Over / Under', 'Prop', 'SGP', '2 Leg Parlay', '3 Leg Parlay', '4+ Parlay'}
        
        for row in cursor.fetchall():
            marker = "✓" if row['bet_type'] in standard_types else "⚠"
            print(f"  {marker} {row['bet_type']}: {row['count']}")

if __name__ == "__main__":
    main()
