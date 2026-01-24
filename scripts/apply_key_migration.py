
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from src.database import get_admin_db_connection

def apply_keys():
    print("[Migration] Adding snapshot_key and prediction_key...")
    
    stmts = [
        "ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS snapshot_key TEXT;",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_odds_snapshots_snapshot_key ON odds_snapshots(snapshot_key);",
        
        "ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS model_version TEXT;",
        "ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS prediction_key TEXT;",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_model_predictions_prediction_key ON model_predictions(prediction_key);"
    ]
    
    with get_admin_db_connection() as conn:
        with conn.cursor() as cur:
            for s in stmts:
                try:
                    print(f"Exec: {s}")
                    cur.execute(s)
                except Exception as e:
                    print(f"Skip/Error: {e}")
        conn.commit()
    print("[Migration] Done.")

if __name__ == "__main__":
    apply_keys()
