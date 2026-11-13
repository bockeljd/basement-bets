"""Helpers for historical score backfill, MLB/NRFI resolution, and parlay grading."""

from __future__ import annotations

import datetime as dt
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.utils.naming import standardize_team_name

ESPN_LEAGUE_PATHS: Dict[str, str] = {
    "NFL": "football/nfl",
    "NCAAM": "basketball/mens-college-basketball",
    "NBA": "basketball/nba",
    "EPL": "soccer/eng.1",
    "MLB": "baseball/mlb",
}

_MLB_TEAM_ALIASES: Dict[str, str] = {
    "athletics": "athletics",
    "oakland athletics": "athletics",
    "sacramento athletics": "athletics",
    "oakland as": "athletics",
    "as": "athletics",
    "cleveland indians": "cleveland guardians",
    "cleveland guardians": "cleveland guardians",
    "st louis cardinals": "st louis cardinals",
    "saint louis cardinals": "st louis cardinals",
    "la dodgers": "los angeles dodgers",
    "los angeles dodgers": "los angeles dodgers",
    "la angels": "los angeles angels",
    "los angeles angels": "los angeles angels",
    "los angeles angels of anaheim": "los angeles angels",
    "ny yankees": "new york yankees",
    "new york yankees": "new york yankees",
    "ny mets": "new york mets",
    "new york mets": "new york mets",
    "chi cubs": "chicago cubs",
    "chicago cubs": "chicago cubs",
    "chi white sox": "chicago white sox",
    "chicago white sox": "chicago white sox",
    "az diamondbacks": "arizona diamondbacks",
    "arizona diamondbacks": "arizona diamondbacks",
    "d backs": "arizona diamondbacks",
    "tampa bay devil rays": "tampa bay rays",
    "tampa bay rays": "tampa bay rays",
    "miami marlins": "miami marlins",
    "florida marlins": "miami marlins",
}

_FINAL_MLB_STATUSES = ("final", "completed early", "game over")
_NON_FINAL_MLB_STATUSES = ("postponed", "cancelled", "canceled", "suspended", "delayed", "scheduled", "pre-game")
_NON_BET_PICKS = ("", "NONE", "NO BET", "PASS")


def normalize_team_key(name: Optional[str]) -> str:
    """Normalize a team string for resilient matching."""
    text = str(name or "").lower().strip()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_mlb_team(name: Optional[str]) -> str:
    """Normalize an MLB team name across Action Network, ESPN, and MLB Stats API."""
    key = normalize_team_key(name)
    return _MLB_TEAM_ALIASES.get(key, key)


def match_team_names(cand_a: Optional[str], cand_b: Optional[str], is_mlb: bool = False) -> bool:
    """Return True if two team names refer to the same team."""
    if not cand_a or not cand_b:
        return False
    if is_mlb:
        na, nb = normalize_mlb_team(cand_a), normalize_mlb_team(cand_b)
        if not na or not nb:
            return False
        if na == nb:
            return True
        return na in nb or nb in na

    ka, kb = normalize_team_key(cand_a), normalize_team_key(cand_b)
    if ka and kb and ka == kb:
        return True
    sa = normalize_team_key(standardize_team_name(str(cand_a)))
    sb = normalize_team_key(standardize_team_name(str(cand_b)))
    if sa and sb and sa == sb:
        return True
    return False


def _specificity_score(pick_norm: str, target_norm: str) -> int:
    """Higher score means a closer/more specific match between pick and target."""
    if not pick_norm or not target_norm:
        return 0
    if pick_norm == target_norm:
        return 1000 + len(target_norm)
    if target_norm in pick_norm:
        return 500 + len(target_norm)
    if pick_norm in target_norm:
        return 250 + len(pick_norm)
    p_tokens = set(pick_norm.split())
    t_tokens = set(target_norm.split())
    overlap = len(p_tokens & t_tokens)
    return overlap * 20 if overlap >= 2 or (overlap == 1 and len(t_tokens) == 1) else 0


