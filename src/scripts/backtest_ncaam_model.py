import sys
import os
import json
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Allow running from repo root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.database import get_db_connection, _exec
from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
from src.utils.model_performance import compute_top6_quality_score, rank_top6_items


def _et_date(d: datetime) -> str:
    try:
        dt = d
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("America/New_York")).strftime('%Y-%m-%d')
    except Exception:
        return d.strftime('%Y-%m-%d')


_HAS_ODDS_CREATED_AT = None


def _odds_has_created_at(conn) -> bool:
    global _HAS_ODDS_CREATED_AT
    if _HAS_ODDS_CREATED_AT is None:
        row = _exec(conn, """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'odds_snapshots' AND column_name = 'created_at'
            LIMIT 1
        """).fetchone()
        _HAS_ODDS_CREATED_AT = bool(row)
    return _HAS_ODDS_CREATED_AT


def _best_book_line_before(conn, event_id: str, market_type: str, side: str, cutoff: datetime):
    """Fetch the best bettable retail line & price across all live books before tipoff."""
    created_filter = "AND created_at <= %s" if _odds_has_created_at(conn) else ""
    line_filter = "" if market_type == "MONEYLINE" else "AND line_value IS NOT NULL"
    params = (event_id, market_type, side, cutoff, cutoff, cutoff) if created_filter else (event_id, market_type, side, cutoff, cutoff)
    rows = _exec(conn, f"""
        SELECT DISTINCT ON (book) book, line_value, price, captured_at
        FROM odds_snapshots
        WHERE event_id=%s AND market_type=%s AND side=%s
          AND lower(COALESCE(book, '')) NOT IN ('action_open', 'open', '', 'consensus')
          AND lower(book) !~ '^action_book_' AND price IS NOT NULL
          {line_filter}
          AND captured_at BETWEEN %s - interval '90 minutes' AND %s
          {created_filter}
        ORDER BY book, captured_at DESC
    """, params).fetchall()
    if not rows:
        return None
    cands = [dict(r) for r in rows]
    if market_type == 'SPREAD':
        best = max(cands, key=lambda x: (float(x['line_value']), float(x.get('price') or -110)))
    elif market_type == 'TOTAL' and side == 'OVER':
        best = min(cands, key=lambda x: (float(x['line_value']), -float(x.get('price') or -110)))
    elif market_type == 'TOTAL' and side == 'UNDER':
        best = max(cands, key=lambda x: (float(x['line_value']), float(x.get('price') or -110)))
    else:
        best = max(cands, key=lambda x: float(x.get('price') or -110))
    return best


def _latest_line_before(conn, event_id: str, market_type: str, side: str, cutoff: datetime):
    # Only observations already ingested by the historical cutoff are available.
    created_filter = "AND created_at <= %s" if _odds_has_created_at(conn) else ""
    params = (event_id, market_type, side, cutoff, cutoff, cutoff) if created_filter else (event_id, market_type, side, cutoff, cutoff)
    row = _exec(conn, f"""
        SELECT line_value, price, captured_at
        FROM odds_snapshots
        WHERE event_id=%s AND market_type=%s AND side=%s
          AND COALESCE(book, '') NOT IN ('action_open', 'open')
          AND captured_at BETWEEN %s - interval '90 minutes' AND %s
          {created_filter}
        ORDER BY captured_at DESC, (CASE WHEN book = 'consensus' THEN 0 ELSE 1 END) ASC
        LIMIT 1
    """, params).fetchone()
    return dict(row) if row else None


def _american_profit_per_unit(price: float) -> float:
    """Profit (not including stake) for risking 1 unit at given American odds."""
    if price is None:
        price = -110
    p = float(price)
    if p == 0:
        return 0.0
    if p > 0:
        return p / 100.0
    return 100.0 / abs(p)


def _grade_spread(pick: str, home_team: str, away_team: str, line: float, home_score: float, away_score: float) -> str:
    # pick is team name
    if pick == home_team:
        adj = (home_score + line) - away_score
    elif pick == away_team:
        adj = (away_score + line) - home_score
    else:
        return 'VOID'
    if abs(adj) < 1e-9:
        return 'PUSH'
    return 'WIN' if adj > 0 else 'LOSS'


def _grade_total(side: str, line: float, home_score: float, away_score: float) -> str:
    tot = home_score + away_score
    s = str(side or '').upper().strip()
    if abs(tot - line) < 1e-9:
        return 'PUSH'
    if s == 'OVER':
        return 'WIN' if tot > line else 'LOSS'
    if s == 'UNDER':
        return 'WIN' if tot < line else 'LOSS'
    return 'VOID'


def _leg_has_contra_risk(tags) -> bool:
    for t in tags or []:
        low = str(t or "").strip().lower()
        if low in ("contra_sharp_money", "contra_sharp_line") or low.startswith("reverse_steam="):
            return True
    return False


def _dec_from_american(price: float) -> float:
    p = float(price)
    if abs(p) < 100.0:
        return 1.0
    if p > 0:
        return 1.0 + (p / 100.0)
    return 1.0 + (100.0 / abs(p))


def _american_from_dec(dec: float) -> int:
    if dec <= 1.0:
        return 0
    x = dec - 1.0
    if x >= 1.0:
        return int(round(x * 100))
    return int(round(-100 / x))


