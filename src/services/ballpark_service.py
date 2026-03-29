"""
Ballpark Service — Park factors and stadium metadata for MLB model.

Provides:
- Park factor adjustments for run projections (runs, HR)
- Stadium coordinates for weather API lookups
- Roof/dome detection (weather irrelevant for domed stadiums)
"""

import json
import os
import math
from typing import Dict, Optional, Tuple

# Resolve path relative to this file
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
_STADIUMS_FILE = os.path.join(_DATA_DIR, "mlb_stadiums.json")


class BallparkService:
    """Stadium data, park factors, and travel distance calculations."""

    # Park factor baseline (100 = league average)
    BASELINE = 100

    def __init__(self):
        self._data = None
        self._abbreviations = None

    def _load(self):
        """Lazy-load stadium data."""
        if self._data is not None:
            return
        try:
            with open(_STADIUMS_FILE, "r") as f:
                raw = json.load(f)
            self._data = raw.get("stadiums", {})
            self._abbreviations = raw.get("team_abbreviations", {})
        except Exception as e:
            print(f"[BALLPARK] Error loading stadium data: {e}")
            self._data = {}
            self._abbreviations = {}

    # ── Public API ──────────────────────────────────────────────

    def get_stadium(self, team_name: str) -> Optional[Dict]:
        """Get full stadium info for a team."""
        self._load()
        # Try exact match first
        if team_name in self._data:
            return self._data[team_name]
        # Try abbreviation
        full_name = self._abbreviations.get(team_name)
        if full_name and full_name in self._data:
            return self._data[full_name]
        # Fuzzy: check if team_name is a substring of any team
        for key in self._data:
            if team_name.lower() in key.lower() or key.lower() in team_name.lower():
                return self._data[key]
        return None

    def get_park_factor_runs(self, team_name: str) -> float:
        """
        Get park factor for runs.

        Returns a multiplier relative to baseline 100.
        Example: Coors Field = 118 → 1.18x runs expected.
        """
        stadium = self.get_stadium(team_name)
        if not stadium:
            return 1.0  # Neutral fallback
        pf = stadium.get("park_factor_runs", self.BASELINE)
        return pf / self.BASELINE

    def get_park_factor_hr(self, team_name: str) -> float:
        """Get park factor for home runs. Returns multiplier (1.0 = neutral)."""
        stadium = self.get_stadium(team_name)
        if not stadium:
            return 1.0
        pf = stadium.get("park_factor_hr", self.BASELINE)
        return pf / self.BASELINE

    def get_coordinates(self, team_name: str) -> Optional[Tuple[float, float]]:
        """Get (latitude, longitude) for a team's stadium."""
        stadium = self.get_stadium(team_name)
        if not stadium:
            return None
        lat = stadium.get("lat")
        lon = stadium.get("lon")
        if lat is not None and lon is not None:
            return (lat, lon)
        return None

    def is_domed(self, team_name: str) -> bool:
        """
        Check if the stadium has a dome or retractable roof.

        If True, weather adjustments should be reduced/skipped.
        """
        stadium = self.get_stadium(team_name)
        if not stadium:
            return False
        roof = (stadium.get("roof") or "").lower()
        return roof in ("dome", "retractable")

    def get_elevation_ft(self, team_name: str) -> float:
        """Get stadium elevation in feet. Relevant for Coors Field altitude adjustment."""
        stadium = self.get_stadium(team_name)
        if not stadium:
            return 0.0
        return float(stadium.get("elevation_ft", 0))

    def get_run_adjustment(self, home_team: str) -> float:
        """
        Calculate run adjustment in points for the home team's park.

        Returns: adjustment to add to projected total runs.
        Example: Coors Field (+18% runs) → +1.6 runs on an 8.8-run total.
        """
        pf = self.get_park_factor_runs(home_team)
        # Convert factor to point adjustment.
        # Assume league-average game total is ~8.8 runs.
        # A park factor of 1.18 means 18% more runs → 8.8 * 0.18 = +1.58
        LEAGUE_AVG_TOTAL = 8.8
        adjustment = LEAGUE_AVG_TOTAL * (pf - 1.0)
        return round(adjustment, 2)

    def get_altitude_adjustment(self, home_team: str) -> float:
        """
        Additional altitude-based adjustment.

        Only significant for Coors Field (5,280 ft).
        Ball carries ~9% farther per 1,000 ft of elevation.
        """
        elev = self.get_elevation_ft(home_team)
        if elev < 2000:
            return 0.0
        # Scaling: significant only above 2000 ft
        # Coors (5280 ft) → ~0.5 runs extra beyond park factor
        adj = (elev - 2000) / 3000 * 0.5
        return round(min(adj, 0.8), 2)

    def calculate_travel_distance(self, team_a: str, team_b: str) -> float:
        """
        Calculate great-circle distance between two teams' stadiums in miles.

        Used for travel fatigue adjustments.
        """
        coords_a = self.get_coordinates(team_a)
        coords_b = self.get_coordinates(team_b)
        if not coords_a or not coords_b:
            return 0.0

        lat1, lon1 = math.radians(coords_a[0]), math.radians(coords_a[1])
        lat2, lon2 = math.radians(coords_b[0]), math.radians(coords_b[1])

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))

        # Earth radius in miles
        R = 3956
        return round(R * c, 1)

    def get_all_teams(self) -> list:
        """Return list of all team names."""
        self._load()
        return list(self._data.keys())

    def resolve_team_name(self, raw_name: str) -> Optional[str]:
        """Resolve abbreviation or partial name to canonical full team name."""
        self._load()
        # Exact
        if raw_name in self._data:
            return raw_name
        # Abbreviation
        full = self._abbreviations.get(raw_name)
        if full:
            return full
        # Fuzzy substring
        raw_lower = raw_name.lower()
        for key in self._data:
            if raw_lower in key.lower():
                return key
        # Try city name match
        for key, info in self._data.items():
            if raw_lower in info.get("city", "").lower():
                return key
        return None


if __name__ == "__main__":
    svc = BallparkService()

    print("=== Ballpark Service Test ===")
    print(f"Teams loaded: {len(svc.get_all_teams())}")

    # Test park factors
    for team in ["Colorado Rockies", "San Francisco Giants", "New York Yankees", "Miami Marlins"]:
        pf_r = svc.get_park_factor_runs(team)
        pf_hr = svc.get_park_factor_hr(team)
        adj = svc.get_run_adjustment(team)
        alt = svc.get_altitude_adjustment(team)
        domed = svc.is_domed(team)
        print(f"\n{team}:")
        print(f"  Runs PF: {pf_r:.2f} | HR PF: {pf_hr:.2f} | Run Adj: {adj:+.2f}")
        print(f"  Altitude Adj: {alt:+.2f} | Domed: {domed}")

    # Test abbreviation resolution
    print(f"\nResolve 'NYY' → {svc.resolve_team_name('NYY')}")
    print(f"Resolve 'Dodgers' → {svc.resolve_team_name('Dodgers')}")

    # Test distance
    dist = svc.calculate_travel_distance("New York Yankees", "Los Angeles Dodgers")
    print(f"\nNYY → LAD distance: {dist} miles")

    dist2 = svc.calculate_travel_distance("New York Yankees", "New York Mets")
    print(f"NYY → NYM distance: {dist2} miles")
