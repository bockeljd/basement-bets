
from datetime import datetime, date
import math
import json
from collections import defaultdict
from src.database import get_db_connection, _exec, store_daily_evaluation

class EvaluationService:
    def __init__(self):
        pass

    def evaluate_daily_performance(self, target_date: date = None):
        """
        Runs evaluation for a specific date (bets settled on that date).
        If date is None, runs for yesterday.
        """
        if not target_date:
            target_date = date.today() # Or yesterday? usually settled items are from yesterday. 
            # But let's assume we run this for "today" implies things settled today.
            
        print(f"[Evaluation] Running for {target_date}...")
        
        # 1. Fetch Settlements on this date
        # We look at 'graded_at' or the game start time?
        # Usually model health is tracked by Event Start Date (Cohort Analysis).
        # So we want events that started on 'target_date' and are now settled.
        
        with get_db_connection() as conn:
            # Query: Join Predictions with Settlement Events
            # We filter by event start_time cast to date
            q = """
            SELECT 
                p.model_version_id,
                p.league,
                p.market_type,
                p.output_win_prob,
                p.output_implied_margin,
                p.output_implied_total,
                s.outcome, 
                s.result,   -- JSON
                s.computed  -- JSON
            FROM predictions p
            JOIN settlement_events s ON p.event_id = s.event_id
            JOIN events_v2 e ON p.event_id = e.id
            WHERE date(e.start_time) = :date
              AND s.outcome IN ('WON', 'LOST') -- PUSH/VOID excluded for Brier/LogLoss usually, or handled separately
            """
            
            # Note: sqlite uses strftime for date
            # We need DB agnostic date function or try/except
            # Or just filter in python if volume low.
            # Let's try standard SQL, sqlite might support date()
            
            cursor = _exec(conn, q, {"date": str(target_date)})
            rows = cursor.fetchall()
            
        print(f"[Evaluation] Found {len(rows)} settled predictions.")
        
        # 2. Aggregate Metrics
        # Key: (model_id, league, market)
        stats = defaultdict(lambda: {"brier_sum": 0.0, "logloss_sum": 0.0, "correct": 0, "count": 0, "profit_sim": 0.0})
        
        for row in rows:
            mid = row['model_version_id']
            league = row['league']
            market = row['market_type']
            prob = row['output_win_prob']
            outcome = row['outcome']
            
            if prob is None: continue
            
            key = (mid, league, market)
            
            # Actual: WON=1, LOST=0
            actual = 1.0 if outcome == 'WON' else 0.0
            
            # Brier: (prob - actual)^2
            brier = (prob - actual) ** 2
            stats[key]["brier_sum"] += brier
            
            # Log Loss: - (y log(p) + (1-y) log(1-p))
            # Clip prob to avoid log(0)
            p_safe = max(min(prob, 0.9999), 0.0001)
            ll = - (actual * math.log(p_safe) + (1-actual) * math.log(1-p_safe))
            stats[key]["logloss_sum"] += ll
            
            if (prob > 0.5 and actual == 1.0) or (prob < 0.5 and actual == 0.0):
                stats[key]["correct"] += 1
                
            stats[key]["count"] += 1
            
        # 3. Compute Averages and Store
        metrics_to_store = []
        for key, agg in stats.items():
            mid, league, market = key
            n = agg["count"]
            if n == 0: continue
            
            metrics_to_store.append({
                "date": target_date,
                "model_version_id": mid,
                "league": league, 
                "market_type": market,
                "metric_name": "brier_score",
                "metric_value": agg["brier_sum"] / n,
                "sample_size": n
            })
            metrics_to_store.append({
                "date": target_date,
                "model_version_id": mid,
                "league": league, 
                "market_type": market,
                "metric_name": "log_loss",
                "metric_value": agg["logloss_sum"] / n,
                "sample_size": n
            })
            metrics_to_store.append({
                "date": target_date,
                "model_version_id": mid,
                "league": league, 
                "market_type": market,
                "metric_name": "accuracy",
                "metric_value": agg["correct"] / n,
                "sample_size": n
            })

        print(f"[Evaluation] Storing {len(metrics_to_store)} metrics.")
        store_daily_evaluation(metrics_to_store)
        return len(metrics_to_store)

if __name__ == "__main__":
    svc = EvaluationService()
    svc.evaluate_daily_performance(date.today())
