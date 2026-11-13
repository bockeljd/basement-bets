"""Pure-Python empirical correlation engine for NCAAM matchup archetypes.

Avoids importing pandas/numpy so serverless deployments (Vercel) stay under
bundle limits while still accepting pandas DataFrames when callers pass them.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from src.database import _exec, get_db_connection


def _to_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    """Coerce Postgres Decimal, numeric strings, or NaN safely to float."""
    if val is None or val == "":
        return default
    try:
        num = float(val)
        return default if math.isnan(num) or math.isinf(num) else num
    except Exception:
        return default


def _as_rows(data: Any) -> Tuple[List[Dict[str, Any]], Any]:
    """Normalize DataFrame or list-of-dicts into mutable row dicts; returns (rows, df_cls)."""
    if data is None:
        return [], None
    if hasattr(data, "to_dict") and callable(data.to_dict):
        return [dict(r) for r in data.to_dict("records")], type(data)
    return [dict(r) for r in list(data)], None


def _tercile_thresholds(values: List[float]) -> Optional[Tuple[float, float]]:
    """Compute (q33, q67) empirical breakpoints when values span at least 3 buckets."""
    if len(values) < 3 or len(set(values)) < 3:
        return None
    s = sorted(values)
    q1 = s[len(s) // 3]
    q2 = s[(2 * len(s)) // 3]
    if q1 == q2:
        return None
    return q1, q2


class NCAAMCorrelationEngine:
    """
    Computes empirical joint probabilities and correlation metrics (Lift, Phi)
    for NCAAM betting markets, conditional on matchup archetypes.
    """

    from src.utils.ncaam_season import ncaam_season_date_bounds

    SEASON_START, SEASON_END = ncaam_season_date_bounds()
    del ncaam_season_date_bounds
    MIN_SAMPLE_SIZE = 40

    def fetch_season_data(self) -> List[Dict[str, Any]]:
        """
        Fetch completed games, closing spread/total snapshots, and team metrics
        for the target NCAAM season in pure Python.
        """
        query = """
        WITH game_metrics AS (
            SELECT
                e.id,
                e.start_time,
                e.home_team,
                e.away_team,
                gr.home_score,
                gr.away_score,
                (
                    SELECT line_value
                    FROM odds_snapshots os
                    WHERE os.event_id = e.id
                      AND os.market_type = 'SPREAD'
                      AND os.side = 'HOME'
                      AND os.captured_at <= (e.start_time AT TIME ZONE 'UTC')
                    ORDER BY os.captured_at DESC LIMIT 1
                ) as close_spread,
                (
                    SELECT line_value
                    FROM odds_snapshots os
                    WHERE os.event_id = e.id
                      AND os.market_type = 'TOTAL'
                      AND os.side = 'OVER'
                      AND os.captured_at <= (e.start_time AT TIME ZONE 'UTC')
                    ORDER BY os.captured_at DESC LIMIT 1
                ) as close_total,
                mh.adj_tempo as home_pace,
                (mh.adj_off - mh.adj_def) as home_net_eff,
                ma.adj_tempo as away_pace,
                (ma.adj_off - ma.adj_def) as away_net_eff
            FROM events e
            JOIN game_results gr ON e.id = gr.event_id
            LEFT JOIN LATERAL (
                SELECT adj_tempo, adj_off, adj_def
                FROM bt_team_metrics_daily
                WHERE date = (SELECT MAX(date) FROM bt_team_metrics_daily)
                  AND LENGTH(TRIM(team_text)) > 0
                  AND STRPOS(LOWER(e.home_team), LOWER(team_text)) > 0
                ORDER BY LENGTH(team_text) DESC
                LIMIT 1
            ) mh ON TRUE
            LEFT JOIN LATERAL (
                SELECT adj_tempo, adj_off, adj_def
                FROM bt_team_metrics_daily
                WHERE date = (SELECT MAX(date) FROM bt_team_metrics_daily)
                  AND LENGTH(TRIM(team_text)) > 0
                  AND STRPOS(LOWER(e.away_team), LOWER(team_text)) > 0
                ORDER BY LENGTH(team_text) DESC
                LIMIT 1
            ) ma ON TRUE
            WHERE e.start_time >= %(start)s
              AND e.start_time < %(end)s
              AND (e.league = 'NCAAM' OR e.league = 'ncaab')
              AND gr.final = TRUE
        )
        SELECT * FROM game_metrics
        WHERE close_spread IS NOT NULL
          AND close_total IS NOT NULL
        """

        with get_db_connection() as conn:
            raw_rows = _exec(
                conn,
                query,
                {"start": self.SEASON_START, "end": self.SEASON_END},
            ).fetchall()

        results: List[Dict[str, Any]] = []
        for raw in raw_rows:
            row = dict(raw)
            hs = _to_float(row.get("home_score"))
            aws = _to_float(row.get("away_score"))
            if hs is None or aws is None:
                continue
            row["margin"] = hs - aws
            row["total_score"] = hs + aws
            results.append(row)
        return results

    def build_archetype_bins(self, data: Any) -> Any:
        """
        Enrich rows with 'pace_index', 'eff_index', 'spread_bucket', 'pace_bin', 'eff_bin'.
        Accepts list[dict] or pandas.DataFrame and preserves the input container type.
        """
        rows, df_cls = _as_rows(data)
        if not rows:
            return data

        pace_vals: List[float] = []
        eff_vals: List[float] = []
        for row in rows:
            hp = _to_float(row.get("home_pace"), 68.0)
            ap = _to_float(row.get("away_pace"), 68.0)
            hne = _to_float(row.get("home_net_eff"), 0.0)
            ane = _to_float(row.get("away_net_eff"), 0.0)
            cs = _to_float(row.get("close_spread"))

            pace_idx = (hp + ap) / 2.0
            eff_idx = hne + ane
            row["home_pace"] = hp
            row["away_pace"] = ap
            row["home_net_eff"] = hne
            row["away_net_eff"] = ane
            row["close_spread"] = cs
            row["pace_index"] = pace_idx
            row["eff_index"] = eff_idx
            pace_vals.append(pace_idx)
            eff_vals.append(eff_idx)

            if cs is None:
                row["abs_spread"] = None
                row["spread_bucket"] = "Medium"
            else:
                abs_sp = abs(cs)
                row["abs_spread"] = abs_sp
                if abs_sp <= 3.5:
                    row["spread_bucket"] = "Close"
                elif abs_sp <= 9.5:
                    row["spread_bucket"] = "Medium"
                else:
                    row["spread_bucket"] = "Big"

        pace_thresh = _tercile_thresholds(pace_vals)
        eff_thresh = _tercile_thresholds(eff_vals)

        for row in rows:
            if pace_thresh is None:
                row["pace_bin"] = "Avg"
            else:
                q1, q2 = pace_thresh
                p = row["pace_index"]
                row["pace_bin"] = "Slow" if p <= q1 else ("Avg" if p <= q2 else "Fast")

            if eff_thresh is None:
                row["eff_bin"] = "Avg"
            else:
                q1, q2 = eff_thresh
                e = row["eff_index"]
                row["eff_bin"] = "Low" if e <= q1 else ("Avg" if e <= q2 else "High")

        return df_cls(rows) if df_cls is not None else rows

    def compute_metrics(self, data: Any) -> Dict[str, Any]:
        """Aggregate joint probabilities and Lift per archetype without numpy/pandas."""
        rows, _ = _as_rows(data)
        if not rows:
            return {}

        groups: Dict[Tuple[str, str, str], List[Dict[str, bool]]] = {}
        for row in rows:
            margin = _to_float(row.get("margin"))
            close_spread = _to_float(row.get("close_spread"))
            total_score = _to_float(row.get("total_score"))
            close_total = _to_float(row.get("close_total"))
            if None in (margin, close_spread, total_score, close_total):
                continue

            key_tuple = (
                str(row.get("pace_bin") or "Avg"),
                str(row.get("eff_bin") or "Avg"),
                str(row.get("spread_bucket") or "Medium"),
            )
            groups.setdefault(key_tuple, []).append({
                "home_cover": (margin + close_spread) > 0,
                "away_cover": (margin + close_spread) < 0,
                "total_over": total_score > close_total,
                "total_under": total_score < close_total,
            })

        results: Dict[str, Any] = {}
        for (pace, eff, spread), group in groups.items():
            key = f"{pace}_{eff}_{spread}"
            n = len(group)
            if n < self.MIN_SAMPLE_SIZE:
                results[key] = {"status": "insufficient_data", "n": n}
                continue
            results[key] = {
                "status": "valid",
                "n": n,
                "pairs": {
                    "over_home_cover": self._calc_pair_stats(group, "total_over", "home_cover"),
                },
            }
        return results

    def _calc_pair_stats(self, rows: Any, leg_a: str, leg_b: str) -> Dict[str, float]:
        """Calculate marginal probabilities, conditional probability, and empirical Lift."""
        seq, _ = _as_rows(rows) if not isinstance(rows, list) else (rows, None)
        n = len(seq)
        if n == 0:
            return {"p_a": 0.0, "p_b": 0.0, "p_joint": 0.0, "p_b_given_a": 0.0, "lift": 1.0}

        a_hits = sum(1 for r in seq if bool(r.get(leg_a)))
        b_hits = sum(1 for r in seq if bool(r.get(leg_b)))
        joint_hits = sum(1 for r in seq if bool(r.get(leg_a)) and bool(r.get(leg_b)))

        p_a = a_hits / n
        p_b = b_hits / n
        p_joint = joint_hits / n
        p_b_given_a = (joint_hits / a_hits) if a_hits > 0 else 0.0
        expected_joint = p_a * p_b
        lift = (p_joint / expected_joint) if expected_joint > 0 else 1.0

        return {
            "p_a": round(p_a, 3),
            "p_b": round(p_b, 3),
            "p_joint": round(p_joint, 3),
            "p_b_given_a": round(p_b_given_a, 3),
            "lift": round(lift, 3),
        }
