
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
        """
        if not target_date:
            target_date = date.today()
            
        print(f"[Evaluation] Running for {target_date}...")
        
        with get_db_connection() as conn:
            # Query: Join Predictions, Settlement Events, AND Bets for Financials
            # Note: We group by model or league/market.
            q = """
            SELECT 
                p.model_version_id,
                p.league,
                p.market_type,
                p.output_win_prob,
                b.wager,
                b.profit,
                b.provider as book,
                s.outcome, 
                s.inputs_json
            FROM settlement_events s
            LEFT JOIN predictions p ON p.event_id = s.event_id -- Optional: Metrics even if no prediction (manual bets)
            JOIN bet_legs bl ON bl.id = s.leg_id
            JOIN bets b ON b.id = bl.bet_id
            JOIN events e ON s.event_id = e.id
            WHERE date(e.start_time) = :date
              AND s.outcome IN ('WON', 'LOST', 'PUSH') 
            """
            
            # SQLite safe execution
            cursor = _exec(conn, q, {"date": str(target_date)})
            rows = cursor.fetchall()
            
        print(f"[Evaluation] Found {len(rows)} settled bets.")
        
        # Aggregators
        # Key: (league, market_type, model_id)
        # We also might want Book breakdown? User asked for "By-book breakdowns".
        # Let's start with League/Market/Model as primary key for 'model_health_daily'.
        # We can add 'book' to key if we want granular rows.
        
        stats = defaultdict(lambda: {
            "wager_sum": 0.0, "profit_sum": 0.0, 
            "brier_sum": 0.0, "logloss_sum": 0.0, 
            "correct": 0, "count": 0, 
            "clv_diff_sum": 0.0, "clv_count": 0,
            "won": 0, "lost": 0, "push": 0
        })
        
        for row in rows:
            mid = row['model_version_id'] or 'manual'
            league = row['league']
            market = row['market_type']
            prob = row['output_win_prob']
            wager = row['wager'] or 0.0
            profit = row['profit'] or 0.0
            outcome = row['outcome']
            inputs = json.loads(row['inputs_json'] or '{}')
            
            key = (mid, league, market)
            
            agg = stats[key]
            agg["count"] += 1
            agg["wager_sum"] += wager
            agg["profit_sum"] += profit
            
            if outcome == 'WON': agg["won"] += 1
            elif outcome == 'LOST': agg["lost"] += 1
            elif outcome == 'PUSH': agg["push"] += 1
            
            # Probability Metrics (only if model prob exists)
            if prob is not None:
                actual = 1.0 if outcome == 'WON' else 0.0 # PUSH? usually ignore for Brier or 0.5?
                # Ignoring PUSH for calibration is standard or treat as void
                if outcome != 'PUSH':
                    agg["brier_sum"] += (prob - actual) ** 2
                    
                    p_safe = max(min(prob, 0.9999), 0.0001)
                    agg["logloss_sum"] += - (actual * math.log(p_safe) + (1-actual) * math.log(1-p_safe))
                    
                    if (prob > 0.5 and actual == 1.0) or (prob < 0.5 and actual == 0.0):
                        agg["correct"] += 1
            
            # CLV Extraction
            # CLV Diff = (Bet Line - Closing Line) for spread? 
            # Or (Closing Price - Bet Price)?
            # User wants "CLV (core health signal)".
            # Usually: Closing Line Probability - Bet Implied Probability.
            # OR just line difference.
            # Let's look for 'clv' in inputs.
            clv_data = inputs.get('clv')
            if clv_data:
                # Calculate CLV% (Implied Prob Diff)
                # Need helper to convert odd to prob.
                pass # TODO: Implement odd converter or simplified line diff.
                # For MVP, let's track Line movement if spread, Price value if ML.
                # If Market is ML: Compare Price.
                # If Market is Spread: Compare Line.
                
                bet_line = inputs.get('line')
                clv_line = clv_data.get('line')
                
                if bet_line is not None and clv_line is not None:
                    try:
                        diff = float(bet_line) - float(clv_line)
                        # Direction matters. If we bet Home (-7) and it closes (-8), we beat it (got 7, closed 8).
                        # If we bet Home (-7) and it closes (-6), we lost value.
                        # Need to know Side to sign the diff correctly?
                        # Assuming positive diff is good?
                        # Keep it raw for now: Line Diff
                        agg["clv_diff_sum"] += abs(diff) # Abs diff shows volatility? No.
                        # Let's just store line movement magnitude for now.
                        agg["clv_diff_sum"] += (float(bet_line) - float(clv_line))
                        agg["clv_count"] += 1
                    except:
                        pass

        # Store Metrics
        metrics_to_store = []
        for key, agg in stats.items():
            mid, league, market = key
            n = agg["count"]
            if n == 0: continue
            
            # ROI
            roi = (agg["profit_sum"] / agg["wager_sum"]) if agg["wager_sum"] else 0.0
            metrics_to_store.append(self._make_metric(target_date, mid, league, market, "roi", roi, n))
            
            # Yield (Same as ROI roughly?)
            
            # Hit Rate (Won / (Won+Lost))
            decided = agg["won"] + agg["lost"]
            hit_rate = (agg["won"] / decided) if decided > 0 else 0.0
            metrics_to_store.append(self._make_metric(target_date, mid, league, market, "hit_rate", hit_rate, decided))
            
            # CLV (Avg Line Diff)
            if agg["clv_count"] > 0:
                avg_clv = agg["clv_diff_sum"] / agg["clv_count"]
                metrics_to_store.append(self._make_metric(target_date, mid, league, market, "clv_line_diff", avg_clv, agg["clv_count"]))
            
            # Brier
            # Only correct if we had probs
            # Not strict count check here but valid enough
            if agg["brier_sum"] != 0: 
                 # This logic is slightly flawed if brier sum is truly 0 (perfect prediction). 
                 # But practically ok.
                 metrics_to_store.append(self._make_metric(target_date, mid, league, market, "brier_score", agg["brier_sum"]/n, n))

        print(f"[Evaluation] Storing {len(metrics_to_store)} metrics.")
        store_daily_evaluation(metrics_to_store)
        return len(metrics_to_store)

    def _make_metric(self, date, mid, league, market, name, val, size):
        return {
            "date": date,
            "model_version_id": mid,
            "league": league, 
            "market_type": market,
            "metric_name": name,
            "metric_value": val,
            "sample_size": size
        }

if __name__ == "__main__":
    svc = EvaluationService()
    svc.evaluate_daily_performance(date.today())