def _summarize_bet_slice(items: list[dict], count_key: str = "n_bets", roi_key: str = "roi_units_per_bet") -> dict:
    n = len(items)
    wins = sum(1 for b in items if b.get("outcome") == "WIN")
    losses = sum(1 for b in items if b.get("outcome") == "LOSS")
    pushes = sum(1 for b in items if b.get("outcome") == "PUSH")
    total_pnl = round(sum(float(b.get("pnl_units") or 0.0) for b in items), 4) if n else 0.0
    roi = round(total_pnl / n, 4) if n else None
    win_rate = round(wins / (wins + losses), 4) if (wins + losses) else None
    return {
        count_key: n,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": win_rate,
        "total_pnl_units": total_pnl,
        roi_key: roi,
    }


def _simulate_parlays(parlay_legs: list[dict]) -> dict:
    by_day: dict[str, list[dict]] = {}
    for leg in parlay_legs or []:
        day_k = str(leg.get("day_et") or "")
        if day_k:
            by_day.setdefault(day_k, []).append(leg)

    high_conf_all: list[dict] = []
    plus_money_all: list[dict] = []
    combined_all: list[dict] = []

    for day_k in sorted(by_day.keys()):
        legs = by_day[day_k]
        if len(legs) < 2:
            continue
        combos: list[dict] = []
        for i in range(len(legs)):
            for j in range(i + 1, len(legs)):
                a = legs[i]
                b = legs[j]
                if not a.get("event_id") or a.get("event_id") == b.get("event_id"):
                    continue
                oa = str(a.get("outcome") or "").upper()
                ob = str(b.get("outcome") or "").upper()
                if oa not in ("WIN", "LOSS", "PUSH") or ob not in ("WIN", "LOSS", "PUSH"):
                    continue
                try:
                    wa = float(a.get("win_prob"))
                    wb = float(b.get("win_prob"))
                    pa = float(a.get("price"))
                    pb = float(b.get("price"))
                except Exception:
                    continue
                if not (0.0 < wa < 1.0 and 0.0 < wb < 1.0 and abs(pa) >= 100.0 and abs(pb) >= 100.0):
                    continue
                p_win = wa * wb
                dec_a = _dec_from_american(pa)
                dec_b = _dec_from_american(pb)
                dec = dec_a * dec_b
                amer = _american_from_dec(dec)
                ev = p_win * (dec - 1.0) - (1.0 - p_win)
                if ev < 0.02 or not (-120 <= amer <= 800):
                    continue

                if oa == "LOSS" or ob == "LOSS":
                    p_out, p_pnl = "LOSS", -1.0
                elif oa == "WIN" and ob == "WIN":
                    p_out, p_pnl = "WIN", dec - 1.0
                elif oa == "PUSH" and ob == "PUSH":
                    p_out, p_pnl = "PUSH", 0.0
                elif oa == "WIN" and ob == "PUSH":
                    p_out, p_pnl = "WIN", dec_a - 1.0
                else:
                    p_out, p_pnl = "WIN", dec_b - 1.0

                combos.append({
                    "day_et": day_k,
                    "event_ids": (a["event_id"], b["event_id"]),
                    "legs": [
                        {"pick": a.get("pick"), "market_type": a.get("market_type"), "price": a.get("price"), "outcome": oa, "risk_tier": a.get("risk_tier")},
                        {"pick": b.get("pick"), "market_type": b.get("market_type"), "price": b.get("price"), "outcome": ob, "risk_tier": b.get("risk_tier")},
                    ],
                    "p_win": round(p_win, 4),
                    "american_odds": amer,
                    "ev": round(ev, 4),
                    "outcome": p_out,
                    "pnl_units": round(p_pnl, 4),
                })

        used_eids: set[str] = set()
        hc_day: list[dict] = []
        for c in sorted(combos, key=lambda x: (x["p_win"], x["ev"]), reverse=True):
            e1, e2 = c["event_ids"]
            if e1 in used_eids or e2 in used_eids:
                continue
            hc_day.append(c)
            used_eids.add(e1)
            used_eids.add(e2)
            if len(hc_day) >= 2:
                break

        pm_day: list[dict] = []
        for c in sorted([x for x in combos if x["american_odds"] >= 100], key=lambda x: (x["ev"], x["p_win"]), reverse=True):
            e1, e2 = c["event_ids"]
            if e1 in used_eids or e2 in used_eids:
                continue
            pm_day.append(c)
            used_eids.add(e1)
            used_eids.add(e2)
            if len(pm_day) >= 2:
                break

        high_conf_all.extend(hc_day)
        plus_money_all.extend(pm_day)
        combined_all.extend(hc_day + pm_day)

    summary = _summarize_bet_slice(combined_all, count_key="n_parlays", roi_key="roi_units_per_parlay")
    summary["legs_considered"] = len(parlay_legs or [])
    summary["high_confidence"] = _summarize_bet_slice(high_conf_all, count_key="n_parlays", roi_key="roi_units_per_parlay")
    summary["plus_money_parlays"] = _summarize_bet_slice(plus_money_all, count_key="n_parlays", roi_key="roi_units_per_parlay")
    return summary


