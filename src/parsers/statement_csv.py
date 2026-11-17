from __future__ import annotations

import csv
import io
import re
from typing import Any, Dict, List, Optional, Tuple

from src.services.bet_sync_service import (
    normalize_bet_status,
    normalize_date_str,
    normalize_sync_provider,
    parse_american_odds,
    parse_money_value,
    stable_external_id,
)


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(h or "").strip().lower()).strip("_")


def _first_val(row: Dict[str, str], keys: List[str]) -> Optional[str]:
    for k in keys:
        if k in row and str(row[k] or "").strip() != "":
            return str(row[k]).strip()
    return None


def detect_statement_provider(headers: List[str], sample_rows: List[Dict[str, str]], requested: str = "Auto") -> str:
    req = str(requested or "").strip()
    if req and req.lower() not in ("auto", "auto-detect", "unknown"):
        return normalize_sync_provider(req)
    joined_hdr = " ".join(headers).lower()
    sample_text = " ".join(
        " ".join(str(v or "") for v in r.values()) for r in sample_rows[:15]
    ).lower()
    if "fanduel" in joined_hdr or "fanduel" in sample_text or "o/" in sample_text or "fd " in sample_text:
        return "FanDuel"
    if "draftkings" in joined_hdr or "draftkings" in sample_text or "crowns" in joined_hdr or "dk_" in sample_text or "dk " in sample_text:
        return "DraftKings"
    return "DraftKings"


