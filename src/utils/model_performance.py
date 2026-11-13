
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


def normalize_market_type(market_type, *, is_parlay: bool = False, bet_type=None) -> str:
    """Normalize legacy and vendor market labels into canonical UI categories."""
    if is_parlay or "PARLAY" in str(bet_type or "").upper():
        return "PARLAY"

    raw = str(market_type or "").strip().upper()
    if not raw or raw in ("AUTO", "NONE", "UNKNOWN"):
        return "OTHER"
    if raw in ("H2H", "ML", "MONEYLINE", "MONEY LINE") or "MONEYLINE" in raw:
        return "MONEYLINE"
    if "SPREAD" in raw:
        return "SPREAD"
    if "TOTAL" in raw or raw in ("OVER", "UNDER", "OU", "O/U"):
        return "TOTAL"
    if "PARLAY" in raw:
        return "PARLAY"
    return raw


def format_matchup(row: dict) -> str:
    """Return a clean 'Away @ Home' matchup label from row fields."""
    for key in ("matchup", "game"):
        val = str(row.get(key) or "").strip()
        if val and val not in ("—", "-"):
            return val
    away = str(row.get("away_team") or "").strip()
    home = str(row.get("home_team") or "").strip()
    if away and home:
        return f"{away} @ {home}"
    return away or home or ""


def normalize_confidence_pct(val):
    """Normalize confidence to a 0-100 scale when present."""
    if val is None or isinstance(val, bool):
        return None
    try:
        num = float(val)
    except Exception:
        return None
    if 0.0 < num <= 1.0:
        return round(num * 100.0, 1)
    return round(num, 1)


def _first_present(*vals):
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return v
    return None


def _meaningful_pick_text(val) -> str:
    s = str(val or "").strip()
    if s.upper() in ("", "NONE", "NULL", "-", "—"):
        return ""
    return s


def normalize_history_row(row: dict) -> dict:
    """Normalize a single history/slate pick row for consistent analytics and UI rendering."""
    out = dict(row or {})
    out["market_type"] = normalize_market_type(
        _first_present(out.get("market_type"), out.get("market"), out.get("bet_type")),
        is_parlay=bool(out.get("is_parlay")),
        bet_type=out.get("bet_type"),
    )
    out["outcome"] = norm_outcome(out.get("graded_result") or out.get("outcome") or out.get("result"))
    out["sport"] = _first_present(out.get("sport"), out.get("league")) or "NCAAM"

    matchup = format_matchup(out)
    if matchup:
        out["matchup"] = matchup

    eff_price = _first_present(out.get("bet_price"), out.get("price"))
    if eff_price is not None:
        out["bet_price"] = eff_price
        out["price"] = eff_price

    eff_line = _first_present(out.get("bet_line"), out.get("line"))
    if eff_line is not None:
        out["bet_line"] = eff_line

    sel = _meaningful_pick_text(out.get("selection"))
    pick = _meaningful_pick_text(out.get("pick"))
    bet_on = _meaningful_pick_text(out.get("bet_on"))
    best_pick = sel or bet_on or pick
    if best_pick:
        if not sel:
            out["selection"] = best_pick
        if not pick:
            out["pick"] = best_pick
        if not bet_on:
            out["bet_on"] = best_pick

    conf = normalize_confidence_pct(out.get("confidence_0_100") if out.get("confidence_0_100") is not None else out.get("confidence"))
    if conf is not None:
        out["confidence_0_100"] = conf

    if out.get("ev_per_unit") is None and out.get("ev") is not None:
        out["ev_per_unit"] = out.get("ev")

    return out


def _semantic_row_key(row: dict):
    eid = str(row.get("event_id") or "").strip()
    mt = str(row.get("market_type") or "").strip().upper()
    if not eid or not mt:
        return None
    if mt == "OTHER":
        sel = _meaningful_pick_text(row.get("selection") or row.get("pick"))
        return (eid, mt, sel)
    return (eid, mt)


def dedupe_and_merge_history(canonical_rows: list, fallback_rows: list) -> list:
    """Normalize and merge canonical slate rows with fallback predictions without double-counting."""
    merged = []
    seen_ids = set()
    seen_sem = set()

    for raw in canonical_rows or []:
        row = normalize_history_row(raw)
        row["source_type"] = "canonical_slate"
        rid = row.get("id")
        sem = _semantic_row_key(row)
        if rid and rid in seen_ids:
            continue
        if sem and sem in seen_sem:
            continue
        if rid:
            seen_ids.add(rid)
        if sem:
            seen_sem.add(sem)
        merged.append(row)

    for raw in fallback_rows or []:
        row = normalize_history_row(raw)
        row["source_type"] = raw.get("source_type") or "fallback_prediction"
        rid = row.get("id")
        sem = _semantic_row_key(row)
        if rid and rid in seen_ids:
            continue
        if sem and sem in seen_sem:
            continue
        if rid:
            seen_ids.add(rid)
        if sem:
            seen_sem.add(sem)
        merged.append(row)

    return merged
