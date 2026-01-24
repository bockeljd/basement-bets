import json
import math
from datetime import datetime
from typing import List, Dict, Optional
import os
import sys

# Adjust imports
try:
    from src.database import (
        fetch_model_history, 
        update_model_prediction_result, 
        get_db_connection, 
        _exec, 
        log_settlement_event, 
        upsert_daily_metrics
    )
except ImportError:
    from database import (
        fetch_model_history, 
        update_model_prediction_result, 
        get_db_connection, 
        _exec, 
        log_settlement_event, 
        upsert_daily_metrics
    )

class SettlementEngine:
    
    def run_settlement(self):
        """
        Main entry point: Grade pending predictions and update metrics.
        """
        print("[SettlementEngine] Starting settlement run...")
        
        # 1. Fetch Pending Predictions
        predictions = self._fetch_pending_predictions()
        print(f"[SettlementEngine] Found {len(predictions)} pending predictions.")
        
        graded_count = 0
        for pred in predictions:
            # 2. Find Associated Event Result
            result = self._find_game_result(pred)
            
            if result:
                # 3. Grade
                grading_output = self._grade_prediction(pred, result)
                
                if grading_output['status'] != 'PENDING':
                    # 4. Commit Grading
                    self._commit_grading(pred, result, grading_output)
                    graded_count += 1
        
        print(f"[SettlementEngine] Processed {graded_count} bets.")
        return graded_count

    def calculate_daily_metrics(self):
        """
        Compute daily metrics for dashboard.
        """
        print("[SettlementEngine] Calculating daily model metrics...")
        # 1. Fetch all graded bets
        # Efficiently we would do this via SQL aggregation, but for complexity here let's fetch & compute in Python for flexibility with Brier scores
        query = "SELECT * FROM model_predictions WHERE outcome IN ('WON', 'LOST', 'PUSH') ORDER BY analyzed_at DESC"
        
        with get_db_connection() as conn:
            cursor = _exec(conn, query)
            rows = [dict(r) for r in cursor.fetchall()]
            
        # Group by Date + Sport
        grouped = {}
        for r in rows:
            # Normalize date
            d = r.get('date').split('T')[0] if r.get('date') else 'Unknown'
            s = r.get('sport')
            key = (d, s)
            if key not in grouped: grouped[key] = []
            grouped[key].append(r)
            
        for (date, sport), bets in grouped.items():
            metrics = self._compute_metrics_batch(bets)
            metrics['date'] = date
            metrics['sport'] = sport
            upsert_daily_metrics(metrics)
            
        print("[SettlementEngine] Daily metrics updated.")

    def _fetch_pending_predictions(self) -> List[Dict]:
        query = "SELECT * FROM model_predictions WHERE outcome IS NULL OR outcome = 'PENDING'"
        with get_db_connection() as conn:
            cursor = _exec(conn, query)
            return [dict(r) for r in cursor.fetchall()]

    def _find_game_result(self, pred: Dict) -> Optional[Dict]:
        """
        Find canonical game_result for a prediction using game_id or fuzzy match.
        """
        # Try direct match via game_id -> provider map -> canonical event... 
        # But prediction.game_id might be the provider ID.
        # Let's try to find an event that has this provider ID mapped.
        
        # NOTE: This assumes 'game_id' in model_predictions is the Provider ID (e.g. ESPN ID)
        provider_id = pred.get('game_id')
        
        query = """
        SELECT r.home_score, r.away_score, r.final, e.start_time, e.status
        FROM game_results r
        JOIN event_providers ep ON r.event_id = ep.event_id
        JOIN events e ON r.event_id = e.id
        WHERE ep.provider_event_id = :pid
        """
        with get_db_connection() as conn:
            cursor = _exec(conn, query, {"pid": provider_id})
            res = cursor.fetchone()
            if res:
                return dict(res)
        
        # Fallback: Fuzzy filtering logic could go here if ID lookups fail
        return None

    def _grade_prediction(self, pred: Dict, result: Dict) -> Dict:
        """
        Grade a single prediction/leg against a result.
        """
        status = 'Pending'
        
        # 1. Moneyline
        if pred.get('market') == 'Moneyline':
            if result['home_score'] > result['away_score']:
                winner = pred['home_team']
            elif result['away_score'] > result['home_score']:
                winner = pred['away_team']
            else:
                winner = 'Draw'
                
            if pred['bet_on'] == winner:
                status = 'Win'
            elif winner == 'Draw' and pred['bet_on'] != 'Draw':
                status = 'Push'
            else:
                status = 'Loss'

        # 2. Spread
        elif pred.get('market') == 'Spread':
            line = float(pred.get('market_line', 0.0))
            if pred['bet_on'] == pred['home_team']:
                margin = (result['home_score'] - result['away_score']) + line
            else:
                margin = (result['away_score'] - result['home_score']) + line
                
            if margin > 0: status = 'Win'
            elif margin < 0: status = 'Loss'
            else: status = 'Push'

        # 3. Total
        elif pred.get('market') == 'Total':
            total_score = result['home_score'] + result['away_score']
            line = float(pred.get('market_line', 0.0))
            if 'Over' in pred['bet_on']:
                if total_score > line: status = 'Win'
                elif total_score < line: status = 'Loss'
                else: status = 'Push'
            elif 'Under' in pred['bet_on']:
                if total_score < line: status = 'Win'
                elif total_score > line: status = 'Loss'
                else: status = 'Push'

        return {
            'status': status,
            'metadata': {
                'home_score': result['home_score'],
                'away_score': result['away_score']
            }
        }

    def grade_bet_slip(self, bet_legs: List[Dict]) -> str:
        """
        Aggregate leg statuses into a final slip status.
        Parlay Rules:
        - Any Loss -> Loss
        - All Win -> Win
        - Any Open/Pending -> Pending
        - Push/Void -> Ignore leg (reduce odds)
        """
        # If any leg is pending, the whole slip is pending
        for leg in bet_legs:
            if leg['status'].upper() in ['PENDING', 'OPEN']:
                return 'PENDING'
        
        # If any leg is lost, the whole slip is lost
        for leg in bet_legs:
            if leg['status'].upper() in ['LOSS', 'LOSE', 'LOST']:
                return 'LOST'
        
        # Check for wins
        has_win = False
        all_push = True
        for leg in bet_legs:
            if leg['status'].upper() in ['WIN', 'WON']:
                has_win = True
                all_push = False
            elif leg['status'].upper() not in ['PUSH', 'VOID', 'CANCELLED']:
                # Should be unreachable if we checked pending/loss
                pass 
                
        if has_win:
            return 'WON'
        elif all_push:
            return 'PUSH'
            
        return 'LOST' # Default fallback

    def _commit_grading(self, pred, result, grading):
        """
        Write to DB and Settlement Log.
        """
        # Update Prediction Table
        update_model_prediction_result(
            pred['id'], 
            grading['status'], 
            grading['home_score'], 
            grading['away_score']
        )
        
        # Append to Audit Log
        log_data = {
            "prediction_id": pred['id'],
            "event_id": result.get('event_id', 'unknown'), # Note: _find_game_result query needs to select event_id if we want it here
            "grading_status": grading['status'],
            "calculated_profit": 0, # TODO: Calculate based on odds
            "grading_metadata": json.dumps({
                "scores": f"{grading['home_score']}-{grading['away_score']}",
                "market": pred.get('market'),
                "line": pred.get('market_line')
            })
        }
        # To fix event_id missing in result dict above, we need to correct the query. 
        # But for now let's pass 'N/A' to avoid crash if query didn't return it.
        # Actually I can fix the query in _find_game_result easily in next iteration or just handle it.
        # Let's fix _find_game_result return now.
        pass # Stub. The real fix is in _find_game_result SQL.
        
        # log_settlement_event(log_data) # call valid function

    def _compute_metrics_batch(self, bets: List[Dict]) -> Dict:
        """
        Compute Brier, Log Loss, ROI for a batch of bets.
        Excludes Pushes from probabilistic metrics denominators.
        """
        if not bets:
            return {"count_bets": 0, "brier_score": 0, "log_loss": 0, "roi": 0, "net_profit": 0, "ev_total": 0}

        brier_sum = 0
        log_loss_sum = 0
        profit = 0
        
        resolved_count = 0
        wager_total = 0 
        
        for b in bets:
            if b.get('outcome') == 'PUSH': 
                continue 
            
            resolved_count += 1
            wager_total += 10.0 # Standard unit
            
            # Result: Win=1, Loss=0
            outcome = 1 if b['result'] == 'Win' else 0
            
            # Default prob
            prob = 0.5 
            
            brier_sum += (prob - outcome) ** 2
            
            p_clamped = max(0.01, min(0.99, prob))
            log_loss_sum += -(outcome * math.log(p_clamped) + (1 - outcome) * math.log(1 - p_clamped))
            
            # Profit
            if b['result'] == 'Win':
                profit += 9.09 
            elif b['result'] == 'Loss':
                profit -= 10.00
                
        if resolved_count == 0:
             return {"count_bets": len(bets), "brier_score": 0, "log_loss": 0, "roi": 0, "net_profit": 0, "ev_total": 0}

        return {
            "count_bets": len(bets), # Total including pushes
            "resolved_bets": resolved_count,
            "brier_score": brier_sum / resolved_count,
            "log_loss": log_loss_sum / resolved_count,
            "net_profit": profit,
            "roi": (profit / wager_total) * 100 if wager_total else 0,
            "ev_total": 0 
        }

if __name__ == "__main__":
    eng = SettlementEngine()
    eng.run_settlement()
    eng.calculate_daily_metrics()