def summarize_simulate_backtest(bets: list[dict], parlay_legs: list[dict]) -> dict:
    """Compute overall, risk-tier, Top-6-curated, and 2-leg parlay simulation metrics."""
    sim = _summarize_bet_slice(bets)
    sim["bets_by_market"] = {
        "SPREAD": sum(1 for b in bets if b.get("market_type") == "SPREAD"),
        "TOTAL": sum(1 for b in bets if b.get("market_type") == "TOTAL"),
    }

    core_bets = [b for b in bets if not b.get("is_smart_risk")]
    smart_risk_bets = [b for b in bets if b.get("is_smart_risk")]
    sim["by_risk_tier"] = {
        "CORE": _summarize_bet_slice(core_bets),
        "SMART_RISK": _summarize_bet_slice(smart_risk_bets),
    }
    sim["sized_pnl_units"] = round(
        sum(
            float(b.get("pnl_units") or 0.0) * (0.5 if b.get("is_smart_risk") else 1.0)
            for b in bets
        ),
        4,
    ) if bets else 0.0

    by_day: dict[str, list[dict]] = {}
    for b in bets:
        day_k = str(b.get("day_et") or "").strip()
        if not day_k:
            try:
                day_k = _et_date(datetime.fromisoformat(str(b.get("start_time") or "").replace("Z", "+00:00")))
            except Exception:
                day_k = "unknown"
        by_day.setdefault(day_k, []).append(b)
    top6_bets: list[dict] = []
    for day_k in sorted(by_day.keys()):
        top6_bets.extend(rank_top6_items(by_day[day_k], limit=6))
    sim["top6_curated"] = _summarize_bet_slice(top6_bets)
    sim["parlays"] = _simulate_parlays(parlay_legs)
    return sim


DEFAULT_WALKFORWARD_WEIGHT_GRID = [
    (w_b, w_k, w_h)
    for w_b in (0.15, 0.20, 0.25, 0.30, 0.35)
    for w_k in (0.15, 0.20, 0.25)
    for w_h in (0.04, 0.08, 0.12)
    if (w_b + w_k + w_h) <= 0.62
]


def _score_spread_candidate(
    records: list[dict],
    weights: tuple[float, float, float],
    min_edge: float = 1.5,
) -> dict:
    """Evaluate a (w_base, w_kenpom, w_hasla) weight triple on spread records."""
    w_b, w_k, w_h = weights
    n_bets = 0
    wins = 0
    losses = 0
    pushes = 0
    total_profit = 0.0
    mae_sum = 0.0
    n_mae = 0

    for rec in records:
        close_spread = rec.get("close_spread")
        final_margin = rec.get("final_margin")
        if close_spread is None or final_margin is None:
            continue
        close_spread = float(close_spread)
        final_margin = float(final_margin)
        mu_market = float(rec.get("mu_market_spread", close_spread))

        pred_spread = (
            mu_market
            + (w_b * float(rec.get("diff_torvik", 0.0)))
            + (w_k * float(rec.get("diff_kenpom", 0.0)))
            + (w_h * float(rec.get("diff_hasla", 0.0)))
            + float(rec.get("other_adj", 0.0))
        )
        mae_sum += abs((-pred_spread) - final_margin)
        n_mae += 1

        home_edge = close_spread - pred_spread
        away_edge = pred_spread - close_spread
        if home_edge >= min_edge:
            side = "HOME"
            price = float(rec.get("spread_price_home") or -110)
        elif away_edge >= min_edge:
            side = "AWAY"
            price = float(rec.get("spread_price_away") or -110)
        else:
            continue

        adj = final_margin + close_spread
        if abs(adj) < 1e-9:
            pushes += 1
            n_bets += 1
            continue

        n_bets += 1
        won = (adj > 0) if side == "HOME" else (adj < 0)
        if won:
            wins += 1
            total_profit += _american_profit_per_unit(price)
        else:
            losses += 1
            total_profit -= 1.0

    roi = (total_profit / n_bets) if n_bets > 0 else 0.0
    mae = (mae_sum / n_mae) if n_mae > 0 else 999.0
    return {
        "weights": {"NCAAM_W_BASE": w_b, "NCAAM_W_KENPOM": w_k, "NCAAM_W_HASLA": w_h},
        "n_games": n_mae,
        "n_bets": n_bets,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "profit_units": round(total_profit, 4),
        "roi": round(roi, 4),
        "mae_vs_final": round(mae, 4),
    }


