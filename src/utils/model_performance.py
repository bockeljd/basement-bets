
def payout_per_unit(price) -> float:
    """
    Calculates payout when risking 1 unit based on American odds.
    Fallbacks to -110 if price is None, 0, or non-numeric.
    """
    try:
        p = int(price)
    except (TypeError, ValueError):
        p = -110
    
    if p == 0:
        p = -110
        
    if p > 0:
        return p / 100.0
    else:
        return 100.0 / abs(p)

def norm_outcome(o: str) -> str:
    """
    Standardizes outcome strings strictly to WON, LOST, PUSH or PENDING.
    WIN/WON -> WON
    LOSS/LOST -> LOST
    PUSH -> PUSH
    Anything else -> PENDING
    """
    s = str(o or '').upper().strip()
    if s in ('WIN', 'WON'): return 'WON'
    if s in ('LOSS', 'LOST'): return 'LOST'
    if s == 'PUSH': return 'PUSH'
    return 'PENDING'

def is_decided(o: str) -> bool:
    """Returns True only for WON, LOST, or PUSH."""
    return norm_outcome(o) in ('WON', 'LOST', 'PUSH')

def roi_per_unit(outcome: str, price) -> float:
    """
    Calculates ROI per unit wagered.
    WON -> payout_per_unit(price)
    LOST -> -1.0
    Else -> 0.0
    """
    o = norm_outcome(outcome)
    if o == 'WON':
        return payout_per_unit(price)
    if o == 'LOST':
        return -1.0
    return 0.0

def conf_bucket(c0) -> str:
    """
    Buckets confidence into High, Medium, or Low.
    Supports both 0-100 and 0-1 scales.
    0.85 -> High, 0.65 -> Medium, 40 -> Low.
    """
    try:
        n = float(c0)
    except (TypeError, ValueError):
        return 'Low'
    
    # Normalize 0.0-1.0 scale to 0-100
    if 0.0 < n <= 1.0:
        n *= 100
    
    if n >= 80: return 'High'
    if n >= 50: return 'Medium'
    return 'Low'
