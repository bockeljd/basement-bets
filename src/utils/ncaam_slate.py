"""Shared event identity for the NCAAM scoring and publication paths."""

import re

_TEAM_KEY_REPLACEMENTS = (
    ("north carolina state", "nc state"),
    ("n.c. state", "nc state"),
    ("n.c. st.", "nc state"),
    ("nc st.", "nc state"),
    ("app state", "appalachian state"),
    ("appalachian st.", "appalachian state"),
    ("south carolina upstate", "usc upstate"),
    ("u.s.c. upstate", "usc upstate"),
    ("long island university", "liu"),
    ("l.i.u.", "liu"),
    ("se louisiana", "southeastern louisiana"),
    ("s.e. louisiana", "southeastern louisiana"),
    ("southeastern la.", "southeastern louisiana"),
    ("se missouri state", "southeast missouri state"),
    ("se missouri st.", "southeast missouri state"),
    ("semo", "southeast missouri state"),
    ("grambling state", "grambling"),
    ("grambling st.", "grambling"),
    ("warner southern royals", "warner"),
    ("warner southern", "warner"),
    ("warner royals", "warner"),
    ("warner university", "warner"),
    ("delaware fightin blue hens", "delaware blue hens"),
    ("tennessee-martin", "ut martin"),
    ("tenn-martin", "ut martin"),
    ("american university eagles", "american eagles"),
    ("nicholls state", "nicholls"),
    ("nicholls st.", "nicholls"),
    ("mcneese state", "mcneese"),
    ("mcneese st.", "mcneese"),
    ("sam houston state", "sam houston"),
    ("sam houston st.", "sam houston"),
    ("george washington revolutionaries", "george washington colonials"),
    ("san josé state", "san jose state"),
    ("stephen f. austin", "stephen f austin"),
    ("sf austin", "stephen f austin"),
    ("st. francis", "saint francis"),
)


def normalize_ncaam_team_key(name: str | None) -> str:
    """Canonical alphanumeric key mirroring ``team_key_sql`` for Python matching/tests."""
    txt = str(name or "").lower().strip()
    if not txt:
        return ""
    for src, dst in _TEAM_KEY_REPLACEMENTS:
        txt = txt.replace(src, dst)
    txt = re.sub(r"^st\.?\s+", "saint ", txt)
    txt = re.sub(r"(^|\s)(?:mt\.?|mount)\s+st\.?\s+", r"\1mount saint ", txt)
    return re.sub(r"[^a-z0-9]+", "", txt)


def team_key_sql(col: str) -> str:
    """Build a Postgres SQL expression normalizing a team column for cross-feed dedupe."""
    expr = f"LOWER(TRIM(COALESCE({col},'')))"
    for src, dst in _TEAM_KEY_REPLACEMENTS:
        src_sql = src.replace("'", "''")
        dst_sql = dst.replace("'", "''")
        expr = f"replace({expr}, '{src_sql}', '{dst_sql}')"
    expr = f"regexp_replace({expr}, '^st\\.?\\s+', 'saint ')"
    expr = f"regexp_replace({expr}, '(^|\\s)(mt\\.?|mount)\\s+st\\.?\\s+', '\\1mount saint ', 'g')"
    return f"regexp_replace({expr}, '[^a-z0-9]+', '', 'g')"


SLATE_CTE = f"""
WITH base_events AS (
      SELECT e.*,
        DATE(e.start_time AT TIME ZONE 'America/New_York') AS day_et,
        {team_key_sql("e.home_team")} AS home_key,
        {team_key_sql("e.away_team")} AS away_key,
        CASE
          WHEN e.id LIKE 'action:ncaam:%%' THEN 0
          WHEN e.id LIKE 'espn:ncaam:%%' THEN 1
          ELSE 2
        END AS src_rank
      FROM events e
      WHERE e.league='NCAAM'
        AND DATE(e.start_time AT TIME ZONE 'America/New_York') BETWEEN %s AND %s
    ),
    dedup_events AS (
      SELECT *
      FROM (
        SELECT *,
          ROW_NUMBER() OVER (PARTITION BY league, day_et, LEAST(home_key, away_key), GREATEST(home_key, away_key) ORDER BY src_rank ASC, start_time ASC, id ASC) AS rn
        FROM base_events
      ) t
      WHERE rn = 1
    )
"""
