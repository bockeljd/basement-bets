
import math
import json
from datetime import datetime
from typing import Dict, List, Any, Optional

from src.services.torvik_projection import TorvikProjectionService
from src.services.odds_selection_service import OddsSelectionService
from src.services.kenpom_client import KenPomClient
from src.services.news_service import NewsService
from src.services.geo_service import GeoService
from src.database import get_db_connection, _exec, insert_model_prediction

class NCAAMMarketFirstModelV2:
    """
    NCAAM Market-First Model v2.
    - Market base with corrective signals.
    - CLV-first gating.
    - Structured narratives.
    """
    
    VERSION = "2.1.0-accuracy"
    
    # Default Model Weights
    DEFAULT_W_BASE = 0.20  # Market-first blend
    DEFAULT_W_SCHED = 0.05 # Torvik schedule-lean weight
    DEFAULT_W_KENPOM = 0.05 # KenPom efficiency weight
    
    # Default Caps
    DEFAULT_CAP_SPREAD = 2.0
    DEFAULT_CAP_TOTAL = 3.0
    
    # Aggressive Mode Caps
    AGGRESSIVE_CAP_SPREAD = 4.0
    AGGRESSIVE_CAP_TOTAL = 5.0

    def __init__(self, aggressive: bool = False, cap_spread: float = None, cap_total: float = None, manual_adjustments: dict = None):
        """
        Initialize model with configurable parameters.
        
        Args:
            aggressive: If True, use higher caps (4.0/5.0) to catch larger edges.
            cap_spread: Override spread cap (takes precedence over aggressive).
            cap_total: Override total cap (takes precedence over aggressive).
            manual_adjustments: Dict of manual overrides (e.g. {'home_injury': 1.5})
        """
        self.torvik_service = TorvikProjectionService()
        self.odds_selector = OddsSelectionService()
        self.kenpom_client = KenPomClient()
        self.news_service = NewsService()
        self.geo_service = GeoService()
        
        self.manual_adjustments = manual_adjustments or {}
        
        # Set weights
        self.W_BASE = self.DEFAULT_W_BASE
        self.W_SCHED = self.DEFAULT_W_SCHED
        self.W_KENPOM = self.DEFAULT_W_KENPOM
        
        # Set caps (priority: explicit > aggressive > default)
        if cap_spread is not None:
            self.CAP_SPREAD = cap_spread
        elif aggressive:
            self.CAP_SPREAD = self.AGGRESSIVE_CAP_SPREAD
        else:
            self.CAP_SPREAD = self.DEFAULT_CAP_SPREAD
            
        if cap_total is not None:
            self.CAP_TOTAL = cap_total
        elif aggressive:
            self.CAP_TOTAL = self.AGGRESSIVE_CAP_TOTAL
        else:
            self.CAP_TOTAL = self.DEFAULT_CAP_TOTAL

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

        # 2. Market Snapshot - Use CONSENSUS for model input (not best-line outlier)
        raw_snaps = []
        if not market_snapshot:
            raw_snaps = self._get_all_recent_odds(event_id)
            
            # Step A: Get CONSENSUS lines (median of all books) for model input
            consensus_spread = self.odds_selector.get_consensus_snapshot(raw_snaps, 'SPREAD', 'HOME')
            consensus_total = self.odds_selector.get_consensus_snapshot(raw_snaps, 'TOTAL', 'OVER')
            
            # Step B: Get BEST PRICES for later (after we find an edge)
            best_spread_home = self.odds_selector.get_best_price_for_side(raw_snaps, 'SPREAD', 'HOME')
            best_spread_away = self.odds_selector.get_best_price_for_side(raw_snaps, 'SPREAD', 'AWAY')
            best_total_over = self.odds_selector.get_best_price_for_side(raw_snaps, 'TOTAL', 'OVER')
            best_total_under = self.odds_selector.get_best_price_for_side(raw_snaps, 'TOTAL', 'UNDER')
            
            # Composite Snapshot for Analysis (uses CONSENSUS for model math)
            market_snapshot = {
                # Consensus for model input
                'spread_home': consensus_spread['line_value'] if consensus_spread else 0.0,
                'spread_price_home': consensus_spread['price'] if consensus_spread else -110,
                'total': consensus_total['line_value'] if consensus_total else 145.0,
                'total_over_price': consensus_total['price'] if consensus_total else -110,
                'book_spread': 'Consensus',
                'book_total': 'Consensus',
                # Best prices for betting (after edge identified)
                '_best_spread_home': best_spread_home,
                '_best_spread_away': best_spread_away,
                '_best_total_over': best_total_over,
                '_best_total_under': best_total_under,
                # Raw for narrative
                '_raw_snaps': raw_snaps
            }
        else:
            raw_snaps = market_snapshot.get('_raw_snaps', [])

        # 3. Get Signals
        torvik_view = self.torvik_service.get_projection(event['home_team'], event['away_team'])
        torvik_team_stats = self.torvik_service.get_matchup_team_stats(event['home_team'], event['away_team'])
        kenpom_adj = self.kenpom_client.calculate_kenpom_adjustment(event['home_team'], event['away_team'])
        news_context = self.news_service.fetch_game_context(event['home_team'], event['away_team'])
        
        # 4. Market Baselines
        mu_market_spread = market_snapshot.get('spread_home', 0.0)
        mu_market_total = market_snapshot.get('total', 145.0)

        # 5. Blend Math (Strict mu_final)
        mu_torvik_spread = -torvik_view.get('margin', 0.0)
        mu_sched_spread = -torvik_view.get('official_margin', -mu_torvik_spread)
        mu_kenpom_spread = kenpom_adj.get('spread_adj', 0.0) # This is an adjustment, not a raw line.
        # KenPom spread_adj from client: Home - Away efficiency diff. 
        # If Home > Away, it returns positive margin. spread is usually negative for home fav.
        # Wait, calculate_kenpom_adjustment returns spread_adj (points better home is).
        # So fair spread = -spread_adj.
        
        diff_torvik = (mu_torvik_spread - mu_market_spread)
        diff_sched = (mu_sched_spread - mu_market_spread)
        
        # KenPom Integration: 
        # kenpom_adj['spread_adj'] is expected Home margin. So spread = -margin.
        # diff = (-expected_margin) - market_spread
        kp_margin = kenpom_adj.get('spread_adj', 0.0)
        mu_kenpom_line = -kp_margin
        diff_kenpom = (mu_kenpom_line - mu_market_spread)
        
        # --- Feature: Luck Regression ---
        # If a team has high "Luck" (>0.05), they are overperforming and due for regression.
        # We apply a penalty to their projected margin.
        
        # Volatility Check: In November (Month 11), luck is noisy. Scale down.
        luck_scale = 1.0
        try:
             # event['start_time'] is datetime object
             if event['start_time'].month == 11:
                 luck_scale = 0.5
        except Exception:
             pass

        home_luck = (torvik_team_stats.get('home') or {}).get('luck', 0.0) or 0.0
        away_luck = (torvik_team_stats.get('away') or {}).get('luck', 0.0) or 0.0
        
        luck_adjustment = 0.0
        if home_luck > 0.05:
            luck_adjustment += (1.0 * luck_scale) # Home penalty
        if home_luck < -0.05:
            luck_adjustment -= (1.0 * luck_scale) # Home boost
            
        if away_luck > 0.05:
            luck_adjustment -= (1.0 * luck_scale) # Away penalty
        if away_luck < -0.05:
            luck_adjustment += (1.0 * luck_scale) # Away boost
            
        # --- Feature: Continuity / Transfer Portal Factor ---
        # If teams have low continuity, metrics are less reliable early season.
        # We trust the MARKET more.
        home_continuity = (torvik_team_stats.get('home') or {}).get('continuity', 1.0) or 0.7
        away_continuity = (torvik_team_stats.get('away') or {}).get('continuity', 1.0) or 0.7
        
        avg_continuity = (home_continuity + away_continuity) / 2.0
        
        # Dynamic Weights
        w_base = self.W_BASE
        if avg_continuity < 0.5:
             # Low continuity -> Trust Market More (increase W_BASE from 0.20 to 0.40?)
             # Effectively reduces weight of Torvik/KenPom
             # Wait, equation is: mu_market + W * (diff)
             # If we want to stay closer to market, we REDUCE the weights of projections?
             # Or we treat Market as anchor. 
             # Current formula: market + 0.2*(torvik-market).
             # If we want to trust market more, we should LOWER W_BASE.
             # "increase W_BASE (Market Weight)" - wait, W_BASE in my code is strictly applied to Torvik diff?
             # Let's check line 102: mu_spread_final = mu_market + (W_BASE * diff_torvik) ...
             # YES. To trust market MORE, we need SMALLER weights on the diffs.
             w_base = 0.10 # Reduced from 0.20
        
        
        mu_spread_final = mu_market_spread + (w_base * diff_torvik) + (self.W_SCHED * diff_sched) + (self.W_KENPOM * diff_kenpom) + luck_adjustment
        
        # Apply Caps
        if abs(mu_spread_final - mu_market_spread) > self.CAP_SPREAD:
             mu_spread_final = mu_market_spread + (self.CAP_SPREAD * math.copysign(1, mu_spread_final - mu_market_spread))

        # Total
        mu_torvik_total = torvik_view.get('total', 145.0)
        mu_kenpom_total = market_snapshot.get('total', 145.0) + kenpom_adj.get('total_adj', 0.0)
        
        mu_total_final = mu_market_total + (w_base * (mu_torvik_total - mu_market_total)) + (self.W_KENPOM * (mu_kenpom_total - mu_market_total))
        
        if abs(mu_total_final - mu_market_total) > self.CAP_TOTAL:
             mu_total_final = mu_market_total + (self.CAP_TOTAL * math.copysign(1, mu_total_final - mu_market_total))

        # 6. Pace-Adjusted Sigma (Refined)
        # Higher tempo = more possessions = higher variance = wider sigma
        # Scaling: sqrt(tempo / avg) is theoretically correct for variance scaling.
        game_tempo = (torvik_team_stats or {}).get('game_tempo', 68.0) or 68.0
        tempo_factor = math.sqrt(game_tempo / 68.0)
        
        base_sigma_spread = 10.5
        base_sigma_total = 15.0
        
        
        sigma_spread = (base_sigma_spread * tempo_factor) + 0.1 * abs(diff_torvik)
        sigma_total = (base_sigma_total * tempo_factor) + 0.1 * abs(mu_torvik_total - mu_market_total)
        
        # --- Feature: Advanced Home Court (Geo) ---
        # Travel Fatigue & Altitude
        # Neutral Site Detection
        is_neutral = False
        if event_context and event_context.get('neutral_site'):
            is_neutral = True
        elif ' vs ' in f"{event['away_team']} {event['home_team']}" or ' vs. ' in f"{event['away_team']} {event['home_team']}":
             # Extremely crude heuristic: some feeds use "vs" for neutral, "@" for home.
             # But our event['home_team'] is structured.
             # Better: Check if event['site_key'] or similar exists.
             # For now, rely on manual_adjustments or updated parsers.
             pass
             
        if self.manual_adjustments.get('is_neutral'):
            is_neutral = True

        # Altitude
        altitude_adj = self.geo_service.get_altitude_adjustment(event['home_team'], neutral_site=is_neutral)
        if altitude_adj > 0:
            mu_spread_final -= altitude_adj
            
        # Travel
        dist = self.geo_service.calculate_distance(event['home_team'], event['away_team'])
        if dist > 1000 and not is_neutral:
            mu_spread_final -= 0.5

        # --- Feature: Live Injury Impact Toggle ---
        if self.manual_adjustments:
            h_inj = self.manual_adjustments.get('home_injury', 0.0)
            a_inj = self.manual_adjustments.get('away_injury', 0.0)
            mu_spread_final += h_inj
            mu_spread_final -= a_inj

        # --- Feature: Basement Line (Power Rating) ---
        # Calculate a "Pure" line without Market influence for backtesting/CLV.
        # Basement Line = Average(Torvik, KenPom) + Adjustments (Luck, Geo, Injury)
        # Note: KenPom is an adjustment off market? No, it's relative efficiency.
        # But our implementation uses it as an adjustment.
        # Let's reconstruct consistent Basement Line.
        # Torvik: mu_torvik_spread (Projected Margin)
        # KenPom: mu_kenpom_line (Projected Margin)
        # Geo/Luck: Adjustments.
        # Basement Line = Average(Torvik, KenPom) + Adjustments
        
        raw_basement_line = (mu_torvik_spread + mu_kenpom_line) / 2.0
        # Add adjustments (Luck, Geo, Injury)
        raw_basement_line += luck_adjustment
        if altitude_adj > 0: raw_basement_line -= altitude_adj
        if dist > 1000 and not is_neutral: raw_basement_line -= 0.5
        if self.manual_adjustments:
            raw_basement_line += self.manual_adjustments.get('home_injury', 0.0)
            raw_basement_line -= self.manual_adjustments.get('away_injury', 0.0)
            
        # 7. Recommendations & EV
        recs = self._generate_recommendations(mu_spread_final, sigma_spread, mu_total_final, sigma_total, market_snapshot, event)
        
        debug_info = {
            "mu_spread_final": mu_spread_final,
            "sigma_spread": sigma_spread,
            "tempo_factor": tempo_factor,
            "luck_adj": luck_adjustment,
            "geo_adj": altitude_adj if 'altitude_adj' in locals() else 0.0,
            "is_neutral": is_neutral,
            "basement_line": raw_basement_line  # Pure Power Rating Line
        }
        
        # 8. Narrative (UI MATCH)
        # Pass raw odds so we can generate matchup-specific key factors (e.g., line movement)
        narrative = self._generate_narrative(event, market_snapshot, torvik_view, kenpom_adj, news_context, recs, raw_snaps=raw_snaps)
        
        # 9. Result Object
        ui_recs = []
        best_rec = None

        # Basic game script (team-efficiency driven; Torvik)
        game_script = []
        try:
            h = (torvik_team_stats or {}).get('home') or {}
            a = (torvik_team_stats or {}).get('away') or {}
            tempo = (torvik_team_stats or {}).get('game_tempo')
            if tempo is not None:
                pace_label = 'fast' if tempo >= 71 else 'average' if tempo >= 67 else 'slow'
                game_script.append(f"Expected pace: {pace_label} (~{tempo} possessions).")

            # Mismatch style explanations (adj_off vs opp adj_def)
            # Note: adj_def is points allowed per 100 (lower is better).
            if h.get('adj_off') is not None and a.get('adj_def') is not None:
                game_script.append(f"Home offense ({h['adj_off']:.1f} AdjO) vs away defense ({a['adj_def']:.1f} AdjD) drives home scoring projection.")
            if a.get('adj_off') is not None and h.get('adj_def') is not None:
                game_script.append(f"Away offense ({a['adj_off']:.1f} AdjO) vs home defense ({h['adj_def']:.1f} AdjD) drives away scoring projection.")

            # Late-game / variance callouts
            game_script.append("Spread outcomes are most sensitive to turnover margin and late free throws (end-game fouling).")
        except Exception:
            game_script = []

        
        for r in recs:
            # Provide side-relative market + fair lines so UI can explain meaning.
            market_line_side = None
            fair_line_side = None
            edge_points_side = None
            win_prob = r.get('win_prob')

            if r['market'] == 'SPREAD':
                market_home = market_snapshot.get('spread_home')
                fair_home = mu_spread_final

                # Convert to the side being bet (home vs away)
                if r['side'] == event['home_team']:
                    market_line_side = market_home
                    fair_line_side = fair_home
                else:
                    market_line_side = (-market_home) if market_home is not None else None
                    fair_line_side = (-fair_home) if fair_home is not None else None

                if (market_line_side is not None) and (fair_line_side is not None):
                    # Points you are getting vs model fair (positive = better for bettor)
                    edge_points_side = round(float(market_line_side) - float(fair_line_side), 1)

            elif r['market'] == 'TOTAL':
                market_total = market_snapshot.get('total')
                fair_total = mu_total_final
                market_line_side = market_total
                fair_line_side = fair_total
                if (market_line_side is not None) and (fair_line_side is not None):
                    # For totals, interpret edge points as difference in line (direction depends on OVER/UNDER)
                    edge_points_side = round(float(fair_line_side) - float(market_line_side), 1)

            ui_recs.append({
                "bet_type": r['market'],
                "selection": r['side'] + (f" {r['line']}" if r['line'] is not None else ""),
                # Keep legacy key name for UI, but this is EV% not points.
                "edge": f"{(r['ev']*100):.2f}%",
                "win_prob": round(float(win_prob), 3) if win_prob is not None else None,
                "market_line": (round(float(market_line_side), 1) if market_line_side is not None else None),
                "fair_line": (round(float(fair_line_side), 1) if fair_line_side is not None else None),
                "edge_points": edge_points_side,
                "confidence": "High" if r['ev'] * 100 * 5 > 80 else "Medium" if r['ev'] * 100 * 5 > 50 else "Low", # Using new confidence calc
                "book": r['book']
            })
            if not best_rec or r['ev'] > best_rec['ev']:
                best_rec = r

        res = {
            "id": None, 
            "event_id": event_id,
            "home_team": event['home_team'],
            "away_team": event['away_team'],
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
            "win_prob": best_rec['win_prob'] if best_rec else 0.5,
            "ev_per_unit": best_rec['ev'] if best_rec else 0.0,
            "kelly": best_rec['kelly'] if best_rec else 0.0,
            "confidence_0_100": int(best_rec['ev'] * 100 * 5) if best_rec else 0, # Crude scale
            "inputs_json": json.dumps({"market": market_snapshot, "torvik": torvik_view, "kenpom": kenpom_adj, "news": news_context}, default=str),
            "outputs_json": json.dumps({"mu_spread": mu_spread_final, "mu_total": mu_total_final, "recommendations": recs}, default=str),
            "narrative": narrative, 
            "narrative_json": json.dumps(narrative, default=str),
            "recommendations": ui_recs,
            "torvik_view": torvik_view,
            "torvik_team_stats": torvik_team_stats,
            "game_script": game_script,
            "kenpom_data": kenpom_adj,
            "news_summary": self.news_service.summarize_impact(news_context),
            "key_factors": narrative.get('key_factors') or [],
            "risks": narrative.get('risks') or [],
            "selection": best_rec['side'] if best_rec else None,
            "price": best_rec['price'] if best_rec else None,
            "basement_line": mu_spread_final if (best_rec and best_rec['market'] == 'SPREAD') else mu_total_final,
            "edge_points": abs((best_rec['line'] if best_rec else 0) - (mu_spread_final if (best_rec and best_rec['market'] == 'SPREAD') else mu_total_final)), 
            "open_line": best_rec['line'] if best_rec else None,
            "open_price": best_rec['price'] if best_rec else None,
            "clv_method": "odds_selector_v1",
            "debug": debug_info
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
        
        # Helper: Push probability for whole-number lines
        def get_push_prob(line, sigma):
            """Estimate push probability for whole-number lines."""
            if line is None:
                return 0.0
            # If half-point line (e.g., -5.5), no push possible
            if line % 1 != 0:
                return 0.0
            # For whole-number lines, estimate P(margin == line) using PDF approximation
            # Approximate: push_prob ≈ 0.05 for common numbers, 0.03 otherwise
            key_numbers = {2, 3, 4, 5, 6, 7, 10, 14}
            if abs(line) in key_numbers:
                return 0.05
            return 0.03
        
        # --- Spread ---
        line_s = snap.get('spread_home')
        
        # Get best prices: use actual from snapshot if available, else consensus
        best_home = snap.get('_best_spread_home')
        best_away = snap.get('_best_spread_away')
        
        price_home = best_home['price'] if best_home else snap.get('spread_price_home', -110)
        price_away = best_away['price'] if best_away else -110
        book_home = best_home['book'] if best_home else snap.get('book_spread', 'Consensus')
        book_away = best_away['book'] if best_away else snap.get('book_spread', 'Consensus')
        
        if line_s is not None:
            # Calculate Home Side
            # Correct formula: P(Home Covers) = P(Margin > -Spread)
            # Margin = Home Score - Away Score (positive = home wins)
            # Spread = Home's spread (negative = favorite, positive = underdog)
            # Home at -3.5 covers if Margin > 3.5 = P(X > -(-3.5)) = P(X > 3.5)
            # Home at +10.5 covers if Margin > -10.5 = P(X > -(10.5)) = P(X > -10.5)
            # General: P(Margin > -Spread) = 1 - CDF(-Spread, mean_margin, sigma)
            # mu_s is Expected SPREAD (e.g. -5). Expected Margin is -mu_s (e.g. +5).
            prob_home_raw = 1.0 - self._normal_cdf(-line_s, -mu_s, sig_s)
            
            push_prob = get_push_prob(line_s, sig_s)
            # Adjust: subtract half of push probability
            prob_home = prob_home_raw - (push_prob / 2)
            
            # EV for Home (using best available price)
            ev_home = self._calculate_ev(prob_home, price_home)
            kelly_home = self._calculate_kelly(prob_home, price_home)
            
            # Away side
            prob_away = (1.0 - prob_home_raw) - (push_prob / 2)
            ev_away = self._calculate_ev(prob_away, price_away)
            kelly_away = self._calculate_kelly(prob_away, price_away)
            
            threshold = 0.01
            
            if ev_home > threshold:
                # Home Bet
                recs.append({
                    "market": "SPREAD",
                    "side": event['home_team'],
                    "line": best_home['line_value'] if best_home else line_s,
                    "price": price_home,
                    "prob": round(prob_home, 3), # implied prob inverse? No, this is Model Win Prob.
                    "win_prob": round(prob_home, 3),
                    "ev": round(ev_home, 3),
                    "kelly": round(kelly_home, 3),
                    "book": book_home
                })
            elif ev_away > threshold:
                # Away Bet
                recs.append({
                    "market": "SPREAD",
                    "side": event['away_team'],
                    "line": best_away['line_value'] if best_away else -line_s,
                    "price": price_away,
                    "prob": round(prob_away, 3),
                    "win_prob": round(prob_away, 3),
                    "ev": round(ev_away, 3),
                    "kelly": round(kelly_away, 3),
                    "book": book_away
                })

        # --- Total ---
        line_t = snap.get('total')
        
        # Get best prices for totals
        best_over = snap.get('_best_total_over')
        best_under = snap.get('_best_total_under')
        
        price_over = best_over['price'] if best_over else snap.get('total_over_price', -110)
        price_under = best_under['price'] if best_under else -110
        book_over = best_over['book'] if best_over else snap.get('book_total', 'Consensus')
        book_under = best_under['book'] if best_under else snap.get('book_total', 'Consensus')
        
        if line_t is not None:
            # Prob Over = P(score > line)
            prob_over_raw = 1.0 - self._normal_cdf(line_t, mu_t, sig_t)
            push_prob_t = get_push_prob(line_t, sig_t)
            prob_over = prob_over_raw - (push_prob_t / 2)
            prob_under = (1.0 - prob_over_raw) - (push_prob_t / 2)
            
            ev_over = self._calculate_ev(prob_over, price_over)
            kelly_over = self._calculate_kelly(prob_over, price_over)
            ev_under = self._calculate_ev(prob_under, price_under)
            kelly_under = self._calculate_kelly(prob_under, price_under)
            
            threshold = 0.01
            
            if ev_over > threshold:
                # Over Bet
                recs.append({
                    "market": "TOTAL",
                    "side": "OVER",
                    "line": best_over['line_value'] if best_over else line_t,
                    "price": price_over,
                    "prob": round(prob_over, 3),
                    "win_prob": round(prob_over, 3),
                    "ev": round(ev_over, 3),
                    "kelly": round(kelly_over, 3),
                    "book": book_over
                })
            elif ev_under > threshold:
                # Under Bet
                recs.append({
                    "market": "TOTAL",
                    "side": "UNDER",
                    "line": best_under['line_value'] if best_under else line_t,
                    "price": price_under,
                    "prob": round(prob_under, 3),
                    "win_prob": round(prob_under, 3),
                    "ev": round(ev_under, 3),
                    "kelly": round(kelly_under, 3),
                    "book": book_under
                })
                 
        return recs

    def _normal_cdf(self, x, mu, sigma):
        return 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))

    def _calculate_ev(self, win_prob, price):
        """
        Calculate Estimated Value (ROI)
        EV = (Win_Prob * Profit) - (Loss_Prob * Wager)
        Normalized to 1 unit wager.
        """
        if price > 0:
            payout = price / 100.0
        else:
            payout = 100.0 / abs(price)
            
        ev = (win_prob * payout) - (1.0 - win_prob)
        return ev

    def _calculate_kelly(self, win_prob, price):
        """
        Calculate Kelly Criterion optimal stake fraction.
        f = (bp - q) / b
        b = net odds received (decimal - 1)
        p = win probability
        q = loss probability
        """
        if price > 0:
            b = price / 100.0
        else:
            b = 100.0 / abs(price)
            
        p = win_prob
        q = 1.0 - p
        
        fraction = (b * p - q) / b
        
        # Quarter Kelly for safety
        return max(0.0, fraction * 0.25)

    def _generate_narrative(self, event, snap, torvik, kenpom, news, recs, raw_snaps: Optional[List[Dict]] = None) -> Dict:
        """Generate matchup-specific narrative + factors.

        IMPORTANT: key_factors/risks must be specific to this matchup, not generic labels.
        """
        headline = "No Edge Detected"
        rationale: List[str] = []
        key_factors: List[str] = []
        risks: List[str] = []

        spread_mkt = snap.get('spread_home', None)
        total_mkt = snap.get('total', None)

        # --- Line movement (best effort) ---
        line_move = None
        try:
            if raw_snaps:
                home_spreads = [s for s in raw_snaps if s.get('market_type') == 'SPREAD' and s.get('side') == 'HOME' and s.get('line_value') is not None]
                if home_spreads:
                    latest = home_spreads[0].get('line_value')
                    earliest = home_spreads[-1].get('line_value')
                    if latest is not None and earliest is not None:
                        line_move = float(latest) - float(earliest)
        except Exception:
            line_move = None

        # --- Core rationale strings (still specific) ---
        if spread_mkt is not None:
            rationale.append(f"Market spread (home): {spread_mkt:+.1f}")
        if total_mkt is not None:
            rationale.append(f"Market total: {float(total_mkt):.1f}")

        # Torvik
        if torvik:
            try:
                margin = float(torvik.get('margin', 0.0))
                # torvik margin is (home - away). fair spread is -margin.
                fair_spread_torvik = -margin
                if spread_mkt is not None:
                    delta = fair_spread_torvik - float(spread_mkt)
                    key_factors.append(f"Torvik margin {margin:+.1f} → fair spread {fair_spread_torvik:+.1f} (Δ vs market {delta:+.1f})")
            except Exception:
                pass
            if torvik.get('projected_score'):
                rationale.append(f"Torvik projected score: {torvik.get('projected_score')}")
            if torvik.get('lean'):
                rationale.append(f"Torvik lean: {torvik.get('lean')}")

        # KenPom
        try:
            kp_margin = kenpom.get('spread_adj', None)
            if kp_margin is not None:
                kp_margin = float(kp_margin)
                fair_spread_kp = -kp_margin
                if spread_mkt is not None:
                    delta = fair_spread_kp - float(spread_mkt)
                    key_factors.append(f"KenPom expected margin {kp_margin:+.1f} → fair spread {fair_spread_kp:+.1f} (Δ vs market {delta:+.1f})")
            if kenpom.get('total_adj') is not None and total_mkt is not None:
                key_factors.append(f"KenPom total adj {float(kenpom.get('total_adj')):+.1f} (market {float(total_mkt):.1f})")
        except Exception:
            pass

        # News
        if news:
            if news.get('has_injury_news'):
                key_factors.append(f"Injury/news: {news.get('summary')}")
            else:
                # Still matchup-specific: we looked and found none
                risks.append("No meaningful injury/rotation news detected (risk: late scratches)")

        # Market movement risk (if any)
        if line_move is not None and abs(line_move) >= 1.0:
            risks.append(f"Line moved {line_move:+.1f} pts recently (market disagreement / timing risk)")

        # Recommendation framing
        if recs:
            main = recs[0]
            headline = f"Bet: {main['side']} {main['line'] or ''}".strip()
            try:
                ev_pct = float(main.get('ev', 0.0)) * 100.0
                rationale.append(f"Model EV vs price: {ev_pct:+.1f}%")
            except Exception:
                pass

        # Data quality risk
        if not snap:
            risks.append("Missing market snapshot for this matchup (defaults used)")

        # If still empty, make it explicit but not generic
        if not key_factors:
            key_factors.append("No strong model-vs-market discrepancies detected for this matchup")

        return {
            "headline": headline,
            "market_summary": f"Line: {snap.get('spread_home','N/A')}  •  Total: {snap.get('total','N/A')}",
            "recommendation": headline,
            "rationale": rationale,
            "key_factors": key_factors,
            "risks": risks,
            "torvik_view": torvik.get('lean', 'Computed projections only') if torvik else 'Computed projections only',
            "kenpom_view": kenpom.get('summary', 'No Data') if kenpom else 'No Data',
            "news_view": news.get('summary', 'No News') if news else 'No News',
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
