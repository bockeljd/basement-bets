"""Shared helpers for Men's College Basketball (NCAAM/NCAAB) season identifiers and date windows.

In college basketball, a season spans November of `year - 1` through April of `year`
and is canonically indexed by `season_end_year` (e.g. the 2026-27 season -> `2027`).
Athletic calendar rollover is July 1 (`month >= 7` maps to `calendar_year + 1`).
"""

from __future__ import annotations

from datetime import date, datetime
import re
from typing import Optional, Tuple, Union
from zoneinfo import ZoneInfo

ET_TZ = ZoneInfo("America/New_York")
SEASON_ROLLOVER_MONTH = 7


def _to_et_date(ref_date: Optional[Union[date, datetime]] = None) -> date:
    if ref_date is None:
        return datetime.now(ET_TZ).date()
    if isinstance(ref_date, datetime):
        if ref_date.tzinfo is not None:
            return ref_date.astimezone(ET_TZ).date()
        return ref_date.date()
    return ref_date


def current_ncaam_calendar_year(ref_date: Optional[Union[date, datetime]] = None) -> int:
    """Return the current calendar year in US/Eastern."""
    return _to_et_date(ref_date).year


def current_ncaam_season_end_year(ref_date: Optional[Union[date, datetime]] = None) -> int:
    """Return NCAAM season_end_year (e.g. Nov 2026 -> 2027, Mar 2027 -> 2027)."""
    d = _to_et_date(ref_date)
    return d.year + 1 if d.month >= SEASON_ROLLOVER_MONTH else d.year


def format_ncaam_season_short(season_end_year: int) -> str:
    """Format season_end_year as 'YYYY-YY' (e.g. 2027 -> '2026-27')."""
    y = int(season_end_year)
    return f"{y - 1}-{str(y)[-2:]}"


def format_ncaam_season_long(season_end_year: int) -> str:
    """Format season_end_year as 'YYYY-YYYY' (e.g. 2027 -> '2026-2027')."""
    y = int(season_end_year)
    return f"{y - 1}-{y}"


def current_ncaam_season_short(ref_date: Optional[Union[date, datetime]] = None) -> str:
    """Return current NCAAM season in short format (e.g. '2026-27')."""
    return format_ncaam_season_short(current_ncaam_season_end_year(ref_date))


def current_ncaam_season_long(ref_date: Optional[Union[date, datetime]] = None) -> str:
    """Return current NCAAM season in long format (e.g. '2026-2027')."""
    return format_ncaam_season_long(current_ncaam_season_end_year(ref_date))


def ncaam_season_date_bounds(
    season_end_year: Optional[int] = None,
    ref_date: Optional[Union[date, datetime]] = None,
) -> Tuple[str, str]:
    """Return ('YYYY-11-01', 'YYYY-05-01') bounds for the requested or current season."""
    y = int(season_end_year) if season_end_year is not None else current_ncaam_season_end_year(ref_date)
    return (f"{y - 1}-11-01", f"{y}-05-01")


def ncaam_season_compact_bounds(
    season_end_year: Optional[int] = None,
    ref_date: Optional[Union[date, datetime]] = None,
) -> Tuple[str, str]:
    """Return ('YYYYMMDD', 'YYYYMMDD') season bounds (e.g. ('20261101', '20270501'))."""
    start_iso, end_iso = ncaam_season_date_bounds(season_end_year=season_end_year, ref_date=ref_date)
    return (start_iso.replace("-", ""), end_iso.replace("-", ""))


def parse_ncaam_season_end_year(
    value: Optional[object],
    default: Optional[int] = None,
) -> int:
    """Parse season inputs like 2027, '2027', '2026-27', or '2026-2027' into season_end_year."""
    fallback = int(default) if default is not None else current_ncaam_season_end_year()
    if value is None:
        return fallback
    if isinstance(value, int):
        return value if value >= 2000 else fallback

    s = str(value).strip()
    if not s or s.lower() in {"current", "latest", "auto"}:
        return fallback
    if re.fullmatch(r"\d{4}", s):
        return int(s)
    m_long = re.fullmatch(r"(\d{4})[-_/](\d{4})", s)
    if m_long:
        return int(m_long.group(2))
    m_short = re.fullmatch(r"(\d{4})[-_/](\d{2})", s)
    if m_short:
        start_y = int(m_short.group(1))
        century = (start_y // 100) * 100
        end_two = int(m_short.group(2))
        end_y = century + end_two
        if end_y < start_y:
            end_y += 100
        return end_y
    return fallback
