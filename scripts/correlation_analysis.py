import json
import os
import ssl
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.utils.ncaam_season import current_ncaam_season_end_year, current_ncaam_season_long

API_URL = "https://basement-bets.vercel.app/api/ncaam/history"
API_KEY = "Xavier"

_SEASON_YEAR = current_ncaam_season_end_year()
_SEASON_RANGE = current_ncaam_season_long()
OUTPUT_PATH = Path(f"data/correlation_summary_{_SEASON_RANGE.replace('-', '_')}.json")

SEASON_START = datetime(_SEASON_YEAR - 1, 10, 1)
SEASON_END = datetime(_SEASON_YEAR, 6, 30, 23, 59, 59)


def in_season(dt_str: str) -> bool:
    if not dt_str:
        return False
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return False
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return SEASON_START <= dt <= SEASON_END


def safe_json_load(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        return {}


def bool_outcome(outcome: str) -> bool:
    return (outcome or "").upper() == "WON"


def parse_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def categorize(entry):
    inputs = safe_json_load(entry.get("inputs_json", "{}"))
    market = inputs.get("market", {})

    total_line = parse_float(
        market.get("total")
        or market.get("line")
        or entry.get("total_line")
        or (market.get("spread_home") and market.get("spread_home") + market.get("total"))
    )
    torvik = entry.get("torvik", {})
    margin = parse_float(torvik.get("margin"))

    recs = entry.get("recommendations") or []
    has_spread = any(rec.get("market") == "SPREAD" for rec in recs)
    has_total = any(rec.get("market") == "TOTAL" for rec in recs)
    multi = len(recs) >= 2

    return {
        "total_line": total_line,
        "torvik_margin": margin,
        "has_spread": has_spread,
        "has_total": has_total,
        "multi_recs": multi,
        "outcome": entry.get("outcome"),
    }


def estimate_probability(entries, condition):
    subset = [e for e in entries if condition(e)]
    if not subset:
        return None
    wins = sum(1 for e in subset if bool_outcome(e["outcome"]))
    return {
        "count": len(subset),
        "win_rate": wins / len(subset),
        "win_count": wins,
    }


def fetch_history(limit=1000):
    params = f"?limit={limit}"
    req = urllib.request.Request(API_URL + params, headers={"X-BASEMENT-KEY": API_KEY})
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=30, context=context) as response:
        data = response.read()
    return json.loads(data)


def main():
    payload = fetch_history()

    filtered = [entry for entry in payload if in_season(entry.get("start_time"))]
    categorized = [categorize(entry) for entry in filtered]

    summary = {
        "total_analyzed": len(categorized),
        "season_range": _SEASON_RANGE,
        "metrics": {},
    }

    metrics = {
        "fast_total": lambda e: e["total_line"] is not None and e["total_line"] >= 160,
        "medium_total": lambda e: e["total_line"] is not None and 146 <= e["total_line"] < 160,
        "slow_total": lambda e: e["total_line"] is not None and e["total_line"] < 146,
        "high_margin": lambda e: e["torvik_margin"] is not None and abs(e["torvik_margin"]) >= 6,
        "positive_margin": lambda e: e["torvik_margin"] is not None and e["torvik_margin"] >= 5,
        "negative_margin": lambda e: e["torvik_margin"] is not None and e["torvik_margin"] <= -5,
        "spread_and_total": lambda e: e["has_spread"] and e["has_total"],
        "multi_leg": lambda e: e["multi_recs"],
        "spread_only": lambda e: e["has_spread"] and not e["has_total"],
    }

    for name, cond in metrics.items():
        summary["metrics"][name] = estimate_probability(categorized, cond)

    summary["metrics"]["fast_total_and_multi"] = estimate_probability(
        categorized,
        lambda e: (e["total_line"] is not None and e["total_line"] >= 160) and e["multi_recs"],
    )

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w") as fp:
        json.dump(summary, fp, indent=2)

    print("Correlation summary written to", OUTPUT_PATH)


if __name__ == "__main__":
    main()
