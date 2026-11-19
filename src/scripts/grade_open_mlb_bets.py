#!/usr/bin/env python3
"""
Research and grade stale PENDING/OPEN MLB bets in the `bets` table
using the free official MLB Stats API (statsapi.mlb.com).
"""
import os
import re
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.database import get_db_connection, _exec

MLB_SCHEDULE_CACHE: Dict[str, List[Dict]] = {}

MLB_TEAM_ALIASES = {
    "dbacks": "arizona diamondbacks",
    "diamondbacks": "arizona diamondbacks",
    "braves": "atlanta braves",
    "orioles": "baltimore orioles",
    "red sox": "boston red sox",
    "cubs": "chicago cubs",
    "white sox": "chicago white sox",
    "reds": "cincinnati reds",
    "guardians": "cleveland guardians",
    "rockies": "colorado rockies",
    "tigers": "detroit tigers",
    "astros": "houston astros",
    "royals": "kansas city royals",
    "angels": "los angeles angels",
    "dodgers": "los angeles dodgers",
    "marlins": "miami marlins",
    "brewers": "milwaukee brewers",
    "twins": "minnesota twins",
    "mets": "new york mets",
    "yankees": "new york yankees",
    "athletics": "athletics",
    "a's": "athletics",
    "phillies": "philadelphia phillies",
    "pirates": "pittsburgh pirates",
    "padres": "san diego padres",
    "giants": "san francisco giants",
    "mariners": "seattle mariners",
    "cardinals": "st. louis cardinals",
    "rays": "tampa bay rays",
    "rangers": "texas rangers",
    "blue jays": "toronto blue jays",
    "nationals": "washington nationals",
}


def fetch_mlb_games_for_date(date_str: str) -> List[Dict]:
    if date_str in MLB_SCHEDULE_CACHE:
        return MLB_SCHEDULE_CACHE[date_str]
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=linescore"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            MLB_SCHEDULE_CACHE[date_str] = []
            return []
        data = resp.json() or {}
        games = []
        for d in data.get("dates") or []:
            for g in d.get("games") or []:
                st = str((g.get("status") or {}).get("abstractGameState") or "").lower()
                if st != "final":
                    continue
                teams = g.get("teams") or {}
                home = teams.get("home") or {}
                away = teams.get("away") or {}
                h_name = str((home.get("team") or {}).get("name") or "")
                a_name = str((away.get("team") or {}).get("name") or "")
                h_score = home.get("score")
                a_score = away.get("score")
                if h_score is None or a_score is None:
                    continue
                games.append({
                    "game_pk": g.get("gamePk"),
                    "date": date_str,
                    "home": h_name,
                    "away": a_name,
                    "home_score": int(h_score),
                    "away_score": int(a_score),
                })
        MLB_SCHEDULE_CACHE[date_str] = games
        return games
    except Exception as e:
        print(f"[MLB Grade] Error fetching {date_str}: {e}")
        MLB_SCHEDULE_CACHE[date_str] = []
        return []


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", str(s or "").lower()).strip()


def _team_matches(text_norm: str, mlb_team_name: str) -> bool:
    t_norm = _norm(mlb_team_name)
    if not t_norm:
        return False
    if t_norm in text_norm:
        return True
    parts = t_norm.split()
    nickname = parts[-1] if parts else ""
    if nickname and len(nickname) >= 4 and re.search(rf"\b{re.escape(nickname)}\b", text_norm):
        return True
    if len(parts) >= 2:
        two = " ".join(parts[-2:])
        if two in text_norm:
            return True
    return False


def _calc_profit(status: str, wager: float, odds: Optional[int]) -> float:
    st = status.upper()
    if st == "LOST":
        return round(-abs(wager), 2)
    if st in ("PUSH", "VOID"):
        return 0.0
    if st == "WON":
        if odds is None or odds == 0:
            return round(wager * (100.0 / 110.0), 2)
        if odds > 0:
            return round(wager * (odds / 100.0), 2)
        return round(wager * (100.0 / abs(odds)), 2)
    return 0.0


