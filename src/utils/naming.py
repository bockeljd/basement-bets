"""
Naming Standardization Utilities
Consolidated from legacy models to ensure consistent matching across services.
"""
import re

def standardize_team_name(team_name: str) -> str:
    """
    Standardize team name for consistent matching across data sources.
    Source: Legacy NCAAMModel.
    """
    if not team_name:
        return team_name
        
    normalized = team_name.strip()
    
    # Known aliases
    aliases = {
        "uconn": "Connecticut",
        "ole miss": "Mississippi",
        "lsu": "LSU",
        "ucla": "UCLA",
        "usc": "USC",
        "smu": "SMU",
        "tcu": "TCU",
        "byu": "BYU",
        "uncw": "UNC Wilmington",
        "unc": "North Carolina",
        "umass": "Massachusetts",
        "unlv": "UNLV",
        "vcu": "VCU",
        "utep": "UTEP",
    }
    
    # Clean up common suffixes/prefixes
    normalized = normalized.replace(".", "")
    
    # Tournament mascot stripping (e.g., "Duke Blue Devils" -> "Duke")
    mascots = [
        "Blue Devils", "Saints", "Buckeyes", "Horned Frogs", "Red Storm", "Panthers",
        "Jayhawks", "Lancers", "Cardinals", "Bulls", "Spartans", "Bison", "Bruins",
        "Knights", "Huskies", "Paladins", "Gators", "Hawkeyes", "Commodores", "Cowboys",
        "Cornhuskers", "Trojans", "Tar Heels", "Rams", "Fighting Illini", "Quakers",
        "Gaels", "Aggies", "Cougars", "Vandals", "Wildcats", "Sharks", "Badgers",
        "Razorbacks", "Rainbow Warriors", "Bulldogs", "Owls", "Hurricanes", "Tigers",
        "Boilermakers", "Royals", "Wolverines", "Billikens", "Red Raiders", "Zips",
        "Crimson Tide", "Pride", "Volunteers", "Cavaliers", "Raiders", "Broncos", "Cyclones"
    ]
    for mascot in mascots:
        if normalized.endswith(f" {mascot}"):
            normalized = normalized[:-(len(mascot)+1)].strip()
            break

    # Re-normalize for alias check
    normalized_lower = normalized.lower()
    for alias, full_name in aliases.items():
        if normalized_lower == alias:
            return full_name
            
    # Conditional replacements
    # Miami (FL) -> Miami FL
    if "miami" in normalized_lower and ("(fl)" in normalized_lower or "florida" in normalized_lower):
        return "Miami FL"
            
    # Fix NC State / NC St
    if normalized_lower == "nc state" or normalized_lower == "nc st":
        return "NC State"

    normalized = normalized.replace(" St", " State")
    # Avoid "Stateate"
    normalized = normalized.replace(" Stateate", " State")
    
    return normalized