def resolve_team_side(
    pick: Optional[str],
    home_team: Optional[str],
    away_team: Optional[str],
    is_mlb: bool = False,
) -> Optional[str]:
    """Resolve a pick label ('HOME', 'AWAY', or team name string) to 'HOME' or 'AWAY'."""
    raw = str(pick or "").strip()
    if not raw:
        return None
    upper = raw.upper()
    if upper == "HOME":
        return "HOME"
    if upper == "AWAY":
        return "AWAY"

    if is_mlb:
        p_norm = normalize_mlb_team(raw)
        h_norm = normalize_mlb_team(home_team)
        a_norm = normalize_mlb_team(away_team)
    else:
        p_norm = normalize_team_key(standardize_team_name(raw))
        h_norm = normalize_team_key(standardize_team_name(str(home_team or "")))
        a_norm = normalize_team_key(standardize_team_name(str(away_team or "")))

    h_score = max(
        _specificity_score(p_norm, h_norm),
        _specificity_score(normalize_team_key(raw), normalize_team_key(home_team)),
    )
    a_score = max(
        _specificity_score(p_norm, a_norm),
        _specificity_score(normalize_team_key(raw), normalize_team_key(away_team)),
    )

    if h_score > a_score and h_score > 0:
        return "HOME"
    if a_score > h_score and a_score > 0:
        return "AWAY"
    return None


def parse_nrfi_yrfi_pick(pick: Optional[str], selection: Optional[str] = None) -> Optional[str]:
    """Parse whether a first-inning pick represents NRFI or YRFI."""
    for candidate in (pick, selection):
        text = str(candidate or "").upper().strip()
        if not text:
            continue
        if re.search(r"\bYRFI\b", text) or "YES RUN FIRST" in text:
            return "YRFI"
        if re.search(r"\bNRFI\b", text) or "NO RUN FIRST" in text:
            return "NRFI"
    return None


def is_mlb_status_final(status: Optional[str]) -> bool:
    """Return True if an MLB Stats API game status represents a final score."""
    st = str(status or "").lower().strip()
    if not st:
        return False
    if any(bad in st for bad in _NON_FINAL_MLB_STATUSES):
        return False
    return any(ok in st for ok in _FINAL_MLB_STATUSES)


def extract_first_inning_totals(schedule_game: Optional[dict]) -> Optional[Tuple[int, int]]:
    """Extract (away_1st_runs, home_1st_runs) from an MLB schedule linescore when available."""
    if not isinstance(schedule_game, dict):
        return None
    status = str(schedule_game.get("status") or "").lower()
    if any(bad in status for bad in ("postponed", "cancelled", "canceled", "scheduled", "pre-game")):
        return None

    ls = schedule_game.get("linescore") or {}
    innings = ls.get("innings") or []
    if not innings:
        return None

    inn1 = next((i for i in innings if i.get("num") == 1), innings[0])
    away_runs = (inn1.get("away") or {}).get("runs")
    home_runs = (inn1.get("home") or {}).get("runs")
    if away_runs is None or home_runs is None:
        return None

    # Ensure both halves of inning 1 have finished.
    current_inning = ls.get("currentInning")
    if not is_mlb_status_final(status):
        try:
            cur_num = int(current_inning or 0)
        except Exception:
            cur_num = 0
        if cur_num < 2:
            return None

    return int(away_runs), int(home_runs)


def grade_nrfi_yrfi(
    pick: Optional[str],
    away_1st: int,
    home_1st: int,
    selection: Optional[str] = None,
) -> str:
    """Grade an NRFI or YRFI bet from 1st-inning run totals."""
    kind = parse_nrfi_yrfi_pick(pick, selection=selection)
    if not kind:
        return "VOID"
    total_1st = int(away_1st) + int(home_1st)
    if kind == "NRFI":
        return "WON" if total_1st == 0 else "LOST"
    return "WON" if total_1st >= 1 else "LOST"


def _parse_dt_utc(value: Any) -> Optional[dt.datetime]:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    try:
        s = str(value).strip().replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(s)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def match_mlb_schedule_game(
    schedule_games: List[dict],
    away_team: Optional[str],
    home_team: Optional[str],
    start_time: Any = None,
    *,
    require_final: bool = True,
) -> Optional[dict]:
    """Match a DB event by normalized (away_team, home_team) and closest start_time."""
    target_away = normalize_mlb_team(away_team)
    target_home = normalize_mlb_team(home_team)
    if not target_away or not target_home:
        return None

    candidates: List[dict] = []
    for g in schedule_games or []:
        if require_final and not is_mlb_status_final(g.get("status")):
            continue
        if (
            normalize_mlb_team(g.get("away_team")) == target_away
            and normalize_mlb_team(g.get("home_team")) == target_home
        ):
            candidates.append(g)

    if not candidates:
        return None
    if len(candidates) == 1 or start_time is None:
        return candidates[0]

    target_dt = _parse_dt_utc(start_time)
    if target_dt is None:
        return candidates[0]

    best_game = None
    best_diff = float("inf")
    for g in candidates:
        g_dt = _parse_dt_utc(g.get("game_date") or g.get("start_time"))
        diff = abs((g_dt - target_dt).total_seconds()) if g_dt else float("inf")
        if diff < best_diff:
            best_diff = diff
            best_game = g

    if best_game is not None and best_diff <= 36 * 3600:
        return best_game
    return None


