
import sys
import os

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from src.database import migrate_model_predictions_schema

if __name__ == "__main__":
    print("[Migration] Starting manual schema migration for metrics/CLV...")
    try:
        migrate_model_predictions_schema()
        print("[Migration] Success.")
    except Exception as e:
        print(f"[Migration] Failed: {e}")
