"""
MLB Betting Model — Market-First architecture for MLB predictions.

Supports five bet types:
- Run Line (Spread ±1.5)
- Moneyline (Win/Loss)
- Over/Under (Total Runs)
- NRFI (No Run First Inning)

Architecture mirrors the NCAAM Market-First Model V2:
1. Anchor on market odds (consensus from Action Network)
2. Blend in statistical projections (pitcher ratings, team offense, park, weather)
3. Identify edges where model disagrees with market
4. Generate structured recommendations with confidence scoring

Data flow:
    Action Network odds → Market anchor
    MLB Stats API → Probable pitchers, season stats
    pybaseball (cached) → FIP, xERA, wOBA, splits
    Ballpark Service → Park factors
    Weather Service → Temperature, wind
    NRFI Service → First-inning analysis
"""

import math
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from src.models.base_model import BaseModel
from src.services.mlb_service import MLBService
from src.services.mlb_nrfi_service import MLBNRFIService
from src.services.ballpark_service import BallparkService
from src.services.weather_service import WeatherService


def _safe_float(x):
    try:
        if x is None or x == '':
            return None
        return float(x)
    except Exception:
        return None


def norm_cdf(x, mu=0.0, sigma=1.0):
    """Standard normal CDF using error function."""
    if sigma <= 0:
        sigma = 0.01
    val = (x - mu) / sigma
    return (1.0 + math.erf(val / math.sqrt(2.0))) / 2.0


