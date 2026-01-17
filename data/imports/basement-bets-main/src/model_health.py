import math
from typing import List, Dict, Tuple
import sys
import os

# Adjust imports based on project structure
try:
    from src.database import get_db_connection, _exec
except ImportError:
    from database import get_db_connection, _exec

class ModelHealth:
    
    def compute_brier(self, predictions: List[Dict]) -> float:
        """
        Mean Squared Error of Probabilities.
        Expects keys: 'prob', 'outcome' (1 or 0)
        """
        if not predictions: return 0.0
        sse = sum((p['prob'] - p['outcome']) ** 2 for p in predictions)
        return sse / len(predictions)

    def compute_ece(self, predictions: List[Dict], n_bins=10) -> float:
        """
        Expected Calibration Error.
        """
        if not predictions: return 0.0
        
        bins = [[] for _ in range(n_bins)]
        for p in predictions:
            prob = p['prob']
            idx = min(int(prob * n_bins), n_bins - 1)
            bins[idx].append(p)
            
        ece = 0.0
        total = len(predictions)
        
        for b in bins:
            if not b: continue
            avg_prob = sum(x['prob'] for x in b) / len(b)
            avg_outcome = sum(x['outcome'] for x in b) / len(b)
            ece += (len(b) / total) * abs(avg_prob - avg_outcome)
            
        return ece

    def check_promotion(self, candidate_metrics: Dict, incumbent_metrics: Dict) -> bool:
        """
        Check if Candidate beats Incumbent.
        Rules:
        1. Brier must be lower (better).
        2. ECE must be lower (better) OR very low (< 0.02).
        3. ROI (if available) must be higher.
        """
        
        # 1. Brier
        if candidate_metrics['brier'] >= incumbent_metrics['brier']:
            return False
            
        # 2. ECE (If candidate ECE is terrible, reject even if Brier is good)
        if candidate_metrics['ece'] > 0.10:
            return False
            
        return True

    def run_report(self):
        # Fetch data dummy
        # In real impl, would query prediction_outcomes table.
        print("Running Model Health Report...")
        # TODO: Connect to DB
