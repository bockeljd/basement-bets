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
        "utep": "UTEP",
        "long island": "LIU",
        "liu": "LIU",
        "st johns": "St. John's",
        "kennesaw state": "Kennesaw St.",
        "saint marys": "Saint Mary's",
        "st marys": "Saint Mary's",
        "wright state": "Wright St.",
        "michigan state": "Michigan St.",
        "ohio state": "Ohio St.",
        "mississippi state": "Mississippi St.",
        "penn state": "Penn St.",
        "boise state": "Boise St.",
        "utah state": "Utah St.",
        "colorado state": "Colorado St.",
        "san diego state": "San Diego St.",
        "arizona state": "Arizona St.",
        "kansas state": "Kansas St.",
        "oklahoma state": "Oklahoma St.",
        "iowa state": "Iowa St.",
        "kansas st": "Kansas St.",
        "michigan st": "Michigan St.",
        "wright st": "Wright St.",
    }
    
    # Remove parenthesis content (e.g., "Queens (N.C.)" -> "Queens")
    normalized = re.sub(r'\s*\([^)]*\)', '', normalized).strip()
    
    # Clean up common suffixes/prefixes
    normalized = normalized.replace(".", "")
    
    # Tournament mascot stripping
    # ... (existing mascots list)
    mascots = [
        "Blue Devils", "Saints", "Buckeyes", "Horned Frogs", "Red Storm", "Panthers",
        "Jayhawks", "Lancers", "Cardinals", "Bulls", "Spartans", "Bison", "Bruins",
        "Knights", "Huskies", "Paladins", "Gators", "Hawkeyes", "Commodores", "Cowboys",
        "Cornhuskers", "Trojans", "Tar Heels", "Rams", "Fighting Illini", "Quakers",
        "Gaels", "Aggies", "Cougars", "Vandals", "Wildcats", "Sharks", "Badgers",
        "Razorbacks", "Rainbow Warriors", "Bulldogs", "Owls", "Hurricanes", "Tigers",
        "Boilermakers", "Royals", "Wolverines", "Billikens", "Red Raiders", "Zips",
        "Crimson Tide", "Pride", "Volunteers", "Cavaliers", "Raiders", "Broncos", "Cyclones",
        "Mountain Hawks", "Bravehearts"
    ]
    for mascot in mascots:
        if normalized.endswith(f" {mascot}"):
            normalized = normalized[:-(len(mascot)+1)].strip()
            break

    # Re-normalize for alias check
    normalized_lower = normalized.lower()
    
    # Handle St. vs State variants
    # If the normalized name ends with "State", we also check for "St" and vice versa
    if normalized_lower.endswith(" state"):
        st_variant = normalized[:-5].strip() + " St"
    elif normalized_lower.endswith(" st"):
        st_variant = normalized[:-2].strip() + " State"
    else:
        st_variant = normalized

    for alias, full_name in aliases.items():
        if normalized_lower == alias:
            return full_name
            
    # Conditional replacements
    if "miami" in normalized_lower and ("fl" in normalized_lower or "florida" in normalized_lower or "(fl)" in team_name.lower()):
        return "Miami FL"
            
    if normalized_lower == "nc state" or normalized_lower == "nc st":
        return "NC State"

    # Default to original normalized
    return normalized
