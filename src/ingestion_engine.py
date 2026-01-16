import json
import gzip
import os
import uuid
import datetime
import hashlib
from typing import Dict, Any, List

import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Adjust imports based on project structure
try:
    from src.database import get_db_connection, _exec, log_ingestion_run
except ImportError:
    from database import get_db_connection, _exec, log_ingestion_run

class IngestionEngine:
    
    def __init__(self, storage_path: str = "data/snapshots"):
        self.storage_path = storage_path
        os.makedirs(self.storage_path, exist_ok=True)

    def _save_snapshot(self, provider: str, league: str, data: Any) -> str:
        """
        Save raw payload to gzip JSON.
        Returns absolute path.
        """
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        run_id = str(uuid.uuid4())
        
        dir_path = os.path.join(self.storage_path, provider, league, date_str)
        os.makedirs(dir_path, exist_ok=True)
        
        filename = f"{run_id}.json.gz"
        full_path = os.path.abspath(os.path.join(dir_path, filename))
        
        with gzip.open(full_path, 'wt', encoding='utf-8') as f:
            json.dump(data, f)
            
        return full_path

    def _detect_drift(self, data: Any, expected_keys: set) -> bool:
        """
        Simple schema drift detection. Checks if expected keys are present in the first item.
        """
        if not data: return False
        
        # Assume List[Dict] or Dict structure
        sample = data[0] if isinstance(data, list) else data
        if not isinstance(sample, dict): return False
        
        keys = set(sample.keys())
        # Drift if expected keys are MISSING. Extra keys are fine usually.
        missing = expected_keys - keys
        if missing:
            print(f"[Drift] Missing keys: {missing}")
            return True
        return False

    def ingest_data(self, provider: str, league: str, data: Any, expected_keys: set = None):
        """
        Main entry point for ingestion.
        1. Save Snapshot
        2. Detect Drift
        3. Log Run
        """
        start_time = datetime.datetime.now()
        run_id = str(uuid.uuid4())
        
        # 1. Snapshot
        snapshot_path = self._save_snapshot(provider, league, data)
        
        # 2. Drift
        drift_detected = False
        if expected_keys:
            drift_detected = self._detect_drift(data, expected_keys)
            
        # 3. Log (Placeholder for actual processing count logic)
        items_count = len(data) if isinstance(data, list) else 1
        
        log_data = {
            "id": run_id,
            "provider": provider,
            "league": league,
            "run_status": "SUCCESS", # TODO: Handle Errors
            "items_processed": items_count,
            "items_changed": 0, # TODO: Diff logic
            "payload_snapshot_path": snapshot_path,
            "schema_drift_detected": drift_detected
        }
        
        try:
            log_ingestion_run(log_data)
            print(f"[Ingestion] Logged run {run_id}. Drift: {drift_detected}")
        except Exception as e:
            print(f"[Ingestion] Failed to log run: {e}")

    # TODO: Add specific provider methods (ingest_espn, ingest_football_data)

if __name__ == "__main__":
    # Smoke Test
    engine = IngestionEngine()
    dummy_data = [{"id": 1, "name": "Event A"}, {"id": 2, "name": "Event B"}]
    engine.ingest_data("TEST_PROVIDER", "NFL", dummy_data, expected_keys={"id", "name", "status"})
