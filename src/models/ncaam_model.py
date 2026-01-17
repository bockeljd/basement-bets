import pandas as pd
import numpy as np
import math
from typing import Dict, Any, List, Optional
from src.models.base_model import BaseModel
from src.models.schemas import MarketSnapshot, TorvikMetrics, Signal, ModelSnapshot, PredictionResult, PredictionComponent, OpportunityRanking

class NCAAMModel(BaseModel):
    def __init__(self):
        super().__init__(sport_key="basketball_ncaab")
        self.team_stats = {} # Map of team -> {adj_eff, tempo}
        self.league_avg_eff = 105.0
        self.league_avg_tempo = 68.5

    def fetch_data(self):
        """
        Fetch dynamic efficiency ratings.
        Priority: 
        1. Local DB (persisted from previous cron job).
        2. Live fetch (via BartTorvikClient).
        3. Hardcoded fallback.
        """
        from src.database import get_db_connection, _exec
        from datetime import datetime
        
        today = datetime.now().strftime("%Y-%m-%d")
        
        # 1. Try DB
        try:
            with get_db_connection() as conn:
                rows = _exec(conn, "SELECT team_text, adj_off, adj_def, adj_tempo FROM bt_team_metrics_daily WHERE date = :date", {"date": today}).fetchall()
                
            if rows:
                print(f"[NCAAM] Loaded {len(rows)} team ratings from DB ({today}).")
                self.team_stats = {}
                for r in rows:
                    self.team_stats[r['team_text']] = {
                        "eff_off": r['adj_off'],
                        "eff_def": r['adj_def'],
                        "tempo": r['adj_tempo']
                    }
                return # Done
        except Exception as e:
            print(f"[NCAAM] DB fetch failed (might be empty/missing table): {e}")

        # 2. Live Fetch
        print("[NCAAM] Fetching live from BartTorvik...")
        from src.services.barttorvik import BartTorvikClient
        client = BartTorvikClient()
        ratings = client.get_efficiency_ratings(year=2026)
        
        # Normalize keys to match Model expectation (eff_off, eff_def)
        self.team_stats = {}
        if ratings:
            for team, stats in ratings.items():
                self.team_stats[team] = {
                    "eff_off": stats.get('off_rating'),
                    "eff_def": stats.get('def_rating'),
                    "tempo": stats.get('tempo')
                }
        
        # 3. Fallback
        if not self.team_stats:
            print("[NCAAM] Warning: Using fallback MVP stats.")
            self.team_stats = {
             "Houston": {"eff_off": 118.5, "eff_def": 87.0, "tempo": 63.5},
            }

    def canonicalize_market(self, market: MarketSnapshot) -> MarketSnapshot:
        """
        Enforce canonical rules:
        - Spread is always Home - Away.
        - If input had explicit home/away, we trust it.
        """
        # In v1, we rely on the ingestion layer to populate 'spread_home' correctly.
        # If we had raw fields like 'spread_team_1' we would need mapping logic here.
        # For now, we return as is, assuming 'spread_home' is chemically pure (Home - Away).
        return market

    def compute_torvik_projection(self, metrics: TorvikMetrics) -> Dict[str, float]:
        """
        Compute projected score based on efficiency ratings.
        """
        # Baseline Logic (V1 Simple)
        avg_poss = (metrics.tempo_home + metrics.tempo_away) / 2.0
        
        lg_avg = 105.0
        
        # Additive approximation for PPP
        ppp_home = (metrics.adj_oe_home + metrics.adj_de_away - lg_avg) / 100.0
        ppp_away = (metrics.adj_oe_away + metrics.adj_de_home - lg_avg) / 100.0
        
        score_home = avg_poss * ppp_home
        score_away = avg_poss * ppp_away
        
        if not metrics.is_neutral:
            # Add HFA to Home Score (approx 3.2 pts total margin swing)
            # Typically 1.6 pts added to home, 1.6 deducted from away (relative to neutral)
            hfa = 3.2
            score_home += (hfa / 2)
            score_away -= (hfa / 2)
            
        return {
            "score_home": score_home,
            "score_away": score_away,
            "margin": score_home - score_away, # +ve means Home Wins
            "total": score_home + score_away
        }

    def predict_v1(self, home_team: str, away_team: str, market: MarketSnapshot, signals: List[Signal] = []) -> Optional[ModelSnapshot]:
        """
        Market-First V1 Prediction.
        """
        # 1. Fetch Metrics
        t_home = self.team_stats.get(home_team, {})
        t_away = self.team_stats.get(away_team, {})
        
        if not t_home or not t_away:
             # Try fuzzy match if exact fail
             t_home = self.get_team_stats(home_team) or {}
             t_away = self.get_team_stats(away_team) or {}
        
        if not t_home or not t_away:
             print(f"[NCAAM] WARN: Missing stats for {home_team} or {away_team}")
             return None
             
        torvik_metrics = TorvikMetrics(
            adj_oe_home=t_home.get('eff_off', 105.0),
            adj_de_home=t_home.get('eff_def', 105.0),
            adj_oe_away=t_away.get('eff_off', 105.0),
            adj_de_away=t_away.get('eff_def', 105.0),
            tempo_home=t_home.get('tempo', 68.0),
            tempo_away=t_away.get('tempo', 68.0),
            is_neutral=False # TODO: Source from event context
        )
        
        # 3. Canonicalize
        market = self.canonicalize_market(market)
        
        # 4. Compute Torvik Projection
        proj = self.compute_torvik_projection(torvik_metrics)
        mu_torvik_margin = proj["margin"]
        mu_torvik_total = proj["total"]
        
        # 5. Compute Deltas (Torvik - Market)
        mu_market_margin = -market.spread_home
        mu_market_total = market.total_line
        
        delta_margin = mu_torvik_margin - mu_market_margin
        delta_total = mu_torvik_total - mu_market_total
        
        # 6. Signal Adjustments
        signal_adj_margin = 0.0
        signal_adj_total = 0.0
        conf_signals_agg = 0.0 # Average confidence of active signals
        
        if signals:
            weighted_conf_sum = 0
            for sig in signals:
                impact = sig.impact_points
                # Bounded impact rules
                if abs(impact) > 3.0: impact = 3.0 * (1 if impact > 0 else -1)
                
                if sig.target == "HOME":
                    signal_adj_margin += impact
                elif sig.target == "AWAY":
                    signal_adj_margin -= impact 
                elif sig.target == "TOTAL":
                    signal_adj_total += impact
                
                weighted_conf_sum += sig.confidence
            
            conf_signals_agg = weighted_conf_sum / len(signals)
        else:
            conf_signals_agg = 1.0 # No signals = No uncertainty penalty from signals
        
        # 7. Blending (Weights)
        w_margin = 0.20
        w_total = 0.25
        
        mu_final_margin = mu_market_margin + (w_margin * delta_margin) + signal_adj_margin
        mu_final_total = mu_market_total + (w_total * delta_total) + signal_adj_total
        
        # 8. Probabilities (Normal CDF)
        def normal_cdf(x, mu, sigma):
            return 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))
        
        sigma_margin = 10.5
        sigma_total = 18.0
        
        # Expansion if high disagreement
        sigma_margin *= (1 + 0.05 * abs(delta_margin))
        sigma_total *= (1 + 0.03 * abs(delta_total))
        
        # Expansion if low confidence signals (or no info?)
        # Spec: (1 + beta * (1 - conf))
        if signals:
            sigma_margin *= (1 + 0.1 * (1.0 - conf_signals_agg))
        
        # Calc Probs
        # Spread Cover Prob (Home covers spread)
        # Market Spread = -5.5. Home must win by > 5.5.
        # Threshold = -Spread.
        threshold_margin = -market.spread_home
        prob_cover = 1.0 - normal_cdf(threshold_margin, mu_final_margin, sigma_margin)
        
        # Total Over Prob
        prob_over = 1.0 - normal_cdf(market.total_line, mu_final_total, sigma_total)
        
        # 9. Edges & Ranking
        implied_home = 0.5238 # -110 standard
        if market.moneyline_home:
            # Convert ML to prob? For now static checks
            pass
            
        edge_cover = prob_cover - implied_home
        edge_over = prob_over - 0.5238
        
        # Determines classification
        rank = OpportunityRanking(
            ev_units=edge_cover * 1.0, # Simplistic 1u bet
            edge_margin=mu_final_margin - mu_market_margin, # Diff from market
            confidence_score=75.0, # Placeholder
            is_allowed=True
        )
        
        return ModelSnapshot(
            prediction=PredictionResult(
                score_home=float(proj["score_home"]),
                score_away=float(proj["score_away"]),
                mu_final_margin=float(mu_final_margin),
                mu_final_total=float(mu_final_total),
                prob_cover=float(prob_cover),
                prob_over=float(prob_over),
                edge_cover=float(edge_cover),
                edge_over=float(edge_over)
            ),
            market_snapshot=market,
            torvik_metrics=torvik_metrics,
            components=PredictionComponent(
                mu_market=float(mu_market_margin),
                mu_torvik=float(mu_torvik_margin),
                delta=float(delta_margin),
                signal_adj=float(signal_adj_margin),
                conf_signals=float(conf_signals_agg),
                # Detailed Breakdowns
                mu_market_margin=float(mu_market_margin),
                mu_market_total=float(mu_market_total),
                mu_torvik_margin=float(mu_torvik_margin),
                mu_torvik_total=float(mu_torvik_total),
                delta_margin=float(delta_margin),
                delta_total=float(delta_total),
                mu_final_margin=float(mu_final_margin),
                mu_final_total=float(mu_final_total)
            ),
            ranking=rank
        )

    def get_team_stats(self, team_name: str) -> Dict[str, float]:
        """
        Retrieve stats with fuzzy matching for team names.
        """
        if not self.team_stats:
            self.fetch_data()
            
        # 1. Exact Match
        if team_name in self.team_stats:
            return self.team_stats[team_name]
            
        normalized_input = team_name.lower().replace('.', '').replace(' st', ' state').replace(' (fl)', '').replace(' u', '')
        
        for k, v in self.team_stats.items():
            norm_k = k.lower().replace('.', '').replace(' st', ' state')
            
            # Substring match
            if normalized_input in norm_k or norm_k in normalized_input:
                 return v
                 
            # Specific Overrides
            if "uconn" in normalized_input and "connecticut" in norm_k: return v
            if "mississippi" in normalized_input and "ole miss" in norm_k: return v
            
        # Default Logic
        return {"eff_off": self.league_avg_eff, "eff_def": self.league_avg_eff, "tempo": self.league_avg_tempo}

    def predict(self, game_id: str, home_team: str, away_team: str, market_total: float = 0) -> Dict[str, Any]:
        """
        Legacy predict shim, calling V1 if possible or falling back.
        """
        snapshot = self.predict_v1(
            home_team, 
            away_team, 
            MarketSnapshot(spread_home=0.0, total_line=market_total)
        )
        
        if not snapshot:
            return {"error": "Prediction failed"}
            
        return {
            "game_id": game_id,
            "fair_total": round(snapshot.prediction.mu_final_total * 2) / 2,
            "win_prob": snapshot.prediction.prob_over,
            "edge": snapshot.prediction.edge_over,
            "model_version": "2024-01-14-ncaam-v1"
        }

    def find_edges(self):
        """
        Fetch live odds and compare with model predictions to find edges.
        """
        from src.models.odds_client import OddsAPIClient
        client = OddsAPIClient()
        
        # 1. Fetch Odds
        odds = client.get_odds("basketball_ncaab", regions="us", markets="spreads,totals")
        if not odds:
            print("[NCAAM] No odds found.")
            return []
            
        edges = []
        target_books = ['draftkings', 'fanduel', 'betmgm', 'actionnetwork']
        
        print(f"[NCAAM] Scanning {len(odds)} games for edges...")
        
        for game in odds:
            home_team = game.get('home_team')
            away_team = game.get('away_team')
            game_id = game.get('id')
            commence_time = game.get('commence_time')
            
            # Find Best Lines
            from src.utils.market_micro import MarketMicrostructure
            
            # Aggregate all available lines for Home Spread and Total Over
            spread_outcomes = []
            total_outcomes = []
            
            for book in game.get('bookmakers', []):
                if book['key'] in target_books:
                    current_spread = None
                    current_spread_price = -110
                    
                    current_total = None
                    current_total_price = -110
                    
                    for m in book['markets']:
                        if m['key'] == 'spreads':
                            for o in m['outcomes']:
                                if o['name'] == home_team:
                                    current_spread = o.get('point')
                                    current_spread_price = o.get('price')
                        elif m['key'] == 'totals':
                             for o in m['outcomes']:
                                 if o['name'] == 'Over':
                                     current_total = o.get('point')
                                     current_total_price = o.get('price')
                                     
                    if current_spread is not None:
                        spread_outcomes.append({
                            'book': book['title'], 'point': current_spread, 'price': current_spread_price
                        })
                    if current_total is not None:
                        total_outcomes.append({
                            'book': book['title'], 'point': current_total, 'price': current_total_price
                        })

            # Shop for Best Lines (Maximize Point for Home/Over?)
            # Spread: Buying Home -5 is better than -6. Max point.
            # Total: Buying Over 150 is better than 151. Min point!
            
            best_spread = MarketMicrostructure.get_best_line(spread_outcomes, 'Home')
            # For totals (Over), we want MIN point.
            # get_best_line maximizes. So we might need custom logic or just min() here.
            best_total = min(total_outcomes, key=lambda x: (x.get('point', 9999), -x.get('price', -9999))) if total_outcomes else None
            
            if not best_spread or not best_total:
                continue
                
            ref_spread_home = best_spread['point']
            ref_total = best_total['point']
            ref_book = f"{best_spread['book']} / {best_total['book']}" # Mixed book

                
            # Construct Market Snapshot
            market = MarketSnapshot(
                spread_home=ref_spread_home,
                total_line=ref_total
            )
            
            # Run Model
            snapshot = self.predict_v1(home_team, away_team, market)
            if not snapshot: continue
            
            # Check for Edges
            # 1. Spread Edge
            if abs(snapshot.ranking.edge_margin) >= 1.0:
                edges.append({
                    "game_id": game_id,
                    "game": f"{away_team} @ {home_team}",
                    "matchup": f"{away_team} @ {home_team}",
                    "home_team": home_team,
                    "away_team": away_team,
                    "market": "Spread",
                    "bet_on": home_team if snapshot.ranking.edge_margin > 0 else away_team, # simplistic
                    "line": ref_spread_home,
                    "market_line": ref_spread_home,
                    "model_line": -snapshot.prediction.mu_final_margin, 
                    "fair_line": -snapshot.prediction.mu_final_margin,
                    "edge": round(snapshot.ranking.edge_margin, 2),
                    "ev": round(snapshot.ranking.ev_units, 3),
                    "book": ref_book,
                    "is_actionable": True
                })
                
            # 2. Total Edge
            # If total_delta > 1.0 => Over. If < -1.0 => Under.
            # mu_final_total vs market.total_line
            # Delta = Model - Market
            delta_total = snapshot.prediction.mu_final_total - ref_total
            if abs(delta_total) >= 1.0:
                 edges.append({
                    "game_id": game_id,
                    "game": f"{away_team} @ {home_team}",
                    "matchup": f"{away_team} @ {home_team}",
                    "home_team": home_team,
                    "away_team": away_team,
                    "market": "Total",
                    "bet_on": "OVER" if delta_total > 0 else "UNDER",
                    "line": ref_total,
                    "market_line": ref_total,
                    "model_line": round(snapshot.prediction.mu_final_total, 1),
                    "fair_line": round(snapshot.prediction.mu_final_total, 1),
                    "edge": round(abs(delta_total), 2),
                    "ev": round(snapshot.ranking.ev_units, 3), # Using shared simplistic EV
                    "book": ref_book,
                    "is_actionable": True
                })
        
        print(f"[NCAAM] Found {len(edges)} potential edges.")
        return edges

    def evaluate(self, predictions: List[Dict[str, Any]]):
        pass
