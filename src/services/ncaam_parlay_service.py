"""Reusable NCAAM parlay math, leg validation, grading, and 2-leg / 3-leg builder helpers."""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def dec_from_american(a: int) -> float:
    a = int(a)
    if abs(a) < 100:
        return 1.0
    return 1.0 + (a / 100.0) if a > 0 else 1.0 + (100.0 / abs(a))


def implied_prob_american(a: int) -> float:
    a = int(a)
    if abs(a) < 100:
        return 0.5
    return 100.0 / (a + 100.0) if a > 0 else abs(a) / (abs(a) + 100.0)


def american_from_dec(d: float) -> int:
    if d <= 1.0:
        return 0
    x = d - 1.0
    if x >= 1.0:
        return int(round(x * 100))
    return int(round(-100 / x))


def leg_has_contra_risk(raw_tags: Any) -> bool:
    if not raw_tags:
        return False
    if isinstance(raw_tags, str):
        tag_list = [t.strip().lower() for t in raw_tags.split(",") if t.strip()]
    elif isinstance(raw_tags, (list, tuple, set)):
        tag_list = [str(t or "").strip().lower() for t in raw_tags]
    else:
        return False
    return any(
        t in ("contra_sharp_money", "contra_sharp_line") or t.startswith("reverse_steam=")
        for t in tag_list
    )


def combine_leg_outcomes(outcomes: Sequence[Any]) -> str:
    norm = [str(o or "").upper() for o in outcomes]
    if not norm or any(o in ("PENDING", "") for o in norm):
        return "PENDING"
    if any(o == "LOST" for o in norm):
        return "LOST"
    if any(o == "VOID" for o in norm):
        return "VOID"
    if all(o == "WON" for o in norm):
        return "WON"
    if all(o == "PUSH" for o in norm):
        return "PUSH"
    if any(o == "WON" for o in norm) and any(o == "PUSH" for o in norm):
        return "WON (partial)"
    return "PENDING"


def grade_parlay_leg_from_scores(lg: dict, gr: dict) -> Optional[str]:
    """Grade a single parlay leg (MONEYLINE, SPREAD, SPREAD_1H, TOTAL, TOTAL_1H) against final scores."""
    hs = float(gr["home_score"])
    as_ = float(gr["away_score"])
    h_team = str(gr.get("home_team") or "").strip().lower()
    a_team = str(gr.get("away_team") or "").strip().lower()
    pick_str = str(lg.get("team_pick") or lg.get("selection") or lg.get("pick") or "").strip()
    pick_low = pick_str.lower()
    mkt = str(lg.get("market_type") or "MONEYLINE").upper()
    is_home = (
        bool(lg.get("is_home_pick"))
        or (str(lg.get("side") or "").upper() == "HOME")
        or (bool(h_team) and h_team in pick_low and (not a_team or a_team not in pick_low))
    )

    if "1H" in mkt:
        if gr.get("home_score_1h") is None or gr.get("away_score_1h") is None:
            return None
        hs = float(gr["home_score_1h"])
        as_ = float(gr["away_score_1h"])

    if "SPREAD" in mkt:
        m_ln = re.search(r"([+-]\d+(?:\.\d+)?)\s*$", pick_str)
        if m_ln:
            ln_val = float(m_ln.group(1))
        elif lg.get("market_line") is not None:
            ln_val = float(lg["market_line"])
        else:
            return None
        margin = ((hs - as_) if is_home else (as_ - hs)) + ln_val
        return "PUSH" if margin == 0 else ("WON" if margin > 0 else "LOST")

    if "TOTAL" in mkt:
        m_ln = re.search(r"(\d+(?:\.\d+)?)\s*$", pick_str)
        if not m_ln and lg.get("market_line") is not None:
            ln_val = float(lg["market_line"])
        elif m_ln:
            ln_val = float(m_ln.group(1))
        else:
            return None
        tot_pts = hs + as_
        is_over = ("OVER" in pick_str.upper()) or (str(lg.get("side") or "").upper() == "OVER")
        diff = (tot_pts - ln_val) if is_over else (ln_val - tot_pts)
        return "PUSH" if diff == 0 else ("WON" if diff > 0 else "LOST")

    diff = (hs - as_) if is_home else (as_ - hs)
    return "PUSH" if diff == 0 else ("WON" if diff > 0 else "LOST")


