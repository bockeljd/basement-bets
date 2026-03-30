"""
MLB NRFI Service — First-inning data aggregation for No Run First Inning bets.

Provides:
- Pitcher first-inning statistics (ERA, WHIP, K rate)
- Team first-inning scoring rates
- Historical NRFI probability calculation
- NRFI model inputs

Data sources:
- MLB Stats API game logs → first-inning linescore extraction
- pybaseball (when available) → pitcher game logs for 1st-inning splits
"""

import datetime
import requests
from typing import Dict, List, Optional

from src.services.mlb_service import MLBService
from src.services.ballpark_service import BallparkService


class MLBNRFIService:
    """
    Aggregates first-inning specific data for NRFI modeling.

    Key metrics:
    - Pitcher 1st-inning ERA/WHIP (how well they handle the top of the order)
    - Team 1st-inning scoring rate (how often a team scores in the 1st)
    - Historical NRFI rate for pitcher-team matchups
    """

    STATS_API_BASE = "https://statsapi.mlb.com/api/v1"

    # League-average 1st-inning scoring rate (~28% of half-innings produce a run)
    LEAGUE_AVG_1ST_INN_SCORING_PCT = 0.28

    # League-average NRFI rate (~52% of games have zero runs in the 1st)
    LEAGUE_AVG_NRFI_RATE = 0.52

    def __init__(self):
        self.mlb_service = MLBService()
        self.ballpark = BallparkService()
        self._cache: Dict[str, any] = {}

    def get_pitcher_first_inning_stats(self, player_id: int, season: int = None) -> Dict:
        """
        Estimate a pitcher's first-inning effectiveness.

        Ideally uses game-log level data to compute actual 1st-inning ERA.
        When full data isn't available, approximates from season stats.

        Returns:
            {
                "first_inn_era": 3.50,
                "first_inn_whip": 1.10,
                "first_inn_k_rate": 0.28,
                "nrfi_rate": 0.72,  # % of starts with 0 runs in their half
                "starts_sampled": 25,
                "confidence": 0.8
            }
        """
        if season is None:
            season = datetime.date.today().year

        cache_key = f"nrfi_pitcher:{player_id}:{season}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Strategy: Fetch pitcher game logs, extract 1st-inning data
        game_logs = self._fetch_pitcher_game_logs(player_id, season)

        if game_logs and len(game_logs) >= 3:
            result = self._compute_first_inning_from_logs(game_logs, player_id)
        else:
            # Fallback: Approximate from season stats
            season_stats = self.mlb_service.get_pitcher_season_stats(player_id, season)
            result = self._approximate_first_inning(season_stats, player_id)

        self._cache[cache_key] = result
        return result

    def get_team_first_inning_scoring(self, team_name: str, season: int = None) -> Dict:
        """
        Get team's first-inning offensive production.

        Returns:
            {
                "scoring_pct": 0.30,  # % of games team scores in 1st inning
                "avg_runs_1st": 0.42,  # avg runs scored per 1st inning
                "games_sampled": 80,
                "confidence": 0.7
            }
        """
        if season is None:
            season = datetime.date.today().year

        cache_key = f"nrfi_team:{team_name}:{season}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Default / fallback values
        result = {
            "scoring_pct": self.LEAGUE_AVG_1ST_INN_SCORING_PCT,
            "avg_runs_1st": 0.40,
            "games_sampled": 0,
            "confidence": 0.3,
        }

        # TODO: Use pybaseball game logs or pre-computed data to get actual
        # team 1st-inning scoring rates. For now, adjust based on team
        # overall offensive strength.
        team_batting = self.mlb_service.get_team_batting_rating(team_name, season)
        rpg = team_batting.get("runs_per_game", MLBService.LEAGUE_AVG_RUNS_PER_GAME)

        # Rough approximation: better offenses score more in the 1st inning
        # Teams scoring ~5.0 RPG have ~32% 1st-inning scoring rate
        # Teams scoring ~3.5 RPG have ~24% 1st-inning scoring rate
        ratio = rpg / MLBService.LEAGUE_AVG_RUNS_PER_GAME
        result["scoring_pct"] = round(self.LEAGUE_AVG_1ST_INN_SCORING_PCT * ratio, 3)
        result["avg_runs_1st"] = round(0.40 * ratio, 2)
        result["confidence"] = team_batting.get("confidence", 0.3)

        self._cache[cache_key] = result
        return result

    def calculate_nrfi_probability(self,
                                   home_pitcher_id: int,
                                   away_pitcher_id: int,
                                   home_team: str,
                                   away_team: str,
                                   park_factor: float = 1.0) -> Dict:
        """
        Calculate the probability of NRFI for a specific matchup.

        P(NRFI) = P(no_run_top_1st) × P(no_run_bottom_1st)

        Where each half-inning probability depends on:
        - Pitcher quality (1st-inning stats)
        - Opposing team's 1st-inning scoring tendency
        - Park factor
        """
        # Get pitcher 1st-inning data
        home_sp = self.get_pitcher_first_inning_stats(home_pitcher_id) if home_pitcher_id else None
        away_sp = self.get_pitcher_first_inning_stats(away_pitcher_id) if away_pitcher_id else None

        # Get team 1st-inning offensive data
        home_batting_1st = self.get_team_first_inning_scoring(home_team)
        away_batting_1st = self.get_team_first_inning_scoring(away_team)

        # Calculate P(no run) for each half inning
        # Top of 1st: Away team hitting vs Home SP
        p_run_top = self._probability_of_scoring(
            pitcher_stats=home_sp,
            batting_stats=away_batting_1st,
            park_factor=park_factor,
        )

        # Bottom of 1st: Home team hitting vs Away SP
        p_run_bottom = self._probability_of_scoring(
            pitcher_stats=away_sp,
            batting_stats=home_batting_1st,
            park_factor=park_factor,
        )

        # P(NRFI) = P(no run top) × P(no run bottom)
        p_no_run_top = 1.0 - p_run_top
        p_no_run_bottom = 1.0 - p_run_bottom
        p_nrfi = p_no_run_top * p_no_run_bottom

        # Confidence: average of component confidences
        confidences = []
        if home_sp:
            confidences.append(home_sp.get("confidence", 0.3))
        if away_sp:
            confidences.append(away_sp.get("confidence", 0.3))
        confidences.append(home_batting_1st.get("confidence", 0.3))
        confidences.append(away_batting_1st.get("confidence", 0.3))
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.3

        return {
            "p_nrfi": round(p_nrfi, 4),
            "p_yrfi": round(1.0 - p_nrfi, 4),
            "p_no_run_top": round(p_no_run_top, 4),
            "p_no_run_bottom": round(p_no_run_bottom, 4),
            "home_sp_nrfi_rate": home_sp.get("nrfi_rate", 0.72) if home_sp else 0.72,
            "away_sp_nrfi_rate": away_sp.get("nrfi_rate", 0.72) if away_sp else 0.72,
            "home_team_1st_scoring_pct": home_batting_1st.get("scoring_pct", 0.28),
            "away_team_1st_scoring_pct": away_batting_1st.get("scoring_pct", 0.28),
            "park_factor": park_factor,
            "confidence": round(avg_confidence, 2),
        }

    def _probability_of_scoring(self,
                                pitcher_stats: Optional[Dict],
                                batting_stats: Dict,
                                park_factor: float = 1.0) -> float:
        """
        Estimate probability of a team scoring in one half-inning.

        Blends pitcher quality with team offensive tendency.
        """
        # Pitcher component: convert NRFI rate to scoring probability
        if pitcher_stats:
            pitcher_scoring = 1.0 - pitcher_stats.get("nrfi_rate", 0.72)
            pitcher_weight = pitcher_stats.get("confidence", 0.5)
        else:
            pitcher_scoring = self.LEAGUE_AVG_1ST_INN_SCORING_PCT
            pitcher_weight = 0.3

        # Team batting component
        team_scoring = batting_stats.get("scoring_pct", self.LEAGUE_AVG_1ST_INN_SCORING_PCT)
        team_weight = batting_stats.get("confidence", 0.3)

        # Weighted blend (pitcher is more important in the 1st inning)
        # Pitcher gets 60% weight, team offense gets 40%
        total_weight = pitcher_weight * 0.6 + team_weight * 0.4
        if total_weight > 0:
            p = (pitcher_scoring * pitcher_weight * 0.6 + team_scoring * team_weight * 0.4) / total_weight
        else:
            p = self.LEAGUE_AVG_1ST_INN_SCORING_PCT

        # Park factor adjustment
        # Parks that boost runs also boost 1st-inning scoring
        p *= park_factor

        # Clamp
        return max(0.05, min(0.60, p))

    def _fetch_pitcher_game_logs(self, player_id: int, season: int) -> List[Dict]:
        """Fetch pitcher game logs from MLB Stats API."""
        url = f"{self.STATS_API_BASE}/people/{player_id}/stats"
        params = {
            "stats": "gameLog",
            "group": "pitching",
            "season": season,
        }

        try:
            resp = requests.get(url, params=params, timeout=6)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[NRFI] Game log fetch error for {player_id}: {e}")
            return []

        logs = []
        for group in data.get("stats", []):
            for split in group.get("splits", []):
                stat = split.get("stat", {})
                logs.append({
                    "date": split.get("date"),
                    "opponent": split.get("opponent", {}).get("name"),
                    "innings_pitched": MLBService._safe_float(stat.get("inningsPitched")),
                    "runs": stat.get("runs", 0),
                    "earned_runs": stat.get("earnedRuns", 0),
                    "hits": stat.get("hits", 0),
                    "walks": stat.get("baseOnBalls", 0),
                    "strikeouts": stat.get("strikeOuts", 0),
                    "home_runs": stat.get("homeRuns", 0),
                })

        return logs

    def _compute_first_inning_from_logs(self, game_logs: List[Dict], player_id: int) -> Dict:
        """
        Compute first-inning approximation from game logs.

        Since MLB Stats API game logs don't give inning-by-inning splits,
        we approximate: if a pitcher's first 1.0 IP frequently has 0 runs,
        we can estimate their 1st-inning effectiveness.

        Better approximation: pitchers who allow fewer runs/IP overall
        tend to have cleaner first innings. Strong K-rate pitchers
        dominate the 1st inning especially (facing lineup in order).
        """
        if not game_logs:
            return self._approximate_first_inning(None, player_id)

        total_starts = len(game_logs)
        total_runs = sum(g.get("runs", 0) for g in game_logs)
        total_ip = sum(g.get("innings_pitched", 0) or 0 for g in game_logs)
        total_hits = sum(g.get("hits", 0) for g in game_logs)
        total_walks = sum(g.get("walks", 0) for g in game_logs)
        total_k = sum(g.get("strikeouts", 0) for g in game_logs)

        if total_ip <= 0:
            return self._approximate_first_inning(None, player_id)

        # Season-level stats
        era = (total_runs / total_ip) * 9.0
        whip = (total_hits + total_walks) / total_ip
        k_rate = total_k / total_ip

        # First-inning approximation:
        # Pitchers typically perform ~10% better in the 1st inning
        # (lineup is in order, pitcher is fresh, adrenaline)
        first_inn_era = era * 0.90
        first_inn_whip = whip * 0.92
        first_inn_k_rate = k_rate * 1.05

        # Estimate NRFI rate (pitcher's half of the inning)
        # Based on runs/IP: if ERA ~3.00, first-inning run rate ≈ 0.30/inn → 70% NRFI for their half
        first_inn_run_rate = first_inn_era / 9.0
        nrfi_rate = max(0.40, min(0.90, 1.0 - first_inn_run_rate))

        confidence = min(1.0, total_starts / 20)  # Full confidence at 20+ starts

        return {
            "first_inn_era": round(first_inn_era, 2),
            "first_inn_whip": round(first_inn_whip, 2),
            "first_inn_k_rate": round(first_inn_k_rate, 2),
            "nrfi_rate": round(nrfi_rate, 3),
            "starts_sampled": total_starts,
            "confidence": round(confidence, 2),
            "method": "game_log_approximation",
        }

    def _approximate_first_inning(self, season_stats: Optional[Dict], player_id: int) -> Dict:
        """
        Fallback: approximate 1st-inning stats from season aggregates.
        """
        if season_stats:
            era = season_stats.get("era") or 4.10
            whip = season_stats.get("whip") or 1.30
            k_per_9 = season_stats.get("k_per_9") or 7.0
        else:
            era = 4.10
            whip = 1.30
            k_per_9 = 7.0

        # Approximations (pitchers are ~10% better in 1st inning)
        first_inn_era = era * 0.90
        first_inn_whip = whip * 0.92
        first_inn_k_rate = (k_per_9 / 9.0) * 1.05

        first_inn_run_rate = first_inn_era / 9.0
        nrfi_rate = max(0.40, min(0.90, 1.0 - first_inn_run_rate))

        return {
            "first_inn_era": round(first_inn_era, 2),
            "first_inn_whip": round(first_inn_whip, 2),
            "first_inn_k_rate": round(first_inn_k_rate, 2),
            "nrfi_rate": round(nrfi_rate, 3),
            "starts_sampled": 0,
            "confidence": 0.3 if season_stats else 0.1,
            "method": "season_approximation",
        }


if __name__ == "__main__":
    svc = MLBNRFIService()

    print("=== NRFI Service Test ===\n")

    # Test team 1st-inning scoring
    for team in ["New York Yankees", "Los Angeles Dodgers", "Miami Marlins"]:
        data = svc.get_team_first_inning_scoring(team)
        print(f"{team}: 1st-Inn Scoring {data['scoring_pct']:.1%} | Avg Runs: {data['avg_runs_1st']}")

    print()

    # Test full NRFI calculation (with placeholder pitcher IDs)
    # Will use approximation method since we don't have real IDs here
    result = svc.calculate_nrfi_probability(
        home_pitcher_id=None,
        away_pitcher_id=None,
        home_team="New York Yankees",
        away_team="Boston Red Sox",
        park_factor=1.04,
    )
    print(f"NYY vs BOS NRFI Probability: {result['p_nrfi']:.1%}")
    print(f"  P(no run top 1st): {result['p_no_run_top']:.1%}")
    print(f"  P(no run bot 1st): {result['p_no_run_bottom']:.1%}")
