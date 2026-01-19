import sqlite3

def main():
    conn = sqlite3.connect('data/bets.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT count(*) FROM bets")
    count = cursor.fetchone()[0]
    print(f"Total Bets in DB: {count}")
    
    cursor.execute("SELECT DISTINCT sport, count(*) FROM bets GROUP BY sport ORDER BY count(*) DESC")
    rows = cursor.fetchall()
    
    print("Current Sport Distribution:")
    for row in rows:
        print(f"{row[0]}: {row[1]}")
    
    conn.close()

if __name__ == "__main__":
    main()
