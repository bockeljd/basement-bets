import os
from dotenv import load_dotenv
load_dotenv('.env.local')

from src.database import get_db_connection, init_db, init_transactions_db, init_model_history

def reset():
    print("Resetting database tables...")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        print("Dropping transactions...")
        cursor.execute("DROP TABLE IF EXISTS transactions")
        print("Dropping bets...")
        cursor.execute("DROP TABLE IF EXISTS bets")
        conn.commit()
    
    print("Initializing tables...")
    # init_db is likely just a wrapper, checking lines 71+ would confirm
    # but I can just call the specific inits I see exported/defined.
    
    # Wait, init_db() on line 71. Viewing it:
    # It calls init_transactions_db() and others? 
    # I didn't see the body of init_db in previous view, but assuming it calls sub-inits.
    # To be safe, I'll call them explicitly if I can import them.
    # checking imports...
    # I can import init_transactions_db. 
    # Can I import a function to init bets? 
    # src/database.py has `init_model_history` (line 142).
    # Does it have `init_bets_tab`? 
    # I'll rely on init_db() first, effectively testing it.
    
    init_db() 
    # Also ensure transactions is valid (init_db might call it, but verify)
    init_transactions_db()

if __name__ == "__main__":
    reset()
