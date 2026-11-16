"""Central EV + odds conversion utilities.

Goal: one canonical implementation used everywhere (models, risk manager, UI exports).

Definitions:
- American odds: -110, +120, etc.
- Decimal odds: total return per 1 staked (includes stake), e.g. -110 -> 1.9091
- b (net payout multiplier): decimal_odds - 1
- EV per unit risked: p*b - (1-p)

Guardrails:
- Clamp win prob to [0,1]
- Sanitize impossible american odds (e.g. -9) by returning None or defaulting upstream
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


def clamp_prob(p: Any, default: float = 0.5) -> float:
    try:
        x = float(p)
    except Exception:
        return float(default)
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def sanitize_american_odds(price: Any, default: Optional[int] = -110) -> Optional[int]:
    """Return a plausible American odds int.

    If default is None, returns None when odds are invalid.
    """
    try:
        if price is None or price == '':
            return default
        p = int(price)
    except Exception:
        return default

    # Typical odds: <= -100 or >= +100.
    if -100 < p < 100:
        return default
    return p


def american_to_decimal(price: Any) -> Optional[float]:
    p = sanitize_american_odds(price, default=None)
    if p is None:
        return None
    if p > 0:
        return 1.0 + (p / 100.0)
    return 1.0 + (100.0 / abs(p))


def american_to_b(price: Any) -> Optional[float]:
    """Net payout multiplier b (profit per 1 risked if win)."""
    dec = american_to_decimal(price)
    if dec is None:
        return None
    return dec - 1.0


def implied_prob_american(price: Any) -> Optional[float]:
    p = sanitize_american_odds(price, default=None)
    if p is None:
        return None
    if p > 0:
        return 100.0 / (p + 100.0)
    return abs(p) / (abs(p) + 100.0)


def ev_per_unit(win_prob: Any, price: Any, *, clamp: bool = True) -> Optional[float]:
    p = clamp_prob(win_prob) if clamp else win_prob
    b = american_to_b(price)
    if b is None:
        return None
    return (p * b) - (1.0 - p)


def kelly_fraction(win_prob: Any, price: Any, *, kelly_mult: float = 0.25) -> Optional[float]:
    p = clamp_prob(win_prob)
    b = american_to_b(price)
    if b is None or b <= 0:
        return None
    q = 1.0 - p
    f = (b * p - q) / b
    f = max(0.0, float(f))
    return f * float(kelly_mult)


def compute_recommended_bet_size(
    win_prob: Any,
    price: Any,
    *,
    confidence_tier: Optional[str] = None,
    confidence_score: Optional[float] = None,
    ev: Optional[float] = None,
    kelly_q: Optional[float] = None,
    unit_pct: float = 1.0,
    min_units: float = 0.5,
    max_units: float = 2.0,
) -> dict:
    """
    Compute canonical risk-capped recommended bet size (in units & % of bankroll).
    Uses quarter-Kelly (0.25x) bounded by confidence tier and max bankroll risk limits.
    """
    tier = (confidence_tier or "").strip().upper()
    if not tier and confidence_score is not None:
        try:
            cs = float(confidence_score)
            tier = "HIGH" if cs >= 80 else ("MEDIUM" if cs >= 50 else "LOW")
        except Exception:
            tier = ""

    kf: Optional[float] = None
    if kelly_q is not None:
        try:
            kq_f = float(kelly_q)
            if 0.0 <= kq_f <= 1.0:
                kf = kq_f
        except Exception:
            kf = None
    if kf is None and win_prob is not None and price is not None:
        kf = kelly_fraction(win_prob, price, kelly_mult=0.25)

    ev_val: Optional[float] = None
    if ev is not None:
        try:
            ev_val = float(ev)
        except Exception:
            ev_val = None
    elif win_prob is not None and price is not None:
        ev_val = ev_per_unit(win_prob, price)

    safe_unit_pct = max(0.25, float(unit_pct or 1.0))

    if kf is not None:
        kf = min(0.05, max(0.0, float(kf)))
        if kf <= 0.0 and (ev_val is None or ev_val <= 0.0):
            return {
                "units": 0.0,
                "bankroll_pct": 0.0,
                "kelly_fraction": 0.0,
                "sizing_tier": "Pass",
            }
        raw_units = ((kf * 100.0) / safe_unit_pct) if kf > 0.0 else min_units
        quantized = round(min(max_units, max(min_units, raw_units)) * 4.0) / 4.0
        if tier == "HIGH":
            units = min(max_units, max(1.25 if quantized >= 1.0 else 1.0, quantized))
        elif tier == "LOW":
            units = min(0.75, max(min_units, quantized))
        elif tier == "MEDIUM":
            units = min(1.5, max(min_units, quantized))
        else:
            units = quantized
    else:
        if ev_val is not None and ev_val <= 0.0:
            return {
                "units": 0.0,
                "bankroll_pct": 0.0,
                "kelly_fraction": 0.0,
                "sizing_tier": "Pass",
            }
        if tier == "HIGH":
            units = min(max_units, 1.5)
        elif tier == "LOW":
            units = min_units
        else:
            units = 1.0
        kf = round((units * safe_unit_pct) / 100.0, 4)

    units = round(float(units), 2)
    bankroll_pct = round(min(5.0, units * safe_unit_pct), 2)
    if units >= 1.5:
        sizing_tier = "Strong Play"
    elif units >= 1.0:
        sizing_tier = "Standard Play"
    elif units >= 0.4:
        sizing_tier = "Half-Unit Play"
    elif units > 0.0:
        sizing_tier = "Quarter-Unit Play"
    else:
        sizing_tier = "Pass"

    return {
        "units": units,
        "bankroll_pct": bankroll_pct,
        "kelly_fraction": round(float(kf), 4),
        "sizing_tier": sizing_tier,
    }


@dataclass
class EvBreakdown:
    win_prob: float
    american_odds: int
    decimal_odds: float
    b: float
    implied_prob: float
    ev: float
    kelly_q: float


def ev_breakdown(win_prob: Any, price: Any, *, kelly_mult: float = 0.25) -> Optional[EvBreakdown]:
    p = clamp_prob(win_prob)
    a = sanitize_american_odds(price, default=None)
    if a is None:
        return None
    dec = american_to_decimal(a)
    b = american_to_b(a)
    ip = implied_prob_american(a)
    ev = ev_per_unit(p, a)
    k = kelly_fraction(p, a, kelly_mult=kelly_mult)
    if dec is None or b is None or ip is None or ev is None or k is None:
        return None
    return EvBreakdown(
        win_prob=p,
        american_odds=a,
        decimal_odds=dec,
        b=b,
        implied_prob=ip,
        ev=ev,
        kelly_q=k,
    )