def fetch_espn_scoreboard_finals(
    league: str,
    yyyymmdd: str,
    session: Optional[requests.Session] = None,
) -> List[dict]:
    """Fetch final game scores directly from ESPN public scoreboard without DB side effects."""
    lg = str(league or "").upper().strip()
    path = ESPN_LEAGUE_PATHS.get(lg)
    if not path:
        return []

    url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
    params: Dict[str, Any] = {"dates": yyyymmdd, "limit": 1000}
    if lg == "NCAAM":
        params["groups"] = 50

    client = session or requests
    try:
        resp = client.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json() or {}
    except Exception as exc:
        print(f"[GRADING] ESPN fallback fetch error ({lg} {yyyymmdd}): {exc}")
        return []

    finals: List[dict] = []
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        status_type = ((comp.get("status") or {}).get("type") or {})
        completed = bool(status_type.get("completed")) or str(status_type.get("state") or "").lower() == "post"
        if not completed:
            continue

        home_team = None
        away_team = None
        home_score = None
        away_score = None
        for competitor in comp.get("competitors") or []:
            side = competitor.get("homeAway")
            team_name = (competitor.get("team") or {}).get("displayName")
            raw_score = competitor.get("score")
            try:
                score_val = int(float(raw_score)) if raw_score is not None else None
            except Exception:
                score_val = None
            if side == "home":
                home_team = team_name
                home_score = score_val
            elif side == "away":
                away_team = team_name
                away_score = score_val

        if home_team and away_team and home_score is not None and away_score is not None:
            finals.append({
                "id": f"espn:{ev.get('id')}",
                "home_team": home_team,
                "away_team": away_team,
                "home_score": home_score,
                "away_score": away_score,
                "start_time": comp.get("date") or ev.get("date"),
                "completed": True,
            })
    return finals


def find_pending_backfill_dates(conn, max_dates: int = 250) -> Dict[str, List[str]]:
    """Return {league: [YYYY-MM-DD, ...]} for ungraded past model predictions & slates."""
    from src.database import _exec

    query = """
    WITH pending_events AS (
        SELECT
            UPPER(COALESCE(e.league, 'NCAAM')) AS league,
            ((e.start_time AT TIME ZONE 'America/New_York')::date)::text AS day_et,
            MAX(e.start_time) AS latest_start
        FROM model_predictions m
        JOIN events e ON m.event_id = e.id
        LEFT JOIN game_results gr ON gr.event_id = e.id
        WHERE (m.outcome IS NULL OR UPPER(m.outcome) IN ('PENDING', 'VOID'))
          AND UPPER(COALESCE(m.pick, '')) NOT IN ('', 'NONE', 'NO BET', 'PASS')
          AND UPPER(COALESCE(m.market_type, '')) <> 'AUTO'
          AND e.start_time < NOW() - INTERVAL '2 hours'
          AND (
              COALESCE(gr.final, FALSE) IS NOT TRUE
              OR UPPER(COALESCE(m.market_type, '')) IN ('NRFI', 'YRFI')
          )
        GROUP BY 1, 2
    )
    SELECT league, day_et
    FROM pending_events
    WHERE day_et IS NOT NULL
    ORDER BY latest_start DESC
    LIMIT %s
    """
    grouped: Dict[str, List[str]] = {}
    cursor = _exec(conn, query, (int(max_dates),))
    for row in cursor.fetchall():
        lg = str(row["league"]).upper().strip()
        day_et = str(row["day_et"])[:10]
        if lg and day_et:
            grouped.setdefault(lg, []).append(day_et)
    return grouped


