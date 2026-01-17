import sys
import os
import json
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.database import get_db_connection, fetch_model_history
from src.services.grading_service import GradingService
from src.services.auditor import ResearchAuditor

def audit_database():
    print("\n--- 1. DATABASE AUDIT ---")
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        # Predictions
        cur.execute("SELECT count(*) FROM model_predictions")
        count_preds = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM model_predictions WHERE result='Pending'")
        count_pending = cur.fetchone()[0]
        
        print(f"Total Predictions: {count_preds}")
        print(f"Pending Predictions: {count_pending}")
        
        # Games
        try:
            cur.execute("SELECT count(*) FROM games")
            count_games = cur.fetchone()[0]
            print(f"Cached Games: {count_games}")
        except:
            print("Cached Games: Table 'games' not found or empty.")

def audit_models():
    print("\n--- 2. MODEL HEALTH CHECK ---")
    
    # NCAAM
    try:
        from src.models.ncaam_model import NCAAMModel
        ncaam = NCAAMModel()
        print("Running NCAAM find_edges()...")
        edges = ncaam.find_edges()
        print(f"NCAAM Edges Found: {len(edges)}")
        if edges:
            print(f"Sample: {edges[0]['away_team']} @ {edges[0]['home_team']} (Edge: {edges[0]['edge']})")
    except Exception as e:
        print(f"NCAAM FAILED: {e}")

    # NFL
    try:
        from src.models.nfl_model import NFLModel
        nfl = NFLModel()
        print("Running NFL find_edges()...")
        edges = nfl.find_edges()
        print(f"NFL Edges Found: {len(edges)}")
    except Exception as e:
        print(f"NFL FAILED: {e}")

    # EPL
    try:
        from src.models.epl_model import EPLModel
        epl = EPLModel()
        print("Running EPL find_edges()...")
        edges = epl.find_edges()
        print(f"EPL Edges Found: {len(edges)}")
    except Exception as e:
        print(f"EPL FAILED: {e}")

def audit_grading():
    print("\n--- 3. GRADING SERVICE CHECK ---")
    service = GradingService()
    try:
        res = service.grade_predictions()
        print(f"Grading Result: {res}")
    except Exception as e:
        print(f"Grading FAILED: {e}")

def audit_confidence_logic():
    print("\n--- 4. CONFIDENCE LOGIC CHECK ---")
    auditor = ResearchAuditor()
    
    # Test Cases
    cases = [
        {"sport": "NCAAM", "edge": 9.0, "desc": "High Deviation (>8)"},
        {"sport": "NCAAM", "edge": 2.0, "desc": "Low Deviation (<8)"},
        {"sport": "NFL", "edge": 4.0, "desc": "Med Deviation (>3.5)"},
        {"sport": "NFL", "edge": 1.0, "desc": "Low Deviation (<3.5)"}
    ]
    
    for c in cases:
        res = auditor.audit(c)
        print(f"[{c['sport']}] {c['desc']} -> Class: {res['audit_class']}, Score: {res['audit_score']}")

if __name__ == "__main__":
    print(f"Starting System Audit at {datetime.now()}")
    audit_database()
    audit_models()
    audit_grading()
    audit_confidence_logic()
    print("\nAudit Complete.")