def recommend_weights_walkforward(
    records: list[dict],
    min_bets: int = 75,
    weight_grid: list[tuple[float, float, float]] | None = None,
    min_edge: float = 1.5,
) -> dict:
    """
    Run chronological expanding-window walk-forward evaluation across [W_BASE, W_KENPOM, W_HASLA].
    Returns a non-destructive recommendation JSON summary only when sample >= min_bets.
    """
    baseline = (0.25, 0.20, 0.08)
    grid = list(weight_grid or DEFAULT_WALKFORWARD_WEIGHT_GRID)
    if baseline not in grid:
        grid.insert(0, baseline)

    valid = sorted(
        [r for r in (records or []) if r.get("close_spread") is not None and r.get("final_margin") is not None],
        key=lambda r: str(r.get("start_time") or ""),
    )

    baseline_full = _score_spread_candidate(valid, baseline, min_edge=min_edge)
    if len(valid) < min_bets:
        return {
            "mode": "tune_weights",
            "status": "insufficient_sample",
            "non_destructive": True,
            "min_bets": min_bets,
            "n_games": len(valid),
            "n_bets": baseline_full["n_bets"],
            "baseline": baseline_full,
            "recommended_weights": None,
            "reason": f"Need at least {min_bets} completed games before recommending weight changes (got {len(valid)}).",
        }

    # 3 expanding chronological walk-forward folds starting after first 50% of games
    n = len(valid)
    split_points = [int(n * 0.50), int(n * 0.67), int(n * 0.84), n]
    folds = []
    oos_profits = []
    oos_bets_total = 0
    oos_baseline_profits = []
    oos_baseline_bets = 0

    for idx in range(3):
        train_end = split_points[idx]
        test_end = split_points[idx + 1]
        train_slice = valid[:train_end]
        test_slice = valid[train_end:test_end]
        if not train_slice or not test_slice:
            continue

        best_train = max(
            (_score_spread_candidate(train_slice, w, min_edge=min_edge) for w in grid),
            key=lambda m: (m["n_bets"] >= 10, m["roi"] - 0.05 * m["mae_vs_final"], -m["mae_vs_final"]),
        )
        w_best = (
            best_train["weights"]["NCAAM_W_BASE"],
            best_train["weights"]["NCAAM_W_KENPOM"],
            best_train["weights"]["NCAAM_W_HASLA"],
        )
        oos_best = _score_spread_candidate(test_slice, w_best, min_edge=min_edge)
        oos_base = _score_spread_candidate(test_slice, baseline, min_edge=min_edge)
        oos_profits.append(oos_best["profit_units"])
        oos_bets_total += oos_best["n_bets"]
        oos_baseline_profits.append(oos_base["profit_units"])
        oos_baseline_bets += oos_base["n_bets"]
        folds.append({
            "fold": idx + 1,
            "train_n": len(train_slice),
            "test_n": len(test_slice),
            "train_selected": best_train,
            "oos_selected": oos_best,
            "oos_baseline": oos_base,
        })

    if oos_bets_total < min_bets and baseline_full["n_bets"] < min_bets:
        return {
            "mode": "tune_weights",
            "status": "insufficient_bets",
            "non_destructive": True,
            "min_bets": min_bets,
            "n_games": len(valid),
            "n_bets": max(oos_bets_total, baseline_full["n_bets"]),
            "baseline": baseline_full,
            "folds": folds,
            "recommended_weights": None,
            "reason": f"Qualified spread bets below {min_bets} minimum threshold.",
        }

    # Final candidate ranking across full sample while guarding against overfit using OOS lift
    all_full = sorted(
        (_score_spread_candidate(valid, w, min_edge=min_edge) for w in grid),
        key=lambda m: (m["n_bets"] >= min_bets, m["roi"] - 0.05 * m["mae_vs_final"], -m["mae_vs_final"]),
        reverse=True,
    )
    top_candidate = all_full[0]
    oos_roi = (sum(oos_profits) / oos_bets_total) if oos_bets_total > 0 else 0.0
    oos_base_roi = (sum(oos_baseline_profits) / oos_baseline_bets) if oos_baseline_bets > 0 else 0.0
    improved = (top_candidate["n_bets"] >= min_bets) and (oos_roi > oos_base_roi) and (top_candidate["roi"] > baseline_full["roi"])

    return {
        "mode": "tune_weights",
        "status": "recommendation_ready" if improved else "keep_defaults",
        "non_destructive": True,
        "min_bets": min_bets,
        "n_games": len(valid),
        "n_bets": top_candidate["n_bets"],
        "oos_summary": {
            "oos_bets": oos_bets_total,
            "oos_profit_units": round(sum(oos_profits), 4),
            "oos_roi": round(oos_roi, 4),
            "oos_baseline_roi": round(oos_base_roi, 4),
        },
        "baseline": baseline_full,
        "top_candidate": top_candidate,
        "recommended_weights": top_candidate["weights"] if improved else None,
        "folds": folds,
        "top_5_grid": all_full[:5],
    }


