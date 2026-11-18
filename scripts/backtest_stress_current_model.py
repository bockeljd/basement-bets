#!/usr/bin/env python3
"""Walk-forward backtest & adversarial stress-test suite for NCAAMMarketFirstModelV2.

Uses real D1 team ratings from `data/ncaam_torvik_cache.json` (plus realistic
market efficiency, correlated early-season rating noise, sharp splits, reverse steam,
injury shocks, and blowout variance) to evaluate the *current* model implementation
end-to-end without requiring network or DB access (`REQUIRE_DATABASE=0`).

Usage:
  REQUIRE_DATABASE=0 ./venv/bin/python scripts/backtest_stress_current_model.py
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

os.environ.setdefault("REQUIRE_DATABASE", "0")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2


def american_profit_per_unit(price: int) -> float:
    p = int(price or -110)
    return (p / 100.0) if p > 0 else (100.0 / abs(p))


def load_real_d1_teams() -> List[Dict[str, Any]]:
    path = os.path.join(REPO_ROOT, "data", "ncaam_torvik_cache.json")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    stats = raw.get("stats") or {}
    teams = []
    for name, d in stats.items():
        pace = float(d.get("Pace") or 68.0)
        ortg = float(d.get("ORtg") or 106.0)
        drtg = float(d.get("DRtg") or 106.0)
        teams.append(
            {
                "name": name,
                "ortg": ortg,
                "drtg": drtg,
                "net": ortg - drtg,
                "pace": min(80.0, max(60.0, pace)),
            }
        )
    return teams


def build_offline_model(
    *,
    winprob_cal: Optional[Dict[str, Any]] = None,
) -> NCAAMMarketFirstModelV2:
    """Instantiate NCAAMMarketFirstModelV2 with lightweight mocked I/O collaborators."""
    model = NCAAMMarketFirstModelV2()
    model.torvik_service = MagicMock()
    model.kenpom_client = MagicMock()
    model.haslametrics_client = MagicMock()
    model.injury_service = MagicMock()
    model.geo_service = MagicMock()
    model.news_service = MagicMock()

    model.geo_service.get_altitude_adjustment.return_value = 0.0
    model.geo_service.calculate_distance.return_value = 250.0
    model.kenpom_client.get_home_court.return_value = None
    model.kenpom_client.get_player_stats_for_team.return_value = []
    model.kenpom_client.get_team_player_agg.return_value = None
    model.news_service.fetch_game_context.return_value = {}
    model.news_service.summarize_impact.return_value = ""
    model._get_council_verdict = lambda eid: None
    model._calculate_shooting_regression = lambda *a, **kw: 0.0
    model._calculate_situational_spots = lambda *a, **kw: 0.0
    model._calculate_fatigue_penalty = lambda *a, **kw: 0.0
    model._apply_referee_signal = lambda eid, tot: tot
    model._get_archetype_stats = lambda key: {"n": 80, "mean": 0.02, "sd": 0.90}
    model._load_adaptive_learning = lambda: {}
    if winprob_cal is not None:
        model._load_winprob_calibration = lambda: winprob_cal
    else:
        model._load_winprob_calibration = lambda: {"points": []}
    return model


def simulate_season_slate(
    teams: List[Dict[str, Any]],
    *,
    seed: int = 20261116,
    days_per_month: Tuple[Tuple[int, int], ...] = ((11, 25), (12, 25), (1, 25), (2, 25)),
    games_per_day: int = 16,
    over_public_shade: float = 0.5,
) -> List[Dict[str, Any]]:
    """Build deterministic realistic multi-month NCAAM matchups grounded in real D1 ratings."""
    rng = random.Random(seed)
    games: List[Dict[str, Any]] = []
    day_idx = 0

    for month, n_days in days_per_month:
        year = 2026 if month in (11, 12) else 2027
        # Rating estimation error decays from Nov preseason uncertainty to Feb convergence
        if month == 11:
            est_sigma, mkt_sigma, game_sigma_base, tot_sigma_base = 4.2, 1.35, 11.4, 15.8
            continuity_mu = 0.52
        elif month == 12:
            est_sigma, mkt_sigma, game_sigma_base, tot_sigma_base = 3.0, 1.25, 10.9, 15.3
            continuity_mu = 0.62
        else:
            est_sigma, mkt_sigma, game_sigma_base, tot_sigma_base = 2.1, 1.15, 10.5, 14.9
            continuity_mu = 0.72

        for d_off in range(n_days):
            day_idx += 1
            day_str = f"{year}-{month:02d}-{min(28, d_off + 1):02d}"
            start_dt = datetime(year, month, min(28, d_off + 1), 20, 0, tzinfo=timezone.utc)
            pool = list(teams)
            rng.shuffle(pool)

            for g_i in range(games_per_day):
                h = pool[(2 * g_i) % len(pool)]
                a = pool[(2 * g_i + 1) % len(pool)]
                if h["name"] == a["name"]:
                    continue

                true_tempo = max(56.0, min(82.0, 68.0 + 0.65 * ((h["pace"] - 68.0) + (a["pace"] - 68.0))))
                h_true_score = (h["ortg"] * a["drtg"] / 106.0) * (true_tempo / 100.0) + 1.6
                a_true_score = (a["ortg"] * h["drtg"] / 106.0) * (true_tempo / 100.0) - 1.6
                true_margin = h_true_score - a_true_score
                true_total = h_true_score + a_true_score

                # Correlated error shared across Torvik/KenPom/Hasla vs semi-sharp market close
                shared_spread_err = rng.gauss(0.0, est_sigma * 0.78)
                shared_total_err = rng.gauss(0.0, est_sigma * 0.90)
                tv_margin = true_margin + shared_spread_err + rng.gauss(0.0, 0.9)
                kp_margin = true_margin + shared_spread_err + rng.gauss(0.0, 0.9)
                hs_margin = true_margin + shared_spread_err + rng.gauss(0.0, 1.1)

                # Slight positive bias on rated totals in Nov/Dec (transfer pace / cupcake noise)
                early_over_bias = 1.1 if month in (11, 12) else 0.35
                tv_total = true_total + shared_total_err + early_over_bias + rng.gauss(0.0, 1.2)
                kp_total = true_total + shared_total_err + early_over_bias + rng.gauss(0.0, 1.4)
                hs_total = true_total + shared_total_err + early_over_bias + rng.gauss(0.0, 1.6)

                # Market close reflects sharp information + occasional soft edges
                mkt_spread_home = round((-true_margin + rng.gauss(0.0, mkt_sigma)) * 2.0) / 2.0
                mkt_total = round((true_total - over_public_shade * 0.3 + rng.gauss(0.0, mkt_sigma * 1.1)) * 2.0) / 2.0

                # Realistic line movement & sharp splits
                spread_move = round(rng.gauss(0.0, 0.85), 1)
                total_move = round(rng.gauss(0.0, 1.05), 1)

                # Realistic game residual variance (wider on blowouts + 14-22 mid-blowouts)
                abs_true = abs(true_margin)
                spread_sigma_real = game_sigma_base
                if abs_true >= 14.0:
                    spread_sigma_real += min(4.2, (abs_true - 14.0) * 0.17)
                actual_margin = round(true_margin + rng.gauss(0.0, spread_sigma_real))
                if actual_margin == 0:
                    actual_margin = 1 if rng.random() > 0.5 else -1

                actual_total = round(true_total + rng.gauss(0.0, tot_sigma_base))
                actual_home = max(38, int(round((actual_total + actual_margin) / 2.0)))
                actual_away = max(35, int(round((actual_total - actual_margin) / 2.0)))

                # Public/Money splits (some sharp divergences)
                pub_over_b = rng.randint(42, 76)
                sharp_flag = rng.random() < 0.22
                if sharp_flag:
                    # Sharp Under divergence when public bets Over
                    pub_over_m = max(18, pub_over_b - rng.randint(25, 42))
                else:
                    pub_over_m = max(15, min(85, pub_over_b + rng.randint(-12, 12)))

                pub_home_b = rng.randint(30, 72)
                pub_home_m = max(15, min(85, pub_home_b + rng.randint(-28, 28)))

                games.append(
                    {
                        "event_id": f"bt:{day_str}:{g_i}",
                        "day": day_str,
                        "month": month,
                        "start_time": start_dt,
                        "home_team": h["name"],
                        "away_team": a["name"],
                        "tempo": true_tempo,
                        "continuity": min(0.90, max(0.30, rng.gauss(continuity_mu, 0.12))),
                        "tv_margin": tv_margin,
                        "kp_margin": kp_margin,
                        "hs_margin": hs_margin,
                        "tv_total": tv_total,
                        "kp_total": kp_total,
                        "hs_total": hs_total,
                        "mkt_spread_home": mkt_spread_home,
                        "mkt_total": mkt_total,
                        "spread_move": spread_move,
                        "total_move": total_move,
                        "actual_home": actual_home,
                        "actual_away": actual_away,
                        "splits": {
                            "SPREAD": {
                                "HOME": {"bet_pct": pub_home_b, "handle_pct": pub_home_m},
                                "AWAY": {"bet_pct": 100 - pub_home_b, "handle_pct": 100 - pub_home_m},
                            },
                            "TOTAL": {
                                "OVER": {"bet_pct": pub_over_b, "handle_pct": pub_over_m},
                                "UNDER": {"bet_pct": 100 - pub_over_b, "handle_pct": 100 - pub_over_m},
                            },
                        },
                    }
                )
    return games


def run_model_on_games(
    model: NCAAMMarketFirstModelV2,
    games: List[Dict[str, Any]],
    *,
    relax_gates: bool = False,
) -> List[Dict[str, Any]]:
    """Run NCAAMMarketFirstModelV2.analyze() over simulated games & grade every recommendation."""
    import src.database as db_mod

    current_splits: Dict[str, Any] = {}
    orig_splits_fn = getattr(db_mod, "get_latest_action_splits", None)
    db_mod.get_latest_action_splits = lambda eid: current_splits.get(eid, {})

    records: List[Dict[str, Any]] = []
    try:
        for g in games:
            eid = g["event_id"]
            current_splits[eid] = g.get("splits") or {}
            model.torvik_service.get_projection.return_value = {
                "margin": g["tv_margin"],
                "official_margin": g["tv_margin"],
                "total": g["tv_total"],
                "projected_score": "70-72",
                "lean": "Home",
            }
            model.torvik_service.get_matchup_team_stats.return_value = {
                "game_tempo": g["tempo"],
                "home": {"luck": 0.0, "continuity": g["continuity"], "record": "6-2"},
                "away": {"luck": 0.0, "continuity": g["continuity"], "record": "5-3"},
            }
            if g.get("kp_disabled"):
                model.kenpom_client.calculate_kenpom_adjustment.return_value = None
                model.kenpom_client.get_team_rating.return_value = None
            else:
                model.kenpom_client.calculate_kenpom_adjustment.return_value = {
                    "spread_adj": g["kp_margin"],
                    "neutral_margin": g["kp_margin"] - 3.2,
                    "fair_margin": g["kp_margin"],
                    "fair_total": g["kp_total"],
                    "total_adj": 0.0,
                    "sos_spread_adj": 0.0,
                    "four_factors_adj": 0.0,
                    "exp_height_adj": 0.0,
                    "summary": "KP",
                }
                model.kenpom_client.get_team_rating.return_value = {"adj_t": g["tempo"]}

            if g.get("hs_disabled"):
                model.haslametrics_client.calculate_projection.return_value = {"available": False}
            else:
                model.haslametrics_client.calculate_projection.return_value = {
                    "available": True,
                    "margin": g["hs_margin"],
                    "total": g["hs_total"],
                    "home": {"sos": 100, "mom": 0.0, "inc": g.get("hs_inc", 0.05)},
                    "away": {"sos": 100, "mom": 0.0, "inc": g.get("hs_inc", 0.05)},
                }

            model.injury_service.get_matchup_injuries.return_value = g.get(
                "injury_ctx", {"has_injuries": False, "injuries": [], "sigma_mult": 1.0, "spread_adj": 0.0, "total_adj": 0.0}
            )

            sp = g["mkt_spread_home"]
            tot = g["mkt_total"]
            snap = {
                "spread_home": sp,
                "spread_price_home": -110,
                "total": tot,
                "total_over_price": -110,
                "book_spread": "Consensus",
                "book_total": "Consensus",
                "_best_spread_home": {"line_value": sp, "price": -110, "book": "DK"},
                "_best_spread_away": {"line_value": -sp, "price": -110, "book": "FD"},
                "_best_total_over": {"line_value": tot, "price": -110, "book": "DK"},
                "_best_total_under": {"line_value": tot, "price": -110, "book": "FD"},
                "_market_consensus": {
                    "open_spread_home": sp - g.get("spread_move", 0.0),
                    "current_spread_home": sp,
                    "spread_move_home": g.get("spread_move", 0.0),
                    "open_total": tot - g.get("total_move", 0.0),
                    "current_total": tot,
                    "total_move": g.get("total_move", 0.0),
                    "spread_disagreement": g.get("spread_disagree", 0.5),
                    "total_disagreement": g.get("total_disagree", 0.5),
                },
            }
            ev_ctx = {
                "id": eid,
                "home_team": g["home_team"],
                "away_team": g["away_team"],
                "start_time": g["start_time"],
                "neutral_site": False,
                "action_splits": g.get("splits") or {},
            }

            res = model.analyze(
                eid,
                market_snapshot=snap,
                event_context=ev_ctx,
                persist=False,
                relax_gates=relax_gates,
            )
            recs = res.get("recommendations") or []
            if not recs:
                continue

            margin = g["actual_home"] - g["actual_away"]
            tot_score = g["actual_home"] + g["actual_away"]

            # Keep per-rec graded details for All Picks & Top 6/Day evaluation
            for rec in recs:
                mt = str(rec.get("bet_type") or "").upper()
                sel = str(rec.get("selection") or "")
                line = rec.get("market_line")
                price = int(rec.get("price") or -110)
                if line is None:
                    continue
                line_f = float(line)

                if mt == "SPREAD":
                    is_home_pick = sel.startswith(g["home_team"])
                    diff = (margin + line_f) if is_home_pick else ((-margin) + line_f)
                    if abs(diff) < 1e-9:
                        outcome, pl = "PUSH", 0.0
                    elif diff > 0:
                        outcome, pl = "WON", american_profit_per_unit(price)
                    else:
                        outcome, pl = "LOST", -1.0
                    side_tag = "SPREAD"
                elif mt == "TOTAL":
                    is_over = sel.upper().startswith("OVER")
                    diff = (tot_score - line_f) if is_over else (line_f - tot_score)
                    if abs(diff) < 1e-9:
                        outcome, pl = "PUSH", 0.0
                    elif diff > 0:
                        outcome, pl = "WON", american_profit_per_unit(price)
                    else:
                        outcome, pl = "LOST", -1.0
                    side_tag = "TOTAL_OVER" if is_over else "TOTAL_UNDER"
                else:
                    continue

                records.append(
                    {
                        "event_id": eid,
                        "day": g["day"],
                        "month": g["month"],
                        "market": mt,
                        "side_tag": side_tag,
                        "abs_spread": abs(float(sp)),
                        "line": line_f,
                        "ev": float(rec.get("ev") or 0.0),
                        "win_prob": float(rec.get("win_prob") or 0.5),
                        "win_prob_lb10": float(rec.get("win_prob_lb10") or rec.get("win_prob") or 0.5),
                        "edge_points": float(rec.get("edge_points") or 0.0),
                        "conf_score": int(rec.get("confidence_0_100") or 0),
                        "conf_tier": str(rec.get("confidence") or "Low"),
                        "tags": list(rec.get("movement_tags") or []),
                        "top6_eligible": bool(rec.get("top6_eligible", True)),
                        "quality_score": float(rec.get("quality_score") if rec.get("quality_score") is not None else rec.get("ev") or 0.0),
                        "sigma_mult": float(rec.get("sigma_mult") or 1.0),
                        "outcome": outcome,
                        "pl": pl,
                    }
                )
    finally:
        if orig_splits_fn is not None:
            db_mod.get_latest_action_splits = orig_splits_fn
    return records


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    w = sum(1 for r in rows if r["outcome"] == "WON")
    l = sum(1 for r in rows if r["outcome"] == "LOST")
    p = sum(1 for r in rows if r["outcome"] == "PUSH")
    dec = w + l
    settle = dec + p
    pl = sum(r["pl"] for r in rows)
    wr = (w / dec * 100.0) if dec else 0.0
    roi = (pl / settle * 100.0) if settle else 0.0
    dec_rows = [r for r in rows if r["outcome"] in ("WON", "LOST")]
    brier = (
        sum(((r["win_prob"] - (1.0 if r["outcome"] == "WON" else 0.0)) ** 2) for r in dec_rows) / len(dec_rows)
        if dec_rows
        else None
    )
    avg_p = (sum(r["win_prob"] for r in dec_rows) / len(dec_rows) * 100.0) if dec_rows else 0.0

    # Max cumulative unit drawdown
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for r in rows:
        cum += r["pl"]
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    return {
        "n": settle,
        "w": w,
        "l": l,
        "p": p,
        "wr": round(wr, 1),
        "pl": round(pl, 2),
        "roi": round(roi, 1),
        "avg_pred": round(avg_p, 1),
        "cal_gap": round(wr - avg_p, 1) if dec else 0.0,
        "brier": round(brier, 4) if brier is not None else None,
        "max_dd": round(max_dd, 2),
    }


def select_top_n_per_day(
    rows: List[Dict[str, Any]],
    n: int = 6,
    *,
    score_fn=None,
) -> List[Dict[str, Any]]:
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["day"]].append(r)

    if score_fn is None:
        score_fn = lambda r: r["ev"]

    selected: List[Dict[str, Any]] = []
    for day in sorted(by_day.keys()):
        day_rows = sorted(by_day[day], key=score_fn, reverse=True)
        seen_eids = set()
        picked = []
        for r in day_rows:
            if r["event_id"] in seen_eids:
                continue
            seen_eids.add(r["event_id"])
            item = dict(r)
            item["daily_rank"] = len(picked) + 1
            picked.append(item)
            if len(picked) >= n:
                break
        selected.extend(picked)
    return selected


def quality_rank_score(r: Dict[str, Any]) -> float:
    """Candidate quality-adjusted ranking score that penalizes OVER inflation & thin close spreads."""
    score = r["ev"]
    if r["side_tag"] == "TOTAL_OVER":
        score -= 0.015
    elif r["side_tag"] == "TOTAL_UNDER":
        score += 0.008
    if r["market"] == "SPREAD" and 14.0 <= r["abs_spread"] < 22.0:
        score -= 0.012
    if "sharp_backing" in r["tags"]:
        score += 0.012
    if "contra_sharp_money" in r["tags"]:
        score -= 0.025
    if any(t.startswith("reverse_steam=") for t in r["tags"]):
        score -= 0.015
    score += max(0.0, r["win_prob_lb10"] - 0.52) * 0.4
    return score


def print_row(label: str, s: Dict[str, Any]) -> None:
    brier_str = f"{s['brier']:.4f}" if s["brier"] is not None else "  —   "
    print(
        f"  {label:<28} | {s['w']:>4}-{s['l']:<4} ({s['n']:>4}) | WR {s['wr']:>5.1f}% | "
        f"Pred {s['avg_pred']:>5.1f}% (Gap {s['cal_gap']:>+5.1f}%) | PL {s['pl']:>+7.2f}u | "
        f"ROI {s['roi']:>+5.1f}% | DD {s['max_dd']:>5.2f}u | Brier {brier_str}"
    )


def main() -> None:
    teams = load_real_d1_teams()
    print(f"Loaded {len(teams)} D1 teams from data/ncaam_torvik_cache.json.")
    model = build_offline_model()

    # 1. Multi-month walk-forward baseline backtest (1,600 games across 100 daily slates)
    season_games = simulate_season_slate(teams, seed=20261116, games_per_day=16)
    all_recs = run_model_on_games(model, season_games)
    top6_recs = select_top_n_per_day(all_recs, 6)
    top6_new_recs = select_top_n_per_day(
        [r for r in all_recs if r.get("top6_eligible", True)],
        6,
        score_fn=lambda r: float(r.get("quality_score", r["ev"])),
    )

    print("\n=== 1. CURRENT MODEL WALK-FORWARD BACKTEST (1,600 GAMES / 100 SLATES) ===")
    print_row("All Actionable Picks", summarize(all_recs))
    print_row("Top 6 / Day (by Raw EV)", summarize(top6_recs))
    print_row("Top 6 / Day (Quality + Clean)", summarize(top6_new_recs))

    print("\n--- By Month (All vs Top 6) ---")
    for label, months in (("Nov (Early Preseason)", (11,)), ("Dec (Transition)", (12,)), ("Jan-Feb (In-Season)", (1, 2))):
        print_row(f"All: {label}", summarize([r for r in all_recs if r["month"] in months]))
        print_row(f"Top6: {label}", summarize([r for r in top6_recs if r["month"] in months]))

    print("\n--- By Market & Spread Size (All Picks) ---")
    for side in ("SPREAD", "TOTAL_OVER", "TOTAL_UNDER"):
        print_row(f"Market: {side}", summarize([r for r in all_recs if r["side_tag"] == side]))
    for lbl, lo, hi in (("Spread <6", 0, 6), ("Spread 6-14", 6, 14), ("Spread 14-22", 14, 22), ("Spread 22+", 22, 99)):
        print_row(lbl, summarize([r for r in all_recs if r["market"] == "SPREAD" and lo <= r["abs_spread"] < hi]))

    print("\n--- By Confidence Tier & Edge Bucket (All Picks) ---")
    for tier in ("High", "Medium", "Low"):
        print_row(f"Tier: {tier}", summarize([r for r in all_recs if r["conf_tier"] == tier]))
    for lbl, lo, hi in (("Edge 2-5%", 0.02, 0.05), ("Edge 5-8%", 0.05, 0.08), ("Edge 8-12%", 0.08, 0.12), ("Edge 12%+", 0.12, 1.0)):
        print_row(lbl, summarize([r for r in all_recs if lo <= r["ev"] < hi]))

    print("\n--- By Daily Rank (#1 to #6, Quality-Ranked Top 6) ---")
    for rk in range(1, 7):
        print_row(f"Rank #{rk}", summarize([r for r in top6_new_recs if r["daily_rank"] == rk]))

    # 2. Adversarial Stress Tests (6 targeted extreme scenarios)
    print("\n=== 2. ADVERSARIAL STRESS TESTS ON CURRENT MODEL ===")
    rng = random.Random(999111)

    def make_stress_games(mode: str, n: int = 300) -> List[Dict[str, Any]]:
        out = []
        pool = list(teams)
        for i in range(n):
            h = pool[(2 * i) % len(pool)]
            a = pool[(2 * i + 7) % len(pool)]
            tempo = 68.0
            true_margin = (h["net"] - a["net"]) * 0.68 + 3.2
            true_tot = 144.0
            mkt_sp = round((-true_margin) * 2.0) / 2.0
            mkt_tot = 144.0
            tv_m, kp_m, hs_m = true_margin, true_margin, true_margin
            tv_t, kp_t, hs_t = 144.0, 144.0, 144.0
            sp_mv, tot_mv = 0.0, 0.0
            sp_sig, tot_sig = 10.6, 15.0
            splits = {}
            kp_off, hs_off = False, False
            month = 11

            if mode == "S1_preseason_corr_noise":
                # Sharp market (0.9), correlated +5.2 pt early rating bias in Nov
                mkt_sp = round((-true_margin + rng.gauss(0.0, 0.9)) * 2.0) / 2.0
                mkt_tot = round((true_tot + rng.gauss(0.0, 1.0)) * 2.0) / 2.0
                err_sp = rng.gauss(0.0, 5.2)
                err_tot = rng.gauss(0.0, 5.5)
                tv_m, kp_m, hs_m = true_margin + err_sp, true_margin + err_sp + 0.4, true_margin + err_sp - 0.3
                tv_t, kp_t, hs_t = true_tot + err_tot, true_tot + err_tot + 0.6, true_tot + err_tot + 0.8
                sp_sig, tot_sig = 11.4, 15.8
            elif mode == "S2_fast_tempo_over_bias":
                # Mid-season fast-tempo games where rating models sit +5.5/+7.5 hotter than true/market total
                month = 1
                tempo = 75.5
                true_tot = 156.0
                mkt_tot = 156.0
                tv_t, kp_t, hs_t = 161.5, 162.8, 164.0
                tot_sig = 16.0
            elif mode == "S3_blowout_14_22":
                # In-season 14-21.5 mismatches where market prices true blowout variance accurately
                month = 1
                true_margin = 18.0 if i % 2 == 0 else -18.0
                mkt_sp = -18.0 if true_margin > 0 else 18.0
                tv_m = kp_m = hs_m = true_margin - (5.0 if true_margin > 0 else -5.0)
                sp_sig = 15.0
            elif mode == "S4_sharp_contra_money":
                # In-season heavy +5/+7 rating edge that fades 76% sharp handle on the opposing side
                month = 1
                tv_m = kp_m = hs_m = true_margin + 5.0
                tv_t = kp_t = hs_t = true_tot + 6.5
                splits = {
                    "SPREAD": {"HOME": {"bet_pct": 74, "handle_pct": 24}, "AWAY": {"bet_pct": 26, "handle_pct": 76}},
                    "TOTAL": {"OVER": {"bet_pct": 75, "handle_pct": 25}, "UNDER": {"bet_pct": 25, "handle_pct": 75}},
                }
            elif mode == "S5_reverse_steam_trap":
                # In-season market steamed 2.5 pts away from static ratings (new close is true outcome)
                month = 1
                tv_m = kp_m = hs_m = true_margin + 5.5
                tv_t = kp_t = hs_t = true_tot + 6.5
                mkt_sp = round((-(true_margin - 2.5)) * 2.0) / 2.0
                mkt_tot = true_tot - 2.5
                sp_mv = -2.5 if mkt_sp < 0 else 2.5
                tot_mv = -2.5
            elif mode == "S6_extreme_edge_trap":
                # Games where unpriced info creates huge +8 to +12 pt rating disagreement vs sharp close
                month = 1
                mkt_sp = round((-true_margin) * 2.0) / 2.0
                mkt_tot = true_tot
                sgn_s = 1.0 if i % 2 == 0 else -1.0
                tv_m = kp_m = hs_m = true_margin + sgn_s * 9.0
                tv_t = kp_t = hs_t = true_tot + 9.5
            elif mode == "S7_kp_hasla_degraded":
                month = 1
                kp_off, hs_off = True, True
                tv_m = true_margin + rng.gauss(0.0, 2.5)
                tv_t = true_tot + rng.gauss(0.0, 3.0)

            act_m = round(true_margin + rng.gauss(0.0, sp_sig))
            if act_m == 0:
                act_m = 1
            act_t = round(true_tot + rng.gauss(0.0, tot_sig))
            out.append(
                {
                    "event_id": f"{mode}:{i}",
                    "day": f"2026-{month:02d}-{(i % 20) + 1:02d}",
                    "month": month,
                    "start_time": datetime(2026 if month in (11, 12) else 2027, month, 15, 20, 0, tzinfo=timezone.utc),
                    "home_team": h["name"],
                    "away_team": a["name"],
                    "tempo": tempo,
                    "continuity": 0.65,
                    "tv_margin": tv_m,
                    "kp_margin": kp_m,
                    "hs_margin": hs_m,
                    "tv_total": tv_t,
                    "kp_total": kp_t,
                    "hs_total": hs_t,
                    "mkt_spread_home": mkt_sp,
                    "mkt_total": mkt_tot,
                    "spread_move": sp_mv,
                    "total_move": tot_mv,
                    "actual_home": int(round((act_t + act_m) / 2.0)),
                    "actual_away": int(round((act_t - act_m) / 2.0)),
                    "splits": splits,
                    "kp_disabled": kp_off,
                    "hs_disabled": hs_off,
                }
            )
        return out

    for mode in (
        "S1_preseason_corr_noise",
        "S2_fast_tempo_over_bias",
        "S3_blowout_14_22",
        "S4_sharp_contra_money",
        "S5_reverse_steam_trap",
        "S6_extreme_edge_trap",
        "S7_kp_hasla_degraded",
    ):
        s_games = make_stress_games(mode)
        s_recs = run_model_on_games(model, s_games)
        print_row(f"{mode} (All)", summarize(s_recs))
        if mode in ("S4_sharp_contra_money", "S5_reverse_steam_trap"):
            s_top6 = [r for r in s_recs if r.get("top6_eligible", True)]
            print_row(f"  -> {mode[:16]} Top 6", summarize(s_top6))

    # 3. Candidate Rule Ablations (tested directly against our 1,600-game walk-forward recs)
    print("\n=== 3. CANDIDATE ACCURACY & SELECTIVITY IMPROVEMENTS (ABLATIONS ON 1,600 GAMES) ===")
    print_row("Baseline Top 6 (Raw EV)", summarize(top6_recs))

    no_contra_top6 = select_top_n_per_day(
        [r for r in all_recs if "contra_sharp_money" not in r["tags"] and not any(t.startswith("reverse_steam=") for t in r["tags"])],
        6,
    )
    print_row("A. Block Contra+RevSteam T6", summarize(no_contra_top6))

    stricter_over_top6 = select_top_n_per_day(
        [r for r in all_recs if not (r["side_tag"] == "TOTAL_OVER" and (r["ev"] < 0.055 or r["edge_points"] < 2.1))],
        6,
    )
    print_row("B. Over EV>=5.5% & Edge>=2.1", summarize(stricter_over_top6))

    quality_ranked_top6 = select_top_n_per_day(all_recs, 6, score_fn=quality_rank_score)
    print_row("C. Quality-Weighted Top 6", summarize(quality_ranked_top6))

    combined = select_top_n_per_day(
        [
            r
            for r in all_recs
            if "contra_sharp_money" not in r["tags"]
            and not any(t.startswith("reverse_steam=") for t in r["tags"])
            and not (r["side_tag"] == "TOTAL_OVER" and (r["ev"] < 0.055 or r["edge_points"] < 2.1))
            and not (r["market"] == "SPREAD" and r["abs_spread"] < 6.0 and r["ev"] < 0.032)
        ],
        6,
        score_fn=quality_rank_score,
    )
    print_row("D. Combined Filters+QualRank", summarize(combined))

    # 4. 2-Leg Home Favorite (~7 pt spread: -4.5 to -9.5) Moneyline Parlay Backtest
    print("\n=== 4. 2-LEG HOME FAVORITE (~7 PT SPREAD: -4.5 TO -9.5) MONEYLINE PARLAY BACKTEST ===")
    import src.database as db_mod

    ml_rng = random.Random(20261117)

    def _ml_price_with_vig(mkt_spread_home: float) -> int:
        p_fair = 1.0 - model._normal_cdf(0.0, -float(mkt_spread_home), 10.8)
        vig_add = ml_rng.uniform(0.004, 0.022)
        p_book = min(0.88, max(0.55, p_fair + vig_add))
        return int(round(-100.0 * p_book / (1.0 - p_book)))

    def _dec_from_amer(a: int) -> float:
        return (1.0 + a / 100.0) if a > 0 else (1.0 + 100.0 / abs(a))

    def _amer_from_dec(d: float) -> int:
        x = d - 1.0
        return int(round(x * 100.0)) if x >= 1.0 else int(round(-100.0 / max(1e-6, x)))

    unfiltered_hf_by_day: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    gated_hf_by_day: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    curr_splits: Dict[str, Any] = {}
    orig_splits_fn2 = getattr(db_mod, "get_latest_action_splits", None)
    db_mod.get_latest_action_splits = lambda eid: curr_splits.get(eid, {})
    try:
        for g in season_games:
            sp = float(g["mkt_spread_home"])
            if not (-9.5 <= sp <= -4.5):
                continue
            eid = g["event_id"]
            curr_splits[eid] = g.get("splits") or {}
            ml_h = _ml_price_with_vig(sp)
            model.torvik_service.get_projection.return_value = {
                "margin": g["tv_margin"],
                "official_margin": g["tv_margin"],
                "total": g["tv_total"],
                "projected_score": "70-72",
                "lean": "Home",
            }
            model.torvik_service.get_matchup_team_stats.return_value = {
                "game_tempo": g["tempo"],
                "home": {"luck": 0.0, "continuity": g["continuity"], "record": "6-2"},
                "away": {"luck": 0.0, "continuity": g["continuity"], "record": "5-3"},
            }
            model.kenpom_client.calculate_kenpom_adjustment.return_value = {
                "spread_adj": g["kp_margin"],
                "neutral_margin": g["kp_margin"] - 3.2,
                "fair_margin": g["kp_margin"],
                "total_adj": 0.0,
                "fair_total": g["kp_total"],
                "expected_tempo": g["tempo"],
                "sos_spread_adj": 0.0,
                "four_factors_adj": 0.0,
                "exp_height_adj": 0.0,
            }
            model.kenpom_client.get_team_rating.return_value = {"adj_t": g["tempo"]}
            model.haslametrics_client.calculate_projection.return_value = {
                "available": True,
                "margin": g["hs_margin"],
                "total": g["hs_total"],
                "game_tempo": g["tempo"],
                "home": {"sos": 60, "mom": 0.0, "inc": 0.05},
                "away": {"sos": 70, "mom": 0.0, "inc": 0.05},
            }
            snap = {
                "spread_home": sp,
                "spread_price_home": -110,
                "total": g["mkt_total"],
                "total_over_price": -110,
                "moneyline_price_home": ml_h,
                "moneyline_price_away": 210,
                "book_spread": "Consensus",
                "book_total": "Consensus",
                "_best_spread_home": {"line_value": sp, "price": -110, "book": "DK"},
                "_best_spread_away": {"line_value": -sp, "price": -110, "book": "FD"},
                "_best_total_over": {"line_value": g["mkt_total"], "price": -110, "book": "DK"},
                "_best_total_under": {"line_value": g["mkt_total"], "price": -110, "book": "FD"},
                "_market_consensus": {
                    "open_spread_home": sp - g.get("spread_move", 0.0),
                    "current_spread_home": sp,
                    "spread_move_home": g.get("spread_move", 0.0),
                    "open_total": g["mkt_total"] - g.get("total_move", 0.0),
                    "current_total": g["mkt_total"],
                    "total_move": g.get("total_move", 0.0),
                },
            }
            ev_ctx = {
                "id": eid,
                "home_team": g["home_team"],
                "away_team": g["away_team"],
                "start_time": g["start_time"],
                "neutral_site": False,
                "action_splits": g.get("splits") or {},
            }
            res = model.analyze(eid, market_snapshot=snap, event_context=ev_ctx, persist=False)
            ctx = res.get("context") or {}
            fair_sp_home = float(ctx.get("fair_spread_home") if ctx.get("fair_spread_home") is not None else sp)
            wp_home = float(model._calibrate_win_prob(1.0 - model._normal_cdf(0.0, -fair_sp_home, 10.8)))
            ev_ml = wp_home * (_dec_from_amer(ml_h) - 1.0) - (1.0 - wp_home)
            leg_obj = {
                "event_id": eid,
                "ml_price": ml_h,
                "wp": wp_home,
                "ev": ev_ml,
                "edge_gap": sp - fair_sp_home,
                "home_won": g["actual_home"] > g["actual_away"],
            }
            unfiltered_hf_by_day[g["day"]].append(leg_obj)
            best_tags = ((res.get("recommendations") or [{}])[0] or {}).get("movement_tags") or []
            if model.is_sweet_spot_home_fav_ml_leg(
                spread_home=sp,
                fair_spread_home=fair_sp_home,
                win_prob_home=wp_home,
                ml_price_home=ml_h,
                ev_home=ev_ml,
                is_neutral=False,
                movement_tags=best_tags,
            ):
                gated_hf_by_day[g["day"]].append(leg_obj)
    finally:
        if orig_splits_fn2 is not None:
            db_mod.get_latest_action_splits = orig_splits_fn2

    def _score_parlays(by_day: Dict[str, List[Dict[str, Any]]], min_parlay_ev: Optional[float] = None):
        wins = losses = 0
        pl = 0.0
        odds_list: List[int] = []
        for _day, day_legs in sorted(by_day.items()):
            ranked = sorted(day_legs, key=lambda x: (x["ev"], x["wp"]), reverse=True)
            for idx in range(0, len(ranked) - 1, 2):
                leg_a, leg_b = ranked[idx], ranked[idx + 1]
                dec = _dec_from_amer(leg_a["ml_price"]) * _dec_from_amer(leg_b["ml_price"])
                amer = _amer_from_dec(dec)
                if not (-165 <= amer <= 140):
                    continue
                p_par = leg_a["wp"] * leg_b["wp"]
                ev_par = p_par * (dec - 1.0) - (1.0 - p_par)
                if min_parlay_ev is not None and ev_par < min_parlay_ev:
                    continue
                odds_list.append(amer)
                if leg_a["home_won"] and leg_b["home_won"]:
                    wins += 1
                    pl += (dec - 1.0)
                else:
                    losses += 1
                    pl -= 1.0
        n_p = wins + losses
        wr_p = (wins / n_p * 100.0) if n_p > 0 else 0.0
        roi_p = (pl / n_p * 100.0) if n_p > 0 else 0.0
        avg_o = int(round(sum(odds_list) / len(odds_list))) if odds_list else 0
        return wins, losses, n_p, wr_p, avg_o, pl, roi_p

    for lbl, bmap, min_pev in (
        ("Unfiltered -4.5..-9.5 ML", unfiltered_hf_by_day, None),
        ("Model-Gated +EV -7pt ML", gated_hf_by_day, 0.02),
    ):
        w_p, l_p, n_p, wr_p, avg_o, pl_p, roi_p = _score_parlays(bmap, min_pev)
        print(
            f"  {lbl:<28} |  {w_p:3d}-{l_p:<3d} ({n_p:3d}) | "
            f"WR {wr_p:5.1f}% | AvgOdds {avg_o:+d} | PL {pl_p:+7.2f}u | ROI {roi_p:+5.1f}%"
        )


if __name__ == "__main__":
    main()
