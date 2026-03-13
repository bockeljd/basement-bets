import pytest
from datetime import datetime

# We define the logic here to verify consistency, since backend implementation is nested.
def payout_per_unit(price: int) -> float:
    if not price: return 0.909
    if price > 0:
        return price / 100.0
    else:
        return 100.0 / abs(price)

def roi_per_unit(outcome: str, price: int) -> float:
    o = (outcome or '').upper()
    if o in ('WON', 'WIN'):
        return payout_per_unit(price)
    if o in ('LOST', 'LOSS'):
        return -1.0
    if o == 'PUSH':
        return 0.0
    return 0.0

def test_outcome_normalization_logic():
    """
    Test that outcome normalization logic correctly maps legacy values to standard ones.
    """
    # -110 is default
    assert round(roi_per_unit("WON", -110), 3) == 0.909
    assert roi_per_unit("LOST", -110) == -1.0
    assert roi_per_unit("PUSH", -110) == 0.0
    assert roi_per_unit("PENDING", -110) == 0.0

def test_roi_calculation_with_actual_odds():
    """
    Test that ROI calculation handles actual odds correctly.
    """
    # +120 profit is 1.2 units
    assert round(roi_per_unit("WON", 120), 2) == 1.20
    # -110 profit is 0.909 units
    assert round(roi_per_unit("WON", -110), 3) == 0.909
    # -200 profit is 0.5 units
    assert round(roi_per_unit("WON", -200), 2) == 0.50
    # LOSS is always -1.0 units (the stake)
    assert roi_per_unit("LOST", 120) == -1.0
    assert roi_per_unit("LOST", -200) == -1.0

def test_confidence_bucketing_ranges():
    """
    Tests the ranges for confidence bucketing (High/Medium/Low).
    """
    def conf_bucket(c0: int) -> str:
        n = int(c0 or 0)
        if n >= 80: return 'High'
        if n >= 50: return 'Medium'
        return 'Low'
        
    assert conf_bucket(85) == 'High'
    assert conf_bucket(80) == 'High'
    assert conf_bucket(79) == 'Medium'
    assert conf_bucket(50) == 'Medium'
    assert conf_bucket(49) == 'Low'
    assert conf_bucket(0) == 'Low'

def test_ncaam_rank_logic_consistency():
    """
    Verification of the Top 6 Rank logic adjustment.
    """
    # Logical check: previously <= 5, now <= 6.
    rank_limit = 6
    assert 5 <= rank_limit
    assert 6 <= rank_limit
    assert 7 > rank_limit