def _collect_tune_records(model: NCAAMMarketFirstModelV2, games: list[dict], now: datetime) -> list[dict]:
    """Build walk-forward spread evaluation records from completed NCAAM games."""
    tune_records = []
    with get_db_connection() as conn:
        for g in games:
            event_id = g["id"]
            st = g["start_time"]
            if isinstance(st, str):
                try:
                    st = datetime.fromisoformat(st.replace("Z", "+00:00"))
                except Exception:
                    st = now
            if st.tzinfo is None:
                st = st.replace(tzinfo=timezone.utc)
            cutoff = st - timedelta(minutes=10)
            s_home = _latest_line_before(conn, event_id, "SPREAD", "HOME", cutoff)
            s_away = _latest_line_before(conn, event_id, "SPREAD", "AWAY", cutoff)
            t_over = _latest_line_before(conn, event_id, "TOTAL", "OVER", cutoff)
            t_under = _latest_line_before(conn, event_id, "TOTAL", "UNDER", cutoff)
            if not s_home or not t_over or s_home.get("line_value") is None or t_over.get("line_value") is None:
                continue

            market_snapshot = {
                "spread_home": float(s_home["line_value"]),
                "spread_price_home": float(s_home.get("price") or -110),
                "total": float(t_over["line_value"]),
                "total_over_price": float(t_over.get("price") or -110),
                "_best_spread_home": {"line_value": float(s_home["line_value"]), "price": float(s_home.get("price") or -110), "book": "bt"},
                "_best_spread_away": {"line_value": float(s_away["line_value"]), "price": float(s_away.get("price") or -110), "book": "bt"} if s_away else None,
                "_best_total_over": {"line_value": float(t_over["line_value"]), "price": float(t_over.get("price") or -110), "book": "bt"},
                "_best_total_under": {"line_value": float(t_under["line_value"]), "price": float(t_under.get("price") or -110), "book": "bt"} if t_under else None,
                "_raw_snaps": [],
            }
            try:
                model.analyze(
                    event_id,
                    market_snapshot=market_snapshot,
                    event_context={
                        "id": event_id,
                        "home_team": g["home_team"],
                        "away_team": g["away_team"],
                        "league": "NCAAM",
                        "sport": "NCAAM",
                        "start_time": st,
                        "neutral_site": bool(g.get("neutral_site", False)),
                        "venue": g.get("venue"),
                        "venue_city": g.get("venue_city"),
                        "venue_state": g.get("venue_state"),
                    },
                    relax_gates=False,
                    persist=False,
                )
            except Exception:
                continue

            comps = getattr(model, "_last_spread_components", None) or {}
            if not comps:
                continue
            home_score = float(g["home_score"])
            away_score = float(g["away_score"])
            tune_records.append({
                "event_id": event_id,
                "start_time": st.isoformat(),
                "close_spread": float(s_home["line_value"]),
                "spread_price_home": float(s_home.get("price") or -110),
                "spread_price_away": float(s_away.get("price") or -110) if s_away else -110.0,
                "final_margin": home_score - away_score,
                "mu_market_spread": comps.get("mu_market_spread", float(s_home["line_value"])),
                "diff_torvik": comps.get("diff_torvik", 0.0),
                "diff_kenpom": comps.get("diff_kenpom", 0.0),
                "diff_hasla": comps.get("diff_hasla", 0.0),
                "other_adj": comps.get("other_adj", 0.0),
            })
    return tune_records


