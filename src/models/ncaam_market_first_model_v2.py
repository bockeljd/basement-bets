import math
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
from scipy.stats import norm

from src.services.torvik_projection import TorvikProjectionService
from src.database import get_db_connection, _exec, insert_model_prediction

class NCAAMMarketFirstModelV2:
    """
    NCAAM Market-First Model v2.
    - Market base with corrective signals.
    - CLV-first gating.
    - Structured narratives.
    """
    
    VERSION = "2.0.0-strict"
    
    # Model Weights
    W_BASE = 0.20  # Market-first blend
    W_SCHED = 0.05 # Torvik schedule-lean weight
    
    # Caps (v2 defaults)
    CAP_SPREAD = 2.0
    CAP_TOTAL = 3.0

    def __init__(self):
        self.torvik_service = TorvikProjectionService()

    def analyze(self, event_id: str, market_snapshot: Optional[Dict] = None) -> Dict:
        """
        On-demand analysis for one game.
        """
        # 1. Load Event
        event = self._get_event(event_id)
        if not event:
            return {"error": f"Event {event_id} not found."}

        # 2. Load Odds if not provided
        if not market_snapshot:
            market_snapshot = self._get_latest_odds(event_id)

        # 3. Get Torvik Signals
        # torvik_view['margin'] is the computed metrics-based projection
        # torvik_view['official_margin'] is the schedule-lean if available
        torvik_view = self.torvik_service.get_projection(event['home_team'], event['away_team'])
        
        # 4. Market Baselines
        mu_market_spread = 0.0
        mu_market_total = 145.0
        has_odds = False
        
        if market_snapshot:
            has_odds = True
            mu_market_spread = market_snapshot.get('spread_home', 0.0)
            mu_market_total = market_snapshot.get('total', 145.0)

        # 5. Blend Math (Strict mu_final)
        # Margin: mu_torvik is computed, mu_sched is official
        mu_torvik_spread = -torvik_view.get('margin', 0.0) # margin is home-away, spread is home-relative
        mu_sched_spread = -torvik_view.get('official_margin', mu_torvik_spread)

        diff_torvik = (mu_torvik_spread - mu_market_spread)
        diff_sched = (mu_sched_spread - mu_market_spread)
        
        mu_spread_final = mu_market_spread + (self.W_BASE * diff_torvik) + (self.W_SCHED * diff_sched)
        
        # Apply Caps
        if abs(mu_spread_final - mu_market_spread) > self.CAP_SPREAD:
             mu_spread_final = mu_market_spread + (self.CAP_SPREAD * math.copysign(1, mu_spread_final - mu_market_spread))

        # Total
        mu_torvik_total = torvik_view.get('total', 145.0)
        mu_total_final = mu_market_total + (self.W_BASE * (mu_torvik_total - mu_market_total))
        
        if abs(mu_total_final - mu_market_total) > self.CAP_TOTAL:
             mu_total_final = mu_market_total + (self.CAP_TOTAL * math.copysign(1, mu_total_final - mu_market_total))

        # 6. Sigma
        sigma_spread = 10.5 + 0.1 * abs(diff_torvik)
        sigma_total = 15.0 + 0.1 * abs(mu_torvik_total - mu_market_total)

        # 7. Recommendations & EV
        recs = self._generate_recommendations(mu_spread_final, sigma_spread, mu_total_final, sigma_total, market_snapshot, event)
        
        # 8. Narrative
        narrative = self._generate_narrative(event, market_snapshot, torvik_view, recs)
        
        # 9. Result Object
        res = {
            "id": str(uuid.uuid4()) if 'uuid' in globals() else None, 
            "event_id": event_id,
            "analyzed_at": datetime.now().isoformat(),
            "model_version": self.VERSION,
            "market_type": recs[0]['market'] if recs else "AUTO",
            "pick": recs[0]['side'] if recs else "NONE",
            "bet_line": recs[0]['line'] if recs else None,
            "bet_price": recs[0]['price'] if recs else None,
            "book": recs[0]['book'] if recs else None,
            "mu_market": mu_market_spread,
            "mu_torvik": mu_torvik_spread,
            "mu_final": mu_spread_final,
            "sigma": sigma_spread,
            "win_prob": recs[0]['prob'] if recs else 0.5,
            "ev_per_unit": recs[0]['ev'] if recs else 0.0,
            "confidence_0_100": recs[0]['confidence_idx'] if recs else 0,
            "inputs_json": json.dumps({"market": market_snapshot, "torvik": torvik_view}),
            "outputs_json": json.dumps({"mu_spread": mu_spread_final, "mu_total": mu_total_final}),
            "narrative": narrative,
            "narrative_json": json.dumps(narrative),
            "recommendations": recs, # For UI
            "torvik_view": torvik_view # For UI
        }
        
        # Fix id if uuid not imported globally
        if not res['id']:
            import uuid
            res['id'] = str(uuid.uuid4())

        # 10. Persist
        insert_model_prediction(res)
        
        return res

    def _generate_recommendations(self, mu_s, sig_s, mu_t, sig_t, snap, event) -> List[Dict]:
        recs = []
        if not snap: return recs
        
        # In a real granular snap, we'd have multiple rows. 
        # For simplicity, if passed a flat dict or first found market:
        
        # Spread
        line = snap.get('spread_home')
        price = snap.get('spread_price_home')
        if line is not None and price is not None:
            # P(home covers) = P(margin > -line)
            # mu_s is predicted home spread (v2 convention)
            # Actually let's use Normal CDF Logic:
            # Home cover prob = 1 - CDF( -line )
            prob_home = 1.0 - norm.cdf(-line, mu_s, sig_s)
            
            # EV Calculation
            ev = self._calculate_ev(prob_home, price)
            
            if abs(ev) > 0.01: # 1% EV threshold
                 recs.append({
                     "market": "SPREAD",
                     "side": event['home_team'] if ev > 0 else event['away_team'],
                     "line": line if ev > 3 else -line, # simplification
                     "price": price,
                     "prob": round(prob_home if ev > 0 else (1-prob_home), 3),
                     "ev": round(ev, 3),
                     "confidence_idx": int(min(100, abs(ev)*2000)),
                     "book": snap.get('book', 'consensus'),
                     "is_actionable": self._check_clv_gate("SPREAD")
                 })
        return recs

    def _calculate_ev(self, prob: float, american_odds: int) -> float:
        if american_odds > 0:
            multiplier = american_odds / 100.0
        else:
            multiplier = 100.0 / abs(american_odds)
        
        return (prob * multiplier) - (1 - prob)

    def _check_clv_gate(self, market_type: str) -> bool:
        # Strict requirement: only actionable if rolling CLV trend is positive.
        # For MVP, return True but placeholder for actual check.
        return True

    def _get_event(self, event_id: str) -> Optional[Dict]:
        query = "SELECT * FROM events WHERE id = :id"
        with get_db_connection() as conn:
            row = _exec(conn, query, {"id": event_id}).fetchone()
            if row:
                return dict(row)
        return None

    def _get_latest_odds(self, event_id: str) -> Optional[Dict]:
        """
        Fetches the latest granular odds snapshots and flattens them for the model.
        Target keys: spread_home, total, ml_home, etc.
        """
        query = """
        SELECT market_type, side, line_value, price, book, captured_at
        FROM odds_snapshots 
        WHERE event_id = :eid 
        ORDER BY captured_at DESC
        """
        
        with get_db_connection() as conn:
            rows = _exec(conn, query, {"eid": event_id}).fetchall()
            if not rows:
                return {}
            
            # We want to flatten the most recent snapshot per (market_type, side)
            # Since they are ordered by captured_at DESC, the first one we see is the latest.
            flat = {}
            seen = set()
            
            for row in rows:
                mkt = row['market_type']
                side = row['side']
                key = f"{mkt}|{side}"
                
                if key in seen:
                    continue
                seen.add(key)
                
                # Standardize keys for the model
                if mkt == 'SPREAD':
                    if side == 'HOME':
                        flat['spread_home'] = row['line_value']
                        flat['spread_home_price'] = row['price']
                    elif side == 'AWAY':
                        flat['spread_away'] = row['line_value']
                        flat['spread_away_price'] = row['price']
                elif mkt == 'TOTAL':
                    # Both sides usually have the same line, but we'll store it
                    flat['total'] = row['line_value'] 
                    if side == 'OVER':
                        flat['total_over_price'] = row['price']
                    elif side == 'UNDER':
                        flat['total_under_price'] = row['price']
                elif mkt == 'ML' or mkt == 'MONEYLINE':
                    if side == 'HOME':
                        flat['ml_home'] = row['price']
                    elif side == 'AWAY':
                        flat['ml_away'] = row['price']
                
                # Also store the book for the first one we find
                if 'book' not in flat:
                    flat['book'] = row['book']

            return flat

    def _generate_narrative(self, event, snap, torvik, recs) -> Dict:
        # evidence-backed, no invented facts
        headline = "No Edge Detected"
        if recs:
            headline = f"Edge Found: {recs[0]['side']} {recs[0].get('line','')}"
            
        return {
            "headline": headline,
            "market_summary": f"Line: {snap.get('spread_home','N/A')}, Total: {snap.get('total','N/A')}",
            "torvik_view": torvik.get('lean', 'Computed projections only'),
            "recommendation": headline,
            "risks": ["Pace variance", "Foul variance"],
            "data_quality": "High" if snap else "Low"
        }

    def _persist_analysis(self, result: Dict):
        # Deprecated: Called directly in analyze now.
        pass

if __name__ == "__main__":
    # Test stub
    # Requires a valid event_id in DB
    pass
