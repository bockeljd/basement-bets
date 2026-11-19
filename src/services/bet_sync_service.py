from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_BOOK_PROVIDER_MAP = {
    "DK": "DraftKings",
    "DRAFTKINGS": "DraftKings",
    "DRAFTKINGS SPORTSBOOK": "DraftKings",
    "FD": "FanDuel",
    "FANDUEL": "FanDuel",
    "FANDUEL SPORTSBOOK": "FanDuel",
    "BETMGM": "BetMGM",
    "MGM": "BetMGM",
    "CAESARS": "Caesars",
    "CZR": "Caesars",
    "BET365": "bet365",
    "BETRIVERS": "BetRivers",
}


def normalize_sync_provider(raw: Any, fallback: str = "Unknown") -> str:
    txt = str(raw or "").strip()
    if not txt:
        return fallback
    up = txt.upper()
    if up in DEFAULT_BOOK_PROVIDER_MAP:
        return DEFAULT_BOOK_PROVIDER_MAP[up]
    try:
        from src.utils.normalize import normalize_provider

        norm = normalize_provider(txt)
        if norm and norm != "Unknown":
            return norm
    except Exception:
        pass
    return txt


def normalize_account_id(raw: Any, default: str = "Main") -> str:
    txt = str(raw or "").strip()
    if not txt:
        return default
    low = txt.lower()
    if low in ("primary", "main", "1"):
        return "Main"
    if low in ("secondary", "user2", "2"):
        return "User2"
    return txt


def normalize_date_str(raw: Any) -> str:
    txt = str(raw or "").strip()
    if not txt:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    iso_match = re.search(r"(\d{4}-\d{2}-\d{2})", txt)
    if iso_match:
        return iso_match.group(1)
    for fmt in ("%m/%d/%Y %I:%M%p", "%m/%d/%Y %I:%M %p", "%m/%d/%Y", "%m-%d-%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            cleaned = re.sub(r"\s+(ET|EST|EDT|CT|CST|CDT|PT|PST|PDT|UTC)$", "", txt, flags=re.IGNORECASE).strip()
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def parse_money_value(raw: Any) -> Optional[float]:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        val = float(raw)
        return val if math.isfinite(val) else None
    txt = str(raw).strip()
    if not txt or txt in ("-", "—", "--", "N/A", "null", "None"):
        return None
    neg = False
    if txt.startswith("(") and txt.endswith(")"):
        neg = True
        txt = txt[1:-1]
    if txt.startswith("-"):
        neg = True
        txt = txt[1:]
    txt = txt.replace("$", "").replace(",", "").replace("+", "").strip()
    m = re.search(r"(\d+(?:\.\d+)?)", txt)
    if not m:
        return None
    val = float(m.group(1))
    return -val if neg else val


def parse_american_odds(raw: Any) -> Optional[int]:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw != 0 else None
    if isinstance(raw, float):
        if not math.isfinite(raw) or raw == 0:
            return None
        # Convert decimal odds > 1.01 ONLY if small float like 1.91 and not already -110/+150
        if 1.01 < abs(raw) < 30.0 and raw != int(raw):
            return decimal_to_american(raw)
        return int(round(raw))
    txt = str(raw).strip().upper()
    if not txt or txt in ("-", "—", "NONE", "N/A"):
        return None
    if txt in ("EVEN", "EV", "PK", "PICK"):
        return 100
    m = re.search(r"([+-]?\d{3,5})", txt)
    if m:
        val = int(m.group(1))
        if val != 0:
            return val
    try:
        f = float(txt)
        if 1.01 < f < 30.0:
            return decimal_to_american(f)
    except Exception:
        pass
    return None


def decimal_to_american(dec: float) -> Optional[int]:
    if not dec or dec <= 1.0:
        return None
    if dec >= 2.0:
        return int(round((dec - 1.0) * 100.0))
    return int(round(-100.0 / (dec - 1.0)))


def american_to_implied_prob(odds: Optional[int]) -> Optional[float]:
    if odds is None or odds == 0:
        return None
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def american_to_decimal(odds: Optional[int]) -> Optional[float]:
    if odds is None or odds == 0:
        return None
    if odds > 0:
        return 1.0 + (odds / 100.0)
    return 1.0 + (100.0 / abs(odds))


def compute_bet_profit(status: str, wager: float, odds: Optional[int], explicit_profit: Optional[float] = None, payout: Optional[float] = None) -> float:
    st = str(status or "PENDING").upper()
    w = max(0.0, float(wager or 0.0))
    if explicit_profit is not None and math.isfinite(float(explicit_profit)):
        return round(float(explicit_profit), 2)
    if payout is not None and math.isfinite(float(payout)):
        if st in ("PENDING", "OPEN"):
            return 0.0
        if st in ("PUSH", "VOID"):
            return 0.0
        return round(float(payout) - w, 2)
    if st == "LOST":
        return round(-w, 2)
    if st in ("PENDING", "OPEN", "PUSH", "VOID"):
        return 0.0
    if st == "WON" and odds:
        if odds > 0:
            return round(w * (odds / 100.0), 2)
        return round(w * (100.0 / abs(odds)), 2)
    return 0.0


def normalize_bet_status(raw: Any, profit: Optional[float] = None, wager: Optional[float] = None, payout: Optional[float] = None) -> str:
    txt = str(raw or "").strip().upper()
    if txt in ("WON", "WIN", "W", "SETTLED_WIN"):
        return "WON"
    if txt in ("LOST", "LOSS", "LOSE", "L", "SETTLED_LOSS"):
        return "LOST"
    if txt in ("PUSH", "TIE", "TIED", "SETTLED_PUSH"):
        return "PUSH"
    if txt in ("VOID", "CANCELLED", "CANCELED", "REFUNDED", "NO ACTION"):
        return "VOID"
    if "CASHOUT" in txt or "CASHED" in txt or "CASH OUT" in txt:
        eff_profit = profit
        if eff_profit is None and payout is not None and wager is not None:
            eff_profit = float(payout) - float(wager)
        if eff_profit is not None:
            if eff_profit > 0.005:
                return "WON"
            if eff_profit < -0.005:
                return "LOST"
            return "PUSH"
        return "WON"
    if txt in ("PENDING", "OPEN", "ACTIVE", "ACCEPTED", "PLACED", "LIVE", "UNSETTLED"):
        return "PENDING"
    if "WIN" in txt or "WON" in txt:
        return "WON"
    if "LOSS" in txt or "LOST" in txt:
        return "LOST"
    if "VOID" in txt or "CANCEL" in txt:
        return "VOID"
    if "PUSH" in txt:
        return "PUSH"
    return "PENDING"


def stable_external_id(provider: str, payload_parts: List[Any], prefix: str = "sync") -> str:
    raw = "|".join(str(x or "").strip() for x in payload_parts)
    digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]
    slug = re.sub(r"[^a-z0-9]", "", provider.lower())[:8] or "book"
    return f"{slug}_{prefix}_{digest}"


