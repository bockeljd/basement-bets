import math
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
from scipy.stats import norm

from src.services.torvik_projection import TorvikProjectionService
from src.services.odds_selection_service import OddsSelectionService
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
        self.odds_selector = OddsSelectionService()

    def analyze(self, event_id: str, market_snapshot: Optional[Dict] = None, event_context: Optional[Dict] = None) -> Dict:
        """
        On-demand analysis for one game.
        """
        # 1. Load Event (Use context if provided, else DB)
        event = event_context
        if not event:
            event = self._get_event(event_id)
        
        if not event:
            return {"error": f"Event {event_id} not found."}

        if not market_snapshot:
            # New Intelligence: Use OddsSelector for BASELINE (Spread/Total)
            # We want current 'best' line to bet into.
            # Get raw list then select.
            raw_snaps = self._get_all_recent_odds(event_id)
            
            # Select Best Spread (Home)
            snap_spread = self.odds_selector.select_best_snapshot(raw_snaps, 'SPREAD', 'HOME')
            # Select Best Total (Over)
            snap_total = self.odds_selector.select_best_snapshot(raw_snaps, 'TOTAL', 'OVER')
            
            # Composite Snapshot for Analysis (Legacy Support)
            market_snapshot = {
                'spread_home': snap_spread['line_value'] if snap_spread else 0.0,
                'spread_price_home': snap_spread['price'] if snap_spread else -110,
                'book_spread': snap_spread.get('book') if snap_spread else None,
                'total': snap_total['line_value'] if snap_total else 145.0,
                'total_over_price': snap_total['price'] if snap_total else -110,
                'book_total': snap_total.get('book') if snap_total else None,
                # Store full objects for later
                '_raw_spread': snap_spread,
                '_raw_total': snap_total
            }

        # 3. Get Torvik Signals
        torvik_view = self.torvik_service.get_projection(event['home_team'], event['away_team'])
        
        # 4. Market Baselines
        mu_market_spread = market_snapshot.get('spread_home', 0.0)
        mu_market_total = market_snapshot.get('total', 145.0)

        # 5. Blend Math (Strict mu_final)
        # mu_sched_spread needs official_margin
        mu_torvik_spread = -torvik_view.get('margin', 0.0)
        # Safe access to official_margin with fallback
        mu_sched_spread = -torvik_view.get('official_margin', -mu_torvik_spread)

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
        
        # 8. Narrative (UI MATCH)
        narrative = self._generate_narrative(event, market_snapshot, torvik_view, recs)
        
        # 9. Result Object
        # Ensure recommendations schema matches strict UI expectations if needed
        # (UI uses: bet_type, selection, edge, fair_line)
        ui_recs = []
        best_rec = None
        
        for r in recs:
            ui_recs.append({
                "bet_type": r['market'],
                "selection": r['side'] + (f" {r['line']}" if r['line'] else ""),
                "edge": f"{r['ev']:.2f}%",
                "fair_line": str(round(mu_spread_final if r['market']=='SPREAD' else mu_total_final, 1)),
                "confidence": "High" if r['confidence_idx'] > 80 else "Medium" if r['confidence_idx'] > 50 else "Low",
                "book": r['book']
            })
            # Simple "Best" logic: max ev
            if not best_rec or r['ev'] > best_rec['ev']:
                best_rec = r

        res = {
            "id": None, # Will be set below
            "event_id": event_id,
            "analyzed_at": datetime.now().isoformat(),
            "model_version": self.VERSION,
            "market_type": best_rec['market'] if best_rec else "AUTO",
            "pick": best_rec['side'] if best_rec else "NONE",
            "bet_line": best_rec['line'] if best_rec else None,
            "bet_price": best_rec['price'] if best_rec else None,
            "book": best_rec['book'] if best_rec else None,
            "mu_market": mu_market_spread,
            "mu_torvik": mu_torvik_spread,
            "mu_final": mu_spread_final,
            "sigma": sigma_spread,
            "win_prob": best_rec['prob'] if best_rec else 0.5,
            "ev_per_unit": best_rec['ev'] if best_rec else 0.0,
            "confidence_0_100": best_rec['confidence_idx'] if best_rec else 0,
            "inputs_json": json.dumps({"market": market_snapshot, "torvik": torvik_view}),
            "outputs_json": json.dumps({"mu_spread": mu_spread_final, "mu_total": mu_total_final, "recommendations": recs}),
            "narrative": narrative, # Full object for UI
            "narrative_json": json.dumps(narrative),
            "recommendations": ui_recs, # Correct UI Schema
            "torvik_view": torvik_view,
            "key_factors": ["Market Efficiency", "Schedule Adjustment"],
            "risks": narrative['risks'],
            # First-Class Columns
            "selection": best_rec['side'] if best_rec else None,
            "price": best_rec['price'] if best_rec else None,
            "fair_line": mu_spread_final if (best_rec and best_rec['market'] == 'SPREAD') else mu_total_final,
            "edge_points": abs((best_rec['line'] if best_rec else 0) - (mu_spread_final if (best_rec and best_rec['market'] == 'SPREAD') else mu_total_final)), # Rough approx
            "open_line": best_rec['line'] if best_rec else None,
            "open_price": best_rec['price'] if best_rec else None,
            "clv_method": "odds_selector_v1"
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

    def _get_all_recent_odds(self, event_id: str) -> List[Dict]:
        """
        Fetches ALL granular odds snapshots for the selector.
        """
        query = """
        SELECT market_type, side, line_value, price, book, captured_at
        FROM odds_snapshots 
        WHERE event_id = :eid 
        ORDER BY captured_at DESC
        LIMIT 200
        """
        with get_db_connection() as conn:
            rows = _exec(conn, query, {"eid": event_id}).fetchall()
            return [dict(r) for r in rows]

    def _get_latest_odds(self, event_id: str) -> Optional[Dict]:
        # Legacy stub or fallback
        raw = self._get_all_recent_odds(event_id)
        if not raw: return {}
        # Naive approach
        flat = {}
        # ... existing logic ...
        return flat

    def _generate_narrative(self, event, snap, torvik, recs) -> Dict:
        # evidence-backed, no invented facts
        headline = "No Edge Detected"
        rationale = []
        
        rationale.append(f"Market Line: {snap.get('spread_home','N/A')}")
        rationale.append(f"Torvik Proj: {torvik.get('projected_score','N/A')} ({torvik.get('lean','N/A')})")
        
        if recs:
            main = recs[0]
            headline = f"Bet: {main['side']} {main['line'] or ''}"
            rationale.append(f"Model sees {main['ev']:.1f}% EV vs market consensus.")
            
        return {
            "headline": headline,
            "market_summary": f"Line: {snap.get('spread_home','N/A')}  •  Total: {snap.get('total','N/A')}",
            "recommendation": headline,
            "rationale": rationale,
            "torvik_view": torvik.get('lean', 'Computed projections only'),
            "risks": ["Line Movement Volatility", "Late Injury Reports"],
            "data_quality": "High" if snap else "Low"
        }

    def _persist_analysis(self, result: Dict):
        # Deprecated: Called directly in analyze now.
        pass

if __name__ == "__main__":
    # Test stub
    # Requires a valid event_id in DB
    pass
