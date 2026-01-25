
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
        
    return m

def normalize_provider(provider: str) -> str:
    """
    Consolidates provider naming.
    Returns: 'DraftKings', 'FanDuel', 'ActionNetwork', 'OddsAPI', etc.
    """
    if not provider: return "Unknown"
    p = provider.upper().strip()
    
    if p in ('DK', 'DRAFTKINGS', 'DRAFT KINGS'):
        return 'DraftKings'
        
    if p in ('FD', 'FANDUEL', 'FAN DUEL'):
        return 'FanDuel'
        
    if p in ('MGM', 'BETMGM'):
        return 'BetMGM'
        
    if p in ('ACTION', 'ACTIONNETWORK', 'ACTION NETWORK'):
        return 'ActionNetwork'
        
    return provider # Return original if not mapped (e.g. correct case usually handled by caller if not forced)

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