def main():
    days = int(os.getenv('BACKTEST_DAYS', '14'))
    limit = int(os.getenv('BACKTEST_LIMIT', '200'))
    mode = 'tune_weights' if '--tune-weights' in sys.argv else str(os.getenv('BACKTEST_MODE', 'mae')).strip().lower()  # mae|simulate|tune_weights

    if mode == "published_holdout":
        from src.services.ncaam_holdout import published_holdout
        print(json.dumps(published_holdout(days), indent=2))
        return

    # Use fixed weights if provided
    print('[backtest] env overrides:', {
        'NCAAM_W_BASE': os.getenv('NCAAM_W_BASE'),
        'NCAAM_W_KENPOM': os.getenv('NCAAM_W_KENPOM'),
        'NCAAM_CAP_SPREAD': os.getenv('NCAAM_CAP_SPREAD'),
        'NCAAM_CAP_TOTAL': os.getenv('NCAAM_CAP_TOTAL'),
    })

    model = NCAAMMarketFirstModelV2()

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    with get_db_connection() as conn:
        # Pull completed games
        rows = _exec(conn, """
            SELECT e.id, e.home_team, e.away_team, e.start_time,
                   COALESCE(e.neutral_site, FALSE) AS neutral_site,
                   e.venue, e.venue_city, e.venue_state,
                   r.home_score, r.away_score
            FROM events e
            JOIN game_results r ON r.event_id = e.id
            WHERE e.league='NCAAM'
              AND r.final = TRUE
              AND e.start_time >= %s
            ORDER BY e.start_time DESC
            LIMIT %s
        """, (start, limit)).fetchall()

        games = [dict(r) for r in rows]

    if not games:
        print('[backtest] no games found')
        return

    if mode == 'tune_weights':
        tune_records = _collect_tune_records(model, games, now)
        summary = recommend_weights_walkforward(
            tune_records,
            min_bets=int(os.getenv('BACKTEST_MIN_BETS', '75')),
        )
        print(json.dumps(summary, indent=2, default=str))
        out_path = os.getenv('BACKTEST_OUTPUT_PATH', 'backtest_output.json')
        try:
            with open(out_path, 'w') as f:
                json.dump(summary, f, indent=2, default=str)
        except Exception as e:
            print(f'[backtest] failed to write {out_path}: {e}')
        return

    # Metrics (MAE mode)
    n_spread = 0
    n_total = 0
    mae_spread_vs_close = 0.0
    mae_total_vs_close = 0.0
    market_spread_error = 0.0
    market_total_error = 0.0
    mae_spread_vs_final = 0.0
    mae_total_vs_final = 0.0
    dir_stats = {
        'spread_05': [0, 0],
        'spread_10': [0, 0],
        'spread_lt14_05': [0, 0],
        'spread_ge14_05': [0, 0],
        'total_over_05': [0, 0],
        'total_under_05': [0, 0],
    }

    # Metrics (simulate mode)
    bets = []
    parlay_legs = []

    samples = []

    with get_db_connection() as conn:
        for g in games:
            event_id = g['id']
            st = g['start_time']
            if isinstance(st, str):
                try:
                    st = datetime.fromisoformat(st.replace('Z', '+00:00'))
                except Exception:
                    st = now
            if st.tzinfo is None:
                st = st.replace(tzinfo=timezone.utc)

            day_et = _et_date(st)
            cutoff = st - timedelta(minutes=10)  # approximate "bet-time/close"

            # Pull bet-time consensus lines + best multi-book retail lines
            s_home = _latest_line_before(conn, event_id, 'SPREAD', 'HOME', cutoff)
            s_away = _latest_line_before(conn, event_id, 'SPREAD', 'AWAY', cutoff)
            t_over = _latest_line_before(conn, event_id, 'TOTAL', 'OVER', cutoff)
            t_under = _latest_line_before(conn, event_id, 'TOTAL', 'UNDER', cutoff)

            best_sh = _best_book_line_before(conn, event_id, 'SPREAD', 'HOME', cutoff)
            best_sa = _best_book_line_before(conn, event_id, 'SPREAD', 'AWAY', cutoff)
            best_to = _best_book_line_before(conn, event_id, 'TOTAL', 'OVER', cutoff)
            best_tu = _best_book_line_before(conn, event_id, 'TOTAL', 'UNDER', cutoff)

            # Need both spread_home + total for the model to run
            if not s_home or not t_over:
                continue
            if s_home.get('line_value') is None or t_over.get('line_value') is None:
                continue

            market_snapshot = {
                'spread_home': float(s_home['line_value']),
                'spread_price_home': float(s_home.get('price') or -110),
                'total': float(t_over['line_value']),
                'total_over_price': float(t_over.get('price') or -110),
                # Keep each retail quote intact, including its capture time.
                '_best_spread_home': best_sh,
                '_best_spread_away': best_sa,
                '_best_total_over': best_to,
                '_best_total_under': best_tu,
                '_quote_as_of': cutoff,
                '_raw_snaps': []
            }
            if mode == 'simulate':
                best_ml_h = _best_book_line_before(conn, event_id, 'MONEYLINE', 'HOME', cutoff) or _latest_line_before(conn, event_id, 'MONEYLINE', 'HOME', cutoff)
                best_ml_a = _best_book_line_before(conn, event_id, 'MONEYLINE', 'AWAY', cutoff) or _latest_line_before(conn, event_id, 'MONEYLINE', 'AWAY', cutoff)
                if best_ml_h:
                    market_snapshot['_best_moneyline_home'] = best_ml_h
                if best_ml_a:
                    market_snapshot['_best_moneyline_away'] = best_ml_a

            # Run model (no persistence)
            try:
                res = model.analyze(event_id, market_snapshot=market_snapshot, event_context={
                    'id': event_id,
                    'home_team': g['home_team'],
                    'away_team': g['away_team'],
                    'league': 'NCAAM',
                    'sport': 'NCAAM',
                    'start_time': st,
                    'neutral_site': bool(g.get('neutral_site', False)),
                    'venue': g.get('venue'),
                    'venue_city': g.get('venue_city'),
                    'venue_state': g.get('venue_state'),
                }, relax_gates=False, persist=False)
                dbg = (res.get('debug') or {})
                ctx = (res.get('context') or {})
            except Exception:
                continue

            mu_spread = dbg.get('mu_spread_power')
            if mu_spread is None:
                mu_spread = ctx.get('mu_spread_power') if ctx.get('mu_spread_power') is not None else ctx.get('fair_spread_home')
            mu_total = dbg.get('mu_total_power')
            if mu_total is None:
                mu_total = ctx.get('mu_total_power') if ctx.get('mu_total_power') is not None else ctx.get('fair_total')

            # Final outcomes
            home_score = float(g.get('home_score'))
            away_score = float(g.get('away_score'))
            home_margin = home_score - away_score
            final_total = home_score + away_score

            if mode == 'mae':
                # Spread MAE
                if s_home and mu_spread is not None:
                    n_spread += 1
                    close = float(s_home['line_value'])
                    mae_spread_vs_close += abs(float(mu_spread) - close)
                    market_spread_error += abs(close + home_margin)
                    mae_spread_vs_final += abs(float(mu_spread) + home_margin)
                    sp_diff = float(mu_spread) - close
                    actual_home_sp = -home_margin
                    if abs(sp_diff) >= 0.5 and abs(actual_home_sp - close) > 1e-9:
                        won = (actual_home_sp < close) if sp_diff < 0 else (actual_home_sp > close)
                        dir_stats['spread_05'][0 if won else 1] += 1
                        bkey = 'spread_lt14_05' if abs(close) < 14.0 else 'spread_ge14_05'
                        dir_stats[bkey][0 if won else 1] += 1
                        if abs(sp_diff) >= 1.0:
                            dir_stats['spread_10'][0 if won else 1] += 1

                # Total MAE
                if t_over and mu_total is not None:
                    n_total += 1
                    close = float(t_over['line_value'])
                    mae_total_vs_close += abs(float(mu_total) - close)
                    market_total_error += abs(close - final_total)
                    mae_total_vs_final += abs(float(mu_total) - final_total)
                    tot_diff = float(mu_total) - close
                    if abs(tot_diff) >= 0.5 and abs(final_total - close) > 1e-9:
                        if tot_diff > 0:
                            dir_stats['total_over_05'][0 if final_total > close else 1] += 1
                        else:
                            dir_stats['total_under_05'][0 if final_total < close else 1] += 1

                if len(samples) < 8:
                    samples.append({
                        'event_id': event_id,
                        'start_time': st.isoformat(),
                        'home': g['home_team'],
                        'away': g['away_team'],
                        'mu_spread': mu_spread,
                        'close_spread': s_home['line_value'] if s_home else None,
                        'final_margin': home_margin,
                        'mu_total': mu_total,
                        'close_total': t_over['line_value'] if t_over else None,
                        'final_total': final_total,
                    })

            elif mode == 'simulate':
                # 1) Collect parlay leg candidates for this game (Sweet-Spot Home Fav ML, Actionable, or Closest-Lean Smart Risk)
                leg_added = False
                home_sp_val = float(s_home['line_value'])
                ml_h_quote = market_snapshot.get('_best_moneyline_home')
                if (
                    not bool(g.get('neutral_site', False))
                    and (-9.5 <= home_sp_val <= -4.5)
                    and mu_spread is not None
                    and float(mu_spread) <= home_sp_val - 0.5
                    and isinstance(ml_h_quote, dict)
                    and ml_h_quote.get('price') is not None
                ):
                    try:
                        ml_pr = int(ml_h_quote['price'])
                        if -380 <= ml_pr <= -155:
                            sig_sp = max(8.0, float(ctx.get('sigma_spread') or 10.8))
                            p_raw_ml = 0.5 * (1.0 - math.erf(float(mu_spread) / (sig_sp * math.sqrt(2.0))))
                            wp_cal_ml = float(model._calibrate_win_prob(p_raw_ml))
                            ev_ml = wp_cal_ml * (_dec_from_american(ml_pr) - 1.0) - (1.0 - wp_cal_ml)
                            if wp_cal_ml >= 0.68 and ev_ml >= 0.005:
                                ml_out = 'PUSH' if abs(home_margin) < 1e-9 else ('WIN' if home_margin > 0 else 'LOSS')
                                parlay_legs.append({
                                    'event_id': event_id,
                                    'day_et': day_et,
                                    'market_type': 'MONEYLINE',
                                    'pick': g['home_team'],
                                    'price': ml_pr,
                                    'win_prob': round(wp_cal_ml, 4),
                                    'ev': round(ev_ml, 4),
                                    'risk_tier': 'CORE',
                                    'outcome': ml_out,
                                })
                                leg_added = True
                    except Exception:
                        pass

                recs_list = (res.get('recommendations') or []) if isinstance(res, dict) else []
                if not leg_added:
                    cand_leg = None
                    cand_tier = 'CORE'
                    for rr in recs_list:
                        bt = str(rr.get('bet_type') or '').upper()
                        if bt not in ('SPREAD', 'TOTAL'):
                            continue
                        if _leg_has_contra_risk(rr.get('movement_tags')):
                            continue
                        if float(rr.get('ev') or 0.0) >= 0.02 and float(rr.get('win_prob') or 0.0) >= 0.525:
                            cand_leg = rr
                            cand_tier = str(rr.get('risk_tier') or ('SMART_RISK' if rr.get('is_smart_risk') else 'CORE'))
                            break
                    if cand_leg is None and isinstance(ctx.get('closest_lean'), dict):
                        cl = ctx['closest_lean']
                        bt_cl = str(cl.get('bet_type') or '').upper()
                        if (
                            bt_cl in ('SPREAD', 'TOTAL')
                            and not _leg_has_contra_risk(cl.get('movement_tags'))
                            and float(cl.get('ev') or 0.0) >= 0.025
                            and float(cl.get('win_prob') or 0.0) >= 0.53
                        ):
                            cand_leg = cl
                            cand_tier = 'SMART_RISK'

                    if isinstance(cand_leg, dict) and cand_leg.get('market_line') is not None:
                        bt_l = str(cand_leg.get('bet_type') or '').upper()
                        side_l = str(cand_leg.get('side') or '').strip().lower()
                        line_l = float(cand_leg['market_line'])
                        price_l = int(cand_leg.get('price') or -110)
                        if bt_l == 'SPREAD':
                            if side_l not in ('home', 'away'):
                                side_l = 'home' if str(g['home_team']).lower() in str(cand_leg.get('selection') or '').lower() else 'away'
                            team_l = g['home_team'] if side_l == 'home' else g['away_team']
                            leg_out = _grade_spread(team_l, g['home_team'], g['away_team'], line_l, home_score, away_score)
                        else:
                            if side_l not in ('over', 'under'):
                                side_l = 'over' if 'OVER' in str(cand_leg.get('selection') or '').upper() else 'under'
                            leg_out = _grade_total(side_l.upper(), line_l, home_score, away_score)
                        if leg_out in ('WIN', 'LOSS', 'PUSH'):
                            parlay_legs.append({
                                'event_id': event_id,
                                'day_et': day_et,
                                'market_type': bt_l,
                                'pick': cand_leg.get('selection'),
                                'price': price_l,
                                'win_prob': float(cand_leg.get('win_prob') or 0.53),
                                'ev': float(cand_leg.get('ev') or 0.0),
                                'risk_tier': cand_tier,
                                'outcome': leg_out,
                            })

                # 2) Published straight bets (Core & Smart Risk)
                if not res or not res.get('market_type') or not res.get('pick'):
                    continue

                market_type = str(res.get('market_type') or '').upper().strip()
                ev = float(res.get('ev_per_unit') or 0.0)

                # Only count bets that would be published/recommended
                min_ev = float(os.getenv('NCAAM_PUBLISH_MIN_EV', '0.02'))
                if ev < min_ev:
                    continue

                bet_line = float(res.get('bet_line')) if res.get('bet_line') is not None else None
                bet_price = float(res.get('bet_price') or -110)

                outcome = 'VOID'
                pnl = 0.0

                if market_type == 'SPREAD' and bet_line is not None:
                    outcome = _grade_spread(str(res.get('pick')), g['home_team'], g['away_team'], bet_line, home_score, away_score)
                elif market_type == 'TOTAL' and bet_line is not None:
                    # res.pick will be OVER/UNDER
                    outcome = _grade_total(str(res.get('pick')), bet_line, home_score, away_score)

                if outcome == 'WIN':
                    pnl = _american_profit_per_unit(bet_price)
                elif outcome == 'LOSS':
                    pnl = -1.0
                elif outcome == 'PUSH':
                    pnl = 0.0
                else:
                    continue

                top_rec_meta = recs_list[0] if recs_list else {}
                is_sr = bool(res.get('is_smart_risk') or top_rec_meta.get('is_smart_risk', False))
                r_tier = str(res.get('risk_tier') or top_rec_meta.get('risk_tier') or ('SMART_RISK' if is_sr else 'CORE'))
                bets.append({
                    'event_id': event_id,
                    'day_et': day_et,
                    'start_time': st.isoformat(),
                    'home_team': g['home_team'],
                    'away_team': g['away_team'],
                    'market_type': market_type,
                    'pick': res.get('pick'),
                    'selection': res.get('selection'),
                    'bet_line': bet_line,
                    'market_line': bet_line,
                    'bet_price': bet_price,
                    'ev_per_unit': ev,
                    'win_prob': float(res.get('win_prob') or top_rec_meta.get('win_prob') or 0.5),
                    'win_prob_lb10': top_rec_meta.get('win_prob_lb10'),
                    'conviction_sources': top_rec_meta.get('conviction_sources'),
                    'conviction_sources_total': top_rec_meta.get('conviction_sources_total'),
                    'movement_tags': top_rec_meta.get('movement_tags') or [],
                    'top6_eligible': bool(res.get('top6_eligible', True)),
                    'quality_score': float(res.get('quality_score') or top_rec_meta.get('quality_score') or compute_top6_quality_score(res)),
                    'is_smart_risk': is_sr,
                    'risk_tier': r_tier,
                    'outcome': outcome,
                    'pnl_units': pnl,
                })

                if len(samples) < 8:
                    samples.append(bets[-1])

    # Summaries
    sim = None
    if mode == 'simulate':
        sim = summarize_simulate_backtest(bets, parlay_legs)

    out = {
        'mode': mode,
        'evaluation_basis': 'historical odds, recomputed features; use published_holdout for prospective validation',
        'window_days': days,
        'limit': limit,
        'n_games': len(games),
        'n_spread': n_spread,
        'n_total': n_total,
        'mae_spread_vs_close': (mae_spread_vs_close / n_spread) if n_spread else None,
        'mae_total_vs_close': (mae_total_vs_close / n_total) if n_total else None,
        'mae_spread_vs_final': (mae_spread_vs_final / n_spread) if n_spread else None,
        'market_spread_mae_vs_final': market_spread_error / n_spread if n_spread else None,
        'market_total_mae_vs_final': market_total_error / n_total if n_total else None,
        'mae_total_vs_final': (mae_total_vs_final / n_total) if n_total else None,
        'directional_ats': {
            k: {
                'wins': w,
                'losses': l,
                'win_rate': round(w / (w + l), 4) if (w + l) else None,
            }
            for k, (w, l) in dir_stats.items()
        } if mode == 'mae' else None,
        'simulation': sim,
        'env': {
            'NCAAM_W_BASE': os.getenv('NCAAM_W_BASE'),
            'NCAAM_W_KENPOM': os.getenv('NCAAM_W_KENPOM'),
            'NCAAM_CAP_SPREAD': os.getenv('NCAAM_CAP_SPREAD'),
            'NCAAM_CAP_TOTAL': os.getenv('NCAAM_CAP_TOTAL'),
            'NCAAM_PUBLISH_MIN_EV': os.getenv('NCAAM_PUBLISH_MIN_EV'),
            'BACKTEST_NO_NETWORK': os.getenv('BACKTEST_NO_NETWORK'),
        },
        'samples': samples,
    }

    txt = json.dumps(out, indent=2, default=str)
    print(txt)

    # also write an artifact file for Actions
    try:
        with open('backtest_output.json', 'w', encoding='utf-8') as f:
            f.write(txt)
    except Exception:
        pass


if __name__ == '__main__':
    main()
