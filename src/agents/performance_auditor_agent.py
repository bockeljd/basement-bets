import datetime
import json
from typing import Any, Dict, List, Optional
from src.agents.base import BaseAgent
from src.database import get_db_connection, _exec

class PerformanceAuditorAgent(BaseAgent):
    """
    Nightly/batch auditor.
    Connects to 'decision_runs' and grades outcomes iteratively via 'game_results'.
    Uses p_fair (model probability) for Brier scoring and computes CLV against
    the closing line captured in odds_snapshots.
    Stores per-league aggregates in 'performance_reports'.
    """
    def execute(self, context: Dict[str, Any], *args, **kwargs) -> Dict[str, Any]:
        target_date_str = context.get('date')  # Format YYYY-MM-DD
        league = context.get('league', 'NCAAM')
        if not target_date_str:
            target_date_str = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
            
        # Target period boundary
        start_ts = f"{target_date_str}T00:00:00Z"
        end_ts = f"{target_date_str}T23:59:59Z"

        with get_db_connection() as conn:
            runs_query = """
            SELECT run_id, payload_json, league FROM decision_runs 
            WHERE created_at >= %s AND created_at <= %s AND status = 'OK'
            """
            runs_rows = _exec(conn, runs_query, (start_ts, end_ts)).fetchall()

            if not runs_rows:
                return {"message": f"No OK decisions observed for {target_date_str}."}

            brier_components: List[float] = []
            clv_components: List[float] = []
            graded_recs = 0
            
            for row in runs_rows:
                payload = json.loads(row['payload_json'])
                recs = payload.get('recommendations', [])
                
                for r in recs:
                    offer = r.get('offer', {})
                    event_id = offer.get('event_id')
                    market_type = offer.get('market_type')
                    side = offer.get('side')
                    
                    if not event_id:
                        continue
                        
                    # Lookup finalized game result
                    res_row = _exec(conn, "SELECT home_score, away_score, final FROM game_results WHERE event_id = %s", (event_id,)).fetchone()
                    
                    if res_row and res_row['final']:
                        actual_outcome: Optional[float] = None
                        if market_type == "SPREAD":
                            home_margin = res_row['home_score'] - res_row['away_score']
                            if offer.get("line") is not None:
                                adj = (home_margin + offer['line']) if side == "HOME" else (-home_margin + offer['line'])
                                if abs(adj) < 1e-9:
                                    pass  # push
                                elif adj > 0:
                                    actual_outcome = 1.0  # Win
                                else:
                                    actual_outcome = 0.0  # Loss
                        elif market_type == "TOTAL":
                            total = res_row['home_score'] + res_row['away_score']
                            if offer.get("line") is not None:
                                diff = total - offer['line']
                                if abs(diff) < 1e-9:
                                    pass  # push
                                elif (side == "OVER" and diff > 0) or (side == "UNDER" and diff < 0):
                                    actual_outcome = 1.0
                                else:
                                    actual_outcome = 0.0

                        if actual_outcome is not None:
                            # Use p_fair (model probability) for Brier score, not implied odds
                            pred_p = float(r.get("p_fair") or 0.5)
                            brier = (pred_p - actual_outcome) ** 2
                            brier_components.append(brier)

                            # CLV: compare model p_fair vs closing line probability
                            closing_p = self._get_closing_prob(conn, event_id, market_type, side)
                            if closing_p is not None:
                                clv = pred_p - closing_p
                                clv_components.append(clv)

                            graded_recs += 1

            mean_brier = (sum(brier_components) / len(brier_components)) if brier_components else 0.0
            mean_clv = (sum(clv_components) / len(clv_components)) if clv_components else None
            pct_positive_clv = (sum(1 for c in clv_components if c > 0) / len(clv_components)) if clv_components else None

            summary = {
                "target_date": target_date_str,
                "league": league,
                "runs_processed": len(runs_rows),
                "total_recommendations_graded": graded_recs,
                "grading_method": "p_fair",
                "mean_brier_score": mean_brier,
                "mean_clv": mean_clv,
                "pct_positive_clv": pct_positive_clv,
                "clv_sample_size": len(clv_components),
            }
            
            insert_perf_sql = """
                INSERT INTO performance_reports (run_date, league, summary_json, created_at)
                VALUES (%s, %s, %s, NOW())
            """
            _exec(conn, insert_perf_sql, (target_date_str, league, json.dumps(summary)))
            conn.commit()

        return summary

    def _get_closing_prob(self, conn, event_id: str, market_type: str, side: str) -> Optional[float]:
        """
        Look up the last captured odds for this market from odds_snapshots (closing line).
        Converts American odds to implied probability.
        """
        try:
            row = _exec(conn, """
                SELECT price FROM odds_snapshots
                WHERE event_id = %s AND market_type = %s AND side = %s
                  AND COALESCE(book, '') NOT IN ('action_open', 'open')
                ORDER BY captured_at DESC, (CASE WHEN book = 'consensus' THEN 0 ELSE 1 END) ASC
                LIMIT 1
            """, (event_id, market_type, side)).fetchone()

            if row and row['price']:
                odds = int(row['price'])
                if odds < 0:
                    return abs(odds) / (abs(odds) + 100.0)
                else:
                    return 100.0 / (odds + 100.0)
        except Exception as e:
            print(f"[PerformanceAuditor] Could not fetch closing prob for {event_id}: {e}")
        return None
