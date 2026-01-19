import sqlite3

def check():
    conn = sqlite3.connect('data/bets.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM bets")
    count = cursor.fetchone()[0]
    print(f"Total Bets: {count}")
    
    cursor.execute("SELECT raw_text FROM bets LIMIT 5")
    print("Sample raw_text:", cursor.fetchall())
    
    # Check duplicate or max ID from raw_text
    # raw_text is "Imported from CSV ID X"
    cursor.execute("SELECT raw_text FROM bets")
    all_raw = [r[0] for r in cursor.fetchall()]
    id_nums = []
    for r in all_raw:
        try:
            id_num = int(r.split('ID ')[1])
            id_nums.append(id_num)
        except:
            pass
            
    print(f"Max ID found: {max(id_nums) if id_nums else 'None'}")
    print(f"Unique IDs found: {len(set(id_nums))}")
    
    conn.close()

if __name__ == "__main__":
    check()