class MLBModel(BaseModel):
    """
    MLB Market-First Betting Model.

    Market-first = market odds are the anchor. Statistical projections
    are used as corrective signals, not replacements.
    """

    VERSION = "1.0.0-mlb"

    # Model weights (how much to blend projections vs market)
    # 0.0 = pure market, 1.0 = pure projection
    DEFAULT_W_PROJ = 0.25  # Same starting point as NCAAM Torvik weight

    # Standard deviations for probability calculations
    # MLB run margins have lower variance than basketball
    SIGMA_MARGIN = 3.8     # For spread/ML probability (MLB margin std dev)
    SIGMA_TOTAL = 3.2      # For total runs probability

    # Edge thresholds (minimum edge to recommend a bet)
    MIN_EDGE_SPREAD = 0.3     # 0.3 runs on run line
    MIN_EDGE_TOTAL = 0.4      # 0.4 runs on total
    MIN_EDGE_ML_PROB = 0.04   # 4% probability edge on moneyline
    MIN_EDGE_NRFI_PROB = 0.06 # 6% probability edge on NRFI

    # EV threshold (minimum expected value per unit to recommend)
    MIN_EV_PER_UNIT = 0.02

    # Caps on how far model can deviate from market
    CAP_MARGIN = 1.5   # Max ±1.5 runs from market spread
    CAP_TOTAL = 1.2    # Max ±1.2 runs from market total

    def __init__(self):
        super().__init__(sport_key="baseball_mlb")
        self.mlb_service = MLBService()
        self.nrfi_service = MLBNRFIService()
        self.ballpark = BallparkService()
        self.weather = WeatherService()

        # Env-configurable weights
        try:
            w = os.getenv("MLB_W_PROJ")
            if w is not None:
                self.W_PROJ = float(w)
            else:
                self.W_PROJ = self.DEFAULT_W_PROJ
        except Exception:
            self.W_PROJ = self.DEFAULT_W_PROJ

    def fetch_data(self):
        """Pre-load data (no-op — data is fetched per-game in analyze)."""
        pass

    def evaluate(self, predictions=None):
        """Evaluate performance (placeholder)."""
        pass

    def predict(self, game_id: str, home_team: str, away_team: str, market_total: float = 0) -> Dict[str, Any]:
        """Satisfy BaseModel interface."""
        event = {
            "id": game_id,
            "home_team": home_team,
            "away_team": away_team,
            "start_time": datetime.now(timezone.utc),
        }
        snap = {
            "total": market_total or 8.5,
            "spread_home": -1.5,
        }
        return self.analyze(event_id=game_id, market_snapshot=snap, event_context=event)

    # ── Core Analysis Engine ───────────────────────────────────

    def analyze(self,
                event_id: str,
                market_snapshot: Optional[Dict] = None,
                event_context: Optional[Dict] = None,
                persist: bool = True) -> Dict:
        """
        Full analysis for one MLB game.

        Returns predictions for all bet types: spread, ML, total, NRFI.
        """
        # 1. Load event context
        event = event_context or {}
        home_team = event.get("home_team", "")
        away_team = event.get("away_team", "")
        game_time = event.get("start_time") or event.get("game_date")

        if isinstance(game_time, str):
            try:
                game_time = datetime.fromisoformat(game_time.replace('Z', '+00:00'))
            except Exception:
                game_time = datetime.now(timezone.utc)

        # 2. Market snapshot (from Action Network)
        if not market_snapshot:
            return {
                "headline": "No Market Data",
                "recommendation": "Pass",
                "is_actionable": False,
                "rationale": ["Market odds not available."],
            }

        mu_market_spread = _safe_float(market_snapshot.get("spread_home")) or -1.5
        mu_market_total = _safe_float(market_snapshot.get("total")) or 8.5
        ml_home_price = _safe_float(market_snapshot.get("moneyline_price_home"))
        ml_away_price = _safe_float(market_snapshot.get("moneyline_price_away"))

        has_spread = market_snapshot.get("spread_home") is not None
        has_total = market_snapshot.get("total") is not None

        # 3. Get probable pitchers
        home_pitcher_info = event.get("home_pitcher")
        away_pitcher_info = event.get("away_pitcher")

        home_pitcher_id = home_pitcher_info.get("id") if home_pitcher_info else None
        away_pitcher_id = away_pitcher_info.get("id") if away_pitcher_info else None
        home_pitcher_name = home_pitcher_info.get("name") if home_pitcher_info else "TBD"
        away_pitcher_name = away_pitcher_info.get("name") if away_pitcher_info else "TBD"

        # 4. Get pitcher stats & ratings
        home_sp_stats = self.mlb_service.get_pitcher_season_stats(home_pitcher_id) if home_pitcher_id else None
        away_sp_stats = self.mlb_service.get_pitcher_season_stats(away_pitcher_id) if away_pitcher_id else None

        home_sp_rating = self.mlb_service.calculate_pitcher_rating(home_sp_stats)
        away_sp_rating = self.mlb_service.calculate_pitcher_rating(away_sp_stats)

        # 5. Get team batting ratings
        home_batting = self.mlb_service.get_team_batting_rating(home_team)
        away_batting = self.mlb_service.get_team_batting_rating(away_team)

        # 6. Park factors
        park_factor_runs = self.ballpark.get_park_factor_runs(home_team)
        park_factor_hr = self.ballpark.get_park_factor_hr(home_team)
        altitude_adj = self.ballpark.get_altitude_adjustment(home_team)

        # 7. Weather
        weather_data = self.weather.get_game_weather(home_team, game_time)
        weather_total_adj = weather_data.get("total_adjustment", 0.0) if weather_data else 0.0

        # 8. Platoon adjustments
        home_sp_throws = home_sp_stats.get("throws") if home_sp_stats else None
        away_sp_throws = away_sp_stats.get("throws") if away_sp_stats else None
        platoon_home = self.mlb_service.get_platoon_adjustment(away_sp_throws, home_team)
        platoon_away = self.mlb_service.get_platoon_adjustment(home_sp_throws, away_team)

        # 9. Bullpen
        home_bullpen = self.mlb_service.get_bullpen_rating(home_team)
        away_bullpen = self.mlb_service.get_bullpen_rating(away_team)

        # 10. Travel distance
        travel_dist = self.ballpark.calculate_travel_distance(home_team, away_team)
        travel_adj = -0.10 if travel_dist > 1500 else 0.0  # Away team fatigue

        # ── Run Projections ────────────────────────────────────

        # Home team runs = how well home offense hits vs away SP
        home_runs_proj = self.mlb_service.project_runs(
            pitcher_rating=away_sp_rating,       # Away SP pitching against Home offense
            opposing_batting=home_batting,         # Home team batting
            park_factor_runs=park_factor_runs,
            weather_adjustment=weather_total_adj,
            bullpen_rating=away_bullpen,
            platoon_adj=platoon_home,
        )

        # Away team runs = how well away offense hits vs home SP
        away_runs_proj = self.mlb_service.project_runs(
            pitcher_rating=home_sp_rating,       # Home SP pitching against Away offense
            opposing_batting=away_batting,         # Away team batting
            park_factor_runs=park_factor_runs,
            weather_adjustment=weather_total_adj,
            bullpen_rating=home_bullpen,
            platoon_adj=platoon_away + travel_adj,
        )

        proj_home_runs = home_runs_proj["projected_runs"]
        proj_away_runs = away_runs_proj["projected_runs"]
        proj_margin = proj_home_runs - proj_away_runs  # Positive = home favored
        proj_total = proj_home_runs + proj_away_runs

        # ── Market-First Blending ──────────────────────────────

        # Spread
        diff_margin = (-proj_margin) - mu_market_spread  # Convention: spread_home is negative for favorite
        mu_final_spread = mu_market_spread + (self.W_PROJ * diff_margin)

        # Cap the deviation
        if abs(mu_final_spread - mu_market_spread) > self.CAP_MARGIN:
            mu_final_spread = mu_market_spread + (self.CAP_MARGIN * math.copysign(1, mu_final_spread - mu_market_spread))

        # Total
        diff_total = proj_total - mu_market_total
        mu_final_total = mu_market_total + (self.W_PROJ * diff_total)

        if abs(mu_final_total - mu_market_total) > self.CAP_TOTAL:
            mu_final_total = mu_market_total + (self.CAP_TOTAL * math.copysign(1, mu_final_total - mu_market_total))

        # Altitude adjustment to total
        mu_final_total += altitude_adj

        # ── Probability Calculations ───────────────────────────

        # Spread (Run Line ±1.5)
        # Home team covers -1.5 means home wins by 2+
        actual_margin = -mu_final_spread  # Convert spread to margin (positive = home winning)
        prob_home_cover = norm_cdf(actual_margin - 1.5, mu=0, sigma=self.SIGMA_MARGIN)
        prob_away_cover = 1.0 - prob_home_cover

        # Moneyline
        prob_home_win = norm_cdf(actual_margin, mu=0, sigma=self.SIGMA_MARGIN)
        prob_away_win = 1.0 - prob_home_win

        # Home field advantage built in to slight degree
        HFA_BOOST = 0.015
        prob_home_win = min(0.95, prob_home_win + HFA_BOOST)
        prob_away_win = 1.0 - prob_home_win

        # Total (Over/Under)
        prob_over = 1.0 - norm_cdf(mu_market_total, mu=mu_final_total, sigma=self.SIGMA_TOTAL)
        prob_under = norm_cdf(mu_market_total, mu=mu_final_total, sigma=self.SIGMA_TOTAL)

        # ── Edge Calculations ──────────────────────────────────

        # Spread edge
        spread_edge = abs(mu_final_spread - mu_market_spread)

        # ML edge (compare model prob vs implied prob from odds)
        implied_home = self._implied_prob_from_american(ml_home_price) if ml_home_price else 0.5
        implied_away = self._implied_prob_from_american(ml_away_price) if ml_away_price else 0.5
        ml_edge_home = prob_home_win - implied_home
        ml_edge_away = prob_away_win - implied_away

        # Total edge
        total_edge = abs(mu_final_total - mu_market_total)

        # ── NRFI Analysis ──────────────────────────────────────

        nrfi_result = self.nrfi_service.calculate_nrfi_probability(
            home_pitcher_id=home_pitcher_id,
            away_pitcher_id=away_pitcher_id,
            home_team=home_team,
            away_team=away_team,
            park_factor=park_factor_runs,
        )

        # ── Generate Recommendations ──────────────────────────

        recommendations = self._generate_recommendations(
            mu_market_spread=mu_market_spread,
            mu_final_spread=mu_final_spread,
            mu_market_total=mu_market_total,
            mu_final_total=mu_final_total,
            prob_home_cover=prob_home_cover,
            prob_away_cover=prob_away_cover,
            prob_home_win=prob_home_win,
            prob_away_win=prob_away_win,
            prob_over=prob_over,
            prob_under=prob_under,
            spread_edge=spread_edge,
            ml_edge_home=ml_edge_home,
            ml_edge_away=ml_edge_away,
            total_edge=total_edge,
            nrfi_result=nrfi_result,
            home_team=home_team,
            away_team=away_team,
            ml_home_price=ml_home_price,
            ml_away_price=ml_away_price,
            market_snapshot=market_snapshot,
            has_spread=has_spread,
            has_total=has_total,
        )

        # ── Bell Curves ────────────────────────────────────────

        spread_curve = self._generate_bell_curve(actual_margin, self.SIGMA_MARGIN, 1.5)
        total_curve = self._generate_bell_curve(mu_final_total, self.SIGMA_TOTAL, mu_market_total)

        # ── Build Result ───────────────────────────────────────

        result = {
            "event_id": event_id,
            "model_version": self.VERSION,
            "sport": "MLB",
            "league": "MLB",
            "home_team": home_team,
            "away_team": away_team,
            "game_time": game_time.isoformat() if isinstance(game_time, datetime) else str(game_time),

            # Pitching matchup
            "pitching_matchup": {
                "home_sp": {
                    "name": home_pitcher_name,
                    "rating": home_sp_rating,
                },
                "away_sp": {
                    "name": away_pitcher_name,
                    "rating": away_sp_rating,
                },
            },

            # Run projections
            "projections": {
                "home_runs": proj_home_runs,
                "away_runs": proj_away_runs,
                "total_runs": round(proj_total, 2),
                "margin": round(proj_margin, 2),
                "home_projection_detail": home_runs_proj,
                "away_projection_detail": away_runs_proj,
            },

            # Market data
            "market": {
                "spread_home": mu_market_spread,
                "total": mu_market_total,
                "ml_home_price": ml_home_price,
                "ml_away_price": ml_away_price,
            },

            # Model outputs (blended)
            "model": {
                "fair_spread": round(mu_final_spread, 2),
                "fair_total": round(mu_final_total, 2),
                "prob_home_cover": round(prob_home_cover, 4),
                "prob_away_cover": round(prob_away_cover, 4),
                "prob_home_win": round(prob_home_win, 4),
                "prob_away_win": round(prob_away_win, 4),
                "prob_over": round(prob_over, 4),
                "prob_under": round(prob_under, 4),
                "weight_projection": self.W_PROJ,
            },

            # Edges
            "edges": {
                "spread_edge": round(spread_edge, 2),
                "ml_edge_home": round(ml_edge_home, 4),
                "ml_edge_away": round(ml_edge_away, 4),
                "total_edge": round(total_edge, 2),
            },

            # NRFI
            "nrfi": nrfi_result,

            # Recommendations
            "recommendations": recommendations,

            # Context factors
            "context": {
                "park_factor_runs": round(park_factor_runs, 3),
                "park_factor_hr": round(park_factor_hr, 3),
                "altitude_adj": altitude_adj,
                "weather": weather_data,
                "travel_distance_miles": travel_dist,
                "travel_adj": travel_adj,
                "is_domed": self.ballpark.is_domed(home_team),
            },

            # Visuals
            "bell_curves": {
                "spread": spread_curve,
                "total": total_curve,
            },

            "is_actionable": len(recommendations) > 0,
        }

        # Generate headline
        if recommendations:
            top_rec = recommendations[0]
            result["headline"] = f"{top_rec['market_type']}: {top_rec['selection']}"
            result["recommendation"] = top_rec["selection"]
        else:
            result["headline"] = "No Clear Edge"
            result["recommendation"] = "Pass"

        return result

    # ── Recommendation Generation ──────────────────────────────

    def _generate_recommendations(self, **kwargs) -> List[Dict]:
        """Generate actionable bet recommendations based on edges."""
        recs = []

        home_team = kwargs["home_team"]
        away_team = kwargs["away_team"]
        market_snapshot = kwargs["market_snapshot"]

        # 1. Spread (Run Line)
        if kwargs.get("has_spread"):
            spread_edge = kwargs["spread_edge"]
            mu_final = kwargs["mu_final_spread"]
            mu_market = kwargs["mu_market_spread"]

            if spread_edge >= self.MIN_EDGE_SPREAD:
                # Determine which side to bet
                if mu_final < mu_market:
                    # Model thinks home should be more favored → bet Home -1.5
                    pick = home_team
                    side = "HOME"
                    prob = kwargs["prob_home_cover"]
                    line = mu_market
                else:
                    # Model thinks away should be closer → bet Away +1.5
                    pick = away_team
                    side = "AWAY"
                    prob = kwargs["prob_away_cover"]
                    line = -mu_market

                price = market_snapshot.get(f"spread_price_{side.lower()}", -110)
                ev = self._calculate_ev(prob, price or -110)

                if ev >= self.MIN_EV_PER_UNIT:
                    recs.append({
                        "market_type": "SPREAD",
                        "pick": pick,
                        "side": side,
                        "line": round(line, 1),
                        "price": price,
                        "prob": round(prob, 4),
                        "edge": round(spread_edge, 2),
                        "ev_per_unit": round(ev, 4),
                        "selection": f"{pick} {line:+.1f}",
                        "confidence": "HIGH" if spread_edge > 0.8 else "MEDIUM" if spread_edge > 0.5 else "LOW",
                    })

        # 2. Moneyline
        ml_edge_home = kwargs["ml_edge_home"]
        ml_edge_away = kwargs["ml_edge_away"]
        ml_home_price = kwargs["ml_home_price"]
        ml_away_price = kwargs["ml_away_price"]

        if ml_edge_home > self.MIN_EDGE_ML_PROB and ml_home_price:
            ev = self._calculate_ev(kwargs["prob_home_win"], ml_home_price)
            if ev >= self.MIN_EV_PER_UNIT:
                recs.append({
                    "market_type": "MONEYLINE",
                    "pick": home_team,
                    "side": "HOME",
                    "line": None,
                    "price": ml_home_price,
                    "prob": round(kwargs["prob_home_win"], 4),
                    "edge": round(ml_edge_home, 4),
                    "ev_per_unit": round(ev, 4),
                    "selection": f"{home_team} ML ({ml_home_price:+d})" if isinstance(ml_home_price, int) else f"{home_team} ML",
                    "confidence": "HIGH" if ml_edge_home > 0.08 else "MEDIUM" if ml_edge_home > 0.05 else "LOW",
                })

        if ml_edge_away > self.MIN_EDGE_ML_PROB and ml_away_price:
            ev = self._calculate_ev(kwargs["prob_away_win"], ml_away_price)
            if ev >= self.MIN_EV_PER_UNIT:
                recs.append({
                    "market_type": "MONEYLINE",
                    "pick": away_team,
                    "side": "AWAY",
                    "line": None,
                    "price": ml_away_price,
                    "prob": round(kwargs["prob_away_win"], 4),
                    "edge": round(ml_edge_away, 4),
                    "ev_per_unit": round(ev, 4),
                    "selection": f"{away_team} ML ({ml_away_price:+d})" if isinstance(ml_away_price, int) else f"{away_team} ML",
                    "confidence": "HIGH" if ml_edge_away > 0.08 else "MEDIUM" if ml_edge_away > 0.05 else "LOW",
                })

        # 3. Total (Over/Under)
        if kwargs.get("has_total"):
            total_edge = kwargs["total_edge"]
            mu_final_total = kwargs["mu_final_total"]
            mu_market_total = kwargs["mu_market_total"]

            if total_edge >= self.MIN_EDGE_TOTAL:
                if mu_final_total > mu_market_total:
                    pick = "OVER"
                    prob = kwargs["prob_over"]
                else:
                    pick = "UNDER"
                    prob = kwargs["prob_under"]

                price = market_snapshot.get("total_over_price" if pick == "OVER" else "total_under_price", -110)
                ev = self._calculate_ev(prob, price or -110)

                if ev >= self.MIN_EV_PER_UNIT:
                    recs.append({
                        "market_type": "TOTAL",
                        "pick": pick,
                        "side": pick,
                        "line": mu_market_total,
                        "price": price,
                        "prob": round(prob, 4),
                        "edge": round(total_edge, 2),
                        "ev_per_unit": round(ev, 4),
                        "selection": f"{pick} {mu_market_total}",
                        "confidence": "HIGH" if total_edge > 0.8 else "MEDIUM" if total_edge > 0.5 else "LOW",
                    })

        # 4. NRFI
        nrfi = kwargs.get("nrfi_result", {})
        p_nrfi = nrfi.get("p_nrfi", 0.52)

        # Compare to implied probability (if we have NRFI odds)
        nrfi_market_price = market_snapshot.get("nrfi_price")
        if nrfi_market_price:
            implied_nrfi = self._implied_prob_from_american(nrfi_market_price)
            nrfi_edge = p_nrfi - implied_nrfi
        else:
            # No market odds — use model probability threshold instead
            nrfi_edge = p_nrfi - self.nrfi_service.LEAGUE_AVG_NRFI_RATE
            nrfi_market_price = -120  # Default assumption for EV calc

        if nrfi_edge > self.MIN_EDGE_NRFI_PROB and p_nrfi > 0.55:
            ev = self._calculate_ev(p_nrfi, nrfi_market_price)
            if ev >= self.MIN_EV_PER_UNIT:
                recs.append({
                    "market_type": "NRFI",
                    "pick": "NRFI",
                    "side": "NRFI",
                    "line": None,
                    "price": nrfi_market_price,
                    "prob": round(p_nrfi, 4),
                    "edge": round(nrfi_edge, 4),
                    "ev_per_unit": round(ev, 4),
                    "selection": f"NRFI ({home_team} vs {away_team})",
                    "confidence": "HIGH" if p_nrfi > 0.65 else "MEDIUM" if p_nrfi > 0.58 else "LOW",
                    "nrfi_detail": nrfi,
                })

        # Sort by EV (best edge first)
        recs.sort(key=lambda r: r["ev_per_unit"], reverse=True)

        return recs

    # ── Helper Methods ─────────────────────────────────────────

    def _implied_prob_from_american(self, odds: float) -> float:
        """Convert American odds to implied probability."""
        if odds is None:
            return 0.5
        odds = float(odds)
        if odds > 0:
            return 100 / (odds + 100)
        elif odds < 0:
            return abs(odds) / (abs(odds) + 100)
        return 0.5

    def _calculate_ev(self, prob: float, american_odds: float) -> float:
        """
        Calculate Expected Value per unit bet.

        EV = (prob * payout) - ((1 - prob) * stake)
        For a $1 bet: EV = prob * decimal_payout - 1
        """
        if american_odds is None:
            return 0.0
        odds = float(american_odds)
        if odds > 0:
            decimal = (odds / 100) + 1
        elif odds < 0:
            decimal = (100 / abs(odds)) + 1
        else:
            return 0.0

        ev = (prob * decimal) - 1
        return ev

    def _generate_bell_curve(self, mu: float, sigma: float, line: float) -> Dict:
        """
        Generate bell curve points for frontend visualization.
        Reuses same pattern as NCAAM model.
        """
        points = []
        start = mu - (3 * sigma)
        end = mu + (3 * sigma)
        step = (end - start) / 50

        for i in range(51):
            x = start + (i * step)
            y = (1 / (sigma * math.sqrt(2 * math.pi))) * math.exp(-0.5 * ((x - mu) / sigma) ** 2)
            points.append({"x": round(x, 2), "y": round(y, 6)})

        z = (line - mu) / sigma
        cover_prob = 0.5 * (1 + math.erf(z / math.sqrt(2)))

        return {
            "points": points,
            "mu": round(mu, 2),
            "sigma": round(sigma, 2),
            "line": round(line, 2),
            "cover_prob": round(cover_prob, 4),
        }

    # ── Batch Analysis ─────────────────────────────────────────

    def analyze_todays_slate(self, date: str = None) -> List[Dict]:
        """
        Analyze all MLB games for a given date.

        This is the main entry point for cron-based predictions.
        Uses Action Network as the primary odds source.
        """
        import datetime as dt

        if date is None:
            date_str = dt.date.today().strftime("%Y-%m-%d")
            date_an = dt.date.today().strftime("%Y%m%d")
        else:
            date_str = date
            # Convert YYYY-MM-DD to YYYYMMDD for Action Network
            date_an = date.replace("-", "")

        print(f"\n[MLB MODEL] Analyzing slate for {date_str}")
        print(f"{'='*60}")

        # 1. Get schedule with probable pitchers
        schedule = self.mlb_service.get_schedule(date_str)
        if not schedule:
            print("[MLB MODEL] No games found on schedule.")
            return []

        # 2. Get odds from Action Network
        odds_list = self.mlb_service.fetch_mlb_odds_action_network([date_an])

        # Build matchup → odds lookup
        odds_lookup = {}
        for game in odds_list:
            key = f"{game.get('away_team', '')} @ {game.get('home_team', '')}"
            odds_lookup[key] = game
            # Also index by just home team for fuzzy matching
            odds_lookup[game.get('home_team', '')] = game

        # 3. Analyze each game
        results = []
        for game in schedule:
            home = game["home_team"]
            away = game["away_team"]
            status = (game.get("status") or "").lower()

            # Skip completed games
            if "final" in status or "progress" in status:
                continue

            # Match odds
            matchup_key = f"{away} @ {home}"
            odds = odds_lookup.get(matchup_key) or odds_lookup.get(home)

            if not odds:
                print(f"  [SKIP] No odds found for {away} @ {home}")
                continue

            # Build market snapshot from Action Network data
            market_snap = {
                "spread_home": _safe_float(odds.get("home_spread")),
                "spread_price_home": _safe_float(odds.get("home_spread_odds")) or -110,
                "spread_price_away": _safe_float(odds.get("away_spread_odds")) or -110,
                "total": _safe_float(odds.get("total_score")),
                "total_over_price": _safe_float(odds.get("over_odds")) or -110,
                "total_under_price": _safe_float(odds.get("under_odds")) or -110,
                "moneyline_price_home": _safe_float(odds.get("home_money_line")),
                "moneyline_price_away": _safe_float(odds.get("away_money_line")),
            }

            # Build event context
            event_ctx = {
                "id": odds.get("game_id") or str(game.get("game_pk")),
                "home_team": home,
                "away_team": away,
                "start_time": game.get("game_date"),
                "home_pitcher": game.get("home_pitcher"),
                "away_pitcher": game.get("away_pitcher"),
            }

            event_id = f"action:mlb:{odds.get('game_id', game.get('game_pk'))}"

            print(f"\n  📊 {away} @ {home}")
            hp = game.get("home_pitcher", {})
            ap = game.get("away_pitcher", {})
            print(f"     Pitchers: {ap.get('name', 'TBD') if ap else 'TBD'} vs {hp.get('name', 'TBD') if hp else 'TBD'}")
            print(f"     Market: Spread {market_snap['spread_home']}, O/U {market_snap['total']}")

            try:
                analysis = self.analyze(
                    event_id=event_id,
                    market_snapshot=market_snap,
                    event_context=event_ctx,
                    persist=False,
                )

                if analysis.get("recommendations"):
                    for rec in analysis["recommendations"]:
                        confidence_emoji = "🟢" if rec["confidence"] == "HIGH" else "🟡" if rec["confidence"] == "MEDIUM" else "⚪"
                        print(f"     {confidence_emoji} {rec['market_type']}: {rec['selection']} (Edge: {rec['edge']}, EV: {rec['ev_per_unit']:.3f})")
                else:
                    print(f"     ⚪ No edge found")

                results.append(analysis)

            except Exception as e:
                print(f"     ❌ Analysis error: {e}")

        print(f"\n{'='*60}")
        print(f"[MLB MODEL] Analyzed {len(results)} games. Actionable: {sum(1 for r in results if r.get('is_actionable'))}")
        return results


if __name__ == "__main__":
    model = MLBModel()
    results = model.analyze_todays_slate()

    print("\n\n=== SUMMARY ===")
    for r in results:
        if r.get("is_actionable"):
            print(f"\n{r['away_team']} @ {r['home_team']}:")
            for rec in r.get("recommendations", []):
                print(f"  ✅ {rec['selection']} | Edge: {rec['edge']} | EV: {rec['ev_per_unit']:.3f} | {rec['confidence']}")