def evaluate_value_underdog_ml_leg(
    *,
    event_id: str,
    home_team: str,
    away_team: str,
    start_time: Any,
    side: str,
    ml_price: int,
    ml_book: str,
    fair_spread_home: float,
    sigma_spread: float,
    conviction_sources: int,
    calibrate_fn=None,
) -> Optional[dict]:
    """Return a Smart-Risk Value Underdog ML leg (+110..+220) when model & consensus back the upset."""
    try:
        pr = int(ml_price)
        if not (110 <= pr <= 220):
            return None
        if int(conviction_sources or 0) < 2:
            return None
        sig = max(8.0, float(sigma_spread or 10.8))
        p_home_raw = 0.5 * (1.0 - math.erf(float(fair_spread_home) / (sig * math.sqrt(2.0))))
        side_up = str(side or "").strip().upper()
        p_raw = p_home_raw if side_up == "HOME" else (1.0 - p_home_raw)
        wp = float(calibrate_fn(p_raw)) if callable(calibrate_fn) else float(p_raw)
        ip = implied_prob_american(pr)
        prob_edge = wp - ip
        ev_leg = wp * (dec_from_american(pr) - 1.0) - (1.0 - wp)
        if wp < 0.36 or prob_edge < 0.03 or ev_leg < 0.035:
            return None
        team_nm = home_team if side_up == "HOME" else away_team
        return {
            "event_id": event_id,
            "matchup": f"{away_team} @ {home_team}",
            "away_team": away_team,
            "home_team": home_team,
            "start_time": str(start_time or ""),
            "team_pick": f"{team_nm} ML",
            "pick": team_nm,
            "selection": f"{team_nm} ML",
            "market_type": "MONEYLINE",
            "side": side_up,
            "price": pr,
            "book": ml_book or "Consensus",
            "win_prob": round(wp, 4),
            "ev": round(ev_leg, 4),
            "ev_per_unit": round(ev_leg, 4),
            "outcome": "PENDING",
            "is_home_pick": (side_up == "HOME"),
            "is_sweet_spot_7pt": False,
            "is_value_underdog": True,
            "is_smart_risk": True,
            "risk_tier": "SMART_RISK",
            "conviction_sources": int(conviction_sources),
        }
    except Exception:
        return None


def _price_multi_leg_combo(legs: Sequence[dict]) -> Tuple[List[dict], float, Optional[str], bool]:
    """Compute decimal odds & shared DraftKings/FanDuel book pricing for 2+ legs."""
    shared_dk_fd = []
    for bk_name in ("DraftKings", "FanDuel"):
        if all(bk_name in (lg.get("_dk_fd_prices") or {}) for lg in legs):
            dec_bk = 1.0
            prices_bk = []
            for lg in legs:
                p_i = int((lg.get("_dk_fd_prices") or {})[bk_name])
                prices_bk.append(p_i)
                dec_bk *= dec_from_american(p_i)
            shared_dk_fd.append((dec_bk, bk_name, prices_bk))

    if shared_dk_fd:
        shared_dk_fd.sort(key=lambda x: x[0], reverse=True)
        dec, parlay_book, prices_bk = shared_dk_fd[0]
        clean_legs = []
        for lg, p_i in zip(legs, prices_bk):
            c_lg = {k: v for k, v in lg.items() if k != "_dk_fd_prices"}
            c_lg["price"] = p_i
            c_lg["book"] = parlay_book
            clean_legs.append(c_lg)
        return clean_legs, dec, parlay_book, True

    dec = 1.0
    books = []
    clean_legs = []
    for lg in legs:
        dec *= dec_from_american(int(lg["price"]))
        books.append(str(lg.get("book") or "").strip())
        clean_legs.append({k: v for k, v in lg.items() if k != "_dk_fd_prices"})
    unique_non_cons = {b.lower() for b in books if b and b.lower() != "consensus"}
    same_book = len(unique_non_cons) == 1 and all(b and b.lower() != "consensus" for b in books)
    parlay_book = books[0] if same_book else None
    return clean_legs, dec, parlay_book, same_book


