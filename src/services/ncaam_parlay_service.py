"""Reusable NCAAM parlay math, leg validation, grading, and 2-leg / 3-leg builder helpers."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
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


def compute_ncaam_parlays_today(
    min_ev_per_unit: float = 0.02,
    parlay_odds_lo: int = -120,
    parlay_odds_hi: int = 800,
    max_legs: int = 2,
    limit_legs: int = 80,
    strategy: str = "all",  # 'all' | 'home_fav'
    days_ago: int = 0,
    date: Optional[str] = None,
    persist: bool = False,
) -> Dict[str, Any]:
    """Compute (and optionally lock/persist) 2-leg and 3-leg NCAAM parlays without FastAPI."""
    if int(max_legs) not in (2, 3):
        raise ValueError("Only 2-leg and 3-leg parlays are supported")

    target_date = None
    if date is not None and str(date).strip():
        target_date = str(date).strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", target_date):
            raise ValueError("date must be YYYY-MM-DD")

    _strategy = str(strategy or "all").lower().strip()
    if _strategy == "home_fav":
        if parlay_odds_lo in (-120, -200):
            parlay_odds_lo = -165
        if parlay_odds_hi in (800, 120):
            parlay_odds_hi = 140

    from src.database import _exec, get_admin_db_connection, get_db_connection

    date_predicate = (
        "(e.start_time AT TIME ZONE 'America/New_York')::date = %(target_date)s::date"
        if target_date
        else "(e.start_time AT TIME ZONE 'America/New_York')::date = (NOW() AT TIME ZONE 'America/New_York' - (%(days)s || ' days')::interval)::date"
    )
    q = f"""
      WITH latest_preds AS (
        SELECT DISTINCT ON (m.event_id)
          m.event_id,
          m.model_version,
          m.market_type,
          m.pick,
          m.outcome,
          m.bet_line,
          COALESCE(m.bet_price, m.price) AS price,
          m.win_prob,
          m.ev_per_unit,
          m.selection,
          e.away_team,
          e.home_team,
          e.start_time,
          (e.start_time AT TIME ZONE 'America/New_York')::date::text AS day_et
        FROM model_predictions m
        JOIN events e ON m.event_id = e.id
        WHERE e.league = 'NCAAM'
          AND UPPER(COALESCE(m.market_type,'')) IN ('MONEYLINE','ML')
          AND {date_predicate}
          AND COALESCE(m.ev_per_unit, 0) >= %(min_ev)s
          AND COALESCE(m.bet_price, m.price) IS NOT NULL
        ORDER BY m.event_id, m.analyzed_at DESC
      )
      SELECT * FROM latest_preds
      ORDER BY win_prob DESC
      LIMIT %(lim)s
    """

    query_params: Dict[str, Any] = {
        "min_ev": float(min_ev_per_unit),
        "lim": int(limit_legs),
        "days": int(days_ago),
    }
    if target_date:
        query_params["target_date"] = target_date

    with get_db_connection() as conn:
        legs = [dict(r) for r in _exec(conn, q, query_params).fetchall()]
        resolved_date_et = target_date or _exec(
            conn,
            "SELECT (NOW() AT TIME ZONE 'America/New_York' - (%s || ' days')::interval)::date::text",
            (int(days_ago),),
        ).fetchone()[0]

    norm_legs: List[dict] = []
    for r in legs:
        try:
            price = int(r.get("price"))
        except Exception:
            continue
        if abs(price) < 100:
            continue
        wp = r.get("win_prob")
        try:
            wp = float(wp) if wp is not None else None
        except Exception:
            wp = None
        if wp is None or not (0 < wp < 1.0):
            continue

        home_team = r.get("home_team") or ""
        pick = r.get("pick") or r.get("selection") or ""
        is_home_pick = pick.strip().lower() == home_team.strip().lower()

        norm_legs.append({
            "event_id": r.get("event_id"),
            "matchup": f"{r.get('away_team')} @ {r.get('home_team')}",
            "team_pick": r.get("selection") or r.get("pick"),
            "market_type": "MONEYLINE",
            "side": "HOME" if is_home_pick else "AWAY",
            "price": price,
            "win_prob": wp,
            "ev_per_unit": float(r.get("ev_per_unit") or 0),
            "outcome": r.get("outcome"),
            "model_version": r.get("model_version"),
            "start_time": str(r.get("start_time") or ""),
            "is_home_pick": is_home_pick,
            "is_smart_risk": False,
            "risk_tier": "CORE",
        })

    # Enrich legs with board spread context and qualifying -4.5 to -9.5 Home Favorites
    try:
        from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2

        hf_query = f"""
          SELECT
            e.id AS event_id,
            e.away_team,
            e.home_team,
            e.start_time,
            s_home.line_value AS home_spread,
            ml_home.price AS ml_home_price,
            ml_home.book AS ml_home_book,
            p_latest.mu_final,
            p_latest.sigma,
            p_latest.pick AS pred_pick,
            p_latest.model_version,
            dtp_latest.context_json AS dtp_context_json,
            dtp_latest.rec_json AS dtp_rec_json
          FROM events e
          JOIN LATERAL (
            SELECT line_value
            FROM odds_snapshots
            WHERE event_id = e.id AND market_type = 'SPREAD' AND side = 'HOME'
              AND COALESCE(book, '') NOT IN ('action_open', 'open')
            ORDER BY (CASE WHEN book = 'consensus' THEN 0 ELSE 1 END), captured_at DESC
            LIMIT 1
          ) s_home ON TRUE
          JOIN LATERAL (
            SELECT price, book
            FROM odds_snapshots
            WHERE event_id = e.id AND market_type = 'MONEYLINE' AND side = 'HOME'
              AND COALESCE(book, '') NOT IN ('action_open', 'open')
              AND price IS NOT NULL
            ORDER BY (CASE WHEN LOWER(COALESCE(book,'')) LIKE '%%draftkings%%' OR LOWER(COALESCE(book,'')) LIKE '%%fanduel%%' THEN 0 ELSE 1 END), price DESC, captured_at DESC
            LIMIT 1
          ) ml_home ON TRUE
          LEFT JOIN LATERAL (
            SELECT mu_final, sigma, pick, model_version
            FROM model_predictions
            WHERE event_id = e.id AND market_type = 'SPREAD'
            ORDER BY analyzed_at DESC
            LIMIT 1
          ) p_latest ON TRUE
          LEFT JOIN LATERAL (
            SELECT context_json, rec_json
            FROM daily_top_picks
            WHERE event_id = e.id AND league = 'NCAAM'
            ORDER BY date_et DESC
            LIMIT 1
          ) dtp_latest ON TRUE
          WHERE e.league = 'NCAAM'
            AND COALESCE(e.neutral_site, FALSE) = FALSE
            AND {date_predicate}
            AND s_home.line_value BETWEEN -9.5 AND -4.5
            AND ml_home.price BETWEEN -380 AND -155
          ORDER BY e.start_time ASC
          LIMIT 40
        """
        hf_params: Dict[str, Any] = {"days": int(days_ago)}
        if target_date:
            hf_params["target_date"] = target_date
        with get_db_connection() as conn:
            hf_rows = [dict(r) for r in _exec(conn, hf_query, hf_params).fetchall()]

        if hf_rows:
            cal_model = NCAAMMarketFirstModelV2()
            existing_by_eid = {leg.get("event_id"): leg for leg in norm_legs if leg.get("event_id")}
            for hr in hf_rows:
                try:
                    eid = hr.get("event_id")
                    home_team = hr.get("home_team") or ""
                    away_team = hr.get("away_team") or ""
                    home_sp = float(hr.get("home_spread"))
                    ml_price = int(hr.get("ml_home_price"))
                    if abs(ml_price) < 100:
                        continue
                except Exception:
                    continue
                mu_raw = hr.get("mu_final")
                sigma_raw = hr.get("sigma")
                pred_pick = str(hr.get("pred_pick") or "").strip().lower()
                if mu_raw is not None:
                    mu_f = float(mu_raw)
                    fair_sp_home = (
                        mu_f
                        if (not pred_pick or pred_pick == home_team.strip().lower() or pred_pick.startswith(home_team.strip().lower()))
                        else -mu_f
                    )
                else:
                    ctx_raw = hr.get("dtp_context_json")
                    if isinstance(ctx_raw, str):
                        try:
                            ctx_raw = json.loads(ctx_raw)
                        except Exception:
                            ctx_raw = None
                    ctx_dict = ctx_raw if isinstance(ctx_raw, dict) else {}
                    dtp_fair = (
                        ctx_dict.get("fair_spread_home")
                        if ctx_dict.get("fair_spread_home") is not None
                        else ctx_dict.get("mu_spread_power")
                    )
                    if dtp_fair is not None:
                        fair_sp_home = float(dtp_fair)
                        if sigma_raw is None and ctx_dict.get("sigma_spread") is not None:
                            sigma_raw = ctx_dict.get("sigma_spread")
                    else:
                        fair_sp_home = home_sp
                sigma_val = max(8.0, float(sigma_raw or 10.8))
                p_raw = 0.5 * (1.0 - math.erf(float(fair_sp_home) / (sigma_val * math.sqrt(2.0))))
                wp_cal = float(cal_model._calibrate_win_prob(p_raw))
                ev_leg = wp_cal * (dec_from_american(ml_price) - 1.0) - (1.0 - wp_cal)
                is_sweet = (
                    (-9.5 <= home_sp <= -4.5)
                    and (fair_sp_home <= home_sp - 0.5)
                    and (wp_cal >= 0.68)
                    and (ev_leg >= 0.005)
                )

                if eid in existing_by_eid and existing_by_eid[eid].get("is_home_pick"):
                    existing_by_eid[eid]["home_spread"] = round(home_sp, 1)
                    existing_by_eid[eid]["fair_spread_home"] = round(fair_sp_home, 1)
                    existing_by_eid[eid]["is_sweet_spot_7pt"] = bool(is_sweet)
                    continue

                if not is_sweet or eid in existing_by_eid:
                    continue
                if _strategy == "home_fav" and ev_leg < 0.005:
                    continue
                if _strategy != "home_fav" and ev_leg < float(min_ev_per_unit):
                    continue

                norm_legs.append({
                    "event_id": eid,
                    "matchup": f"{away_team} @ {home_team}",
                    "team_pick": home_team,
                    "market_type": "MONEYLINE",
                    "side": "HOME",
                    "price": ml_price,
                    "book": hr.get("ml_home_book") or "Consensus",
                    "win_prob": round(wp_cal, 4),
                    "ev_per_unit": round(ev_leg, 4),
                    "outcome": "PENDING",
                    "model_version": hr.get("model_version") or "board_hf_7pt_v1",
                    "start_time": str(hr.get("start_time") or ""),
                    "is_home_pick": True,
                    "home_spread": round(home_sp, 1),
                    "fair_spread_home": round(fair_sp_home, 1),
                    "is_sweet_spot_7pt": True,
                })
    except Exception:
        pass

    if _strategy == "home_fav":
        norm_legs = [
            leg for leg in norm_legs
            if leg.get("is_home_pick") and -380 <= int(leg.get("price") or 0) <= -150
        ]

    combos: List[dict] = []
    if _strategy != "home_fav":
        try:
            sp_date = resolved_date_et or target_date
            if not sp_date:
                with get_db_connection() as conn:
                    sp_date = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]
            with get_db_connection() as conn:
                sp_rows = _exec(
                    conn,
                    """
                    SELECT d.event_id, d.is_actionable, d.rec_json, d.context_json,
                           e.away_team, e.home_team, e.start_time
                    FROM daily_top_picks d
                    JOIN events e ON e.id = d.event_id
                    WHERE d.league = 'NCAAM'
                      AND d.date_et = %s
                    """,
                    (sp_date,),
                ).fetchall()
            seen_sp_eids = {leg.get("event_id") for leg in norm_legs if leg.get("event_id")}
            for sr in (sp_rows or []):
                try:
                    srd = dict(sr)
                    eid = srd.get("event_id")
                    if not eid or eid in seen_sp_eids:
                        continue

                    is_act = bool(srd.get("is_actionable"))
                    rj = srd.get("rec_json")
                    if isinstance(rj, str):
                        try:
                            rj = json.loads(rj)
                        except Exception:
                            rj = None
                    cj = srd.get("context_json")
                    if isinstance(cj, str):
                        try:
                            cj = json.loads(cj)
                        except Exception:
                            cj = None

                    cand_obj = None
                    leg_smart_risk = False
                    if is_act and isinstance(rj, dict):
                        bt = str(rj.get("bet_type") or "").upper()
                        if bt in ("SPREAD", "SPREAD_1H", "TOTAL", "TOTAL_1H"):
                            ev_val = float(rj.get("ev") or 0.0)
                            wp_val = float(rj.get("win_prob") or 0.0)
                            if ev_val >= 0.02 and wp_val >= 0.525 and not leg_has_contra_risk(rj.get("movement_tags")):
                                cand_obj = rj
                                leg_smart_risk = bool(rj.get("is_smart_risk", False))
                    elif (not is_act) and isinstance(cj, dict):
                        lean = cj.get("closest_lean")
                        if isinstance(lean, dict):
                            bt = str(lean.get("bet_type") or "").upper()
                            if bt in ("SPREAD", "TOTAL"):
                                ev_val = float(lean.get("ev") or 0.0)
                                wp_val = float(lean.get("win_prob") or 0.0)
                                if ev_val >= 0.025 and wp_val >= 0.53 and not leg_has_contra_risk(lean.get("movement_tags")):
                                    cand_obj = lean
                                    leg_smart_risk = True

                    if not cand_obj:
                        continue

                    bt = str(cand_obj.get("bet_type") or "").upper()
                    ev_sp = float(cand_obj.get("ev") or 0.0)
                    wp_sp = float(cand_obj.get("win_prob") or 0.0)
                    pr_sp = int(cand_obj.get("price") or -110)
                    if abs(pr_sp) < 100 or not (0.0 < wp_sp < 1.0):
                        continue
                    sel_str = str(cand_obj.get("selection") or cand_obj.get("pick") or "").strip()
                    if not sel_str:
                        continue
                    home_nm = str(srd.get("home_team") or "").strip()
                    if bt in ("TOTAL", "TOTAL_1H"):
                        side_hint = str(cand_obj.get("side") or sel_str).upper()
                        sp_side = "OVER" if "OVER" in side_hint else "UNDER"
                    else:
                        side_hint = str(cand_obj.get("side") or "").strip().upper()
                        if side_hint in ("HOME", "AWAY"):
                            sp_side = side_hint
                        else:
                            sp_side = "HOME" if (home_nm and home_nm.lower() in sel_str.lower()) else "AWAY"

                    mkt_line_val = cand_obj.get("market_line")
                    if mkt_line_val is None:
                        m_ln_match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*$", sel_str)
                        if m_ln_match:
                            try:
                                mkt_line_val = float(m_ln_match.group(1))
                            except Exception:
                                mkt_line_val = None
                    else:
                        try:
                            mkt_line_val = float(mkt_line_val)
                        except Exception:
                            mkt_line_val = None

                    risk_tier_val = str(
                        cand_obj.get("risk_tier") or ("SMART_RISK" if leg_smart_risk else "CORE")
                    )
                    norm_legs.append({
                        "event_id": eid,
                        "matchup": f"{srd.get('away_team')} @ {srd.get('home_team')}",
                        "away_team": srd.get("away_team"),
                        "home_team": srd.get("home_team"),
                        "start_time": str(srd.get("start_time") or ""),
                        "team_pick": sel_str,
                        "pick": sel_str,
                        "selection": sel_str,
                        "market_type": bt,
                        "side": sp_side,
                        "market_line": mkt_line_val,
                        "price": pr_sp,
                        "book": cand_obj.get("book") or "Consensus",
                        "win_prob": wp_sp,
                        "ev": ev_sp,
                        "ev_per_unit": ev_sp,
                        "outcome": "PENDING",
                        "is_home_pick": (sp_side == "HOME"),
                        "is_sweet_spot_7pt": False,
                        "is_smart_risk": leg_smart_risk,
                        "risk_tier": risk_tier_val,
                    })
                    seen_sp_eids.add(eid)
                except Exception:
                    continue
        except Exception as sp_e:
            print(f"[parlays] spread/total leg enrichment skipped: {sp_e}")

        # Value Underdog Moneyline legs (+110..+220 with >=2 model consensus & >=+3.5% EV)
        try:
            from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2

            ud_query = f"""
              SELECT
                e.id AS event_id,
                e.away_team,
                e.home_team,
                e.start_time,
                ml_dog.side AS dog_side,
                ml_dog.price AS dog_price,
                ml_dog.book AS dog_book,
                dtp.context_json AS dtp_context_json
              FROM events e
              JOIN daily_top_picks dtp
                ON dtp.event_id = e.id AND dtp.league = 'NCAAM' AND dtp.date_et = %(sp_date)s
              JOIN LATERAL (
                SELECT side, price, book
                FROM odds_snapshots
                WHERE event_id = e.id AND market_type = 'MONEYLINE'
                  AND COALESCE(book, '') NOT IN ('action_open', 'open')
                  AND price BETWEEN 110 AND 220
                ORDER BY (CASE WHEN LOWER(COALESCE(book,'')) LIKE '%%draftkings%%' OR LOWER(COALESCE(book,'')) LIKE '%%fanduel%%' THEN 0 ELSE 1 END), price DESC, captured_at DESC
                LIMIT 1
              ) ml_dog ON TRUE
              WHERE e.league = 'NCAAM'
                AND {date_predicate}
              LIMIT 40
            """
            ud_params: Dict[str, Any] = {"days": int(days_ago), "sp_date": resolved_date_et or target_date}
            if target_date:
                ud_params["target_date"] = target_date
            with get_db_connection() as conn:
                ud_rows = [dict(r) for r in _exec(conn, ud_query, ud_params).fetchall()]
            if ud_rows:
                cal_model_ud = NCAAMMarketFirstModelV2()
                seen_ud_eids = {leg.get("event_id") for leg in norm_legs if leg.get("event_id")}
                for ur in ud_rows:
                    try:
                        eid = ur.get("event_id")
                        if not eid or eid in seen_ud_eids:
                            continue
                        cj_u = ur.get("dtp_context_json")
                        if isinstance(cj_u, str):
                            cj_u = json.loads(cj_u)
                        if not isinstance(cj_u, dict):
                            continue
                        fair_sp = cj_u.get("fair_spread_home") if cj_u.get("fair_spread_home") is not None else cj_u.get("mu_spread_power")
                        if fair_sp is None:
                            continue
                        dog_leg = evaluate_value_underdog_ml_leg(
                            event_id=eid,
                            home_team=str(ur.get("home_team") or ""),
                            away_team=str(ur.get("away_team") or ""),
                            start_time=ur.get("start_time"),
                            side=str(ur.get("dog_side") or ""),
                            ml_price=int(ur.get("dog_price")),
                            ml_book=str(ur.get("dog_book") or "Consensus"),
                            fair_spread_home=float(fair_sp),
                            sigma_spread=float(cj_u.get("sigma_spread") or 10.8),
                            conviction_sources=int(cj_u.get("conviction_sources") or 0),
                            calibrate_fn=cal_model_ud._calibrate_win_prob,
                        )
                        if dog_leg:
                            norm_legs.append(dog_leg)
                            seen_ud_eids.add(eid)
                    except Exception:
                        continue
        except Exception as ud_e:
            print(f"[parlays] value underdog enrichment skipped: {ud_e}")

    # Attach latest DraftKings & FanDuel prices
    try:
        leg_eids = list({str(leg.get("event_id")) for leg in norm_legs if leg.get("event_id")})
        if leg_eids:
            with get_db_connection() as conn:
                dk_fd_rows = _exec(
                    conn,
                    """
                    SELECT DISTINCT ON (event_id, market_type, side,
                      CASE WHEN LOWER(book) LIKE '%%draftkings%%' THEN 'DraftKings' ELSE 'FanDuel' END)
                      event_id,
                      market_type,
                      side,
                      CASE WHEN LOWER(book) LIKE '%%draftkings%%' THEN 'DraftKings' ELSE 'FanDuel' END AS canon_book,
                      line_value,
                      price
                    FROM odds_snapshots
                    WHERE event_id = ANY(%s)
                      AND price IS NOT NULL
                      AND (LOWER(COALESCE(book, '')) LIKE '%%draftkings%%' OR LOWER(COALESCE(book, '')) LIKE '%%fanduel%%')
                    ORDER BY event_id, market_type, side,
                      CASE WHEN LOWER(book) LIKE '%%draftkings%%' THEN 'DraftKings' ELSE 'FanDuel' END,
                      captured_at DESC
                    """,
                    (leg_eids,),
                ).fetchall()
            dk_fd_map: Dict[Tuple[str, str, str], Dict[str, Dict[str, Any]]] = {}
            for r in (dk_fd_rows or []):
                rd = dict(r)
                k = (str(rd["event_id"]), str(rd["market_type"]).upper(), str(rd["side"]).upper())
                dk_fd_map.setdefault(k, {})[rd["canon_book"]] = {
                    "price": int(rd["price"]),
                    "line_value": (float(rd["line_value"]) if rd.get("line_value") is not None else None),
                }
            for leg in norm_legs:
                mkt_k = str(leg.get("market_type") or "MONEYLINE").upper()
                if mkt_k == "ML":
                    mkt_k = "MONEYLINE"
                side_k = str(leg.get("side") or ("HOME" if leg.get("is_home_pick") else "AWAY")).upper()
                raw_bk_map = dk_fd_map.get((str(leg.get("event_id")), mkt_k, side_k), {})
                leg_line = leg.get("market_line")
                prices_by_book: Dict[str, int] = {}
                for bk_name, bk_info in raw_bk_map.items():
                    if not isinstance(bk_info, dict):
                        continue
                    bk_lv = bk_info.get("line_value")
                    if (
                        mkt_k in ("MONEYLINE", "ML")
                        or leg_line is None
                        or bk_lv is None
                        or abs(float(bk_lv) - float(leg_line)) < 0.01
                    ):
                        prices_by_book[bk_name] = int(bk_info["price"])
                leg["_dk_fd_prices"] = prices_by_book
                if prices_by_book:
                    best_bk, best_pr = max(prices_by_book.items(), key=lambda kv: dec_from_american(kv[1]))
                    if abs(int(best_pr)) >= 100:
                        leg["price"] = int(best_pr)
                        leg["book"] = best_bk
                        leg["ev_per_unit"] = round(
                            float(leg["win_prob"]) * (dec_from_american(best_pr) - 1.0) - (1.0 - float(leg["win_prob"])),
                            4,
                        )
            min_leg_ev_post = 0.005 if _strategy == "home_fav" else 0.0
            norm_legs = [
                lg for lg in norm_legs
                if float(lg.get("ev_per_unit") if lg.get("ev_per_unit") is not None else 0.0) >= min_leg_ev_post
            ]
    except Exception as dkfd_e:
        print(f"[parlays] DK/FD price enrichment skipped: {dkfd_e}")

    def _combine_two_leg_outcome(oa_raw: Any, ob_raw: Any) -> str:
        return combine_leg_outcomes((oa_raw, ob_raw))

    def _grade_parlay_legs_from_results(target_legs: list) -> None:
        if not target_legs:
            return
        pending_eids = list({
            str(lg.get("event_id"))
            for lg in target_legs
            if lg.get("event_id") and str(lg.get("outcome") or "PENDING").upper() in ("PENDING", "")
        })
        if not pending_eids:
            return
        try:
            with get_db_connection() as conn:
                gr_rows = _exec(
                    conn,
                    """
                    SELECT e.id AS event_id, e.home_team, e.away_team,
                           g.home_score, g.away_score, g.home_score_1h, g.away_score_1h, g.final
                    FROM events e
                    JOIN game_results g ON g.event_id = e.id
                    WHERE e.id = ANY(%s)
                      AND COALESCE(g.final, FALSE) = TRUE
                      AND g.home_score IS NOT NULL
                      AND g.away_score IS NOT NULL
                    """,
                    (pending_eids,),
                ).fetchall()
            gr_map = {str(r["event_id"]): dict(r) for r in (gr_rows or [])}
            for lg in target_legs:
                if str(lg.get("outcome") or "PENDING").upper() not in ("PENDING", ""):
                    continue
                gr = gr_map.get(str(lg.get("event_id")))
                if not gr:
                    continue
                graded = grade_parlay_leg_from_scores(lg, gr)
                if graded:
                    lg["outcome"] = graded
        except Exception as gr_e:
            print(f"[parlays] leg grading from game_results skipped: {gr_e}")

    _grade_parlay_legs_from_results(norm_legs)

    for i in range(len(norm_legs)):
        for j in range(i + 1, len(norm_legs)):
            a = norm_legs[i]
            b = norm_legs[j]
            if not a.get("event_id") or a.get("event_id") == b.get("event_id"):
                continue

            parlay_outcome = _combine_two_leg_outcome(a.get("outcome"), b.get("outcome"))
            p = float(a["win_prob"]) * float(b["win_prob"])

            a_books = a.get("_dk_fd_prices") or {}
            b_books = b.get("_dk_fd_prices") or {}
            shared_dk_fd = []
            for bk_name in ("DraftKings", "FanDuel"):
                if bk_name in a_books and bk_name in b_books:
                    p1 = int(a_books[bk_name])
                    p2 = int(b_books[bk_name])
                    d_bk = dec_from_american(p1) * dec_from_american(p2)
                    shared_dk_fd.append((d_bk, bk_name, p1, p2))

            if shared_dk_fd:
                shared_dk_fd.sort(key=lambda x: x[0], reverse=True)
                dec, parlay_book, price_a, price_b = shared_dk_fd[0]
                same_book = True
                leg_a = {k: v for k, v in a.items() if k != "_dk_fd_prices"}
                leg_b = {k: v for k, v in b.items() if k != "_dk_fd_prices"}
                leg_a["price"] = price_a
                leg_a["book"] = parlay_book
                leg_b["price"] = price_b
                leg_b["book"] = parlay_book
            else:
                dec = dec_from_american(a["price"]) * dec_from_american(b["price"])
                b1 = str(a.get("book") or "").strip()
                b2 = str(b.get("book") or "").strip()
                same_book = bool(b1 and b2 and b1.lower() == b2.lower() and b1.lower() != "consensus")
                parlay_book = b1 if same_book else None
                leg_a = {k: v for k, v in a.items() if k != "_dk_fd_prices"}
                leg_b = {k: v for k, v in b.items() if k != "_dk_fd_prices"}

            amer = american_from_dec(dec)
            ev = p * (dec - 1.0) - (1.0 - p)
            try:
                from src.utils.ev import compute_recommended_bet_size

                parlay_sizing = compute_recommended_bet_size(
                    p,
                    amer,
                    ev=ev,
                    confidence_tier="LOW" if ev < 0.08 else "MEDIUM",
                    min_units=0.25,
                    max_units=0.75,
                )
            except Exception:
                parlay_sizing = {"units": 0.5, "bankroll_pct": 0.5, "kelly_fraction": 0.005, "sizing_tier": "Half-Unit Play"}
            combos.append({
                "legs": [leg_a, leg_b],
                "p_win": p,
                "decimal_odds": dec,
                "american_odds": amer,
                "ev": ev,
                "outcome": parlay_outcome,
                "same_book": same_book,
                "parlay_book": parlay_book,
                "sweet_spot_legs": sum(1 for leg_item in (leg_a, leg_b) if leg_item.get("is_sweet_spot_7pt")),
                "suggested_units": parlay_sizing["units"],
                "bankroll_pct": parlay_sizing["bankroll_pct"],
                "sizing_tier": parlay_sizing["sizing_tier"],
                "kelly": parlay_sizing["kelly_fraction"],
            })

    def in_parlay_band(c: dict) -> bool:
        try:
            a = int(c.get("american_odds") or 0)
        except Exception:
            return False
        min_combo_ev = 0.01 if _strategy == "home_fav" else float(min_ev_per_unit)
        if float(c.get("ev") or 0.0) < min_combo_ev:
            return False
        return int(parlay_odds_lo) <= a <= int(parlay_odds_hi)

    combos_in_band = [c for c in combos if in_parlay_band(c)]

    def get_independent_combos(combo_list: Sequence[dict], limit: int, avoid_eids=None):
        used = set(avoid_eids) if avoid_eids else set()
        accepted_list = []
        for c in combo_list:
            e1 = c["legs"][0].get("event_id")
            e2 = c["legs"][1].get("event_id")
            if e1 not in used and e2 not in used:
                accepted_list.append(c)
                used.add(e1)
                used.add(e2)
            if len(accepted_list) >= limit:
                break
        return accepted_list, used

    if _strategy == "home_fav":
        sorted_by_win = sorted(
            combos_in_band,
            key=lambda x: (1 if x.get("same_book") else 0, int(x.get("sweet_spot_legs") or 0), round(float(x["p_win"]), 3), x["ev"]),
            reverse=True,
        )
    else:
        sorted_by_win = sorted(
            combos_in_band,
            key=lambda x: (1 if x.get("same_book") else 0, x["p_win"], x["ev"]),
            reverse=True,
        )
    high_conf, used_eids = get_independent_combos(sorted_by_win, 5)

    plus_money = [c for c in combos_in_band if (c.get("american_odds") or 0) >= 100]
    sorted_plus_money = sorted(plus_money, key=lambda x: (1 if x.get("same_book") else 0, x["ev"], x["p_win"]), reverse=True)
    payout_band, payout_eids = get_independent_combos(sorted_plus_money, 5, avoid_eids=used_eids)

    if len(payout_band) < 5:
        sorted_chalk = sorted([c for c in combos_in_band if c not in plus_money], key=lambda x: (x["ev"], x["p_win"]), reverse=True)
        combined_avoid = used_eids.union(payout_eids)
        extra_chalk, _ = get_independent_combos(sorted_chalk, 5 - len(payout_band), avoid_eids=combined_avoid)
        payout_band.extend(extra_chalk)

    if not payout_band:
        payout_band, _ = get_independent_combos(sorted_by_win, 5, avoid_eids=used_eids)
        if not payout_band:
            payout_band = [c for c in sorted_by_win if c not in high_conf][:5]

    official_daily_parlay = None
    try:
        if _strategy != "home_fav":
            date_et_val = str(resolved_date_et or "")
            if not date_et_val:
                try:
                    with get_db_connection() as conn:
                        date_et_val = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]
                except Exception:
                    date_et_val = datetime.now(timezone.utc).date().isoformat()

            existing_locked = None
            try:
                with get_db_connection() as conn:
                    row_lk = _exec(
                        conn,
                        """
                        SELECT parlay_json, locked_at, american_odds, p_win, ev, bucket
                        FROM recommended_parlays
                        WHERE league = 'NCAAM' AND date_et = %s AND kind = 'ML2'
                          AND locked_at IS NOT NULL AND parlay_json IS NOT NULL
                        ORDER BY locked_at ASC
                        LIMIT 1
                        """,
                        (date_et_val,),
                    ).fetchone()
                    if row_lk:
                        existing_locked = dict(row_lk)
            except Exception:
                existing_locked = None

            if existing_locked and existing_locked.get("parlay_json"):
                try:
                    pj = existing_locked["parlay_json"]
                    if isinstance(pj, str):
                        pj = json.loads(pj)
                    if isinstance(pj, dict):
                        if isinstance(pj.get("legs"), list) and len(pj["legs"]) == 2:
                            _grade_parlay_legs_from_results(pj["legs"])
                            pj["outcome"] = _combine_two_leg_outcome(
                                pj["legs"][0].get("outcome"),
                                pj["legs"][1].get("outcome"),
                            )
                        pj["is_locked"] = True
                        pj["locked_at"] = str(existing_locked.get("locked_at") or "")
                        pj["is_official_daily"] = True
                        official_daily_parlay = pj
                except Exception:
                    official_daily_parlay = None

            if official_daily_parlay is None and (high_conf or payout_band):
                chosen = high_conf[0] if high_conf else payout_band[0]
                earliest_tip = None
                for lg in (chosen.get("legs") or []):
                    st_raw = str(lg.get("start_time") or "").strip()
                    if not st_raw:
                        continue
                    try:
                        st_dt = datetime.fromisoformat(st_raw.replace("Z", "+00:00"))
                        if st_dt.tzinfo is None:
                            st_dt = st_dt.replace(tzinfo=timezone.utc)
                        if earliest_tip is None or st_dt < earliest_tip:
                            earliest_tip = st_dt
                    except Exception:
                        continue

                now_utc = datetime.now(timezone.utc)
                should_lock = bool(persist) or (
                    int(days_ago or 0) == 0
                    and not target_date
                    and earliest_tip is not None
                    and (now_utc - timedelta(minutes=15)) <= earliest_tip <= (now_utc + timedelta(minutes=10))
                )

                official_daily_parlay = {
                    **chosen,
                    "is_official_daily": True,
                    "is_locked": bool(should_lock),
                    "locked_at": (now_utc.isoformat() if should_lock else None),
                    "locks_at": ((earliest_tip - timedelta(minutes=10)).isoformat() if earliest_tip else None),
                }

                if should_lock:
                    eids = sorted([str(chosen["legs"][0].get("event_id") or ""), str(chosen["legs"][1].get("event_id") or "")])
                    pair_key = "|".join(eids)
                    ukey = hashlib.sha256(("NCAAM|ML2|" + pair_key).encode()).hexdigest()
                    bucket = "high_confidence" if high_conf else "payout_band"
                    pid = hashlib.sha256((str(date_et_val) + "|" + ukey).encode()).hexdigest()

                    ddl = """
                      CREATE TABLE IF NOT EXISTS recommended_parlays (
                        id TEXT PRIMARY KEY,
                        league TEXT NOT NULL,
                        date_et TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        bucket TEXT,
                        american_odds INTEGER,
                        p_win REAL,
                        ev REAL,
                        event_id_1 TEXT,
                        event_id_2 TEXT,
                        parlay_json TEXT,
                        locked_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        UNIQUE(league, date_et, kind, event_id_1, event_id_2)
                      );
                    """
                    try:
                        with get_admin_db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute(ddl)
                                cur.execute("ALTER TABLE recommended_parlays ADD COLUMN IF NOT EXISTS parlay_json TEXT;")
                                cur.execute("ALTER TABLE recommended_parlays ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ;")
                            conn.commit()
                    except Exception:
                        pass

                    with get_db_connection() as conn:
                        _exec(conn, """
                          INSERT INTO recommended_parlays (id, league, date_et, kind, bucket, american_odds, p_win, ev, event_id_1, event_id_2, parlay_json, locked_at)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                          ON CONFLICT (league, date_et, kind, event_id_1, event_id_2) DO UPDATE SET
                            parlay_json = COALESCE(recommended_parlays.parlay_json, EXCLUDED.parlay_json),
                            locked_at = COALESCE(recommended_parlays.locked_at, EXCLUDED.locked_at)
                        """, (
                            pid, "NCAAM", str(date_et_val), "ML2", bucket,
                            int(chosen.get("american_odds") or 0),
                            float(chosen.get("p_win") or 0.0),
                            float(chosen.get("ev") or 0.0),
                            eids[0], eids[1],
                            json.dumps(official_daily_parlay, default=str),
                        ))
                        if hasattr(conn, "commit"):
                            conn.commit()
    except Exception as e:
        try:
            print(f"[parlays] official daily lock/persist failed: {e}")
        except Exception:
            pass

    three_leg_high_payout = (
        build_three_leg_high_payout_parlays(norm_legs, min_ev=max(0.04, float(min_ev_per_unit)))
        if _strategy != "home_fav"
        else []
    )

    return {
        "status": "success",
        "date_et": resolved_date_et,
        "strategy": _strategy,
        "legs_considered": len(norm_legs),
        "combos_considered": len(combos),
        "params": {
            "min_ev_per_unit": float(min_ev_per_unit),
            "odds_lo": int(parlay_odds_lo),
            "odds_hi": int(parlay_odds_hi),
        },
        "official_daily_parlay": official_daily_parlay,
        "high_confidence": high_conf,
        "payout_band": payout_band,
        "three_leg_high_payout": three_leg_high_payout,
    }
