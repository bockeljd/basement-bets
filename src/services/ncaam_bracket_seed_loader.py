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

def load_manual_bracket_seeds(season: str = "2025-26") -> Dict[str, List[Dict[str, object]]]:
    """Return the frozen manual bracket seed list for a season."""
    if season != "2025-26":
        return {}

    return {
        region: [
            {"seed": seed, "team_name": team}
            for seed, team in entries
        ]
        for region, entries in _MANUAL_2026_BRACKET.items()
    }


def get_seed_source_metadata() -> Dict[str, object]:
    """Metadata describing the current manual seed feed."""
    return {
        "season": "2025-26",
        "source": "manual_bracket_data",
        "note": "Manual entry derived from the published 2026 bracket. Update when an official NCAA/ESPN feed is available.",
        "path": "src/services/ncaam_bracket_seed_loader.py"
    }
