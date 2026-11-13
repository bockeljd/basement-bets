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
from typing import Dict, List, Any, Optional, Tuple

from src.models.base_model import BaseModel
from src.services.mlb_service import MLBService
from src.services.mlb_nrfi_service import MLBNRFIService
from src.services.ballpark_service import BallparkService
from src.services.weather_service import WeatherService
from src.utils.model_calibration import interpolate_pava_prob, load_winprob_calibration


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
    SIGMA_TOTAL = 4.0      # Realistic MLB combined runs std dev (~4.0-4.2 runs)

    # Edge thresholds (minimum edge to recommend a bet)
    MIN_EDGE_SPREAD = 0.3     # 0.3 runs on run line
    MIN_EDGE_TOTAL = 0.65     # 0.65 runs on total (curbs marginal -110 O/U noise)
    MIN_EDGE_ML_PROB = 0.06   # 6% probability edge on moneyline
    MIN_EDGE_NRFI_PROB = 0.06 # 6% probability edge on NRFI

    # EV thresholds (minimum expected value per unit to recommend)
    MIN_EV_PER_UNIT = 0.05
    MIN_EV_TOTAL = 0.06       # Require +6.0% EV on Over/Under totals (historically noisy)
    MAX_ML_PRICE = -165       # Don't recommend ML picks shorter than -165

    # Late-season (Aug-Sep) roster expansion / fatigue conservatism
    LATE_SEASON_START_MONTH = 8
    LATE_SEASON_TOTAL_EDGE_BUMP = 0.15
    LATE_SEASON_EV_BUMP = 0.015

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

        home_sp_recent = self.mlb_service.get_pitcher_recent_form(home_pitcher_id) if home_pitcher_id else None
        away_sp_recent = self.mlb_service.get_pitcher_recent_form(away_pitcher_id) if away_pitcher_id else None

        home_sp_splits = self.mlb_service.get_pitcher_home_away_splits(home_pitcher_id) if home_pitcher_id else None
        away_sp_splits = self.mlb_service.get_pitcher_home_away_splits(away_pitcher_id) if away_pitcher_id else None

        home_sp_rating = self.mlb_service.calculate_pitcher_rating(
            stats=home_sp_stats, recent_form=home_sp_recent, ha_splits=home_sp_splits, is_home=True
        )
        away_sp_rating = self.mlb_service.calculate_pitcher_rating(
            stats=away_sp_stats, recent_form=away_sp_recent, ha_splits=away_sp_splits, is_home=False
        )

        # 5. Get team batting ratings
        home_batting = self.mlb_service.get_team_batting_rating(home_team)
        away_batting = self.mlb_service.get_team_batting_rating(away_team)

        # Data confidence (min model inputs required to be fully confident)
        home_data_conf = min(home_sp_rating.get("confidence", 0.0), (home_batting or {}).get("confidence", 0.0))
        away_data_conf = min(away_sp_rating.get("confidence", 0.0), (away_batting or {}).get("confidence", 0.0))

        # 6. Park factors
        park_factor_runs = self.ballpark.get_park_factor_runs(home_team)
        park_factor_hr = self.ballpark.get_park_factor_hr(home_team)
        altitude_adj = self.ballpark.get_altitude_adjustment(home_team)

        # 7. Weather
        try:
            weather_data = self.weather.get_game_weather(home_team, game_time)
        except Exception as e:
            print(f"[MLB] Weather error for {home_team}: {e}")
            weather_data = None
        weather_total_adj = (weather_data or {}).get("total_adjustment", 0.0)

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
        # Away team runs = how well away offense hits vs home SP
        # Both raise ValueError if real data is unavailable — skip this game.
        try:
            home_runs_proj = self.mlb_service.project_runs(
                pitcher_rating=away_sp_rating,
                opposing_batting=home_batting,
                park_factor_runs=park_factor_runs,
                weather_adjustment=weather_total_adj,
                bullpen_rating=away_bullpen,
                platoon_adj=platoon_home,
            )
            away_runs_proj = self.mlb_service.project_runs(
                pitcher_rating=home_sp_rating,
                opposing_batting=away_batting,
                park_factor_runs=park_factor_runs,
                weather_adjustment=weather_total_adj,
                bullpen_rating=home_bullpen,
                platoon_adj=platoon_away + travel_adj,
            )
        except ValueError as e:
            print(f"[MLB] Skipping {away_team} @ {home_team}: {e}")
            return {
                "event_id": event_id,
                "home_team": home_team,
                "away_team": away_team,
                "headline": "Insufficient Data",
                "recommendation": "Pass",
                "is_actionable": False,
                "rationale": [str(e)],
                "recommendations": [],
            }

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
        # Total blend (park_factor_runs in run projections + market total already price altitude;
        # avoid double-counting altitude_adj after blending with market total).
        diff_total = proj_total - mu_market_total
        mu_final_total = mu_market_total + (self.W_PROJ * diff_total)

        if abs(mu_final_total - mu_market_total) > self.CAP_TOTAL:
            mu_final_total = mu_market_total + (self.CAP_TOTAL * math.copysign(1, mu_final_total - mu_market_total))

        # ── Probability Calculations ───────────────────────────

        # Spread (Run Line ±1.5): home covers mu_market_spread iff margin + spread > 0
        actual_margin = -mu_final_spread  # Convert spread to margin (positive = home winning)
        prob_home_cover = norm_cdf(actual_margin + mu_market_spread, mu=0, sigma=self.SIGMA_MARGIN)
        prob_away_cover = 1.0 - prob_home_cover

        # Moneyline (market spread & H/A pitcher splits already incorporate HFA)
        prob_home_win = max(0.05, min(0.95, norm_cdf(actual_margin, mu=0, sigma=self.SIGMA_MARGIN)))
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

        try:
            nrfi_result = self.nrfi_service.calculate_nrfi_probability(
                home_pitcher_id=home_pitcher_id,
                away_pitcher_id=away_pitcher_id,
                home_team=home_team,
                away_team=away_team,
                park_factor=park_factor_runs,
            )
        except Exception as e:
            print(f"[MLB] NRFI error for {away_team} @ {home_team}: {e}")
            nrfi_result = {
                "p_nrfi": self.nrfi_service.LEAGUE_AVG_NRFI_RATE,
                "p_yrfi": 1 - self.nrfi_service.LEAGUE_AVG_NRFI_RATE,
                "p_no_run_top": 0.72,
                "p_no_run_bottom": 0.72,
                "confidence": 0.0,
            }

        # ── Generate Recommendations ──────────────────────────
        is_late_season = bool(isinstance(game_time, datetime) and game_time.month >= self.LATE_SEASON_START_MONTH)

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
            home_data_conf=home_data_conf,
            away_data_conf=away_data_conf,
            is_late_season=is_late_season,
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

    _winprob_calibration: Optional[Dict[str, Any]] = None

    def _load_winprob_calibration(self) -> Dict[str, Any]:
        """Load MLB piecewise-linear win_prob calibration mapping (DB first, JSON fallback)."""
        if self._winprob_calibration is not None:
            return self._winprob_calibration
        self._winprob_calibration = load_winprob_calibration(
            "winprob_calibration_mlb",
            "winprob_calibration_mlb.json",
            min_max_pcal=0.52,
        )
        return self._winprob_calibration

    def _calibrate_win_prob(self, prob: float) -> float:
        """Apply shrinkage-blended PAVA calibration when full-season observations (>=200) exist."""
        return interpolate_pava_prob(
            prob,
            self._load_winprob_calibration(),
            min_obs=200,
            blend_weight=0.35,
        )

    def _classify_confidence(self, prob: float, ev: float) -> Tuple[str, int]:
        """Classify pick confidence aligned with calibrated win probability and positive EV.

        Returns (label, score_0_100) matching conf_bucket tiers (>=80 High, >=50 Medium, <50 Low)
        so low-probability longshots cannot be misclassified as High Confidence.
        """
        p = max(0.0, min(1.0, float(prob or 0.0)))
        ev_val = float(ev or 0.0)
        if p >= 0.56 and ev_val >= 0.07:
            score = min(95, 80 + int(round((p - 0.56) * 120)))
            return "HIGH", score
        if p >= 0.50 and ev_val >= 0.03:
            score = 55 + int(round(((min(p, 0.559) - 0.50) / 0.06) * 23))
            return "MEDIUM", min(78, max(50, score))
        score = max(20, min(49, int(round(p * 90))))
        return "LOW", score

    def _generate_recommendations(self, **kwargs) -> List[Dict]:
        """Generate actionable bet recommendations based on edges."""
        recs = []

        home_team = kwargs["home_team"]
        away_team = kwargs["away_team"]
        market_snapshot = kwargs["market_snapshot"]
        is_late_season = bool(kwargs.get("is_late_season"))
        late_ev_bump = float(self.LATE_SEASON_EV_BUMP) if is_late_season else 0.0
        min_ev_standard = float(self.MIN_EV_PER_UNIT) + late_ev_bump
        min_edge_total = float(self.MIN_EDGE_TOTAL) + (float(self.LATE_SEASON_TOTAL_EDGE_BUMP) if is_late_season else 0.0)
        min_ev_total = float(self.MIN_EV_TOTAL) + late_ev_bump

        # 1. Spread (Run Line)
        if kwargs.get("has_spread"):
            spread_edge = kwargs["spread_edge"]
            mu_final = kwargs["mu_final_spread"]
            mu_market = kwargs["mu_market_spread"]

            if spread_edge >= self.MIN_EDGE_SPREAD:
                # Determine which side to bet
                if mu_final < mu_market:
                    # Model thinks home should be more favored → bet Home spread
                    pick = home_team
                    side = "HOME"
                    prob = kwargs["prob_home_cover"]
                    line = mu_market
                else:
                    # Model thinks away should be closer → bet Away spread
                    pick = away_team
                    side = "AWAY"
                    prob = kwargs["prob_away_cover"]
                    line = -mu_market

                price = market_snapshot.get(f"spread_price_{side.lower()}", -110)
                prob_cal = self._calibrate_win_prob(prob)
                ev = self._calculate_ev(prob_cal, price or -110)

                if ev >= min_ev_standard:
                    conf_label, conf_score = self._classify_confidence(prob_cal, ev)
                    recs.append({
                        "market_type": "SPREAD",
                        "pick": pick,
                        "side": side,
                        "line": round(line, 1),
                        "price": price,
                        "prob": round(prob_cal, 4),
                        "edge": round(spread_edge, 2),
                        "ev_per_unit": round(ev, 4),
                        "selection": f"{pick} {line:+.1f}",
                        "confidence": conf_label,
                        "confidence_0_100": conf_score,
                    })

        # 2. Moneyline (symmetrical evaluation for home & away)
        home_conf = kwargs.get("home_data_conf", 0.0)
        away_conf = kwargs.get("away_data_conf", 0.0)
        for side, team, ml_edge, raw_prob, ml_price, data_conf in (
            ("HOME", home_team, kwargs["ml_edge_home"], kwargs["prob_home_win"], kwargs["ml_home_price"], home_conf),
            ("AWAY", away_team, kwargs["ml_edge_away"], kwargs["prob_away_win"], kwargs["ml_away_price"], away_conf),
        ):
            if ml_edge > self.MIN_EDGE_ML_PROB and ml_price and data_conf >= 0.5 and (isinstance(ml_price, int) and ml_price >= self.MAX_ML_PRICE):
                prob_cal = self._calibrate_win_prob(raw_prob)
                ev = self._calculate_ev(prob_cal, ml_price)
                if ev >= min_ev_standard:
                    conf_label, conf_score = self._classify_confidence(prob_cal, ev)
                    recs.append({
                        "market_type": "MONEYLINE",
                        "pick": team,
                        "side": side,
                        "line": None,
                        "price": ml_price,
                        "prob": round(prob_cal, 4),
                        "edge": round(ml_edge, 4),
                        "ev_per_unit": round(ev, 4),
                        "selection": f"{team} ML ({ml_price:+d})",
                        "confidence": conf_label,
                        "confidence_0_100": conf_score,
                    })

        # 3. Total (Over/Under)
        if kwargs.get("has_total"):
            total_edge = kwargs["total_edge"]
            mu_final_total = kwargs["mu_final_total"]
            mu_market_total = kwargs["mu_market_total"]

            if total_edge >= min_edge_total:
                if mu_final_total > mu_market_total:
                    pick = "OVER"
                    prob = kwargs["prob_over"]
                else:
                    pick = "UNDER"
                    prob = kwargs["prob_under"]

                price = market_snapshot.get("total_over_price" if pick == "OVER" else "total_under_price", -110)
                prob_cal = self._calibrate_win_prob(prob)
                ev = self._calculate_ev(prob_cal, price or -110)

                if ev >= min_ev_total:
                    conf_label, conf_score = self._classify_confidence(prob_cal, ev)
                    recs.append({
                        "market_type": "TOTAL",
                        "pick": pick,
                        "side": pick,
                        "line": mu_market_total,
                        "price": price,
                        "prob": round(prob_cal, 4),
                        "edge": round(total_edge, 2),
                        "ev_per_unit": round(ev, 4),
                        "selection": f"{pick} {mu_market_total}",
                        "confidence": conf_label,
                        "confidence_0_100": conf_score,
                    })

        # 4. NRFI
        nrfi = kwargs.get("nrfi_result") or {}
        p_nrfi = nrfi.get("p_nrfi", 0.52) if isinstance(nrfi, dict) else 0.52

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
                conf_label, conf_score = self._classify_confidence(p_nrfi, ev)
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
                    "confidence": conf_label,
                    "confidence_0_100": conf_score,
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