def ingest_mlb_finals_for_dates(
    mlb_service,
    conn,
    dates: List[str],
    schedule_cache: Optional[Dict[str, List[dict]]] = None,
) -> int:
    """Fetch MLB Stats API schedules for target YYYY-MM-DD dates and upsert game_results."""
    from src.database import _exec, upsert_game_result

    if schedule_cache is None:
        schedule_cache = {}

    if not dates:
        return 0

    clean_dates = sorted({str(d)[:10] for d in dates if d})
    expanded_dates = set()
    for d_str in clean_dates:
        try:
            base = dt.date.fromisoformat(d_str)
            for delta in (-1, 0, 1):
                expanded_dates.add((base + dt.timedelta(days=delta)).strftime("%Y-%m-%d"))
        except Exception:
            expanded_dates.add(d_str)

    # Load DB MLB events across the target date range (+/- 2 days around each target date).
    min_d = min(clean_dates)
    max_d = max(clean_dates)
    ev_cursor = _exec(
        conn,
        """
        SELECT id, home_team, away_team, start_time
        FROM events
        WHERE UPPER(COALESCE(league, '')) = 'MLB'
          AND (start_time AT TIME ZONE 'America/New_York')::date
              BETWEEN (%s::date - INTERVAL '2 days') AND (%s::date + INTERVAL '2 days')
        """,
        (min_d, max_d),
    )
    db_events = [dict(r) for r in ev_cursor.fetchall()]
    if not db_events:
        return 0

    # Fetch schedule once per date (with linescore hydrated for NRFI).
    all_schedule_games: List[dict] = []
    for d_str in sorted(expanded_dates):
        if d_str not in schedule_cache:
            try:
                schedule_cache[d_str] = mlb_service.get_schedule(d_str) or []
            except Exception as exc:
                print(f"[GRADING] MLB schedule error for {d_str}: {exc}")
                schedule_cache[d_str] = []
        all_schedule_games.extend(schedule_cache[d_str])

    ingested = 0
    seen_ids = set()
    for ev in db_events:
        eid = ev["id"]
        if eid in seen_ids:
            continue
        matched = match_mlb_schedule_game(
            all_schedule_games,
            ev.get("away_team"),
            ev.get("home_team"),
            start_time=ev.get("start_time"),
            require_final=True,
        )
        if not matched:
            continue
        h_score = matched.get("home_score")
        a_score = matched.get("away_score")
        if h_score is None or a_score is None:
            continue
        upsert_game_result({
            "event_id": eid,
            "home_score": int(h_score),
            "away_score": int(a_score),
            "final": True,
        })
        seen_ids.add(eid)
        ingested += 1
    return ingested


def parse_parlay_legs(selection: Optional[str]) -> List[str]:
    """Extract individual leg strings from a parlay selection."""
    text = str(selection or "").strip()
    if not text:
        return []
    m = re.search(r"parlay\s*:\s*", text, re.IGNORECASE)
    if m:
        text = text[m.end():].strip()
    parts = [p.strip() for p in text.split("|") if p and p.strip()]
    return [p for p in parts if not p.lower().startswith("parlay")]


def _find_matching_final_game(
    candidates: List[dict],
    team_fragment: str,
) -> Optional[dict]:
    """Find best matching final game row for a team fragment using naming standardization."""
    frag_norm = normalize_team_key(standardize_team_name(team_fragment))
    frag_raw = normalize_team_key(team_fragment)
    best_row = None
    best_score = 0
    for row in candidates:
        h = row.get("home_team")
        a = row.get("away_team")
        hs = max(
            _specificity_score(frag_norm, normalize_team_key(standardize_team_name(str(h or "")))),
            _specificity_score(frag_raw, normalize_team_key(h)),
        )
        as_ = max(
            _specificity_score(frag_norm, normalize_team_key(standardize_team_name(str(a or "")))),
            _specificity_score(frag_raw, normalize_team_key(a)),
        )
        score = max(hs, as_)
        if score > best_score:
            best_score = score
            best_row = row
    return best_row if best_score >= 250 else None


