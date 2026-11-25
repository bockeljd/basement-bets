"""Shared event identity for the NCAAM scoring and publication paths."""

SLATE_CTE = """
WITH base_events AS (
      SELECT e.*,
        DATE(e.start_time AT TIME ZONE 'America/New_York') AS day_et,
        LOWER(regexp_replace(
          replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(
            replace(replace(replace(replace(replace(replace(COALESCE(e.home_team,''),
            'North Carolina State', 'NC State'), 'N.C. State', 'NC State'), 'N.C. St.', 'NC State'), 'NC St.', 'NC State'),
            'App State', 'Appalachian State'), 'Appalachian St.', 'Appalachian State'), 'Appalachian St', 'Appalachian State'),
            'South Carolina Upstate', 'USC Upstate'), 'U.S.C. Upstate', 'USC Upstate'),
            'Long Island University', 'LIU'), 'L.I.U.', 'LIU'),
            'St. Francis', 'Saint Francis'),
            'Delaware Fightin Blue Hens', 'Delaware Blue Hens'),
            'Tennessee-Martin', 'UT Martin'),
            'American University Eagles', 'American Eagles'),
            'Nicholls State', 'Nicholls'),
            'George Washington Revolutionaries', 'George Washington Colonials'),
            'San José State', 'San Jose State'),
          '[^a-z0-9]+', '', 'g'
        )) AS home_key,
        LOWER(regexp_replace(
          replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(
            replace(replace(replace(replace(replace(replace(COALESCE(e.away_team,''),
            'North Carolina State', 'NC State'), 'N.C. State', 'NC State'), 'N.C. St.', 'NC State'), 'NC St.', 'NC State'),
            'App State', 'Appalachian State'), 'Appalachian St.', 'Appalachian State'), 'Appalachian St', 'Appalachian State'),
            'South Carolina Upstate', 'USC Upstate'), 'U.S.C. Upstate', 'USC Upstate'),
            'Long Island University', 'LIU'), 'L.I.U.', 'LIU'),
            'St. Francis', 'Saint Francis'),
            'Delaware Fightin Blue Hens', 'Delaware Blue Hens'),
            'Tennessee-Martin', 'UT Martin'),
            'American University Eagles', 'American Eagles'),
            'Nicholls State', 'Nicholls'),
            'George Washington Revolutionaries', 'George Washington Colonials'),
            'San José State', 'San Jose State'),
          '[^a-z0-9]+', '', 'g'
        )) AS away_key,
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
          ROW_NUMBER() OVER (PARTITION BY league, day_et, home_key, away_key ORDER BY src_rank ASC, start_time ASC, id ASC) AS rn
        FROM base_events
      ) t
      WHERE rn = 1
    )
"""
