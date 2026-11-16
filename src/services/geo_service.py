import math

class GeoService:
    """
    Calculates travel distance and altitude adjustments for NCAAM teams.
    """
    
    # High Altitude Schools (>4000 ft)
    HIGH_ALTITUDE_TEAMS = {
        "Wyoming", "Air Force", "Colorado", "Colorado State", "Denver", "Northern Colorado",
        "Utah", "Utah State", "BYU", "Utah Valley", "Weber State", "Southern Utah", "Utah Tech",
        "New Mexico", "New Mexico State", "Northern Arizona",
    }

    HIGH_ALTITUDE_CITIES = {
        "laramie", "colorado springs", "usaf academy", "boulder", "fort collins",
        "denver", "greeley", "salt lake city", "logan", "provo", "orem", "ogden",
        "cedar city", "st. george", "albuquerque", "las cruces", "flagstaff",
    }

    HIGH_ALTITUDE_STATES = {"CO", "WY", "UT", "NM"}

    # Coordinates (Approximate Lat/Lon for major schools - expandable)
    # This is a placeholder. In production, use a full CSV or API.
    # For now, we return 0 distance if unknown to be safe.
    TEAM_COORDS = {
        "Duke": (36.0014, -78.9382),
        "North Carolina": (35.9049, -79.0469),
        "Kansas": (38.9543, -95.2558),
        # ... add more as needed or integrate external data
    }

    @classmethod
    def is_high_altitude_team(cls, team_name: str) -> bool:
        t = str(team_name or "").strip().lower()
        if not t:
            return False
        for team in cls.HIGH_ALTITUDE_TEAMS:
            if team.lower() in t:
                return True
        return False

    def get_altitude_adjustment(
        self,
        home_team: str,
        neutral_site: bool = False,
        away_team: str = None,
        venue_city: str = None,
        venue_state: str = None,
    ) -> float:
        """
        Returns point adjustment for home team altitude advantage.
        Standard: +1.0 pts for high altitude venue vs non-altitude visitor.
        Returns 0.0 on neutral courts or when visiting team is also acclimated.
        """
        if neutral_site:
            return 0.0
        if away_team and self.is_high_altitude_team(away_team):
            return 0.0

        if self.is_high_altitude_team(home_team):
            return 1.0
        if venue_city and str(venue_city).strip().lower() in self.HIGH_ALTITUDE_CITIES:
            return 1.0
        if venue_state and str(venue_state).strip().upper() in self.HIGH_ALTITUDE_STATES and not away_team:
            return 1.0
        return 0.0

    def calculate_distance(self, team_a: str, team_b: str) -> float:
        """
        Calculate Haversine distance between two teams in miles.
        Returns 0.0 if coords missing.
        """
        coords_a = self._get_coords(team_a)
        coords_b = self._get_coords(team_b)
        
        if not coords_a or not coords_b:
            return 0.0
            
        return self._haversine(coords_a[0], coords_a[1], coords_b[0], coords_b[1])

    def _get_coords(self, team_name):
        return self.TEAM_COORDS.get(team_name)

    def _haversine(self, lat1, lon1, lat2, lon2):
        R = 3958.8  # Earth radius in miles
        
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) * math.sin(dlat / 2) +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) * math.sin(dlon / 2))
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c
