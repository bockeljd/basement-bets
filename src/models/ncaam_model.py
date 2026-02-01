import datetime
import math
from typing import Dict, Any, List, Optional, Tuple
from src.models.base_model import BaseModel
from src.models.schemas import MarketSnapshot, TorvikMetrics, Signal, ModelSnapshot, PredictionResult, PredictionComponent, OpportunityRanking

# Pure Python Norm CDF (Error Function)
def norm_cdf(x, mu=0.0, sigma=1.0):
    val = (x - mu) / sigma
    return (1.0 + math.erf(val / math.sqrt(2.0))) / 2.0

class NCAAMModel(BaseModel):
    """
    NCAAM Market-First Model (v1).
    Blends Market Consensus with Torvik Efficiency Metrics.
    Now Lightweight (No SciPy/Pandas).
    """
    def __init__(self):
        super().__init__(sport_key="basketball_ncaab")
        self.team_stats = {} # Map of team -> {adj_eff, tempo}
        self.market_allowlist = {} # Map of market -> {status, limits}
        self.model_config = {} # Map of version -> {weights, sigma}
        
        # Initialize ESPN client for injury data
        try:
            from src.services.espn_ncaa_client import ESPNNCAAClient
            self.espn_client = ESPNNCAAClient()
        except Exception as e:
            print(f"[NCAAM] Warning: ESPN client not available: {e}")
            self.espn_client = None
        
    # [Rest of init methods...]
    
    def fetch_data(self):
        """
        Fetch dynamic efficiency ratings.
        Includes caching logic to prevent redundant calls.
        """
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        
        if self.team_stats and getattr(self, 'last_loaded', None) == today:
            return

        from src.database import get_db_connection, _exec
        
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
                self.last_loaded = today
                return # Done
        except Exception as e:
            print(f"[NCAAM] DB fetch failed: {e}")

        # 2. Live Fetch (if DB empty)
        # ... (Same as before)
        # For Vercel safety, if DB fails we rely on fallback MVP stats or minimal fetch
        # Given P0 fix, we trust DB should have data if cron ran.
        
        if not self.team_stats:
             print("[NCAAM] Warning: No stats found. Using fallback.")
             self.team_stats = {
                 "Houston": {"eff_off": 118.5, "eff_def": 87.0, "tempo": 63.5},
             }
        self.last_loaded = today

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
        Compute projected score based on Efficiency Advantage.
        exp_pp100 = lg_avg + 0.5 * off_adv - 0.5 * opp_def_adv
        """
        avg_poss = (metrics.tempo_home + metrics.tempo_away) / 2.0
        lg_avg = 105.0 # League average efficiency
        
        # Calculate Advantages
        # Offense Advantage vs League
        off_adv_home = metrics.adj_oe_home - lg_avg
        off_adv_away = metrics.adj_oe_away - lg_avg
        
        # Defense Advantage vs League (Positive = Stronger Defense = Lower allowed)
        # opp_def_adv = lg_avg - adj_de
        def_adv_home = lg_avg - metrics.adj_de_home
        def_adv_away = lg_avg - metrics.adj_de_away
        
        # Combined Efficiency
        # Home Offense vs Away Defense
        ppp_home = lg_avg + 0.5 * off_adv_home - 0.5 * def_adv_away
        
        # Away Offense vs Home Defense
        ppp_away = lg_avg + 0.5 * off_adv_away - 0.5 * def_adv_home
        
        # Convert to Score
        score_home = avg_poss * (ppp_home / 100.0)
        score_away = avg_poss * (ppp_away / 100.0)
        
        if not metrics.is_neutral:
            # Add HFA to Final Score (approx 3.2 pts total margin swing)
            # 1.6 pts added to home, 1.6 deducted from away
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
        # 0. Ensure Data Loaded
        self.fetch_data()
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
        
            # 4. Compute Torvik Projection (Efficiency Advantage Method)
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
        w_margin = 0.25 # Increased from 0.20 (Opt Plan 2026-02-01)
        w_total = 0.25
        
        mu_final_margin = mu_market_margin + (w_margin * delta_margin) + signal_adj_margin
        mu_final_total = mu_market_total + (w_total * delta_total) + signal_adj_total
        
        # 8. Probabilities (Normal CDF)
        # Using global norm_cdf
        
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
        prob_cover = 1.0 - norm_cdf(threshold_margin, mu_final_margin, sigma_margin)
        
        # Total Over Prob
        prob_over = 1.0 - norm_cdf(market.total_line, mu_final_total, sigma_total)
        
        # 9. Edges & Ranking
        implied_home = 0.5238 # -110 standard
        if market.moneyline_home:
             # TODO: Implement ML EV
             pass
        
        # Calculate EV using actual price (Issue D)
        # Market usually has American odds, converted to probability
        # EV = (WinProb * Profit) - (LossProb * Wager)
        # This is handled by downstream or callers, but we should emit 'edge' relative to price?
        # Current 'edge' def is prob difference.
        
        # Re-calc edge based on price if available?
        # For now, edge_cover is purely prob difference vs 50% (fair coin) or -110 (52.4%)?
        # Standard: Edge = Prob(Win) - ImpliedProb(Odds)
        implied_home = 0.5238
        edge_cover = prob_cover - implied_home
        edge_over = prob_over - 0.5238
        # We don't have Odds here directly in predict_v1 unless passed in MarketSnapshot?
        # MarketSnapshot doesn't have odds attached securely yet. 
        # find_edges passes snapshot with ONLY lines.
        # We will fix EV calculation in find_edges loop.
            
        rank = OpportunityRanking(
            ev_units=edge_cover * 1.0, # Placeholder, real EV calc in find_edges
            edge_margin=mu_final_margin - mu_market_margin, # Diff from market
            confidence_score=75.0, # Placeholder
            is_allowed=True
        )
        
        # Derived Scores from Final Mu (Margin/Total)
        # Total = H + A
        # Margin = H - A
        # 2H = Total + Margin => H = (Total + Margin) / 2
        # 2A = Total - Margin => A = (Total - Margin) / 2
        final_score_home = (mu_final_total + mu_final_margin) / 2
        final_score_away = (mu_final_total - mu_final_margin) / 2
        
        return ModelSnapshot(
            prediction=PredictionResult(
                score_home=float(final_score_home),
                score_away=float(final_score_away),
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
            
        # 1. Try DB Helper (Standardized)
        from src.database import get_team_efficiency_by_name
        db_stats = get_team_efficiency_by_name(team_name)
        if db_stats:
             return {
                 "eff_off": db_stats['adj_off'],
                 "eff_def": db_stats['adj_def'],
                 "tempo": db_stats['adj_tempo']
             }
             
        # 2. Internal Cache (if loaded)
        if team_name in self.team_stats:
            return self.team_stats[team_name]
            
        # 3. Fuzzy Match
        normalized_input = team_name.lower().replace('.', '').replace(' st', ' state').replace(' (fl)', '').replace(' u', '')
        
        for k, v in self.team_stats.items():
            norm_k = k.lower().replace('.', '').replace(' st', ' state')
            if normalized_input in norm_k or norm_k in normalized_input:
                 return v
            # Specific Overrides
            if "uconn" in normalized_input and "connecticut" in norm_k: return v
            if "mississippi" in normalized_input and "ole miss" in norm_k: return v
            
        # Default Logic
        return {"eff_off": 105.0, "eff_def": 105.0, "tempo": 68.0}

    def standardize_team_name(self, team_name: str) -> str:
        """
        Standardize team name for consistent matching across data sources.
        """
        if not team_name:
            return team_name
            
        # Common normalizations
        normalized = team_name.strip()
        
        # Known aliases
        aliases = {
            "uconn": "Connecticut",
            "ole miss": "Mississippi",
            "lsu": "LSU",
            "ucla": "UCLA",
            "usc": "USC",
            "smu": "SMU",
            "tcu": "TCU",
            "byu": "BYU",
            "uncw": "UNC Wilmington",
            "unc": "North Carolina",
            "umass": "Massachusetts",
            "unlv": "UNLV",
            "vcu": "VCU",
            "utep": "UTEP",
        }
        
        normalized_lower = normalized.lower()
        for alias, full_name in aliases.items():
            if normalized_lower == alias:
                return full_name
                
        # Clean up common suffixes/prefixes
        normalized = normalized.replace(".", "")
        normalized = normalized.replace(" St", " State")
        normalized = normalized.replace(" (FL)", "")
        normalized = normalized.replace(" (PA)", "")
        normalized = normalized.replace(" (OH)", "")
        
        return normalized

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
            
            # Find Best Lines & Devig Context
            from src.utils.market_micro import MarketMicrostructure
            from src.database import get_market_allowlist, get_market_features
            
            allowlist = get_market_allowlist()
            market_features = get_market_features(game_id)
            
            game_signals = []
            
            # Create Signals from Line Movement (Phase 10)
            if market_features:
                if "Spread" in market_features:
                     mf = market_features["Spread"]
                     move = mf.get("line_movement", 0.0)
                     # Movement is (Current - Open).
                     # Spread is usually neg for fav (e.g. -5.0).
                     # If spread goes -5 -> -6, movement is -1.0. This assumes "Spread" is Home Spread.
                     # We assume database logic keyed off "Home Spread" logic. 
                     # If Home favored and move is negative (more neg), market likes Home.
                     # Impact: If move is -1.0, we add +0.5 to Home Score? Or roughly 0.5 impact.
                     
                     # Signal convention: +Impact = Boost Home / Over.
                     # If Spread (Home) gets MORE negative, home is stronger.
                     
                     # Simple heuristics:
                     # Move < 0 (Home getting favored): Impact + (|Move| * 0.5)
                     # Move > 0 (Away getting favored): Impact - (|Move| * 0.5)
                     
                     impact = move * -0.5 # Example: Move -2.0 -> Impact +1.0 (Home +1 pt)
                     
                     if abs(move) >= 0.5:
                         game_signals.append(Signal(
                             source="MARKET_MOVE",
                             category="MARKET",
                             description=f"Line moved {move} pts",
                             target="HOME" if impact > 0 else "AWAY", # Or just apply raw impact
                             impact_points=abs(impact) * (1 if impact > 0 else -1),
                             confidence=0.8
                         ))

                if "Total" in market_features:
                     mf_t = market_features["Total"]
                     move_t = mf_t.get("line_movement", 0.0)
                     # Total goes 140 -> 142. Move +2.0. Market likes Over.
                     # Impact + (Move * 0.5)
                     impact_t = move_t * 0.5
                     
                     if abs(move_t) >= 0.5:
                         game_signals.append(Signal(
                             source="MARKET_MOVE",
                             category="MARKET",
                             description=f"Total moved {move_t} pts",
                             target="TOTAL",
                             impact_points=impact_t,
                             confidence=0.8
                         ))

            # Aggregate lines (with context for devig)
            spread_outcomes = []
            total_outcomes = []
            
            # Needed for Moneyline context later? (Issue E part 3 - ML support)
            
            for book in game.get('bookmakers', []):
                if book['key'] in target_books:
                    # Spread
                    s_home_point = None
                    s_home_price = -110
                    s_away_price = -110
                    
                    # Total
                    t_over_point = None
                    t_over_price = -110
                    t_under_price = -110
                    
                    found_spread = False
                    found_total = False

                    for m in book['markets']:
                        if m['key'] == 'spreads':
                            # Need to find Home and Away to get proper prices
                            p_home, p_away = -110, -110
                            pt_home = None
                            
                            for o in m['outcomes']:
                                if o['name'] == home_team:
                                    p_home = o.get('price')
                                    pt_home = o.get('point')
                                else: # Assume away
                                    p_away = o.get('price')
                            
                            if pt_home is not None:
                                spread_outcomes.append({
                                    'book': book['title'], 
                                    'point': pt_home, 
                                    'price': p_home,
                                    'opp_price': p_away # Context for Devig
                                })
                                
                        elif m['key'] == 'totals':
                            # Need Over and Under
                            p_over, p_under = -110, -110
                            pt_over = None
                            
                            for o in m['outcomes']:
                                if o['name'] == 'Over':
                                    p_over = o.get('price')
                                    pt_over = o.get('point')
                                elif o['name'] == 'Under':
                                    p_under = o.get('price')
                                    
                            if pt_over is not None:
                                total_outcomes.append({
                                    'book': book['title'], 
                                    'point': pt_over, 
                                    'price': p_over,
                                    'opp_price': p_under
                                })

            # Shop for Best Lines
            best_spread = MarketMicrostructure.get_best_line(spread_outcomes, 'Home')
            # For Totals: Model predicts "True Total". 
            # If we like OVER, we want MIN point. If UNDER, we want MAX point.
            # But we don't know direction until we run model?
            # Chicken/Egg. 
            # Solution: Run Model on Consensus first, then shop?
            # Or: Shop for "Consensus" (Median) to use as input, then re-eval specific lines?
            # V1: Just pick "Widest Available" total? No, Median is safer for Model Input.
            
            # Let's use Consensus Line for PREDICTION input.
            consensus_spread = MarketMicrostructure.get_consensus_line(spread_outcomes)
            consensus_total = MarketMicrostructure.get_consensus_line(total_outcomes)
            
            if not consensus_spread or not consensus_total:
                continue
                
            # Run Model on CONSENSUS to get "True" opinion
            market_input = MarketSnapshot(
                spread_home=consensus_spread['point'],
                total_line=consensus_total['point']
            )
            snapshot = self.predict_v1(home_team, away_team, market_input, signals=game_signals)
            if not snapshot: continue
            
            # Apply ensemble adjustments (injuries + season stats)
            ensemble_adj = {'spread_adj': 0.0, 'total_adj': 0.0, 'summary': 'Standard'}
            
            # 1. Injury adjustments (13% weight)
            if self.espn_client:
                try:
                    from src.models.injury_impact import get_injury_adjustment
                    injury_adj = get_injury_adjustment(self.espn_client, home_team, away_team)
                    
                    if injury_adj['spread_adj'] != 0.0:
                        snapshot.prediction.mu_final_margin += injury_adj['spread_adj']
                        ensemble_adj['spread_adj'] += injury_adj['spread_adj']
                        print(f"[INJURY] {home_team} vs {away_team}: Spread adj {injury_adj['spread_adj']:+.1f} pts")
                    
                    if injury_adj['total_adj'] != 0.0:
                        snapshot.prediction.mu_final_total += injury_adj['total_adj']
                        ensemble_adj['total_adj'] += injury_adj['total_adj']
                except Exception as e:
                    print(f"[INJURY] Error: {e}")
            
            # 2. Season stats adjustments (Disabled - Noise/Naive win%)
            # try:
            #     from src.services.season_stats_client import SeasonStatsClient
            #     season_client = SeasonStatsClient()
            #     season_adj = season_client.calculate_season_adjustment(home_team, away_team)
                
            #     if season_adj['spread_adj'] != 0.0:
            #         snapshot.prediction.mu_final_margin += season_adj['spread_adj']
            #         ensemble_adj['spread_adj'] += season_adj['spread_adj']
            #         print(f"[SEASON] {home_team} vs {away_team}: {season_adj['summary']}, Spread adj {season_adj['spread_adj']:+.1f} pts")
                
            #     if season_adj['total_adj'] != 0.0:
            #         snapshot.prediction.mu_final_total += season_adj['total_adj']
            #         ensemble_adj['total_adj'] += season_adj['total_adj']
            # except Exception as e:
            #     print(f"[SEASON] Error: {e}")
            
            # 3. KenPom adjustments (5% weight)
            try:
                from src.services.kenpom_client import KenPomClient
                kenpom_client = KenPomClient()
                kenpom_adj = kenpom_client.calculate_kenpom_adjustment(home_team, away_team)
                
                if kenpom_adj['spread_adj'] != 0.0:
                    snapshot.prediction.mu_final_margin += kenpom_adj['spread_adj']
                    ensemble_adj['spread_adj'] += kenpom_adj['spread_adj']
                    print(f"[KENPOM] {home_team} vs {away_team}: Spread adj {kenpom_adj['spread_adj']:+.1f} pts")
                
                if kenpom_adj['total_adj'] != 0.0:
                    snapshot.prediction.mu_final_total += kenpom_adj['total_adj']
                    ensemble_adj['total_adj'] += kenpom_adj['total_adj']
            except Exception as e:
                print(f"[KENPOM] Error: {e}")



            
            # Now Evaluate Specific Lines against Model (Finding Specific Edges)
            
            # --- Spread Evaluation ---
            # Model says: Fair Spread is X.
            # Iterate all books? Or just check Best?
            # Let's check Best Available for the direction we like.
            
            # Which way do we lean?
            # Model Spread (Home) vs Consensus
            model_spread = -snapshot.prediction.mu_final_margin
            lean_home = model_spread < consensus_spread['point'] # e.g. Model -8, Mkt -5. Like Home.
            
            # Find best line matching our lean
            target_spread = best_spread # Simplification: get_best_line defaults to Home logic (-5 better than -6)
            # If we liked Away, we'd want Max Point (+7 better than +6).
            # Current get_best_line is 'Home' centric (-5 > -6).
            # If we like Away, we want + Points.
            
            # Re-shop based on lean?
            # V1 Simplification: Use the Best Home Line found earlier.
            # AND verify if it creates value.
            
            # Calculate No-Vig Prob of the Target Line
            # Use devig_american_odds
            mkt_prob_home, mkt_prob_away = MarketMicrostructure.devig_american_odds(
                target_spread['price'], target_spread['opp_price']
            )
            
            # Model Probability for THIS specific line
            # We need to re-calc prob for cover if the line is different from consensus?
            # Yes. predict_v1 returned prob for consensus.
            # Re-calc prob using Z-score for target_spread['point'].
            # Threshold = -Line
            # P(Margin > -Line)
            mu = snapshot.prediction.mu_final_margin
            sigma = 10.5 # Default/Hardcoded for now (should pass out from snapshot?)
            
            prob_cover_target = 1.0 - norm_cdf(-target_spread['point'], mu, sigma)
            
            # Calculate Edge & EV
            no_vig_prob = mkt_prob_home
            edge_prob = prob_cover_target - no_vig_prob
            
            # EV = (ProbWin * DecimalOdds - 1) - (ProbLoss * 1) ? No.
            # EV = (ProbWin * Profit) - (ProbLoss * Stake)
            # Decimal = (Price>0) ? (Price/100)+1 : (100/-Price)+1
            if target_spread['price'] > 0: dec = (target_spread['price']/100) + 1
            else: dec = (100/-target_spread['price']) + 1
            
            ev_pct = (prob_cover_target * (dec - 1)) - ((1 - prob_cover_target) * 1)
            
            # Always show spread edge
            # Strict Filtering (Sniper Mode)
            # Only bet if Edge >= 2.5
            calc_edge = abs(model_spread - target_spread['point'])
            is_live = (status == "ENABLED" and calc_edge >= 2.5)
            
            edges.append({
               "game_id": game_id,
               "market_type": "SPREAD", # Issue E
               "game": f"{away_team} @ {home_team}",
               "matchup": f"{away_team} @ {home_team}",
               "home_team": home_team,
               "away_team": away_team,
               "market": "Spread", # Legacy compact
               "bet_on": home_team, 
               "line": target_spread['point'],
               "price": target_spread['price'],
               "market_line": target_spread['point'],
               "model_line": round(model_spread, 1),
               "fair_line": round(model_spread, 1),
               "edge": round(abs(model_spread - target_spread['point']), 1), 
               "edge_prob": round(edge_prob, 3),
               "ev": round(ev_pct, 4),
               "book": target_spread['book'],
               "is_actionable": is_live
           })
                
            # --- Total Evaluation ---
            # Similar logic.
            # Model Says: Total is Y.
            # Consensus is C.
            diff_total = snapshot.prediction.mu_final_total - consensus_total['point']
            
            # Best Line?
            # If diff > 0 (Over), find MIN point.
            # If diff < 0 (Under), find MAX point.
            best_total_line = None
            lean = "OVER" if diff_total > 0 else "UNDER"
            
            if lean == "OVER":
                best_total_line = min(total_outcomes, key=lambda x: (x.get('point', 999), -x.get('price', -999)))
            else:
                best_total_line = max(total_outcomes, key=lambda x: (x.get('point', -999), x.get('price', -999)))
                
            if best_total_line:
                # Devig
                prob_over_mkt, prob_under_mkt = MarketMicrostructure.devig_american_odds(
                    best_total_line['price'], best_total_line['opp_price']
                )
                mkt_prob = prob_over_mkt if lean == "OVER" else prob_under_mkt
                
                # Model Prob for THIS line
                sigma_t = 18.0 
                # P(Total > Line)
                prob_over_target = 1.0 - norm_cdf(best_total_line['point'], snapshot.prediction.mu_final_total, sigma_t)
                model_prob = prob_over_target if lean == "OVER" else (1.0 - prob_over_target)
                
                edge_prob_total = model_prob - mkt_prob
                
                # EV
                if best_total_line['price'] > 0: dec_t = (best_total_line['price']/100) + 1
                else: dec_t = (100/-best_total_line['price']) + 1
                
                ev_pct_total = (model_prob * (dec_t - 1)) - ((1 - model_prob) * 1)
                
            # Always show total edge
            # Disable Totals (37.5% win rate - drag on ROI)
            # status_total = allowlist.get(("basketball_ncaab", "Total"), "SHADOW")
            is_live_total = False # Force disabled for now
            
            edges.append({
                "game_id": game_id,
                "market_type": "TOTAL",
                "game": f"{away_team} @ {home_team}",
                "matchup": f"{away_team} @ {home_team}",
                "home_team": home_team,
                "away_team": away_team,
                "market": "Total",
                "bet_on": lean,
                "line": best_total_line['point'],
                "price": best_total_line['price'],
                "market_line": best_total_line['point'],
                "model_line": round(snapshot.prediction.mu_final_total, 1),
                "fair_line": round(snapshot.prediction.mu_final_total, 1),
                "edge": round(abs(snapshot.prediction.mu_final_total - best_total_line['point']), 1),
                "edge_prob": round(edge_prob_total, 3),
                "ev": round(ev_pct_total, 4),
                "book": best_total_line['book'],
                "is_actionable": is_live_total
            })

        print(f"[NCAAM] Found {len(edges)} potential edges.")
        return edges

    def evaluate(self, predictions: List[Dict[str, Any]]):
        pass
