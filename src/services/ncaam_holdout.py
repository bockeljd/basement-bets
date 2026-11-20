"""Score frozen, pregame Top 6 snapshots on the same settled rows for all baselines."""
from collections import Counter, defaultdict
from datetime import datetime
import math

from src.database import _exec, get_db_connection


def _implied(price):
    return 100 / (100 + price) if price > 0 else -price / (100 - price)


def score_published(rows):
    coverage = Counter(published=0, scored=0)
    losses = defaultdict(lambda: defaultdict(list))
    for row in rows:
        coverage["published"] += 1
        snap = row["snapshot"] or {}
        if row["outcome"] not in ("WON", "LOST"):
            coverage["pending_push_or_void"] += 1
            continue
        if row["published_at"] >= row["start_time"]:
            coverage["late_publication"] += 1
            continue
        calibration = snap.get("calibration") or {}
        fitted = calibration.get("fit_completed_at")
        if calibration.get("source") != "raw_fallback" and (
            not fitted or datetime.fromisoformat(fitted) > row["published_at"]
        ):
            coverage["unverified_calibration_date"] += 1
            continue
        if any(snap.get(k) is None for k in ("raw_win_prob", "win_prob", "opposite_price")):
            coverage["incomplete_probability_or_quote"] += 1
            continue
        if not row["bet_price"] or not snap["opposite_price"]:
            coverage["invalid_price"] += 1
            continue
        price = _implied(row["bet_price"])
        market = price / (price + _implied(snap["opposite_price"]))
        probabilities = {"raw": snap["raw_win_prob"], "calibrated": snap["win_prob"], "market": market}
        if not all(0 < p < 1 for p in probabilities.values()):
            coverage["invalid_probability"] += 1
            continue
        coverage["scored"] += 1
        y = int(row["outcome"] == "WON")
        for method, p in probabilities.items():
            losses[row["market_type"]][method].append(((p-y)**2, -math.log(p if y else 1-p)))
    markets = {}
    for market, methods in losses.items():
        markets[market] = {}
        for name, values in methods.items():
            n = len(values)
            markets[market][name] = {"n": n, "brier": sum(x for x,_ in values)/n,
                                     "log_loss": sum(x for _,x in values)/n}
    return {"coverage": dict(coverage), "markets": markets}


def published_holdout(days):
    with get_db_connection() as conn:
        rows = _exec(conn, """SELECT i.market_type,i.bet_price,to_jsonb(i)->'snapshot' AS snapshot,
                m.outcome,e.start_time,i.created_at AS published_at
            FROM recommended_slates s JOIN recommended_slate_items i ON i.slate_id=s.id
            JOIN events e ON e.id=i.event_id LEFT JOIN model_predictions m ON m.id=i.prediction_id
            WHERE s.league='NCAAM' AND s.source='cached' AND s.id='NCAAM:'||s.date_et||':cached'
              AND i.rank BETWEEN 1 AND 6 AND s.date_et >=
              ((NOW() AT TIME ZONE 'America/New_York')::date - %s + 1)::text
            ORDER BY s.created_at,i.rank""", (days,)).fetchall()
    return score_published(rows)
