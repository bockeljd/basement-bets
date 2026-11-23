from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any


VALID_TIMING_ACTIONS = ("BET_NOW", "WAIT_LINEUPS", "MONITOR")

DEFAULT_TIMING_THRESHOLDS: dict[str, float] = {
    "imminent_tip_mins": 60.0,
    "sharp_edge_pts_min": 0.5,
    "opp_public_pct_min": 62.0,
    "opp_public_min_mins_to_tip": 90.0,
    "our_public_pct_min": 65.0,
    "early_special_mins_to_tip": 180.0,
    "early_default_mins_to_tip": 240.0,
    "strong_ev_min": 0.06,
}

_CALIBRATION_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "data",
        "model_params",
        "bet_timing_calibration.json",
    )
)

_UNCERTAIN_STATUS_RE = re.compile(
    r"\b(questionable|doubtful|gtd|game[- ]time|day[- ]to[- ]day)\b",
    re.IGNORECASE,
)


def load_timing_thresholds(calibration_path: str | None = None) -> dict[str, float]:
    """Load data-tunable timing thresholds, merging optional calibration JSON overrides."""
    thresholds = dict(DEFAULT_TIMING_THRESHOLDS)
    path = calibration_path or _CALIBRATION_PATH
    if not path or not os.path.exists(path):
        return thresholds
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        source = payload.get("thresholds", payload) if isinstance(payload, dict) else {}
        if isinstance(source, dict):
            for key, default_val in DEFAULT_TIMING_THRESHOLDS.items():
                if key in source and source[key] is not None:
                    try:
                        val = float(source[key])
                        if val >= 0:
                            thresholds[key] = val
                    except (TypeError, ValueError):
                        pass
    except Exception:
        pass
    return thresholds


def _to_float(val: Any) -> float | None:
    if val is None or isinstance(val, bool) or val == "":
        return None
    try:
        num = float(val)
        return num if num == num else None
    except (TypeError, ValueError):
        return None


def _parse_dt_utc(val: Any) -> datetime | None:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
    try:
        txt = str(val).strip()
        if not txt:
            return None
        dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _extract_tags(rec: dict) -> list[str]:
    raw = rec.get("movement_tags") or rec.get("sanity_reasons")
    if isinstance(raw, str):
        return [t.strip().lower() for t in raw.split(",") if t and t.strip()]
    if isinstance(raw, (list, tuple, set)):
        return [str(t).strip().lower() for t in raw if t is not None and str(t).strip()]
    return []


def _extract_uncertain_players(signals: dict) -> list[str]:
    seen: set[str] = set()
    players: list[str] = []

    def _check_entry(entry: Any) -> None:
        if not isinstance(entry, dict):
            return
        status = str(entry.get("status") or "").strip()
        if not status or not _UNCERTAIN_STATUS_RE.search(status):
            return
        name = str(entry.get("player") or entry.get("name") or "").strip()
        label = name or "Key player"
        key = label.lower()
        if key not in seen:
            seen.add(key)
            players.append(label)

    raw_inj = signals.get("injuries")
    if isinstance(raw_inj, list):
        for item in raw_inj:
            _check_entry(item)

    inj_impact = signals.get("injuries_impact")
    if isinstance(inj_impact, dict):
        impact_players = inj_impact.get("impact_players")
        if isinstance(impact_players, list):
            for item in impact_players:
                _check_entry(item)

    return players


def _resolve_split_market(bet_type: str, selection: str) -> str:
    if "TOTAL" in bet_type or re.search(r"\b(OVER|UNDER)\b", selection, re.IGNORECASE):
        return "TOTAL"
    if bet_type in ("ML", "MONEYLINE", "H2H") or "MONEYLINE" in bet_type:
        return "ML"
    if "SPREAD" in bet_type:
        return "SPREAD"
    return bet_type


def _resolve_pick_side(
    rec: dict,
    split_mkt: str,
    home_team: str | None = None,
    away_team: str | None = None,
) -> str | None:
    raw_side = str(rec.get("side") or "").strip().upper()
    if split_mkt == "TOTAL":
        if raw_side in ("OVER", "UNDER"):
            return raw_side
        sel_up = str(rec.get("selection") or rec.get("pick") or "").upper()
        if "OVER" in sel_up:
            return "OVER"
        if "UNDER" in sel_up:
            return "UNDER"
        return None

    if raw_side in ("HOME", "AWAY"):
        return raw_side

    sel_low = str(rec.get("selection") or rec.get("pick") or "").strip().lower()
    h_low = str(home_team or rec.get("home_team") or "").strip().lower()
    a_low = str(away_team or rec.get("away_team") or "").strip().lower()
    if h_low and sel_low.startswith(h_low):
        return "HOME"
    if a_low and sel_low.startswith(a_low):
        return "AWAY"
    if h_low and h_low in sel_low and (not a_low or a_low not in sel_low):
        return "HOME"
    if a_low and a_low in sel_low and (not h_low or h_low not in sel_low):
        return "AWAY"
    return None


