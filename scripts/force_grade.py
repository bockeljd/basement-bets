import sys
import os
import json
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.services.grading_service import GradingService
from src.database import get_db_connection

def force_grade():
    print("--- FORCE GRADING RUN ---")
    service = GradingService()
    
    # 1. Check Pending Count Before
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT count(*) FROM model_predictions WHERE result='Pending'")
        pending_before = c.fetchone()[0]
        print(f"Pending Before: {pending_before}")
    
    # 2. Run Grading
    # Verify the days parameter inside the service (we bumped it to 7)
    results = service.grade_predictions()
    print(f"Grading Service Output: {results}")
    
    # 3. Check Pending Count After
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT count(*) FROM model_predictions WHERE result='Pending'")
        pending_after = c.fetchone()[0]
        print(f"Pending After: {pending_after}")
    
        # 4. Inspect specific 1/13 games if still pending
        if pending_after > 0:
            c.execute("SELECT * FROM model_predictions WHERE result='Pending' LIMIT 5")
            rows = c.fetchall()
            print("\nRemaining Pending Sample:")
            for r in rows:
                print(f"ID: {r['id']}, Sport: {r['sport']}, Teams: {r['home_team']} vs {r['away_team']}, Date: {r['date']}")

if __name__ == "__main__":
    force_grade()