def grade_parlay_legs_from_games(legs: List[str], final_games: List[dict]) -> str:
    """Pure grading helper for parlay legs against candidate final game dicts."""
    if not legs:
        return "VOID"

    leg_outcomes: List[str] = []
    for leg in legs:
        # 1. Total leg (e.g., "Over 145.5" or "Duke @ UNC Under 148.5")
        tot_m = re.search(r"\b(OVER|UNDER)\s+(\d+(?:\.\d+)?)\b", leg, re.IGNORECASE)
        if tot_m and ("@" in leg or "vs" in leg.lower()):
            side = tot_m.group(1).upper()
            line_val = float(tot_m.group(2))
            prefix = leg[:tot_m.start()].strip()
            parts = re.split(r"\s+@\s+|\s+vs\.?\s+", prefix, flags=re.IGNORECASE)
            matched_game = None
            for g in final_games:
                if len(parts) == 2 and (
                    (match_team_names(parts[0], g.get("away_team")) and match_team_names(parts[1], g.get("home_team")))
                    or (match_team_names(parts[1], g.get("away_team")) and match_team_names(parts[0], g.get("home_team")))
                ):
                    matched_game = g
                    break
            if not matched_game:
                leg_outcomes.append("PENDING")
                continue
            tot_score = float(matched_game["away_score"]) + float(matched_game["home_score"])
            if tot_score == line_val:
                leg_outcomes.append("PUSH")
            elif (side == "OVER" and tot_score > line_val) or (side == "UNDER" and tot_score < line_val):
                leg_outcomes.append("WON")
            else:
                leg_outcomes.append("LOST")
            continue

        # 2. Spread leg (e.g., "UCLA -6.5", "Arizona -10.5")
        sp_m = re.match(r"^(.*?)\s+([+-]\d+(?:\.\d+)?)\b", leg)
        if sp_m:
            team_name = sp_m.group(1).strip()
            line_val = float(sp_m.group(2))
            g = _find_matching_final_game(final_games, team_name)
            if not g:
                leg_outcomes.append("PENDING")
                continue
            side = resolve_team_side(team_name, g.get("home_team"), g.get("away_team"))
            if not side:
                leg_outcomes.append("PENDING")
                continue
            a_sc, h_sc = float(g["away_score"]), float(g["home_score"])
            diff = (h_sc - a_sc) if side == "HOME" else (a_sc - h_sc)
            adj = diff + line_val
            if adj > 0:
                leg_outcomes.append("WON")
            elif adj < 0:
                leg_outcomes.append("LOST")
            else:
                leg_outcomes.append("PUSH")
            continue

        # 3. Moneyline leg (e.g., "UCLA ML")
        ml_m = re.match(r"^(.*?)\s+ML\b", leg, re.IGNORECASE)
        if ml_m:
            team_name = ml_m.group(1).strip()
            g = _find_matching_final_game(final_games, team_name)
            if not g:
                leg_outcomes.append("PENDING")
                continue
            side = resolve_team_side(team_name, g.get("home_team"), g.get("away_team"))
            if not side:
                leg_outcomes.append("PENDING")
                continue
            a_sc, h_sc = float(g["away_score"]), float(g["home_score"])
            if a_sc == h_sc:
                leg_outcomes.append("PUSH")
            elif (side == "HOME" and h_sc > a_sc) or (side == "AWAY" and a_sc > h_sc):
                leg_outcomes.append("WON")
            else:
                leg_outcomes.append("LOST")
            continue

        leg_outcomes.append("PENDING")

    if "LOST" in leg_outcomes:
        return "LOST"
    if "PENDING" in leg_outcomes:
        return "PENDING"
    if all(o == "PUSH" for o in leg_outcomes):
        return "PUSH"
    if all(o in ("WON", "PUSH") for o in leg_outcomes):
        return "WON"
    return "VOID"


def grade_parlay_selection(conn, selection: Optional[str], ref_time: Any = None) -> str:
    """Grade a parlay prediction against game_results within +/- 7 days of ref_time."""
    from src.database import _exec

    legs = parse_parlay_legs(selection)
    if not legs:
        return "VOID"

    ref_dt = _parse_dt_utc(ref_time) or dt.datetime.now(dt.timezone.utc)
    start_win = ref_dt - dt.timedelta(days=7)
    end_win = ref_dt + dt.timedelta(days=7)

    rows = _exec(
        conn,
        """
        SELECT e.id, e.home_team, e.away_team, e.start_time, gr.home_score, gr.away_score
        FROM game_results gr
        JOIN events e ON gr.event_id = e.id
        WHERE gr.final = TRUE
          AND gr.home_score IS NOT NULL
          AND gr.away_score IS NOT NULL
          AND e.start_time BETWEEN %s AND %s
        ORDER BY ABS(EXTRACT(EPOCH FROM (e.start_time - %s))) ASC
        """,
        (start_win, end_win, ref_dt),
    ).fetchall()
    final_games = [dict(r) for r in rows]
    return grade_parlay_legs_from_games(legs, final_games)
