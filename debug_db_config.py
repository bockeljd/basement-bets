
from src.config import settings
from src.database import DB_PATH, get_db_type
import os

print(f"DATABASE_URL is set: {bool(settings.DATABASE_URL)}")
if settings.DATABASE_URL:
    print(f"DATABASE_URL value (masked): {settings.DATABASE_URL[:15]}...")
print(f"DB_PATH: {DB_PATH}")
print(f"get_db_type(): {get_db_type()}")
print(f"Current Working Dir: {os.getcwd()}")
