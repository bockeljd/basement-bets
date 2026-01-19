import sqlite3

# This script will search for 'Unknown' sport bets and display their context
def main():
    conn = sqlite3.connect('data/bets.db')
    cursor = conn.cursor()
    
    print("Searching for Unknown Sport bets...")
    cursor.execute("SELECT id, description, selection, provider, raw_text FROM bets WHERE sport = 'Unknown'")
    rows = cursor.fetchall()
    
    if not rows:
        print("No bets with 'Unknown' sport found.")
    
    for r in rows:
        print(f"\nID: {r[0]}")
        print(f"Provider: {r[3]}")
        print(f"Desc: {r[1]}")
        print(f"Selection: {r[2]}")
        print(f"Raw Text: {r[4][:100]}...") # First 100 chars
        
    conn.close()

if __name__ == "__main__":
    main()
