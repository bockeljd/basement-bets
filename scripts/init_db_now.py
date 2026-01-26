
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.database import init_db

if __name__ == "__main__":
    print("Initializing Database...")
    init_db()
    print("Done.")
