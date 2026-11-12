"""Haslametrics ratings client & matchup projection engine.

Parses https://haslametrics.com/ratings.xml (served compressed with Brotli)
and provides DB-backed team lookups and pace-adjusted matchup projections
so the NCAAM ensemble has a live, free second ratings source alongside Torvik.
"""

from __future__ import annotations

import html
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.database import _exec, get_db_connection
from src.utils.ncaam_season import season_start_date_for_game
from src.utils.team_matcher import TeamMatcher


HASLAMETRICS_XML_URL = "https://haslametrics.com/ratings.xml"

HASLAMETRICS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/xml, text/xml, */*;q=0.8",
    "Referer": "https://haslametrics.com/",
}

# Explicit aliases bridging Haslametrics' abbreviated names to standard/sportsbook names.
_HASLA_ALIASES: Dict[str, List[str]] = {
    "abilene christian": ["Abil. Christian", "Abilene Christian"],
    "alabama state": ["Alabama St.", "Alabama State"],
    "alcorn state": ["Alcorn St.", "Alcorn State"],
    "appalachian state": ["Appalachian St.", "App St."],
    "arizona state": ["Arizona St."],
    "arkansas state": ["Arkansas St."],
    "ball state": ["Ball St."],
    "boise state": ["Boise St."],
    "cal state bakersfield": ["CSU Bakersfield", "Cal St. Bakersfield"],
    "cal state fullerton": ["CS Fullerton", "Cal St. Fullerton"],
    "cal state northridge": ["CSUN", "Cal St. Northridge"],
    "central arkansas": ["Cent. Arkansas", "Central Arkansas"],
    "central connecticut": ["Cent. Conn. St.", "Central Conn. St.", "CCSU"],
    "central michigan": ["Cent. Michigan", "Central Michigan"],
    "charleston southern": ["Charleston So."],
    "chicago state": ["Chicago St."],
    "cleveland state": ["Cleveland St."],
    "colorado state": ["Colorado St."],
    "coppin state": ["Coppin St."],
    "delaware state": ["Delaware St."],
    "east tennessee state": ["ETSU", "East Tenn. St."],
    "eastern illinois": ["E. Illinois"],
    "eastern kentucky": ["E. Kentucky"],
    "eastern michigan": ["E. Michigan"],
    "eastern washington": ["E. Washington"],
    "florida state": ["Florida St."],
    "fresno state": ["Fresno St."],
    "georgia southern": ["Ga. Southern"],
    "georgia state": ["Georgia St."],
    "grambling state": ["Grambling St.", "Grambling"],
    "idaho state": ["Idaho St."],
    "illinois state": ["Illinois St."],
    "indiana state": ["Indiana St."],
    "iowa state": ["Iowa St."],
    "jackson state": ["Jackson St."],
    "jacksonville state": ["Jacksonville St."],
    "kansas state": ["Kansas St."],
    "kennesaw state": ["Kennesaw St."],
    "kent state": ["Kent St."],
    "long beach state": ["Long Beach St."],
    "louisiana monroe": ["UL Monroe", "ULM"],
    "loyola marymount": ["LMU"],
    "loyola chicago": ["Loyola-Chicago", "Loyola (IL)"],
    "massachusetts": ["UMass"],
    "mcneese state": ["McNeese", "McNeese St."],
    "miami oh": ["Miami (OH)"],
    "miami fl": ["Miami (FL)", "Miami"],
    "michigan state": ["Michigan St."],
    "middle tennessee": ["Middle Tenn."],
    "mississippi state": ["Mississippi St."],
    "mississippi valley state": ["Miss. Valley St."],
    "missouri state": ["Missouri St."],
    "montana state": ["Montana St."],
    "morehead state": ["Morehead St."],
    "morgan state": ["Morgan St."],
    "murray state": ["Murray St."],
    "new mexico state": ["New Mexico St."],
    "nicholls state": ["Nicholls"],
    "norfolk state": ["Norfolk St."],
    "north carolina a t": ["N.C. A&T"],
    "north carolina central": ["N.C. Central"],
    "north dakota state": ["North Dakota St.", "N. Dakota St."],
    "northern arizona": ["N. Arizona"],
    "northern colorado": ["N. Colorado"],
    "northern illinois": ["N. Illinois"],
    "northern iowa": ["N. Iowa", "UNI"],
    "northern kentucky": ["N. Kentucky"],
    "northwestern state": ["Northwestern St."],
    "ohio state": ["Ohio St."],
    "oklahoma state": ["Oklahoma St."],
    "oregon state": ["Oregon St."],
    "penn state": ["Penn St."],
    "portland state": ["Portland St."],
    "prairie view a m": ["Prairie View"],
    "sacramento state": ["Sacramento St."],
    "saint francis": ["St. Francis (PA)", "Saint Francis"],
    "saint josephs": ["St. Joseph's", "Saint Joseph's"],
    "saint louis": ["St. Louis", "Saint Louis"],
    "saint marys": ["St. Mary's", "Saint Mary's"],
    "saint peters": ["St. Peter's", "Saint Peter's"],
    "sam houston": ["Sam Houston St."],
    "san diego state": ["San Diego St."],
    "san jose state": ["San Jose St."],
    "south alabama": ["S. Alabama"],
    "south carolina state": ["S. Carolina St."],
    "south dakota state": ["S. Dakota St.", "South Dakota St."],
    "southeast missouri state": ["SE Missouri St.", "SEMO"],
    "southeastern louisiana": ["SE Louisiana"],
    "southern illinois": ["S. Illinois"],
    "southern indiana": ["S. Indiana"],
    "southern miss": ["Southern Miss", "So. Miss"],
    "southern utah": ["S. Utah"],
    "stephen f austin": ["Stephen F. Austin", "SFA"],
    "tennessee state": ["Tennessee St."],
    "texas a m corpus christi": ["Texas A&M-CC"],
    "texas state": ["Texas St."],
    "uc santa barbara": ["UCSB", "UC Santa Barbara"],
    "umbc": ["UMBC"],
    "utah state": ["Utah St."],
    "washington state": ["Washington St."],
    "weber state": ["Weber St."],
    "western carolina": ["W. Carolina"],
    "western illinois": ["W. Illinois"],
    "western kentucky": ["W. Kentucky", "WKU"],
    "western michigan": ["W. Michigan"],
    "wichita state": ["Wichita St."],
    "wright state": ["Wright St."],
    "youngstown state": ["Youngstown St."],
}


def _to_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        num = float(val)
        # Haslametrics uses +-999 sentinel values when early-season sample is missing.
        if abs(num) >= 998.0:
            return None
        return num
    except Exception:
        return None


def _to_int(val: Any) -> Optional[int]:
    try:
        return int(float(val)) if val not in (None, "") else None
    except Exception:
        return None


def _parse_asof_date(md_str: Optional[str], fallback_date: Optional[str] = None) -> str:
    if md_str:
        s = md_str.strip()
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    if fallback_date:
        return str(fallback_date)[:10]
    return datetime.utcnow().strftime("%Y-%m-%d")


def _decode_response_bytes(raw: bytes, headers: Optional[Dict[str, str]] = None) -> str:
    """Decode XML bytes, supporting explicit Brotli decompression when needed."""
    stripped = raw.lstrip()
    if stripped.startswith(b"<"):
        return raw.decode("utf-8", errors="replace")

    enc = str((headers or {}).get("Content-Encoding") or "").lower()
    if "br" in enc or not stripped.startswith(b"<"):
        try:
            import brotli

            decompressed = brotli.decompress(raw)
            return decompressed.decode("utf-8", errors="replace")
        except Exception:
            pass

    return raw.decode("utf-8", errors="replace")


def parse_haslametrics_xml(xml_text: str, fallback_date: Optional[str] = None) -> Dict[str, Any]:
    """Parse Haslametrics ratings.xml payload into normalized meta and team rows."""
    if not xml_text or "<" not in xml_text:
        raise ValueError("Empty or non-XML response from Haslametrics")

    trimmed = xml_text.lstrip()
    if trimmed.lower().startswith("<!doctype html") or trimmed.lower().startswith("<html"):
        raise ValueError("Haslametrics returned an HTML challenge/block page instead of XML")

    root = ET.fromstring(xml_text)

    dt_el = root.find("dt")
    md_str = dt_el.attrib.get("md") if dt_el is not None else None
    asof_date = _parse_asof_date(md_str, fallback_date=fallback_date)

    av_el = root.find("av")
    av_eff = _to_float(av_el.attrib.get("e")) if av_el is not None else None
    av_pace = _to_float(av_el.attrib.get("u")) if av_el is not None else None

    ha_el = root.find("ha")
    hca_eff = _to_float(ha_el.attrib.get("e")) if ha_el is not None else None
    hca_pace = _to_float(ha_el.attrib.get("u")) if ha_el is not None else None

    teams: List[Dict[str, Any]] = []
    for mr in root.findall("mr"):
        attr = mr.attrib
        team_name = html.unescape(str(attr.get("t") or "")).strip()
        if not team_name:
            continue

        oe = _to_float(attr.get("oe"))
        de = _to_float(attr.get("de"))
        ou = _to_float(attr.get("ou"))
        du = _to_float(attr.get("du"))
        w = _to_int(attr.get("w"))
        losses = _to_int(attr.get("l"))

        net_eff = (oe - de) if (oe is not None and de is not None) else None
        tempo = ((ou + du) / 2.0) if (ou is not None and du is not None) else (ou or du)
        record = f"{w}-{losses}" if (w is not None and losses is not None) else None

        teams.append(
            {
                "asof_date": asof_date,
                "team_name": team_name,
                "rank": _to_int(attr.get("rk")),
                "conf": (attr.get("c") or "").strip() or None,
                "record": record,
                "oe": oe,
                "de": de,
                "net_eff": net_eff,
                "ou": ou,
                "du": du,
                "tempo": tempo,
                "ap": _to_float(attr.get("ap")),
                "sos": _to_float(attr.get("sos")),
                "mom": _to_float(attr.get("mom")),
                "inc": _to_float(attr.get("inc")),
                "av_eff": av_eff or 109.7,
                "av_pace": av_pace or 69.5,
                "hca_eff": hca_eff or 4.27,
                "hca_pace": hca_pace or 0.08,
                "raw": dict(attr),
            }
        )

    return {
        "asof_date": asof_date,
        "meta": {
            "md": md_str,
            "av_eff": av_eff or 109.7,
            "av_pace": av_pace or 69.5,
            "hca_eff": hca_eff or 4.27,
            "hca_pace": hca_pace or 0.08,
        },
        "teams": teams,
    }


def _expand_hasla_abbrev(name: str) -> str:
    """Expand common Haslametrics abbreviations for normalized fuzzy comparison."""
    s = html.unescape(str(name or ""))
    replacements = (
        (r"\bN\.", "Northern"),
        (r"\bS\.", "Southern"),
        (r"\bE\.", "Eastern"),
        (r"\bW\.", "Western"),
        (r"\bCent\.", "Central"),
        (r"\bAbil\.", "Abilene"),
        (r"\bSt\.", "State"),
        (r"\bGa\.", "Georgia"),
        (r"\bSE\b", "Southeast"),
        (r"\bSW\b", "Southwest"),
        (r"\bNE\b", "Northeast"),
        (r"\bNW\b", "Northwest"),
    )
    for pat, rep in replacements:
        s = re.sub(pat, rep, s)
    return s


def compute_matchup_projection(
    home: Dict[str, Any],
    away: Dict[str, Any],
    neutral_site: bool = False,
) -> Optional[Dict[str, Any]]:
    """Compute Haslametrics projected margin (home - away), total, and score."""
    if not home or not away:
        return None

    h_oe = _to_float(home.get("oe"))
    h_de = _to_float(home.get("de"))
    a_oe = _to_float(away.get("oe"))
    a_de = _to_float(away.get("de"))
    if None in (h_oe, h_de, a_oe, a_de) or min(h_oe, h_de, a_oe, a_de) <= 0:
        return None

    av_eff = _to_float(home.get("av_eff")) or _to_float(away.get("av_eff")) or 109.7
    av_pace = _to_float(home.get("av_pace")) or _to_float(away.get("av_pace")) or 69.5
    hca_eff = _to_float(home.get("hca_eff")) or _to_float(away.get("hca_eff")) or 4.27
    hca_pace = _to_float(home.get("hca_pace")) or _to_float(away.get("hca_pace")) or 0.08

    h_tempo = _to_float(home.get("tempo")) or 69.5
    a_tempo = _to_float(away.get("tempo")) or 69.5
    expected_pace = (h_tempo + a_tempo - av_pace) + (0.0 if neutral_site else hca_pace)
    expected_pace = max(55.0, min(85.0, expected_pace))

    h_eff = (h_oe * a_de) / av_eff + (0.0 if neutral_site else hca_eff * 0.5)
    a_eff = (a_oe * h_de) / av_eff - (0.0 if neutral_site else hca_eff * 0.5)

    h_score = h_eff * (expected_pace / 100.0)
    a_score = a_eff * (expected_pace / 100.0)

    margin = h_score - a_score  # Positive = home favored
    total = h_score + a_score

    return {
        "available": True,
        "asof_date": str(home.get("asof_date") or away.get("asof_date") or ""),
        "margin": round(margin, 2),
        "total": round(total, 2),
        "home_score": round(h_score, 1),
        "away_score": round(a_score, 1),
        "projected_score": f"{int(round(a_score))}-{int(round(h_score))}",
        "game_tempo": round(expected_pace, 1),
        "home": home,
        "away": away,
    }


class HaslametricsClient:
    """Client for fetching live Haslametrics XML and querying daily DB snapshots."""

    def __init__(self) -> None:
        self.matcher = TeamMatcher()
        self._rating_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._all_names_cache: Optional[List[str]] = None

    def fetch_live_ratings(self, timeout: int = 20) -> Dict[str, Any]:
        """Download and parse live Haslametrics XML ratings."""
        resp = requests.get(HASLAMETRICS_XML_URL, headers=HASLAMETRICS_HEADERS, timeout=timeout)
        resp.raise_for_status()
        xml_text = _decode_response_bytes(resp.content, dict(resp.headers))
        return parse_haslametrics_xml(xml_text)

    def _find_hasla_team_name(self, conn, team_name: str) -> Optional[str]:
        if not team_name:
            return None

        # 1. Standard TeamMatcher against haslametrics_ratings_daily
        matched = self.matcher.find_source_name(team_name, "haslametrics_ratings_daily", "team_name")
        if matched:
            return matched

        # 2. Haslametrics-specific alias table & expanded abbreviation lookup
        if self._all_names_cache is None:
            rows = _exec(
                conn,
                "SELECT DISTINCT team_name FROM haslametrics_ratings_daily",
            ).fetchall()
            self._all_names_cache = [
                (dict(r).get("team_name") if isinstance(r, dict) or hasattr(r, "keys") else r[0])
                for r in (rows or [])
            ]

        all_names = self._all_names_cache or []
        if not all_names:
            return None

        norm_target = self.matcher.normalize(team_name)
        alias_cands = _HASLA_ALIASES.get(norm_target, [])
        all_by_norm = {self.matcher.normalize(n): n for n in all_names if n}
        for cand in alias_cands:
            hit = all_by_norm.get(self.matcher.normalize(cand))
            if hit:
                return hit

        for raw_name in all_names:
            expanded = self.matcher.normalize(_expand_hasla_abbrev(raw_name))
            if expanded == norm_target:
                return raw_name

        return None

    def get_team_rating(
        self,
        team_name: str,
        asof_date: Optional[str] = None,
        conn=None,
    ) -> Optional[Dict[str, Any]]:
        if not team_name:
            return None
        cache_key = f"{team_name}:{asof_date or 'latest'}"
        if cache_key in self._rating_cache:
            return self._rating_cache[cache_key]

        if os.environ.get("REQUIRE_DATABASE") == "0" and conn is None:
            return None

        def _query(c) -> Optional[Dict[str, Any]]:
            matched = self._find_hasla_team_name(c, team_name)
            if not matched:
                return None
            season_start = season_start_date_for_game(asof_date)
            row = _exec(
                c,
                """
                SELECT asof_date, team_name, rank, conf, record, oe, de, net_eff,
                       ou, du, tempo, ap, sos, mom, inc, av_eff, av_pace, hca_eff, hca_pace
                FROM haslametrics_ratings_daily
                WHERE team_name = %s
                  AND asof_date >= %s
                ORDER BY asof_date DESC
                LIMIT 1
                """,
                (matched, season_start),
            ).fetchone()
            return dict(row) if row else None

        try:
            if conn is not None:
                res = _query(conn)
            else:
                with get_db_connection() as c:
                    res = _query(c)
        except Exception as e:
            print(f"[Haslametrics] Rating lookup failed for {team_name}: {e}")
            res = None

        self._rating_cache[cache_key] = res
        return res

    def calculate_projection(
        self,
        home_team: str,
        away_team: str,
        neutral_site: bool = False,
        asof_date: Optional[str] = None,
        conn=None,
    ) -> Optional[Dict[str, Any]]:
        """Compute Haslametrics spread/total projection for a matchup."""
        try:
            home = self.get_team_rating(home_team, asof_date=asof_date, conn=conn)
            away = self.get_team_rating(away_team, asof_date=asof_date, conn=conn)
            return compute_matchup_projection(home, away, neutral_site=neutral_site)
        except Exception as e:
            print(f"[Haslametrics] Projection failed for {away_team} @ {home_team}: {e}")
            return None
