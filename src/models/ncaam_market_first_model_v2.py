
import math
import json
import os
from datetime import datetime, timezone
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
from src.utils.model_calibration import (
    interpolate_pava_prob,
    load_winprob_calibration,
    resolve_model_param_path,
)
from src.utils.naming import standardize_team_name
from src.utils.ev import compute_recommended_bet_size

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
    
    VERSION = "2.4.1-calibrated"
    
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

    @staticmethod
    def _anchor_with_sharp(retail_val, sharp_val, max_diff: float = 3.0) -> Optional[float]:
        """Blend retail consensus 50/50 with sharp benchmark when difference is within sanity bounds."""
        r = _safe_float(retail_val)
        if r is None:
            return None
        s = _safe_float(sharp_val)
        if s is not None and abs(s - r) <= float(max_diff):
            return round((0.50 * s) + (0.50 * r), 2)
        return float(r)

    @staticmethod
    def _sharp_line_for_side(
        market: str,
        side: str,
        sharp_spread_home=None,
        sharp_total=None,
    ) -> Optional[float]:
        mkt = str(market or "").upper()
        s_low = str(side or "").strip().lower()
        if mkt == "SPREAD":
            sh = _safe_float(sharp_spread_home)
            if sh is None:
                return None
            val = sh if s_low == "home" else -sh
            return round(val, 1)
        if mkt == "TOTAL":
            st = _safe_float(sharp_total)
            return round(st, 1) if st is not None else None
        return None

    @staticmethod
    def _compute_sharp_edge_pts(
        market: str,
        side: str,
        bet_line,
        sharp_spread_home=None,
        sharp_total=None,
    ) -> Optional[float]:
        """Points the bettable retail line beats (+) or trails (-) the sharp benchmark line."""
        bl = _safe_float(bet_line)
        if bl is None:
            return None
        mkt = str(market or "").upper()
        s_low = str(side or "").strip().lower()
        if mkt == "SPREAD":
            sh = _safe_float(sharp_spread_home)
            if sh is None:
                return None
            sharp_side = sh if s_low == "home" else -sh
            return round(bl - sharp_side, 2)
        if mkt == "TOTAL":
            st = _safe_float(sharp_total)
            if st is None:
                return None
            diff = (st - bl) if s_low == "over" else (bl - st)
            return round(diff, 2)
        return None

    def __init__(self, aggressive: bool = False, cap_spread: float = None, cap_total: float = None, manual_adjustments: dict = None):
        """Initialize model with configurable parameters.

        Staging/tuning: core knobs can be overridden via env vars.
        """
        super().__init__(sport_key="ncaam")  # BaseModel init
        self.torvik_service = TorvikProjectionService()
        self.odds_selector = OddsSelectionService()
        self.kenpom_client = KenPomClient()
        self.haslametrics_client = None
        try:
            from src.services.haslametrics_client import HaslametricsClient
            self.haslametrics_client = HaslametricsClient()
        except Exception:
            self.haslametrics_client = None
        self.injury_service = None
        try:
            from src.services.injury_service import InjuryService
            self.injury_service = InjuryService()
        except Exception:
            self.injury_service = None
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

    def _parse_game_datetime(self, game_date):
        from datetime import datetime
        if game_date is None:
            return datetime.now()
        if isinstance(game_date, str):
            try:
                return datetime.fromisoformat(game_date.replace('Z', '+00:00'))
            except Exception:
                return datetime.now()
        return game_date

    def _get_dynamic_weights(self, game_date) -> float:
        """
        Returns a weight (W_BASE) that scales based on the time of year.
        Early season: Trust Market heavily (projections are preseason-based).
        Late season: Trust Projections more (based on actual games).
        """
        dt = self._parse_game_datetime(game_date)
        month = getattr(dt, 'month', 1)
        
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

    def _get_dynamic_kenpom_weight(self, game_date, avg_continuity: float = 0.7) -> float:
        """
        Scale W_KENPOM dynamically by month and roster continuity so early-season
        preseason priors do not overpower the market in November/December.
        """
        if os.getenv('NCAAM_W_KENPOM') is not None:
            try:
                return float(os.getenv('NCAAM_W_KENPOM'))
            except Exception:
                pass

        dt = self._parse_game_datetime(game_date)
        month = getattr(dt, 'month', 1)
        base_kp = float(self.W_KENPOM)

        if month == 11:
            w_kp = base_kp * 0.50  # 0.10 when W_KENPOM=0.20
        elif month == 12:
            w_kp = base_kp * 0.75  # 0.15 when W_KENPOM=0.20
        else:
            w_kp = base_kp

        if avg_continuity < 0.5:
            w_kp = min(w_kp, 0.08)

        return w_kp

    def _calculate_shooting_regression(self, team_name: str, as_of_date=None) -> float:
        """
        3-Point Variance Signal: Fade teams shooting hot from 3.
        Requires at least 4 current-season games before activating so week-1 noise
        or prior-season games never distort early-November spreads.
        """
        from src.database import get_team_recent_shooting
        
        try:
            stats = get_team_recent_shooting(team_name, num_games=3, as_of_date=as_of_date)
            games_played = int(stats.get('games_played') or 0)
            if games_played < 4:
                return 0.0

            delta = stats.get('delta', 0.0)
            if delta is None:
                return 0.0
                
            # Smooth continuous shooting-regression ramp past a +/-2% deadzone
            # so there is no step cliff at +/-4% (bounded to [-2.0, +1.0] pts).
            excess = abs(float(delta)) - 0.02
            if excess <= 0.0:
                return 0.0
            if delta > 0.0:
                return -min(round(excess * 35.0, 3), 2.0)
            return min(round(excess * 18.0, 3), 1.0)
                
        except Exception as e:
            print(f"[MODEL] Shooting regression error for {team_name}: {e}")
            
        return 0.0

    @staticmethod
    def _event_team_matches(candidate_name: Optional[str], target_team: str) -> bool:
        """Return True only when candidate_name matches target_team without school-name collisions."""
        if not candidate_name or not target_team:
            return False
        from src.utils.team_matcher import TeamMatcher

        matcher = TeamMatcher()
        cand_norm = matcher.normalize(str(candidate_name))
        target_norm = matcher.normalize(str(target_team))
        if not cand_norm or not target_norm:
            return False
        if cand_norm == target_norm:
            return True

        disambig = matcher._DISAMBIGUATING_NEXT_WORDS
        c_tokens = cand_norm.split()
        t_tokens = target_norm.split()
        if len(c_tokens) > len(t_tokens) and c_tokens[:len(t_tokens)] == t_tokens:
            return c_tokens[len(t_tokens)] not in disambig
        if len(t_tokens) > len(c_tokens) and t_tokens[:len(c_tokens)] == c_tokens:
            return t_tokens[len(c_tokens)] not in disambig
        return False

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
            # 1. LETDOWN SPOT: Check if last game in current season was an upset win
            last_game = get_team_last_game(team_name, as_of_date=current_date)
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
            
            # 2. LOOKAHEAD SPOT: Apply bounded penalty if next game within 4 days is vs a Top-25 opponent
            if os.getenv('REQUIRE_DATABASE') != '0':
                with get_db_connection() as conn:
                    query = """
                    SELECT e.home_team, e.away_team, e.start_time
                    FROM events e
                    WHERE (LOWER(e.home_team) LIKE LOWER(:t) OR LOWER(e.away_team) LIKE LOWER(:t))
                      AND e.start_time > :now
                    ORDER BY e.start_time ASC
                    LIMIT 15
                    """
                    cur = _exec(conn, query, {"t": f"%{team_name}%", "now": current_date})
                    if hasattr(cur, 'fetchall'):
                        cand_rows = cur.fetchall() or []
                    elif hasattr(cur, 'fetchone'):
                        one = cur.fetchone()
                        cand_rows = [one] if one else []
                    else:
                        cand_rows = []
                    next_row = None
                    for cr in cand_rows:
                        cd = dict(cr) if not isinstance(cr, dict) else cr
                        if self._event_team_matches(cd.get('home_team'), team_name) or self._event_team_matches(cd.get('away_team'), team_name):
                            next_row = cd
                            break
                    if next_row and getattr(self, 'kenpom_client', None):
                        next_dict = dict(next_row) if not isinstance(next_row, dict) else next_row
                        now_dt = self._parse_game_datetime(current_date)
                        next_dt = self._parse_game_datetime(next_dict.get('start_time'))
                        if now_dt and next_dt:
                            if getattr(now_dt, 'tzinfo', None) is not None and getattr(next_dt, 'tzinfo', None) is None:
                                now_dt = now_dt.replace(tzinfo=None)
                            elif getattr(next_dt, 'tzinfo', None) is not None and getattr(now_dt, 'tzinfo', None) is None:
                                next_dt = next_dt.replace(tzinfo=None)
                        if now_dt and next_dt and 0.0 <= (next_dt - now_dt).total_seconds() <= 4 * 86400:
                            nh = str(next_dict.get('home_team') or '')
                            na = str(next_dict.get('away_team') or '')
                            next_opp = na if self._event_team_matches(nh, team_name) else nh
                            if next_opp:
                                opp_kp = self.kenpom_client.get_team_rating(next_opp) or {}
                                opp_rank = opp_kp.get('rank')
                                if opp_rank is not None and int(opp_rank) <= 25:
                                    adj -= 0.75
                
        except Exception as e:
            print(f"[MODEL] Situational spot error for {team_name}: {e}")
            
        return adj

    def _apply_referee_signal(self, event_id: str, mu_total: float, avg_ftr: Optional[float] = None) -> float:
        """Referee Signal: Adjust total based on officiating crew tendencies + 3-way FT/foul synergy.

        Priority:
        1) referee_assignments.crew_avg_fouls (if present)
        2) KenPom ref ratings (best-effort, header-driven) when crew names are assigned.
        If no officiating crew is assigned for the game, returns mu_total unchanged.
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

            # Fall back to KenPom ref table only if we have assigned referee names.
            if crew_fouls is None:
                names = [ref_data.get('referee_1'), ref_data.get('referee_2'), ref_data.get('referee_3')]
                names = [n for n in names if n]
                if names:
                    crew_fouls = self.kenpom_client.estimate_crew_avg_fouls(names)

            if crew_fouls is not None:
                # Every 1 foul above average adds ~0.8 points to total
                if crew_fouls > NCAA_AVG_FOULS:
                    over_adj = (crew_fouls - NCAA_AVG_FOULS) * 0.8
                    # 3-way synergy: whistle-heavy crew + high-FTR/foul-prone matchup
                    ft_synergy = 0.0
                    if avg_ftr is not None and float(avg_ftr) > 35.0 and crew_fouls >= 37.5:
                        ft_synergy = min(1.2, ((float(avg_ftr) - 35.0) * 0.12) + ((crew_fouls - 37.0) * 0.25))
                    total_boost = min(over_adj + ft_synergy, 4.5)
                    mu_total += total_boost
                    print(f"[REF] Crew avg {crew_fouls:.1f} fouls (FTR={avg_ftr}) → Total +{total_boost:.1f}")
                elif crew_fouls < NCAA_AVG_FOULS - 2:
                    under_adj = (NCAA_AVG_FOULS - crew_fouls) * 0.5
                    mu_total -= min(under_adj, 2.0)  # Cap at -2 points
                    print(f"[REF] Tight crew {crew_fouls:.1f} fouls → Total -{under_adj:.1f}")

        except Exception as e:
            print(f"[MODEL] Referee signal error: {e}")

        return mu_total

    def _calculate_fatigue_penalty(self, team_name: str, event_id: str, current_game_date) -> float:
        """
        Checks the schedule for 'Short Rest' spots within the current season.
        -2.5 pts for '3rd game in 6 days' (The 'Tired Legs' Spot)
        -1.5 pts for 'Back-to-back'
        """
        from src.database import get_db_connection, _exec
        from src.utils.ncaam_season import season_start_date_for_game
        from datetime import datetime, timedelta
        
        if current_game_date is None:
            return 0.0
        if isinstance(current_game_date, str):
            try:
                current_game_date = datetime.fromisoformat(current_game_date.replace('Z', '+00:00'))
            except:
                return 0.0
        
        try:
            season_start = season_start_date_for_game(current_game_date)
            # Query recent games in the active season, excluding the current one
            query = """
            SELECT id, home_team, away_team, start_time FROM events 
            WHERE (LOWER(home_team) LIKE LOWER(:t) OR LOWER(away_team) LIKE LOWER(:t))
            AND start_time >= :season_start
            AND start_time < :now
            AND id != :eid  -- Critical fix: Exclude current game to prevent self-matching
            ORDER BY start_time DESC LIMIT 20
            """
            
            # Use named parameters
            params = {
                "t": f"%{team_name}%",
                "season_start": season_start,
                "now": current_game_date,
                "eid": event_id
            }
            
            with get_db_connection() as conn:
                raw_rows = _exec(conn, query, params).fetchall() or []

            rows = []
            for r in raw_rows:
                rd = dict(r) if not isinstance(r, dict) else r
                rh = rd.get('home_team')
                ra = rd.get('away_team')
                if rh is None and ra is None:
                    rows.append(rd)
                elif self._event_team_matches(rh, team_name) or self._event_team_matches(ra, team_name):
                    rows.append(rd)
                if len(rows) >= 2:
                    break
                
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
                print(f"[FATIGUE] {team_name}: Back-to-back (-0.75)")
                return -0.75  # Back-to-back
            
            if len(rows) > 1:
                two_games_ago = rows[1]['start_time']
                if isinstance(two_games_ago, str):
                    two_games_ago = datetime.fromisoformat(two_games_ago)
                if (current_game_date - two_games_ago).days <= 6:
                    print(f"[FATIGUE] {team_name}: 3rd game in 6 days (-1.0)")
                    return -1.0  # 3rd game in 6 days
                    
        except Exception as e:
            print(f"[MODEL] Fatigue calc error for {team_name}: {e}")
            
        return 0.0

    def _generate_bell_curve(self, mu: Optional[float], sigma: Optional[float], line: Optional[float]) -> Dict:
        """
        Generates 50 points representing the Normal Distribution curve.
        Used by Frontend (Chart.js) to render the 'Cover Zone'.
        """
        import math

        if mu is None or line is None or sigma is None or float(sigma) <= 0.0:
            return {
                "points": [],
                "mu": round(float(mu), 2) if mu is not None else None,
                "sigma": round(float(sigma), 2) if sigma is not None else None,
                "line": round(float(line), 2) if line is not None else None,
                "cover_prob": None,
                "is_under_line": False,
            }

        mu_f = float(mu)
        sigma_f = float(sigma)
        line_f = float(line)

        points = []
        # Generate points from -3 sigma to +3 sigma
        start = mu_f - (3 * sigma_f)
        end = mu_f + (3 * sigma_f)
        step = (end - start) / 50

        for i in range(51):
            x = start + (i * step)
            # Standard Normal PDF Formula
            y = (1 / (sigma_f * math.sqrt(2 * math.pi))) * math.exp(-0.5 * ((x - mu_f) / sigma_f)**2)
            points.append({"x": round(x, 2), "y": round(y, 6)})

        # Calculate probability of covering (CDF at line)
        z = (line_f - mu_f) / sigma_f
        cover_prob = 0.5 * (1 + math.erf(z / math.sqrt(2)))

        return {
            "points": points,
            "mu": round(mu_f, 2),
            "sigma": round(sigma_f, 2),
            "line": round(line_f, 2),
            "cover_prob": round(cover_prob, 4),
            "is_under_line": mu_f < line_f  # Tells UI which side is favorable
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
                 
        try:
            torvik_view = self.torvik_service.get_projection(team_a_canon, team_b_canon, date=game_date_str, conn=conn, neutral_site=True)
        except TypeError:
            torvik_view = self.torvik_service.get_projection(team_a_canon, team_b_canon, date=game_date_str, conn=conn)
        try:
            try:
                kenpom_adj = self.kenpom_client.calculate_kenpom_adjustment(team_a_canon, team_b_canon, conn=conn, neutral_site=True)
            except TypeError:
                kenpom_adj = self.kenpom_client.calculate_kenpom_adjustment(team_a_canon, team_b_canon, conn=conn)
        except Exception:
            kenpom_adj = None

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
            kp_players_a = self.kenpom_client.get_player_stats_for_team(team_a_canon, limit=12, conn=conn) or []
        except Exception:
            kp_players_a = []
        try:
            kp_players_b = self.kenpom_client.get_player_stats_for_team(team_b_canon, limit=12, conn=conn) or []
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
        try:
            mods_a = tf.get_tournament_modifiers(team_a_canon, conn=conn)
        except Exception:
            mods_a = {}
        try:
            mods_b = tf.get_tournament_modifiers(team_b_canon, conn=conn)
        except Exception:
            mods_b = {}
        
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

            # KenPom adjustment (if available)
            if kenpom_adj and kenpom_adj.get('spread_adj') is not None:
                kp_val = kenpom_adj.get('neutral_margin') if kenpom_adj.get('neutral_margin') is not None else kenpom_adj['spread_adj']
                mu_kp_spread = -float(kp_val)
                mu_base_spread = (0.75 * mu_base_spread) + (0.25 * mu_kp_spread)

            # Sanity blend: if Torvik spread is wildly inconsistent with KenPom team strength, pull back.
            # This prevents absurd outcomes like 1-seeds becoming huge underdogs due to a bad mapping/projection.
            try:
                if isinstance(kp_a, dict) and isinstance(kp_b, dict):
                    em_a = float(kp_a.get('adj_o') or 0) - float(kp_a.get('adj_d') or 0)
                    em_b = float(kp_b.get('adj_o') or 0) - float(kp_b.get('adj_d') or 0)
                    kp_margin_a = em_a - em_b  # positive => A better
                    mu_kp_from_em = -kp_margin_a  # negative => A favored
                    if abs(mu_base_spread - mu_kp_from_em) >= 12.0:
                        # heavy blend toward the more stable KP-derived line
                        mu_base_spread = (0.40 * mu_base_spread) + (0.60 * mu_kp_from_em)
                        risk_flags.append("Projection sanity blend applied (Torvik vs KenPom disagreement).")
            except Exception:
                pass
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
            
            # Step A: Get retail CONSENSUS lines (median of retail books) + separate SHARP benchmark
            consensus_spread = self.odds_selector.get_consensus_snapshot(raw_snaps, 'SPREAD', 'HOME')
            consensus_spread_away = self.odds_selector.get_consensus_snapshot(raw_snaps, 'SPREAD', 'AWAY')
            consensus_total = self.odds_selector.get_consensus_snapshot(raw_snaps, 'TOTAL', 'OVER')
            consensus_ml_home = self.odds_selector.get_consensus_snapshot(raw_snaps, 'MONEYLINE', 'HOME')
            consensus_ml_away = self.odds_selector.get_consensus_snapshot(raw_snaps, 'MONEYLINE', 'AWAY')

            sharp_spread_home_snap = self.odds_selector.get_sharp_benchmark_snapshot(raw_snaps, 'SPREAD', 'HOME')
            sharp_spread_away_snap = self.odds_selector.get_sharp_benchmark_snapshot(raw_snaps, 'SPREAD', 'AWAY')
            sharp_total_over_snap = self.odds_selector.get_sharp_benchmark_snapshot(raw_snaps, 'TOTAL', 'OVER')
            sharp_total_under_snap = self.odds_selector.get_sharp_benchmark_snapshot(raw_snaps, 'TOTAL', 'UNDER')

            sharp_spread_home_val = None
            sharp_spread_book = None
            if sharp_spread_home_snap and sharp_spread_home_snap.get('line_value') is not None:
                sharp_spread_home_val = float(sharp_spread_home_snap['line_value'])
                sharp_spread_book = sharp_spread_home_snap.get('book')
            elif sharp_spread_away_snap and sharp_spread_away_snap.get('line_value') is not None:
                sharp_spread_home_val = -float(sharp_spread_away_snap['line_value'])
                sharp_spread_book = sharp_spread_away_snap.get('book')

            sharp_total_val = None
            sharp_total_book = None
            if sharp_total_over_snap and sharp_total_over_snap.get('line_value') is not None:
                sharp_total_val = float(sharp_total_over_snap['line_value'])
                sharp_total_book = sharp_total_over_snap.get('book')
            elif sharp_total_under_snap and sharp_total_under_snap.get('line_value') is not None:
                sharp_total_val = float(sharp_total_under_snap['line_value'])
                sharp_total_book = sharp_total_under_snap.get('book')

            spread_target_home = consensus_spread['line_value'] if consensus_spread else None
            spread_target_away = (
                consensus_spread_away['line_value']
                if consensus_spread_away
                else (-float(consensus_spread['line_value']) if consensus_spread and consensus_spread.get('line_value') is not None else None)
            )
            total_target = consensus_total['line_value'] if consensus_total else None

            # Step B: Get BEST RETAIL PRICES for betting (never sharp benchmark books when retail exists)
            from src.utils.ncaam_quotes import recent_retail_quote
            quote_time = datetime.now(timezone.utc)
            retail_snaps = [q for q in raw_snaps if recent_retail_quote(q, quote_time)]
            best_spread_home = self.odds_selector.get_best_price_for_side(retail_snaps, 'SPREAD', 'HOME', target_line=spread_target_home)
            best_spread_away = self.odds_selector.get_best_price_for_side(retail_snaps, 'SPREAD', 'AWAY', target_line=spread_target_away)
            best_total_over = self.odds_selector.get_best_price_for_side(retail_snaps, 'TOTAL', 'OVER', target_line=total_target)
            best_total_under = self.odds_selector.get_best_price_for_side(retail_snaps, 'TOTAL', 'UNDER', target_line=total_target)
            best_ml_home = self.odds_selector.get_best_price_for_side(retail_snaps, 'MONEYLINE', 'HOME')
            best_ml_away = self.odds_selector.get_best_price_for_side(retail_snaps, 'MONEYLINE', 'AWAY')
            
            # Composite Snapshot for Analysis (uses CONSENSUS for model math)
            mc = self._derive_market_consensus_from_snaps(
                raw_snaps,
                consensus_spread=consensus_spread,
                consensus_total=consensus_total,
                base_mc=self._get_market_consensus(event_id),
            )
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
                # Sharp offshore/benchmark reference (Pinnacle / LowVig / BetOnline)
                '_sharp_spread_home': sharp_spread_home_val,
                '_sharp_spread_book': sharp_spread_book,
                '_sharp_total': sharp_total_val,
                '_sharp_total_book': sharp_total_book,
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
            if raw_snaps and market_snapshot.get('_sharp_spread_home') is None:
                s_h = self.odds_selector.get_sharp_benchmark_snapshot(raw_snaps, 'SPREAD', 'HOME')
                s_a = self.odds_selector.get_sharp_benchmark_snapshot(raw_snaps, 'SPREAD', 'AWAY')
                if s_h and s_h.get('line_value') is not None:
                    market_snapshot['_sharp_spread_home'] = float(s_h['line_value'])
                    market_snapshot['_sharp_spread_book'] = s_h.get('book')
                elif s_a and s_a.get('line_value') is not None:
                    market_snapshot['_sharp_spread_home'] = -float(s_a['line_value'])
                    market_snapshot['_sharp_spread_book'] = s_a.get('book')
            if raw_snaps and market_snapshot.get('_sharp_total') is None:
                t_o = self.odds_selector.get_sharp_benchmark_snapshot(raw_snaps, 'TOTAL', 'OVER')
                t_u = self.odds_selector.get_sharp_benchmark_snapshot(raw_snaps, 'TOTAL', 'UNDER')
                t_s = t_o if (t_o and t_o.get('line_value') is not None) else t_u
                if t_s and t_s.get('line_value') is not None:
                    market_snapshot['_sharp_total'] = float(t_s['line_value'])
                    market_snapshot['_sharp_total_book'] = t_s.get('book')

        # VALIDATION: If *both* spread and total are missing (or out of sane D1 bounds), we can't do anything.
        # Otherwise, proceed and only generate recommendations for markets with valid lines.
        raw_sp = market_snapshot.get('spread_home')
        has_spread = False
        if raw_sp is not None:
            try:
                sp_val = float(raw_sp)
                if math.isfinite(sp_val) and abs(sp_val) <= 55.0:
                    has_spread = True
                else:
                    market_snapshot['spread_home'] = None
            except Exception:
                market_snapshot['spread_home'] = None

        raw_tot = market_snapshot.get('total')
        has_total = False
        if raw_tot is not None:
            try:
                tot_val = float(raw_tot)
                if math.isfinite(tot_val) and 85.0 <= tot_val <= 215.0:
                    has_total = True
                else:
                    market_snapshot['total'] = None
            except Exception:
                market_snapshot['total'] = None

        if (not has_spread) and (not has_total):
            return {
                "headline": "Market Data Waiting",
                "recommendation": "No Line",
                "rationale": ["Market odds not yet fully populated."],
                "is_actionable": False
            }

        # If one market is missing, we still compute the other market.
        # Keep missing total as None instead of fabricating 145.0; _generate_recommendations skips missing markets.
        # Blend market prior 50/50 with sharp benchmark (Pinnacle/LowVig/BetOnline) when within 3.0 pts.
        mu_market_spread = (
            self._anchor_with_sharp(market_snapshot['spread_home'], market_snapshot.get('_sharp_spread_home'))
            if has_spread
            else 0.0
        )
        mu_market_total = (
            self._anchor_with_sharp(market_snapshot['total'], market_snapshot.get('_sharp_total'))
            if has_total
            else None
        )
        if isinstance(market_snapshot, dict):
            market_snapshot['_anchored_spread_home'] = mu_market_spread if has_spread else None
            market_snapshot['_anchored_total'] = mu_market_total if has_total else None

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

        # Neutral Site Detection (resolved early so Torvik/KenPom projections use neutral HCA=0)
        is_neutral = bool(
            (event_context and event_context.get('neutral_site'))
            or event.get('neutral_site')
            or self.manual_adjustments.get('is_neutral')
        )

        try:
            torvik_view = self.torvik_service.get_projection(
                event['home_team'],
                event['away_team'],
                date=game_date_str,
                neutral_site=is_neutral,
            )
        except TypeError:
            torvik_view = self.torvik_service.get_projection(
                event['home_team'],
                event['away_team'],
                date=game_date_str,
            )
        
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
        try:
            kenpom_adj = self.kenpom_client.calculate_kenpom_adjustment(
                event['home_team'],
                event['away_team'],
                neutral_site=is_neutral,
            )
        except TypeError:
            kenpom_adj = self.kenpom_client.calculate_kenpom_adjustment(
                event['home_team'],
                event['away_team'],
            )
        haslametrics_view = None
        if getattr(self, 'haslametrics_client', None) is not None:
            try:
                haslametrics_view = self.haslametrics_client.calculate_projection(
                    event['home_team'],
                    event['away_team'],
                    neutral_site=is_neutral,
                    asof_date=game_date_str,
                )
            except Exception as e:
                print(f"[MODEL] Haslametrics fetch error: {e}")
                haslametrics_view = None

        # KenPom player stats (used for injury point impact + UI/debug context)
        kp_players_home = []
        kp_players_away = []
        try:
            kp_players_home = self.kenpom_client.get_player_stats_for_team(event['home_team'], limit=50) or []
            kp_players_away = self.kenpom_client.get_player_stats_for_team(event['away_team'], limit=50) or []
        except Exception as e:
            print(f"[MODEL] KenPom player stats fetch error: {e}")

        injury_context = {"has_injuries": False, "injuries": [], "sigma_mult": 1.0, "spread_adj": 0.0, "total_adj": 0.0}
        if getattr(self, 'injury_service', None) is not None:
            try:
                try:
                    injury_context = self.injury_service.get_matchup_injuries(
                        event_id=event['id'],
                        home_team=event['home_team'],
                        away_team=event['away_team'],
                        allow_live_fallback=False,
                        home_players=kp_players_home,
                        away_players=kp_players_away,
                    )
                except TypeError:
                    injury_context = self.injury_service.get_matchup_injuries(
                        event_id=event['id'],
                        home_team=event['home_team'],
                        away_team=event['away_team'],
                        allow_live_fallback=False,
                    )
            except Exception as e:
                print(f"[MODEL] Injury lookup error: {e}")
        if not isinstance(injury_context, dict):
            injury_context = {"has_injuries": False, "injuries": [], "sigma_mult": 1.0, "spread_adj": 0.0, "total_adj": 0.0}

        action_splits = {}
        try:
            if os.environ.get("REQUIRE_DATABASE") != "0":
                from src.database import get_latest_action_splits
                action_splits = get_latest_action_splits(event['id'])
            elif isinstance(event, dict) and isinstance(event.get("action_splits"), dict):
                action_splits = event.get("action_splits") or {}
        except Exception:
            action_splits = {}

        # News can be slow; fetch only if we have a candidate edge to write up.
        news_context = {}
        
        # 4. Dynamic Weight Scaling
        # Compute local base_w_torvik per game without mutating self.W_BASE across batch runs.
        env_w_base = os.getenv('NCAAM_W_BASE')
        if env_w_base is not None:
            try:
                base_w_torvik = float(env_w_base)
            except Exception:
                base_w_torvik = self._get_dynamic_weights(game_date_obj)
        elif abs(float(self.W_BASE) - float(self.DEFAULT_W_BASE)) > 1e-9:
            base_w_torvik = float(self.W_BASE)
        else:
            base_w_torvik = self._get_dynamic_weights(game_date_obj)
        w_base = base_w_torvik

        # 5. Blend Math (Strict mu_final)
        # Defensive None handling
        mu_torvik_spread = -(torvik_view.get('margin') or 0.0)
        mu_sched_spread = -(torvik_view.get('official_margin') or -mu_torvik_spread)
        
        # KenPom Integration (only blend when KenPom ratings are actually available)
        kp_available = bool(
            kenpom_adj
            and kenpom_adj.get('summary') != 'KenPom data not available'
            and kenpom_adj.get('spread_adj') is not None
        )
        if kp_available:
            if is_neutral and kenpom_adj.get('neutral_margin') is not None:
                kp_margin = float(kenpom_adj.get('neutral_margin') or 0.0)
            elif not is_neutral and kenpom_adj.get('fair_margin') is not None:
                kp_margin = float(kenpom_adj.get('fair_margin') or 0.0)
            else:
                kp_margin = float(kenpom_adj.get('spread_adj') or 0.0)
            mu_kenpom_line = -kp_margin
            diff_kenpom = (mu_kenpom_line - mu_market_spread)
        else:
            kp_margin = 0.0
            mu_kenpom_line = mu_torvik_spread
            diff_kenpom = 0.0
        
        diff_torvik = (mu_torvik_spread - mu_market_spread)
        diff_sched = (mu_sched_spread - mu_market_spread)

        hasla_available = bool(
            haslametrics_view
            and haslametrics_view.get('available')
            and haslametrics_view.get('margin') is not None
        )
        if hasla_available:
            hasla_margin = float(haslametrics_view.get('margin') or 0.0)
            mu_hasla_line = -hasla_margin
            diff_hasla = (mu_hasla_line - mu_market_spread)
        else:
            hasla_margin = 0.0
            mu_hasla_line = mu_torvik_spread
            diff_hasla = 0.0
        
        # --- Feature: Luck Regression ---
        # If a team has high "Luck" (>0.05), they are overperforming and due for regression.
        # In November (Month 11), small sample sizes make Luck noisy; require >= 4 games or scale heavily.
        parsed_dt = self._parse_game_datetime(game_date_obj)
        game_month = getattr(parsed_dt, 'month', 1)
        luck_scale = 0.25 if game_month == 11 else (0.60 if game_month == 12 else 1.0)

        def _parse_games_from_record(rec_str) -> Optional[int]:
            if not rec_str or not isinstance(rec_str, str) or '-' not in rec_str:
                return None
            try:
                parts = rec_str.strip().split('-')
                return int(parts[0]) + int(parts[1])
            except Exception:
                return None

        home_rec_games = _parse_games_from_record((torvik_team_stats.get('home') or {}).get('record'))
        away_rec_games = _parse_games_from_record((torvik_team_stats.get('away') or {}).get('record'))
        known_rec_games = [g for g in (home_rec_games, away_rec_games) if g is not None]
        min_rec_games: Optional[int] = min(known_rec_games) if known_rec_games else None
        if min_rec_games is not None:
            luck_scale = 0.0 if min_rec_games < 3 else min(1.0, (min_rec_games - 2) / 10.0)
            situational_scale = round(min(1.0, 0.35 + 0.65 * max(0, min_rec_games - 1) / 10.0), 3)
        else:
            luck_scale = 0.30 if game_month == 11 else (0.65 if game_month == 12 else 1.0)
            situational_scale = 0.50 if game_month == 11 else (0.80 if game_month == 12 else 1.0)

        home_luck = (torvik_team_stats.get('home') or {}).get('luck', 0.0) or 0.0
        away_luck = (torvik_team_stats.get('away') or {}).get('luck', 0.0) or 0.0
        if isinstance(kenpom_adj, dict):
            kp_hl = _safe_float(kenpom_adj.get('home_luck'))
            kp_al = _safe_float(kenpom_adj.get('away_luck'))
            if kp_hl is not None:
                home_luck = (home_luck + kp_hl) / 2.0 if home_luck else kp_hl
            if kp_al is not None:
                away_luck = (away_luck + kp_al) / 2.0 if away_luck else kp_al
        
        # Continuous linear regression toward the mean (bounded to +/-1.0 * luck_scale per team)
        # Positive luck = overperformed close-game expectation -> fade team; negative luck -> boost.
        def _luck_fade(val: float) -> float:
            return max(-1.0, min(1.0, float(val) * 12.0))

        luck_adjustment = (_luck_fade(home_luck) - _luck_fade(away_luck)) * luck_scale
            
        # --- Feature: Continuity / Transfer Portal Factor ---
        # Prefer KenPom height_experience continuity when present (BartTorvik historical rows
        # previously mis-stored AdjTempo at row[44] as continuity; filter any value matching tempo).
        def _clean_cont(val: Any, tempo_val: Any) -> Optional[float]:
            v = _safe_float(val)
            if v is None:
                return None
            t = _safe_float(tempo_val)
            if t is not None and abs(v - t) <= 0.5:
                return None
            return v

        h_stats_tv = (torvik_team_stats or {}).get('home') or {}
        a_stats_tv = (torvik_team_stats or {}).get('away') or {}
        kp_h_cont = _safe_float(kenpom_adj.get('home_continuity')) if isinstance(kenpom_adj, dict) else None
        kp_a_cont = _safe_float(kenpom_adj.get('away_continuity')) if isinstance(kenpom_adj, dict) else None
        raw_h_cont = kp_h_cont if kp_h_cont is not None else _clean_cont(h_stats_tv.get('continuity'), h_stats_tv.get('tempo'))
        raw_a_cont = kp_a_cont if kp_a_cont is not None else _clean_cont(a_stats_tv.get('continuity'), a_stats_tv.get('tempo'))
        raw_h_cont = 0.7 if raw_h_cont is None else raw_h_cont
        raw_a_cont = 0.7 if raw_a_cont is None else raw_a_cont
        home_continuity = float(raw_h_cont) / 100.0 if float(raw_h_cont) > 1.5 else float(raw_h_cont)
        away_continuity = float(raw_a_cont) / 100.0 if float(raw_a_cont) > 1.5 else float(raw_a_cont)
        
        avg_continuity = (home_continuity + away_continuity) / 2.0
        
        # Dynamic Weights for Torvik (w_base), KenPom (w_kp), and Haslametrics (w_hasla)
        # Keep efficiency signals meaningfully independent from Vegas when multiple systems agree.
        w_base = base_w_torvik
        if avg_continuity < 0.5:
            w_base = min(w_base, 0.12)
        w_kp_target = self._get_dynamic_kenpom_weight(game_date_obj, avg_continuity=avg_continuity)
        w_hasla_base = 0.10 if game_month == 11 else (0.12 if game_month == 12 else 0.15)
        if avg_continuity < 0.5:
            w_hasla_base = min(w_hasla_base, 0.08)
        w_hasla_override = os.getenv('NCAAM_W_HASLA')
        w_hasla = 0.0
        if kp_available and hasla_available:
            w_kp = w_kp_target
            w_hasla = float(w_hasla_override) if w_hasla_override is not None else w_hasla_base
        elif kp_available:
            w_kp = w_kp_target
        elif hasla_available:
            w_kp = 0.0
            if w_hasla_override is not None:
                w_hasla = float(w_hasla_override)
            elif os.getenv('NCAAM_W_BASE') is None:
                w_hasla = round(w_hasla_base + (w_kp_target * 0.45), 4)
                w_base = round(w_base + (w_kp_target * 0.55), 4)
            else:
                w_hasla = w_hasla_base
        else:
            w_kp = 0.0
            if os.getenv('NCAAM_W_BASE') is None:
                w_base = min(w_base + w_kp_target, 0.45)

        # Early-season single-source outlier clamp (Nov/Dec):
        # When all 3 independent rating feeds are available, clamp any single feed's spread diff
        # to within +/-3.5 pts of the other two feeds' average so one noisy early-season rating
        # (e.g. light-prior Haslametrics) cannot pull the ensemble off consensus.
        if game_month in (11, 12) and kp_available and hasla_available:
            def _clamp_vs_peers(val, peer_a, peer_b, max_dev=3.5):
                peer_avg = (float(peer_a) + float(peer_b)) / 2.0
                if abs(float(val) - peer_avg) > max_dev:
                    return peer_avg + (max_dev if float(val) > peer_avg else -max_dev)
                return float(val)
            raw_dt, raw_dk, raw_dh = diff_torvik, diff_kenpom, diff_hasla
            diff_torvik = _clamp_vs_peers(raw_dt, raw_dk, raw_dh)
            diff_kenpom = _clamp_vs_peers(raw_dk, raw_dt, raw_dh)
            diff_hasla = _clamp_vs_peers(raw_dh, raw_dt, raw_dk)

        # Multi-Source Conviction Boost: when independent rating sources agree Vegas is off,
        # scale ensemble weight up (up to 60% independent / 40% market) instead of hugging market.
        spread_sig_diffs = []
        if abs(diff_torvik) >= 1.0:
            spread_sig_diffs.append(diff_torvik)
        if kp_available and abs(diff_kenpom) >= 1.0:
            spread_sig_diffs.append(diff_kenpom)
        if hasla_available and abs(diff_hasla) >= 1.0:
            spread_sig_diffs.append(diff_hasla)

        agree_count = 0
        if len(spread_sig_diffs) >= 2:
            if all(d > 0 for d in spread_sig_diffs) or all(d < 0 for d in spread_sig_diffs):
                agree_count = len(spread_sig_diffs)

        is_early_season = game_month in (11, 12)
        low_sample_teams = (min_rec_games is not None and min_rec_games < 6)
        if os.getenv('NCAAM_W_BASE') is None and agree_count >= 2:
            if game_month == 11 or low_sample_teams:
                conv_mult = 1.15 if agree_count >= 3 else 1.08
            elif game_month == 12:
                conv_mult = 1.25 if agree_count >= 3 else 1.16
            else:
                conv_mult = 1.45 if agree_count >= 3 else 1.30
            w_base *= conv_mult
            w_kp *= conv_mult
            w_hasla *= conv_mult

        # Conference-tier awareness: keep Power-5 games fully eligible, while giving
        # non-Power-5 (mid/low-major) 2+/3-model consensus spots a modest weight boost
        # where sportsbook lines are softer.
        POWER_CONFS = {"ACC", "B10", "B12", "SEC", "BE", "BIG EAST", "BIG TEN", "BIG 12"}
        h_conf = str((kenpom_adj or {}).get("home_conf") or "").strip().upper()
        a_conf = str((kenpom_adj or {}).get("away_conf") or "").strip().upper()
        is_power_game = bool((h_conf in POWER_CONFS) or (a_conf in POWER_CONFS))
        mid_major_boost = (0.04 if is_early_season else 0.05) if (not is_power_game and agree_count >= 2) else 0.0

        if os.getenv('NCAAM_W_BASE') is not None:
            max_eff_sum = 0.60
        elif game_month == 11:
            if agree_count >= 3:
                max_eff_sum = 0.35 + mid_major_boost
            elif agree_count == 2:
                max_eff_sum = (0.26 if not low_sample_teams else 0.24) + (mid_major_boost * 0.5)
            else:
                max_eff_sum = 0.20 if not low_sample_teams else 0.18
        elif game_month == 12:
            max_eff_sum = (0.44 if agree_count >= 3 else (0.36 if agree_count == 2 else 0.28)) + mid_major_boost
        else:
            max_eff_sum = (0.60 if agree_count >= 2 else 0.45) + mid_major_boost
        eff_sum = w_base + w_kp + w_hasla
        if eff_sum > max_eff_sum and eff_sum > 0:
            scale_back = max_eff_sum / eff_sum
            w_base = round(w_base * scale_back, 4)
            w_kp = round(w_kp * scale_back, 4)
            w_hasla = round(w_hasla * scale_back, 4)
        else:
            w_base = round(w_base, 4)
            w_kp = round(w_kp, 4)
            w_hasla = round(w_hasla, 4)
        
        mu_spread_final = (
            mu_market_spread
            + (w_base * diff_torvik)
            + (self.W_SCHED * diff_sched)
            + (w_kp * diff_kenpom)
            + (w_hasla * diff_hasla)
            + luck_adjustment
        )
        self._last_spread_components = {
            "mu_market_spread": float(mu_market_spread),
            "diff_torvik": float(diff_torvik),
            "diff_kenpom": float(diff_kenpom),
            "diff_hasla": float(diff_hasla),
            "other_adj": float((self.W_SCHED * diff_sched) + luck_adjustment),
            "w_base": float(w_base),
            "w_kp": float(w_kp),
            "w_hasla": float(w_hasla),
            "conviction_sources": int(agree_count),
        }
        
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
        
        # Compute average model-vs-market divergence across available feeds.
        sp_diffs_avail = [d for d, ok in ((diff_torvik, True), (diff_kenpom, kp_available), (diff_hasla, hasla_available)) if ok]
        mean_sp_gap = (sum(abs(float(d)) for d in sp_diffs_avail) / len(sp_diffs_avail)) if sp_diffs_avail else 0.0

        # Apply Caps (widen raw cap modestly when 2+ independent sources agree,
        # but keep Nov/Dec early-season spread cap tighter so unpriced roster variance doesn't overshoot market;
        # damp blowout spread cap on 25+ pt mismatches so walk-on garbage time doesn't inflate edges)
        is_early_season = game_month in (11, 12)
        effective_cap_spread = self.CAP_SPREAD
        if (os.getenv('NCAAM_CAP_SPREAD') is None) and agree_count >= 2:
            if is_early_season:
                effective_cap_spread = max(self.CAP_SPREAD, 2.2 if agree_count >= 3 else self.CAP_SPREAD)
            else:
                effective_cap_spread = max(self.CAP_SPREAD, 3.2)
        if (os.getenv('NCAAM_CAP_SPREAD') is None) and game_month == 11 and agree_count < 2:
            effective_cap_spread = min(effective_cap_spread, 1.65)
        if (os.getenv('NCAAM_CAP_SPREAD') is None) and mu_market_spread is not None:
            abs_mkt_spread = abs(float(mu_market_spread))
            if abs_mkt_spread >= 25.0:
                effective_cap_spread = min(effective_cap_spread, 1.85 if is_early_season else 2.4)
            elif abs_mkt_spread >= 15.0:
                effective_cap_spread = min(effective_cap_spread, 1.95 if is_early_season else 2.6)
        if abs(mu_spread_final - mu_market_spread) > effective_cap_spread:
             mu_spread_final = mu_market_spread + (effective_cap_spread * math.copysign(1, mu_spread_final - mu_market_spread))
        # Post-cap shrinkage on extreme 4.5+ pt rating-vs-market clashes (curbs unpriced-lineup edge traps)
        if os.getenv('NCAAM_DISABLE_EXTREME_SHRINK') is None and mean_sp_gap >= 4.5 and mu_market_spread is not None:
            sp_div_shrink = max(0.38, 1.0 - (mean_sp_gap - 4.5) * 0.14)
            mu_spread_final = mu_market_spread + ((mu_spread_final - mu_market_spread) * sp_div_shrink)

        # Total - None-safe handling without synthetic 145.0 fallbacks
        torvik_total_ok = bool(torvik_view and torvik_view.get('lean') != 'No Data')
        mu_torvik_total = _safe_float(torvik_view.get('total')) if torvik_total_ok else None
        kenpom_total_adj = (_safe_float(kenpom_adj.get('total_adj')) if isinstance(kenpom_adj, dict) else None) or 0.0
        kp_fair_total = _safe_float(kenpom_adj.get('fair_total')) if isinstance(kenpom_adj, dict) else None
        mu_kenpom_total = kp_fair_total if kp_fair_total is not None else (
            (mu_market_total + kenpom_total_adj)
            if (has_total and mu_market_total is not None and kp_available and abs(kenpom_total_adj) > 1e-9)
            else None
        )

        # KenPom player-based (rotation-weighted) efficiency signal (best-effort)
        # Only apply when KenPom team-level fair_total is unavailable so we don't double-count
        # KenPom offensive/defensive efficiency, and center around D1 average ORtg (106.5).
        kp_player_total_adj = 0.0
        kp_team_player_home = None
        kp_team_player_away = None
        try:
            kp_team_player_home = self.kenpom_client.get_team_player_agg(event['home_team'])
            kp_team_player_away = self.kenpom_client.get_team_player_agg(event['away_team'])
            if kp_fair_total is None and kp_team_player_home and kp_team_player_away:
                h_ortg = kp_team_player_home.get('ortg_w')
                a_ortg = kp_team_player_away.get('ortg_w')
                if h_ortg is not None and a_ortg is not None:
                    delta = (float(h_ortg) + float(a_ortg)) / 2.0 - 106.5
                    kp_player_total_adj = max(min(delta * 0.10, 1.5), -1.5)
        except Exception as e:
            print(f"[MODEL] KenPom player agg error: {e}")
        
        mu_hasla_total = _safe_float(haslametrics_view.get('total')) if hasla_available else None
        
        w_total_torvik = w_base + (0.5 * self.W_SCHED)
        w_total_kp = w_kp
        w_total_hasla = w_hasla
        diff_tv_tot = (mu_torvik_total - mu_market_total) if (has_total and mu_market_total is not None and torvik_total_ok and mu_torvik_total is not None) else 0.0
        diff_kp_tot = (mu_kenpom_total - mu_market_total) if (has_total and mu_market_total is not None and kp_available and mu_kenpom_total is not None) else 0.0
        diff_hs_tot = (mu_hasla_total - mu_market_total) if (has_total and mu_market_total is not None and hasla_available and mu_hasla_total is not None) else 0.0

        tot_sig_diffs = []
        if torvik_total_ok and mu_torvik_total is not None and abs(diff_tv_tot) >= 1.5:
            tot_sig_diffs.append(diff_tv_tot)
        if kp_available and mu_kenpom_total is not None and abs(diff_kp_tot) >= 1.5:
            tot_sig_diffs.append(diff_kp_tot)
        if hasla_available and mu_hasla_total is not None and abs(diff_hs_tot) >= 1.5:
            tot_sig_diffs.append(diff_hs_tot)

        agree_count_total = 0
        if len(tot_sig_diffs) >= 2:
            if all(d > 0 for d in tot_sig_diffs) or all(d < 0 for d in tot_sig_diffs):
                agree_count_total = len(tot_sig_diffs)

        if os.getenv('NCAAM_W_BASE') is None and agree_count_total >= 2:
            tot_sum = w_total_torvik + w_total_kp + w_total_hasla
            max_tot_sum = (
                0.30
                if (agree_count_total >= 3 and game_month == 11)
                else (0.22 if game_month == 11 else (0.36 if game_month == 12 else 0.54))
            )
            mult_tot_agree = (
                (1.18 if agree_count_total >= 3 else 1.08)
                if is_early_season
                else (1.35 if agree_count_total >= 3 else 1.25)
            )
            target_sum = min(max_tot_sum, tot_sum * mult_tot_agree)
            if tot_sum > 0 and target_sum != tot_sum:
                mult_t = target_sum / tot_sum
                w_total_torvik *= mult_t
                w_total_kp *= mult_t
                w_total_hasla *= mult_t

        effective_cap_total = self.CAP_TOTAL
        if os.getenv('NCAAM_CAP_TOTAL') is None:
            if is_early_season and self.CAP_TOTAL <= self.DEFAULT_CAP_TOTAL:
                effective_cap_total = min(self.CAP_TOTAL, 2.2 if game_month == 11 else 2.6)
            elif agree_count_total >= 2 and not is_early_season:
                effective_cap_total = max(self.CAP_TOTAL, 4.5 if agree_count_total >= 3 else 3.8)

        game_tempo_val = float((torvik_team_stats or {}).get('game_tempo', 68.0) or 68.0)
        tot_diffs_avail = [
            d for d, ok in (
                (diff_tv_tot, torvik_total_ok and mu_torvik_total is not None),
                (diff_kp_tot, kp_available and mu_kenpom_total is not None),
                (diff_hs_tot, hasla_available and mu_hasla_total is not None),
            ) if ok
        ]
        mean_tot_gap = (sum(abs(float(d)) for d in tot_diffs_avail) / len(tot_diffs_avail)) if tot_diffs_avail else 0.0

        kp_total_ff_adj = (_safe_float(kenpom_adj.get('total_four_factors_adj')) if isinstance(kenpom_adj, dict) else None) or 0.0

        if has_total and mu_market_total is not None:
            mu_total_final = (
                mu_market_total
                + (w_total_torvik * diff_tv_tot)
                + (w_total_kp * diff_kp_tot)
                + (w_total_hasla * diff_hs_tot)
            )
            tot_adj_scale = 0.45 if (game_month == 11 or low_sample_teams) else 1.0
            mu_total_final += kp_player_total_adj * tot_adj_scale
            mu_total_final += kp_total_ff_adj * situational_scale * tot_adj_scale
            potential_adjustment_total = council_adjustment_total
            if COUNCIL_ADJUSTMENTS_ENABLED:
                mu_total_final += council_adjustment_total
            else:
                if council_adjustment_total != 0.0:
                    print(f"[MODEL] Council total adj {council_adjustment_total:+.2f} computed but GATED (Phase 1 mode).")

            # Apply learned empirical scoring-environment bias from settled TOTAL predictions
            try:
                learned_tot_bias = float(((self._load_adaptive_learning() or {}).get("learned_adjustments") or {}).get("total_bias_pts") or 0.0)
                if learned_tot_bias != 0.0:
                    mu_total_final += 0.5 * learned_tot_bias
            except Exception:
                pass

            # Asymmetric TOTAL OVER calibration: efficiency ensembles systematically run hot
            # above sharp market totals in early season and fast-tempo matchups.
            if os.getenv('NCAAM_DISABLE_OVER_DAMP') is None and mu_total_final > mu_market_total:
                if game_month == 11 or low_sample_teams:
                    over_damp = 0.68 if agree_count_total >= 3 else 0.60
                else:
                    over_damp = 0.74 if is_early_season else 0.80
                if game_tempo_val >= 72.0:
                    over_damp *= 0.72
                mu_total_final = mu_market_total + ((mu_total_final - mu_market_total) * over_damp)
                eff_cap_tot_use = min(
                    effective_cap_total,
                    (2.0 if agree_count_total >= 3 else 1.80) if (game_month == 11 or low_sample_teams) else (2.25 if game_tempo_val >= 72.0 else 3.0),
                )
            else:
                eff_cap_tot_use = effective_cap_total
            if abs(mu_total_final - mu_market_total) > eff_cap_tot_use:
                mu_total_final = mu_market_total + (eff_cap_tot_use * math.copysign(1, mu_total_final - mu_market_total))
            if os.getenv('NCAAM_DISABLE_EXTREME_SHRINK') is None and mean_tot_gap >= 6.0:
                tot_div_shrink = max(0.50, 1.0 - (mean_tot_gap - 6.0) * 0.10)
                mu_total_final = mu_market_total + ((mu_total_final - mu_market_total) * tot_div_shrink)
        else:
            # Market total absent: compute display-only total from available real projections (never synthetic 145.0).
            weighted_tots = [
                (val, w)
                for val, w in (
                    (mu_torvik_total, max(float(w_total_torvik), 0.0)),
                    (mu_kenpom_total, max(float(w_total_kp), 0.0)),
                    (mu_hasla_total, max(float(w_total_hasla), 0.0)),
                )
                if val is not None
            ]
            if weighted_tots:
                w_sum_avail = sum(w for _, w in weighted_tots)
                if w_sum_avail > 0:
                    mu_total_final = sum(val * w for val, w in weighted_tots) / w_sum_avail
                else:
                    mu_total_final = sum(val for val, _ in weighted_tots) / len(weighted_tots)
                mu_total_final += kp_player_total_adj + (kp_total_ff_adj * situational_scale)
            else:
                mu_total_final = None
            potential_adjustment_total = council_adjustment_total

        # 6. Pace-Adjusted & Season-Calibrated Sigma (Refined)
        # Higher tempo = more possessions = higher variance = wider sigma
        # Early season (Nov/Dec) & low-continuity transfer rosters have higher residual variance.
        game_tempo = game_tempo_val
        tempo_factor = math.sqrt(game_tempo / 68.0)
        
        base_sigma_spread = 10.5
        base_sigma_total = 15.0  # Restored D1 total scoring sigma to curb marginal O/U false positives

        early_season_sigma_mult = 1.11 if game_month == 11 else (1.045 if game_month == 12 else 1.0)
        if min_rec_games is not None and min_rec_games < 5:
            early_season_sigma_mult *= 1.03
        if avg_continuity < 0.5:
            early_season_sigma_mult *= 1.05

        blowout_sigma_add = 0.0
        if mu_market_spread is not None and abs(float(mu_market_spread)) >= 14.0:
            blowout_sigma_add = min(4.5, (abs(float(mu_market_spread)) - 14.0) * 0.18)
        elif mu_market_spread is not None and abs(float(mu_market_spread)) >= 6.0:
            blowout_sigma_add = (abs(float(mu_market_spread)) - 6.0) * 0.09

        sigma_spread = (((base_sigma_spread + blowout_sigma_add) * tempo_factor) + 0.1 * abs(diff_torvik)) * early_season_sigma_mult
        sigma_total = ((base_sigma_total * tempo_factor) + 0.1 * (abs(mu_torvik_total - mu_market_total) if (mu_torvik_total is not None and mu_market_total is not None) else 0.0)) * early_season_sigma_mult
        if game_month == 11 and agree_count == 0:
            sigma_spread *= 1.035
        elif game_month == 11 and abs(diff_torvik) >= 4.0 and agree_count >= 2:
            sigma_spread *= 1.05
        elif is_early_season and abs(diff_torvik) >= 4.5:
            sigma_spread *= 1.06
        if game_month == 11 and abs(diff_tv_tot) >= 4.5:
            sigma_total *= 1.055
        elif is_early_season and abs(diff_tv_tot) >= 6.0:
            sigma_total *= 1.06

        # Extreme model-vs-market divergence reflects likely unpriced roster/situational info;
        # widen sigma smoothly so 12%+ edge outliers do not overstate predicted cover probability.
        if mean_sp_gap >= 4.5:
            sigma_spread *= (1.0 + min(0.22, (mean_sp_gap - 4.5) * 0.045))
        if mean_tot_gap >= 5.5:
            sigma_total *= (1.0 + min(0.20, (mean_tot_gap - 5.5) * 0.035))
        if has_total and mu_market_total is not None and mu_total_final is not None and mu_total_final > mu_market_total and game_tempo >= 72.0:
            sigma_total *= 1.08

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
                print(f"[MODEL] Inflating sigma due to qualitative instability signals for {event_id}")
                sigma_spread *= 1.15
                sigma_total *= 1.15

        # Pre-game injury uncertainty inflation (Rotowire / ESPN injury feed)
        inj_sigma_mult = float((injury_context or {}).get('sigma_mult') or 1.0)
        if inj_sigma_mult > 1.0:
            print(
                f"[MODEL] Inflating sigma due to pre-game injuries for {event_id}: "
                f"mult={inj_sigma_mult:.2f}, home_out={(injury_context or {}).get('home_out_count', 0)}, "
                f"away_out={(injury_context or {}).get('away_out_count', 0)}"
            )
            sigma_spread *= inj_sigma_mult
            sigma_total *= inj_sigma_mult

        # Possessions validation: compare Torvik game_tempo vs KenPom AdjT and Haslametrics pace.
        kp_tempo = None
        kp_tempo_gap = None
        hasla_tempo = _safe_float((haslametrics_view or {}).get('game_tempo')) if hasla_available and isinstance(haslametrics_view, dict) else None
        try:
            hr = self.kenpom_client.get_team_rating(event['home_team'])
            ar = self.kenpom_client.get_team_rating(event['away_team'])
            if hr and ar and hr.get('adj_t') is not None and ar.get('adj_t') is not None:
                kp_tempo = (float(hr['adj_t']) + float(ar['adj_t'])) / 2.0
                kp_tempo_gap = float(game_tempo) - float(kp_tempo)
        except Exception as e:
            print(f"[MODEL] tempo validation error: {e}")

        sec_tempos = [float(t) for t in (kp_tempo, hasla_tempo) if t is not None and float(t) > 40.0]
        if sec_tempos and max(abs(float(game_tempo) - t) for t in sec_tempos) >= 3.0:
            sigma_total *= 1.10

        # NOTE: We avoid hard sigma clamps; data-quality guardrails are applied later via
        # sanity scoring (sigma inflation / higher EV thresholds) rather than forcing caps.
        
        # --- Feature: Advanced Home Court (Geo) ---
        # Altitude
        try:
            altitude_adj = (
                self.geo_service.get_altitude_adjustment(
                    event['home_team'],
                    neutral_site=is_neutral,
                    away_team=event.get('away_team'),
                    venue_city=event.get('venue_city'),
                    venue_state=event.get('venue_state'),
                )
                or 0.0
            )
        except TypeError:
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

        # --- Feature: Basement Line (Power Rating) ---
        rating_lines = [mu_torvik_spread]
        if kp_available:
            rating_lines.append(mu_kenpom_line)
        if hasla_available:
            rating_lines.append(mu_hasla_line)
        raw_basement_line = sum(rating_lines) / float(len(rating_lines))
        raw_basement_line += luck_adjustment
        if altitude_adj > 0: raw_basement_line -= altitude_adj
        if kp_hca: raw_basement_line -= kp_hca
        if dist > 1000 and not is_neutral: raw_basement_line -= 0.5
        if self.manual_adjustments:
            raw_basement_line += self.manual_adjustments.get('home_injury', 0.0)
            raw_basement_line -= self.manual_adjustments.get('away_injury', 0.0)
        
        # 6.5 Advanced Situational Signals (uses precomputed situational_scale & bounded by outer sniper guardrail)

        # -- Shooting Regression (3PT Variance) --
        shooting_regr_home = self._calculate_shooting_regression(event['home_team'], as_of_date=game_date_obj) or 0.0
        shooting_regr_away = self._calculate_shooting_regression(event['away_team'], as_of_date=game_date_obj) or 0.0
        shooting_adj = (shooting_regr_home - shooting_regr_away) * situational_scale
        mu_spread_final += shooting_adj
        
        # -- Situational Spots (Letdown/Lookahead) --
        spot_adj_home = self._calculate_situational_spots(event['home_team'], event) or 0.0
        spot_adj_away = self._calculate_situational_spots(event['away_team'], event) or 0.0
        spot_adj = (spot_adj_home - spot_adj_away) * situational_scale
        mu_spread_final += spot_adj
        
        # -- Fatigue / Short Rest Signal --
        game_date = event.get('start_time')
        event_id = event.get('id')
        h_fatigue = self._calculate_fatigue_penalty(event['home_team'], event_id, game_date) or 0.0
        a_fatigue = self._calculate_fatigue_penalty(event['away_team'], event_id, game_date) or 0.0
        fatigue_adj = max(-1.0, min(1.0, h_fatigue - a_fatigue))
        mu_spread_final += fatigue_adj

        # -- Automated Player-Level Injury Impact (bounded) --
        inj_spread_adj = float((injury_context or {}).get('spread_adj') or 0.0)
        inj_total_adj = float((injury_context or {}).get('total_adj') or 0.0)
        inj_spread_adj = max(-3.0, min(3.0, inj_spread_adj))
        inj_total_adj = max(-3.0, min(0.5, inj_total_adj))
        if inj_spread_adj != 0.0:
            mu_spread_final += inj_spread_adj
        if inj_total_adj != 0.0 and mu_total_final is not None:
            mu_total_final += inj_total_adj

        # -- Strength of Schedule / Non-Conference Cupcake + Haslametrics Momentum & Inconsistency --
        kp_sos_adj = _safe_float((kenpom_adj or {}).get('sos_spread_adj')) or 0.0
        hasla_sos_adj = 0.0
        mom_adj = 0.0
        if hasla_available and isinstance(haslametrics_view, dict):
            h_hasla = haslametrics_view.get('home') or {}
            a_hasla = haslametrics_view.get('away') or {}
            h_sos_rank = _safe_float(h_hasla.get('sos'))
            a_sos_rank = _safe_float(a_hasla.get('sos'))
            if h_sos_rank is not None and a_sos_rank is not None:
                hasla_sos_adj = max(-0.6, min(0.6, ((a_sos_rank - h_sos_rank) / 250.0) * 0.45))
            h_mom = _safe_float(h_hasla.get('mom'))
            a_mom = _safe_float(a_hasla.get('mom'))
            if h_mom is not None and a_mom is not None:
                mom_adj = max(-0.5, min(0.5, (h_mom - a_mom) * 2.5))
            h_inc = _safe_float(h_hasla.get('inc'))
            a_inc = _safe_float(a_hasla.get('inc'))
            if h_inc is not None and a_inc is not None:
                avg_inc = max(0.0, (h_inc + a_inc) / 2.0)
                if avg_inc > 0.10:
                    sigma_spread *= (1.0 + min(0.08, avg_inc * 0.25))

        if kp_available and hasla_available:
            sos_adj = max(-1.0, min(1.0, (kp_sos_adj * 0.65) + (hasla_sos_adj * 0.35)))
        elif kp_available:
            sos_adj = max(-1.0, min(1.0, kp_sos_adj))
        else:
            sos_adj = hasla_sos_adj

        kp_ff_adj = _safe_float((kenpom_adj or {}).get('four_factors_adj')) or 0.0
        kp_eh_adj = _safe_float((kenpom_adj or {}).get('exp_height_adj')) or 0.0
        kp_style_adj = round(max(-1.2, min(1.2, kp_ff_adj + kp_eh_adj)), 2) if kp_available else 0.0

        # Positive sos_adj / mom_adj / kp_style_adj favors home team -> lower (more negative) home spread
        mu_spread_final -= (sos_adj + mom_adj + kp_style_adj) * situational_scale

        # Re-clamp automated spread adjustments (allow up to effective_cap + buffer,
        # keeping tighter buffers in early season and on 15+ / 25+ pt blowouts)
        if mu_market_spread is not None and abs(float(mu_market_spread)) >= 25.0:
            blowout_buffer = 0.3 if is_early_season else 0.4
        elif mu_market_spread is not None and abs(float(mu_market_spread)) >= 15.0:
            blowout_buffer = 0.35 if is_early_season else 0.6
        else:
            blowout_buffer = 0.5 if is_early_season else 1.0
        max_auto_spread_dev = effective_cap_spread + blowout_buffer
        if abs(mu_spread_final - mu_market_spread) > max_auto_spread_dev:
            mu_spread_final = mu_market_spread + (max_auto_spread_dev * math.copysign(1, mu_spread_final - mu_market_spread))
        if (
            os.getenv('NCAAM_DISABLE_MID_SPREAD_GATE') is None
            and mu_market_spread is not None
            and 6.0 <= abs(float(mu_market_spread)) < 14.0
        ):
            mu_spread_final = mu_market_spread + ((mu_spread_final - mu_market_spread) * 0.80)
        # Road favorite asymmetry: market/public favorites on the road face foul trouble & late-clock risk
        if (
            os.getenv('NCAAM_DISABLE_AWAY_FAV_GATE') is None
            and not is_neutral
            and mu_market_spread is not None
            and float(mu_market_spread) > 0.0
            and float(mu_spread_final) > float(mu_market_spread)
        ):
            mkt_sp_pos = float(mu_market_spread)
            if mkt_sp_pos >= 5.5 or is_early_season:
                mu_spread_final = mu_market_spread + ((mu_spread_final - mu_market_spread) * 0.65)
                sigma_spread *= 1.035
            else:
                mu_spread_final = mu_market_spread + ((mu_spread_final - mu_market_spread) * 0.85)

        # --- Feature: Live Injury Impact Toggle (applied after automated clamp) ---
        if self.manual_adjustments:
            h_inj = self.manual_adjustments.get('home_injury', 0.0)
            a_inj = self.manual_adjustments.get('away_injury', 0.0)
            mu_spread_final += h_inj
            mu_spread_final -= a_inj
        
        # -- Referee Signal (Totals + 3-way FT/foul synergy) --
        if mu_total_final is not None:
            kp_avg_ftr = _safe_float((kenpom_adj or {}).get('avg_ftr'))
            mu_total_final = self._apply_referee_signal(event['id'], mu_total_final, avg_ftr=kp_avg_ftr) or mu_total_final
            base_tot_cap = effective_cap_total
            if mu_market_total is not None and mu_total_final > mu_market_total and os.getenv('NCAAM_DISABLE_OVER_DAMP') is None:
                base_tot_cap = min(
                    effective_cap_total,
                    (2.0 if agree_count_total >= 3 else 1.80) if (game_month == 11 or low_sample_teams) else (2.25 if game_tempo >= 72.0 else 3.0),
                )
                if float(mu_market_total) >= 152.0:
                    base_tot_cap = min(base_tot_cap, 1.65 if is_early_season else 1.95)
                    mu_total_final = mu_market_total + ((mu_total_final - mu_market_total) * 0.78)
            max_auto_total_dev = base_tot_cap + (0.35 if is_early_season else 1.0)
            if mu_market_total is not None and abs(mu_total_final - mu_market_total) > max_auto_total_dev:
                mu_total_final = mu_market_total + (max_auto_total_dev * math.copysign(1, mu_total_final - mu_market_total))
        
        # 6.6 Generate Bell Curve Data for UI Visualization
        bell_curve_spread = self._generate_bell_curve(mu_spread_final, sigma_spread, mu_market_spread)
        bell_curve_total = self._generate_bell_curve(mu_total_final, sigma_total, mu_market_total)
            
        # 7. Recommendations & EV
        recs = self._generate_recommendations(
            mu_spread_final,
            sigma_spread,
            mu_total_final,
            sigma_total,
            market_snapshot,
            event,
            torvik_view=torvik_view,
            relax_gates=relax_gates,
            action_splits=action_splits,
            injury_context=injury_context,
            model_ctx={
                "game_month": game_month,
                "min_rec_games": min_rec_games,
                "is_early_season": is_early_season,
                "agree_count": agree_count,
                "agree_count_total": agree_count_total,
                "mean_sp_gap": mean_sp_gap,
                "mean_tot_gap": mean_tot_gap,
            },
        )

        # Only fetch news context if something passed the gates.
        if recs:
            try:
                news_context = self.news_service.fetch_game_context(event['home_team'], event['away_team'])
            except Exception as e:
                print(f"[NEWS] fetch_game_context failed: {e}")
                news_context = {}

        ref_summary = None
        try:
            if os.environ.get("REQUIRE_DATABASE") != "0":
                from src.database import get_referee_assignment
                ra = get_referee_assignment(event['id']) or {}
                refs = [ra.get('referee_1'), ra.get('referee_2'), ra.get('referee_3')]
                refs = [r for r in refs if r]
                if refs or ra.get('crew_avg_fouls') is not None:
                    crew_fouls = ra.get('crew_avg_fouls')
                    ref_summary = {
                        "officials": refs,
                        "crew_avg_fouls": float(crew_fouls) if crew_fouls is not None else None,
                    }
        except Exception:
            ref_summary = None

        hasla_asof = haslametrics_view.get("asof_date") if hasla_available else None
        if hasattr(hasla_asof, "isoformat"):
            hasla_asof = hasla_asof.isoformat()
        elif hasla_asof is not None:
            hasla_asof = str(hasla_asof)

        projected_score_info = None
        proj_home_score = None
        proj_away_score = None
        if mu_total_final is not None and mu_spread_final is not None:
            proj_home_exact = round((float(mu_total_final) - float(mu_spread_final)) / 2.0, 1)
            proj_away_exact = round((float(mu_total_final) + float(mu_spread_final)) / 2.0, 1)
            proj_home_score = int(round(proj_home_exact))
            proj_away_score = int(round(proj_away_exact))
            projected_score_info = {
                "home": proj_home_score,
                "away": proj_away_score,
                "home_exact": proj_home_exact,
                "away_exact": proj_away_exact,
                "formatted": f"{event.get('away_team', 'Away')} {proj_away_score} - {event.get('home_team', 'Home')} {proj_home_score}",
            }

        matchup_signals = {
            "projected_score": projected_score_info,
            "haslametrics": {
                "fair_spread_home": round(-float(hasla_margin), 1),
                "fair_total": round(float(mu_hasla_total), 1) if mu_hasla_total is not None else None,
                "projected_score": haslametrics_view.get("projected_score"),
                "asof_date": hasla_asof,
            } if hasla_available else None,
            "kenpom": {
                "fair_spread_home": round(-float(kp_margin), 1),
                "fair_total": round(float(mu_kenpom_total), 1) if mu_kenpom_total is not None else None,
                "four_factors_adj": round(float(kp_ff_adj), 2),
                "total_four_factors_adj": round(float(kp_total_ff_adj), 2),
                "exp_height_adj": round(float(kp_eh_adj), 2),
                "fanmatch_projected_score": (kenpom_adj.get("fanmatch") or {}).get("projected_score") if isinstance(kenpom_adj, dict) and isinstance(kenpom_adj.get("fanmatch"), dict) else None,
                "available": True,
            } if kp_available else None,
            "torvik": {
                "fair_spread_home": round(float(mu_torvik_spread), 1),
                "fair_total": round(float(mu_torvik_total), 1) if mu_torvik_total is not None else None,
                "projected_score": torvik_view.get("projected_score"),
            },
            "public_splits": action_splits or None,
            "injuries": (injury_context or {}).get("injuries") or [],
            "injuries_impact": {
                "spread_adj": inj_spread_adj,
                "total_adj": inj_total_adj,
                "home_impact_pts": float((injury_context or {}).get("home_impact_pts") or 0.0),
                "away_impact_pts": float((injury_context or {}).get("away_impact_pts") or 0.0),
                "impact_players": (injury_context or {}).get("impact_players") or [],
            } if ((injury_context or {}).get("has_injuries") or inj_spread_adj != 0.0 or inj_total_adj != 0.0) else None,
            "referees": ref_summary,
            "sharp_benchmark": {
                "spread_book": market_snapshot.get("_sharp_spread_book"),
                "spread_home": market_snapshot.get("_sharp_spread_home"),
                "total_book": market_snapshot.get("_sharp_total_book"),
                "total": market_snapshot.get("_sharp_total"),
                "anchored_spread_home": market_snapshot.get("_anchored_spread_home"),
                "anchored_total": market_snapshot.get("_anchored_total"),
            } if (
                market_snapshot.get("_sharp_spread_home") is not None
                or market_snapshot.get("_sharp_total") is not None
            ) else None,
            "weights": {
                "torvik": round(float(w_base), 3),
                "kenpom": round(float(w_kp), 3),
                "haslametrics": round(float(w_hasla), 3),
                "torvik_total": round(float(w_total_torvik), 3),
                "kenpom_total": round(float(w_total_kp), 3),
                "haslametrics_total": round(float(w_total_hasla), 3),
            },
            "adjustments": {
                "sos_adj": round(float(sos_adj), 2),
                "mom_adj": round(float(mom_adj), 2),
                "kp_style_adj": round(float(kp_style_adj), 2),
                "kp_hca": round(float(kp_hca), 2),
                "fatigue_adj": round(float(fatigue_adj), 2),
                "spot_adj": round(float(spot_adj), 2),
                "shooting_adj": round(float(shooting_adj), 2),
                "injury_spread_adj": round(float(inj_spread_adj), 2),
                "injury_total_adj": round(float(inj_total_adj), 2),
                "blowout_sigma_add": round(float(blowout_sigma_add), 2),
                "conviction_sources": int(agree_count),
                "conviction_sources_total": int(agree_count_total),
                "efficiency_weight": round(float(w_base + w_kp + w_hasla), 3),
            },
        }

        debug_info = {
            "mu_spread_final": mu_spread_final,
            "mu_total_final": mu_total_final,
            "sigma_spread": sigma_spread,
            "sigma_total": sigma_total,
            "tempo_factor": tempo_factor,
            "luck_adj": luck_adjustment,
            "geo_adj": altitude_adj if 'altitude_adj' in locals() else 0.0,
            "kenpom_hca_adj": kp_hca if 'kp_hca' in locals() else 0.0,
            "is_neutral": is_neutral,
            "basement_line": raw_basement_line,
            "w_base": w_base,
            "w_kp": w_kp,
            "w_hasla": w_hasla,
            "conviction_sources": agree_count,
            "conviction_sources_total": agree_count_total,
            "sos_adj": round(float(sos_adj), 3),
            "mom_adj": round(float(mom_adj), 3),
            "shooting_adj": shooting_adj,
            "spot_adj": spot_adj,
            "fatigue_adj": fatigue_adj,
            "injury_spread_adj": inj_spread_adj,
            "injury_total_adj": inj_total_adj,
            "bell_curve_spread": bell_curve_spread,
            "bell_curve_total": bell_curve_total,
            "torvik_refresh": datetime.now().strftime('%Y-%m-%d %H:%M'),  # When Torvik data was fetched
            "kenpom_players_home_n": len(kp_players_home or []),
            "kenpom_players_away_n": len(kp_players_away or []),
            "kenpom_player_total_adj": kp_player_total_adj if 'kp_player_total_adj' in locals() else 0.0,
            "kenpom_total_four_factors_adj": round(float(kp_total_ff_adj), 2),
            "kenpom_team_player_home": kp_team_player_home,
            "kenpom_team_player_away": kp_team_player_away,
            "tempo_torvik": game_tempo,
            "tempo_kenpom": kp_tempo if 'kp_tempo' in locals() else None,
            "tempo_gap": kp_tempo_gap if 'kp_tempo_gap' in locals() else None,
            "council_adj_spread": council_adjustment_spread,
            "council_adj_total": council_adjustment_total,
            "signals": matchup_signals,
        }
        
        mc = market_snapshot.get('_market_consensus') if isinstance(market_snapshot, dict) else None
        closest_lean = market_snapshot.get('_best_candidate') if isinstance(market_snapshot, dict) else None
        ctx = {
            'mu_spread_power': float(mu_spread_final) if mu_spread_final is not None else None,
            'mu_total_power': float(mu_total_final) if mu_total_final is not None else None,
            'fair_spread_home': round(float(mu_spread_final), 1) if mu_spread_final is not None else None,
            'fair_total': round(float(mu_total_final), 1) if mu_total_final is not None else None,
            'basement_line': round(float(raw_basement_line), 1) if raw_basement_line is not None else None,
            'torvik_spread_home': round(float(mu_torvik_spread), 1) if mu_torvik_spread is not None else None,
            'hasla_spread_home': round(float(mu_hasla_line), 1) if hasla_available else None,
            'kenpom_spread_home': round(float(mu_kenpom_line), 1) if kp_available else None,
            'conviction_sources': int(agree_count),
            'conviction_sources_total': int(agree_count_total),
            'efficiency_weight': round(float(w_base + w_kp + w_hasla), 3),
            'w_base': round(float(w_base), 3),
            'w_kp': round(float(w_kp), 3),
            'w_hasla': round(float(w_hasla), 3),
            'sos_adj': round(float(sos_adj), 2),
            'mom_adj': round(float(mom_adj), 2),
            'kp_style_adj': round(float(kp_style_adj), 2),
            'kp_hca': round(float(kp_hca), 2),
            'fatigue_adj': round(float(fatigue_adj), 2),
            'spot_adj': round(float(spot_adj), 2),
            'shooting_adj': round(float(shooting_adj), 2),
            'injury_spread_adj': round(float(inj_spread_adj), 2),
            'injury_total_adj': round(float(inj_total_adj), 2),
            'closest_lean': closest_lean,
            'projected_home_score': proj_home_score,
            'projected_away_score': proj_away_score,
            'projected_score': (projected_score_info or {}).get('formatted'),
            'blowout_sigma_add': round(float(blowout_sigma_add), 2),
            'sigma_spread': float(sigma_spread) if sigma_spread is not None else None,
            'sigma_total': float(sigma_total) if sigma_total is not None else None,
            'line_at_prediction_spread_home': (float(market_snapshot.get('spread_home')) if market_snapshot.get('spread_home') is not None else None) if isinstance(market_snapshot, dict) else None,
            'line_at_prediction_total': (float(market_snapshot.get('total')) if market_snapshot.get('total') is not None else None) if isinstance(market_snapshot, dict) else None,
            'sharp_book': (market_snapshot.get('_sharp_spread_book') or market_snapshot.get('_sharp_total_book')) if isinstance(market_snapshot, dict) else None,
            'sharp_spread_home': _safe_float(market_snapshot.get('_sharp_spread_home')) if isinstance(market_snapshot, dict) else None,
            'sharp_total': _safe_float(market_snapshot.get('_sharp_total')) if isinstance(market_snapshot, dict) else None,
            'anchored_market_spread_home': _safe_float(market_snapshot.get('_anchored_spread_home')) if isinstance(market_snapshot, dict) else None,
            'anchored_market_total': _safe_float(market_snapshot.get('_anchored_total')) if isinstance(market_snapshot, dict) else None,
            'open_spread_home': _safe_float(mc.get('open_spread_home')) if mc else None,
            'current_spread_home': _safe_float(mc.get('current_spread_home')) if mc else None,
            'spread_move_home': _safe_float(mc.get('spread_move_home')) if mc else None,
            'open_total': _safe_float(mc.get('open_total')) if mc else None,
            'current_total': _safe_float(mc.get('current_total')) if mc else None,
            'total_move': _safe_float(mc.get('total_move')) if mc else None,
            'spread_disagreement': _safe_float(mc.get('spread_disagreement')) if mc else None,
            'total_disagreement': _safe_float(mc.get('total_disagreement')) if mc else None,
            'books_count': (int(mc.get('books_count')) if mc and mc.get('books_count') is not None else None),
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

            if r['market'] in ('SPREAD', 'SPREAD_1H'):
                is_1h_sp = (r['market'] == 'SPREAD_1H')
                market_home = market_snapshot.get('spread_home')
                if is_1h_sp and r.get('fair_line_1h_home') is not None:
                    fair_home = float(r['fair_line_1h_home'])
                else:
                    fair_home = (mu_spread_final * 0.50) if (is_1h_sp and mu_spread_final is not None) else mu_spread_final

                # Convert to the side being bet (home vs away).
                # `r['side']` is usually 'home'/'away' (not a team name).
                side_key = str(r.get('side') or '').lower().strip()
                is_home_side = (side_key == 'home') or (r.get('team') == event.get('home_team')) or (r.get('side') == event.get('home_team'))

                if is_home_side:
                    market_line_side = r.get('line') if r.get('line') is not None else market_home
                    fair_line_side = fair_home
                else:
                    market_line_side = r.get('line') if r.get('line') is not None else ((-market_home) if market_home is not None else None)
                    fair_line_side = (-fair_home) if fair_home is not None else None

                if (market_line_side is not None) and (fair_line_side is not None):
                    # Points you are getting vs model fair (positive = better for bettor)
                    edge_points_side = round(float(market_line_side) - float(fair_line_side), 1)

            elif r['market'] in ('TOTAL', 'TOTAL_1H'):
                is_1h_tot = (r['market'] == 'TOTAL_1H')
                market_total = r.get('line') if r.get('line') is not None else market_snapshot.get('total')
                if is_1h_tot and r.get('fair_line_1h_total') is not None:
                    fair_total = float(r['fair_line_1h_total'])
                else:
                    fair_total = (mu_total_final * 0.472) if (is_1h_tot and mu_total_final is not None) else mu_total_final
                market_line_side = market_total
                fair_line_side = fair_total
                if (market_line_side is not None) and (fair_line_side is not None):
                    side_up = str(r.get('side') or '').upper()
                    edge_points_side = round(
                        (float(market_line_side) - float(fair_line_side))
                        if side_up == 'UNDER'
                        else (float(fair_line_side) - float(market_line_side)),
                        1,
                    )

            # Build a human-friendly selection label.
            # IMPORTANT: For SPREAD / SPREAD_1H, include the sign (+/-) so underdogs aren't displayed as favorites.
            sel = None
            if r['market'] in ('SPREAD', 'SPREAD_1H'):
                team = r.get('team') or (event['home_team'] if r.get('side') == 'home' else event['away_team'])
                if r['market'] == 'SPREAD_1H' and '1H' not in str(team):
                    team = f"{team} 1H"
                if r.get('line') is not None:
                    try:
                        v = float(r.get('line'))
                        sign = '+' if v > 0 else ''
                        sel = f"{team} {sign}{v:g}"
                    except Exception:
                        sel = team + f" {r.get('line')}"
                else:
                    sel = team
            elif r['market'] in ('TOTAL', 'TOTAL_1H'):
                side = str(r.get('side') or '').upper()
                prefix = '1H ' if r['market'] == 'TOTAL_1H' else ''
                sel = f"{prefix}{side}" + (f" {r['line']}" if r.get('line') is not None else "")
            else:
                sel = str(r.get('side') or '')

            lb10 = (round(float(r.get('win_prob_lb10')), 3) if r.get('win_prob_lb10') is not None else None)
            ub90 = (round(float(r.get('win_prob_ub90')), 3) if r.get('win_prob_ub90') is not None else None)
            bounds_available = (lb10 is not None) and (ub90 is not None)

            conf_label = self._confidence_label_from_winprob(
                r.get('win_prob_lb10') if isinstance(r, dict) else None,
                fallback_win_prob=win_prob,
            )
            conf_score = self._confidence_score_0_100(
                r.get('win_prob_lb10') if isinstance(r, dict) else None,
                fallback_win_prob=win_prob,
                ev_per_unit=r.get('ev'),
            )

            from src.utils.model_performance import compute_top6_quality_score, has_top6_risk_flag

            quality_input = {
                "market_type": r['market'],
                "side": r.get('side'),
                "home_team": event.get('home_team'),
                "away_team": event.get('away_team'),
                "selection": sel,
                "bet_line": r.get('line'),
                "market_line": market_line_side,
                "ev_per_unit": float(r['ev']),
                "win_prob_lb10": lb10,
                "confidence_0_100": conf_score,
                "movement_tags": r.get('movement_tags') or [],
                "sanity_reasons": r.get('sanity_reasons') or [],
            }
            top6_eligible = not has_top6_risk_flag(quality_input)
            quality_score = compute_top6_quality_score(quality_input)
            r['top6_eligible'] = top6_eligible
            r['quality_score'] = quality_score

            sizing = compute_recommended_bet_size(
                win_prob,
                r.get('price'),
                confidence_tier=conf_label,
                confidence_score=conf_score,
                ev=r.get('ev'),
                kelly_q=r.get('kelly'),
            )
            r['suggested_units'] = sizing['units']
            r['recommended_units'] = sizing['units']
            r['bankroll_pct'] = sizing['bankroll_pct']
            r['sizing_tier'] = sizing['sizing_tier']

            ui_rec = {
                "bet_type": r['market'],
                "calibration": {k: self._load_winprob_calibration().get(k) for k in (
                    "source", "n_obs", "training_cutoff", "fit_completed_at", "season_start")},
                "side": r.get('side'),
                "selection": sel,
                # Numeric EV (decimal & %) + legacy 'edge' string for backward compatibility
                "ev": round(float(r['ev']), 4),
                "ev_pct": round(float(r['ev']) * 100.0, 2),
                "edge": f"{(r['ev']*100):.1f}%",
                "raw_win_prob": r.get("raw_win_prob"),
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
                "suggested_units": sizing['units'],
                "recommended_units": sizing['units'],
                "bankroll_pct": sizing['bankroll_pct'],
                "sizing_tier": sizing['sizing_tier'],
                # Confidence = model confidence that the bet wins (based on calibrated win_prob lower bound)
                "confidence": conf_label,
                "confidence_tier": str(conf_label).upper(),
                "confidence_0_100": conf_score,
                "book": r['book'],
                "quote_captured_at": r.get("quote_captured_at"),
                "sharp_book": r.get('sharp_book'),
                "sharp_line": r.get('sharp_line'),
                "sharp_edge_pts": r.get('sharp_edge_pts'),
                # Movement/uncertainty instrumentation
                "sigma_mult": r.get('sigma_mult'),
                "ev_raw": r.get('ev_raw'),
                "ev_penalty": r.get('ev_penalty'),
                "movement_tags": r.get('movement_tags'),
                "top6_eligible": top6_eligible,
                "quality_score": quality_score,
                "prediction_id": r.get('prediction_id'),
                "signals": matchup_signals,
            }
            ui_recs.append(ui_rec)
            r['_ui_rec'] = ui_rec

        if ui_recs:
            ui_recs.sort(
                key=lambda x: (
                    1 if x.get('top6_eligible', True) else 0,
                    float(x.get('quality_score') if x.get('quality_score') is not None else -999.0),
                    float(x.get('ev') if x.get('ev') is not None else -999.0),
                ),
                reverse=True,
            )
            recs.sort(
                key=lambda x: (
                    1 if x.get('top6_eligible', True) else 0,
                    float(x.get('quality_score') if x.get('quality_score') is not None else -999.0),
                    float(x.get('ev') if x.get('ev') is not None else -999.0),
                ),
                reverse=True,
            )
            best_rec = recs[0]

        inputs_payload = {
            "market": market_snapshot,
            "winprob_calibration": self._load_winprob_calibration(),
            "torvik": torvik_view,
            "kenpom": kenpom_adj,
            "haslametrics": haslametrics_view,
            "injuries": injury_context,
            "public_splits": action_splits,
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
        persisted_best = False
        persisted_spread_sides = set()
        within_lock_window = False
        try:
            st = event.get('start_time')
            if st is not None:
                if isinstance(st, str):
                    st = datetime.fromisoformat(st.replace('Z', '+00:00'))
                if getattr(st, 'tzinfo', None) is None:
                    st = st.replace(tzinfo=timezone.utc)
                now_dt = datetime.now(timezone.utc)
                if now_dt >= (st - timedelta(minutes=10)):
                    within_lock_window = True
        except Exception:
            within_lock_window = False

        def _extract_open_line_and_price(rec_obj):
            if not isinstance(rec_obj, dict):
                return None, None
            mkt_o = str(rec_obj.get('market') or '').upper()
            side_o = str(rec_obj.get('side') or '').lower()
            mc_open = market_snapshot.get('_market_consensus') if isinstance(market_snapshot, dict) else None
            open_l = None
            open_p = None
            if isinstance(mc_open, dict):
                if mkt_o == 'SPREAD':
                    osh = _safe_float(mc_open.get('open_spread_home'))
                    if osh is not None:
                        open_l = round(-osh if side_o == 'away' else osh, 2)
                    if side_o == 'home':
                        open_p = mc_open.get('open_spread_price_home')
                elif mkt_o == 'TOTAL':
                    open_l = _safe_float(mc_open.get('open_total'))
                    open_p = (
                        mc_open.get('open_total_over_price')
                        if side_o == 'over'
                        else mc_open.get('open_total_under_price')
                    )
            if open_l is None:
                open_l = rec_obj.get('line')
            if open_p is None:
                open_p = rec_obj.get('price')
            return open_l, (int(open_p) if open_p is not None else None)

        if recs:
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
                    bet_line = _safe_float(line_val)
                    if pick and bet_line is not None:
                        v = float(bet_line)
                        sign = '+' if v > 0 else ''
                        selection = f"{pick} {sign}{v:g}"
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
                    mu_market = _safe_float(market_snapshot.get('total'))
                    mu_torvik_val = mu_torvik_total
                    mu_final_val = mu_total_final
                    sigma_val = sigma_total
                    if mu_market is not None and mu_final_val is not None:
                        edge = float(mu_final_val) - float(mu_market)
                elif mkt == 'TOTAL_1H':
                    pick = side.upper()
                    bet_line = _safe_float(line_val)
                    selection = f"1H {pick}"
                    mu_final_val = _safe_float(rec.get('fair_line_1h_total'))
                elif mkt == 'SPREAD_1H':
                    pick = rec.get('team')
                    bet_line = _safe_float(line_val)
                    selection = (rec.get('_ui_rec') or {}).get('selection') or pick
                    fair_home = _safe_float(rec.get('fair_line_1h_home'))
                    mu_final_val = -fair_home if side == 'away' and fair_home is not None else fair_home
                else:
                    pick = rec.get('team') or event.get('home_team')
                    bet_line = line_val
                    selection = selection or pick
                    mu_market = _safe_float(market_snapshot.get('total'))
                    mu_torvik_val = mu_torvik_total
                    mu_final_val = mu_total_final
                    sigma_val = sigma_total
                    if mu_market is not None and mu_final_val is not None:
                        edge = float(mu_final_val) - float(mu_market)

                open_line_val, open_price_val = _extract_open_line_and_price(rec)

                doc = {
                    "event_id": event_id,
                    "model_version": self.VERSION,
                    "market_type": mkt,
                    "pick": pick,
                    "bet_line": bet_line,
                    "bet_price": int(price) if price is not None else None,
                    "open_line": open_line_val,
                    "open_price": open_price_val,
                    "book": book,
                    "mu_market": mu_market,
                    "mu_torvik": mu_torvik_val,
                    "mu_final": mu_final_val,
                    "sigma": sigma_val,
                    "win_prob": float(rec.get('win_prob') or 0.0),
                    "ev_per_unit": float(rec.get('ev') or 0.0),
                    "confidence_0_100": self._confidence_score_0_100(
                        rec.get('win_prob_lb10'),
                        fallback_win_prob=rec.get('win_prob'),
                        ev_per_unit=rec.get('ev'),
                    ),
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
                if not persist or within_lock_window:
                    continue
                if relax_gates and (
                    int(doc.get("confidence_0_100") or 0) < 55
                    or float(doc.get("ev_per_unit") or 0.0) < self.PUBLISH_MIN_EV
                ):
                    continue
                try:
                    import uuid
                    doc.setdefault("id", str(uuid.uuid4()))
                    persisted_id = insert_model_prediction(doc)
                    if not persisted_id:
                        continue
                    doc["id"] = persisted_id
                except Exception as e:
                    print(f"[MODEL] failed to persist rec {rec.get('market')} {rec.get('side')}: {e}")
                    continue
                rec['prediction_id'] = doc.get('id')
                if str(rec.get('market') or '').upper() == 'SPREAD' and rec.get('side'):
                    persisted_spread_sides.add(str(rec.get('side')).strip().upper())
                ui_ref = rec.get('_ui_rec')
                if ui_ref is not None:
                    ui_ref['prediction_id'] = doc.get('id')
                if rec is best_rec:
                    inserted_best_doc_id = doc.get('id')
                    persisted_best = True
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


        def _summarize_rotation(players_list):
            out_p = []
            for p in (players_list or []):
                if not isinstance(p, dict):
                    continue
                name = str(p.get('player_name') or '').strip()
                if not name:
                    continue
                m = p.get('metrics') if isinstance(p.get('metrics'), dict) else {}
                min_pct = _safe_float(m.get('min_pct') or m.get('Min%') or m.get('min'))
                ortg = _safe_float(m.get('ortg') or m.get('ORtg'))
                usg = _safe_float(m.get('usg') or m.get('Poss%'))
                porpag = _safe_float(m.get('porpag'))
                # Estimate spread impact (pts) if player sits:
                # Prefer BartTorvik PORPAG (points over replacement per game) blended with minutes share.
                min_share = (min_pct / 100.0) if (min_pct is not None and min_pct > 1.5) else (min_pct or 0.45)
                if porpag is not None:
                    # Clamp replacement value so negative-PORPAG starters still carry modest rotation-disruption cost
                    raw_pts = max(0.3, min(3.8, (max(0.0, porpag) * 0.65) + (min_share * 1.1)))
                else:
                    eff_bonus = max(0.0, ((ortg or 104.0) - 98.0) / 14.0)
                    raw_pts = max(0.3, min(3.2, (min_share * 2.4) + (eff_bonus * min_share)))
                est_pts = round(raw_pts, 1)
                out_p.append({
                    'name': name,
                    'min_pct': round(min_pct, 1) if min_pct is not None else None,
                    'ortg': round(ortg, 1) if ortg is not None else None,
                    'usg': round(usg, 1) if usg is not None else None,
                    'porpag': round(porpag, 2) if porpag is not None else None,
                    'est_impact_pts': est_pts,
                })
            out_p.sort(key=lambda x: (x['min_pct'] or 0.0, x['est_impact_pts']), reverse=True)
            return out_p[:7]

        res = {
            "id": best_prediction_id or None,
            "rotation_players": {
                "home": _summarize_rotation(kp_players_home),
                "away": _summarize_rotation(kp_players_away),
            },
            "event_id": event_id,
            "home_team": event['home_team'],
            "away_team": event['away_team'],
            "neutral_site": bool(is_neutral),
            "venue": event.get('venue'),
            "venue_city": event.get('venue_city'),
            "venue_state": event.get('venue_state'),
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
            "confidence_0_100": self._confidence_score_0_100(
                best_rec.get('win_prob_lb10'),
                fallback_win_prob=best_rec.get('win_prob'),
                ev_per_unit=best_rec.get('ev'),
            ) if best_rec else 0,
            "inputs_json": inputs_json_str,
            "outputs_json": outputs_json_str,
            "narrative": narrative,
            "narrative_json": narrative_json_str,
            "context": ctx,
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
            "open_line": _extract_open_line_and_price(best_rec)[0] if best_rec else None,
            "open_price": _extract_open_line_and_price(best_rec)[1] if best_rec else None,
            "clv_method": "odds_selector_v1",
            "debug": debug_info
        }
        if not res['id']:
            import uuid
            res['id'] = str(uuid.uuid4())

        res["signals"] = matchup_signals

        # 10. Persist
        # Only keep history for recommended bets (avoid storing analysis-only rows).
        should_persist = bool(best_rec) and (float(res.get('ev_per_unit') or 0.0) >= self.PUBLISH_MIN_EV)
        should_persist = should_persist and str(res.get('market_type') or '').upper() not in ('', 'AUTO')
        should_persist = should_persist and str(res.get('pick') or '').upper() not in ('', 'NONE')
        should_persist = should_persist and (res.get('selection') is not None and str(res.get('selection')).strip() not in ('', '—'))

        if within_lock_window:
            should_persist = False

        if persist and should_persist and not persisted_best:
            fallback_id = insert_model_prediction(res)
            if fallback_id and best_rec and best_rec.get('_ui_rec') is not None:
                best_rec['_ui_rec']['prediction_id'] = fallback_id
                res['id'] = fallback_id
            if str(res.get('market_type') or '').upper() == 'SPREAD':
                rec_side = str((best_rec or {}).get('side') or '').strip().upper()
                if rec_side:
                    persisted_spread_sides.add(rec_side)

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
                prob_home, prob_away = self._moneyline_probabilities(prob_home_raw, is_early_season)

                ev_home = float(ev_per_unit(prob_home, int(ml_price_home)) or 0.0)
                ev_away = float(ev_per_unit(prob_away, int(ml_price_away)) or 0.0)

                # Evaluate ~7pt home favorite 2-leg ML parlay qualifier (-4.5 to -9.5 spread)
                spread_home_snap = market_snapshot.get('spread_home') if isinstance(market_snapshot, dict) else None
                best_tags = (best_rec or {}).get('movement_tags') if isinstance(best_rec, dict) else None
                is_home_fav_parlay_leg = self.is_sweet_spot_home_fav_ml_leg(
                    spread_home=spread_home_snap,
                    fair_spread_home=mu_spread_final,
                    win_prob_home=prob_home,
                    ml_price_home=ml_price_home,
                    ev_home=ev_home,
                    is_neutral=bool(is_neutral),
                    movement_tags=best_tags,
                )

                # Choose side with higher EV (unless HOME qualifies specifically for the ~7pt ML parlay builder)
                side = 'HOME' if (ev_home >= ev_away or is_home_fav_parlay_leg) else 'AWAY'
                team = event.get('home_team') if side == 'HOME' else event.get('away_team')
                price = int(ml_price_home) if side == 'HOME' else int(ml_price_away)
                book = ml_book_home if side == 'HOME' else ml_book_away
                wp = prob_home if side == 'HOME' else prob_away
                ev = ev_home if side == 'HOME' else ev_away

                if side == 'HOME' and is_home_fav_parlay_leg and ev_home >= 0.005:
                    should_persist_ml = bool(team is not None and str(team).strip() != '')
                else:
                    # Gate Moneyline persistence strictly to curb unprofitable longshots / marginal noise
                    should_persist_ml = self._passes_ml_persist_gates(
                        win_prob=wp,
                        ev=ev,
                        price=price,
                    )
                    should_persist_ml = should_persist_ml and team is not None and str(team).strip() != ''

                    # Prevent correlated same-game double exposure: if we already persisted a SPREAD
                    # bet on the exact same team/side (either as best_rec or secondary rec), skip
                    # persisting a standalone MONEYLINE row.
                    team_norm = str(team or '').strip().lower()
                    same_team_spread_persisted = side in persisted_spread_sides
                    if not same_team_spread_persisted and should_persist and str(res.get('market_type') or '').upper() == 'SPREAD':
                        spread_pick_norm = str(res.get('pick') or res.get('selection') or '').strip().lower()
                        rec_side_norm = str((best_rec or {}).get('side') or '').strip().upper()
                        same_team_spread_persisted = bool(team_norm) and (
                            spread_pick_norm == team_norm
                            or spread_pick_norm.startswith(team_norm)
                            or rec_side_norm == side
                        )
                    if same_team_spread_persisted:
                        should_persist_ml = False

                # Apply same lock window
                if should_persist_ml:
                    try:
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

                    equiv_ml_lb10 = (0.50 + float(edge_prob) - 0.015) if edge_prob is not None else None
                    ml_conf_0_100 = self._confidence_score_0_100(
                        equiv_ml_lb10,
                        fallback_win_prob=(0.50 + max(0.0, float(edge_prob or 0.0))),
                        ev_per_unit=float(ev),
                    )
                    if (side == 'HOME' and is_home_fav_parlay_leg and not is_neutral) or relax_gates or ml_conf_0_100 >= 55:
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
                            "confidence_0_100": ml_conf_0_100,
                            "selection": str(team),
                            "price": price,
                            # Store probability edge as edge_points for ML (not points).
                            "edge_points": (round(float(edge_prob), 4) if edge_prob is not None else None),
                            "open_line": None,
                            "open_price": price,
                            "clv_method": ("home_fav_7pt_parlay_v1" if (side == 'HOME' and is_home_fav_parlay_leg) else "odds_selector_v1"),
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
    PUBLISH_MIN_EV_TOTAL = 0.035  # +3.5% EV required on Over/Under totals (curbs O/U bleed)
    PUBLISH_MIN_EV_TOTAL_OVER = 0.041  # +4.1% base EV required on TOTAL OVER (higher early-season/solo bars below)
    PUBLISH_MIN_WINPROB_LB10 = 0.52  # Require >= 52% 10th-pct cover prob (maps to >= 55 conf / Medium+)
    PUBLISH_MIN_EV_ML = 0.05  # +5.0% EV required on Moneyline picks
    MIN_ML_WIN_PROB = 0.52    # Exclude plus-money / sub-52% underdogs (historically ~20% win rate)
    MAX_ML_UNDERDOG_PRICE = 105
    MAX_ML_FAVORITE_PRICE = -250
    MIN_ML_PROB_EDGE = 0.035  # Require >= +3.5% calibrated win-prob edge vs market implied
    PUBLISH_CI_Z = 1.96    # 95% CI on archetype mean
    PUBLISH_MIN_N_TORVIK_OK = 40
    PUBLISH_MIN_N_TORVIK_MISSING = 60
    PUBLISH_MIN_EV_TORVIK_MISSING_BUMP = 0.005  # +0.5%
    HOME_FAV_PARLAY_SPREAD_MIN = -9.5
    HOME_FAV_PARLAY_SPREAD_MAX = -4.5
    MAX_ML_HOME_FAV_PARLAY_PRICE = -380
    MIN_ML_HOME_FAV_WIN_PROB = 0.68

    def is_sweet_spot_home_fav_ml_leg(
        self,
        *,
        spread_home: Any,
        fair_spread_home: Any,
        win_prob_home: Any,
        ml_price_home: Any,
        ev_home: Any = None,
        is_neutral: bool = False,
        movement_tags: Optional[List[str]] = None,
    ) -> bool:
        """Return True when a non-neutral +EV ~7pt (-4.5 to -9.5) home favorite qualifies for 2-leg ML parlays."""
        if is_neutral:
            return False
        try:
            sp = float(spread_home)
            wp = float(win_prob_home)
            pr = int(ml_price_home)
        except Exception:
            return False

        if not (self.HOME_FAV_PARLAY_SPREAD_MIN <= sp <= self.HOME_FAV_PARLAY_SPREAD_MAX):
            return False
        if not (self.MAX_ML_HOME_FAV_PARLAY_PRICE <= pr <= -160):
            return False
        if wp < float(self.MIN_ML_HOME_FAV_WIN_PROB):
            return False

        if ev_home is not None:
            try:
                if float(ev_home) < 0.005:
                    return False
            except Exception:
                return False

        if fair_spread_home is not None:
            try:
                if float(fair_spread_home) > sp - 0.5:
                    return False
            except Exception:
                pass

        for t in movement_tags or []:
            low = str(t or "").strip().lower()
            if low == "contra_sharp_money" or low.startswith("reverse_steam="):
                return False
        return True

    def _passes_ml_persist_gates(self, *, win_prob: Any, ev: Any, price: Any) -> bool:
        """Apply calibrated Moneyline profitability & price-band gates before persisting.

        Supports:
        - Core favorites/pick'ems (-250 to +105): win_prob >= 52%, EV >= +5%, prob edge >= +3.5%
        - Plus-odds value underdogs (+106 to +200): win_prob >= 38%, EV >= +6%, prob edge >= +4.5%
        """
        from src.utils.ev import implied_prob_american

        try:
            ev_val = float(ev)
            wp_val = float(win_prob)
            pr_val = int(price)
        except Exception:
            return False

        if pr_val < int(self.MAX_ML_FAVORITE_PRICE):
            return False

        ip = implied_prob_american(pr_val)
        prob_edge = (wp_val - float(ip)) if ip is not None else 0.0

        # Plus-odds value underdog band (+106 to +200)
        if int(self.MAX_ML_UNDERDOG_PRICE) < pr_val <= 200:
            return (
                wp_val >= 0.38
                and ev_val >= 0.06
                and prob_edge >= 0.045
            )

        if pr_val > int(self.MAX_ML_UNDERDOG_PRICE):
            return False
        if ev_val < float(self.PUBLISH_MIN_EV_ML):
            return False
        if wp_val < float(self.MIN_ML_WIN_PROB):
            return False
        if ip is not None and prob_edge < float(self.MIN_ML_PROB_EDGE):
            return False
        return True

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
    _adaptive_learning_cache: Optional[Dict[str, Any]] = None

    def _resolve_model_param_path(self, filename: str) -> str:
        return resolve_model_param_path(filename)

    def _load_adaptive_learning(self) -> Dict[str, Any]:
        """Load persisted self-learning archetype ROI & bias state (empty dict offline)."""
        if self._adaptive_learning_cache is not None:
            return self._adaptive_learning_cache
        try:
            from src.services.archetype_learning_service import load_adaptive_model_learning

            self._adaptive_learning_cache = load_adaptive_model_learning() or {}
        except Exception:
            self._adaptive_learning_cache = {}
        return self._adaptive_learning_cache

    def _load_action_network_stats(self) -> Dict[str, Any]:
        if self._action_network_stats is not None:
            return self._action_network_stats

        path = self._resolve_model_param_path('action_network_archetype_stats_ncaam.json')

        try:
            with open(path, 'r', encoding='utf-8') as f:
                base_stats = json.load(f)
        except Exception:
            base_stats = {"bins": {}}

        bins = dict((base_stats or {}).get('bins') or {})
        try:
            learned_bins = (self._load_adaptive_learning() or {}).get('bins')
            if isinstance(learned_bins, dict) and learned_bins:
                bins.update(learned_bins)
        except Exception:
            pass
        self._action_network_stats = {**(base_stats or {}), "bins": bins}
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
        side_lower = str(rec.get("side") or "").strip().lower()
        tags = [str(t or "").strip().lower() for t in (rec.get("movement_tags") or [])]
        has_sharp = ("sharp_backing" in tags) or ("rlm_confirmed" in tags) or ("lagging_book_edge" in tags)
        is_early = bool(rec.get("_is_early_season"))
        min_games = rec.get("_min_rec_games")
        low_sample = min_games is not None and int(min_games) < 6
        agree_sp = rec.get("_agree_count")
        agree_tot = rec.get("_agree_count_total")

        if market == "TOTAL":
            base_ev = (
                float(getattr(self, "PUBLISH_MIN_EV_TOTAL_OVER", 0.052))
                if side_lower == "over"
                else float(self.PUBLISH_MIN_EV_TOTAL)
            )
        else:
            base_ev = float(self.PUBLISH_MIN_EV)
        min_ev = base_ev if torvik_ok else (base_ev + float(self.PUBLISH_MIN_EV_TORVIK_MISSING_BUMP))

        # Mid-spread (6–14 pt), blowout (14–22 pt), and early-season selectivity gates
        if market == "SPREAD" and market_line_home is not None:
            try:
                abs_sp_line = abs(float(market_line_home))
                if 6.0 <= abs_sp_line < 14.0 and os.getenv("NCAAM_DISABLE_MID_SPREAD_GATE") is None:
                    mid_bump = 0.004 if has_sharp else 0.012
                    try:
                        sb_bumps = ((self._load_adaptive_learning() or {}).get("learned_adjustments") or {}).get("spread_bucket_ev_bump") or {}
                        if "mid_6_14" in sb_bumps and not has_sharp:
                            mid_bump = float(sb_bumps["mid_6_14"])
                    except Exception:
                        pass
                    min_ev += max(0.0, mid_bump)
                elif 14.0 <= abs_sp_line < 22.0 and not has_sharp:
                    min_ev += 0.006
                if (is_early or low_sample) and not has_sharp:
                    if abs_sp_line < 6.0 and (agree_sp is not None and int(agree_sp) < 2):
                        min_ev += 0.012
                    elif low_sample and (agree_sp is not None and int(agree_sp) < 2):
                        min_ev += 0.008
                # Road favorite gate: laying points away demands stronger EV unless backed by sharp money
                if side_lower == "away" and float(market_line_home) > 0.0 and os.getenv("NCAAM_DISABLE_AWAY_FAV_GATE") is None:
                    if has_sharp:
                        min_ev += 0.008
                    elif float(market_line_home) >= 5.5:
                        min_ev += 0.022
                    else:
                        min_ev += 0.014
            except Exception:
                pass
        elif market == "TOTAL" and side_lower == "over" and os.getenv("NCAAM_DISABLE_OVER_DAMP") is None:
            try:
                line_val = abs(float(rec.get("line") or rec.get("market_line") or 0.0))
                if line_val >= 152.0:
                    min_ev += 0.010
                if (is_early or low_sample) and not has_sharp:
                    min_ev += 0.010
                    if agree_tot is not None and int(agree_tot) < 2:
                        min_ev += 0.012
            except Exception:
                pass
        try:
            ms_bumps = ((self._load_adaptive_learning() or {}).get("learned_adjustments") or {}).get("market_side_ev_bump") or {}
            ms_key = f"{market}:{side_lower}"
            if ms_key in ms_bumps:
                min_ev += float(ms_bumps[ms_key])
        except Exception:
            pass

        if ev < min_ev:
            return False

        lb10 = rec.get("win_prob_lb10")
        if lb10 is not None:
            min_lb10 = float(
                os.getenv(
                    "PUBLISH_MIN_WINPROB_LB10",
                    str(getattr(self, "PUBLISH_MIN_WINPROB_LB10", 0.52)),
                )
            )
            # High-EV 3/3-model consensus plays (e.g. +3.5%+ EV with all 3 efficiency feeds agreeing)
            # may clear at 51.0% lb10 so legitimate November edges aren't over-throttled.
            if market == "SPREAD" and ev >= 0.035 and (agree_sp is not None and int(agree_sp) >= 3):
                min_lb10 = min(min_lb10, 0.51)
            if float(lb10) < min_lb10:
                return False

        if (stats.get("n") or 0) < min_n:
            return False

        n = int(stats.get("n") or 0)
        mean = float(stats.get("mean") or 0.0)
        sd = float(stats.get("sd") or 0.0)
        se = (sd / (n ** 0.5)) if (n > 1 and sd > 0) else 0.0
        lb = mean - (self.PUBLISH_CI_Z * se)

        # Standard rule: lower-bound EV must be >= 0
        # Override ("reward mode", option B): allow high-EV, high-edge plays
        # even if the archetype 95% CI lower bound is negative (since sd ~ 0.95 makes
        # 95% CI wide across most bins). Note CAP_SPREAD=2.0 caps spread edge_pts at 2.0,
        # so requiring 2.0 pts + 6% EV previously blocked all standard -110 spread plays.
        override_ev = float(os.getenv('PUBLISH_OVERRIDE_MIN_EV', '0.025'))  # 2.5%
        override_edge = float(os.getenv('PUBLISH_OVERRIDE_MIN_EDGE_PTS', '1.1'))
        
        # Totals have wider variance & worse historical ROI; require >= +4.0% EV override,
        # and demand stronger edge/EV when overriding historically unprofitable TOTAL:over bins.
        if market == 'TOTAL':
            if side_lower == 'over' and mean < -0.03:
                override_ev = float(os.getenv('PUBLISH_OVERRIDE_MIN_EV_TOTAL_OVER', '0.048'))
                override_edge = float(os.getenv('PUBLISH_OVERRIDE_MIN_EDGE_PTS_TOTAL_OVER', '1.8'))
            else:
                override_ev = float(os.getenv('PUBLISH_OVERRIDE_MIN_EV_TOTAL', '0.04'))
                override_edge = float(os.getenv('PUBLISH_OVERRIDE_MIN_EDGE_PTS_TOTAL', '1.3'))

        override_ok = (ev >= override_ev) and (edge_pts >= override_edge) and (n >= min_n)

        if lb < 0.0 and not override_ok:
            return False

        # attach stats for debugging/UI if needed
        rec["archetype"] = {"key": key, "n": n, "mean": mean, "lb95": lb, "override_ok": override_ok}
        return True

    _winprob_calibration: Optional[Dict[str, Any]] = None

    def _load_winprob_calibration(self) -> Dict[str, Any]:
        """Load piecewise-linear win_prob calibration mapping for the current season (DB first, JSON fallback)."""
        if self._winprob_calibration is not None:
            return self._winprob_calibration
        from src.utils.ncaam_season import season_start_date_for_game

        self._winprob_calibration = load_winprob_calibration(
            "winprob_calibration_ncaam",
            "winprob_calibration_ncaam.json",
            min_obs=150,
            min_max_pcal=0.55,
            min_season_start=season_start_date_for_game(),
        )
        return self._winprob_calibration

    def _moneyline_probabilities(self, home_raw: float, is_early_season: bool):
        home = self._calibrate_win_prob(home_raw, is_early_season=is_early_season)
        away = self._calibrate_win_prob(1.0 - home_raw, is_early_season=is_early_season)
        home_prob = home / (home + away) if home + away > 0 else home_raw
        return home_prob, 1.0 - home_prob

    def _calibrate_win_prob(self, p: float, is_early_season: bool = False) -> float:
        """Calibrate raw win probability using empirical-weighted PAVA mapping."""
        try:
            p_val = float(p)
        except Exception:
            return p
        if p_val <= 0.0:
            return 0.0
        if p_val >= 1.0:
            return 1.0
        cal = self._load_winprob_calibration()
        try:
            default_blend = '0.25' if is_early_season else '0.35'
            blend_w = float(os.getenv('NCAAM_WINPROB_CAL_BLEND', default_blend))
            blend_w = max(0.0, min(1.0, blend_w))
        except Exception:
            blend_w = 0.25 if is_early_season else 0.35
        return interpolate_pava_prob(
            p_val,
            cal,
            blend_weight=blend_w,
        )

    _model_conf_params: Optional[Dict[str, Any]] = None

    def _load_model_conf_params(self) -> Dict[str, Any]:
        """Load model uncertainty params (tau) used for confidence intervals."""
        if self._model_conf_params is not None:
            return self._model_conf_params

        path = self._resolve_model_param_path('model_confidence_params_ncaam.json')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self._model_conf_params = json.load(f)
        except Exception:
            self._model_conf_params = {}
        return self._model_conf_params

    def _tau_for_market(
        self,
        market: str,
        *,
        game_month: Optional[int] = None,
        min_rec_games: Optional[int] = None,
        mean_gap: float = 0.0,
        agree_count: Optional[int] = None,
    ) -> float:
        """Return shrinkage-adjusted tau for mu-uncertainty bounds.

        Scales uncertainty higher during early-season low-sample windows and wide
        model-vs-market divergences so November predictions do not over-claim High confidence.
        """
        try:
            if str(os.getenv('ENABLE_MU_UNCERTAINTY_CONF', '1')).strip() == '0':
                return 0.0
            params = self._load_model_conf_params() or {}
            if str(market).upper() == 'TOTAL':
                raw_tau = float(params.get('tau_total') or 0.0)
            else:
                raw_tau = float(params.get('tau_spread') or 0.0)
            if raw_tau <= 0.0:
                return 0.0
            env_shrink = os.getenv('NCAAM_MU_TAU_SHRINKAGE')
            if env_shrink is not None:
                shrinkage = float(env_shrink)
            elif min_rec_games is not None and int(min_rec_games) < 5:
                shrinkage = 0.38
            elif game_month == 11:
                shrinkage = 0.35
            elif game_month == 12:
                shrinkage = 0.30
            else:
                shrinkage = 0.25
            if agree_count is not None and int(agree_count) < 2 and (game_month in (11, 12) or (min_rec_games is not None and int(min_rec_games) < 6)):
                shrinkage *= 1.10
            if float(mean_gap or 0.0) >= 5.0:
                shrinkage *= 1.10
            shrinkage = max(0.10, min(1.0, shrinkage))
            return raw_tau * shrinkage
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
        *,
        game_month: Optional[int] = None,
        min_rec_games: Optional[int] = None,
        mean_gap: float = 0.0,
        agree_count: Optional[int] = None,
    ) -> Dict[str, Optional[float]]:
        """Compute deterministic win_prob p10/p90 bounds from uncertainty in mu.

        NOTE: `mu` and `line` are passed in HOME perspective for SPREAD, and absolute for TOTAL.
        """
        tau = self._tau_for_market(
            market,
            game_month=game_month,
            min_rec_games=min_rec_games,
            mean_gap=mean_gap,
            agree_count=agree_count,
        )
        if not (tau and tau > 0.0 and sigma and sigma > 0.0):
            return {"lb10": None, "ub90": None}

        probs: List[float] = []
        mkt = str(market).upper()
        side = str(side).lower().strip()
        is_early = game_month in (11, 12) or (min_rec_games is not None and int(min_rec_games) < 6)

        z_10 = -1.2815515655446004
        z_90 = 1.2815515655446004
        for z_val in (z_10, z_90):
            mu_true = float(mu) + z_val * float(tau)

            if mkt == 'SPREAD':
                # Home cover probability using same convention as main path
                prob_home_raw = 1.0 - self._normal_cdf(-float(line), -float(mu_true), float(sigma))
                p = prob_home_raw if side == 'home' else 1.0 - prob_home_raw
            else:
                prob_over_raw = 1.0 - self._normal_cdf(float(line), float(mu_true), float(sigma))
                p = prob_over_raw if side == 'over' else 1.0 - prob_over_raw

            probs.append(self._calibrate_win_prob(p, is_early_season=is_early))

        return {
            "lb10": float(min(probs)),
            "ub90": float(max(probs)),
        }

    def _confidence_label_from_winprob(self, lb10: Optional[float], fallback_win_prob: Optional[float] = None) -> str:
        # Use lower-bound if available; else fall back to point estimate.
        p = lb10 if lb10 is not None else fallback_win_prob
        try:
            p = float(p)
        except Exception:
            return 'Low'

        if p >= 0.565:
            return 'High'
        if p >= 0.52:
            return 'Medium'
        return 'Low'

    def _confidence_score_0_100(
        self,
        lb10: Optional[float],
        fallback_win_prob: Optional[float] = None,
        ev_per_unit: Optional[float] = None,
    ) -> int:
        """Compute calibrated 0-100 confidence score aligned with conf_bucket tiers.

        Prevents high-EV longshots or narrow-margin early-season edges from being
        scored >= 80 and misclassified into the High Confidence bucket.
        """
        p_raw = lb10 if lb10 is not None else fallback_win_prob
        try:
            p = max(0.0, min(1.0, float(p_raw)))
        except Exception:
            return 25

        try:
            ev_val = float(ev_per_unit) if ev_per_unit is not None else None
        except Exception:
            ev_val = None

        if ev_val is not None and ev_val <= 0.0:
            return max(15, min(49, int(round(p * 90))))

        if p >= 0.565:
            return min(95, 80 + int(round((p - 0.565) * 150)))
        if p >= 0.52:
            return 55 + int(round(((p - 0.52) / 0.045) * 24))
        return max(15, min(49, int(round(p * 90))))

    def _apply_split_and_injury_signals(
        self,
        recs: List[Dict],
        action_splits: Optional[Dict] = None,
        injury_context: Optional[Dict] = None,
        market_consensus: Optional[Dict] = None,
        relax_gates: bool = False,
    ) -> List[Dict]:
        """Adjust/annotate recommendations with Action Network splits, RLM alignment, and injuries."""
        if not recs:
            return recs

        splits = action_splits or {}
        inj_count = len((injury_context or {}).get("injuries") or [])
        inj_spread = abs(float((injury_context or {}).get("spread_adj") or 0.0))
        inj_total = abs(float((injury_context or {}).get("total_adj") or 0.0))
        mc = market_consensus or {}
        filtered: List[Dict] = []

        for r in recs:
            rec = dict(r)
            mkt = str(rec.get("market") or "").upper()
            side = str(rec.get("side") or "").upper().strip()
            tags = list(rec.get("movement_tags") or [])

            mkt_splits = splits.get(mkt) if isinstance(splits, dict) else None
            if isinstance(mkt_splits, dict) and side in mkt_splits:
                opp_side = (
                    ("AWAY" if side == "HOME" else "HOME")
                    if mkt in ("SPREAD", "ML")
                    else ("UNDER" if side == "OVER" else "OVER")
                )
                pick_s = mkt_splits.get(side) or {}
                opp_s = mkt_splits.get(opp_side) or {}

                pick_bets = pick_s.get("bet_pct")
                pick_money = pick_s.get("handle_pct")
                opp_bets = opp_s.get("bet_pct")
                opp_money = opp_s.get("handle_pct")

                is_sharp_split = (
                    pick_bets is not None
                    and pick_money is not None
                    and float(pick_money) >= 55.0
                    and (float(pick_money) - float(pick_bets)) >= 12.0
                )
                if is_sharp_split:
                    if "sharp_backing" not in tags:
                        tags.append("sharp_backing")

                    # Check line direction relative to pick without chasing heavy steam (>1.5 pts)
                    line_aligned = False
                    if mkt == "SPREAD" and mc.get("open_spread_home") is not None and mc.get("current_spread_home") is not None:
                        move_home = float(mc["current_spread_home"]) - float(mc["open_spread_home"])
                        move_toward_pick = (-move_home) if side == "HOME" else move_home
                        line_aligned = 0.0 <= move_toward_pick <= 1.5
                    elif mkt == "TOTAL" and mc.get("open_total") is not None and mc.get("current_total") is not None:
                        move_t = float(mc["current_total"]) - float(mc["open_total"])
                        line_aligned = (0.0 <= move_t <= 1.5) if side == "OVER" else (-1.5 <= move_t <= 0.0)

                    if line_aligned:
                        if "rlm_confirmed" not in tags:
                            tags.append("rlm_confirmed")
                        if rec.get("win_prob") is not None and rec.get("price") is not None:
                            old_wp = float(rec["win_prob"])
                            new_wp = self._clamp_prob(old_wp + 0.003)
                            new_ev = float(self._calculate_ev(new_wp, rec["price"], self._push_probability(rec.get("line"))))
                            rec["win_prob"] = round(new_wp, 3)
                            if rec.get("win_prob_lb10") is not None:
                                rec["win_prob_lb10"] = round(self._clamp_prob(float(rec["win_prob_lb10"]) + (new_wp - old_wp)), 3)
                            rec["ev"] = round(new_ev, 4)
                            new_kelly = float(self._calculate_kelly(new_wp, rec["price"]))
                            rec["kelly"] = round(new_kelly, 4)
                            if "kelly_pct" in rec:
                                rec["kelly_pct"] = round(new_kelly * 100.0, 2)
                            if "confidence_0_100" in rec:
                                rec["confidence_0_100"] = self._confidence_score_0_100(
                                    rec.get("win_prob_lb10"),
                                    fallback_win_prob=new_wp,
                                    ev_per_unit=new_ev,
                                )
                        else:
                            rec["ev"] = round(float(rec.get("ev") or 0.0) + 0.005, 4)

                if (
                    opp_bets is not None
                    and opp_money is not None
                    and float(opp_money) >= 65.0
                    and float(opp_bets) <= 40.0
                    and (float(opp_money) - float(opp_bets)) >= 20.0
                ):
                    if "contra_sharp_money" not in tags:
                        tags.append("contra_sharp_money")
                    if rec.get("win_prob") is not None and rec.get("price") is not None:
                        old_wp = float(rec["win_prob"])
                        old_ev = float(rec.get("ev") or 0.0)
                        split_gap = float(opp_money) - float(opp_bets)
                        wp_drop = min(0.020, 0.012 + max(0.0, (split_gap - 20.0) * 0.0002))
                        new_wp = self._clamp_prob(old_wp - wp_drop)
                        new_ev = float(self._calculate_ev(new_wp, rec["price"], self._push_probability(rec.get("line"))))
                        penalty = max(0.0, round(old_ev - new_ev, 4))
                        rec["win_prob"] = round(new_wp, 3)
                        if rec.get("win_prob_lb10") is not None:
                            new_lb10 = self._clamp_prob(float(rec["win_prob_lb10"]) + (new_wp - old_wp) - 0.004)
                            rec["win_prob_lb10"] = round(min(new_lb10, 0.548), 3)
                        rec["ev_penalty"] = round(float(rec.get("ev_penalty") or 0.0) + penalty, 4)
                        rec["ev"] = round(new_ev, 4)
                        new_kelly = float(self._calculate_kelly(new_wp, rec["price"]))
                        rec["kelly"] = round(new_kelly, 4)
                        if "kelly_pct" in rec:
                            rec["kelly_pct"] = round(new_kelly * 100.0, 2)
                        if "confidence_0_100" in rec:
                            scored = self._confidence_score_0_100(
                                rec.get("win_prob_lb10"),
                                fallback_win_prob=new_wp,
                                ev_per_unit=new_ev,
                            )
                            rec["confidence_0_100"] = min(int(scored), 74)
                        if rec.get("confidence") == "High":
                            rec["confidence"] = "Medium"
                            rec["confidence_tier"] = "MEDIUM"
                    else:
                        penalty = 0.01
                        rec["ev_penalty"] = round(float(rec.get("ev_penalty") or 0.0) + penalty, 4)
                        rec["ev"] = round(float(rec.get("ev") or 0.0) - penalty, 4)
                        if float(rec.get("ev") or 0.0) <= 0:
                            rec["kelly"] = 0.0
                            if "kelly_pct" in rec:
                                rec["kelly_pct"] = 0.0
                    mkt_name = str(rec.get("market") or rec.get("market_type") or "").upper()
                    if mkt_name == "TOTAL":
                        min_gate_ev = (
                            float(getattr(self, "PUBLISH_MIN_EV_TOTAL_OVER", 0.041))
                            if (side == "OVER" and rec.get("win_prob") is not None and rec.get("price") is not None)
                            else float(self.PUBLISH_MIN_EV_TOTAL)
                        )
                    elif mkt_name == "MONEYLINE":
                        min_gate_ev = float(self.PUBLISH_MIN_EV_ML)
                    else:
                        min_gate_ev = float(self.PUBLISH_MIN_EV)
                    if not relax_gates and float(rec.get("ev") or 0.0) < min_gate_ev:
                        continue
                    if not relax_gates and rec.get("win_prob_lb10") is not None and float(rec["win_prob_lb10"]) < float(getattr(self, "PUBLISH_MIN_WINPROB_LB10", 0.52)):
                        continue

            if inj_count > 0 and "injury_report_active" not in tags:
                tags.append("injury_report_active")
            if (inj_spread >= 0.4 or inj_total >= 0.4) and "injury_line_adjusted" not in tags:
                tags.append("injury_line_adjusted")

            if tags:
                rec["movement_tags"] = tags
            filtered.append({k: v for k, v in rec.items() if not str(k).startswith("_")})

        return filtered

    def _generate_recommendations(
        self,
        mu_s,
        sig_s,
        mu_t,
        sig_t,
        snap,
        event,
        torvik_view: Optional[Dict[str, Any]] = None,
        relax_gates: bool = False,
        action_splits: Optional[Dict] = None,
        injury_context: Optional[Dict] = None,
        model_ctx: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        recs: List[Dict[str, Any]] = []
        if not snap:
            return recs

        mctx = model_ctx or {}
        g_month = mctx.get("game_month")
        g_min_games = mctx.get("min_rec_games")
        g_is_early = bool(mctx.get("is_early_season")) if "is_early_season" in mctx else (g_month in (11, 12))
        g_agree_sp = mctx.get("agree_count")
        g_agree_tot = mctx.get("agree_count_total")
        g_gap_sp = float(mctx.get("mean_sp_gap") or 0.0)
        g_gap_tot = float(mctx.get("mean_tot_gap") or 0.0)

        # Torvik availability: do not hard-require; used to tighten gates.
        torvik_ok = True
        try:
            if not torvik_view:
                torvik_ok = False
            elif str(torvik_view.get("lean") or "").lower().strip() in ("no data", ""):
                torvik_ok = False
        except Exception:
            torvik_ok = False

        def _spread_cover_prob_home(mu_home: float, sigma: float, line_home: float) -> float:
            """No-push conditional P(Home covers) given home-perspective mu and home spread line."""
            return 1.0 - self._normal_cdf(-float(line_home), -float(mu_home), float(sigma))

        def _total_over_prob(mu_total: float, sigma: float, total_line: float) -> float:
            return 1.0 - self._normal_cdf(float(total_line), float(mu_total), float(sigma))

        def _format_sanity_block(reasons: List[str], score: int) -> str:
            labels = []
            for item in (reasons or []):
                text = str(item or "")
                if text.startswith("prob_gap="):
                    labels.append("model and sportsbook odds differ too much")
                elif text.startswith("odds_outlier_gap="):
                    labels.append("one sportsbook price looks out of line")
                elif text.startswith("steam_block=") or text.startswith("steam_against="):
                    labels.append("line already moved against this pick")
                elif text.startswith("reverse_steam="):
                    labels.append("market steamed the opposite way")
                elif text.startswith("steam_reason="):
                    labels.append(text.split("=", 1)[1])
            if not labels:
                labels.append("risk guardrail triggered")
            return "Held for safety: " + "; ".join(dict.fromkeys(labels))

        def _sanity_adjust(market: str, side: str, win_prob: float, ev: float, mc: Optional[Dict[str, Any]], eval_price: Optional[int] = None, bet_line: Optional[float] = None):
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

            # Sharp offshore/benchmark check (Pinnacle / LowVig / BetOnline vs US retail line)
            try:
                sharp_edge_pts = self._compute_sharp_edge_pts(
                    market,
                    side,
                    bet_line,
                    snap.get('_sharp_spread_home') if isinstance(snap, dict) else None,
                    snap.get('_sharp_total') if isinstance(snap, dict) else None,
                )
                if sharp_edge_pts is not None:
                    if sharp_edge_pts >= 0.5:
                        reasons.append("sharp_price_edge")
                    elif sharp_edge_pts <= -1.0:
                        score += 1
                        reasons.append("contra_sharp_line")
                        sigma_mult *= 1.12
                        ev_penalty += float(os.getenv('CONTRA_SHARP_EV_PENALTY', '0.015'))
            except Exception:
                pass

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

                eff_best = eval_price if eval_price is not None else best_price
                ip = implied_prob_american(eff_best)
                if ip is not None:
                    dp = float(win_prob) - float(ip)
                    if abs(dp) >= float(os.getenv('SANITY_MAX_PROB_GAP', '0.18')):
                        score += 2
                        reasons.append(f"prob_gap={dp:+.2f}")
                        sigma_mult *= 1.35

                # If best price is a wild outlier vs consensus, it's often bad ingest.
                if cons_price is not None and eff_best is not None:
                    ip_best = implied_prob_american(eff_best)
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
                            reverse_against = (mv < 0) if s == 'away' else (mv > 0)
                            if reverse_against and abs(mv) >= float(os.getenv('SANITY_REVERSE_STEAM_WARN', '1.5')):
                                reasons.append(f"reverse_steam={mv:+.1f}")
                                sigma_mult *= 1.12
                                ev_penalty += float(os.getenv('REVERSE_STEAM_EV_PENALTY', '0.008'))
                            if reverse_against and abs(mv) >= float(os.getenv('SANITY_REVERSE_STEAM_BLOCK', '2.5')):
                                score += 1
                                sigma_mult *= 1.15
                                ev_penalty += float(os.getenv('REVERSE_STEAM_EV_PENALTY_BLOCK', '0.012'))
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
                            reverse_against = (mv < 0) if s == 'over' else (mv > 0)
                            if reverse_against and abs(mv) >= float(os.getenv('SANITY_REVERSE_STEAM_WARN_TOTAL', '2.0')):
                                reasons.append(f"reverse_steam={mv:+.1f}")
                                sigma_mult *= 1.12
                                ev_penalty += float(os.getenv('REVERSE_STEAM_EV_PENALTY_TOTAL', '0.01'))
                            if reverse_against and abs(mv) >= float(os.getenv('SANITY_REVERSE_STEAM_BLOCK_TOTAL', '3.0')):
                                score += 1
                                sigma_mult *= 1.15
                                ev_penalty += float(os.getenv('REVERSE_STEAM_EV_PENALTY_BLOCK_TOTAL', '0.015'))
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


        def _clean_main_price(raw_p, default: int = -110) -> int:
            try:
                if raw_p is None:
                    return int(default)
                p = int(round(float(raw_p)))
            except Exception:
                return int(default)
            if abs(p) < 100 or p < -165 or p > 145:
                return int(default)
            return p

        from src.utils.ncaam_quotes import recent_retail_quote
        quote_time = snap.get('_quote_as_of') or datetime.now(timezone.utc)

        def executable(quote, target):
            if not quote or not recent_retail_quote(quote, quote_time) or target is None or quote.get("line_value") is None:
                return False
            try:
                price = int(quote["price"])
                return _clean_main_price(price, default=0) == price and price != 0 and abs(float(quote["line_value"]) - float(target)) <= 1
            except (KeyError, TypeError, ValueError):
                return False

        candidates_eval: List[Dict[str, Any]] = []

        # --- Spread ---
        line_s = snap.get("spread_home")
        price_home = _clean_main_price(snap.get("spread_price_home", -110))
        best_away = snap.get("_best_spread_away", {})
        price_away = _clean_main_price(best_away.get("price", -110) if best_away else -110)
        book_consensus = snap.get("book_spread", "Consensus")

        line_s_valid = False
        if line_s is not None:
            try:
                line_s_valid = math.isfinite(float(line_s)) and abs(float(line_s)) <= 55.0
            except Exception:
                line_s_valid = False

        if line_s_valid:

            # Use consensus for model math, and evaluate prob/bounds/EV at the exact bettable
            # line & price (constrained near consensus so stale alt lines never distort EV).
            market_line_s = float(line_s)
            fair_line_s = float(mu_s)

            best_home = snap.get('_best_spread_home') or {}
            best_home_line = best_home.get('line_value')
            best_away_line = (best_away or {}).get('line_value')

            line_home_bet = float(
                best_home_line
                if (best_home_line is not None and abs(float(best_home_line) - market_line_s) <= 1.0)
                else market_line_s
            )
            line_away_bet = float(
                best_away_line
                if (best_away_line is not None and abs(float(best_away_line) - (-market_line_s)) <= 1.0)
                else -market_line_s
            )
            price_home_bet = _clean_main_price(best_home.get('price'), default=price_home)
            price_away_bet = _clean_main_price(best_away.get('price') if best_away else None, default=price_away)

            prob_home = _spread_cover_prob_home(mu_s, sig_s, line_home_bet)
            prob_home_cal = self._calibrate_win_prob(prob_home, is_early_season=g_is_early)
            push_prob_home = self._push_probability(float(line_home_bet))
            ev_home = self._calculate_ev(prob_home_cal, price_home_bet, push_prob=push_prob_home)
            kelly_home = self._calculate_kelly(prob_home_cal, price_home_bet)

            prob_away = 1.0 - _spread_cover_prob_home(mu_s, sig_s, -float(line_away_bet))
            prob_away_cal = self._calibrate_win_prob(prob_away, is_early_season=g_is_early)
            push_prob_away = self._push_probability(float(line_away_bet))
            ev_away = self._calculate_ev(prob_away_cal, price_away_bet, push_prob=push_prob_away)
            kelly_away = self._calculate_kelly(prob_away_cal, price_away_bet)

            edge_pts_home = abs(fair_line_s - float(line_home_bet))
            edge_pts_away = abs(fair_line_s - (-float(line_away_bet)))

            bounds_home = self._confidence_bounds_from_mu_uncertainty(
                market='SPREAD',
                mu=float(mu_s),
                sigma=float(sig_s),
                line=float(line_home_bet),
                side='home',
                game_month=g_month,
                min_rec_games=g_min_games,
                mean_gap=g_gap_sp,
                agree_count=g_agree_sp,
            )

            # Top-down lagging-book line-shopping edge (best book beats market consensus by >= 1.0 pt)
            home_book_edge_pts = round(float(line_home_bet) - float(market_line_s), 2)
            away_book_edge_pts = round(float(line_away_bet) - (-float(market_line_s)), 2)

            cand_home = {
                "market": "SPREAD",
                "side": "home",
                "team": event["home_team"],
                "line": line_home_bet,
                "price": price_home_bet,
                "raw_win_prob": prob_home,
                "prob": round(prob_home_cal, 3),
                "win_prob": round(prob_home_cal, 3),
                "win_prob_lb10": (round(float(bounds_home.get('lb10')), 3) if bounds_home.get('lb10') is not None else None),
                "win_prob_ub90": (round(float(bounds_home.get('ub90')), 3) if bounds_home.get('ub90') is not None else None),
                "ev": float(round(ev_home, 4)),
                "kelly": float(round(kelly_home, 4)),
                "book": best_home.get('book') or book_consensus,
                "quote_captured_at": str(best_home.get("captured_at") or "") or None,
                "edge_points": float(round(edge_pts_home, 2)),
                "market_line_edge_pts": home_book_edge_pts,
                "movement_tags": (["lagging_book_edge"] if home_book_edge_pts >= 1.0 else []),
                "sharp_book": snap.get("_sharp_spread_book"),
                "sharp_line": self._sharp_line_for_side("SPREAD", "home", snap.get("_sharp_spread_home"), snap.get("_sharp_total")),
                "sharp_edge_pts": self._compute_sharp_edge_pts("SPREAD", "home", line_home_bet, snap.get("_sharp_spread_home"), snap.get("_sharp_total")),
                "_is_early_season": g_is_early,
                "_min_rec_games": g_min_games,
                "_agree_count": g_agree_sp,
                "_agree_count_total": g_agree_tot,
            }

            bounds_away = self._confidence_bounds_from_mu_uncertainty(
                market='SPREAD',
                mu=float(mu_s),
                sigma=float(sig_s),
                line=-float(line_away_bet),
                side='away',
                game_month=g_month,
                min_rec_games=g_min_games,
                mean_gap=g_gap_sp,
                agree_count=g_agree_sp,
            )

            cand_away = {
                "market": "SPREAD",
                "side": "away",
                "team": event["away_team"],
                "line": line_away_bet,
                "price": price_away_bet,
                "raw_win_prob": prob_away,
                "prob": round(prob_away_cal, 3),
                "win_prob": round(prob_away_cal, 3),
                "win_prob_lb10": (round(float(bounds_away.get('lb10')), 3) if bounds_away.get('lb10') is not None else None),
                "win_prob_ub90": (round(float(bounds_away.get('ub90')), 3) if bounds_away.get('ub90') is not None else None),
                "ev": float(round(ev_away, 4)),
                "kelly": float(round(kelly_away, 4)),
                "book": (best_away or {}).get('book') or book_consensus,
                "quote_captured_at": str((best_away or {}).get("captured_at") or "") or None,
                "edge_points": float(round(edge_pts_away, 2)),
                "market_line_edge_pts": away_book_edge_pts,
                "movement_tags": (["lagging_book_edge"] if away_book_edge_pts >= 1.0 else []),
                "sharp_book": snap.get("_sharp_spread_book"),
                "sharp_line": self._sharp_line_for_side("SPREAD", "away", snap.get("_sharp_spread_home"), snap.get("_sharp_total")),
                "sharp_edge_pts": self._compute_sharp_edge_pts("SPREAD", "away", line_away_bet, snap.get("_sharp_spread_home"), snap.get("_sharp_total")),
                "_is_early_season": g_is_early,
                "_min_rec_games": g_min_games,
                "_agree_count": g_agree_sp,
                "_agree_count_total": g_agree_tot,
            }

            # Choose the higher-EV side, then gate it.
            choices = [candidate for candidate, quote, target in (
                (cand_home, best_home, market_line_s), (cand_away, best_away, -market_line_s)
            ) if executable(quote, target)]
            best = max(choices, key=lambda c: c["ev"], default=None)
            if best:
                candidates_eval.append(best)
            if best and (relax_gates or self._passes_publish_gates(best, market_line_home=market_line_s, torvik_ok=torvik_ok)):
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
                        score, reasons, sigma_mult, ev_penalty = _sanity_adjust(
                            'SPREAD',
                            str(best.get('side') or ''),
                            float(best.get('win_prob') or 0.5),
                            float(best.get('ev') or 0.0),
                            mc,
                            eval_price=best.get('price'),
                            bet_line=best.get('line'),
                        )
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
                            snap['_no_bet_reason_spread'] = _format_sanity_block(reasons, score)
                        else:
                            # Soft-adjust: inflate uncertainty + degrade EV
                            ev_raw = float(best.get('ev') or 0.0)
                            ev_adj = ev_raw - float(ev_penalty or 0.0)
                            merged_tags = list(dict.fromkeys(list(best.get('movement_tags') or []) + list(reasons or [])))
                            out = {**best,
                                   'steam_blocked': False,
                                   'sanity_score': score,
                                   'sanity_reasons': reasons,
                                   'sigma_mult': float(sigma_mult or 1.0),
                                   'ev_raw': float(round(ev_raw, 4)),
                                   'ev_penalty': float(round(ev_penalty or 0.0, 4)),
                                   'movement_tags': merged_tags}

                            # Recompute win_prob, ev, kelly, and bounds with inflated sigma (movement/disagreement => more uncertainty)
                            try:
                                out_side = str(out.get('side') or '').lower()
                                eff_sigma_mult = float(out.get('sigma_mult') or 1.0)
                                sig_s_adj = float(sig_s) * eff_sigma_mult
                                if eff_sigma_mult > 1.0:
                                    if out_side == 'home':
                                        p_raw_adj = _spread_cover_prob_home(mu_s, sig_s_adj, float(out['line']))
                                    else:
                                        p_raw_adj = 1.0 - _spread_cover_prob_home(mu_s, sig_s_adj, -float(out['line']))
                                    p_cal_adj = self._calibrate_win_prob(p_raw_adj, is_early_season=g_is_early)
                                    push_p_adj = self._push_probability(float(out['line']))
                                    ev_recomp = float(self._calculate_ev(p_cal_adj, int(out['price']), push_prob=push_p_adj))
                                    ev_adj = min(ev_raw, ev_recomp) - float(ev_penalty or 0.0)
                                    out['raw_win_prob'] = p_raw_adj
                                    out['prob'] = round(p_cal_adj, 3)
                                    out['win_prob'] = round(p_cal_adj, 3)
                                    out['kelly'] = float(round(self._calculate_kelly(p_cal_adj, int(out['price'])), 4))
                                home_persp_line = float(out['line']) if out_side == 'home' else -float(out['line'])
                                b2 = self._confidence_bounds_from_mu_uncertainty(
                                    market='SPREAD',
                                    mu=float(mu_s),
                                    sigma=sig_s_adj,
                                    line=home_persp_line,
                                    side=out_side,
                                    game_month=g_month,
                                    min_rec_games=g_min_games,
                                    mean_gap=g_gap_sp,
                                    agree_count=g_agree_sp,
                                )
                                if b2:
                                    out['win_prob_lb10'] = (round(float(b2.get('lb10')), 3) if b2.get('lb10') is not None else out.get('win_prob_lb10'))
                                    out['win_prob_ub90'] = (round(float(b2.get('ub90')), 3) if b2.get('ub90') is not None else out.get('win_prob_ub90'))
                            except Exception:
                                pass

                            out['ev'] = float(round(ev_adj, 4))
                            if relax_gates or self._passes_publish_gates(out, market_line_home=market_line_s, torvik_ok=torvik_ok):
                                recs.append(out)
                    else:
                        recs.append({**best, 'steam_blocked': False})

        # --- Total ---
        line_t = snap.get("total")
        best_over = snap.get("_best_total_over")
        best_under = snap.get("_best_total_under")

        price_tot_cons = _clean_main_price(snap.get("total_over_price", -110))
        price_over = _clean_main_price(best_over.get("price") if isinstance(best_over, dict) else None, default=price_tot_cons)
        price_under = _clean_main_price(best_under.get("price") if isinstance(best_under, dict) else None, default=-110)
        book_over = best_over["book"] if best_over else snap.get("book_total", "Consensus")
        book_under = best_under["book"] if best_under else snap.get("book_total", "Consensus")

        line_t_valid = False
        if line_t is not None and mu_t is not None:
            try:
                line_t_valid = math.isfinite(float(line_t)) and (85.0 <= float(line_t) <= 215.0)
            except Exception:
                line_t_valid = False

        if line_t_valid:
            market_line_t = float(line_t)
            fair_line_t = float(mu_t)

            over_raw_line = best_over.get("line_value") if isinstance(best_over, dict) else None
            under_raw_line = best_under.get("line_value") if isinstance(best_under, dict) else None
            line_over_bet = (
                float(over_raw_line)
                if (over_raw_line is not None and abs(float(over_raw_line) - market_line_t) <= 1.0)
                else market_line_t
            )
            line_under_bet = (
                float(under_raw_line)
                if (under_raw_line is not None and abs(float(under_raw_line) - market_line_t) <= 1.0)
                else market_line_t
            )

            prob_over_raw = 1.0 - self._normal_cdf(line_over_bet, mu_t, sig_t)
            prob_under_raw = self._normal_cdf(line_under_bet, mu_t, sig_t)
            push_prob_over = self._push_probability(line_over_bet)
            push_prob_under = self._push_probability(line_under_bet)

            prob_over_cal = self._calibrate_win_prob(prob_over_raw, is_early_season=g_is_early)
            prob_under_cal = self._calibrate_win_prob(prob_under_raw, is_early_season=g_is_early)

            ev_over = self._calculate_ev(prob_over_cal, price_over, push_prob=push_prob_over)
            kelly_over = self._calculate_kelly(prob_over_cal, price_over)
            ev_under = self._calculate_ev(prob_under_cal, price_under, push_prob=push_prob_under)
            kelly_under = self._calculate_kelly(prob_under_cal, price_under)

            edge_pts_over = abs(fair_line_t - line_over_bet)
            edge_pts_under = abs(fair_line_t - line_under_bet)

            bounds_over = self._confidence_bounds_from_mu_uncertainty(
                market='TOTAL',
                mu=float(mu_t),
                sigma=float(sig_t),
                line=float(line_over_bet),
                side='over',
                game_month=g_month,
                min_rec_games=g_min_games,
                mean_gap=g_gap_tot,
                agree_count=g_agree_tot,
            )

            cand_over = {
                "market": "TOTAL",
                "side": "over",
                "line": line_over_bet,
                "price": int(price_over),
                "raw_win_prob": prob_over_raw,
                "prob": round(prob_over_cal, 3),
                "win_prob": round(prob_over_cal, 3),
                "win_prob_lb10": (round(float(bounds_over.get('lb10')), 3) if bounds_over.get('lb10') is not None else None),
                "win_prob_ub90": (round(float(bounds_over.get('ub90')), 3) if bounds_over.get('ub90') is not None else None),
                "ev": float(round(ev_over, 4)),
                "kelly": float(round(kelly_over, 4)),
                "book": book_over,
                "quote_captured_at": str((best_over or {}).get("captured_at") or "") or None,
                "edge_points": float(round(edge_pts_over, 2)),
                "sharp_book": snap.get("_sharp_total_book"),
                "sharp_line": self._sharp_line_for_side("TOTAL", "over", snap.get("_sharp_spread_home"), snap.get("_sharp_total")),
                "sharp_edge_pts": self._compute_sharp_edge_pts("TOTAL", "over", line_over_bet, snap.get("_sharp_spread_home"), snap.get("_sharp_total")),
                "_is_early_season": g_is_early,
                "_min_rec_games": g_min_games,
                "_agree_count": g_agree_sp,
                "_agree_count_total": g_agree_tot,
            }

            bounds_under = self._confidence_bounds_from_mu_uncertainty(
                market='TOTAL',
                mu=float(mu_t),
                sigma=float(sig_t),
                line=float(line_under_bet),
                side='under',
                game_month=g_month,
                min_rec_games=g_min_games,
                mean_gap=g_gap_tot,
                agree_count=g_agree_tot,
            )

            cand_under = {
                "market": "TOTAL",
                "side": "under",
                "line": line_under_bet,
                "price": int(price_under),
                "raw_win_prob": prob_under_raw,
                "prob": round(prob_under_cal, 3),
                "win_prob": round(prob_under_cal, 3),
                "win_prob_lb10": (round(float(bounds_under.get('lb10')), 3) if bounds_under.get('lb10') is not None else None),
                "win_prob_ub90": (round(float(bounds_under.get('ub90')), 3) if bounds_under.get('ub90') is not None else None),
                "ev": float(round(ev_under, 4)),
                "kelly": float(round(kelly_under, 4)),
                "book": book_under,
                "quote_captured_at": str((best_under or {}).get("captured_at") or "") or None,
                "edge_points": float(round(edge_pts_under, 2)),
                "sharp_book": snap.get("_sharp_total_book"),
                "sharp_line": self._sharp_line_for_side("TOTAL", "under", snap.get("_sharp_spread_home"), snap.get("_sharp_total")),
                "sharp_edge_pts": self._compute_sharp_edge_pts("TOTAL", "under", line_under_bet, snap.get("_sharp_spread_home"), snap.get("_sharp_total")),
                "_is_early_season": g_is_early,
                "_min_rec_games": g_min_games,
                "_agree_count": g_agree_sp,
                "_agree_count_total": g_agree_tot,
            }

            choices = [candidate for candidate, quote in ((cand_over, best_over), (cand_under, best_under))
                       if executable(quote, market_line_t)]
            best = max(choices, key=lambda c: c["ev"], default=None)
            if best:
                candidates_eval.append(best)
            if best and (relax_gates or self._passes_publish_gates(best, market_line_home=None, torvik_ok=torvik_ok)):
                reason = self._steam_block_reason('TOTAL', str(best.get('side') or ''), snap.get('_market_consensus') if isinstance(snap, dict) else None, snap)
                steam_hard_block = str(os.getenv('STEAM_HARD_BLOCK', '0')).strip() not in ('0', 'false', 'False', '')
                if reason and steam_hard_block:
                    if isinstance(snap, dict):
                        snap['_no_bet_reason_total'] = reason
                else:
                    sanity_on = str(os.getenv('SANITY_ENABLE', '1')).strip() not in ('0', 'false', 'False', '')
                    if sanity_on and isinstance(snap, dict):
                        mc = snap.get('_market_consensus')
                        score, reasons, sigma_mult, ev_penalty = _sanity_adjust(
                            'TOTAL',
                            str(best.get('side') or ''),
                            float(best.get('win_prob') or 0.5),
                            float(best.get('ev') or 0.0),
                            mc,
                            eval_price=best.get('price'),
                            bet_line=best.get('line'),
                        )
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
                            snap['_no_bet_reason_total'] = _format_sanity_block(reasons, score)
                        else:
                            ev_raw = float(best.get('ev') or 0.0)
                            ev_adj = ev_raw - float(ev_penalty or 0.0)
                            merged_tags = list(dict.fromkeys(list(best.get('movement_tags') or []) + list(reasons or [])))
                            out = {**best,
                                   'steam_blocked': False,
                                   'sanity_score': score,
                                   'sanity_reasons': reasons,
                                   'sigma_mult': float(sigma_mult or 1.0),
                                   'ev_raw': float(round(ev_raw, 4)),
                                   'ev_penalty': float(round(ev_penalty or 0.0, 4)),
                                   'movement_tags': merged_tags}

                            try:
                                out_side = str(out.get('side') or '').lower()
                                eff_sigma_mult = float(out.get('sigma_mult') or 1.0)
                                sig_t_adj = float(sig_t) * eff_sigma_mult
                                if eff_sigma_mult > 1.0:
                                    if out_side == 'over':
                                        p_raw_adj = 1.0 - self._normal_cdf(float(out['line']), float(mu_t), sig_t_adj)
                                    else:
                                        p_raw_adj = self._normal_cdf(float(out['line']), float(mu_t), sig_t_adj)
                                    p_cal_adj = self._calibrate_win_prob(p_raw_adj, is_early_season=g_is_early)
                                    push_p_adj = self._push_probability(float(out['line']))
                                    ev_recomp = float(self._calculate_ev(p_cal_adj, int(out['price']), push_prob=push_p_adj))
                                    ev_adj = min(ev_raw, ev_recomp) - float(ev_penalty or 0.0)
                                    out['raw_win_prob'] = p_raw_adj
                                    out['prob'] = round(p_cal_adj, 3)
                                    out['win_prob'] = round(p_cal_adj, 3)
                                    out['kelly'] = float(round(self._calculate_kelly(p_cal_adj, int(out['price'])), 4))
                                b2 = self._confidence_bounds_from_mu_uncertainty(
                                    market='TOTAL',
                                    mu=float(mu_t),
                                    sigma=sig_t_adj,
                                    line=float(out['line']),
                                    side=str(out.get('side') or ''),
                                    game_month=g_month,
                                    min_rec_games=g_min_games,
                                    mean_gap=g_gap_tot,
                                    agree_count=g_agree_tot,
                                )
                                if b2:
                                    out['win_prob_lb10'] = (round(float(b2.get('lb10')), 3) if b2.get('lb10') is not None else out.get('win_prob_lb10'))
                                    out['win_prob_ub90'] = (round(float(b2.get('ub90')), 3) if b2.get('ub90') is not None else out.get('win_prob_ub90'))
                            except Exception:
                                pass

                            out['ev'] = float(round(ev_adj, 4))
                            if relax_gates or self._passes_publish_gates(out, market_line_home=None, torvik_ok=torvik_ok):
                                recs.append(out)
                    else:
                        recs.append({**best, 'steam_blocked': False})

        # --- First-Half (1H) Markets (SPREAD_1H & TOTAL_1H) ---
        # Anchor 1H fair line to the 1H market median + half of the model's true full-game edge
        # (prevents blowout favorites whose 1H share is ~55% from generating fake 1H underdog edges).
        import statistics as _stats
        raw_snaps_list = [
            s for s in ((snap.get('_raw_snaps') or []) if isinstance(snap, dict) else [])
            if recent_retail_quote(s, quote_time) and s.get('price') is not None
            and _clean_main_price(s['price'], default=0) != 0
        ]
        if raw_snaps_list and mu_s is not None and sig_s is not None and line_s_valid:
            try:
                sp1h_home = [s for s in raw_snaps_list if str(s.get('market_type') or '').upper() == 'SPREAD_1H' and str(s.get('side') or '').upper() == 'HOME' and s.get('line_value') is not None]
                sp1h_away = [s for s in raw_snaps_list if str(s.get('market_type') or '').upper() == 'SPREAD_1H' and str(s.get('side') or '').upper() == 'AWAY' and s.get('line_value') is not None]
                if sp1h_home or sp1h_away:
                    h1_home_vals = [float(s['line_value']) for s in sp1h_home] + [-float(s['line_value']) for s in sp1h_away]
                    mkt_1h_home = _stats.median(h1_home_vals)
                    fg_edge_home = float(mu_s) - float(line_s)
                    mu_1h_s = mkt_1h_home + (0.52 * fg_edge_home)
                    sig_1h_s = max(6.0, float(sig_s) * 0.72)
                    best_1h_cands = []
                    if sp1h_home:
                        bh = max(sp1h_home, key=lambda x: (float(x['line_value']), int(x.get('price') or -110)))
                        lh = float(bh['line_value'])
                        if abs(lh - mkt_1h_home) <= 1.5:
                            ph = _clean_main_price(bh.get('price'), default=-110)
                            raw_h1 = _spread_cover_prob_home(mu_1h_s, sig_1h_s, lh)
                            prob_h1 = self._calibrate_win_prob(raw_h1, is_early_season=g_is_early)
                            ev_h1 = self._calculate_ev(prob_h1, ph, push_prob=self._push_probability(lh))
                            edge_h1 = lh - mu_1h_s
                            if ev_h1 >= 0.03 and prob_h1 >= 0.54 and edge_h1 >= 1.2:
                                best_1h_cands.append({
                                    "market": "SPREAD_1H", "side": "home", "team": f"{event['home_team']} 1H",
                                    "raw_win_prob": raw_h1, "line": lh, "price": ph, "prob": round(prob_h1, 3), "win_prob": round(prob_h1, 3),
                                    "fair_line_1h_home": round(mu_1h_s, 1),
                                    "win_prob_lb10": round(max(0.50, prob_h1 - 0.02), 3),
                                    "win_prob_ub90": round(min(0.95, prob_h1 + 0.02), 3),
                                    "ev": float(round(ev_h1, 4)), "kelly": float(round(self._calculate_kelly(prob_h1, ph), 4)),
                                    "quote_captured_at": str(bh.get("captured_at") or "") or None,
                                    "book": bh.get('book') or 'Consensus', "edge_points": float(round(edge_h1, 2)),
                                    "movement_tags": ["first_half_market"], "_is_early_season": g_is_early,
                                    "_agree_count": g_agree_sp, "_agree_count_total": g_agree_tot,
                                })
                    if sp1h_away:
                        ba = max(sp1h_away, key=lambda x: (float(x['line_value']), int(x.get('price') or -110)))
                        la = float(ba['line_value'])
                        if abs(la - (-mkt_1h_home)) <= 1.5:
                            pa = _clean_main_price(ba.get('price'), default=-110)
                            raw_a1 = 1.0 - _spread_cover_prob_home(mu_1h_s, sig_1h_s, -la)
                            prob_a1 = self._calibrate_win_prob(raw_a1, is_early_season=g_is_early)
                            ev_a1 = self._calculate_ev(prob_a1, pa, push_prob=self._push_probability(la))
                            edge_a1 = la - (-mu_1h_s)
                            if ev_a1 >= 0.03 and prob_a1 >= 0.54 and edge_a1 >= 1.2:
                                best_1h_cands.append({
                                    "market": "SPREAD_1H", "side": "away", "team": f"{event['away_team']} 1H",
                                    "raw_win_prob": raw_a1, "line": la, "price": pa, "prob": round(prob_a1, 3), "win_prob": round(prob_a1, 3),
                                    "fair_line_1h_home": round(mu_1h_s, 1),
                                    "win_prob_lb10": round(max(0.50, prob_a1 - 0.02), 3),
                                    "win_prob_ub90": round(min(0.95, prob_a1 + 0.02), 3),
                                    "ev": float(round(ev_a1, 4)), "kelly": float(round(self._calculate_kelly(prob_a1, pa), 4)),
                                    "quote_captured_at": str(ba.get("captured_at") or "") or None,
                                    "book": ba.get('book') or 'Consensus', "edge_points": float(round(edge_a1, 2)),
                                    "movement_tags": ["first_half_market"], "_is_early_season": g_is_early,
                                    "_agree_count": g_agree_sp, "_agree_count_total": g_agree_tot,
                                })
                    if best_1h_cands:
                        recs.append(max(best_1h_cands, key=lambda c: c['ev']))
            except Exception:
                pass

        if raw_snaps_list and mu_t is not None and sig_t is not None and line_t_valid:
            try:
                tot1h_over = [s for s in raw_snaps_list if str(s.get('market_type') or '').upper() == 'TOTAL_1H' and str(s.get('side') or '').upper() == 'OVER' and s.get('line_value') is not None]
                tot1h_under = [s for s in raw_snaps_list if str(s.get('market_type') or '').upper() == 'TOTAL_1H' and str(s.get('side') or '').upper() == 'UNDER' and s.get('line_value') is not None]
                if tot1h_over or tot1h_under:
                    h1_tot_vals = [float(s['line_value']) for s in (tot1h_over + tot1h_under)]
                    mkt_1h_tot = _stats.median(h1_tot_vals)
                    fg_edge_tot = float(mu_t) - float(line_t)
                    mu_1h_t = mkt_1h_tot + (0.48 * fg_edge_tot)
                    sig_1h_t = max(7.5, float(sig_t) * 0.70)
                    best_1h_tot = []
                    if tot1h_under:
                        bu = max(tot1h_under, key=lambda x: (float(x['line_value']), int(x.get('price') or -110)))
                        lu = float(bu['line_value'])
                        if abs(lu - mkt_1h_tot) <= 2.0:
                            pu = _clean_main_price(bu.get('price'), default=-110)
                            raw_u1 = self._normal_cdf(lu, mu_1h_t, sig_1h_t)
                            prob_u1 = self._calibrate_win_prob(raw_u1, is_early_season=g_is_early)
                            ev_u1 = self._calculate_ev(prob_u1, pu, push_prob=self._push_probability(lu))
                            edge_u1 = lu - mu_1h_t
                            if ev_u1 >= 0.038 and prob_u1 >= 0.545 and edge_u1 >= 1.5:
                                best_1h_tot.append({
                                    "market": "TOTAL_1H", "side": "under", "team": "1H UNDER",
                                    "raw_win_prob": raw_u1, "line": lu, "price": pu, "prob": round(prob_u1, 3), "win_prob": round(prob_u1, 3),
                                    "fair_line_1h_total": round(mu_1h_t, 1),
                                    "win_prob_lb10": round(max(0.50, prob_u1 - 0.02), 3),
                                    "win_prob_ub90": round(min(0.95, prob_u1 + 0.02), 3),
                                    "ev": float(round(ev_u1, 4)), "kelly": float(round(self._calculate_kelly(prob_u1, pu), 4)),
                                    "quote_captured_at": str(bu.get("captured_at") or "") or None,
                                    "book": bu.get('book') or 'Consensus', "edge_points": float(round(edge_u1, 2)),
                                    "movement_tags": ["first_half_market"], "_is_early_season": g_is_early,
                                    "_agree_count": g_agree_sp, "_agree_count_total": g_agree_tot,
                                })
                    if tot1h_over:
                        bo = min(tot1h_over, key=lambda x: (float(x['line_value']), -int(x.get('price') or -110)))
                        lo = float(bo['line_value'])
                        if abs(lo - mkt_1h_tot) <= 2.0:
                            po = _clean_main_price(bo.get('price'), default=-110)
                            raw_o1 = 1.0 - self._normal_cdf(lo, mu_1h_t, sig_1h_t)
                            prob_o1 = self._calibrate_win_prob(raw_o1, is_early_season=g_is_early)
                            ev_o1 = self._calculate_ev(prob_o1, po, push_prob=self._push_probability(lo))
                            edge_o1 = mu_1h_t - lo
                            if ev_o1 >= 0.045 and prob_o1 >= 0.55 and edge_o1 >= 1.8:
                                best_1h_tot.append({
                                    "market": "TOTAL_1H", "side": "over", "team": "1H OVER",
                                    "raw_win_prob": raw_o1, "line": lo, "price": po, "prob": round(prob_o1, 3), "win_prob": round(prob_o1, 3),
                                    "fair_line_1h_total": round(mu_1h_t, 1),
                                    "win_prob_lb10": round(max(0.50, prob_o1 - 0.02), 3),
                                    "win_prob_ub90": round(min(0.95, prob_o1 + 0.02), 3),
                                    "ev": float(round(ev_o1, 4)), "kelly": float(round(self._calculate_kelly(prob_o1, po), 4)),
                                    "quote_captured_at": str(bo.get("captured_at") or "") or None,
                                    "book": bo.get('book') or 'Consensus', "edge_points": float(round(edge_o1, 2)),
                                    "movement_tags": ["first_half_market"], "_is_early_season": g_is_early,
                                    "_agree_count": g_agree_sp, "_agree_count_total": g_agree_tot,
                                })
                    if best_1h_tot:
                        recs.append(max(best_1h_tot, key=lambda c: c['ev']))
            except Exception:
                pass

        if candidates_eval and isinstance(snap, dict):
            top_cand = max(candidates_eval, key=lambda c: float(c.get('ev') or -999.0))
            mkt = str(top_cand.get('market') or '').upper()
            side = str(top_cand.get('side') or '').lower()
            line_val = _safe_float(top_cand.get('line'))
            if mkt == 'SPREAD' and line_val is not None:
                team_lbl = top_cand.get('team') or (event.get('home_team') if side == 'home' else event.get('away_team'))
                sign = '+' if line_val > 0 else ''
                sel_lbl = f"{team_lbl} {sign}{line_val:g}"
                fair_val = round(float(mu_s) if side == 'home' else float(-mu_s), 1)
                edge_val = round(float(line_val) - float(fair_val), 1)
                gate_msg = snap.get('_no_bet_reason_spread')
            elif mkt == 'TOTAL' and line_val is not None:
                side_up = side.upper()
                sel_lbl = f"{side_up} {line_val:g}"
                fair_val = round(float(mu_t), 1)
                edge_val = round((fair_val - line_val) if side_up == 'OVER' else (line_val - fair_val), 1)
                gate_msg = snap.get('_no_bet_reason_total')
            else:
                sel_lbl = str(top_cand.get('side') or '')
                fair_val = None
                edge_val = _safe_float(top_cand.get('edge_points'))
                gate_msg = None

            ev_f = float(top_cand.get('ev') or 0.0)
            if not gate_msg:
                gate_msg = (
                    f"EV {ev_f * 100:+.1f}% / edge {edge_val if edge_val is not None else 0:+.1f} pts below strict publish gate"
                )
            snap['_best_candidate'] = {
                'bet_type': mkt,
                'selection': sel_lbl,
                'market_line': line_val,
                'fair_line': fair_val,
                'edge_points': edge_val,
                'ev': round(ev_f, 4),
                'ev_pct': round(ev_f * 100.0, 2),
                'price': top_cand.get('price'),
                'book': top_cand.get('book'),
                'win_prob': top_cand.get('win_prob'),
                'confidence': self._confidence_label_from_winprob(
                    top_cand.get('win_prob_lb10'),
                    fallback_win_prob=top_cand.get('win_prob'),
                ),
                'reason': gate_msg,
            }

        return self._apply_split_and_injury_signals(
            recs,
            action_splits=action_splits,
            injury_context=injury_context,
            market_consensus=(snap.get('_market_consensus') if isinstance(snap, dict) else None),
            relax_gates=relax_gates,
        )

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

    @staticmethod
    def _push_probability(line):
        if line is None or float(line) % 1:
            return 0.0
        return 0.05 if abs(float(line)) in {2, 3, 4, 5, 6, 7, 10, 14} else 0.03

    def _calculate_ev(self, win_prob, price, push_prob: float = 0.0):
        """Estimated Value (ROI) per 1u risked (scaling action by 1 - push_prob on whole numbers)."""
        from src.utils.ev import ev_per_unit
        ev = ev_per_unit(win_prob, price)
        # Guardrail: if odds invalid, treat as no edge.
        if ev is None:
            return 0.0
        return float(ev) * max(0.0, 1.0 - float(push_prob or 0.0))

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

        # --- Line movement (open -> current consensus, best effort) ---
        line_move = _safe_float(snap.get('spread_move_home')) if isinstance(snap, dict) else None
        try:
            if line_move is None and raw_snaps:
                open_sp = next(
                    (
                        _safe_float(s.get('line_value'))
                        for s in raw_snaps
                        if str(s.get('book') or '').strip().lower() == 'action_open'
                        and s.get('market_type') == 'SPREAD'
                        and s.get('side') == 'HOME'
                        and s.get('line_value') is not None
                    ),
                    None,
                )
                cur_sp = _safe_float(spread_mkt)
                if open_sp is not None and cur_sp is not None:
                    line_move = round(cur_sp - open_sp, 2)
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
                    key_factors.append(f"Torvik projected margin {margin:+.1f} → fair spread {fair_spread_torvik:+.1f} (diff vs market {delta:+.1f})")
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
                    key_factors.append(f"KenPom projected margin {kp_margin:+.1f} → fair spread {fair_spread_kp:+.1f} (diff vs market {delta:+.1f})")
            if kenpom.get('total_adj') is not None and total_mkt is not None:
                key_factors.append(f"KenPom pace adjustment {float(kenpom.get('total_adj')):+.1f} pts vs market {float(total_mkt):.1f}")
        except Exception:
            pass

        # Haslametrics
        signals = (debug_info or {}).get('signals') or {}
        hasla = signals.get('haslametrics')
        if isinstance(hasla, dict):
            h_spr = hasla.get('fair_spread_home')
            h_tot = hasla.get('fair_total')
            h_score = hasla.get('projected_score')
            if h_score and h_spr is not None:
                key_factors.append(
                    f"Haslametrics projects {h_score} (fair spread {float(h_spr):+.1f}, total {float(h_tot or 0):.1f})"
                )

        # Action Network Splits & Pre-Game Injuries
        splits = signals.get('public_splits') or {}
        if isinstance(splits, dict) and recs:
            main_r = recs[0]
            rmkt = str(main_r.get('market') or '').upper()
            rside = str(main_r.get('side') or '').upper()
            side_split = (splits.get(rmkt) or {}).get(rside) if rmkt in splits else None
            if isinstance(side_split, dict) and side_split.get('bet_pct') is not None and side_split.get('handle_pct') is not None:
                key_factors.append(
                    f"Public betting ({rside}): {int(round(side_split['bet_pct']))}% of tickets / {int(round(side_split['handle_pct']))}% of money"
                )

        inj_list = signals.get('injuries') or []
        inj_impact = signals.get('injuries_impact') or {}
        if inj_list:
            names = [f"{i.get('player')} ({i.get('status')})" for i in inj_list[:3] if i.get('player')]
            if names:
                risks.append(f"Injury watch: {', '.join(names)}")
        if isinstance(inj_impact, dict):
            isa = float(inj_impact.get('spread_adj') or 0.0)
            ita = float(inj_impact.get('total_adj') or 0.0)
            if abs(isa) >= 0.4:
                side_lbl = "away" if isa < 0 else "home"
                key_factors.append(f"Injury line adjustment: {abs(isa):.1f} pts against {side_lbl} from reported absences")
            if abs(ita) >= 0.4:
                key_factors.append(f"Injury scoring impact: {ita:+.1f} pts on projected total")

        ref_info = signals.get('referees') or {}
        if isinstance(ref_info, dict) and ref_info.get('officials'):
            key_factors.append(f"Assigned crew: {', '.join(ref_info['officials'][:3])}")

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

    def _derive_market_consensus_from_snaps(
        self,
        raw_snaps: List[Dict[str, Any]],
        consensus_spread: Optional[Dict[str, Any]] = None,
        consensus_total: Optional[Dict[str, Any]] = None,
        base_mc: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Enrich market_consensus metrics live from multi-book raw_snaps + action_open."""
        mc: Dict[str, Any] = dict(base_mc) if isinstance(base_mc, dict) else {}
        snaps = raw_snaps or []

        cur_sp = _safe_float((consensus_spread or {}).get('line_value'))
        if cur_sp is None:
            cur_sp = _safe_float(mc.get('current_spread_home'))
        elif mc.get('current_spread_home') is None:
            mc['current_spread_home'] = cur_sp

        cur_tot = _safe_float((consensus_total or {}).get('line_value'))
        if cur_tot is None:
            cur_tot = _safe_float(mc.get('current_total'))
        elif mc.get('current_total') is None:
            mc['current_total'] = cur_tot

        live_sp_rows = [
            s for s in snaps
            if s.get('market_type') == 'SPREAD'
            and s.get('side') == 'HOME'
            and s.get('line_value') is not None
            and str(s.get('book') or '').strip().lower() not in ('action_open', 'open')
        ]
        if live_sp_rows:
            books = {str(s.get('book')).strip() for s in live_sp_rows if s.get('book')}
            if books and (mc.get('books_count') is None or len(books) > int(mc.get('books_count') or 0)):
                mc['books_count'] = len(books)
            retail_sp_rows = [
                s for s in live_sp_rows if not self.odds_selector._is_sharp_benchmark(s.get('book'))
            ]
            disp_sp_rows = retail_sp_rows if len(retail_sp_rows) >= 2 else live_sp_rows
            sp_vals = [_safe_float(s.get('line_value')) for s in disp_sp_rows]
            sp_vals = [v for v in sp_vals if v is not None]
            if len(sp_vals) >= 2:
                mc['spread_disagreement'] = round(max(sp_vals) - min(sp_vals), 2)

        live_tot_rows = [
            s for s in snaps
            if s.get('market_type') == 'TOTAL'
            and s.get('side') == 'OVER'
            and s.get('line_value') is not None
            and str(s.get('book') or '').strip().lower() not in ('action_open', 'open')
        ]
        if live_tot_rows:
            retail_tot_rows = [
                s for s in live_tot_rows if not self.odds_selector._is_sharp_benchmark(s.get('book'))
            ]
            disp_tot_rows = retail_tot_rows if len(retail_tot_rows) >= 2 else live_tot_rows
            tot_vals = [_safe_float(s.get('line_value')) for s in disp_tot_rows]
            tot_vals = [v for v in tot_vals if v is not None]
            if len(tot_vals) >= 2:
                mc['total_disagreement'] = round(max(tot_vals) - min(tot_vals), 2)

        open_sp = next(
            (
                _safe_float(s.get('line_value'))
                for s in snaps
                if str(s.get('book') or '').strip().lower() == 'action_open'
                and s.get('market_type') == 'SPREAD'
                and s.get('side') == 'HOME'
                and s.get('line_value') is not None
            ),
            None,
        )
        if open_sp is not None and (
            _safe_float(mc.get('open_spread_home')) is None
            or (cur_sp is not None and abs(float(_safe_float(mc.get('open_spread_home'))) - float(cur_sp)) < 1e-6)
        ):
            mc['open_spread_home'] = open_sp

        open_tot = next(
            (
                _safe_float(s.get('line_value'))
                for s in snaps
                if str(s.get('book') or '').strip().lower() == 'action_open'
                and s.get('market_type') == 'TOTAL'
                and s.get('side') == 'OVER'
                and s.get('line_value') is not None
            ),
            None,
        )
        if open_tot is not None and (
            _safe_float(mc.get('open_total')) is None
            or (cur_tot is not None and abs(float(_safe_float(mc.get('open_total'))) - float(cur_tot)) < 1e-6)
        ):
            mc['open_total'] = open_tot

        if _safe_float(mc.get('open_spread_home')) is not None and cur_sp is not None:
            mc['current_spread_home'] = cur_sp
            mc['spread_move_home'] = round(float(cur_sp) - float(mc['open_spread_home']), 2)
        if _safe_float(mc.get('open_total')) is not None and cur_tot is not None:
            mc['current_total'] = cur_tot
            mc['total_move'] = round(float(cur_tot) - float(mc['open_total']), 2)

        return mc or None

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
                return f"Line moved against pick ({open_line:+.1f} → {cur_line:+.1f})"

        if m == 'TOTAL':
            open_total = _safe_float(mc.get('open_total'))
            cur_total = _safe_float(mc.get('current_total'))
            if open_total is None or cur_total is None:
                return None

            # For totals, direction depends on side.
            # Over: higher total is worse. Under: lower total is worse.
            delta = (cur_total - open_total)
            if s == 'over' and delta > abs(max_move_total):
                return f"Total moved against pick ({open_total:.1f} → {cur_total:.1f})"
            if s == 'under' and delta < -abs(max_move_total):
                return f"Total moved against pick ({open_total:.1f} → {cur_total:.1f})"

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
            raw_rows = [dict(r) for r in rows] if rows else []

        # Deduplicate to latest snapshot per (book, market_type, side) so stale history
        # cannot outrank current lines during consensus/best-price selection.
        seen_keys = set()
        deduped: List[Dict] = []
        for row in raw_rows:
            key = (row.get("book"), row.get("market_type"), row.get("side"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(row)
        return deduped

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
