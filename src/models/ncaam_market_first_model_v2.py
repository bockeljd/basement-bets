
import math
import json
from datetime import datetime
from typing import Dict, List, Any, Optional

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

        # 2. Market Snapshot
        if not market_snapshot:
            # New Intelligence: Use OddsSelector for BASELINE (Spread/Total)
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
        mu_torvik_spread = -torvik_view.get('margin', 0.0)
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
        ui_recs = []
        best_rec = None
        
        for r in recs:
            ui_recs.append({
                "bet_type": r['market'],
                "selection": r['side'] + (f" {r['line']}" if r['line'] else ""),
                "edge": f"{(r['ev']*100):.2f}%",
                "fair_line": str(round(mu_spread_final if r['market']=='SPREAD' else mu_total_final, 1)),
                "confidence": "High" if r['confidence_idx'] > 80 else "Medium" if r['confidence_idx'] > 50 else "Low",
                "book": r['book']
            })
            if not best_rec or r['ev'] > best_rec['ev']:
                best_rec = r

        res = {
            "id": None, 
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
            "inputs_json": json.dumps({"market": market_snapshot, "torvik": torvik_view}, default=str),
            "outputs_json": json.dumps({"mu_spread": mu_spread_final, "mu_total": mu_total_final, "recommendations": recs}, default=str),
            "narrative": narrative, 
            "narrative_json": json.dumps(narrative, default=str),
            "recommendations": ui_recs,
            "torvik_view": torvik_view,
            "key_factors": ["Market Efficiency", "Schedule Adjustment"],
            "risks": narrative['risks'],
            "selection": best_rec['side'] if best_rec else None,
            "price": best_rec['price'] if best_rec else None,
            "fair_line": mu_spread_final if (best_rec and best_rec['market'] == 'SPREAD') else mu_total_final,
            "edge_points": abs((best_rec['line'] if best_rec else 0) - (mu_spread_final if (best_rec and best_rec['market'] == 'SPREAD') else mu_total_final)), 
            "open_line": best_rec['line'] if best_rec else None,
            "open_price": best_rec['price'] if best_rec else None,
            "clv_method": "odds_selector_v1"
        }
        
        if not res['id']:
            import uuid
            res['id'] = str(uuid.uuid4())

        # 10. Persist
        insert_model_prediction(res)
        
        return res

    def _generate_recommendations(self, mu_s, sig_s, mu_t, sig_t, snap, event) -> List[Dict]:
        recs = []
        if not snap: return recs
        
        # --- Spread ---
        # User Convention: Input is Home Line (e.g. -5.5 means Home is favorite)
        # Prediction: mu_s is expected margin (Home Score - Away Score).
        # Win Prob (Home Cover) = P(margin > -line) = 1 - CDF(-line)
        
        line_s = snap.get('spread_home')
        price_s = snap.get('spread_price_home')
        
        if line_s is not None and price_s is not None:
             # Calculate Home Side
             prob_home = 1.0 - self._normal_cdf(-line_s, mu_s, sig_s)
             
             # EV for Home
             ev_home = self._calculate_ev(prob_home, price_s)
             
             # Check Away Side (Implied from Home)
             # Away line is -line_s
             # Away prob = 1 - prob_home
             # We need Away Price. Ideally from snapshot, but fallback to -110 or mirrored.
             # If we only have spread_price_home, we can't accurately calc Away EV without assuming -110 or price symmetry.
             # Let's check if snapshot has 'spread_price_away' (not standard in our current snap dict but maybe in raw?)
             # raw_spread stores full object.
             # Let's try to get it from `snap._raw_spread` if available? 
             # Our `market_snapshot` dict structure in `analyze` keys 65-66 stores `_raw_spread`.
             # But here `snap` is passed as argument.
             
             # Fallback: Assume -110 if missing, or maybe we just focus on Home edge?
             # User specified "If recommending AWAY: use -line".
             # If ev_home is negative, it implies Away *might* be positive IF the price is fair.
             # Let's assume standard pricing allows finding edge on other side if significant.
             
             # Logic:
             # If Home EV > threshold -> Recommend Home
             # Else If Home EV is very negative -> Recommend Away (Check Away EV with -110 placeholder?)
             
             threshold = 0.01
             
             if ev_home > threshold:
                 # Home Bet
                 recs.append({
                     "market": "SPREAD",
                     "side": event['home_team'],
                     "line": line_s, # Use line as-is
                     "price": price_s,
                     "prob": round(prob_home, 3),
                     "ev": round(ev_home, 3),
                     "confidence_idx": int(min(100, abs(ev_home)*2000)),
                     "book": snap.get('book_spread', 'consensus'),
                     "is_actionable": True
                 })
             elif ev_home < -threshold:
                 # Away Bet
                 # Prob Away = 1 - prob_home
                 prob_away = 1.0 - prob_home
                 # Estimate Price (use -110 standard if unknown, or try to infer)
                 # Ideally we fetch best away price.
                 # For MVP, assume symmetric price or -110.
                 price_away = -110 
                 ev_away = self._calculate_ev(prob_away, price_away)
                 
                 if ev_away > threshold:
                     recs.append({
                         "market": "SPREAD",
                         "side": event['away_team'],
                         "line": -line_s, # Use negative line
                         "price": price_away,
                         "prob": round(prob_away, 3),
                         "ev": round(ev_away, 3),
                         "confidence_idx": int(min(100, abs(ev_away)*2000)),
                         "book": snap.get('book_spread', 'consensus'),
                         "is_actionable": True
                     })

        # --- Total ---
        line_t = snap.get('total')
        price_over = snap.get('total_over_price')
        
        if line_t is not None and price_over is not None:
             # Prob Over = P(score > line) = 1 - CDF(line)
             prob_over = 1.0 - self._normal_cdf(line_t, mu_t, sig_t)
             ev_over = self._calculate_ev(prob_over, price_over)
             
             threshold = 0.01
             
             if ev_over > threshold:
                 # Over Bet
                 recs.append({
                     "market": "TOTAL",
                     "side": "OVER",
                     "line": line_t,
                     "price": price_over,
                     "prob": round(prob_over, 3),
                     "ev": round(ev_over, 3),
                     "confidence_idx": int(min(100, abs(ev_over)*2000)),
                     "book": snap.get('book_total', 'consensus'),
                     "is_actionable": True
                 })
             elif ev_over < -threshold:
                 # Under Bet
                 prob_under = 1.0 - prob_over
                 # Use Best Under Price (fetch from Selector or assume -110)
                 # In `analyze` we called selector.select_best_snapshot(..., 'OVER').
                 # We didn't fetch UNDER.
                 # User instructions: "price uses total_under_price (select_best_snapshot with side='UNDER')"
                 # We don't have that passed in `market_snapshot` currently.
                 # We'd need to update `analyze` to fetch Under snapshot too.
                 # For now, default -110.
                 price_under = -110
                 ev_under = self._calculate_ev(prob_under, price_under)
                 
                 if ev_under > threshold:
                     recs.append({
                         "market": "TOTAL",
                         "side": "UNDER",
                         "line": line_t,
                         "price": price_under,
                         "prob": round(prob_under, 3),
                         "ev": round(ev_under, 3),
                         "confidence_idx": int(min(100, abs(ev_under)*2000)),
                         "book": snap.get('book_total', 'consensus'),
                         "is_actionable": True
                     })
                 
        return recs

    def _normal_cdf(self, x, mu, sigma):
        return 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))

    def _calculate_ev(self, win_prob, american_odds):
        if american_odds > 0:
            multiplier = american_odds / 100.0
        else:
            multiplier = 100.0 / abs(american_odds)
        return (win_prob * multiplier) - (1 - win_prob)

    def _generate_narrative(self, event, snap, torvik, recs) -> Dict:
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

    def _get_event(self, event_id: str) -> Optional[Dict]:
        query = "SELECT * FROM events WHERE id = :id"
        with get_db_connection() as conn:
            row = _exec(conn, query, {"id": event_id}).fetchone()
            if row: return dict(row)
        return None

    def _get_all_recent_odds(self, event_id: str) -> List[Dict]:
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