def grade_single_bet(bet: Dict) -> Tuple[Optional[str], Optional[float], str]:
    raw_date = str(bet.get("date") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
        return None, None, f"invalid date {raw_date}"

    dt = datetime.strptime(raw_date, "%Y-%m-%d")
    candidate_dates = [raw_date, (dt + timedelta(days=1)).strftime("%Y-%m-%d"), (dt - timedelta(days=1)).strftime("%Y-%m-%d")]

    sel = str(bet.get("selection") or "")
    desc = str(bet.get("description") or "")
    bet_type = str(bet.get("bet_type") or "")
    combined = f"{sel} | {desc} | {bet_type}"
    comb_norm = _norm(combined)

    if "parlay" in comb_norm or "sgp" in comb_norm or "future" in comb_norm or "world series" in comb_norm or "mvp" in comb_norm:
        return None, None, "parlay/future (needs manual review)"

    matched_game = None
    for d_str in candidate_dates:
        games = fetch_mlb_games_for_date(d_str)
        # Prefer exact 2-team matchup match first
        for g in games:
            if _team_matches(comb_norm, g["home"]) and _team_matches(comb_norm, g["away"]):
                matched_game = g
                break
        if matched_game:
            break
    if not matched_game:
        # Fallback: single team match on exact date
        for g in fetch_mlb_games_for_date(raw_date):
            if _team_matches(comb_norm, g["home"]) or _team_matches(comb_norm, g["away"]):
                matched_game = g
                break

    if not matched_game:
        return None, None, f"no final MLB game matched on {raw_date}"

    h_s = matched_game["home_score"]
    a_s = matched_game["away_score"]
    tot = h_s + a_s
    wager = float(bet.get("wager") or 0.0)
    odds = int(bet["odds"]) if bet.get("odds") is not None else None

    sel_norm = _norm(sel or desc)

    # 1) Total (Over / Under)
    m_tot = re.search(r"\b(over|under)\s+(\d+(?:\.\d+)?)\b", sel_norm)
    if m_tot:
        side = m_tot.group(1)
        line = float(m_tot.group(2))
        if tot == line:
            st = "PUSH"
        elif (side == "over" and tot > line) or (side == "under" and tot < line):
            st = "WON"
        else:
            st = "LOST"
        return st, _calc_profit(st, wager, odds), f"{matched_game['away']} {a_s} @ {matched_game['home']} {h_s} (total {tot})"

    # 2) Runline / Spread (+/-1.5, +/-2.5, etc.)
    m_sp = re.search(r"([+-]\d+(?:\.\d+)?)", sel)
    picked_home = _team_matches(sel_norm, matched_game["home"])
    picked_away = _team_matches(sel_norm, matched_game["away"])

    if picked_home and not picked_away:
        if m_sp and abs(float(m_sp.group(1))) <= 10.0:
            line = float(m_sp.group(1))
            margin = (h_s - a_s) + line
            st = "PUSH" if margin == 0 else ("WON" if margin > 0 else "LOST")
        else:
            st = "PUSH" if h_s == a_s else ("WON" if h_s > a_s else "LOST")
        return st, _calc_profit(st, wager, odds), f"{matched_game['away']} {a_s} @ {matched_game['home']} {h_s}"

    if picked_away and not picked_home:
        if m_sp and abs(float(m_sp.group(1))) <= 10.0:
            line = float(m_sp.group(1))
            margin = (a_s - h_s) + line
            st = "PUSH" if margin == 0 else ("WON" if margin > 0 else "LOST")
        else:
            st = "PUSH" if a_s == h_s else ("WON" if a_s > h_s else "LOST")
        return st, _calc_profit(st, wager, odds), f"{matched_game['away']} {a_s} @ {matched_game['home']} {h_s}"

    return None, None, f"ambiguous side for {matched_game['away']} @ {matched_game['home']}"


def main():
    with get_db_connection() as conn:
        rows = _exec(
            conn,
            """
            SELECT id, date, provider, account_id, sport, bet_type, selection, description, odds, wager, status
            FROM bets
            WHERE UPPER(COALESCE(sport, '')) IN ('MLB', 'BASEBALL')
              AND UPPER(COALESCE(status, '')) IN ('PENDING', 'OPEN')
            ORDER BY date ASC
            """,
        ).fetchall()

        print(f"[MLB Grade] Found {len(rows or [])} open/pending MLB bets")
        graded = 0
        skipped = 0
        for r in rows or []:
            b = dict(r)
            st, prof, note = grade_single_bet(b)
            print(
                f"  id={b['id']} | {str(b['date'])[:10]} | {b['provider']} ({b['account_id']}) | "
                f"{b['bet_type']} | sel={b['selection']!r} | desc={b['description']!r} | "
                f"wager={b['wager']} odds={b['odds']} -> {st or 'SKIP'} ({note})"
            )
            if st is not None:
                _exec(
                    conn,
                    "UPDATE bets SET status = %s, profit = %s WHERE id = %s",
                    (st, float(prof or 0.0), b["id"]),
                )
                graded += 1
            else:
                skipped += 1
        conn.commit()
        print(f"[MLB Grade] Done: graded={graded}, skipped={skipped}")


if __name__ == "__main__":
    main()
