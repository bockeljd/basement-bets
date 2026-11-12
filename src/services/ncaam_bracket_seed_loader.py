from typing import Dict, List

# Manual bracket data taken from the first public reveal. Keep this localized so
# it can be swapped for an official NCAA/ESPN feed in one place when that
# becomes available. Treat as stale-prone until refreshed.
_MANUAL_2026_BRACKET = {
    "East": [
        (1, "Duke Blue Devils"), (16, "Siena Saints"),
        (8, "Ohio State Buckeyes"), (9, "TCU Horned Frogs"),
        (5, "St. John's Red Storm"), (12, "Northern Iowa Panthers"),
        (4, "Kansas Jayhawks"), (13, "Cal Baptist Lancers"),
        (6, "Louisville Cardinals"), (11, "South Florida Bulls"),
        (3, "Michigan State Spartans"), (14, "North Dakota State Bison"),
        (7, "UCLA Bruins"), (10, "UCF Knights"),
        (2, "UConn Huskies"), (15, "Furman Paladins")
    ],
    "South": [
        (1, "Florida Gators"), (16, "Lehigh / Prairie View A&M"),
        (8, "Clemson Tigers"), (9, "Iowa Hawkeyes"),
        (5, "Vanderbilt Commodores"), (12, "McNeese Cowboys"),
        (4, "Nebraska Cornhuskers"), (13, "Troy Trojans"),
        (6, "North Carolina Tar Heels"), (11, "VCU Rams"),
        (3, "Illinois Fighting Illini"), (14, "Penn Quakers"),
        (7, "Saint Mary's Gaels"), (10, "Texas A&M Aggies"),
        (2, "Houston Cougars"), (15, "Idaho Vandals")
    ],
    "West": [
        (1, "Arizona Wildcats"), (16, "Long Island Sharks"),
        (8, "Villanova Wildcats"), (9, "Utah State Aggies"),
        (5, "Wisconsin Badgers"), (12, "High Point Panthers"),
        (4, "Arkansas Razorbacks"), (13, "Hawaii Rainbow Warriors"),
        (6, "BYU Cougars"), (11, "NC State / Texas"),
        (3, "Gonzaga Bulldogs"), (14, "Kennesaw State Owls"),
        (7, "Miami (FL) Hurricanes"), (10, "Missouri Tigers"),
        (2, "Purdue Boilermakers"), (15, "Queens (N.C.) Royals")
    ],
    "Midwest": [
        (1, "Michigan Wolverines"), (16, "Howard / UMBC"),
        (8, "Georgia Bulldogs"), (9, "Saint Louis Billikens"),
        (5, "Texas Tech Red Raiders"), (12, "Akron Zips"),
        (4, "Alabama Crimson Tide"), (13, "Hofstra Pride"),
        (6, "Tennessee Volunteers"), (11, "SMU / Miami (OH)"),
        (3, "Virginia Cavaliers"), (14, "Wright State Raiders"),
        (7, "Kentucky Wildcats"), (10, "Santa Clara Broncos"),
        (2, "Iowa State Cyclones"), (15, "Tennessee State Tigers")
    ]
}

def _snake_seed_teams(team_names: List[str]) -> Dict[str, List[Dict[str, object]]]:
    """Arrange 64 ranked teams in standard NCAA 1..16 S-curve order across 4 regions."""
    regions = ["South", "East", "West", "Midwest"]
    grouped: Dict[str, List[Dict[str, object]]] = {r: [] for r in regions}
    for idx, team in enumerate(team_names[:64]):
        seed_num = (idx // 4) + 1
        pos_in_band = idx % 4
        # Snake alternate every seed line: L->R on odd seeds, R->L on even seeds
        region = regions[pos_in_band] if seed_num % 2 == 1 else regions[3 - pos_in_band]
        grouped[region].append({"seed": seed_num, "team_name": team})
    return grouped


def build_projected_bracket_seeds(limit: int = 64, season: str = None) -> Dict[str, List[Dict[str, object]]]:
    """Build a projected 64-team tournament field from live season ratings when official seeds aren't set."""
    try:
        from src.database import get_db_connection, _exec
        from src.utils.ncaam_season import (
            current_ncaam_season_short,
            ncaam_season_date_bounds,
            parse_ncaam_season_end_year,
        )

        target_season = season or current_ncaam_season_short()
        season_end_year = parse_ncaam_season_end_year(target_season)
        season_start, season_end = ncaam_season_date_bounds(season_end_year)

        with get_db_connection() as conn:
            rows = _exec(conn, """
                SELECT team_name
                FROM kenpom_team_ratings_daily
                WHERE asof_date = (
                    SELECT MAX(asof_date)
                    FROM kenpom_team_ratings_daily
                    WHERE asof_date >= %s::date AND asof_date < %s::date
                )
                ORDER BY rank ASC
                LIMIT %s
            """, (season_start, season_end, int(limit))).fetchall()
            if not rows or len(rows) < 64:
                rows = _exec(conn, """
                    SELECT team_name
                    FROM kenpom_ratings
                    WHERE updated_at >= %s::timestamp AND updated_at < %s::timestamp
                    ORDER BY rank ASC
                    LIMIT %s
                """, (season_start, season_end, int(limit))).fetchall()
            if not rows or len(rows) < 64:
                rows = _exec(conn, """
                    SELECT team_text AS team_name
                    FROM bt_team_metrics_daily
                    WHERE date = (
                        SELECT MAX(date)
                        FROM bt_team_metrics_daily
                        WHERE date >= %s AND date < %s
                    )
                    ORDER BY (adj_off - adj_def) DESC
                    LIMIT %s
                """, (season_start, season_end, int(limit))).fetchall()
        teams = [r["team_name"] for r in (rows or []) if r and r.get("team_name")]
        if len(teams) < 64:
            return {}
        return _snake_seed_teams(teams)
    except Exception:
        return {}


def load_manual_bracket_seeds(season: str = None) -> Dict[str, List[Dict[str, object]]]:
    """Return the frozen manual bracket seed list for historical seasons where defined."""
    if season is None:
        from src.utils.ncaam_season import current_ncaam_season_short
        season = current_ncaam_season_short()
    if season != "2025-26":
        return {}

    return {
        region: [
            {"seed": seed, "team_name": team}
            for seed, team in entries
        ]
        for region, entries in _MANUAL_2026_BRACKET.items()
    }


def get_seed_source_metadata(season: str = None, source: str = None) -> Dict[str, object]:
    """Metadata describing the bracket seed feed."""
    if season is None:
        from src.utils.ncaam_season import current_ncaam_season_short
        season = current_ncaam_season_short()

    if source == "projected_ratings":
        return {
            "season": season,
            "source": "projected_ratings",
            "projected": True,
            "note": f"Projected 64-team field from live {season} rankings (official NCAA bracket announced Selection Sunday).",
            "path": "src/services/ncaam_bracket_seed_loader.py",
        }
    if source == "preseason_unseeded":
        return {
            "season": season,
            "source": "preseason_unseeded",
            "projected": False,
            "note": f"Official {season} NCAA Tournament bracket is not yet announced.",
            "path": "src/services/ncaam_bracket_seed_loader.py",
        }
    return {
        "season": season,
        "source": "manual_bracket_data",
        "note": f"Manual/DB bracket seed entry for {season}.",
        "path": "src/services/ncaam_bracket_seed_loader.py",
    }
