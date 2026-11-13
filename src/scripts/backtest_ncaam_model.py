import sys
import os
import json
from datetime import datetime, timedelta, timezone

# Allow running from repo root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.database import get_db_connection, _exec
from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2


def _et_date(d: datetime) -> str:
    try:
        return d.astimezone(timezone.utc).strftime('%Y-%m-%d')
    except Exception:
        return d.strftime('%Y-%m-%d')


def _latest_line_before(conn, event_id: str, market_type: str, side: str, cutoff: datetime):
    # Use captured_at if exists; fallback to latest.
    row = _exec(conn, """
        SELECT line_value, price, captured_at
        FROM odds_snapshots
        WHERE event_id=%s AND market_type=%s AND side=%s
          AND captured_at <= %s
        ORDER BY captured_at DESC
        LIMIT 1
    """, (event_id, market_type, side, cutoff)).fetchone()
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
    mae_spread_vs_final = 0.0
    mae_total_vs_final = 0.0

    # Metrics (simulate mode)
    bets = []

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

            cutoff = st - timedelta(minutes=10)  # approximate "bet-time/close"

            # Pull bet-time consensus lines (per-side)
            s_home = _latest_line_before(conn, event_id, 'SPREAD', 'HOME', cutoff)
            s_away = _latest_line_before(conn, event_id, 'SPREAD', 'AWAY', cutoff)
            t_over = _latest_line_before(conn, event_id, 'TOTAL', 'OVER', cutoff)
            t_under = _latest_line_before(conn, event_id, 'TOTAL', 'UNDER', cutoff)

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
                # best-price placeholders (use same bet-time snapshot for fairness)
                '_best_spread_home': {'line_value': float(s_home['line_value']), 'price': float(s_home.get('price') or -110), 'book': 'bt'},
                '_best_spread_away': {'line_value': float(s_away['line_value']), 'price': float(s_away.get('price') or -110), 'book': 'bt'} if s_away else None,
                '_best_total_over': {'line_value': float(t_over['line_value']), 'price': float(t_over.get('price') or -110), 'book': 'bt'},
                '_best_total_under': {'line_value': float(t_under['line_value']), 'price': float(t_under.get('price') or -110), 'book': 'bt'} if t_under else None,
                '_raw_snaps': []
            }

            # Run model (no persistence)
            try:
                res = model.analyze(event_id, market_snapshot=market_snapshot, event_context={
                    'id': event_id,
                    'home_team': g['home_team'],
                    'away_team': g['away_team'],
                    'league': 'NCAAM',
                    'sport': 'NCAAM',
                    'start_time': st,
                }, relax_gates=False, persist=False)
                dbg = (res.get('debug') or {})
            except Exception:
                continue

            mu_spread = dbg.get('mu_spread_power')
            mu_total = dbg.get('mu_total_power')

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
                    mae_spread_vs_final += abs(float(mu_spread) - home_margin)

                # Total MAE
                if t_over and mu_total is not None:
                    n_total += 1
                    close = float(t_over['line_value'])
                    mae_total_vs_close += abs(float(mu_total) - close)
                    mae_total_vs_final += abs(float(mu_total) - final_total)

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
                # Use the model's own published-bet logic: it returns a single persisted rec when it has one.
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
                    pnl = 0.0

                bets.append({
                    'event_id': event_id,
                    'start_time': st.isoformat(),
                    'market_type': market_type,
                    'pick': res.get('pick'),
                    'bet_line': bet_line,
                    'bet_price': bet_price,
                    'ev_per_unit': ev,
                    'outcome': outcome,
                    'pnl_units': pnl,
                })

                if len(samples) < 8:
                    samples.append(bets[-1])

    # Summaries
    sim = None
    if mode == 'simulate':
        n_bets = len(bets)
        wins = sum(1 for b in bets if b['outcome'] == 'WIN')
        losses = sum(1 for b in bets if b['outcome'] == 'LOSS')
        pushes = sum(1 for b in bets if b['outcome'] == 'PUSH')
        roi = (sum(b['pnl_units'] for b in bets) / n_bets) if n_bets else None
        sim = {
            'n_bets': n_bets,
            'wins': wins,
            'losses': losses,
            'pushes': pushes,
            'win_rate': (wins / (wins + losses)) if (wins + losses) else None,
            'roi_units_per_bet': roi,
            'total_pnl_units': sum(b['pnl_units'] for b in bets) if n_bets else 0.0,
            'bets_by_market': {
                'SPREAD': sum(1 for b in bets if b['market_type'] == 'SPREAD'),
                'TOTAL': sum(1 for b in bets if b['market_type'] == 'TOTAL'),
            }
        }

    out = {
        'mode': mode,
        'window_days': days,
        'limit': limit,
        'n_games': len(games),
        'n_spread': n_spread,
        'n_total': n_total,
        'mae_spread_vs_close': (mae_spread_vs_close / n_spread) if n_spread else None,
        'mae_total_vs_close': (mae_total_vs_close / n_total) if n_total else None,
        'mae_spread_vs_final': (mae_spread_vs_final / n_spread) if n_spread else None,
        'mae_total_vs_final': (mae_total_vs_final / n_total) if n_total else None,
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