def _extract_ev_decimal(rec: dict) -> float | None:
    for key in ("ev", "ev_per_unit", "expected_value"):
        num = _to_float(rec.get(key))
        if num is not None:
            return num / 100.0 if abs(num) > 1.5 else num
    raw_edge = rec.get("edge")
    if isinstance(raw_edge, str) and "%" in raw_edge:
        parsed = _to_float(raw_edge.replace("%", "").replace("+", "").strip())
        if parsed is not None:
            return parsed / 100.0
    return None


def compute_bet_timing(
    rec: dict | None,
    *,
    start_time: Any = None,
    now_utc: datetime | None = None,
    context: dict | None = None,
    home_team: str | None = None,
    away_team: str | None = None,
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """
    Compute data-driven "When to Bet" timing guidance for a recommended pick.

    Returns a dictionary with action ('BET_NOW', 'WAIT_LINEUPS', 'MONITOR'),
    labels, tone, plain-English reason, drivers, and minutes_to_tip, or None
    if the recommendation is invalid or the game has already tipped off.
    """
    if not isinstance(rec, dict):
        return None

    cfg = dict(load_timing_thresholds())
    if isinstance(thresholds, dict):
        for k, v in thresholds.items():
            fv = _to_float(v)
            if fv is not None:
                cfg[k] = fv

    ctx = context if isinstance(context, dict) else {}
    ref_now = _parse_dt_utc(now_utc) or datetime.now(timezone.utc)
    tip_dt = _parse_dt_utc(
        start_time
        or rec.get("start_time")
        or ctx.get("start_time")
    )
    minutes_to_tip: float | None = None
    if tip_dt is not None:
        minutes_to_tip = round((tip_dt - ref_now).total_seconds() / 60.0, 1)
        if minutes_to_tip <= 0:
            return None

    tags = _extract_tags(rec)
    signals = rec.get("signals") if isinstance(rec.get("signals"), dict) else {}
    sharp_edge_pts = _to_float(rec.get("sharp_edge_pts"))
    has_sharp_price_edge = (
        (sharp_edge_pts is not None and sharp_edge_pts >= cfg["sharp_edge_pts_min"])
        or ("sharp_price_edge" in tags)
        or ("lagging_book_edge" in tags)
    )
    has_sharp_steam = ("rlm_confirmed" in tags) or ("sharp_backing" in tags)

    bet_type = str(rec.get("bet_type") or rec.get("market_type") or rec.get("market") or "").upper().strip()
    selection_text = str(rec.get("selection") or rec.get("pick") or "")
    is_first_half = bet_type in ("TOTAL_1H", "SPREAD_1H") or ("first_half_market" in tags)
    is_smart_risk = (
        bool(rec.get("is_smart_risk"))
        or str(rec.get("risk_tier") or "").strip().upper() == "SMART_RISK"
        or ("smart_risk_high_return" in tags)
    )
    book_name = str(rec.get("book") or "Sportsbook").strip() or "Sportsbook"
    uncertain_players = _extract_uncertain_players(signals)

    split_mkt = _resolve_split_market(bet_type, selection_text)
    pick_side = _resolve_pick_side(
        rec,
        split_mkt,
        home_team=home_team or ctx.get("home_team"),
        away_team=away_team or ctx.get("away_team"),
    )
    pick_bet_pct: float | None = None
    opp_bet_pct: float | None = None
    splits = signals.get("public_splits")
    if isinstance(splits, dict) and split_mkt in splits and isinstance(splits[split_mkt], dict) and pick_side:
        opp_side = (
            ("UNDER" if pick_side == "OVER" else "OVER")
            if split_mkt == "TOTAL"
            else ("AWAY" if pick_side == "HOME" else "HOME")
        )
        pick_entry = splits[split_mkt].get(pick_side)
        opp_entry = splits[split_mkt].get(opp_side)
        if isinstance(pick_entry, dict):
            pick_bet_pct = _to_float(pick_entry.get("bet_pct"))
        if isinstance(opp_entry, dict):
            opp_bet_pct = _to_float(opp_entry.get("bet_pct"))

    adj = signals.get("adjustments") if isinstance(signals.get("adjustments"), dict) else {}
    raw_agree = (
        rec.get("conviction_sources_total")
        if "TOTAL" in bet_type
        else rec.get("conviction_sources")
    )
    if raw_agree is None:
        raw_agree = (
            adj.get("conviction_sources_total")
            if "TOTAL" in bet_type
            else adj.get("conviction_sources")
        )
    if raw_agree is None:
        raw_agree = (
            ctx.get("conviction_sources_total")
            if "TOTAL" in bet_type
            else ctx.get("conviction_sources")
        )
    agree_count = int(round(_to_float(raw_agree) or 0))
    ev_dec = _extract_ev_decimal(rec)

    def _pack(action: str, reason: str, drivers: list[str]) -> dict[str, Any]:
        meta = {
            "BET_NOW": {
                "label": "Bet Now",
                "short_label": "Bet Now",
                "tone": "emerald",
            },
            "WAIT_LINEUPS": {
                "label": "Wait · Check Lineups",
                "short_label": "Wait Lineups",
                "tone": "amber",
            },
            "MONITOR": {
                "label": "Monitor · May Improve",
                "short_label": "Monitor",
                "tone": "blue",
            },
        }[action]
        return {
            "action": action,
            "label": meta["label"],
            "short_label": meta["short_label"],
            "tone": meta["tone"],
            "reason": reason,
            "drivers": drivers,
            "minutes_to_tip": minutes_to_tip,
        }

    # 1. Tipoff imminent (<= 60 min)
    if minutes_to_tip is not None and minutes_to_tip <= cfg["imminent_tip_mins"]:
        drivers = ["tipoff_imminent"]
        if has_sharp_price_edge:
            drivers.append("sharp_price_edge")
        mins_int = max(1, int(round(minutes_to_tip)))
        if sharp_edge_pts is not None and sharp_edge_pts >= cfg["sharp_edge_pts_min"]:
            reason = (
                f"Tipoff in ~{mins_int} min and {book_name} is {sharp_edge_pts:.1f} pts better than sharp books — lock in before close."
            )
        elif uncertain_players:
            listed = ", ".join(uncertain_players[:2])
            reason = f"Tipoff in ~{mins_int} min — confirm final status on {listed}, then lock in before tip."
        else:
            reason = f"Tipoff in ~{mins_int} min — closing lines are firming up, good time to lock it in."
        return _pack("BET_NOW", reason, drivers)

    # 2. Uncertain lineup news (> 60 min or unknown start_time)
    if uncertain_players:
        listed = ", ".join(uncertain_players[:2])
        suffix = " listed Questionable/Doubtful" if len(uncertain_players) > 1 else " is Questionable/Doubtful"
        return _pack(
            "WAIT_LINEUPS",
            f"{listed}{suffix} — wait for lineup news ~45 min before tip.",
            ["uncertain_injury"],
        )

    # 3. Sharp-book lag or sharp steam
    if has_sharp_price_edge or has_sharp_steam:
        drivers: list[str] = []
        if has_sharp_price_edge:
            if sharp_edge_pts is not None and sharp_edge_pts >= cfg["sharp_edge_pts_min"]:
                drivers.append("sharp_price_edge")
            elif "sharp_price_edge" in tags:
                drivers.append("sharp_price_edge")
            if "lagging_book_edge" in tags:
                drivers.append("lagging_book_edge")
        if "rlm_confirmed" in tags:
            drivers.append("rlm_confirmed")
        if "sharp_backing" in tags:
            drivers.append("sharp_backing")

        if sharp_edge_pts is not None and sharp_edge_pts >= cfg["sharp_edge_pts_min"]:
            reason = f"{book_name} is {sharp_edge_pts:.1f} pts better than sharp books — likely to move soon."
        elif "sharp_price_edge" in tags or "lagging_book_edge" in tags:
            reason = f"{book_name} is offering a better number than sharp books — take it before it adjusts."
        elif "rlm_confirmed" in tags:
            reason = "Respected money already pushed the line toward this pick — better to grab it now."
        else:
            reason = "Big money is backing this side and the number may tighten closer to tip."
        return _pack("BET_NOW", reason, drivers)

    # 4. Opposite public ticket wave
    if (
        opp_bet_pct is not None
        and opp_bet_pct >= cfg["opp_public_pct_min"]
        and (minutes_to_tip is None or minutes_to_tip > cfg["opp_public_min_mins_to_tip"])
    ):
        return _pack(
            "MONITOR",
            f"{int(round(opp_bet_pct))}% of public tickets are on the other side — waiting may get a better number.",
            ["opposite_public_tickets"],
        )

    # 5. Early 1H or Smart Risk play (> 3h to tip)
    if (
        (is_first_half or is_smart_risk)
        and minutes_to_tip is not None
        and minutes_to_tip > cfg["early_special_mins_to_tip"]
    ):
        hrs = max(1, int(round(minutes_to_tip / 60.0)))
        if is_first_half:
            return _pack(
                "MONITOR",
                f"1st-half limits are light with ~{hrs}h to tip — check again closer to game time.",
                ["early_1h_market"],
            )
        return _pack(
            "MONITOR",
            f"Higher-variance Smart Risk play with ~{hrs}h to tip — monitor line moves before sizing in.",
            ["early_smart_risk"],
        )

    # 6. Our-side public steam or high conviction
    has_our_public = pick_bet_pct is not None and pick_bet_pct >= cfg["our_public_pct_min"]
    has_high_conv = agree_count >= 3
    has_strong_ev = ev_dec is not None and ev_dec >= cfg["strong_ev_min"]
    if has_our_public or has_high_conv or has_strong_ev:
        drivers = []
        if has_our_public:
            drivers.append("our_public_steam")
        if has_high_conv:
            drivers.append("high_conviction")
        if has_strong_ev:
            drivers.append("strong_ev")

        if has_our_public:
            reason = f"{int(round(pick_bet_pct))}% of tickets are backing this side — bet now before the line moves away."
        elif has_high_conv:
            reason = f"{agree_count}-of-{agree_count} rating models agree with no injury flags — strong number to grab now."
        else:
            reason = f"High +{ev_dec * 100:.1f}% value cushion is likely to trim down closer to tipoff."
        return _pack("BET_NOW", reason, drivers)

    # 7. Default fallback
    if minutes_to_tip is not None and minutes_to_tip > cfg["early_default_mins_to_tip"]:
        hrs = max(1, int(round(minutes_to_tip / 60.0)))
        return _pack(
            "MONITOR",
            f"No sharp-book rush yet with ~{hrs}h to tip — fine to watch for a better number.",
            ["early_no_rush"],
        )

    return _pack(
        "BET_NOW",
        "Clean number with no lineup flags — good to lock in now.",
        ["clean_number"],
    )


def extract_bet_timing_action(row: dict | None) -> str | None:
    """Extract canonical bet timing action from a history row or nested rec_json."""
    if not isinstance(row, dict):
        return None
    candidates = [row.get("bet_timing_action")]
    bt = row.get("bet_timing")
    if isinstance(bt, dict):
        candidates.append(bt.get("action"))
    elif isinstance(bt, str):
        candidates.append(bt)
    rec_obj = row.get("rec_json")
    if isinstance(rec_obj, dict):
        candidates.append(rec_obj.get("bet_timing_action"))
        rbt = rec_obj.get("bet_timing")
        if isinstance(rbt, dict):
            candidates.append(rbt.get("action"))
        elif isinstance(rbt, str):
            candidates.append(rbt)
    for cand in candidates:
        if not cand:
            continue
        act = str(cand).strip().upper()
        if act in VALID_TIMING_ACTIONS:
            return act
    return None


def summarize_timing_clv(rows: list[dict] | None) -> list[dict[str, Any]]:
    """Aggregate decided bets and Closing Line Value (CLV) metrics by timing action."""
    labels = {
        "BET_NOW": "Bet Now",
        "WAIT_LINEUPS": "Wait · Check Lineups",
        "MONITOR": "Monitor · May Improve",
    }
    buckets = {
        action: {
            "action": action,
            "label": labels[action],
            "count": 0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "clv_count": 0,
            "clv_sum": 0.0,
            "positive_clv_count": 0,
        }
        for action in VALID_TIMING_ACTIONS
    }

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        action = extract_bet_timing_action(row)
        if not action or action not in buckets:
            continue
        raw_out = str(row.get("graded_result") or row.get("outcome") or row.get("result") or "").upper().strip()
        if raw_out in ("WIN", "WON"):
            norm_out = "WON"
        elif raw_out in ("LOSS", "LOST"):
            norm_out = "LOST"
        elif raw_out == "PUSH":
            norm_out = "PUSH"
        else:
            continue

        b = buckets[action]
        b["count"] += 1
        if norm_out == "WON":
            b["wins"] += 1
        elif norm_out == "LOST":
            b["losses"] += 1
        else:
            b["pushes"] += 1

        clv = _to_float(row.get("clv_points"))
        if clv is not None:
            b["clv_count"] += 1
            b["clv_sum"] += clv
            if clv > 0:
                b["positive_clv_count"] += 1

    out: list[dict[str, Any]] = []
    for action in VALID_TIMING_ACTIONS:
        b = buckets[action]
        avg_clv = round(b["clv_sum"] / b["clv_count"], 2) if b["clv_count"] > 0 else None
        pos_rate = (
            round((b["positive_clv_count"] / b["clv_count"]) * 100.0, 1)
            if b["clv_count"] > 0
            else None
        )
        out.append({
            "action": b["action"],
            "label": b["label"],
            "count": b["count"],
            "wins": b["wins"],
            "losses": b["losses"],
            "pushes": b["pushes"],
            "clv_count": b["clv_count"],
            "avg_clv": avg_clv,
            "positive_clv_rate": pos_rate,
        })
    return out
