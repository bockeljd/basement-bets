import sys
import os

# Ensure src is in path
sys.path.append(os.path.abspath("."))

from src.database import init_games_db

if __name__ == "__main__":
    print("Initializing 'games' table...")
    init_games_db()
    print("Done.")
