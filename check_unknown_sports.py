import sqlite3

def main():
    conn = sqlite3.connect('data/bets.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT count(*) FROM bets WHERE sport = 'Unknown'")
    count = cursor.fetchone()[0]
    print(f"Total Unknown Sport Bets: {count}\n")
    
    cursor.execute("""
        SELECT id, description, selection, provider, bet_type 
        FROM bets 
        WHERE sport = 'Unknown' 
        LIMIT 20
    """)
    
    rows = cursor.fetchall()
    for row in rows:
        print(f"ID: {row['id']} | Provider: {row['provider']} | Type: {row['bet_type']}")
        print(f"  Desc: {row['description']}")
        print(f"  Sel:  {row['selection']}")
        print("-" * 40)
    
    conn.close()

if __name__ == "__main__":
    main()
