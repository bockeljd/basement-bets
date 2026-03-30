"""
MLB Service — Data fetching for MLB betting model.

Provides:
- Probable pitcher lookups via MLB Stats API (free, no key)
- Pitcher statistics via pybaseball (FanGraphs / Statcast)
- Team batting statistics via pybaseball
- Final scores via MLB Stats API (for grading)
- Action Network odds integration (primary odds source)

Strategy: pybaseball is used locally to pre-compute & cache pitcher/team
ratings. For Vercel serverless, cached values are read from the DB.
"""

import os
import json
import math
import requests
import datetime
from typing import Dict, List, Optional, Any, Tuple

# pybaseball is optional — not available on Vercel (too large)
try:
    import pybaseball  # type: ignore
    HAS_PYBASEBALL = True
except ImportError:
    HAS_PYBASEBALL = False

from src.services.ballpark_service import BallparkService


class MLBService:
    """
    MLB data service — wraps MLB Stats API and pybaseball.

    Designed for the same pre-compute + cache pattern as NCAAM Torvik service:
    heavy pybaseball calls run locally → results cached to DB → Vercel reads cache.
    """

    # MLB Stats API (free, no key required)
    STATS_API_BASE = "https://statsapi.mlb.com/api/v1"

    # Action Network (primary odds source — same as NCAAM)
    AN_HEADERS = {
        'Authority': 'api.actionnetwork.com',
        'Accept': 'application/json',
        'Origin': 'https://www.actionnetwork.com',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36'
    }

    # League-average benchmarks (updated each season)
    LEAGUE_AVG_ERA = 4.10
    LEAGUE_AVG_FIP = 4.05
    LEAGUE_AVG_WOBA = 0.315
    LEAGUE_AVG_wRC_PLUS = 100
    LEAGUE_AVG_RUNS_PER_GAME = 4.40  # per team

    def __init__(self):
        self.ballpark = BallparkService()
        self._pitcher_cache: Dict[str, Dict] = {}  # player_id -> stats
        self._team_cache: Dict[str, Dict] = {}     # team_name -> batting stats
        self._schedule_cache: Dict[str, Any] = {}   # date -> schedule data

    # ── MLB Stats API: Schedule & Probables ────────────────────

    def get_schedule(self, date: str = None) -> List[Dict]:
        """
        Fetch MLB schedule for a date with probable pitchers.

        Args:
            date: YYYY-MM-DD format. Defaults to today.

        Returns:
            List of game dicts with home/away teams, probable pitchers, gamePk.
        """
        if date is None:
            date = datetime.date.today().strftime("%Y-%m-%d")

        cache_key = f"schedule:{date}"
        if cache_key in self._schedule_cache:
            return self._schedule_cache[cache_key]

        url = f"{self.STATS_API_BASE}/schedule"
        params = {
            "sportId": 1,  # MLB
            "date": date,
            "hydrate": "probablePitcher(note),linescore",
        }

        try:
            resp = requests.get(url, params=params, timeout=8)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[MLB] Schedule API error: {e}")
            return []

        games = []
        for date_entry in data.get("dates", []):
            for game in date_entry.get("games", []):
                game_pk = game.get("gamePk")
                status = game.get("status", {}).get("detailedState", "")

                teams = game.get("teams", {})
                home_info = teams.get("home", {})
                away_info = teams.get("away", {})

                home_team = home_info.get("team", {}).get("name", "")
                away_team = away_info.get("team", {}).get("name", "")

                # Probable pitchers
                home_pitcher = home_info.get("probablePitcher", {})
                away_pitcher = away_info.get("probablePitcher", {})

                # Linescore (for grading)
                linescore = game.get("linescore", {})

                games.append({
                    "game_pk": game_pk,
                    "game_date": game.get("gameDate"),
                    "status": status,
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_pitcher": {
                        "id": home_pitcher.get("id"),
                        "name": home_pitcher.get("fullName"),
                        "note": home_pitcher.get("note"),
                    } if home_pitcher else None,
                    "away_pitcher": {
                        "id": away_pitcher.get("id"),
                        "name": away_pitcher.get("fullName"),
                        "note": away_pitcher.get("note"),
                    } if away_pitcher else None,
                    "linescore": linescore,
                    "home_score": home_info.get("score"),
                    "away_score": away_info.get("score"),
                })

        self._schedule_cache[cache_key] = games
        print(f"[MLB] Loaded {len(games)} games for {date}")
        return games

    def get_final_scores(self, date: str = None) -> List[Dict]:
        """
        Get final scores for MLB games on a date.
        Used by grading service.
        """
        games = self.get_schedule(date)
        finals = []
        for g in games:
            status = (g.get("status") or "").lower()
            if "final" in status:
                finals.append({
                    "game_pk": g["game_pk"],
                    "home_team": g["home_team"],
                    "away_team": g["away_team"],
                    "home_score": g.get("home_score"),
                    "away_score": g.get("away_score"),
                    "linescore": g.get("linescore"),
                    "final": True,
                })
        return finals

    def get_first_inning_scores(self, game_pk: int) -> Optional[Dict]:
        """
        Get first inning scoring for a specific game.
        Used for NRFI grading.
        """
        url = f"{self.STATS_API_BASE}/game/{game_pk}/linescore"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[MLB] Linescore API error for {game_pk}: {e}")
            return None

        innings = data.get("innings", [])
        if not innings:
            return None

        first = innings[0]
        return {
            "away_runs_1st": first.get("away", {}).get("runs", 0),
            "home_runs_1st": first.get("home", {}).get("runs", 0),
            "nrfi": (first.get("away", {}).get("runs", 0) == 0 and
                     first.get("home", {}).get("runs", 0) == 0),
        }

    # ── MLB Stats API: Player Stats ────────────────────────────

    def get_pitcher_season_stats(self, player_id: int, season: int = None) -> Optional[Dict]:
        """
        Fetch season pitching stats from MLB Stats API.

        This is the lightweight alternative when pybaseball is not available.
        Returns basic stats: ERA, WHIP, K/9, BB/9, IP, W, L, etc.
        """
        if season is None:
            season = datetime.date.today().year

        cache_key = f"pitcher:{player_id}:{season}"
        if cache_key in self._pitcher_cache:
            return self._pitcher_cache[cache_key]

        url = f"{self.STATS_API_BASE}/people/{player_id}"
        params = {
            "hydrate": f"stats(group=[pitching],type=[season],season={season})",
        }

        try:
            resp = requests.get(url, params=params, timeout=8)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[MLB] Player stats API error for {player_id}: {e}")
            return None

        people = data.get("people", [])
        if not people:
            return None

        person = people[0]
        stats_groups = person.get("stats", [])

        for group in stats_groups:
            splits = group.get("splits", [])
            if splits:
                stat = splits[0].get("stat", {})
                result = {
                    "player_id": player_id,
                    "name": person.get("fullName"),
                    "throws": person.get("pitchHand", {}).get("code"),  # L or R
                    "era": self._safe_float(stat.get("era")),
                    "whip": self._safe_float(stat.get("whip")),
                    "innings_pitched": self._safe_float(stat.get("inningsPitched")),
                    "strikeouts": stat.get("strikeOuts", 0),
                    "walks": stat.get("baseOnBalls", 0),
                    "hits_allowed": stat.get("hits", 0),
                    "home_runs_allowed": stat.get("homeRuns", 0),
                    "games_started": stat.get("gamesStarted", 0),
                    "wins": stat.get("wins", 0),
                    "losses": stat.get("losses", 0),
                    "k_per_9": self._safe_float(stat.get("strikeoutsPer9Inn")),
                    "bb_per_9": self._safe_float(stat.get("walksPer9Inn")),
                    "hr_per_9": self._safe_float(stat.get("homeRunsPer9")),
                    "avg_against": self._safe_float(stat.get("avg")),
                    "obp_against": self._safe_float(stat.get("obp")),
                    "slg_against": self._safe_float(stat.get("slg")),
                }
                self._pitcher_cache[cache_key] = result
                return result

        return None

    # ── Pitcher Rating Engine ──────────────────────────────────

    def calculate_pitcher_rating(self, stats: Dict) -> Dict:
        """
        Calculate a composite pitcher quality rating from raw stats.
        Always returns a dict — never raises.
        """
        if not stats or not isinstance(stats, dict):
            return {"runs_per_9": self.LEAGUE_AVG_ERA, "tier": "UNKNOWN", "confidence": 0.0}

        era = stats.get("era") or self.LEAGUE_AVG_ERA
        whip = stats.get("whip") or 1.30
        ip = stats.get("innings_pitched") or 0

        # Calculate FIP from components if not provided directly
        fip = stats.get("fip")
        if fip is None:
            k = stats.get("strikeouts", 0)
            bb = stats.get("walks", 0)
            hr = stats.get("home_runs_allowed", 0)
            if ip and ip > 0:
                # FIP constant ≈ 3.10 (varies by year, close enough)
                FIP_CONSTANT = 3.10
                fip = ((13 * hr + 3 * bb - 2 * k) / ip) + FIP_CONSTANT
            else:
                fip = self.LEAGUE_AVG_FIP

        # xERA proxy: K-BB% maps roughly to run prevention
        k_per_9 = stats.get("k_per_9") or 7.0
        bb_per_9 = stats.get("bb_per_9") or 3.0
        k_bb_diff = k_per_9 - bb_per_9
        # Higher K-BB → lower xERA. Rough mapping: xERA ≈ 5.5 - 0.3 * K-BB_diff
        xera_proxy = max(2.0, min(6.5, 5.5 - 0.3 * k_bb_diff))

        # Confidence based on IP (more innings = more reliable)
        if ip >= 100:
            confidence = 1.0
        elif ip >= 50:
            confidence = 0.8
        elif ip >= 20:
            confidence = 0.5
        else:
            confidence = 0.3

        # Blend with confidence-adjusted weights
        if confidence >= 0.8:
            # Full-season sample: trust FIP + ERA
            runs_per_9 = (fip * 0.40) + (era * 0.25) + (xera_proxy * 0.20) + (whip * 2.8 * 0.15)
        else:
            # Small sample: lean more on FIP (peripherals) and league average
            runs_per_9 = (fip * 0.35) + (self.LEAGUE_AVG_ERA * 0.30) + (xera_proxy * 0.20) + (whip * 2.8 * 0.15)

        # Tier classification
        if runs_per_9 <= 3.00:
            tier = "ACE"
        elif runs_per_9 <= 3.60:
            tier = "ELITE"
        elif runs_per_9 <= 4.20:
            tier = "SOLID"
        elif runs_per_9 <= 4.80:
            tier = "AVERAGE"
        elif runs_per_9 <= 5.50:
            tier = "BELOW_AVG"
        else:
            tier = "POOR"

        return {
            "runs_per_9": round(runs_per_9, 2),
            "fip": round(fip, 2),
            "era": round(era, 2),
            "xera_proxy": round(xera_proxy, 2),
            "whip": round(whip, 2),
            "k_per_9": round(k_per_9, 1),
            "bb_per_9": round(bb_per_9, 1),
            "tier": tier,
            "confidence": confidence,
            "innings_pitched": ip,
        }

    # ── Team Batting Rating ────────────────────────────────────

    def get_team_batting_rating(self, team_name: str, season: int = None) -> Dict:
        """
        Get team offensive quality rating.

        When pybaseball is available, pulls wOBA, wRC+, ISO, K%, BB%.
        Otherwise, returns league-average defaults.

        Returns runs_per_game estimate for this team's offense.
        """
        # TODO: When pybaseball is available, use:
        # batting_stats(season) filtered by team
        # For now, use MLB Stats API team stats endpoint

        if season is None:
            season = datetime.date.today().year

        cache_key = f"team_batting:{team_name}:{season}"
        if cache_key in self._team_cache:
            return self._team_cache[cache_key]

        # Try MLB Stats API team stats
        team_id = self._resolve_team_id(team_name)
        if team_id:
            stats = self._fetch_team_batting_stats(team_id, season)
            if stats:
                self._team_cache[cache_key] = stats
                return stats

        # Fallback: league average
        return {
            "runs_per_game": self.LEAGUE_AVG_RUNS_PER_GAME,
            "wrc_plus": 100,
            "obp": 0.320,
            "slg": 0.410,
            "iso": 0.160,
            "k_pct": 0.220,
            "bb_pct": 0.085,
            "woba": self.LEAGUE_AVG_WOBA,
            "tier": "UNKNOWN",
            "confidence": 0.3,
        }

    def _fetch_team_batting_stats(self, team_id: int, season: int) -> Optional[Dict]:
        """Fetch team batting stats from MLB Stats API."""
        url = f"{self.STATS_API_BASE}/teams/{team_id}/stats"
        params = {
            "stats": "season",
            "group": "hitting",
            "season": season,
        }
        try:
            resp = requests.get(url, params=params, timeout=8)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[MLB] Team batting stats error for {team_id}: {e}")
            return None

        for group in data.get("stats", []):
            splits = group.get("splits", [])
            if splits:
                stat = splits[0].get("stat", {})
                games = stat.get("gamesPlayed", 1) or 1
                runs = stat.get("runs", 0)
                rpg = runs / games if games > 0 else self.LEAGUE_AVG_RUNS_PER_GAME

                obp = self._safe_float(stat.get("obp")) or 0.320
                slg = self._safe_float(stat.get("slg")) or 0.410
                avg = self._safe_float(stat.get("avg")) or 0.250
                iso = slg - avg if slg and avg else 0.160

                # Tier classification
                if rpg >= 5.2:
                    tier = "ELITE"
                elif rpg >= 4.6:
                    tier = "ABOVE_AVG"
                elif rpg >= 4.0:
                    tier = "AVERAGE"
                elif rpg >= 3.5:
                    tier = "BELOW_AVG"
                else:
                    tier = "WEAK"

                return {
                    "runs_per_game": round(rpg, 2),
                    "obp": round(obp, 3),
                    "slg": round(slg, 3),
                    "avg": round(avg, 3),
                    "iso": round(iso, 3),
                    "runs": runs,
                    "games": games,
                    "tier": tier,
                    "confidence": min(1.0, games / 60),  # Confident after ~60 games
                }
        return None

    # ── Team vs Pitcher Platoon Splits ─────────────────────────

    def get_platoon_adjustment(self, pitcher_throws: str, team_name: str) -> float:
        """
        Calculate platoon adjustment based on pitcher handedness vs team batting splits.

        LHP facing a team that crushes lefties → bump runs up.
        RHP facing a team that struggles vs righties → bump runs down.

        Returns: adjustment in runs (positive = more runs expected).
        """
        # TODO: When pybaseball is available, pull vs-LHP and vs-RHP splits.
        # For now, use a small default platoon adjustment:
        # ~60% of the league is RHH, so LHP face more same-side matchups.
        # LHP slight advantage (platoon advantage goes to pitcher).
        if pitcher_throws == "L":
            return -0.10  # LHP slight edge (less familiar for most lineups)
        elif pitcher_throws == "R":
            return 0.0  # Neutral (most lineups built to face RHP)
        return 0.0

    # ── Bullpen Strength ───────────────────────────────────────

    def get_bullpen_rating(self, team_name: str, season: int = None) -> Dict:
        """
        Estimate bullpen quality for a team.

        Returns a runs-per-9 estimate for the bullpen.
        Used to adjust total runs projection (bullpen pitches ~4 innings avg).
        """
        # TODO: Pull reliever stats via pybaseball when available.
        # For now, return league-average bullpen estimate.
        return {
            "bullpen_era": 4.00,
            "bullpen_whip": 1.28,
            "bullpen_tier": "AVERAGE",
            "innings_per_game": 3.8,  # Average bullpen usage
            "confidence": 0.3,
        }

    # ── Action Network Odds (Primary Source) ───────────────────

    def fetch_mlb_odds_action_network(self, dates: List[str] = None) -> List[Dict]:
        """
        Fetch MLB odds from Action Network.
        Same approach as NCAAM — Action Network is the primary odds source.

        Returns list of events in the same format as ActionNetworkClient.fetch_odds().
        """
        from src.action_network import get_todays_games

        if dates is None:
            today = datetime.date.today().strftime('%Y%m%d')
            dates = [today]

        print(f"[MLB] Fetching odds from Action Network for dates: {dates}")
        games = get_todays_games('mlb', dates, headers=self.AN_HEADERS)
        print(f"[MLB] Retrieved {len(games)} games from Action Network")
        return games

    # ── Run Projection Engine ──────────────────────────────────

    def project_runs(self,
                     pitcher_rating: Dict,
                     opposing_batting: Dict,
                     park_factor_runs: float = 1.0,
                     weather_adjustment: float = 0.0,
                     bullpen_rating: Dict = None,
                     platoon_adj: float = 0.0) -> Dict:
        """
        Project runs scored by one team (one side of the game).
        Always returns a dict — never raises.
        """
        # Defensive: ensure inputs are dicts
        if not pitcher_rating or not isinstance(pitcher_rating, dict):
            pitcher_rating = {"runs_per_9": self.LEAGUE_AVG_ERA}
        if not opposing_batting or not isinstance(opposing_batting, dict):
            opposing_batting = {"runs_per_game": self.LEAGUE_AVG_RUNS_PER_GAME}

        league_avg_rpg = self.LEAGUE_AVG_RUNS_PER_GAME  # 4.40

        # Offensive strength relative to league
        team_rpg = opposing_batting.get("runs_per_game", league_avg_rpg)
        off_factor = team_rpg / league_avg_rpg

        # Pitcher quality: runs_per_9 is the pitcher's expected run rate
        pitcher_r9 = pitcher_rating.get("runs_per_9", self.LEAGUE_AVG_ERA)
        # What fraction the pitcher pitches (typically ~5.5 innings for starter)
        sp_innings = 5.5
        bp_innings = 3.5

        # Starter contribution: pitcher's runs_per_9 scaled to their innings
        sp_runs = (pitcher_r9 / 9.0) * sp_innings

        # Bullpen contribution
        if bullpen_rating:
            bp_era = bullpen_rating.get("bullpen_era", 4.00)
        else:
            bp_era = 4.00
        bp_runs = (bp_era / 9.0) * bp_innings

        # Raw projected runs = (SP runs + BP runs) * offensive adjustment
        raw_runs = (sp_runs + bp_runs) * off_factor

        # Apply park factor
        raw_runs *= park_factor_runs

        # Apply weather
        raw_runs += weather_adjustment / 2.0  # Weather adj is for the total; split between teams

        # Apply platoon
        raw_runs += platoon_adj

        # Floor at 1.5 runs (can't project less than that realistically)
        projected = max(1.5, raw_runs)

        return {
            "projected_runs": round(projected, 2),
            "sp_contribution": round(sp_runs, 2),
            "bp_contribution": round(bp_runs, 2),
            "off_factor": round(off_factor, 3),
            "park_factor": round(park_factor_runs, 3),
            "weather_adj": round(weather_adjustment / 2.0, 2),
            "platoon_adj": round(platoon_adj, 2),
        }

    # ── Utilities ──────────────────────────────────────────────

    def _resolve_team_id(self, team_name: str) -> Optional[int]:
        """Resolve team name to MLB Stats API team ID."""
        # Standard MLB team IDs
        TEAM_IDS = {
            "Arizona Diamondbacks": 109,
            "Atlanta Braves": 144,
            "Baltimore Orioles": 110,
            "Boston Red Sox": 111,
            "Chicago Cubs": 112,
            "Chicago White Sox": 145,
            "Cincinnati Reds": 113,
            "Cleveland Guardians": 114,
            "Colorado Rockies": 115,
            "Detroit Tigers": 116,
            "Houston Astros": 117,
            "Kansas City Royals": 118,
            "Los Angeles Angels": 108,
            "Los Angeles Dodgers": 119,
            "Miami Marlins": 146,
            "Milwaukee Brewers": 158,
            "Minnesota Twins": 142,
            "New York Mets": 121,
            "New York Yankees": 147,
            "Oakland Athletics": 133,
            "Philadelphia Phillies": 143,
            "Pittsburgh Pirates": 134,
            "San Diego Padres": 135,
            "San Francisco Giants": 137,
            "Seattle Mariners": 136,
            "St. Louis Cardinals": 138,
            "Tampa Bay Rays": 139,
            "Texas Rangers": 140,
            "Toronto Blue Jays": 141,
            "Washington Nationals": 120,
        }
        # Exact match
        if team_name in TEAM_IDS:
            return TEAM_IDS[team_name]
        # Fuzzy match
        name_lower = team_name.lower()
        for full, tid in TEAM_IDS.items():
            if name_lower in full.lower() or full.lower() in name_lower:
                return tid
        # Try resolving via ballpark service
        canonical = self.ballpark.resolve_team_name(team_name)
        if canonical and canonical in TEAM_IDS:
            return TEAM_IDS[canonical]
        return None

    @staticmethod
    def _safe_float(val) -> Optional[float]:
        """Safely convert a value to float."""
        if val is None or val == '':
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None


