from src.services.risk_manager import RiskManager

def test_risk_manager():
    rm = RiskManager()
    
    # 1. De-vig
    odds = [-110, -110]
    probs = rm.de_vig(odds)
    print(f"De-vig [-110, -110]: {probs} (Expected [0.5, 0.5])")
    assert abs(probs[0] - 0.5) < 0.01

    # 2. EV
    # Win prob 55% at -110 odds
    ev = rm.calculate_ev(0.55, -110)
    # Decimal odds = 1.91. Profit = 0.91.
    # EV = (0.55 * 0.91) - 0.45 = 0.5005 - 0.45 = 0.0505 = 5.05%
    print(f"EV (55% at -110): {ev:.2f}% (Expected ~5.05%)")
    assert ev > 5.0
    
    # 3. Kelly
    # Bankroll $1000, 55% win prob, -110 odds, 0.25 fraction
    sizing = rm.kelly_size(0.55, -110, 1000, fraction=0.25)
    print(f"Kelly sizing: {sizing}")
    # b = 0.91
    # Full Kelly f* = (0.55 * 0.91 - 0.45) / 0.91 = (0.5005 - 0.45) / 0.91 = 0.0505 / 0.91 = 0.0555
    # Suggested (0.25) = 0.0138 = $13.80
    assert sizing['suggested_stake'] > 13.0 and sizing['suggested_stake'] < 15.0

    print("RiskManager tests passed!")

if __name__ == "__main__":
    test_risk_manager()
