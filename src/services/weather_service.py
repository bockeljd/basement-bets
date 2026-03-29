"""
Weather Service — Open-Meteo integration for game-time weather data.

Provides temperature, wind speed/direction, and precipitation probability
for MLB game locations. Used by the MLB model to adjust run projections.

Key principle: Weather only matters for open-air stadiums.
Domed/retractable-roof stadiums get neutral weather.
"""

import requests
import json
import time
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Any

from src.services.ballpark_service import BallparkService


class WeatherService:
    """Fetch and interpret game-time weather for MLB stadiums."""

    # Open-Meteo API (free, no key required, 10k requests/day)
    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    # Cache duration (2 hours — weather doesn't change that fast)
    CACHE_DURATION = 7200

    # Wind direction thresholds for HR impact (degrees from North)
    # Outfield is roughly south for most parks. Wind blowing OUT = 160-220°
    WIND_OUT_MIN = 140
    WIND_OUT_MAX = 220

    def __init__(self):
        self.ballpark = BallparkService()
        self._cache: Dict[str, Any] = {}  # In-memory cache: "lat,lon,hour" -> data

    def get_game_weather(self, home_team: str, game_time: datetime = None) -> Optional[Dict]:
        """
        Fetch weather for the home team's stadium at game time.

        Returns:
            {
                "temperature_f": 78.0,
                "wind_speed_mph": 12.5,
                "wind_direction_deg": 180,
                "wind_blowing_out": True,
                "precipitation_prob": 15,
                "is_domed": False,
                "impact_summary": "Wind blowing out, warm — hitter-friendly"
            }
        """
        # 1. Check if stadium is domed — skip API call
        if self.ballpark.is_domed(home_team):
            return {
                "temperature_f": 72.0,  # Controlled indoor temp
                "wind_speed_mph": 0.0,
                "wind_direction_deg": 0,
                "wind_blowing_out": False,
                "precipitation_prob": 0,
                "is_domed": True,
                "impact_summary": "Indoor/retractable roof — weather neutralized",
                "run_adjustment": 0.0,
                "total_adjustment": 0.0,
            }

        # 2. Get coordinates
        coords = self.ballpark.get_coordinates(home_team)
        if not coords:
            print(f"[WEATHER] No coordinates for {home_team}")
            return None

        lat, lon = coords

        # 3. Determine target hour
        if game_time is None:
            game_time = datetime.now(timezone.utc)
        elif game_time.tzinfo is None:
            game_time = game_time.replace(tzinfo=timezone.utc)

        # 4. Check cache
        cache_key = f"{lat:.2f},{lon:.2f},{game_time.strftime('%Y%m%d%H')}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if time.time() - cached.get("_cached_at", 0) < self.CACHE_DURATION:
                return cached

        # 5. Fetch from Open-Meteo
        try:
            params = {
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m,windspeed_10m,winddirection_10m,precipitation_probability",
                "temperature_unit": "fahrenheit",
                "windspeed_unit": "mph",
                "timezone": "auto",
                "forecast_days": 3,
            }
            resp = requests.get(self.BASE_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[WEATHER] API error for {home_team}: {e}")
            return None

        # 6. Find the hourly data closest to game time
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        winds = hourly.get("windspeed_10m", [])
        wind_dirs = hourly.get("winddirection_10m", [])
        precip_probs = hourly.get("precipitation_probability", [])

        if not times:
            return None

        # Find closest hour
        target_str = game_time.strftime("%Y-%m-%dT%H:00")
        best_idx = 0
        best_diff = float("inf")
        for i, t in enumerate(times):
            try:
                dt = datetime.fromisoformat(t)
                diff = abs((game_time.replace(tzinfo=None) - dt).total_seconds())
                if diff < best_diff:
                    best_diff = diff
                    best_idx = i
            except Exception:
                continue

        temp = temps[best_idx] if best_idx < len(temps) else 72.0
        wind = winds[best_idx] if best_idx < len(winds) else 0.0
        wind_dir = wind_dirs[best_idx] if best_idx < len(wind_dirs) else 0
        precip = precip_probs[best_idx] if best_idx < len(precip_probs) else 0

        # 7. Determine if wind is blowing out (toward outfield)
        wind_out = self.WIND_OUT_MIN <= wind_dir <= self.WIND_OUT_MAX

        # 8. Calculate adjustments
        run_adj = self._calculate_run_adjustment(temp, wind, wind_out, precip)
        total_adj = run_adj  # Applied to total runs projection

        # 9. Generate summary
        summary = self._generate_summary(temp, wind, wind_out, precip)

        result = {
            "temperature_f": round(temp, 1),
            "wind_speed_mph": round(wind, 1),
            "wind_direction_deg": int(wind_dir),
            "wind_blowing_out": wind_out,
            "precipitation_prob": int(precip),
            "is_domed": False,
            "impact_summary": summary,
            "run_adjustment": round(run_adj, 2),
            "total_adjustment": round(total_adj, 2),
            "_cached_at": time.time(),
        }

        # Cache it
        self._cache[cache_key] = result
        return result

    def _calculate_run_adjustment(self, temp: float, wind: float, wind_out: bool, precip: int) -> float:
        """
        Calculate total run adjustment based on weather conditions.

        Factors:
        - Temperature: Ball carries farther in warm air
        - Wind blowing out: Fly balls become HR
        - Wind blowing in: Suppresses fly balls
        - High precip probability: Possible delays, wet ball → less carry
        """
        adj = 0.0

        # Temperature effect
        # Baseline: 72°F = neutral
        # Every 10°F above adds ~0.15 runs (ball carries farther)
        # Every 10°F below subtracts ~0.10 runs (denser air)
        temp_delta = temp - 72.0
        if temp_delta > 0:
            adj += (temp_delta / 10.0) * 0.15
        else:
            adj += (temp_delta / 10.0) * 0.10

        # Wind effect
        if wind > 5.0:  # Only significant above 5 mph
            if wind_out:
                # Wind blowing out — increases HR, run scoring
                adj += min((wind - 5.0) / 10.0 * 0.4, 0.6)
            else:
                # Check if wind is blowing IN (roughly 340-360, 0-40 degrees)
                # For simplicity, any non-out strong wind suppresses slightly
                adj -= min((wind - 5.0) / 15.0 * 0.2, 0.3)

        # Precipitation
        if precip > 50:
            adj -= 0.2  # Wet conditions → slightly fewer runs

        # Cap total weather adjustment
        return max(min(adj, 0.8), -0.5)

    def _generate_summary(self, temp: float, wind: float, wind_out: bool, precip: int) -> str:
        """Generate readable weather impact summary."""
        parts = []

        if temp > 85:
            parts.append("Hot — ball carries well")
        elif temp > 75:
            parts.append("Warm")
        elif temp < 50:
            parts.append("Cold — ball won't carry")
        elif temp < 60:
            parts.append("Cool")

        if wind > 10:
            if wind_out:
                parts.append(f"Wind blowing out {wind:.0f} mph — hitter-friendly")
            else:
                parts.append(f"Wind {wind:.0f} mph (not outfield) — slight pitcher edge")
        elif wind > 5:
            if wind_out:
                parts.append("Light wind blowing out")

        if precip > 60:
            parts.append(f"Rain likely ({precip}%)")
        elif precip > 30:
            parts.append(f"Rain possible ({precip}%)")

        if not parts:
            return "Neutral weather conditions"

        return "; ".join(parts)


if __name__ == "__main__":
    svc = WeatherService()

    print("=== Weather Service Test ===\n")

    # Test open-air stadium
    weather = svc.get_game_weather("Chicago Cubs")
    if weather:
        print(f"Wrigley Field:")
        print(f"  Temp: {weather['temperature_f']}°F")
        print(f"  Wind: {weather['wind_speed_mph']} mph @ {weather['wind_direction_deg']}°")
        print(f"  Wind Out: {weather['wind_blowing_out']}")
        print(f"  Precip: {weather['precipitation_prob']}%")
        print(f"  Run Adj: {weather['run_adjustment']:+.2f}")
        print(f"  Summary: {weather['impact_summary']}")
    else:
        print("Wrigley Field: API error or no data")

    # Test domed stadium
    print()
    weather_dome = svc.get_game_weather("Tampa Bay Rays")
    if weather_dome:
        print(f"Tropicana Field:")
        print(f"  Domed: {weather_dome['is_domed']}")
        print(f"  Run Adj: {weather_dome['run_adjustment']:+.2f}")
        print(f"  Summary: {weather_dome['impact_summary']}")