def build_three_leg_high_payout_parlays(
    norm_legs: Sequence[dict],
    *,
    min_ev: float = 0.04,
    odds_lo: int = 300,
    odds_hi: int = 1000,
    limit: int = 3,
    max_source_legs: int = 18,
) -> List[dict]:
    """Build independent 3-leg high-payout parlays (+300 to +1000) from the strongest +EV legs."""
    if not norm_legs or len(norm_legs) < 3:
        return []

    ranked_legs = sorted(
        [
            lg for lg in norm_legs
            if lg.get("event_id")
            and float(lg.get("win_prob") or 0.0) > 0.35
            and float(lg.get("ev_per_unit") or lg.get("ev") or 0.0) >= 0.015
            and abs(int(lg.get("price") or 0)) >= 100
        ],
        key=lambda x: (float(x.get("ev_per_unit") or x.get("ev") or 0.0), float(x.get("win_prob") or 0.0)),
        reverse=True,
    )[: int(max_source_legs)]

    if len(ranked_legs) < 3:
        return []

    from src.utils.ev import compute_recommended_bet_size

    candidates: List[dict] = []
    n = len(ranked_legs)
    for i in range(n):
        for j in range(i + 1, n):
            if ranked_legs[i]["event_id"] == ranked_legs[j]["event_id"]:
                continue
            for k in range(j + 1, n):
                if ranked_legs[k]["event_id"] in (ranked_legs[i]["event_id"], ranked_legs[j]["event_id"]):
                    continue
                trio = (ranked_legs[i], ranked_legs[j], ranked_legs[k])
                p = float(trio[0]["win_prob"]) * float(trio[1]["win_prob"]) * float(trio[2]["win_prob"])
                clean_legs, dec, parlay_book, same_book = _price_multi_leg_combo(trio)
                amer = american_from_dec(dec)
                ev = p * (dec - 1.0) - (1.0 - p)
                if ev < float(min_ev) or not (int(odds_lo) <= amer <= int(odds_hi)):
                    continue
                try:
                    sizing = compute_recommended_bet_size(
                        p, amer, ev=ev, confidence_tier="LOW", min_units=0.25, max_units=0.5,
                    )
                except Exception:
                    sizing = {"units": 0.25, "bankroll_pct": 0.25, "kelly_fraction": 0.0025, "sizing_tier": "Quarter-Unit High-Payout Parlay"}
                candidates.append({
                    "legs": clean_legs,
                    "leg_count": 3,
                    "p_win": round(p, 4),
                    "decimal_odds": round(dec, 4),
                    "american_odds": amer,
                    "ev": round(ev, 4),
                    "outcome": combine_leg_outcomes([lg.get("outcome") for lg in clean_legs]),
                    "same_book": same_book,
                    "parlay_book": parlay_book,
                    "has_smart_risk_leg": any(bool(lg.get("is_smart_risk")) for lg in clean_legs),
                    "has_value_underdog": any(bool(lg.get("is_value_underdog")) for lg in clean_legs),
                    "suggested_units": min(float(sizing["units"]), 0.5),
                    "bankroll_pct": min(float(sizing["bankroll_pct"]), 0.5),
                    "sizing_tier": "Quarter-Unit High-Payout Parlay" if float(sizing["units"]) <= 0.3 else "Half-Unit High-Payout Parlay",
                    "kelly": sizing["kelly_fraction"],
                })

    candidates.sort(
        key=lambda x: (1 if x.get("same_book") else 0, x["ev"], x["p_win"]),
        reverse=True,
    )
    accepted: List[dict] = []
    used_eids: set[str] = set()
    for c in candidates:
        eids = {str(lg["event_id"]) for lg in c["legs"]}
        if eids & used_eids:
            continue
        accepted.append(c)
        used_eids.update(eids)
        if len(accepted) >= int(limit):
            break
    return accepted