def _resolve_sport_label(sport_raw: Any, description: str = "", selection: str = "", raw_text: str = "") -> str:
    from src.utils.sport_normalization import CANONICAL_SPORTS, normalize_sport

    cand = normalize_sport(sport_raw)
    if cand and cand in CANONICAL_SPORTS and cand != "UNKNOWN":
        return cand
    combined = f"{sport_raw or ''} {description} {selection} {raw_text}".lower()
    if any(k in combined for k in ("ncaa basketball", "ncaam", "ncaab", "college basketball", "men's college")):
        return "NCAAM"
    if any(k in combined for k in ("college football", "ncaaf")):
        return "NCAAF"
    if "nfl" in combined or "pro football" in combined:
        return "NFL"
    if "nba" in combined or "pro basketball" in combined:
        return "NBA"
    if "mlb" in combined or "baseball" in combined:
        return "MLB"
    if "nhl" in combined or "hockey" in combined:
        return "NHL"
    if "ufc" in combined or "mma" in combined:
        return "MMA"
    if "epl" in combined or "premier league" in combined or "soccer" in combined:
        return "EPL"
    return cand if cand and cand != "UNKNOWN" else "Other"


def _normalize_bet_doc(
    item: Dict[str, Any],
    user_id: str,
    default_provider: Optional[str],
    default_account_id: str,
    source: str,
) -> Optional[Dict[str, Any]]:
    provider = normalize_sync_provider(
        item.get("provider") or item.get("sportsbook") or default_provider or "Unknown"
    )
    account_id = normalize_account_id(item.get("account_id"), default=default_account_id)

    wager_val = parse_money_value(
        item.get("wager") if item.get("wager") is not None else item.get("stake")
    )
    if wager_val is None:
        wager_val = 0.0
    wager_val = abs(float(wager_val))

    payout_val = parse_money_value(item.get("payout"))
    if payout_val is None:
        payout_val = parse_money_value(item.get("return"))
    explicit_profit = parse_money_value(item.get("profit"))

    price_obj = item.get("price") if isinstance(item.get("price"), dict) else {}
    odds_val = parse_american_odds(
        item.get("odds")
        if item.get("odds") is not None
        else (price_obj.get("american") if price_obj.get("american") is not None else price_obj.get("decimal"))
    )

    closing_odds = parse_american_odds(item.get("closing_odds"))
    status = normalize_bet_status(
        item.get("status"), profit=explicit_profit, wager=wager_val, payout=payout_val
    )
    profit = compute_bet_profit(
        status=status,
        wager=wager_val,
        odds=odds_val,
        explicit_profit=explicit_profit,
        payout=payout_val,
    )

    date_str = normalize_date_str(
        item.get("date") or item.get("placed_at") or item.get("settled_at")
    )
    description = str(
        item.get("description") or item.get("event_name") or item.get("selection") or ""
    ).strip()
    selection = str(item.get("selection") or description or "").strip()
    if not description and not selection:
        return None
    if not description:
        description = selection
    if not selection:
        selection = description

    raw_text = str(item.get("raw_text") or "").strip()
    if not raw_text:
        raw_text = f"{provider} | {date_str} | {description} | {selection} | wager={wager_val}"

    sport_raw = item.get("sport") or ""
    bet_type_raw = str(item.get("bet_type") or item.get("market_type") or "").strip()
    sport = _resolve_sport_label(
        sport_raw,
        description=description,
        selection=selection,
        raw_text=raw_text,
    )

    bet_type = bet_type_raw or _infer_bet_type(selection, description)
    external_id = str(item.get("external_id") or item.get("bet_id") or "").strip() or None
    if not external_id and (item.get("placed_at") or source.endswith("csv") or source.endswith("bookmarklet")):
        # Keep deterministic fallback external_id so overlapping CSV/bookmarklet imports never duplicate
        external_id = stable_external_id(
            provider,
            [account_id, date_str, description[:80], selection[:80], round(wager_val, 2), odds_val],
            prefix="csv" if "csv" in source else "bm",
        )

    return {
        "user_id": str(user_id),
        "account_id": account_id,
        "provider": provider,
        "date": date_str,
        "sport": sport or "Other",
        "bet_type": bet_type,
        "wager": round(wager_val, 2),
        "profit": round(profit, 2),
        "status": status,
        "description": description[:400],
        "selection": selection[:400],
        "odds": odds_val,
        "closing_odds": closing_odds,
        "is_live": bool(item.get("is_live", False)),
        "is_bonus": bool(item.get("is_bonus", False)),
        "raw_text": raw_text[:4000],
        "event_text": item.get("event_text") or item.get("event_name"),
        "external_id": external_id,
        "source": str(item.get("source") or source or "sync")[:64],
    }


