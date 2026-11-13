"""Pre-game injury & availability service for NCAAM.

Combines:
1. Live Rotowire College Basketball injury JSON feed (team, player, position, injury, status).
2. Stored DB rows from `action_injuries` (populated by ingest_enrichment_live.py from Rotowire + ESPN).

Provides conservative uncertainty multipliers (sigma inflation) and structured
plain-English injury summaries for the model and UI without blocking on missing feeds.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

from src.database import _exec, get_admin_db_connection, get_db_connection, get_latest_action_injuries
from src.utils.naming import standardize_team_name
from src.utils.team_matcher import TeamMatcher


ROTOWIRE_INJURY_URL = "https://www.rotowire.com/cbasketball/tables/injury-report.php?team=ALL&pos=ALL"

ROTOWIRE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.rotowire.com/cbasketball/injury-report.php",
    "Accept": "application/json, text/plain, */*",
}


def _safe_num(val: Any) -> Optional[float]:
    """Safely coerce numeric player metrics to float, returning None if missing."""
    if val is None or val == "":
        return None
    try:
        num = float(val)
        return num if num == num else None
    except Exception:
        return None


def classify_injury_severity(status: Optional[str]) -> str:
    """Classify injury status string into OUT, DOUBTFUL, QUESTIONABLE, or INFO."""
    s = str(status or "").strip().lower()
    if any(tok in s for tok in ("out", "suspended", "redshirt", "season", "inactive")):
        return "OUT"
    if "doubtful" in s:
        return "DOUBTFUL"
    if any(tok in s for tok in ("questionable", "gtd", "game time", "day-to-day", "probable")):
        return "QUESTIONABLE"
    return "INFO"


def _team_names_match(matcher: TeamMatcher, candidate: str, canonical: str) -> bool:
    if not candidate or not canonical:
        return False
    c_std = matcher.normalize(standardize_team_name(candidate))
    t_std = matcher.normalize(standardize_team_name(canonical))
    if not c_std or not t_std:
        return False
    if c_std == t_std:
        return True
    c_tokens = c_std.split()
    t_tokens = t_std.split()
    if len(c_tokens) <= len(t_tokens) and t_tokens[: len(c_tokens)] == c_tokens:
        if len(t_tokens) > len(c_tokens) and t_tokens[len(c_tokens)] in TeamMatcher._DISAMBIGUATING_NEXT_WORDS:
            return False
        return True
    if len(t_tokens) <= len(c_tokens) and c_tokens[: len(t_tokens)] == t_tokens:
        if len(c_tokens) > len(t_tokens) and c_tokens[len(t_tokens)] in TeamMatcher._DISAMBIGUATING_NEXT_WORDS:
            return False
        return True
    return False


class InjuryService:
    """Fetch, persist, and evaluate pre-game college basketball injuries."""

    def __init__(self) -> None:
        self.matcher = TeamMatcher()
        self._live_feed_cache: Optional[List[Dict[str, Any]]] = None

    def fetch_rotowire_injuries(self, timeout: int = 12) -> List[Dict[str, Any]]:
        """Fetch live Rotowire NCAAM injury table JSON."""
        if os.environ.get("BASEMENT_SKIP_NEWS") == "1" or os.environ.get("BACKTEST_NO_NETWORK") == "1":
            return []
        try:
            resp = requests.get(ROTOWIRE_INJURY_URL, headers=ROTOWIRE_HEADERS, timeout=timeout)
            resp.raise_for_status()
            rows = resp.json()
            if not isinstance(rows, list):
                return []
            cleaned = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                player = (r.get("player") or "").strip()
                team = (r.get("team") or "").strip()
                if not player or not team:
                    continue
                cleaned.append(
                    {
                        "player": player,
                        "team": team,
                        "position": (r.get("position") or "").strip(),
                        "injury": (r.get("injury") or "").strip(),
                        "status": (r.get("status") or "").strip(),
                        "severity": classify_injury_severity(r.get("status")),
                        "source": "Rotowire",
                    }
                )
            return cleaned
        except Exception as e:
            print(f"[Injuries] Rotowire fetch failed: {e}")
            return []

    def sync_injuries_for_dates(
        self,
        dates_iso: Optional[List[str]] = None,
        extra_espn_injuries: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """Persist Rotowire + optional ESPN injuries into `action_injuries` linked to DB events."""
        if not dates_iso:
            now_et = datetime.now(ZoneInfo("America/New_York"))
            dates_iso = [
                now_et.strftime("%Y-%m-%d"),
                (now_et + timedelta(days=1)).strftime("%Y-%m-%d"),
            ]

        rotowire_rows = self.fetch_rotowire_injuries()
        events = []
        with get_db_connection() as conn:
            ev_rows = _exec(
                conn,
                """
                SELECT id, home_team, away_team
                FROM events
                WHERE league = 'NCAAM'
                  AND DATE(start_time AT TIME ZONE 'America/New_York')::text = ANY(%s)
                """,
                (dates_iso,),
            ).fetchall()
            events = [dict(r) for r in ev_rows] if ev_rows else []

        if not events:
            return 0

        to_insert: List[Dict[str, Any]] = []
        for inj in rotowire_rows:
            t_name = inj["team"]
            for ev in events:
                matched_side_team = None
                if _team_names_match(self.matcher, t_name, ev["home_team"]):
                    matched_side_team = ev["home_team"]
                elif _team_names_match(self.matcher, t_name, ev["away_team"]):
                    matched_side_team = ev["away_team"]
                if matched_side_team:
                    to_insert.append(
                        {
                            "event_id": ev["id"],
                            "team_id": matched_side_team,
                            "player_name": inj["player"],
                            "status": inj["status"],
                            "description": f"{inj['position']} — {inj['injury']} ({inj['source']})".strip(" —"),
                            "source_url": ROTOWIRE_INJURY_URL,
                        }
                    )

        for espn_item in extra_espn_injuries or []:
            for eid in espn_item.get("db_event_ids") or []:
                to_insert.append(
                    {
                        "event_id": eid,
                        "team_id": espn_item.get("team"),
                        "player_name": espn_item.get("player"),
                        "status": espn_item.get("status"),
                        "description": f"{espn_item.get('position', '')} — {espn_item.get('injury', '')} (ESPN)".strip(" —"),
                        "source_url": "https://site.api.espn.com/",
                    }
                )

        if not to_insert:
            return 0

        saved = 0
        day_bucket = datetime.now(timezone.utc).strftime("%Y%m%d")
        sql = """
        INSERT INTO action_injuries(id, event_id, team_id, player_name, status, description, reported_at, source_url, fingerprint)
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s)
        ON CONFLICT (fingerprint) DO UPDATE SET
            status = EXCLUDED.status,
            description = EXCLUDED.description,
            reported_at = NOW();
        """
        with get_admin_db_connection() as conn:
            for item in to_insert:
                fp_raw = f"{item['event_id']}:{item.get('team_id')}:{item['player_name']}:{day_bucket}"
                fp = hashlib.md5(fp_raw.encode("utf-8")).hexdigest()
                _exec(
                    conn,
                    sql,
                    (
                        str(uuid.uuid4()),
                        item["event_id"],
                        item.get("team_id"),
                        item["player_name"],
                        item.get("status"),
                        item.get("description"),
                        item.get("source_url"),
                        fp,
                    ),
                )
                saved += 1
            conn.commit()
        return saved

    @staticmethod
    def _norm_player(name: Any) -> str:
        """Normalize a player name for tolerant roster matching."""
        return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())

    @staticmethod
    def _estimate_player_point_impact(
        player_name: Any,
        kp_players: Optional[List[Dict[str, Any]]] = None,
        desc: str = "",
    ) -> float:
        """
        Estimate single-player point value above bench replacement for NCAAM.

        Uses KenPom player metrics (minutes %, usage, PPG) when available, falling
        back to conservative positional/role defaults when roster splits are absent.
        """
        norm_target = InjuryService._norm_player(player_name)
        matched_metrics: Optional[Dict[str, Any]] = None
        if norm_target and kp_players:
            for row in kp_players:
                cand_name = row.get("player_name") or row.get("name") or ""
                cand_norm = InjuryService._norm_player(cand_name)
                if not cand_norm:
                    continue
                if cand_norm == norm_target or (
                    len(norm_target) >= 5 and (norm_target in cand_norm or cand_norm in norm_target)
                ):
                    m = row.get("metrics") if isinstance(row.get("metrics"), dict) else row
                    matched_metrics = m if isinstance(m, dict) else None
                    break

        if matched_metrics:
            min_pct = _safe_num(matched_metrics.get("min_pct") or matched_metrics.get("min") or matched_metrics.get("mpg"))
            usg = _safe_num(matched_metrics.get("usg") or matched_metrics.get("usg_pct"))
            ppg = _safe_num(matched_metrics.get("ppg") or matched_metrics.get("pts"))
            ortg = _safe_num(matched_metrics.get("ortg"))

            # If min_pct looks like MPG (0..40) convert roughly to share (0..100)
            if min_pct is not None and 0 < min_pct <= 40.0 and matched_metrics.get("min_pct") is None:
                min_share = min(100.0, (min_pct / 40.0) * 100.0)
            else:
                min_share = min_pct

            base = 0.0
            if min_share is not None:
                # Bench replacement covers ~65% of a low-usage minute; stars (>65% min, >22% usg) drive 1.5-3.0 pts.
                base = max(0.0, (min_share - 20.0) / 30.0) * 1.15
                if usg is not None and usg > 18.0:
                    base *= 1.0 + min(0.8, (usg - 18.0) / 20.0)
                if ortg is not None and ortg >= 112.0:
                    base *= 1.1
            elif ppg is not None:
                base = max(0.25, (ppg - 3.0) * 0.16)

            if base > 0:
                return round(max(0.2, min(3.0, base)), 2)

        desc_low = str(desc or "").lower()
        if any(tok in desc_low for tok in ("star", "leading", "starter", "pg", "point guard")):
            return 1.1
        if any(tok in desc_low for tok in ("redshirt", "walk-on", "reserve")):
            return 0.15
        return 0.65

    def evaluate_injuries(
        self,
        injuries: List[Dict[str, Any]],
        home_team: str,
        away_team: str,
        home_players: Optional[List[Dict[str, Any]]] = None,
        away_players: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Compute uncertainty multiplier, spread/total point impact, and UI summary."""
        home_out = 0
        away_out = 0
        gtd_count = 0
        home_impact_pts = 0.0
        away_impact_pts = 0.0
        impact_players: List[Dict[str, Any]] = []
        cleaned: List[Dict[str, Any]] = []

        for item in injuries or []:
            player = item.get("player_name") or item.get("player")
            status = item.get("status") or "Questionable"
            team_ref = item.get("team_id") or item.get("team") or ""
            desc = item.get("description") or item.get("injury") or ""
            sev = classify_injury_severity(status)

            side = None
            if _team_names_match(self.matcher, team_ref, home_team):
                side = "home"
            elif _team_names_match(self.matcher, team_ref, away_team):
                side = "away"

            sev_weight = 0.0
            if sev == "OUT":
                sev_weight = 1.0
                if side == "home":
                    home_out += 1
                elif side == "away":
                    away_out += 1
            elif sev == "DOUBTFUL":
                sev_weight = 0.75
                if side == "home":
                    home_out += 1
                elif side == "away":
                    away_out += 1
            elif sev == "QUESTIONABLE":
                sev_weight = 0.25
                gtd_count += 1

            est_pts = 0.0
            if sev_weight > 0 and side in ("home", "away"):
                roster = home_players if side == "home" else away_players
                raw_pts = self._estimate_player_point_impact(player, roster, desc=desc)
                est_pts = round(raw_pts * sev_weight, 2)
                if side == "home":
                    home_impact_pts += est_pts
                else:
                    away_impact_pts += est_pts
                if est_pts >= 0.25:
                    impact_players.append(
                        {
                            "player": player,
                            "side": side,
                            "status": status,
                            "severity": sev,
                            "est_pts": est_pts,
                        }
                    )

            cleaned.append(
                {
                    "player": player,
                    "team": team_ref,
                    "side": side,
                    "status": status,
                    "severity": sev,
                    "detail": desc,
                    "est_pts": est_pts if est_pts > 0 else None,
                }
            )

        home_impact_pts = round(min(4.5, home_impact_pts), 2)
        away_impact_pts = round(min(4.5, away_impact_pts), 2)
        # Home spread sign convention: negative = home favored. Missing home points push spread +; away points push -.
        spread_adj = round(max(-3.0, min(3.0, home_impact_pts - away_impact_pts)), 2)
        # Missing primary scorers slightly depress scoring expectation (bounded; bench still fills possessions).
        total_adj = round(max(-3.0, min(0.0, -0.35 * (home_impact_pts + away_impact_pts))), 2)

        # Conservative uncertainty inflation when active players are Out/Doubtful/GTD
        out_total = home_out + away_out
        sigma_mult = 1.0
        if out_total >= 2:
            sigma_mult = 1.07
        elif out_total == 1:
            sigma_mult = 1.04
        elif gtd_count >= 1:
            sigma_mult = 1.02

        return {
            "has_injuries": bool(cleaned),
            "injuries": cleaned,
            "home_out_count": home_out,
            "away_out_count": away_out,
            "gtd_count": gtd_count,
            "sigma_mult": sigma_mult,
            "home_impact_pts": home_impact_pts,
            "away_impact_pts": away_impact_pts,
            "spread_adj": spread_adj,
            "total_adj": total_adj,
            "impact_players": impact_players,
        }

    def get_matchup_injuries(
        self,
        event_id: str,
        home_team: str,
        away_team: str,
        allow_live_fallback: bool = False,
        home_players: Optional[List[Dict[str, Any]]] = None,
        away_players: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Load injuries for an event from DB `action_injuries`, with optional Rotowire fallback."""
        rows = []
        if os.environ.get("REQUIRE_DATABASE") != "0":
            rows = get_latest_action_injuries(event_id)

        if not rows and allow_live_fallback:
            if self._live_feed_cache is None:
                self._live_feed_cache = self.fetch_rotowire_injuries()
            for inj in self._live_feed_cache or []:
                if _team_names_match(self.matcher, inj["team"], home_team) or _team_names_match(
                    self.matcher, inj["team"], away_team
                ):
                    rows.append(inj)

        return self.evaluate_injuries(
            rows,
            home_team=home_team,
            away_team=away_team,
            home_players=home_players,
            away_players=away_players,
        )