if __name__ == "__main__":
    svc = MLBService()

    print("=== MLB Service Test ===\n")

    # Test schedule
    print("--- Today's Schedule ---")
    games = svc.get_schedule()
    for g in games[:3]:
        home_p = g['home_pitcher']['name'] if g['home_pitcher'] else 'TBD'
        away_p = g['away_pitcher']['name'] if g['away_pitcher'] else 'TBD'
        print(f"  {g['away_team']} @ {g['home_team']}")
        print(f"    Pitchers: {away_p} vs {home_p}")
        print(f"    Status: {g['status']}")
        print()

    # Test pitcher stats (if games have pitchers)
    if games and games[0].get("home_pitcher") and games[0]["home_pitcher"].get("id"):
        pid = games[0]["home_pitcher"]["id"]
        print(f"--- Pitcher Stats (ID: {pid}) ---")
        stats = svc.get_pitcher_season_stats(pid)
        if stats:
            print(f"  {stats['name']}: ERA {stats['era']}, WHIP {stats['whip']}")
            rating = svc.calculate_pitcher_rating(stats)
            print(f"  Rating: {rating['runs_per_9']} R/9 ({rating['tier']})")
            print(f"  FIP: {rating['fip']}, Confidence: {rating['confidence']}")

    # Test Action Network odds
    print("\n--- Action Network MLB Odds ---")
    odds = svc.fetch_mlb_odds_action_network()
    for g in odds[:3]:
        print(f"  {g['away_team']} @ {g['home_team']}")
        if g.get('total_score'):
            print(f"    O/U: {g['total_score']}, Spread: {g.get('home_spread')}")
        if g.get('home_money_line'):
            print(f"    ML: Home {g['home_money_line']} / Away {g.get('away_money_line')}")
