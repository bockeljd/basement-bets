
def normalize_market(market: str) -> str:
    """
    Consolidates market type naming.
    Returns: 'MONEYLINE', 'SPREAD', 'TOTAL', or original uppercase.
    """
    if not market: return "UNKNOWN"
    m = market.upper().strip()
    
    if m in ('H2H', 'MONEYLINE', 'MONEY LINE', 'ML', '1X2', 'WINNER (ML)', 'STRAIGHT'):
        return 'MONEYLINE'
        
    if m in ('SPREADS', 'SPREAD', 'POINT SPREAD', 'HANDICAP', 'ATS'):
        return 'SPREAD'
        
    if m in ('TOTALS', 'TOTAL', 'OVER/UNDER', 'OU', 'O/U'):
        return 'TOTAL'

    if m in ('NRFI', 'NO RUN FIRST INNING', 'H2H_1ST_1_INNINGS', 'FIRST_INNING'):
        return 'NRFI'

    if m in ('YRFI', 'YES RUN FIRST INNING'):
        return 'NRFI'  # Same market type, pick determines side

    return m

def normalize_provider(provider: str) -> str:
    """Normalize sportsbook/provider display names.

    Note: this is intended for *sportsbooks* (DraftKings/FanDuel/etc), not feed sources.
    """
    if not provider:
        return "Unknown"
    p = str(provider).strip()
    u = p.upper()

    if u in ('DK', 'DRAFTKINGS', 'DRAFT KINGS'):
        return 'DraftKings'

    if u in ('FD', 'FANDUEL', 'FAN DUEL'):
        return 'FanDuel'

    if u in ('MGM', 'BETMGM'):
        return 'BetMGM'

    return p


def normalize_feed_provider(provider: str) -> str:
    """Normalize odds *feed* provider keys to a canonical lowercase identifier.

    Examples:
      - "ACTION_NETWORK" / "Action Network" -> "action_network"
      - "odds_api" / "Odds API" -> "odds_api"

    This prevents branching bugs (e.g. comparing to "action_network") when callers
    pass inconsistent casing.
    """
    if not provider:
        return "odds_api"

    p = str(provider).strip().lower().replace(' ', '_').replace('-', '_')

    aliases = {
        'action': 'action_network',
        'actionnetwork': 'action_network',
        'action_network': 'action_network',
        'action-network': 'action_network',
        'oddsapi': 'odds_api',
        'odds_api': 'odds_api',
        'odds-api': 'odds_api',
        'theoddsapi': 'odds_api',
    }

    return aliases.get(p, p)

def normalize_side(side: str) -> str:
    """
    Normalizes bet side (Over/Under, Home/Away usually handled by ID, but text needs mapping).
    """
    if not side: return "UNKNOWN"
    s = str(side).upper().strip()
    
    if s in ('OVER', 'O'): return 'OVER'
    if s in ('UNDER', 'U'): return 'UNDER'
    if s in ('DRAW', 'X'): return 'DRAW'
    
    return s