def parse_sportsbook_statement_csv(
    csv_text: str,
    sportsbook: str = "Auto",
    account_id: str = "Main",
) -> Dict[str, Any]:
    """
    Parse exported DraftKings or FanDuel Bet History or Account Statement CSV text
    into canonical `bets`, `transactions` (Deposit/Withdrawal/Bonus), and optional `closing_balance`.
    """
    cleaned = str(csv_text or "").lstrip("\ufeff").strip()
    if not cleaned:
        raise ValueError("CSV file is empty.")

    # Auto-detect delimiter (comma or tab)
    first_line = cleaned.splitlines()[0]
    delimiter = "\t" if first_line.count("\t") > first_line.count(",") else ","

    reader = csv.DictReader(io.StringIO(cleaned), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("CSV is missing a header row.")

    norm_fields = [_norm_header(f) for f in reader.fieldnames]
    raw_rows: List[Dict[str, str]] = []
    for r in reader:
        mapped = {_norm_header(k): str(v or "").strip() for k, v in r.items() if k is not None}
        if any(mapped.values()):
            raw_rows.append(mapped)

    if not raw_rows:
        raise ValueError("No data rows found in CSV.")

    provider = detect_statement_provider(norm_fields, raw_rows, requested=sportsbook)

    # Identify CSV shape:
    # A) Bet-level CSV (has Stake/Wager/Risk + Selection/Event/Matchup/Description or Status/Odds)
    # B) Financial Ledger CSV (has Type + Amount, possibly Balance)
    hdr_set = set(norm_fields)
    has_bet_cols = bool(
        hdr_set
        & {
            "wager",
            "stake",
            "risk",
            "bet_amount",
            "selection",
            "pick",
            "odds",
            "american_odds",
            "price",
            "payout",
            "winnings",
            "result",
            "bet_type",
            "market",
        }
    )
    has_ledger_cols = bool(hdr_set & {"type", "transaction_type", "txn_type", "category"}) and bool(
        hdr_set & {"amount", "net_amount", "credit", "debit"}
    )

    bets: List[Dict[str, Any]] = []
    txns: List[Dict[str, Any]] = []
    latest_balance: Optional[float] = None
    latest_balance_date: Optional[str] = None

    # Track ledger bet debits/credits by reference id so DK/FD financial CSVs reconstruct settled bets when possible
    ledger_bet_groups: Dict[str, Dict[str, Any]] = {}

    for idx, row in enumerate(raw_rows):
        row_date = normalize_date_str(
            _first_val(
                row,
                [
                    "date",
                    "placed_date",
                    "date_placed",
                    "placed_at",
                    "transaction_date",
                    "settled_date",
                    "timestamp",
                    "time",
                    "created_at",
                ],
            )
        )
        row_bal = parse_money_value(
            _first_val(row, ["balance", "ending_balance", "wallet_balance", "cash_balance", "available_balance"])
        )
        if row_bal is not None:
            # Take top-most row if descending or most recent by date
            if latest_balance is None or (latest_balance_date and row_date >= latest_balance_date):
                latest_balance = row_bal
                latest_balance_date = row_date

        # Check explicit transaction rows first when Type column exists
        row_type_raw = _first_val(row, ["type", "transaction_type", "txn_type", "category", "action"]) or ""
        row_type_low = row_type_raw.lower()
        row_desc = _first_val(row, ["description", "details", "memo", "event", "matchup", "game", "title"]) or ""
        row_id = _first_val(row, ["bet_id", "ticket_id", "transaction_id", "txn_id", "id", "reference", "ref_id"])

        is_cash_txn = any(
            kw in row_type_low
            for kw in ("deposit", "withdrawal", "withdraw", "cashout to bank", "transfer in", "transfer out", "ach", "paypal", "venmo")
        )
        is_bonus_txn = any(kw in row_type_low for kw in ("bonus", "promo credit", "adjustment", "fee", "rebate"))

        if has_ledger_cols and is_cash_txn:
            amt = parse_money_value(_first_val(row, ["amount", "net_amount", "value"]))
            if amt is None:
                credit = parse_money_value(row.get("credit")) or 0.0
                debit = parse_money_value(row.get("debit")) or 0.0
                amt = credit - abs(debit) if (credit or debit) else None
            if amt is not None and amt != 0:
                txn_kind = "Withdrawal" if ("withdraw" in row_type_low or amt < 0 and "deposit" not in row_type_low) else "Deposit"
                txns.append(
                    {
                        "provider": provider,
                        "account_id": account_id,
                        "txn_id": row_id or stable_external_id(provider, [row_date, txn_kind, amt, row_desc, idx], prefix="csvtxn"),
                        "date": row_date,
                        "type": txn_kind,
                        "description": row_desc or f"{provider} {txn_kind}",
                        "amount": abs(amt) if txn_kind == "Deposit" else -abs(amt),
                        "balance": row_bal,
                    }
                )
            continue

        if has_ledger_cols and is_bonus_txn and not has_bet_cols:
            amt = parse_money_value(_first_val(row, ["amount", "net_amount", "value"]))
            if amt is not None and amt != 0:
                txns.append(
                    {
                        "provider": provider,
                        "account_id": account_id,
                        "txn_id": row_id or stable_external_id(provider, [row_date, "Bonus", amt, row_desc, idx], prefix="csvtxn"),
                        "date": row_date,
                        "type": "Bonus",
                        "description": row_desc or row_type_raw,
                        "amount": amt,
                        "balance": row_bal,
                    }
                )
            continue

        # Bet row (either direct Bet History CSV or Financial Ledger wager/winnings row)
        selection = _first_val(row, ["selection", "pick", "outcome", "wager_selection", "side", "bet_details"]) or ""
        event_name = _first_val(row, ["event", "matchup", "game", "event_name", "fixture"]) or ""
        sport = _first_val(row, ["sport", "league", "competition"]) or ""
        bet_type = _first_val(row, ["bet_type", "market", "market_type", "wager_type"]) or ""
        odds_raw = _first_val(row, ["odds", "american_odds", "price", "decimal_odds"])
        odds = parse_american_odds(odds_raw)
        wager = parse_money_value(_first_val(row, ["wager", "stake", "risk", "bet_amount", "wager_amount"]))
        payout = parse_money_value(_first_val(row, ["payout", "return", "total_payout", "winnings", "settled_amount", "cashout_amount"]))
        profit = parse_money_value(_first_val(row, ["profit", "net_profit", "profit_loss", "net"]))
        status_raw = _first_val(row, ["status", "result", "state", "bet_status"]) or ""

        if has_bet_cols and (wager is not None or selection or status_raw):
            st = normalize_bet_status(status_raw or ("WON" if (payout or 0) > 0 else "PENDING"), profit=profit, wager=wager, payout=payout)
            desc_final = event_name or row_desc or selection
            sel_final = selection or desc_final
            bets.append(
                {
                    "provider": provider,
                    "account_id": account_id,
                    "external_id": row_id or stable_external_id(provider, [row_date, desc_final, sel_final, wager or 0, odds], prefix="csvbet"),
                    "date": row_date,
                    "sport": sport,
                    "bet_type": bet_type,
                    "wager": abs(float(wager or 0.0)),
                    "payout": payout,
                    "profit": profit,
                    "status": st,
                    "description": desc_final,
                    "selection": sel_final,
                    "event_name": event_name or None,
                    "odds": odds,
                    "is_live": "live" in f"{bet_type} {row_desc} {selection}".lower(),
                    "is_bonus": "bonus" in f"{bet_type} {row_type_raw} {row_desc}".lower(),
                    "raw_text": f"CSV | {provider} | {row_date} | {desc_final} | {sel_final} | odds={odds} | wager={wager} | payout={payout}",
                    "source": f"{provider.lower()}_csv",
                }
            )
            continue

        # Fallback: ledger-only Sportsbook Wager / Winnings row without explicit Stake/Selection columns
        if has_ledger_cols and any(kw in row_type_low for kw in ("wager", "bet", "win", "payout", "cashout", "refund", "void")):
            amt = parse_money_value(_first_val(row, ["amount", "net_amount", "value"]))
            if amt is None:
                continue
            ref_match = re.search(r"(O/\d+/\d+|DK-\w+|\b\d{7,}\b)", f"{row_id or ''} {row_desc}")
            ref_key = ref_match.group(1) if ref_match else stable_external_id(provider, [row_date, row_desc], prefix="led")
            grp = ledger_bet_groups.setdefault(
                ref_key,
                {
                    "provider": provider,
                    "account_id": account_id,
                    "external_id": row_id or ref_key,
                    "date": row_date,
                    "sport": sport,
                    "description": row_desc or row_type_raw,
                    "selection": selection or row_desc or row_type_raw,
                    "wager": 0.0,
                    "payout": 0.0,
                    "refunded": False,
                    "won_row": False,
                    "odds": odds,
                },
            )
            if "refund" in row_type_low or "void" in row_type_low:
                grp["refunded"] = True
                grp["payout"] += abs(amt)
            elif "win" in row_type_low or "payout" in row_type_low or "cashout" in row_type_low or amt > 0:
                grp["won_row"] = True
                grp["payout"] += abs(amt)
            else:
                grp["wager"] += abs(amt)

    for grp in ledger_bet_groups.values():
        w = float(grp["wager"] or 0.0)
        p_out = float(grp["payout"] or 0.0)
        if w <= 0 and p_out <= 0:
            continue
        if grp["refunded"]:
            st = "VOID"
            prof = 0.0
        elif grp["won_row"] and p_out > 0:
            if w > 0 and p_out < w:
                st = "LOST"
                prof = round(p_out - w, 2)
            elif w > 0 and abs(p_out - w) < 0.01:
                st = "PUSH"
                prof = 0.0
            else:
                st = "WON"
                prof = round(p_out - w, 2) if w > 0 else round(p_out, 2)
        else:
            st = "LOST"
            prof = round(-w, 2)
        bets.append(
            {
                "provider": provider,
                "account_id": account_id,
                "external_id": grp["external_id"],
                "date": grp["date"],
                "sport": grp["sport"],
                "bet_type": "Straight",
                "wager": round(w if w > 0 else p_out, 2),
                "payout": round(p_out, 2),
                "profit": prof,
                "status": st,
                "description": grp["description"],
                "selection": grp["selection"],
                "odds": grp["odds"],
                "raw_text": f"CSV Ledger | {provider} | {grp['date']} | {grp['description']} | wager={w} | payout={p_out}",
                "source": f"{provider.lower()}_csv",
            }
        )

    return {
        "provider": provider,
        "account_id": account_id,
        "bets": bets,
        "transactions": txns,
        "closing_balance": latest_balance,
        "rows_scanned": len(raw_rows),
    }
