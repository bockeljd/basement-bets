
import math
import json
import os
from datetime import datetime
from typing import Dict, List, Any, Optional

from src.services.torvik_projection import TorvikProjectionService
from src.services.odds_selection_service import OddsSelectionService
from src.services.kenpom_client import KenPomClient
from src.services.news_service import NewsService
from src.services.geo_service import GeoService
from src.database import get_db_connection, _exec, insert_model_prediction


def _safe_float(x):
    try:
        if x is None or x == '':
            return None
        return float(x)
    except Exception:
        return None


from src.models.base_model import BaseModel
from src.utils.naming import standardize_team_name

# Phase gate: council qualitative adjustments are only applied to model outputs
# once Phase 2 offline evaluation confirms positive CLV/ROI contribution.
# Set to True only after running performance_auditor_agent.py and confirming signal quality.
COUNCIL_ADJUSTMENTS_ENABLED: bool = os.environ.get("COUNCIL_ADJUSTMENTS_ENABLED", "false").lower() == "true"

class NCAAMMarketFirstModelV2(BaseModel):
    """
    NCAAM Market-First Model v2.
    - Market base with corrective signals.
    - CLV-first gating.
    - Structured narratives.
    """
    
    VERSION = "2.1.2-sniper"
    
    # Optimized Model Weights (2026-02-01 Sniper Plan)
    # Target: 75% Market / 25% Torvik+KenPom
    # Formula: mu = market + base*(torvik-market) + kenpom*(kenpom-market)
    # Weights apply to the DIFF. 0.25 on diff means 25% projection / 75% market anchor.
    DEFAULT_W_BASE = 0.25  # Torvik Weight (Increased from 0.20)
    DEFAULT_W_SCHED = 0.00 # Disabled (Season Stats removal)
    # KenPom weight applied to the KenPom-vs-market delta.
    # Requested: make KenPom 20% of the model blend.
    DEFAULT_W_KENPOM = 0.20
    
    # Default Caps
    DEFAULT_CAP_SPREAD = 2.0
    DEFAULT_CAP_TOTAL = 3.0
    
    # Aggressive Mode Caps
    AGGRESSIVE_CAP_SPREAD = 4.0
    AGGRESSIVE_CAP_TOTAL = 5.0

    def __init__(self, aggressive: bool = False, cap_spread: float = None, cap_total: float = None, manual_adjustments: dict = None):
        """Initialize model with configurable parameters.

        Staging/tuning: core knobs can be overridden via env vars.
        """
        super().__init__(sport_key="ncaam")  # BaseModel init
        self.torvik_service = TorvikProjectionService()
        self.odds_selector = OddsSelectionService()
        self.kenpom_client = KenPomClient()
        self.news_service = NewsService()
        self.geo_service = GeoService()

        from src.services.ncaam_tournament_features import NCAAMTournamentFeatures
        self.tournament_features = NCAAMTournamentFeatures()

        self.manual_adjustments = manual_adjustments or {}

        # Set weights (defaults)
        self.W_BASE = self.DEFAULT_W_BASE
        self.W_SCHED = self.DEFAULT_W_SCHED
        self.W_KENPOM = self.DEFAULT_W_KENPOM

        # Env overrides (staging tune)
        try:
            if os.getenv('NCAAM_W_BASE') is not None:
                self.W_BASE = float(os.getenv('NCAAM_W_BASE'))
        except Exception:
            pass
        try:
            if os.getenv('NCAAM_W_KENPOM') is not None:
                self.W_KENPOM = float(os.getenv('NCAAM_W_KENPOM'))
        except Exception:
            pass
        try:
            if os.getenv('NCAAM_W_SCHED') is not None:
                self.W_SCHED = float(os.getenv('NCAAM_W_SCHED'))
        except Exception:
            pass

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

        # Env overrides for caps
        try:
            if os.getenv('NCAAM_CAP_SPREAD') is not None:
                self.CAP_SPREAD = float(os.getenv('NCAAM_CAP_SPREAD'))
        except Exception:
            pass
        try:
            if os.getenv('NCAAM_CAP_TOTAL') is not None:
                self.CAP_TOTAL = float(os.getenv('NCAAM_CAP_TOTAL'))
        except Exception:
            pass

    def fetch_data(self):
        """Pre-load data (No-op for V2, as it fetches per-request)."""
        pass

    def evaluate(self):
        """Evaluate performance (No-op)."""
        pass

    def _get_dynamic_weights(self, game_date) -> float:
        """
        Returns a weight (W_BASE) that scales based on the time of year.
        Early season: Trust Market heavily (projections are preseason-based).
        Late season: Trust Projections more (based on actual games).
        """
        from datetime import datetime
        
        if game_date is None:
            game_date = datetime.now()
        elif isinstance(game_date, str):
            try:
                game_date = datetime.fromisoformat(game_date.replace('Z', '+00:00'))
            except:
                game_date = datetime.now()
        
        month = game_date.month
        
        # Off-season/Early Season (Nov/Dec) - Preseason projections
        if month == 11: return 0.12  # Trust Market heavily
        if month == 12: return 0.18  
        # Conference Play (Jan/Feb) - Real data accumulating
        if month == 1: return 0.25   # Standard Sniper Weight
        if month == 2: return 0.32   # Trust Projections more
        # Tournament Time (March) - Peak sample size
        if month == 3: return 0.38   # Peak Alpha
        # April+ (Rare, post-tournament)
        return 0.25  # Default

    def _calculate_shooting_regression(self, team_name: str) -> float:
        """
        3-Point Variance Signal: Fade teams shooting hot from 3.
        If a team is shooting >8% above their season average over last 3 games,
        apply a negative regression penalty.
        """
        from src.database import get_team_recent_shooting
        
        try:
            stats = get_team_recent_shooting(team_name, num_games=3)
            delta = stats.get('delta', 0.0)
            
            if delta is None:
                return 0.0
                
            # For every 2% above season average, subtract 0.5 points
            # Only apply if shooting significantly hot (>4% above avg)
            if delta > 0.04:  # 4% threshold
                penalty = (delta * 100) / 2 * 0.5  # Convert to points
                return -min(penalty, 2.0)  # Cap at -2 points
            elif delta < -0.04:  # Shooting cold, bonus (regression to mean UP)
                bonus = abs(delta * 100) / 2 * 0.25  # Smaller bonus
                return min(bonus, 1.0)  # Cap at +1 point
                
        except Exception as e:
            print(f"[MODEL] Shooting regression error for {team_name}: {e}")
            
        return 0.0

    def _calculate_situational_spots(self, team_name: str, event: dict) -> float:
        """
        Spot Modeling: Lookahead and Letdown situations.
        - Lookahead: Team plays weak opponent before a big game → flat performance
        - Letdown: Team just upset a ranked opponent → hangover
        """
        from src.database import get_team_last_game, get_db_connection, _exec
        from datetime import datetime
        
        adj = 0.0
        current_date = event.get('start_time', datetime.now())
        if isinstance(current_date, str):
            try:
                current_date = datetime.fromisoformat(current_date.replace('Z', '+00:00'))
            except:
                current_date = datetime.now()
        
        try:
            # 1. LETDOWN SPOT: Check if last game was an upset win
            last_game = get_team_last_game(team_name)
            if last_game:
                margin = last_game.get('margin', 0) or 0
                opponent_rank = last_game.get('opponent_rank', 0) or 0
                
                # Upset win = Won (margin > 0) against ranked team (#1-25)
                if margin > 0 and 1 <= opponent_rank <= 25:
                    # Big upset against Top 10 = bigger letdown
                    if opponent_rank <= 10:
                        adj -= 1.5  # Major letdown risk
                        print(f"[SPOT] {team_name} LETDOWN: Just beat Top 10 team (#{opponent_rank})")
                    else:
                        adj -= 1.0  # Standard letdown
                        print(f"[SPOT] {team_name} LETDOWN: Just beat ranked team (#{opponent_rank})")
            
            # 2. LOOKAHEAD SPOT: Check if NEXT game is against a Top 25/rival
            with get_db_connection() as conn:
                query = """
                SELECT e.home_team, e.away_team, e.start_time
                FROM events e
                WHERE (LOWER(e.home_team) LIKE LOWER(:t) OR LOWER(e.away_team) LIKE LOWER(:t))
                  AND e.start_time > :now
                ORDER BY e.start_time ASC
                LIMIT 1
                """
                # Use named parameters
                _ = _exec(conn, query, {"t": f"%{team_name}%", "now": current_date}).fetchone()
                # MVP: we are not applying a lookahead penalty yet (needs ranked-opponent + rivalry logic).
                
        except Exception as e:
            print(f"[MODEL] Situational spot error for {team_name}: {e}")
            
        return adj

    def _apply_referee_signal(self, event_id: str, mu_total: float) -> float:
        """Referee Signal: Adjust total based on officiating crew tendencies.

        Priority:
        1) referee_assignments.crew_avg_fouls (if present)
        2) KenPom ref ratings (best-effort, header-driven)
        """
        from src.database import get_referee_assignment

        NCAA_AVG_FOULS = 36.0  # National average fouls per game

        try:
            ref_data = get_referee_assignment(event_id) or {}
            crew_fouls = None
            if ref_data.get('crew_avg_fouls') is not None:
                try:
                    crew_fouls = float(ref_data['crew_avg_fouls'])
                except Exception:
                    crew_fouls = None

            # Fall back to KenPom ref table if we have names.
            if crew_fouls is None:
                names = [ref_data.get('referee_1'), ref_data.get('referee_2'), ref_data.get('referee_3')]
                names = [n for n in names if n]
                if names:
                    crew_fouls = self.kenpom_client.estimate_crew_avg_fouls(names)
                else:
                    # No assignment available: use KenPom ref tendencies in aggregate.
                    crew_fouls = self.kenpom_client.estimate_league_avg_ref_fouls()

            if crew_fouls is not None:
                # Every 1 foul above average adds ~0.8 points to total
                if crew_fouls > NCAA_AVG_FOULS:
                    over_adj = (crew_fouls - NCAA_AVG_FOULS) * 0.8
                    mu_total += min(over_adj, 4.0)  # Cap at +4 points
                    print(f"[REF] Crew avg {crew_fouls:.1f} fouls → Total +{over_adj:.1f}")
                elif crew_fouls < NCAA_AVG_FOULS - 2:
                    under_adj = (NCAA_AVG_FOULS - crew_fouls) * 0.5
                    mu_total -= min(under_adj, 2.0)  # Cap at -2 points
                    print(f"[REF] Tight crew {crew_fouls:.1f} fouls → Total -{under_adj:.1f}")

        except Exception as e:
            print(f"[MODEL] Referee signal error: {e}")

        return mu_total

    def _calculate_fatigue_penalty(self, team_name: str, event_id: str, current_game_date) -> float:
        """
        Checks the schedule for 'Short Rest' spots.
        -2.5 pts for '3rd game in 6 days' (The 'Tired Legs' Spot)
        -1.5 pts for 'Back-to-back'
        """
        from src.database import get_db_connection, _exec
        from datetime import datetime, timedelta
        
        if current_game_date is None:
            return 0.0
        if isinstance(current_game_date, str):
            try:
                current_game_date = datetime.fromisoformat(current_game_date.replace('Z', '+00:00'))
            except:
                return 0.0
        
        try:
            # Query recent games, excluding the current one
            query = """
            SELECT id, start_time FROM events 
            WHERE (LOWER(home_team) LIKE LOWER(:t) OR LOWER(away_team) LIKE LOWER(:t))
            AND start_time < :now
            AND id != :eid  -- Critical fix: Exclude current game to prevent self-matching
            ORDER BY start_time DESC LIMIT 2
            """
            
            # Use named parameters
            params = {
                "t": f"%{team_name}%",
                "now": current_game_date,
                "eid": event_id
            }
            
            with get_db_connection() as conn:
                rows = _exec(conn, query, params).fetchall()
                
            if not rows: 
                return 0.0
            
            last_game_date = rows[0]['start_time']
            if isinstance(last_game_date, str):
                last_game_date = datetime.fromisoformat(last_game_date)
            
            days_rest = (current_game_date - last_game_date).days
            
            # Only count >0 days to avoid weird intraday header issues, 
            # though id exclusion handles the main bug.
            if days_rest == 0:
                 # Sanity check: if same day and not same ID, double header? 
                 # Unlikely in NCAA. Assume data noise.
                 pass

            if days_rest <= 1: 
                print(f"[FATIGUE] {team_name}: Back-to-back (-1.5)")
                return -1.5  # Back-to-back
            
            if len(rows) > 1:
                two_games_ago = rows[1]['start_time']
                if isinstance(two_games_ago, str):
                    two_games_ago = datetime.fromisoformat(two_games_ago)
                if (current_game_date - two_games_ago).days <= 6:
                    print(f"[FATIGUE] {team_name}: 3rd game in 6 days (-2.5)")
                    return -2.5  # 3rd game in 6 days
                    
        except Exception as e:
            print(f"[MODEL] Fatigue calc error for {team_name}: {e}")
            
        return 0.0

    def _generate_bell_curve(self, mu: float, sigma: float, line: float) -> Dict:
        """
        Generates 50 points representing the Normal Distribution curve.
        Used by Frontend (Chart.js) to render the 'Cover Zone'.
        """
        import math
        
        points = []
        # Generate points from -3 sigma to +3 sigma
        start = mu - (3 * sigma)
        end = mu + (3 * sigma)
        step = (end - start) / 50
        
        for i in range(51):
            x = start + (i * step)
            # Standard Normal PDF Formula
            y = (1 / (sigma * math.sqrt(2 * math.pi))) * math.exp(-0.5 * ((x - mu) / sigma)**2)
            points.append({"x": round(x, 2), "y": round(y, 6)})
        
        # Calculate probability of covering (CDF at line)
        z = (line - mu) / sigma
        cover_prob = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        
        return {
            "points": points,
            "mu": round(mu, 2),
            "sigma": round(sigma, 2),
            "line": round(line, 2),
            "cover_prob": round(cover_prob, 4),
            "is_under_line": mu < line  # Tells UI which side is favorable
        }

    def predict(self, game_id: str, home_team: str, away_team: str, market_total: float = 0) -> Dict[str, Any]:
        """
        Satisfy BaseModel interface by wrapping analyze().
        """
        from datetime import datetime
        # Create minimal context
        event = {
            "id": game_id,
            "home_team": standardize_team_name(home_team),
            "away_team": standardize_team_name(away_team),
            "sport": "NCAAM",
            "league": "NCAAM",
            "start_time": datetime.now()  # Default to now to prevent luck check failure
        }
        # Minimal market snap
        snap = {
            "total": market_total or 145.0,
            "spread_home": 0.0
        }
        return self.analyze(game_id, market_snapshot=snap, event_context=event)

    def analyze_tournament_game(self, team_a: str, team_b: str, event_context: Optional[Dict] = None, market_snapshot: Optional[Dict] = None, persist: bool = False, neutral_site: bool = True, conn=None) -> Dict:
        """
        Tournament mode prediction avoiding fake market priors when missing.
        Uses Torvik, KenPom, and bounded modifiers.
        """
        from datetime import datetime
        import math
        
        tf = self.tournament_features
        
        team_a_canon = standardize_team_name(team_a)
        team_b_canon = standardize_team_name(team_b)
        
        # 1. Base logic
        game_date = (event_context or {}).get('start_time')
        game_date_str = None
        if game_date:
             if isinstance(game_date, str):
                 try:
                     game_date = datetime.fromisoformat(game_date.replace('Z', '+00:00'))
                 except: pass
             if isinstance(game_date, datetime):
                 game_date_str = game_date.strftime("%Y%m%d")
                 
        torvik_view = self.torvik_service.get_projection(team_a_canon, team_b_canon, date=game_date_str, conn=conn)
        kenpom_adj = self.kenpom_client.calculate_kenpom_adjustment(team_a_canon, team_b_canon, conn=conn)

        # Team style + player facts for narratives (best-effort)
        kp_a = None
        kp_b = None
        try:
            kp_a = self.kenpom_client.get_team_rating(team_a_canon, conn=conn) or None
        except Exception:
            kp_a = None
        try:
            kp_b = self.kenpom_client.get_team_rating(team_b_canon, conn=conn) or None
        except Exception:
            kp_b = None

        kp_players_a = []
        kp_players_b = []
        try:
            kp_players_a = self.kenpom_client.get_player_stats_for_team(team_a_canon, limit=12) or []
        except Exception:
            kp_players_a = []
        try:
            kp_players_b = self.kenpom_client.get_player_stats_for_team(team_b_canon, limit=12) or []
        except Exception:
            kp_players_b = []

        # News/injury context (best-effort; include up to 2 source URLs)
        news_summary = None
        news_has_injury = None
        news_top_urls = []
        try:
            ctx = self.news_service.fetch_game_context(team_a, team_b)
            news_has_injury = bool(ctx.get('has_injury_news'))
            news_summary = self.news_service.summarize_impact(ctx)
            for a in (ctx.get('home_news') or [])[:1] + (ctx.get('away_news') or [])[:1]:
                if a.get('url'):
                    news_top_urls.append(a['url'])
        except Exception:
            news_summary = None
            news_has_injury = None
            news_top_urls = []
        
        # 3. Features
        mods_a = tf.get_tournament_modifiers(team_a_canon, conn=conn)
        mods_b = tf.get_tournament_modifiers(team_b_canon, conn=conn)
        
        # 4. Math
        fallback_used = False
        reason_codes = []
        risk_flags = []
        
        if not torvik_view or torvik_view.get('lean') == 'No Data':
            fallback_used = True
            from src.services.ncaam_tournament_service import SimulatorDataError
            raise SimulatorDataError(f"Missing core data (Torvik) for {team_a_canon} vs {team_b_canon}. Halting simulation.")
        else:
            mu_base_spread = -(torvik_view.get('margin') or 0.0)
            
            # Verify Torvik actually returned a total
            torvik_total = torvik_view.get('total')
            if not torvik_total:
                 from src.services.ncaam_tournament_service import SimulatorDataError
                 raise SimulatorDataError(f"Torvik returned no total for {team_a} vs {team_b}")
                 
            mu_base_total = float(torvik_total)
            
            if kenpom_adj and kenpom_adj.get('spread_adj') is not None:
                mu_kp_spread = -kenpom_adj['spread_adj']
                mu_base_spread = (0.75 * mu_base_spread) + (0.25 * mu_kp_spread)
                
        # Modifiers (relative to team A perspective where negative points = team A favorite)
        # Bounded modifier points: + is good for the team. We adjust spread (negative is good for A).
        mod_a = mods_a.get('luck_adj_points', 0) + mods_a.get('continuity_adj_points', 0) + mods_a.get('turnover_adj_points', 0) + mods_a.get('q1_adj_points', 0)
        mod_b = mods_b.get('luck_adj_points', 0) + mods_b.get('continuity_adj_points', 0) + mods_b.get('turnover_adj_points', 0) + mods_b.get('q1_adj_points', 0)
        
        mod_diff = mod_a - mod_b # positive = A is better by mod_diff.
        mu_spread_final = mu_base_spread - mod_diff # therefore spread is lowered, making A more favored.
        
        # Market blending if available (and valid!)
        market_data_used = False
        if market_snapshot and market_snapshot.get('spread_home') is not None and market_snapshot.get('spread_home') != 0.0:
            mkt_spread = float(market_snapshot['spread_home'])
            if mkt_spread != 0.0 or market_snapshot.get('total') != 145.0:  # Ignore default fake markets
                diff = mu_spread_final - mkt_spread
                mu_spread_final = mkt_spread + (0.35 * diff) 
                market_data_used = True
                reason_codes.append("Market spread blended into final projection.")
            
        if market_snapshot and market_snapshot.get('total') is not None and market_snapshot.get('total') != 145.0:
            mkt_total = float(market_snapshot['total'])
            mu_base_total = mkt_total + (0.35 * (mu_base_total - mkt_total))
            
        # Variance
        tempo_factor = 1.0
        torvik_team_stats = self.torvik_service.get_matchup_team_stats(team_a_canon, team_b_canon, date=game_date_str)
        if torvik_team_stats:
             tempo = torvik_team_stats.get('game_tempo')
             if tempo: tempo_factor = math.sqrt(tempo / 68.0)
             
        variance_mult = max(mods_a.get('variance_multiplier', 1.0), mods_b.get('variance_multiplier', 1.0))
        sigma_spread = 10.5 * tempo_factor * variance_mult
        
        if mods_a.get('upset_risk_score', 0) > 40:
             risk_flags.append(f"{team_a} high upset risk ({mods_a['upset_risk_score']})")
        if mods_b.get('upset_risk_score', 0) > 40:
             risk_flags.append(f"{team_b} high upset risk ({mods_b['upset_risk_score']})")
             
        z = (0.0 - mu_spread_final) / sigma_spread
        # mu_spread_final is from Team A perspective (negative => Team A favored).
        # P(Team A wins) = P(spread < 0) = CDF((0 - mu)/sigma).
        win_prob_a = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        win_prob_b = 1.0 - win_prob_a
        
        winner = team_a if win_prob_a >= 0.5 else team_b
        winner_side = 'team_a' if win_prob_a >= 0.5 else 'team_b'
        
        return {
            'team_a': team_a,
            'team_b': team_b,
            'winner': winner,
            'winner_side': winner_side,
            'projected_spread_a': round(mu_spread_final, 2),
            'projected_total': round(mu_base_total, 2),
            'win_prob_a': round(win_prob_a * 100, 2),
            'win_prob_b': round(win_prob_b * 100, 2),
            'confidence_0_100': round(max(win_prob_a, win_prob_b) * 100, 2), 
            'market_data_used': market_data_used,
            'fallback_used': fallback_used,
            'reason_codes': reason_codes,
            'risk_flags': risk_flags,
            'debug': {
                 'sigma': sigma_spread,
                 'tempo_factor': tempo_factor,
                 'variance_mult': variance_mult,
                 'mu_base_spread': mu_base_spread,
                 'mu_spread_final': mu_spread_final,
                 'mu_total_final': mu_base_total,
                 'kenpom_spread_adj': (kenpom_adj.get('spread_adj') if kenpom_adj else None),
                 'modifier_points_a': mod_a,
                 'modifier_points_b': mod_b,
                 'modifier_points_diff_a_minus_b': mod_diff,
                 'upset_risk_a': mods_a.get('upset_risk_score', None),
                 'upset_risk_b': mods_b.get('upset_risk_score', None),
                 'market_data_used': market_data_used,

                 'kp_team_a': {
                     'adj_o': (kp_a.get('adj_o') if isinstance(kp_a, dict) else None),
                     'adj_d': (kp_a.get('adj_d') if isinstance(kp_a, dict) else None),
                     'adj_t': (kp_a.get('adj_t') if isinstance(kp_a, dict) else None),
                     'rank': (kp_a.get('rank') if isinstance(kp_a, dict) else None),
                 } if kp_a else None,
                 'kp_team_b': {
                     'adj_o': (kp_b.get('adj_o') if isinstance(kp_b, dict) else None),
                     'adj_d': (kp_b.get('adj_d') if isinstance(kp_b, dict) else None),
                     'adj_t': (kp_b.get('adj_t') if isinstance(kp_b, dict) else None),
                     'rank': (kp_b.get('rank') if isinstance(kp_b, dict) else None),
                 } if kp_b else None,

                 'kp_key_players_a': [
                     {'name': p.get('name'), 'ppg': p.get('ppg'), 'usg': p.get('usg')}
                     for p in (kp_players_a or [])[:2]
                 ] if kp_players_a else [],
                 'kp_key_players_b': [
                     {'name': p.get('name'), 'ppg': p.get('ppg'), 'usg': p.get('usg')}
                     for p in (kp_players_b or [])[:2]
                 ] if kp_players_b else [],

                 'news_summary': news_summary,
                 'news_has_injury': news_has_injury,
                 'news_urls': news_top_urls
            }
        }

    def analyze(self, event_id: str, market_snapshot: Optional[Dict] = None, event_context: Optional[Dict] = None, relax_gates: bool = False, persist: bool = True) -> Dict:
        """
        On-demand analysis for one game.
        """
        council_verdict = self._get_council_verdict(event_id)
        
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
            consensus_ml_home = self.odds_selector.get_consensus_snapshot(raw_snaps, 'MONEYLINE', 'HOME')
            consensus_ml_away = self.odds_selector.get_consensus_snapshot(raw_snaps, 'MONEYLINE', 'AWAY')
            
            # Step B: Get BEST PRICES for later (after we find an edge)
            best_spread_home = self.odds_selector.get_best_price_for_side(raw_snaps, 'SPREAD', 'HOME')
            best_spread_away = self.odds_selector.get_best_price_for_side(raw_snaps, 'SPREAD', 'AWAY')
            best_total_over = self.odds_selector.get_best_price_for_side(raw_snaps, 'TOTAL', 'OVER')
            best_total_under = self.odds_selector.get_best_price_for_side(raw_snaps, 'TOTAL', 'UNDER')
            best_ml_home = self.odds_selector.get_best_price_for_side(raw_snaps, 'MONEYLINE', 'HOME')
            best_ml_away = self.odds_selector.get_best_price_for_side(raw_snaps, 'MONEYLINE', 'AWAY')
            
            # Composite Snapshot for Analysis (uses CONSENSUS for model math)
            mc = self._get_market_consensus(event_id)
            market_snapshot = {
                # Consensus for model input
                'spread_home': consensus_spread['line_value'] if consensus_spread else None,
                'spread_price_home': consensus_spread['price'] if consensus_spread else -110,
                'total': consensus_total['line_value'] if consensus_total else None,
                'total_over_price': consensus_total['price'] if consensus_total else -110,
                # Moneyline consensus prices (used for ML persistence + parlay agent)
                'moneyline_price_home': consensus_ml_home['price'] if consensus_ml_home else None,
                'moneyline_price_away': consensus_ml_away['price'] if consensus_ml_away else None,
                'book_spread': 'Consensus',
                'book_total': 'Consensus',
                'book_ml': 'Consensus',
                'book_ml': 'Consensus',
                # Movement / derived
                '_market_consensus': mc,
                'open_spread_home': (mc.get('open_spread_home') if mc else None),
                'current_spread_home': (mc.get('current_spread_home') if mc else None),
                'open_total': (mc.get('open_total') if mc else None),
                'current_total': (mc.get('current_total') if mc else None),
                'spread_move_home': (mc.get('spread_move_home') if mc else None),
                'total_move': (mc.get('total_move') if mc else None),
                # Best prices for betting (after edge identified)
                '_best_spread_home': best_spread_home,
                '_best_spread_away': best_spread_away,
                '_best_total_over': best_total_over,
                '_best_total_under': best_total_under,
                '_best_moneyline_home': best_ml_home,
                '_best_moneyline_away': best_ml_away,
                # Raw for narrative
                '_raw_snaps': raw_snaps
            }
        else:
            raw_snaps = market_snapshot.get('_raw_snaps', [])

        # VALIDATION: If *both* spread and total are missing, we can't do anything.
        # Otherwise, proceed and only generate recommendations for markets with valid lines.
        has_spread = market_snapshot.get('spread_home') is not None
        has_total = market_snapshot.get('total') is not None

        if (not has_spread) and (not has_total):
            return {
                "headline": "Market Data Waiting",
                "recommendation": "No Line",
                "rationale": ["Market odds not yet fully populated."],
                "is_actionable": False
            }

        # If one market is missing, we still compute the other market.
        # Use sane defaults to keep the math stable; _generate_recommendations will skip missing markets.
        mu_market_spread = float(market_snapshot['spread_home']) if has_spread else 0.0
        mu_market_total = float(market_snapshot['total']) if has_total else 145.0

        # 3. External Projections & Signals
        # Torvik - PRIMARY SIGNAL
        game_date_obj = event.get('start_time')
        game_date_str = None
        if game_date_obj:
            try:
                # Ensure we have a string YYYYMMDD for Torvik service
                # If it's a string, try to parse it first (ISO format from earlier fix)
                if isinstance(game_date_obj, str):
                    game_date_obj = datetime.fromisoformat(game_date_obj.replace('Z', '+00:00'))
                game_date_str = game_date_obj.strftime("%Y%m%d")
            except Exception:
                pass

        torvik_view = self.torvik_service.get_projection(event['home_team'], event['away_team'], date=game_date_str)
        
        # VALIDATION: Abort if Torvik is missing (Stop the "0.0 edge" bug)
        if not torvik_view or torvik_view.get('lean') == 'No Data':
             return {
                "headline": "Data Unavailable",
                "recommendation": "Pass",
                "rationale": ["Primary projection source (Torvik) unavailable for this game."],
                "is_actionable": False
            }

        # Other Signals
        torvik_team_stats = self.torvik_service.get_matchup_team_stats(event['home_team'], event['away_team'], date=game_date_str)
        kenpom_adj = self.kenpom_client.calculate_kenpom_adjustment(event['home_team'], event['away_team'])
        # News can be slow; fetch only if we have a candidate edge to write up.
        news_context = {}
        
        # 4. Dynamic Weight Scaling
        # If NCAAM_W_BASE is set, treat it as a fixed override (staging tuning).
        if os.getenv('NCAAM_W_BASE') is not None:
            try:
                self.W_BASE = float(os.getenv('NCAAM_W_BASE'))
            except Exception:
                self.W_BASE = self._get_dynamic_weights(game_date_obj)
        else:
            self.W_BASE = self._get_dynamic_weights(game_date_obj)
        w_base = self.W_BASE

        # 5. Blend Math (Strict mu_final)
        # Defensive None handling
        mu_torvik_spread = -(torvik_view.get('margin') or 0.0)
        mu_sched_spread = -(torvik_view.get('official_margin') or -mu_torvik_spread)
        
        # KenPom Integration
        kp_margin = kenpom_adj.get('spread_adj') or 0.0
        mu_kenpom_line = -kp_margin
        
        diff_torvik = (mu_torvik_spread - mu_market_spread)
        diff_sched = (mu_sched_spread - mu_market_spread)
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
        
        # --- Feature: Agent Council Qualitative Adjustment ---
        # Explanations-only mode: we still fetch and persist council narratives for UI,
        # but we DO NOT let them change model outputs yet.
        council_adjustment_spread = 0.0
        council_adjustment_total = 0.0
        if council_verdict:
            # New Structured Parsing (Phase 4)
            signals = council_verdict.get('signals', {})
            leans = signals.get('market_lean', {})
            
            # 1. Spread Adjustment
            spread_lean = leans.get('spread', {})
            if spread_lean.get('side') == 'HOME':
                council_adjustment_spread = -abs(float(spread_lean.get('points', 1.0)))
            elif spread_lean.get('side') == 'AWAY':
                council_adjustment_spread = abs(float(spread_lean.get('points', 1.0)))
            
            # 2. Total Adjustment
            total_lean = leans.get('total', {})
            if total_lean.get('side') == 'OVER':
                council_adjustment_total = abs(float(total_lean.get('points', 1.5)))
            elif total_lean.get('side') == 'UNDER':
                council_adjustment_total = -abs(float(total_lean.get('points', 1.5)))

        # Apply council_adjustment_spread (gated by COUNCIL_ADJUSTMENTS_ENABLED)
        potential_adjustment_spread = council_adjustment_spread
        if COUNCIL_ADJUSTMENTS_ENABLED:
            mu_spread_final += council_adjustment_spread
        else:
            if council_adjustment_spread != 0.0:
                print(f"[MODEL] Council spread adj {council_adjustment_spread:+.2f} computed but GATED (Phase 1 mode).")
        
        # Apply Caps
        if abs(mu_spread_final - mu_market_spread) > self.CAP_SPREAD:
             mu_spread_final = mu_market_spread + (self.CAP_SPREAD * math.copysign(1, mu_spread_final - mu_market_spread))

        # Total - with None-safe handling
        mu_torvik_total = torvik_view.get('total') or 145.0
        kenpom_total_adj = kenpom_adj.get('total_adj') or 0.0
        market_total = market_snapshot.get('total') or 145.0
        mu_kenpom_total = market_total + kenpom_total_adj

        # KenPom player-based (rotation-weighted) efficiency signal (best-effort)
        # This helps totals (PPP proxy) and later props.
        kp_player_total_adj = 0.0
        kp_team_player_home = None
        kp_team_player_away = None
        try:
            kp_team_player_home = self.kenpom_client.get_team_player_agg(event['home_team'])
            kp_team_player_away = self.kenpom_client.get_team_player_agg(event['away_team'])
            # Use ORtg_w deltas as a very small total adjustment (capped).
            if kp_team_player_home and kp_team_player_away:
                h_ortg = kp_team_player_home.get('ortg_w')
                a_ortg = kp_team_player_away.get('ortg_w')
                if h_ortg is not None and a_ortg is not None:
                    # ORtg is points per 100 possessions. Convert mismatch to points with a modest scale.
                    # Roughly: 5 ORtg pts difference ~ 1.0 total point.
                    delta = (float(h_ortg) + float(a_ortg)) / 2.0 - 105.0
                    kp_player_total_adj = max(min(delta * 0.10, 1.5), -1.5)
        except Exception as e:
            print(f"[MODEL] KenPom player agg error: {e}")
        
        # Ensure mu_market_total is not None
        if mu_market_total is None:
            mu_market_total = 145.0
        
        mu_total_final = mu_market_total + (w_base * (mu_torvik_total - mu_market_total)) + (self.W_KENPOM * (mu_kenpom_total - mu_market_total))
        mu_total_final += kp_player_total_adj
        potential_adjustment_total = council_adjustment_total
        if COUNCIL_ADJUSTMENTS_ENABLED:
            mu_total_final += council_adjustment_total
        else:
            if council_adjustment_total != 0.0:
                print(f"[MODEL] Council total adj {council_adjustment_total:+.2f} computed but GATED (Phase 1 mode).")
        
        if abs(mu_total_final - mu_market_total) > self.CAP_TOTAL:
             mu_total_final = mu_market_total + (self.CAP_TOTAL * math.copysign(1, mu_total_final - mu_market_total))

        # 6. Pace-Adjusted Sigma (Refined)
        # Higher tempo = more possessions = higher variance = wider sigma
        # Scaling: sqrt(tempo / avg) is theoretically correct for variance scaling.
        game_tempo = (torvik_team_stats or {}).get('game_tempo', 68.0) or 68.0
        tempo_factor = math.sqrt(game_tempo / 68.0)
        
        base_sigma_spread = 10.5
        base_sigma_total = 13.5  # Adjusted from 15.0 for accuracy
        
        
        sigma_spread = (base_sigma_spread * tempo_factor) + 0.1 * abs(diff_torvik)
        sigma_total = (base_sigma_total * tempo_factor) + 0.1 * abs(mu_torvik_total - mu_market_total)

        # --- Feature: Dynamic Sigma Inflation ---
        # If the Council identifies roster instability or significant red flags, 
        # inflate sigma to represent increased uncertainty (wider bell curve).
        if council_verdict:
            instability_found = False
            red_flags = council_verdict.get('signals', {}).get('red_flags', [])
            data_points = council_verdict.get('signals', {}).get('data_points', [])
            
            if red_flags: instability_found = True
            for dp in data_points:
                if dp.get('type') in ['injury', 'rotation']:
                    instability_found = True
                    break
            
            if instability_found:
                self.log_trace("Inflating sigma due to qualitative instability signals", {"event_id": event_id})
                sigma_spread *= 1.15
                sigma_total *= 1.15

        # Possessions validation: compare Torvik game_tempo vs KenPom team tempo (AdjT) average.
        kp_tempo = None
        kp_tempo_gap = None
        try:
            hr = self.kenpom_client.get_team_rating(event['home_team'])
            ar = self.kenpom_client.get_team_rating(event['away_team'])
            if hr and ar and hr.get('adj_t') is not None and ar.get('adj_t') is not None:
                kp_tempo = (float(hr['adj_t']) + float(ar['adj_t'])) / 2.0
                kp_tempo_gap = float(game_tempo) - float(kp_tempo)
                # If tempo sources disagree materially, inflate sigma_total (uncertainty).
                if abs(kp_tempo_gap) >= 3.0:
                    sigma_total *= 1.10
        except Exception as e:
            print(f"[MODEL] tempo validation error: {e}")

        # NOTE: We avoid hard sigma clamps; data-quality guardrails are applied later via
        # sanity scoring (sigma inflation / higher EV thresholds) rather than forcing caps.
        
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
        altitude_adj = self.geo_service.get_altitude_adjustment(event['home_team'], neutral_site=is_neutral) or 0.0
        if altitude_adj > 0:
            mu_spread_final -= altitude_adj

        # KenPom Home Court (best-effort): add a small adjustment for above/below average arenas.
        # We keep it modest because market + AdjEM already bake in generic HCA.
        kp_hca = 0.0
        try:
            if not is_neutral:
                hca_row = self.kenpom_client.get_home_court(event['home_team'])
                if hca_row and hca_row.get('hca') is not None:
                    hca_val = float(hca_row['hca'])
                    # baseline ~3.0-3.5; only use the deviation.
                    delta = hca_val - 3.2
                    kp_hca = max(min(delta * 0.5, 1.5), -1.5)  # cap
                    mu_spread_final -= kp_hca  # negative spread_home means home favored; stronger HCA boosts home
        except Exception as e:
            print(f"[MODEL] KenPom HCA error: {e}")

        # Travel
        dist = self.geo_service.calculate_distance(event['home_team'], event['away_team']) or 0.0
        if dist > 1000 and not is_neutral:
            mu_spread_final -= 0.5

        # --- Feature: Live Injury Impact Toggle ---
        if self.manual_adjustments:
            h_inj = self.manual_adjustments.get('home_injury', 0.0)
            a_inj = self.manual_adjustments.get('away_injury', 0.0)
            mu_spread_final += h_inj
            mu_spread_final -= a_inj

        # --- Feature: Basement Line (Power Rating) ---
        raw_basement_line = (mu_torvik_spread + mu_kenpom_line) / 2.0
        raw_basement_line += luck_adjustment
        if altitude_adj > 0: raw_basement_line -= altitude_adj
        if kp_hca: raw_basement_line -= kp_hca
        if dist > 1000 and not is_neutral: raw_basement_line -= 0.5
        if self.manual_adjustments:
            raw_basement_line += self.manual_adjustments.get('home_injury', 0.0)
            raw_basement_line -= self.manual_adjustments.get('away_injury', 0.0)
        
        # 6.5 Advanced Situational Signals
        # -- Shooting Regression (3PT Variance) --
        shooting_regr_home = self._calculate_shooting_regression(event['home_team']) or 0.0
        shooting_regr_away = self._calculate_shooting_regression(event['away_team']) or 0.0
        shooting_adj = shooting_regr_home - shooting_regr_away
        mu_spread_final += shooting_adj
        
        # -- Situational Spots (Letdown/Lookahead) --
        spot_adj_home = self._calculate_situational_spots(event['home_team'], event) or 0.0
        spot_adj_away = self._calculate_situational_spots(event['away_team'], event) or 0.0
        spot_adj = spot_adj_home - spot_adj_away
        mu_spread_final += spot_adj
        
        # -- Fatigue / Short Rest Signal --
        game_date = event.get('start_time')
        event_id = event.get('id')
        h_fatigue = self._calculate_fatigue_penalty(event['home_team'], event_id, game_date) or 0.0
        a_fatigue = self._calculate_fatigue_penalty(event['away_team'], event_id, game_date) or 0.0
        fatigue_adj = h_fatigue - a_fatigue
        mu_spread_final += fatigue_adj
        
        # -- Referee Signal (Totals) --
        mu_total_final = self._apply_referee_signal(event['id'], mu_total_final) or mu_total_final
        
        # 6.6 Generate Bell Curve Data for UI Visualization
        bell_curve_spread = self._generate_bell_curve(mu_spread_final, sigma_spread, mu_market_spread)
        bell_curve_total = self._generate_bell_curve(mu_total_final, sigma_total, mu_market_total)
            
        # 7. Recommendations & EV
        recs = self._generate_recommendations(mu_spread_final, sigma_spread, mu_total_final, sigma_total, market_snapshot, event, torvik_view=torvik_view, relax_gates=relax_gates)

        # Only fetch news context if something passed the gates.
        if recs:
            try:
                news_context = self.news_service.fetch_game_context(event['home_team'], event['away_team'])
            except Exception as e:
                print(f"[NEWS] fetch_game_context failed: {e}")
                news_context = {}
        
        # KenPom player stats (best-effort): currently used for UI/debug only.
        kp_players_home = []
        kp_players_away = []
        try:
            kp_players_home = self.kenpom_client.get_player_stats_for_team(event['home_team'], limit=50) or []
            kp_players_away = self.kenpom_client.get_player_stats_for_team(event['away_team'], limit=50) or []
        except Exception as e:
            print(f"[MODEL] KenPom player stats fetch error: {e}")

        debug_info = {
            "mu_spread_final": mu_spread_final,
            "sigma_spread": sigma_spread,
            "tempo_factor": tempo_factor,
            "luck_adj": luck_adjustment,
            "geo_adj": altitude_adj if 'altitude_adj' in locals() else 0.0,
            "kenpom_hca_adj": kp_hca if 'kp_hca' in locals() else 0.0,
            "is_neutral": is_neutral,
            "basement_line": raw_basement_line,
            "w_base": self.W_BASE,
            "shooting_adj": shooting_adj,
            "spot_adj": spot_adj,
            "fatigue_adj": fatigue_adj,
            "bell_curve_spread": bell_curve_spread,
            "bell_curve_total": bell_curve_total,
            "torvik_refresh": datetime.now().strftime('%Y-%m-%d %H:%M'),  # When Torvik data was fetched
            "kenpom_players_home_n": len(kp_players_home or []),
            "kenpom_players_away_n": len(kp_players_away or []),
            "kenpom_player_total_adj": kp_player_total_adj if 'kp_player_total_adj' in locals() else 0.0,
            "kenpom_team_player_home": kp_team_player_home,
            "kenpom_team_player_away": kp_team_player_away,
            "tempo_torvik": game_tempo,
            "tempo_kenpom": kp_tempo if 'kp_tempo' in locals() else None,
            "tempo_gap": kp_tempo_gap if 'kp_tempo_gap' in locals() else None,
            "council_adj_spread": council_adjustment_spread,
            "council_adj_total": council_adjustment_total,
        }
        
        mc = market_snapshot.get('_market_consensus') if isinstance(market_snapshot, dict) else None
        ctx = {
            'mu_spread_power': float(mu_spread_final) if mu_spread_final is not None else None,
            'mu_total_power': float(mu_total_final) if mu_total_final is not None else None,
            'sigma_spread': float(sigma_spread) if sigma_spread is not None else None,
            'sigma_total': float(sigma_total) if sigma_total is not None else None,
            'line_at_prediction_spread_home': (float(market_snapshot.get('spread_home')) if market_snapshot.get('spread_home') is not None else None) if isinstance(market_snapshot, dict) else None,
            'line_at_prediction_total': (float(market_snapshot.get('total')) if market_snapshot.get('total') is not None else None) if isinstance(market_snapshot, dict) else None,
            'open_spread_home': _safe_float(mc.get('open_spread_home')) if mc else None,
            'current_spread_home': _safe_float(mc.get('current_spread_home')) if mc else None,
            'spread_move_home': _safe_float(mc.get('spread_move_home')) if mc else None,
            'open_total': _safe_float(mc.get('open_total')) if mc else None,
            'current_total': _safe_float(mc.get('current_total')) if mc else None,
            'total_move': _safe_float(mc.get('total_move')) if mc else None,
            'spread_disagreement': _safe_float(mc.get('spread_disagreement')) if mc else None,
            'total_disagreement': _safe_float(mc.get('total_disagreement')) if mc else None,
            'as_of': (mc.get('as_of') if mc else None),
        }

        # 8. Narrative (UI MATCH)
        # Pass raw odds so we can generate matchup-specific key factors (e.g., line movement)
        narrative = self._generate_narrative(event, market_snapshot, torvik_view, kenpom_adj, news_context, recs, raw_snaps=raw_snaps, debug_info=debug_info)
        
        # 9. Result Object
        ui_recs = []
        best_rec = None

        # If we produced no actionable recommendations, capture why (for UI).
        block_reason = None
        try:
            if not recs and isinstance(market_snapshot, dict):
                block_reason = market_snapshot.get('_no_bet_reason_spread') or market_snapshot.get('_no_bet_reason_total')
        except Exception:
            block_reason = None

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

                # Convert to the side being bet (home vs away).
                # `r['side']` is usually 'home'/'away' (not a team name).
                side_key = str(r.get('side') or '').lower().strip()
                is_home_side = (side_key == 'home') or (r.get('team') == event.get('home_team')) or (r.get('side') == event.get('home_team'))

                if is_home_side:
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

            # Build a human-friendly selection label.
            # IMPORTANT: For SPREAD, include the sign (+/-) so underdogs aren't displayed as favorites.
            sel = None
            if r['market'] == 'SPREAD':
                team = r.get('team') or (event['home_team'] if r.get('side') == 'home' else event['away_team'])
                if r.get('line') is not None:
                    try:
                        v = float(r.get('line'))
                        sign = '+' if v > 0 else ''
                        sel = f"{team} {sign}{v:g}"
                    except Exception:
                        sel = team + f" {r.get('line')}"
                else:
                    sel = team
            elif r['market'] == 'TOTAL':
                side = str(r.get('side') or '').upper()
                sel = side + (f" {r['line']}" if r.get('line') is not None else "")
            else:
                sel = str(r.get('side') or '')

            lb10 = (round(float(r.get('win_prob_lb10')), 3) if r.get('win_prob_lb10') is not None else None)
            ub90 = (round(float(r.get('win_prob_ub90')), 3) if r.get('win_prob_ub90') is not None else None)
            bounds_available = (lb10 is not None) and (ub90 is not None)

            ui_rec = {
                "bet_type": r['market'],
                "selection": sel,
                # Keep legacy key name for UI, but this is EV% not points.
                "edge": f"{(r['ev']*100):.1f}%",
                "win_prob": round(float(win_prob), 3) if win_prob is not None else None,
                "win_prob_lb10": lb10,
                "win_prob_ub90": ub90,
                "bounds_available": bool(bounds_available),
                "bounds_note": (None if bounds_available else 'bounds unavailable'),
                "market_line": (round(float(market_line_side), 1) if market_line_side is not None else None),
                "fair_line": (round(float(fair_line_side), 1) if fair_line_side is not None else None),
                "edge_points": edge_points_side,
                "price": int(r.get('price')) if r.get('price') is not None else None,
                "kelly": float(r.get('kelly')) if r.get('kelly') is not None else None,
                # Confidence = model confidence that the bet wins (based on calibrated win_prob lower bound)
                "confidence": self._confidence_label_from_winprob(r.get('win_prob_lb10') if isinstance(r, dict) else None, fallback_win_prob=win_prob),
                "book": r['book'],
                # Movement/uncertainty instrumentation
                "sigma_mult": r.get('sigma_mult'),
                "ev_raw": r.get('ev_raw'),
                "ev_penalty": r.get('ev_penalty'),
                "movement_tags": r.get('movement_tags'),
                "prediction_id": r.get('prediction_id'),
            }
            ui_recs.append(ui_rec)
            r['_ui_rec'] = ui_rec
            if not best_rec or r['ev'] > best_rec['ev']:
                best_rec = r

        inputs_payload = {
            "market": market_snapshot,
            "torvik": torvik_view,
            "kenpom": kenpom_adj,
            "news": news_context
        }
        outputs_payload = {
            "mu_spread": mu_spread_final,
            "mu_total": mu_total_final,
            "recommendations": recs,
            "debug": debug_info,
            "potential_adjustment": {
                "spread": potential_adjustment_spread,
                "total": potential_adjustment_total,
                "gated": not COUNCIL_ADJUSTMENTS_ENABLED
            }
        }
        inputs_json_str = json.dumps(inputs_payload, default=str)
        outputs_json_str = json.dumps(outputs_payload, default=str)
        narrative_json_str = json.dumps(narrative, default=str)
        context_json_str = json.dumps(ctx, default=str)

        inserted_best_doc_id = None
        if recs:
            def _normalize_spread_line(side, raw_line):
                if raw_line is None:
                    return None
                try:
                    val = float(raw_line)
                except Exception:
                    return None
                spread_home = market_snapshot.get('spread_home')
                if spread_home is None:
                    return val
                home_sign = -1.0 if float(spread_home) < 0 else 1.0
                abs_val = abs(val)
                if side == 'away':
                    return -home_sign * abs_val
                return home_sign * abs_val

            def _build_rec_doc(rec):
                mkt = str(rec.get('market') or '').upper()
                side = str(rec.get('side') or '').lower()
                line_val = rec.get('line')
                price = rec.get('price')
                book = rec.get('book') or 'Consensus'
                pick = None
                bet_line = None
                selection = str(rec.get('selection') or '')
                mu_market = None
                mu_torvik_val = None
                mu_final_val = None
                sigma_val = None
                edge = None

                if mkt == 'SPREAD':
                    pick = event.get('home_team') if side == 'home' else event.get('away_team')
                    bet_line = _normalize_spread_line(side, line_val)
                    if pick and bet_line is not None:
                        selection = f"{pick} {bet_line:+.1f}"
                    else:
                        selection = pick or selection or 'SPREAD'
                    spread_home = market_snapshot.get('spread_home')
                    if spread_home is None:
                        mu_market = None
                    else:
                        mu_market = float(spread_home)
                    if side == 'away':
                        if mu_market is not None:
                            mu_market = -mu_market
                        mu_torvik_val = -mu_torvik_spread
                        mu_final_val = -mu_spread_final if mu_spread_final is not None else None
                    else:
                        mu_torvik_val = mu_torvik_spread
                        mu_final_val = mu_spread_final
                    sigma_val = sigma_spread
                    if mu_market is not None and mu_final_val is not None:
                        edge = float(mu_market) - float(mu_final_val)
                elif mkt == 'TOTAL':
                    pick = (rec.get('side') or 'OVER').upper()
                    try:
                        bet_line = float(line_val) if line_val is not None else None
                    except Exception:
                        bet_line = None
                    selection = selection or (f"{pick} {bet_line}" if bet_line is not None else pick)
                    mu_market = float(market_snapshot.get('total') or 145.0)
                    mu_torvik_val = mu_torvik_total
                    mu_final_val = mu_total_final
                    sigma_val = sigma_total
                    if mu_market is not None and mu_final_val is not None:
                        edge = float(mu_final_val) - float(mu_market)
                else:
                    pick = rec.get('team') or event.get('home_team')
                    bet_line = line_val
                    selection = selection or pick
                    mu_market = float(market_snapshot.get('total') or 145.0)
                    mu_torvik_val = mu_torvik_total
                    mu_final_val = mu_total_final
                    sigma_val = sigma_total
                    if mu_market is not None and mu_final_val is not None:
                        edge = float(mu_final_val) - float(mu_market)

                doc = {
                    "event_id": event_id,
                    "model_version": self.VERSION,
                    "market_type": mkt,
                    "pick": pick,
                    "bet_line": bet_line,
                    "bet_price": int(price) if price is not None else None,
                    "book": book,
                    "mu_market": mu_market,
                    "mu_torvik": mu_torvik_val,
                    "mu_final": mu_final_val,
                    "sigma": sigma_val,
                    "win_prob": float(rec.get('win_prob') or 0.0),
                    "ev_per_unit": float(rec.get('ev') or 0.0),
                    "confidence_0_100": int(round((rec.get('win_prob_lb10') or rec.get('win_prob') or 0.5) * 100)),
                    "selection": selection,
                    "price": int(price) if price is not None else None,
                    "fair_line": mu_final_val,
                    "edge_points": float(round(edge, 4)) if edge is not None else None,
                    "inputs_json": inputs_json_str,
                    "outputs_json": outputs_json_str,
                    "narrative_json": narrative_json_str,
                    "context_json": context_json_str,
                }
                return doc

            ordered_recs = []
            if best_rec:
                ordered_recs.append(best_rec)
            ordered_recs.extend([r for r in recs if r is not best_rec])
            for rec in ordered_recs:
                doc = _build_rec_doc(rec)
                try:
                    insert_model_prediction(doc)
                except Exception as e:
                    print(f"[MODEL] failed to persist rec {rec.get('market')} {rec.get('side')}: {e}")
                    continue
                rec['prediction_id'] = doc.get('id')
                ui_ref = rec.get('_ui_rec')
                if ui_ref is not None:
                    ui_ref['prediction_id'] = doc.get('id')
                if rec is best_rec:
                    inserted_best_doc_id = doc.get('id')
        best_prediction_id = inserted_best_doc_id
        # --- Persisted pick normalization ---
        # For SPREAD we want the persisted `pick` to be the actual team name (not "home/away"),
        # and `bet_line` to be relative to that pick (signed).
        persisted_pick = best_rec['side'] if best_rec else "NONE"
        persisted_line = best_rec['line'] if best_rec else None
        persisted_selection = best_rec['side'] if best_rec else None

        try:
            if best_rec and str(best_rec.get('market') or '').upper() == 'SPREAD':
                side = str(best_rec.get('side') or '').lower().strip()
                home_team = event.get('home_team')
                away_team = event.get('away_team')

                # Convert home/away -> team names
                if side == 'home' and home_team:
                    persisted_pick = home_team
                elif side == 'away' and away_team:
                    persisted_pick = away_team

                # Ensure spread line is signed relative to HOME convention if we have spread_home.
                # Many of our snapshot pipelines store absolute spread with side=HOME/AWAY.
                # If we can infer the home sign from market_snapshot['spread_home'], use it.
                if persisted_line is not None:
                    try:
                        line_abs = abs(float(persisted_line))
                        spread_home = market_snapshot.get('spread_home')
                        if spread_home is not None:
                            home_sign = -1.0 if float(spread_home) < 0 else 1.0
                            if side == 'home':
                                persisted_line = home_sign * line_abs
                            elif side == 'away':
                                persisted_line = -home_sign * line_abs
                            else:
                                persisted_line = float(persisted_line)
                        else:
                            persisted_line = float(persisted_line)
                    except Exception:
                        pass

                # Build human selection like "Creighton -4.5" / "West Virginia +6.5"
                if persisted_pick and persisted_line is not None:
                    try:
                        v = float(persisted_line)
                        sign = '+' if v > 0 else ''
                        persisted_selection = f"{persisted_pick} {sign}{v:g}"
                    except Exception:
                        persisted_selection = f"{persisted_pick} {persisted_line}"

            elif best_rec and str(best_rec.get('market') or '').upper() == 'TOTAL':
                side = str(best_rec.get('side') or '').upper().strip()
                persisted_pick = side
                persisted_selection = f"{side} {best_rec.get('line')}" if best_rec.get('line') is not None else side
        except Exception:
            # never block analyze() on persistence formatting
            pass

        # -------------------------
        # Persistence semantics (critical)
        # - For SPREAD: store all lines in *pick-side perspective* (same sign as bet_line)
        #   so they are comparable to close_line (side-specific snapshot).
        # - For TOTAL: store totals in absolute points (e.g., 145.5), not deltas.
        # -------------------------
        persisted_market_type = best_rec['market'] if best_rec else "AUTO"

        # Market line in HOME perspective
        mkt_spread_home = market_snapshot.get('spread_home')
        mkt_total = market_snapshot.get('total')

        # Fair line in HOME perspective
        fair_spread_home = mu_spread_final
        fair_total = mu_total_final

        # Torvik in HOME perspective
        torvik_spread_home = mu_torvik_spread
        torvik_total = mu_torvik_total

        # Convert to pick-side perspective
        mu_market_persist = None
        mu_torvik_persist = None
        mu_final_persist = None
        sigma_persist = None
        fair_line_persist = None
        edge_points_persist = None

        try:
            if persisted_market_type == 'SPREAD':
                sigma_persist = sigma_spread
                side = str(best_rec.get('side') or '').lower().strip() if best_rec else ''
                if side == 'home':
                    mu_market_persist = float(mkt_spread_home) if mkt_spread_home is not None else None
                    mu_torvik_persist = float(torvik_spread_home) if torvik_spread_home is not None else None
                    mu_final_persist = float(fair_spread_home) if fair_spread_home is not None else None
                else:
                    mu_market_persist = (-float(mkt_spread_home)) if mkt_spread_home is not None else None
                    mu_torvik_persist = (-float(torvik_spread_home)) if torvik_spread_home is not None else None
                    mu_final_persist = (-float(fair_spread_home)) if fair_spread_home is not None else None

                fair_line_persist = mu_final_persist
                # edge in points relative to pick-side market
                if mu_market_persist is not None and mu_final_persist is not None:
                    edge_points_persist = round(float(mu_market_persist) - float(mu_final_persist), 2)

            elif persisted_market_type == 'TOTAL':
                sigma_persist = sigma_total
                mu_market_persist = float(mkt_total) if mkt_total is not None else None
                mu_torvik_persist = float(torvik_total) if torvik_total is not None else None
                mu_final_persist = float(fair_total) if fair_total is not None else None
                fair_line_persist = mu_final_persist
                if mu_market_persist is not None and mu_final_persist is not None:
                    edge_points_persist = round(float(mu_final_persist) - float(mu_market_persist), 2)

        except Exception:
            pass

        # Persist prediction-time context for calibration.


        res = {
            "id": best_prediction_id or None,
            "event_id": event_id,
            "home_team": event['home_team'],
            "away_team": event['away_team'],
            "analyzed_at": datetime.now().isoformat(),
            "model_version": self.VERSION,
            "market_type": persisted_market_type,
            "pick": persisted_pick,
            "bet_line": persisted_line,
            "bet_price": best_rec['price'] if best_rec else None,
            "book": best_rec['book'] if best_rec else None,
            "mu_market": mu_market_persist,
            "mu_torvik": mu_torvik_persist,
            "mu_final": mu_final_persist,
            "sigma": sigma_persist,
            "win_prob": best_rec['win_prob'] if best_rec else 0.5,
            "ev_per_unit": best_rec['ev'] if best_rec else 0.0,
            "kelly": best_rec['kelly'] if best_rec else 0.0,
            "confidence_0_100": int(best_rec['ev'] * 100 * 5) if best_rec else 0,
            "inputs_json": inputs_json_str,
            "outputs_json": outputs_json_str,
            "narrative": narrative,
            "narrative_json": narrative_json_str,
            "context_json": context_json_str,
            "is_actionable": bool(ui_recs),
            "block_reason": block_reason,
            "recommendations": ui_recs,
            "torvik_view": torvik_view,
            "torvik_team_stats": torvik_team_stats,
            "game_script": game_script,
            "kenpom_data": kenpom_adj,
            "news_summary": self.news_service.summarize_impact(news_context),
            "potential_adjustment": {
                "spread": potential_adjustment_spread,
                "total": potential_adjustment_total,
                "gated": not COUNCIL_ADJUSTMENTS_ENABLED
            },
            "key_factors": narrative.get('key_factors') or [],
            "risks": narrative.get('risks') or [],
            "selection": persisted_selection,
            "price": best_rec['price'] if best_rec else None,
            "fair_line": fair_line_persist,
            "edge_points": edge_points_persist,
            "open_line": best_rec['line'] if best_rec else None,
            "open_price": best_rec['price'] if best_rec else None,
            "clv_method": "odds_selector_v1",
            "debug": debug_info
        }
        if not res['id']:
            import uuid
            res['id'] = str(uuid.uuid4())

        # 10. Persist
        # Only keep history for recommended bets (avoid storing analysis-only rows).
        should_persist = bool(best_rec) and (float(res.get('ev_per_unit') or 0.0) >= self.PUBLISH_MIN_EV)
        should_persist = should_persist and str(res.get('market_type') or '').upper() not in ('', 'AUTO')
        should_persist = should_persist and str(res.get('pick') or '').upper() not in ('', 'NONE')
        should_persist = should_persist and (res.get('selection') is not None and str(res.get('selection')).strip() not in ('', '—'))

        # Lock window: do not persist new/updated picks inside 10 minutes to tip.
        try:
            from datetime import timezone
            st = event.get('start_time')
            if st is not None:
                if isinstance(st, str):
                    st = datetime.fromisoformat(st.replace('Z', '+00:00'))
                if getattr(st, 'tzinfo', None) is None:
                    st = st.replace(tzinfo=timezone.utc)
                now_dt = datetime.now(timezone.utc)
                if now_dt >= (st - timedelta(minutes=10)):
                    should_persist = False
        except Exception:
            pass

        if persist and should_persist:
            insert_model_prediction(res)

        # 10b. Persist ML prediction (separate row)
        # This does NOT change the existing spread/total recommendation selection.
        # It exists to power 2-leg ML parlay construction.
        try:
            from src.utils.ev import ev_per_unit, implied_prob_american

            # Determine best ML prices (prefer best book, fallback to consensus).
            best_ml_home = (market_snapshot.get('_best_moneyline_home') or {}) if isinstance(market_snapshot, dict) else {}
            best_ml_away = (market_snapshot.get('_best_moneyline_away') or {}) if isinstance(market_snapshot, dict) else {}
            ml_price_home = best_ml_home.get('price') if best_ml_home else None
            ml_price_away = best_ml_away.get('price') if best_ml_away else None
            ml_book_home = best_ml_home.get('book') if best_ml_home else (market_snapshot.get('book_ml') if isinstance(market_snapshot, dict) else None)
            ml_book_away = best_ml_away.get('book') if best_ml_away else (market_snapshot.get('book_ml') if isinstance(market_snapshot, dict) else None)

            if ml_price_home is None and isinstance(market_snapshot, dict):
                ml_price_home = market_snapshot.get('moneyline_price_home')
            if ml_price_away is None and isinstance(market_snapshot, dict):
                ml_price_away = market_snapshot.get('moneyline_price_away')

            # Compute home win prob from margin distribution: P(margin_home > 0)
            # mu_spread_final is home-perspective margin mean.
            if ml_price_home is not None and ml_price_away is not None:
                prob_home_raw = 1.0 - self._normal_cdf(0.0, -float(mu_spread_final), float(sigma_spread))
                prob_home = self._calibrate_win_prob(prob_home_raw)
                prob_away = self._calibrate_win_prob(1.0 - prob_home_raw)

                ev_home = float(ev_per_unit(prob_home, int(ml_price_home)) or 0.0)
                ev_away = float(ev_per_unit(prob_away, int(ml_price_away)) or 0.0)

                # Choose side with higher EV
                side = 'HOME' if ev_home >= ev_away else 'AWAY'
                team = event.get('home_team') if side == 'HOME' else event.get('away_team')
                price = int(ml_price_home) if side == 'HOME' else int(ml_price_away)
                book = ml_book_home if side == 'HOME' else ml_book_away
                wp = prob_home if side == 'HOME' else prob_away
                ev = ev_home if side == 'HOME' else ev_away

                # Gate persistence similarly to straight picks
                should_persist_ml = float(ev or 0.0) >= float(self.PUBLISH_MIN_EV)
                should_persist_ml = should_persist_ml and team is not None and str(team).strip() != ''

                # Apply same lock window
                if should_persist_ml:
                    try:
                        from datetime import timezone
                        st = event.get('start_time')
                        if st is not None:
                            if isinstance(st, str):
                                st = datetime.fromisoformat(st.replace('Z', '+00:00'))
                            if getattr(st, 'tzinfo', None) is None:
                                st = st.replace(tzinfo=timezone.utc)
                            now_dt = datetime.now(timezone.utc)
                            if now_dt >= (st - timedelta(minutes=10)):
                                should_persist_ml = False
                    except Exception:
                        pass

                if persist and should_persist_ml:
                    import uuid
                    edge_prob = None
                    try:
                        ip = implied_prob_american(price)
                        edge_prob = (float(wp) - float(ip)) if ip is not None else None
                    except Exception:
                        edge_prob = None

                    doc_ml = {
                        **{k: res.get(k) for k in ("event_id", "user_id", "analyzed_at", "model_version", "mu_market", "mu_torvik", "mu_final", "sigma", "inputs_json", "outputs_json", "narrative_json", "context_json")},
                        "id": str(uuid.uuid4()),
                        "market_type": "MONEYLINE",
                        "pick": team,
                        "bet_line": None,
                        "bet_price": price,
                        "book": book,
                        "win_prob": float(wp),
                        "ev_per_unit": float(ev),
                        "confidence_0_100": int(float(ev) * 100 * 5),
                        "selection": str(team),
                        "price": price,
                        # Store probability edge as edge_points for ML (not points).
                        "edge_points": (round(float(edge_prob), 4) if edge_prob is not None else None),
                        "open_line": None,
                        "open_price": price,
                        "clv_method": "odds_selector_v1",
                    }
                    insert_model_prediction(doc_ml)
        except Exception as e:
            # never block analyze() on ML persistence
            try:
                print(f"[MODEL] ML persistence skipped: {e}")
            except Exception:
                pass

        return res

    # --- Publication gates (Research tab) ---
    # Straight bets only for now. (Correlation/parlays are handled elsewhere.)
    PUBLISH_MIN_EV = 0.02  # +2.0% per unit
    PUBLISH_CI_Z = 1.96    # 95% CI on archetype mean
    PUBLISH_MIN_N_TORVIK_OK = 40
    PUBLISH_MIN_N_TORVIK_MISSING = 60
    PUBLISH_MIN_EV_TORVIK_MISSING_BUMP = 0.005  # +0.5%

    _archetype_cache: Dict[str, Dict[str, Any]] = {}

    def _archetype_key(self, market: str, side: str, edge_pts: float, spread_bucket: Optional[str], torvik_ok: bool) -> str:
        # Coarse buckets to stabilize stats.
        edge_bucket = int(round(min(10.0, max(0.0, float(edge_pts)))))
        sb = spread_bucket or "na"
        tv = "tv" if torvik_ok else "no_tv"
        s = (side or "").lower().replace(" ", "_")
        return f"{market}:{s}:{edge_bucket}:{sb}:{tv}"

    def _spread_bucket(self, market_line_home: float) -> str:
        # Used for correlation-driven rules; for now only affects gating / future combos.
        try:
            v = abs(float(market_line_home or 0.0))
        except Exception:
            v = 0.0
        if v <= 3.0:
            return "close"
        if v <= 7.0:
            return "mid"
        return "big"

    def _realized_roi_per_unit(self, outcome: str, price: int) -> Optional[float]:
        """Convert outcome + price into realized ROI per 1u risked."""
        if not outcome:
            return None
        o = str(outcome).upper()
        if o in ("PUSH",):
            return 0.0
        if o not in ("WON", "LOST"):
            return None

        # payout per 1u risk
        if price is None:
            price = -110
        price = int(price)
        payout = (price / 100.0) if price > 0 else (100.0 / abs(price))
        return payout if o == "WON" else -1.0

    _action_network_stats: Optional[Dict[str, Any]] = None

    def _load_action_network_stats(self) -> Dict[str, Any]:
        if self._action_network_stats is not None:
            return self._action_network_stats

        import os
        import json

        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(repo_root, 'data', 'model_params', 'action_network_archetype_stats_ncaam.json')

        try:
            with open(path, 'r', encoding='utf-8') as f:
                self._action_network_stats = json.load(f)
        except Exception:
            self._action_network_stats = {"bins": {}}

        return self._action_network_stats

    def _get_archetype_stats(self, key: str) -> Dict[str, Any]:
        """Return realized ROI stats for an archetype key.

        Canonical source: Action Network history artifact (precomputed).
        """
        stats = self._load_action_network_stats()
        bins = (stats or {}).get('bins') or {}

        # key here includes tv-flag; artifact does not. Strip the suffix.
        # expected: MARKET:side:edge_bucket:spread_bucket:tv_flag
        parts = key.split(':')
        short_key = ':'.join(parts[:4]) if len(parts) >= 4 else key

        row = bins.get(short_key) or {}

        n = int(row.get('n') or 0)
        mean = float(row.get('mean') or 0.0)
        sd = float(row.get('sd') or 0.0)

        # Fallback (especially for TOTAL): if the specific edge bucket has thin history,
        # aggregate across all edge buckets for the same (market, side, spread_bucket).
        # This increases coverage without weakening the EV requirement itself.
        try:
            parts = short_key.split(':')
            market = (parts[0] if len(parts) > 0 else '')
            side = (parts[1] if len(parts) > 1 else '')
            spread_bucket = (parts[3] if len(parts) > 3 else 'na')

            if (market == 'TOTAL') and n < 40:
                prefix = f"TOTAL:{side}:"
                # keys look like TOTAL:over:<edge_bucket>:na
                candidates = [(k, v) for k, v in bins.items() if isinstance(k, str) and k.startswith(prefix) and k.endswith(f":{spread_bucket}")]

                # Weighted mean + pooled sd (best-effort)
                N = 0
                sum_mu = 0.0
                sum_m2 = 0.0
                for _, v in candidates:
                    try:
                        nn = int(v.get('n') or 0)
                        mu = float(v.get('mean') or 0.0)
                        s = float(v.get('sd') or 0.0)
                        if nn <= 0:
                            continue
                        # within-bin M2
                        m2 = (s ** 2) * max(0, nn - 1)
                        # combine
                        if N == 0:
                            N = nn
                            sum_mu = mu * nn
                            sum_m2 = m2
                        else:
                            # merge two groups
                            muA = sum_mu / N
                            muB = mu
                            NA = N
                            NB = nn
                            delta = muB - muA
                            sum_m2 = sum_m2 + m2 + (delta ** 2) * (NA * NB) / (NA + NB)
                            N = NA + NB
                            sum_mu = muA * NA + muB * NB
                    except Exception:
                        continue

                if N >= 40:
                    mean = sum_mu / N
                    sd = ((sum_m2 / (N - 1)) ** 0.5) if N > 1 else 0.0
                    n = N
        except Exception:
            pass

        return {"n": n, "mean": mean, "sd": sd}

    def _passes_publish_gates(self, rec: Dict[str, Any], market_line_home: Optional[float], torvik_ok: bool) -> bool:
        """Research publish gates.

        Requirements:
        - EV ≥ +2.0%
        - lower-bound EV (95% CI on archetype realized ROI mean) ≥ 0.0%
        - MIN_N ≥ 40 (or 60 if Torvik missing)
        - If Torvik missing: EV threshold +0.5%
        """

        ev = float(rec.get("ev") or 0.0)
        edge_pts = float(rec.get("edge_points") or 0.0)
        market = str(rec.get("market") or "")

        spread_bucket = None
        if market == "SPREAD":
            spread_bucket = self._spread_bucket(market_line_home or 0.0)

        # Action Network archetype artifact bins by coarse edge_bucket (|fair-market|).
        # Use the actual computed edge points for lookup.
        key = self._archetype_key(market, side=str(rec.get('side') or ''), edge_pts=edge_pts, spread_bucket=spread_bucket, torvik_ok=torvik_ok)
        stats = self._get_archetype_stats(key)

        min_n = self.PUBLISH_MIN_N_TORVIK_OK if torvik_ok else self.PUBLISH_MIN_N_TORVIK_MISSING
        min_ev = self.PUBLISH_MIN_EV if torvik_ok else (self.PUBLISH_MIN_EV + self.PUBLISH_MIN_EV_TORVIK_MISSING_BUMP)

        if ev < min_ev:
            return False

        if (stats.get("n") or 0) < min_n:
            return False

        n = int(stats.get("n") or 0)
        mean = float(stats.get("mean") or 0.0)
        sd = float(stats.get("sd") or 0.0)
        se = (sd / (n ** 0.5)) if (n > 1 and sd > 0) else 0.0
        lb = mean - (self.PUBLISH_CI_Z * se)

        # Standard rule: lower-bound EV must be >= 0
        # Override ("reward mode", option B): allow a small number of high-EV, high-edge plays
        # even if the archetype lower bound is negative. This is used to keep the system placing
        # some bets so we can learn/improve.
        override_ev = float(os.getenv('PUBLISH_OVERRIDE_MIN_EV', '0.06'))  # 6%
        override_edge = float(os.getenv('PUBLISH_OVERRIDE_MIN_EDGE_PTS', '2.0'))
        
        # Totals have wider variances; applying an identical EV constraint effectively bans them 
        if market == 'TOTAL':
            override_ev = float(os.getenv('PUBLISH_OVERRIDE_MIN_EV_TOTAL', '0.03'))  # 3%
            override_edge = float(os.getenv('PUBLISH_OVERRIDE_MIN_EDGE_PTS_TOTAL', '1.5'))

        override_ok = (ev >= override_ev) and (edge_pts >= override_edge) and (n >= min_n)

        if lb < 0.0 and not override_ok:
            return False

        # attach stats for debugging/UI if needed
        rec["archetype"] = {"key": key, "n": n, "mean": mean, "lb95": lb, "override_ok": override_ok}
        return True

    _winprob_calibration: Optional[Dict[str, Any]] = None

    def _load_winprob_calibration(self) -> Dict[str, Any]:
        """Load piecewise-linear win_prob calibration mapping (if present)."""
        if self._winprob_calibration is not None:
            return self._winprob_calibration

        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(repo_root, 'data', 'model_params', 'winprob_calibration_ncaam.json')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self._winprob_calibration = json.load(f)
        except Exception:
            self._winprob_calibration = {"points": []}
        return self._winprob_calibration

    def _calibrate_win_prob(self, p: float) -> float:
        """Calibrate raw win probability using a monotonic piecewise-linear mapping."""
        try:
            p = float(p)
        except Exception:
            return p

        if p <= 0.0:
            return 0.0
        if p >= 1.0:
            return 1.0

        cal = self._load_winprob_calibration() or {}
        pts = cal.get('points') or []
        if not pts or len(pts) < 2:
            return p

        xs = [float(x.get('p')) for x in pts if x and x.get('p') is not None]
        ys = [float(x.get('p_cal')) for x in pts if x and x.get('p_cal') is not None]
        if len(xs) != len(ys) or len(xs) < 2:
            return p

        # If outside range, clamp to endpoints
        if p <= xs[0]:
            return max(0.0, min(1.0, ys[0]))
        if p >= xs[-1]:
            return max(0.0, min(1.0, ys[-1]))

        # Linear interpolate
        for i in range(1, len(xs)):
            if p <= xs[i]:
                x0, x1 = xs[i - 1], xs[i]
                y0, y1 = ys[i - 1], ys[i]
                if x1 == x0:
                    return max(0.0, min(1.0, y1))
                t = (p - x0) / (x1 - x0)
                y = y0 + t * (y1 - y0)
                return max(0.0, min(1.0, y))
        return p

    _model_conf_params: Optional[Dict[str, Any]] = None

    def _load_model_conf_params(self) -> Dict[str, Any]:
        """Load model uncertainty params (tau) used for confidence intervals."""
        if self._model_conf_params is not None:
            return self._model_conf_params

        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(repo_root, 'data', 'model_params', 'model_confidence_params_ncaam.json')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self._model_conf_params = json.load(f)
        except Exception:
            self._model_conf_params = {}
        return self._model_conf_params

    def _tau_for_market(self, market: str) -> float:
        """Return tau for mu-uncertainty simulations.

        Disabled by default (requires ENABLE_MU_UNCERTAINTY_CONF=1) because it depends on
        close_line/mu_final data integrity.
        """
        try:
            if str(os.getenv('ENABLE_MU_UNCERTAINTY_CONF', '0')).strip() != '1':
                return 0.0
            params = self._load_model_conf_params() or {}
            if str(market).upper() == 'TOTAL':
                return float(params.get('tau_total') or 0.0)
            return float(params.get('tau_spread') or 0.0)
        except Exception:
            return 0.0

    def _quantile(self, xs: List[float], q: float) -> Optional[float]:
        if not xs:
            return None
        xs = sorted(xs)
        q = max(0.0, min(1.0, float(q)))
        idx = int(round(q * (len(xs) - 1)))
        idx = max(0, min(len(xs) - 1, idx))
        return float(xs[idx])

    def _confidence_bounds_from_mu_uncertainty(
        self,
        market: str,
        mu: float,
        sigma: float,
        line: float,
        side: str,
        n_sims: int = 600,
    ) -> Dict[str, Optional[float]]:
        """Compute win_prob bounds by sampling uncertainty in mu.

        Returns calibrated p10/p90 bounds for P(bet wins).
        NOTE: `mu` and `line` are passed in HOME perspective for SPREAD, and absolute for TOTAL.
        """
        import random

        tau = self._tau_for_market(market)
        if not (tau and tau > 0.0 and sigma and sigma > 0.0):
            return {"lb10": None, "ub90": None}

        probs: List[float] = []
        mkt = str(market).upper()
        side = str(side).lower().strip()

        def _push_prob(line_v: float) -> float:
            try:
                if float(line_v) % 1 != 0:
                    return 0.0
                key_numbers = {2, 3, 4, 5, 6, 7, 10, 14}
                return 0.05 if abs(float(line_v)) in key_numbers else 0.03
            except Exception:
                return 0.0

        for _ in range(int(n_sims)):
            mu_true = float(mu) + random.gauss(0.0, float(tau))

            if mkt == 'SPREAD':
                # Home cover probability using same convention as main path
                prob_home_raw = 1.0 - self._normal_cdf(-float(line), -float(mu_true), float(sigma))
                push_prob = _push_prob(float(line))
                p_home = prob_home_raw - (push_prob / 2)
                p_away = (1.0 - prob_home_raw) - (push_prob / 2)
                p = p_home if side == 'home' else p_away

            else:
                prob_over_raw = 1.0 - self._normal_cdf(float(line), float(mu_true), float(sigma))
                push_prob = _push_prob(float(line))
                p_over = prob_over_raw - (push_prob / 2)
                p_under = (1.0 - prob_over_raw) - (push_prob / 2)
                p = p_over if side == 'over' else p_under

            probs.append(self._calibrate_win_prob(p))

        return {
            "lb10": self._quantile(probs, 0.10),
            "ub90": self._quantile(probs, 0.90),
        }

    def _confidence_label_from_winprob(self, lb10: Optional[float], fallback_win_prob: Optional[float] = None) -> str:
        # Use lower-bound if available; else fall back to point estimate.
        p = lb10 if lb10 is not None else fallback_win_prob
        try:
            p = float(p)
        except Exception:
            return 'Low'

        if p >= 0.55:
            return 'High'
        if p >= 0.52:
            return 'Medium'
        return 'Low'

    def _generate_recommendations(self, mu_s, sig_s, mu_t, sig_t, snap, event, torvik_view: Optional[Dict[str, Any]] = None, relax_gates: bool = False) -> List[Dict]:
        recs: List[Dict[str, Any]] = []
        if not snap:
            return recs

        # Torvik availability: do not hard-require; used to tighten gates.
        torvik_ok = True
        try:
            if not torvik_view:
                torvik_ok = False
            elif str(torvik_view.get("lean") or "").lower().strip() in ("no data", ""):
                torvik_ok = False
        except Exception:
            torvik_ok = False

        # Helper: Push probability for whole-number lines
        def get_push_prob(line, sigma):
            """Estimate push probability for whole-number lines."""
            if line is None:
                return 0.0
            if line % 1 != 0:
                return 0.0
            key_numbers = {2, 3, 4, 5, 6, 7, 10, 14}
            if abs(line) in key_numbers:
                return 0.05
            return 0.03

        def _spread_cover_prob_home(mu_home: float, sigma: float, line_home: float) -> float:
            """P(Home covers) given home-perspective mu and home spread line."""
            prob_home_raw = 1.0 - self._normal_cdf(-float(line_home), -float(mu_home), float(sigma))
            push_prob = get_push_prob(float(line_home), float(sigma))
            return prob_home_raw - (push_prob / 2)

        def _total_over_prob(mu_total: float, sigma: float, total_line: float) -> float:
            prob_over_raw = 1.0 - self._normal_cdf(float(total_line), float(mu_total), float(sigma))
            push_prob = get_push_prob(float(total_line), float(sigma))
            return prob_over_raw - (push_prob / 2)

        def _sanity_adjust(market: str, side: str, win_prob: float, ev: float, mc: Optional[Dict[str, Any]]):
            """Soft guardrails + market-movement uncertainty.

            Returns: (score:int, reasons:list[str], sigma_mult:float, ev_penalty:float)

            - sigma_mult inflates model uncertainty when movement/disagreement suggests fragility
            - ev_penalty degrades EV rather than hard-blocking (configurable)
            """
            from src.utils.ev import implied_prob_american

            score = 0
            reasons = []
            sigma_mult = 1.0
            ev_penalty = 0.0

            # Odds/prob mismatch + best-vs-consensus odds outlier check
            try:
                # Pull best and consensus prices for this candidate.
                if market == 'SPREAD' and side == 'home':
                    best_price = (snap.get('_best_spread_home') or {}).get('price')
                    cons_price = snap.get('spread_price_home')
                elif market == 'SPREAD' and side == 'away':
                    best_price = (snap.get('_best_spread_away') or {}).get('price')
                    cons_price = None  # we don't currently store consensus away price
                elif market == 'TOTAL' and side == 'over':
                    best_price = (snap.get('_best_total_over') or {}).get('price')
                    cons_price = snap.get('total_over_price')
                elif market == 'TOTAL' and side == 'under':
                    best_price = (snap.get('_best_total_under') or {}).get('price')
                    cons_price = None
                else:
                    best_price = None
                    cons_price = None

                ip = implied_prob_american(best_price)
                if ip is not None:
                    dp = float(win_prob) - float(ip)
                    if abs(dp) >= float(os.getenv('SANITY_MAX_PROB_GAP', '0.18')):
                        score += 2
                        reasons.append(f"prob_gap={dp:+.2f}")
                        sigma_mult *= 1.35

                # If best price is a wild outlier vs consensus, it's often bad ingest.
                if cons_price is not None and best_price is not None:
                    ip_best = implied_prob_american(best_price)
                    ip_cons = implied_prob_american(cons_price)
                    if ip_best is not None and ip_cons is not None:
                        gap = abs(float(ip_best) - float(ip_cons))
                        if gap >= float(os.getenv('SANITY_BEST_VS_CONS_IMP_GAP', '0.10')):
                            score += 2
                            reasons.append(f"odds_outlier_gap={gap:.2f}")
                            sigma_mult *= 1.25
            except Exception:
                pass

            # Market movement against
            try:
                if mc:
                    m = str(market).upper()
                    s = str(side).lower().strip()
                    if m == 'SPREAD':
                        mv = mc.get('spread_move_home')
                        if mv is not None:
                            mv = float(mv)
                            against = (mv > 0) if s == 'away' else (mv < 0)
                            if against and abs(mv) >= float(os.getenv('SANITY_STEAM_WARN', '1.5')):
                                score += 1
                                reasons.append(f"steam_against={mv:+.1f}")
                                sigma_mult *= 1.20
                                ev_penalty += float(os.getenv('STEAM_EV_PENALTY_WARN', '0.01'))
                            if against and abs(mv) >= float(os.getenv('SANITY_STEAM_BLOCK', '2.5')):
                                score += 2
                                reasons.append(f"steam_block={mv:+.1f}")
                                sigma_mult *= 1.35
                                ev_penalty += float(os.getenv('STEAM_EV_PENALTY_BLOCK', '0.03'))
                    if m == 'TOTAL':
                        mv = mc.get('total_move')
                        if mv is not None:
                            mv = float(mv)
                            against = (mv > 0) if s == 'over' else (mv < 0)
                            if against and abs(mv) >= float(os.getenv('SANITY_STEAM_WARN_TOTAL', '2.0')):
                                score += 1
                                reasons.append(f"steam_against={mv:+.1f}")
                                sigma_mult *= 1.15
                                ev_penalty += float(os.getenv('STEAM_EV_PENALTY_WARN_TOTAL', '0.01'))
                            if against and abs(mv) >= float(os.getenv('SANITY_STEAM_BLOCK_TOTAL', '3.0')):
                                score += 2
                                reasons.append(f"steam_block={mv:+.1f}")
                                sigma_mult *= 1.30
                                ev_penalty += float(os.getenv('STEAM_EV_PENALTY_BLOCK_TOTAL', '0.03'))
            except Exception:
                pass

            # Disagreement across books
            try:
                if mc:
                    dis = mc.get('spread_disagreement') if str(market).upper() == 'SPREAD' else mc.get('total_disagreement')
                    if dis is not None and abs(float(dis)) >= float(os.getenv('SANITY_DISAGREE_WARN', '1.0')):
                        score += 1
                        reasons.append(f"disagree={float(dis):.1f}")
                        sigma_mult *= 1.10
                        ev_penalty += float(os.getenv('DISAGREE_EV_PENALTY', '0.005'))
            except Exception:
                pass

            # Extreme EV itself is a signal, but we don't cap; we demand better data.
            # If EV is *very* extreme, treat it as highly suspicious unless corroborated.
            try:
                ev_abs = abs(float(ev))
                ev_warn = float(os.getenv('SANITY_EV_EXTREME', '0.20'))
                ev_very = float(os.getenv('SANITY_EV_VERY_EXTREME', '0.35'))
                if ev_abs >= ev_warn:
                    score += 1
                    if ev_abs >= ev_very:
                        score += 1
                    reasons.append(f"ev_extreme={float(ev):+.2f}")
                    sigma_mult *= 1.15
                    ev_penalty += float(os.getenv('EXTREME_EV_PENALTY', '0.005'))
            except Exception:
                pass

            return score, reasons, sigma_mult, ev_penalty


        # --- Spread ---
        line_s = snap.get("spread_home")
        price_home = snap.get("spread_price_home", -110)
        best_away = snap.get("_best_spread_away", {})
        price_away = best_away.get("price", -110) if best_away else -110
        book_consensus = snap.get("book_spread", "Consensus")

        if line_s is not None:
            prob_home = _spread_cover_prob_home(mu_s, sig_s, line_s)
            prob_home_cal = self._calibrate_win_prob(prob_home)

            ev_home = self._calculate_ev(prob_home_cal, price_home)
            kelly_home = self._calculate_kelly(prob_home_cal, price_home)

            # No hard EV caps; extreme EVs are handled by sanity scoring (below).
            # Away cover prob = 1 - P(home covers) - push (approx already baked into helper via -push/2)
            # For symmetry we compute raw home cover without calibration then derive away.
            prob_home_raw = 1.0 - self._normal_cdf(-float(line_s), -float(mu_s), float(sig_s))
            push_prob = get_push_prob(float(line_s), float(sig_s))
            prob_away = (1.0 - prob_home_raw) - (push_prob / 2)
            prob_away_cal = self._calibrate_win_prob(prob_away)

            ev_away = self._calculate_ev(prob_away_cal, price_away)
            kelly_away = self._calculate_kelly(prob_away_cal, price_away)
            # (removed hard EV cap; handled by sanity scoring)

            # Use consensus for model math, but use a bettable line for the displayed recommendation.
            # Some consensus aggregations can produce quarter-points (e.g. -10.25) which are not real lines.
            market_line_s = float(line_s)
            fair_line_s = float(mu_s)
            edge_pts = abs(fair_line_s - market_line_s)

            def _snap_half(x: float) -> float:
                try:
                    return round(float(x) * 2.0) / 2.0
                except Exception:
                    return float(x)

            # Candidate recs first
            # Prefer best available line+price for the bet display (avoid quarter-point consensus lines).
            best_home = snap.get('_best_spread_home') or {}
            best_away_line = (best_away or {}).get('line_value')
            best_home_line = best_home.get('line_value')

            bounds_home = self._confidence_bounds_from_mu_uncertainty(
                market='SPREAD',
                mu=float(mu_s),
                sigma=float(sig_s),
                line=float(line_s),
                side='home',
            )

            cand_home = {
                "market": "SPREAD",
                "side": "home",
                "team": event["home_team"],
                "line": _snap_half(best_home_line if best_home_line is not None else market_line_s),
                "price": int(best_home.get('price')) if best_home.get('price') is not None else int(price_home),
                "prob": round(prob_home_cal, 3),
                "win_prob": round(prob_home_cal, 3),
                "win_prob_lb10": (round(float(bounds_home.get('lb10')), 3) if bounds_home.get('lb10') is not None else None),
                "win_prob_ub90": (round(float(bounds_home.get('ub90')), 3) if bounds_home.get('ub90') is not None else None),
                "ev": float(round(ev_home, 4)),
                "kelly": float(round(kelly_home, 4)),
                "book": best_home.get('book') or book_consensus,
                "edge_points": float(round(edge_pts, 2)),
            }

            bounds_away = self._confidence_bounds_from_mu_uncertainty(
                market='SPREAD',
                mu=float(mu_s),
                sigma=float(sig_s),
                line=float(line_s),
                side='away',
            )

            cand_away = {
                "market": "SPREAD",
                "side": "away",
                "team": event["away_team"],
                "line": _snap_half((best_away_line if best_away_line is not None else -market_line_s)),
                "price": int(price_away),
                "prob": round(prob_away_cal, 3),
                "win_prob": round(prob_away_cal, 3),
                "win_prob_lb10": (round(float(bounds_away.get('lb10')), 3) if bounds_away.get('lb10') is not None else None),
                "win_prob_ub90": (round(float(bounds_away.get('ub90')), 3) if bounds_away.get('ub90') is not None else None),
                "ev": float(round(ev_away, 4)),
                "kelly": float(round(kelly_away, 4)),
                "book": (best_away or {}).get('book') or book_consensus,
                "edge_points": float(round(edge_pts, 2)),
            }

            # Choose the higher-EV side, then gate it.
            best = cand_home if cand_home["ev"] >= cand_away["ev"] else cand_away
            if relax_gates or self._passes_publish_gates(best, market_line_home=market_line_s, torvik_ok=torvik_ok):
                # 1) Steam / movement handling
                reason = self._steam_block_reason('SPREAD', str(best.get('side') or ''), snap.get('_market_consensus') if isinstance(snap, dict) else None, snap)
                steam_hard_block = str(os.getenv('STEAM_HARD_BLOCK', '0')).strip() not in ('0', 'false', 'False', '')
                if reason and steam_hard_block:
                    if isinstance(snap, dict):
                        snap['_no_bet_reason_spread'] = reason
                else:
                    # 2) Sanity + movement-based uncertainty (soft by default)
                    sanity_on = str(os.getenv('SANITY_ENABLE', '1')).strip() not in ('0', 'false', 'False', '')
                    if sanity_on and isinstance(snap, dict):
                        mc = snap.get('_market_consensus')
                        score, reasons, sigma_mult, ev_penalty = _sanity_adjust('SPREAD', str(best.get('side') or ''), float(best.get('win_prob') or 0.5), float(best.get('ev') or 0.0), mc)
                        if reason:
                            try:
                                reasons = list(reasons or [])
                                reasons.insert(0, f"steam_reason={reason}")
                            except Exception:
                                pass
                            # small extra penalty when a steam_reason is present
                            try:
                                ev_penalty = float(ev_penalty or 0.0) + float(os.getenv('STEAM_REASON_EV_PENALTY', '0.01'))
                            except Exception:
                                pass

                        # Hard-block is optional; default keeps legacy behavior.
                        hard_block = str(os.getenv('SANITY_HARD_BLOCK', '1')).strip() not in ('0', 'false', 'False', '')
                        block_score = int(float(os.getenv('SANITY_BLOCK_SCORE', '2')))
                        if hard_block and score >= block_score:
                            snap['_no_bet_reason_spread'] = "Sanity block (suspect data): " + ", ".join(reasons or [f"score={score}"])
                        else:
                            # Soft-adjust: inflate uncertainty + degrade EV
                            ev_raw = float(best.get('ev') or 0.0)
                            ev_adj = ev_raw - float(ev_penalty or 0.0)
                            out = {**best,
                                   'steam_blocked': False,
                                   'sanity_score': score,
                                   'sanity_reasons': reasons,
                                   'sigma_mult': float(sigma_mult or 1.0),
                                   'ev_raw': float(round(ev_raw, 4)),
                                   'ev_penalty': float(round(ev_penalty or 0.0, 4)),
                                   'movement_tags': reasons}

                            # Recompute bounds with inflated sigma (movement/disagreement => more uncertainty)
                            try:
                                b2 = self._confidence_bounds_from_mu_uncertainty(
                                    market='SPREAD',
                                    mu=float(mu_s),
                                    sigma=float(sig_s) * float(out.get('sigma_mult') or 1.0),
                                    line=float(line_s),
                                    side=str(out.get('side') or ''),
                                )
                                if b2:
                                    out['win_prob_lb10'] = (round(float(b2.get('lb10')), 3) if b2.get('lb10') is not None else out.get('win_prob_lb10'))
                                    out['win_prob_ub90'] = (round(float(b2.get('ub90')), 3) if b2.get('ub90') is not None else out.get('win_prob_ub90'))
                            except Exception:
                                pass

                            out['ev'] = float(round(ev_adj, 4))
                            recs.append(out)
                    else:
                        recs.append({**best, 'steam_blocked': False})

        # --- Total ---
        line_t = snap.get("total")
        best_over = snap.get("_best_total_over")
        best_under = snap.get("_best_total_under")

        price_over = best_over["price"] if best_over else snap.get("total_over_price", -110)
        price_under = best_under["price"] if best_under else -110
        book_over = best_over["book"] if best_over else snap.get("book_total", "Consensus")
        book_under = best_under["book"] if best_under else snap.get("book_total", "Consensus")

        if line_t is not None:
            prob_over_raw = 1.0 - self._normal_cdf(line_t, mu_t, sig_t)
            push_prob_t = get_push_prob(line_t, sig_t)
            prob_over = prob_over_raw - (push_prob_t / 2)
            prob_under = (1.0 - prob_over_raw) - (push_prob_t / 2)

            prob_over_cal = self._calibrate_win_prob(prob_over)
            prob_under_cal = self._calibrate_win_prob(prob_under)

            ev_over = self._calculate_ev(prob_over_cal, price_over)
            kelly_over = self._calculate_kelly(prob_over_cal, price_over)
            ev_under = self._calculate_ev(prob_under_cal, price_under)
            kelly_under = self._calculate_kelly(prob_under_cal, price_under)

            # No hard EV caps; extreme EVs are handled by sanity scoring (below).
            market_line_t = float(line_t)
            fair_line_t = float(mu_t)
            edge_pts_t = abs(fair_line_t - market_line_t)

            bounds_over = self._confidence_bounds_from_mu_uncertainty(
                market='TOTAL',
                mu=float(mu_t),
                sigma=float(sig_t),
                line=float(line_t),
                side='over',
            )

            cand_over = {
                "market": "TOTAL",
                "side": "over",
                "line": float(best_over["line_value"] if best_over else line_t),
                "price": int(price_over),
                "prob": round(prob_over_cal, 3),
                "win_prob": round(prob_over_cal, 3),
                "win_prob_lb10": (round(float(bounds_over.get('lb10')), 3) if bounds_over.get('lb10') is not None else None),
                "win_prob_ub90": (round(float(bounds_over.get('ub90')), 3) if bounds_over.get('ub90') is not None else None),
                "ev": float(round(ev_over, 4)),
                "kelly": float(round(kelly_over, 4)),
                "book": book_over,
                "edge_points": float(round(edge_pts_t, 2)),
            }

            bounds_under = self._confidence_bounds_from_mu_uncertainty(
                market='TOTAL',
                mu=float(mu_t),
                sigma=float(sig_t),
                line=float(line_t),
                side='under',
            )

            cand_under = {
                "market": "TOTAL",
                "side": "under",
                "line": float(best_under["line_value"] if best_under else line_t),
                "price": int(price_under),
                "prob": round(prob_under_cal, 3),
                "win_prob": round(prob_under_cal, 3),
                "win_prob_lb10": (round(float(bounds_under.get('lb10')), 3) if bounds_under.get('lb10') is not None else None),
                "win_prob_ub90": (round(float(bounds_under.get('ub90')), 3) if bounds_under.get('ub90') is not None else None),
                "ev": float(round(ev_under, 4)),
                "kelly": float(round(kelly_under, 4)),
                "book": book_under,
                "edge_points": float(round(edge_pts_t, 2)),
            }

            best = cand_over if cand_over["ev"] >= cand_under["ev"] else cand_under
            if relax_gates or self._passes_publish_gates(best, market_line_home=None, torvik_ok=torvik_ok):
                reason = self._steam_block_reason('TOTAL', str(best.get('side') or ''), snap.get('_market_consensus') if isinstance(snap, dict) else None, snap)
                steam_hard_block = str(os.getenv('STEAM_HARD_BLOCK', '0')).strip() not in ('0', 'false', 'False', '')
                if reason and steam_hard_block:
                    if isinstance(snap, dict):
                        snap['_no_bet_reason_total'] = reason
                else:
                    sanity_on = str(os.getenv('SANITY_ENABLE', '1')).strip() not in ('0', 'false', 'False', '')
                    if sanity_on and isinstance(snap, dict):
                        mc = snap.get('_market_consensus')
                        score, reasons, sigma_mult, ev_penalty = _sanity_adjust('TOTAL', str(best.get('side') or ''), float(best.get('win_prob') or 0.5), float(best.get('ev') or 0.0), mc)
                        if reason:
                            try:
                                reasons = list(reasons or [])
                                reasons.insert(0, f"steam_reason={reason}")
                            except Exception:
                                pass
                            try:
                                ev_penalty = float(ev_penalty or 0.0) + float(os.getenv('STEAM_REASON_EV_PENALTY', '0.01'))
                            except Exception:
                                pass

                        hard_block = str(os.getenv('SANITY_HARD_BLOCK', '1')).strip() not in ('0', 'false', 'False', '')
                        block_score = int(float(os.getenv('SANITY_BLOCK_SCORE', '2')))
                        if hard_block and score >= block_score:
                            snap['_no_bet_reason_total'] = "Sanity block (suspect data): " + ", ".join(reasons or [f"score={score}"])
                        else:
                            ev_raw = float(best.get('ev') or 0.0)
                            ev_adj = ev_raw - float(ev_penalty or 0.0)
                            out = {**best,
                                   'steam_blocked': False,
                                   'sanity_score': score,
                                   'sanity_reasons': reasons,
                                   'sigma_mult': float(sigma_mult or 1.0),
                                   'ev_raw': float(round(ev_raw, 4)),
                                   'ev_penalty': float(round(ev_penalty or 0.0, 4)),
                                   'movement_tags': reasons}

                            try:
                                b2 = self._confidence_bounds_from_mu_uncertainty(
                                    market='TOTAL',
                                    mu=float(mu_t),
                                    sigma=float(sig_t) * float(out.get('sigma_mult') or 1.0),
                                    line=float(line_t),
                                    side=str(out.get('side') or ''),
                                )
                                if b2:
                                    out['win_prob_lb10'] = (round(float(b2.get('lb10')), 3) if b2.get('lb10') is not None else out.get('win_prob_lb10'))
                                    out['win_prob_ub90'] = (round(float(b2.get('ub90')), 3) if b2.get('ub90') is not None else out.get('win_prob_ub90'))
                            except Exception:
                                pass

                            out['ev'] = float(round(ev_adj, 4))
                            recs.append(out)
                    else:
                        recs.append({**best, 'steam_blocked': False})

        return recs

    def _normal_cdf(self, x, mu, sigma):
        return 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))

    def _sanitize_price(self, price: Any) -> int:
        # Back-compat wrapper.
        from src.utils.ev import sanitize_american_odds
        return int(sanitize_american_odds(price, default=-110) or -110)

    def _clamp_prob(self, win_prob: Any) -> float:
        # Back-compat wrapper.
        from src.utils.ev import clamp_prob
        return float(clamp_prob(win_prob, default=0.5))

    def _calculate_ev(self, win_prob, price):
        """Estimated Value (ROI) per 1u risked."""
        from src.utils.ev import ev_per_unit
        ev = ev_per_unit(win_prob, price)
        # Guardrail: if odds invalid, treat as no edge.
        return float(ev) if ev is not None else 0.0

    def _calculate_kelly(self, win_prob, price):
        """Quarter Kelly stake fraction."""
        from src.utils.ev import kelly_fraction
        k = kelly_fraction(win_prob, price, kelly_mult=0.25)
        return float(k) if k is not None else 0.0

    def _generate_narrative(self, event, snap, torvik, kenpom, news, recs, raw_snaps: Optional[List[Dict]] = None, debug_info: Optional[Dict] = None) -> Dict:
        """Generate matchup-specific narrative + factors.

        IMPORTANT: key_factors/risks must be specific to this matchup, not generic labels.
        """
        headline = "No Edge Detected"
        rationale: List[str] = []
        key_factors: List[str] = []
        risks: List[str] = []

        spread_mkt = snap.get('spread_home', None)
        total_mkt = snap.get('total', None)
        
        debug_info = debug_info or {}

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

        # === SIGNAL-BASED FACTORS (from debug_info) ===
        
        # Luck Regression
        luck_adj = debug_info.get('luck_adj', 0.0)
        if luck_adj and abs(luck_adj) >= 0.5:
            direction = "inflated" if luck_adj > 0 else "deflated"
            key_factors.append(f"Luck regression: Team performance {direction} by recent good fortune ({luck_adj:+.1f} pts adj)")
        
        # Fatigue / Short Rest
        fatigue_adj = debug_info.get('fatigue_adj', 0.0)
        if fatigue_adj and abs(fatigue_adj) >= 1.0:
            if fatigue_adj < 0:
                key_factors.append(f"Fatigue signal: Home team on short rest ({fatigue_adj:+.1f} pts)")
            else:
                key_factors.append(f"Fatigue signal: Away team on short rest ({fatigue_adj:+.1f} pts to home)")
        
        # Shooting Regression (3PT variance)
        shooting_adj = debug_info.get('shooting_adj', 0.0)
        if shooting_adj and abs(shooting_adj) >= 0.5:
            if shooting_adj < 0:
                key_factors.append(f"Shooting regression: Team shooting hot from 3, expect regression ({shooting_adj:+.1f} pts)")
            else:
                key_factors.append(f"Shooting bounce-back: Team shooting cold from 3, expect improvement ({shooting_adj:+.1f} pts)")
        
        # Situational Spots (Letdown/Lookahead)
        spot_adj = debug_info.get('spot_adj', 0.0)
        if spot_adj and abs(spot_adj) >= 0.5:
            if spot_adj > 0:
                key_factors.append(f"Situational spot: Away team in letdown spot after big win ({spot_adj:+.1f} pts to home)")
            else:
                key_factors.append(f"Situational spot: Home team in letdown spot ({spot_adj:+.1f} pts)")
        
        # Dynamic Weights (Season Progression)
        w_base = debug_info.get('w_base', 0.25)
        if w_base != 0.25:
            trust_level = "high" if w_base >= 0.32 else "low"
            key_factors.append(f"Model trust: {trust_level} projection confidence ({w_base:.0%} weight)")

        # News
        if news:
            if news.get('has_injury_news'):
                key_factors.append(f"Injury/news: {news.get('summary')}")
            else:
                # Still matchup-specific: we looked and found none
                risks.append("No meaningful injury/rotation news detected (risk: late scratches)")

        # === Agent Council Adjustments (Phase 4) ===
        council_adj_spread = debug_info.get('council_adj_spread', 0.0)
        council_adj_total = debug_info.get('council_adj_total', 0.0)
        if council_adj_spread != 0.0:
            side_label = "Home" if council_adj_spread < 0 else "Away"
            key_factors.append(f"Agent Council: Added {abs(council_adj_spread):.1f} pts to {side_label} based on qualitative synthesis.")
        if council_adj_total != 0.0:
            side_label = "Over" if council_adj_total > 0 else "Under"
            key_factors.append(f"Agent Council: Adjusted total by {council_adj_total:+.1f} pts ({side_label} lean).")

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

    def _get_market_consensus(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Fetch derived open/current movement metrics for an event (fast path)."""
        try:
            with get_db_connection() as conn:
                row = _exec(conn, "SELECT * FROM market_consensus WHERE event_id=%s", (event_id,)).fetchone()
                if not row:
                    return None
                return dict(row)
        except Exception:
            return None

    def _steam_block_reason(self, market: str, side: str, mc: Optional[Dict[str, Any]], snap: Dict[str, Any]) -> Optional[str]:
        """Return a reason string if market movement suggests steam / line got worse."""
        if not mc:
            return None

        try:
            max_move_spread = float(os.getenv('STEAM_MAX_MOVE_SPREAD', '1.0'))
        except Exception:
            max_move_spread = 1.0
        try:
            max_move_total = float(os.getenv('STEAM_MAX_MOVE_TOTAL', '2.0'))
        except Exception:
            max_move_total = 2.0

        m = str(market or '').upper()
        s = str(side or '').lower().strip()

        if m == 'SPREAD':
            open_home = _safe_float(mc.get('open_spread_home'))
            cur_home = _safe_float(mc.get('current_spread_home'))
            if open_home is None or cur_home is None:
                return None

            # Convert to the side we're betting.
            # Home side line = home spread; Away side line = -home spread.
            open_line = open_home if s == 'home' else -open_home
            cur_line = cur_home if s == 'home' else -cur_home

            # Worse means: line moved against us (more negative for favorite, smaller for dog).
            # For bettor, higher is better (more points). So worse if (cur_line - open_line) < -threshold.
            delta = (cur_line - open_line)
            if delta < -abs(max_move_spread):
                return f"Steam move {delta:+.1f}pts (open {open_line:+.1f} → cur {cur_line:+.1f})"

        if m == 'TOTAL':
            open_total = _safe_float(mc.get('open_total'))
            cur_total = _safe_float(mc.get('current_total'))
            if open_total is None or cur_total is None:
                return None

            # For totals, direction depends on side.
            # Over: higher total is worse. Under: lower total is worse.
            delta = (cur_total - open_total)
            if s == 'over' and delta > abs(max_move_total):
                return f"Steam move +{delta:.1f} (open {open_total:.1f} → cur {cur_total:.1f})"
            if s == 'under' and delta < -abs(max_move_total):
                return f"Steam move {delta:.1f} (open {open_total:.1f} → cur {cur_total:.1f})"

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

    def _get_council_verdict(self, event_id: str) -> Optional[Dict]:
        """
        Fetches the latest Agent Council debate and Oracle prediction for a specific game
        from the decision_runs table to use as a qualitative modifier.
        """
        try:
            with get_db_connection() as conn:
                query = """
                SELECT council_narrative->%(eid)s AS narrative
                FROM decision_runs
                WHERE council_narrative->>%(eid)s IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
                """
                row = _exec(conn, query, {"eid": event_id}).fetchone()
                if row and row[0]:
                    narrative = row[0]
                    import json
                    if isinstance(narrative, str):
                        narrative = json.loads(narrative)
                    return narrative
        except Exception as e:
            import traceback
            print(f"[MODEL] Failed to fetch council verdict for {event_id}:\n{traceback.format_exc()}")
        return None