def _infer_bet_type(selection: str, description: str) -> str:
    combined = f"{selection} {description}".lower()
    if "parlay" in combined or "sgp" in combined:
        return "Parlay"
    if re.search(r"\b(over|under|total)\b", combined):
        return "Total"
    if re.search(r"\b(moneyline|money line|ml|to win)\b", combined):
        return "Moneyline"
    if re.search(r"[+-]\d+\.5\b|[+-]\d+\b(?!\d)", selection):
        return "Spread"
    return "Straight"


def _upsert_bet_by_external_id_or_v2(doc: Dict[str, Any]) -> Tuple[Optional[int], str]:
    """
    Insert or update a bet cleanly.
    If external_id exists in bets for (user_id, provider, external_id), update status/profit/odds
    in-place so PENDING -> WON/LOST transitions never duplicate and always refresh transactions.
    Otherwise falls back to canonical insert_bet_v2.
    """
    from src.database import _exec, _sync_transaction_for_bet, get_db_connection, insert_bet_v2

    ext_id = doc.get("external_id")
    if ext_id:
        with get_db_connection() as conn:
            row = _exec(
                conn,
                """
                SELECT id, status, profit
                FROM bets
                WHERE user_id = %s AND provider = %s AND external_id = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (doc["user_id"], doc["provider"], ext_id),
            ).fetchone()
            if row:
                bet_id = int(row["id"] if isinstance(row, dict) else row[0])
                _exec(
                    conn,
                    """
                    UPDATE bets SET
                        profit = %s,
                        status = %s,
                        odds = COALESCE(%s, odds),
                        closing_odds = COALESCE(%s, closing_odds),
                        event_text = COALESCE(%s, event_text),
                        raw_text = COALESCE(NULLIF(%s, ''), raw_text),
                        source = COALESCE(%s, source),
                        account_id = COALESCE(%s, account_id)
                    WHERE id = %s
                    """,
                    (
                        doc["profit"],
                        doc["status"],
                        doc["odds"],
                        doc["closing_odds"],
                        doc.get("event_text"),
                        doc.get("raw_text"),
                        doc.get("source"),
                        doc.get("account_id"),
                        bet_id,
                    ),
                )
                conn.commit()
                _sync_transaction_for_bet(bet_id, doc)
                return bet_id, "updated"

    bet_id = insert_bet_v2(doc)
    return bet_id, "inserted"


def ingest_normalized_bets(
    bets: List[Dict[str, Any]],
    user_id: str,
    default_provider: Optional[str] = None,
    default_account_id: str = "Main",
    source: str = "sync",
) -> Dict[str, Any]:
    """Normalize, link best-effort, and idempotently save bets into canonical `bets`."""
    saved_ids: List[int] = []
    inserted = 0
    updated = 0
    skipped = 0
    errors: List[str] = []

    linker = None
    try:
        from src.services.event_linker import EventLinker

        linker = EventLinker()
    except Exception:
        linker = None

    for raw_item in bets or []:
        if not isinstance(raw_item, dict):
            skipped += 1
            continue
        doc = _normalize_bet_doc(
            raw_item,
            user_id=user_id,
            default_provider=default_provider,
            default_account_id=default_account_id,
            source=source,
        )
        if not doc:
            skipped += 1
            continue

        # Best-effort event linkage check without blocking storage
        if linker is not None and not doc.get("event_text"):
            try:
                link_res = linker.link_leg(
                    {"selection": doc["selection"]},
                    doc["sport"],
                    doc["date"],
                    doc["description"],
                )
                if link_res and link_res.get("reason") and link_res.get("event_id"):
                    pass
            except Exception:
                pass

        try:
            bet_id, action = _upsert_bet_by_external_id_or_v2(doc)
            if bet_id:
                saved_ids.append(int(bet_id))
                if action == "updated":
                    updated += 1
                else:
                    inserted += 1
            else:
                skipped += 1
        except Exception as exc:
            errors.append(f"{doc.get('selection', 'bet')[:40]}: {exc}")

    return {
        "total_received": len(bets or []),
        "saved": len(saved_ids),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "errors": errors[:10],
        "bet_ids": saved_ids,
    }


def ingest_statement_transactions(
    txns: List[Dict[str, Any]],
    user_id: str,
    default_provider: Optional[str] = None,
    default_account_id: str = "Main",
) -> int:
    """Idempotently save Deposits, Withdrawals, and Bonus/Adjustments."""
    from src.database import insert_transaction, get_db_connection, _exec

    existing_keys = set()
    try:
        with get_db_connection() as conn:
            rows = _exec(
                conn,
                """
                SELECT provider, COALESCE(account_id, 'Main') AS acc,
                       LEFT(CAST(date AS TEXT), 10) AS dt,
                       type, ROUND(ABS(CAST(amount AS NUMERIC)), 2) AS amt
                FROM transactions
                WHERE user_id = %s
                """,
                (str(user_id),),
            ).fetchall()
            for r in rows or []:
                existing_keys.add((
                    normalize_sync_provider(r["provider"]),
                    normalize_account_id(r["acc"]),
                    str(r["dt"] or "")[:10],
                    str(r["type"] or "").strip().title(),
                    float(r["amt"] or 0.0),
                ))
    except Exception:
        pass

    count = 0
    for raw_txn in txns or []:
        if not isinstance(raw_txn, dict):
            continue
        provider = normalize_sync_provider(
            raw_txn.get("provider") or raw_txn.get("sportsbook") or default_provider or "Unknown"
        )
        account_id = normalize_account_id(raw_txn.get("account_id"), default=default_account_id)
        txn_type = str(raw_txn.get("type") or "").strip().title()
        if txn_type not in ("Deposit", "Withdrawal", "Adjustment", "Bonus", "Promo"):
            continue
        amt = parse_money_value(raw_txn.get("amount"))
        if amt is None or amt == 0:
            continue
        if txn_type == "Withdrawal":
            amt = -abs(amt)
        elif txn_type == "Deposit":
            amt = abs(amt)

        date_str = normalize_date_str(raw_txn.get("date"))
        dedupe_key = (provider, account_id, str(date_str or "")[:10], txn_type, round(abs(amt), 2))
        if dedupe_key in existing_keys:
            continue
        existing_keys.add(dedupe_key)

        desc = str(raw_txn.get("description") or f"{provider} {txn_type}").strip()
        txn_id = str(raw_txn.get("txn_id") or raw_txn.get("id") or "").strip()
        if not txn_id:
            txn_id = stable_external_id(
                provider, [account_id, str(date_str or "")[:10], txn_type, round(abs(amt), 2)], prefix="txn"
            )

        doc = {
            "provider": provider,
            "account_id": account_id,
            "txn_id": txn_id,
            "date": date_str,
            "type": txn_type,
            "description": desc[:300],
            "amount": round(amt, 2),
            "balance": parse_money_value(raw_txn.get("balance")),
            "user_id": str(user_id),
            "raw_data": raw_txn,
        }
        if insert_transaction(doc):
            count += 1
    return count


def record_balance_snapshot(
    provider: str,
    account_id: str,
    balance: Any,
    user_id: str,
    source: str,
    note: Optional[str] = None,
    raw_data: Any = None,
) -> bool:
    from src.database import insert_balance_snapshot

    bal = parse_money_value(balance)
    if bal is None:
        return False
    prov = normalize_sync_provider(provider)
    acc = normalize_account_id(account_id)
    return bool(
        insert_balance_snapshot(
            {
                "provider": prov,
                "account_id": acc,
                "balance": round(float(bal), 2),
                "captured_at": datetime.now(timezone.utc),
                "source": str(source or "sync")[:64],
                "user_id": str(user_id),
                "note": note,
                "raw_data": raw_data,
            }
        )
    )


def record_sync_run(
    provider: str,
    account_id: str,
    count_parsed: int = 0,
    inserted: int = 0,
    updated: int = 0,
    message: Optional[str] = None,
) -> bool:
    """Best-effort audit record in book_ingest_runs so every sync updates last_sync_at."""
    from src.database import _exec, get_db_connection

    prov = normalize_sync_provider(provider)
    acc = normalize_account_id(account_id)
    now_utc = datetime.now(timezone.utc)
    try:
        with get_db_connection() as conn:
            _exec(
                conn,
                """
                INSERT INTO book_ingest_runs
                    (book, account_id, run_started_at, run_finished_at, status, count_parsed, inserted, updated, message)
                VALUES (%s, %s, %s, %s, 'SUCCESS', %s, %s, %s, %s)
                """,
                (
                    prov,
                    acc,
                    now_utc,
                    now_utc,
                    int(count_parsed or 0),
                    int(inserted or 0),
                    int(updated or 0),
                    message[:300] if message else None,
                ),
            )
            conn.commit()
        return True
    except Exception:
        return False


def extract_transactions_from_raw_text(raw_text: str, provider: str) -> List[Dict[str, Any]]:
    """
    Fallback text parser for DraftKings Financial Center / FanDuel Transaction History
    page dumps sent by Chrome bookmarklets. Extracts Deposit & Withdrawal rows cleanly.
    """
    if not raw_text:
        return []
    lines = [ln.strip() for ln in str(raw_text).splitlines() if ln.strip()]
    if not lines:
        return []

    date_re = re.compile(
        r"(\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{2,4}\b)",
        re.IGNORECASE,
    )
    amt_re = re.compile(r"([+-]?\s*\$\s*[0-9,]+(?:\.\d{2})?)")
    skip_re = re.compile(r"\b(wager|bet placed|payout|winnings|bonus|promo|crown|free bet|profit boost|entry fee|contest)\b", re.IGNORECASE)

    out: List[Dict[str, Any]] = []
    seen = set()
    n = len(lines)
    i = 0
    while i < n:
        ln = lines[i]
        low = ln.lower()
        txn_type = None
        if "withdraw" in low and not skip_re.search(ln):
            txn_type = "Withdrawal"
        elif "deposit" in low and not skip_re.search(ln):
            txn_type = "Deposit"

        if not txn_type:
            i += 1
            continue

        # Inspect current line + next 3 lines for date and dollar amount
        window = " | ".join(lines[i : min(n, i + 4)])
        m_amt = amt_re.search(ln) or amt_re.search(window)
        m_date = date_re.search(ln) or date_re.search(window)
        if m_amt and m_date:
            amt = parse_money_value(m_amt.group(1))
            if amt is not None and abs(amt) >= 1.0:
                dt = normalize_date_str(m_date.group(1))
                key = (txn_type, dt, round(abs(amt), 2))
                if key not in seen:
                    seen.add(key)
                    out.append({
                        "provider": provider,
                        "type": txn_type,
                        "date": dt,
                        "amount": abs(amt) if txn_type == "Deposit" else -abs(amt),
                        "description": f"{provider} {txn_type} (Browser Sync)",
                    })
                i += 2
                continue
        i += 1

    return out


def ingest_browser_payload(payload: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """
    Process payloads sent by Chrome Bookmarklets or local browser capture tools.
    Supports structured `api_bets`, raw DOM/slip `raw_text`, `transactions`, and `balance`.
    """
    provider = normalize_sync_provider(
        payload.get("provider") or payload.get("sportsbook") or "DraftKings"
    )
    account_id = normalize_account_id(payload.get("account_id"), default="Main")
    source = str(payload.get("source") or f"{provider.lower()}_bookmarklet")
    page_kind = str(payload.get("page_kind") or "bets").strip().lower()

    bets_to_ingest: List[Dict[str, Any]] = []
    api_bets = payload.get("api_bets") or payload.get("bets")
    if page_kind != "transactions" and isinstance(api_bets, list):
        for b in api_bets:
            if isinstance(b, dict):
                bets_to_ingest.append(b)

    raw_text = str(payload.get("raw_text") or "").strip()
    if page_kind != "transactions" and raw_text and not bets_to_ingest:
        if provider == "FanDuel":
            try:
                from src.parsers.fanduel import FanDuelParser

                parsed = FanDuelParser().parse(raw_text)
                if parsed:
                    bets_to_ingest.extend(parsed)
            except Exception as exc:
                print(f"[SyncService] FanDuelParser warn: {exc}")
        elif provider == "DraftKings":
            try:
                from src.parsers.draftkings_text import DraftKingsTextParser

                parsed = DraftKingsTextParser().parse(raw_text)
                if not parsed:
                    from src.parsers.draftkings import DraftKingsParser

                    parsed = DraftKingsParser().parse_text_dump(raw_text)
                if parsed:
                    bets_to_ingest.extend(parsed)
            except Exception as exc:
                print(f"[SyncService] DraftKingsParser warn: {exc}")

    bet_result = ingest_normalized_bets(
        bets_to_ingest,
        user_id=user_id,
        default_provider=provider,
        default_account_id=account_id,
        source=source,
    )

    txns = list(payload.get("transactions") or []) if isinstance(payload.get("transactions"), list) else []
    if not txns and raw_text:
        txns = extract_transactions_from_raw_text(raw_text, provider)
    txn_saved = 0
    if txns:
        txn_saved = ingest_statement_transactions(
            txns,
            user_id=user_id,
            default_provider=provider,
            default_account_id=account_id,
        )

    balance_recorded = False
    allow_balance_write = (page_kind != "transactions") or bool(payload.get("cash_only_balance"))
    if provider == "DraftKings" and "bookmarklet" in source and not payload.get("cash_only_balance"):
        # DraftKings combined header wallet includes Crown Cash / DK Dollars / Rewards;
        # never overwrite pure Cash balance unless explicitly flagged cash_only_balance
        # (e.g. from the pure-Cash Balance column on Transaction History).
        allow_balance_write = False
    if allow_balance_write and payload.get("balance") is not None:
        balance_recorded = record_balance_snapshot(
            provider=provider,
            account_id=account_id,
            balance=payload.get("balance"),
            user_id=user_id,
            source=source,
            note=f"Captured during {source}",
        )

    record_sync_run(
        provider=provider,
        account_id=account_id,
        count_parsed=len(bets_to_ingest),
        inserted=bet_result["inserted"],
        updated=bet_result["updated"],
        message=source,
    )

    return {
        "status": "ok",
        "provider": provider,
        "account_id": account_id,
        "bets_parsed": len(bets_to_ingest),
        "bets_saved": bet_result["saved"],
        "bets_inserted": bet_result["inserted"],
        "bets_updated": bet_result["updated"],
        "bets_skipped": bet_result["skipped"],
        "transactions_saved": txn_saved,
        "balance_snapshot_saved": balance_recorded,
        "errors": bet_result["errors"],
    }


def _tokenize_team_words(text: str) -> set[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", str(text or "").lower())
    stop = {
        "st", "state", "univ", "university", "college", "the", "of", "at", "vs",
        "over", "under", "ml", "moneyline", "spread", "total", "pts", "points",
        "half", "1h", "2h", "live", "parlay", "sgp", "win", "to", "by", "or",
    }
    return {tok for tok in cleaned.split() if len(tok) >= 3 and tok not in stop and not tok.isdigit()}


def _canonical_market_family(bet_type: Any, selection: str) -> str:
    bt = str(bet_type or "").lower()
    sel = str(selection or "").lower()
    if "total" in bt or "over" in bt or "under" in bt or re.search(r"\b(over|under)\b", sel):
        return "TOTAL"
    if "moneyline" in bt or bt == "ml" or re.search(r"\b(ml|moneyline)\b", sel):
        return "ML"
    if "spread" in bt or re.search(r"[+-]\d+(?:\.\d+)?\b", sel):
        return "SPREAD"
    return "OTHER"


def _bet_aligns_with_model(
    bet_market: str,
    bet_selection: str,
    bet_desc: str,
    model_market: str,
    model_pick: str,
    model_selection: str,
    home_team: str,
    away_team: str,
) -> Optional[bool]:
    """Return True if bet aligns with model pick, False if faded/opposite side, None if unclear."""
    bm = bet_market.upper()
    mm = str(model_market or "").upper()
    if mm == "SPREAD" and bm == "ML":
        # Treat ML bet on the same team as aligned side unless contradicted
        pass
    elif bm != "OTHER" and mm and bm != mm:
        return None

    sel_low = f"{bet_selection} {bet_desc}".lower()
    pick_up = str(model_pick or "").upper()
    m_sel_low = str(model_selection or "").lower()

    if mm == "TOTAL" or bm == "TOTAL":
        has_over = bool(re.search(r"\bover\b|\bo\s*\d", sel_low))
        has_under = bool(re.search(r"\bunder\b|\bu\s*\d", sel_low))
        m_over = pick_up == "OVER" or "over" in m_sel_low
        m_under = pick_up == "UNDER" or "under" in m_sel_low
        if has_over and m_over:
            return True
        if has_under and m_under:
            return True
        if (has_over and m_under) or (has_under and m_over):
            return False
        return None

    bet_tokens = _tokenize_team_words(bet_selection)
    home_tokens = _tokenize_team_words(home_team)
    away_tokens = _tokenize_team_words(away_team)
    pick_tokens = _tokenize_team_words(model_selection)
    if pick_up == "HOME" and home_tokens:
        pick_tokens |= home_tokens
    elif pick_up == "AWAY" and away_tokens:
        pick_tokens |= away_tokens

    matches_pick = bool(bet_tokens & pick_tokens)
    other_tokens = away_tokens if (pick_tokens & home_tokens) else home_tokens
    matches_other = bool(bet_tokens & other_tokens)
    if matches_pick and not matches_other:
        return True
    if matches_other and not matches_pick:
        return False
    return None


def compute_actuals_model_reconciliation(
    bets: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
    limit: int = 35,
) -> Dict[str, Any]:
    """
    Reconcile actual placed sportsbook bets against model_predictions rows.
    Pure Python so both live DB API and unit tests execute the exact same math.
    """
    settled_or_pending_bets = [
        b for b in (bets or [])
        if str(b.get("category") or "Bet").lower() != "transaction"
    ]

    # Index predictions by (away/home token signatures + date) for fast matching
    pred_index: List[Tuple[str, set[str], set[str], Dict[str, Any]]] = []
    for p in predictions or []:
        ev_date = str(p.get("date_et") or p.get("start_time") or "")[:10]
        home = str(p.get("home_team") or "")
        away = str(p.get("away_team") or "")
        h_toks = _tokenize_team_words(home)
        a_toks = _tokenize_team_words(away)
        if ev_date and (h_toks or a_toks):
            pred_index.append((ev_date, h_toks, a_toks, p))

    aligned_rows: List[Dict[str, Any]] = []
    faded_rows: List[Dict[str, Any]] = []
    matched_items: List[Dict[str, Any]] = []

    for b in settled_or_pending_bets:
        b_date = str(b.get("date_et") or b.get("date") or "")[:10]
        b_sport = str(b.get("sport") or "").upper()
        b_sel = str(b.get("selection") or "")
        b_desc = str(b.get("description") or "")
        b_ev_txt = str(b.get("event_text") or "")
        b_tokens = _tokenize_team_words(f"{b_ev_txt} {b_desc} {b_sel}")
        b_mkt = _canonical_market_family(b.get("bet_type"), b_sel)

        if not b_date or not b_tokens or b_mkt == "OTHER" or "parlay" in str(b.get("bet_type") or "").lower():
            continue

        # Date window +/- 1 day handles UTC midnight rollover vs sportsbook ET dates
        try:
            b_dt = datetime.strptime(b_date, "%Y-%m-%d").date()
        except Exception:
            continue

        best_pred = None
        best_score = 0
        for p_date, h_toks, a_toks, p in pred_index:
            p_sport = str(p.get("sport") or p.get("league") or "").upper()
            if b_sport and p_sport and b_sport not in (p_sport, "OTHER", "UNKNOWN") and p_sport != b_sport:
                continue
            try:
                p_dt = datetime.strptime(p_date, "%Y-%m-%d").date()
                if abs((p_dt - b_dt).days) > 1:
                    continue
            except Exception:
                continue

            overlap_h = len(b_tokens & h_toks)
            overlap_a = len(b_tokens & a_toks)
            if (overlap_h > 0 and overlap_a > 0) or (overlap_h + overlap_a >= 2) or (
                (overlap_h > 0 or overlap_a > 0) and b_mkt == str(p.get("market_type") or "").upper()
            ):
                score = overlap_h * 2 + overlap_a * 2 + (3 if b_mkt == str(p.get("market_type") or "").upper() else 0)
                if score > best_score:
                    best_score = score
                    best_pred = p

        if best_pred is None:
            continue

        aligned = _bet_aligns_with_model(
            bet_market=b_mkt,
            bet_selection=b_sel,
            bet_desc=b_desc,
            model_market=str(best_pred.get("market_type") or ""),
            model_pick=str(best_pred.get("pick") or ""),
            model_selection=str(best_pred.get("selection") or ""),
            home_team=str(best_pred.get("home_team") or ""),
            away_team=str(best_pred.get("away_team") or ""),
        )
        if aligned is None:
            continue

        bet_odds = parse_american_odds(b.get("odds"))
        model_odds = parse_american_odds(best_pred.get("bet_price") or best_pred.get("price"))
        slippage_prob_pct = None
        if bet_odds and model_odds and aligned:
            p_bet = american_to_implied_prob(bet_odds)
            p_mod = american_to_implied_prob(model_odds)
            if p_bet is not None and p_mod is not None:
                # Positive = user got BETTER price (lower implied prob) than model quote!
                slippage_prob_pct = round((p_mod - p_bet) * 100.0, 2)

        model_outcome = str(best_pred.get("outcome") or "").upper()
        model_unit_pl = None
        if model_outcome == "WON" and model_odds:
            dec = american_to_decimal(model_odds)
            model_unit_pl = round((dec - 1.0), 3) if dec else 0.909
        elif model_outcome == "LOST":
            model_unit_pl = -1.0
        elif model_outcome == "PUSH":
            model_unit_pl = 0.0

        row = {
            "bet_id": b.get("id"),
            "date": b_date,
            "provider": b.get("provider"),
            "sport": b.get("sport"),
            "matchup": f"{best_pred.get('away_team', '')} @ {best_pred.get('home_team', '')}".strip(" @"),
            "bet_selection": b_sel,
            "bet_odds": bet_odds,
            "wager": round(float(b.get("wager") or 0.0), 2),
            "profit": round(float(b.get("profit") or 0.0), 2),
            "status": str(b.get("status") or "PENDING").upper(),
            "model_market": best_pred.get("market_type"),
            "model_selection": best_pred.get("selection"),
            "model_odds": model_odds,
            "model_ev_pct": round(float(best_pred.get("ev_per_unit") or 0.0) * 100.0, 1),
            "model_outcome": model_outcome or "PENDING",
            "model_unit_pl": model_unit_pl,
            "aligned": aligned,
            "price_edge_vs_model_pct": slippage_prob_pct,
        }
        matched_items.append(row)
        if aligned:
            aligned_rows.append(row)
        else:
            faded_rows.append(row)

    total_bets = len(settled_or_pending_bets)
    matched_count = len(matched_items)
    aligned_settled = [r for r in aligned_rows if r["status"] in ("WON", "LOST", "PUSH")]
    actual_wager = sum(r["wager"] for r in aligned_settled)
    actual_profit = sum(r["profit"] for r in aligned_settled)
    actual_wins = sum(1 for r in aligned_settled if r["status"] == "WON")
    actual_losses = sum(1 for r in aligned_settled if r["status"] == "LOST")
    actual_roi = round((actual_profit / actual_wager) * 100.0, 1) if actual_wager > 0 else None

    model_graded = [r for r in aligned_rows if r["model_unit_pl"] is not None]
    model_unit_sum = sum(float(r["model_unit_pl"] or 0.0) for r in model_graded)
    model_roi = round((model_unit_sum / len(model_graded)) * 100.0, 1) if model_graded else None

    price_deltas = [r["price_edge_vs_model_pct"] for r in aligned_rows if r["price_edge_vs_model_pct"] is not None]
    avg_price_edge = round(sum(price_deltas) / len(price_deltas), 2) if price_deltas else None

    return {
        "summary": {
            "total_actual_bets": total_bets,
            "matched_to_model": matched_count,
            "aligned_count": len(aligned_rows),
            "faded_count": len(faded_rows),
            "follow_rate_pct": round((len(aligned_rows) / matched_count) * 100.0, 1) if matched_count else None,
            "aligned_record": f"{actual_wins}-{actual_losses}",
            "aligned_wager": round(actual_wager, 2),
            "aligned_profit": round(actual_profit, 2),
            "actual_roi_pct": actual_roi,
            "model_roi_on_same_picks_pct": model_roi,
            "execution_gap_roi_pct": round(actual_roi - model_roi, 1) if (actual_roi is not None and model_roi is not None) else None,
            "avg_price_edge_vs_model_pct": avg_price_edge,
        },
        "matches": sorted(matched_items, key=lambda x: x["date"], reverse=True)[:limit],
    }
