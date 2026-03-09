"""KenPom ingestion (login-auth + cloudscraper).

Scope: current season only.

Designed to run once per day via GitHub Actions on ubuntu-latest.
Auth (priority order):
  1. KENPOM_EMAIL + KENPOM_PASSWORD  → fresh login each run (preferred)
  2. KENPOM_COOKIE                   → inject pre-existing session cookie
  3. Unauthenticated                 → will only get public data (likely empty)

Data ingested:
- Team ratings (AdjEM/AdjO/AdjD/AdjT + rank)
- Ref ratings (where available)
- Home-court ratings (where available)
- Player stats (stored as JSONB rows)

NOTE: KenPom HTML can change; keep parsing defensive.
"""

from __future__ import annotations
import os
import sys
import time
import json
import requests
from datetime import datetime, timezone

# Allow running from repo root in GitHub Actions
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from bs4 import BeautifulSoup

from src.database import get_admin_db_connection, get_db_connection, _exec


BASE = "https://kenpom.com"

# ──────────────────────────────────────────────
# Session / auth helpers
# ──────────────────────────────────────────────

def _make_cloudscraper():
    """Return a cloudscraper session (handles Cloudflare JS challenges)."""
    try:
        import cloudscraper
        s = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
    except ImportError:
        # Fall back to plain requests if cloudscraper isn't installed
        import requests
        s = requests.Session()

    s.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def _login_with_credentials(s, email: str, password: str) -> bool:
    """
    POST credentials to kenpom.com and return True if login succeeded.
    KenPom uses a simple PHP form: POST /user.php with email + password.
    """
    try:
        # First GET the homepage to let cloudscraper solve any CF challenge
        # and to grab any hidden fields / CSRF tokens.
        print("[kenpom] fetching homepage for CF clearance...")
        r = s.get(BASE, timeout=30)
        if r.status_code == 403:
            print(f"[kenpom] CF blocked homepage (403) — check that cloudscraper is installed")
            return False

        soup = BeautifulSoup(r.text, "html.parser")

        # Find the login form action URL.
        login_form = soup.find("form", {"id": "login-form"}) or soup.find("form", action=lambda a: a and "user" in a)
        if login_form:
            action = login_form.get("action", "/user.php")
            if not action.startswith("http"):
                action = BASE + ("" if action.startswith("/") else "/") + action
        else:
            action = BASE + "/user.php"

        # Collect any hidden inputs (CSRF, etc.)
        payload = {}
        if login_form:
            for inp in login_form.find_all("input", {"type": ["hidden", "text", "email", "password"]}):
                n = inp.get("name")
                v = inp.get("value", "")
                if n:
                    payload[n] = v

        # Override with actual credentials
        payload["email"] = email
        payload["password"] = password

        print(f"[kenpom] POSTing credentials to {action} ...")
        time.sleep(1)
        r2 = s.post(action, data=payload, timeout=30, allow_redirects=True)

        # Detect failed login: kenpom shows "Incorrect" or redirects back to login form
        body = r2.text or ""
        if "Incorrect" in body or "incorrect" in body or "Invalid" in body:
            print("[kenpom] Login failed: invalid credentials")
            return False

        # Check we got a PHPSESSID in the cookie jar
        phpsessid = s.cookies.get("PHPSESSID")
        if not phpsessid:
            # Some CF setups store cookies differently
            print(f"[kenpom] No PHPSESSID in cookie jar after login (status={r2.status_code}). Cookies: {dict(s.cookies)}")

        # Treat as success if we're not on the login/error page
        if "login" not in r2.url.lower() and r2.status_code < 400:
            print(f"[kenpom] Login successful (PHPSESSID={'set' if phpsessid else 'not visible'})")
            return True

        print(f"[kenpom] Login may have failed (redirected to {r2.url})")
        return bool(phpsessid)

    except Exception as e:
        print(f"[kenpom] Login error: {e}")
        return False


def _session():
    """
    Build an authenticated session.

    Priority:
      1. KENPOM_EMAIL + KENPOM_PASSWORD  (fresh login via form POST)
      2. KENPOM_COOKIE                   (inject existing session cookie)
      3. Unauthenticated (public pages only; ratings table will be empty)
    """
    email = (os.getenv("KENPOM_EMAIL") or "").strip()
    password = (os.getenv("KENPOM_PASSWORD") or "").strip()
    cookie = (os.getenv("KENPOM_COOKIE") or "").strip()

    s = _make_cloudscraper()

    if email and password:
        print(f"[kenpom] Authenticating with email={email[:4]}***")
        ok = _login_with_credentials(s, email, password)
        if ok:
            return s
        print("[kenpom] Credential login failed — trying KENPOM_COOKIE fallback")

    if cookie:
        # Strip surrounding quotes
        if (cookie.startswith('"') and cookie.endswith('"')) or \
           (cookie.startswith("'") and cookie.endswith("'")):
            cookie = cookie[1:-1].strip()
        cookie = cookie.replace("\r", " ").replace("\n", " ").strip()
        print("[kenpom] Injecting KENPOM_COOKIE header")
        s.headers["Cookie"] = cookie
        return s

    print("[kenpom] WARNING: no credentials or cookie — scrape will likely return no data")
    return s


def ensure_tables():
    # Use daily snapshots so we can backtest/compare.
    with get_admin_db_connection() as conn:
        _exec(conn, """
        CREATE TABLE IF NOT EXISTS kenpom_team_ratings_daily (
          asof_date DATE NOT NULL,
          team_name TEXT NOT NULL,
          rank INTEGER,
          adj_em REAL,
          adj_o REAL,
          adj_d REAL,
          adj_t REAL,
          conf TEXT,
          record TEXT,
          raw JSONB,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          PRIMARY KEY (asof_date, team_name)
        );
        CREATE INDEX IF NOT EXISTS ix_kp_team_asof_rank ON kenpom_team_ratings_daily(asof_date, rank);

        CREATE TABLE IF NOT EXISTS kenpom_ref_ratings_daily (
          asof_date DATE NOT NULL,
          ref_name TEXT NOT NULL,
          metrics JSONB,
          raw JSONB,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          PRIMARY KEY (asof_date, ref_name)
        );

        CREATE TABLE IF NOT EXISTS kenpom_home_court_daily (
          asof_date DATE NOT NULL,
          team_name TEXT NOT NULL,
          hca REAL,
          raw JSONB,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          PRIMARY KEY (asof_date, team_name)
        );

        CREATE TABLE IF NOT EXISTS kenpom_player_stats_daily (
          asof_date DATE NOT NULL,
          player_name TEXT NOT NULL,
          team_name TEXT NOT NULL DEFAULT '',
          metrics JSONB,
          raw JSONB,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          PRIMARY KEY (asof_date, player_name, team_name)
        );

        CREATE TABLE IF NOT EXISTS kenpom_player_stats_norm_daily (
          asof_date DATE NOT NULL,
          player_name TEXT NOT NULL,
          team_name TEXT NOT NULL DEFAULT '',
          min_pct REAL,
          minutes REAL,
          usage REAL,
          ortg REAL,
          efg REAL,
          ts REAL,
          ast_rate REAL,
          orb_rate REAL,
          drb_rate REAL,
          tov_rate REAL,
          ft_rate REAL,
          three_par REAL,
          raw JSONB,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          PRIMARY KEY (asof_date, player_name, team_name)
        );
        CREATE INDEX IF NOT EXISTS ix_kp_player_norm_team ON kenpom_player_stats_norm_daily(asof_date, team_name);

        CREATE TABLE IF NOT EXISTS kenpom_team_player_agg_daily (
          asof_date DATE NOT NULL,
          team_name TEXT NOT NULL,
          n_players BIGINT,
          minutes_weight_sum REAL,
          ortg_w REAL,
          usage_w REAL,
          efg_w REAL,
          ts_w REAL,
          ast_rate_w REAL,
          reb_rate_w REAL,
          tov_rate_w REAL,
          ft_rate_w REAL,
          three_par_w REAL,
          top7_minutes_pct REAL,
          raw JSONB,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          PRIMARY KEY (asof_date, team_name)
        );
        CREATE INDEX IF NOT EXISTS ix_kp_team_player_agg_team ON kenpom_team_player_agg_daily(asof_date, team_name);

        -- Migration hardening (if table existed with nullable team_name)
        ALTER TABLE kenpom_player_stats_daily ALTER COLUMN team_name SET DEFAULT '';
        UPDATE kenpom_player_stats_daily SET team_name='' WHERE team_name IS NULL;
        ALTER TABLE kenpom_player_stats_daily ALTER COLUMN team_name SET NOT NULL;

        ALTER TABLE kenpom_player_stats_norm_daily ALTER COLUMN team_name SET DEFAULT '';
        UPDATE kenpom_player_stats_norm_daily SET team_name='' WHERE team_name IS NULL;
        ALTER TABLE kenpom_player_stats_norm_daily ALTER COLUMN team_name SET NOT NULL;
        """)
        conn.commit()


def _asof_date_et() -> str:
    with get_db_connection() as conn:
        return _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]


def fetch_html(sess: requests.Session, path: str, params: dict | None = None) -> str:
    url = path if path.startswith("http") else BASE + path
    r = sess.get(url, params=params, timeout=25)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        if r is not None and getattr(r, 'status_code', None) == 403:
            msg = (
                "KenPom returned 403 Forbidden. This is usually Cloudflare blocking GitHub-hosted runner IPs. "
                "Fix: run this workflow on a self-hosted runner (home/residential IP) with label 'kenpom', "
                "and set KENPOM_COOKIE (include PHPSESSID and cf_clearance if present)."
            )
            raise requests.HTTPError(msg) from e
        raise
    return r.text


def _table_headers_and_rows(table) -> tuple[list[str], list[list[str]]]:
    """Return (headers, rows). Headers best-effort."""
    if not table:
        return [], []

    headers: list[str] = []
    thead = table.find("thead")
    if thead:
        # Prefer last header row (often has the real column labels)
        trs = thead.find_all("tr")
        if trs:
            ths = trs[-1].find_all(["th", "td"])
            headers = [h.get_text(" ", strip=True) for h in ths]

    rows: list[list[str]] = []
    tbody = table.find("tbody") or table
    for tr in tbody.find_all("tr"):
        cols = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if cols:
            rows.append(cols)

    # If we didn't find headers and the first row looks like headers, use it.
    if not headers and rows:
        first = rows[0]
        # Heuristic: header-ish if it contains non-numeric strings like 'Rank'/'Team'
        if any(str(x).lower() in ("rank", "team", "player") for x in first):
            headers = first
            rows = rows[1:]

    return headers, rows


def scrape_team_ratings(sess: requests.Session) -> list[dict]:
    html = fetch_html(sess, "/")
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table", {"id": "ratings-table"})
    if not table:
        # If logged-in view changes, try any table containing "AdjEM".
        for t in soup.find_all("table"):
            if "AdjEM" in (t.get_text(" ", strip=True)[:500] or ""):
                table = t
                break

    headers, rows = _table_headers_and_rows(table)
    teams = []
    for cols in rows:
        # Expect rank, team, conf, record, AdjEM, AdjO, ..., AdjD, ..., AdjT
        if len(cols) < 10:
            continue
        try:
            rank = int(cols[0])
        except Exception:
            continue
        team = cols[1]
        conf = cols[2] if len(cols) > 2 else None
        record = cols[3] if len(cols) > 3 else None
        def f(x):
            try:
                return float(str(x).replace("+", "").strip())
            except Exception:
                return None
        adj_em = f(cols[4])
        adj_o = f(cols[5])
        # cols[6] is AdjO rank in the public table; skip
        adj_d = f(cols[7])
        adj_t = f(cols[9])
        teams.append({
            "team_name": team,
            "rank": rank,
            "adj_em": adj_em,
            "adj_o": adj_o,
            "adj_d": adj_d,
            "adj_t": adj_t,
            "conf": conf,
            "record": record,
            "raw": {"headers": headers, "cols": cols},
        })
    return teams


def scrape_home_court(sess: requests.Session) -> list[dict]:
    # KenPom has a home-court ranking page; path may vary. Try a few known guesses.
    candidates = [
        "/hca.php",
        "/home.php",
        "/homeratings.php",
    ]
    html = None
    for p in candidates:
        try:
            html = fetch_html(sess, p)
            if html and "Home" in html and "Court" in html:
                break
        except Exception:
            html = None
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    headers, rows = _table_headers_and_rows(table)
    out = []
    for cols in rows:
        if len(cols) < 2:
            continue
        team = cols[0]
        try:
            hca = float(cols[1].replace("+", "").strip())
        except Exception:
            continue
        out.append({"team_name": team, "hca": hca, "raw": {"headers": headers, "cols": cols}})
    return out


def scrape_ref_ratings(sess: requests.Session) -> list[dict]:
    # Ref data is less standardized; try common paths.
    candidates = [
        "/refs.php",
        "/ref.php",
        "/refstats.php",
    ]
    html = None
    for p in candidates:
        try:
            html = fetch_html(sess, p)
            if html and ("Ref" in html or "Officials" in html):
                break
        except Exception:
            html = None
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    headers, rows = _table_headers_and_rows(table)

    out = []
    # Store as JSONB per ref to avoid brittle column parsing.
    for cols in rows:
        if not cols:
            continue
        name = cols[0]
        if not name or name.lower() in ("ref", "official"):
            continue
        out.append({"ref_name": name, "metrics": {"headers": headers, "cols": cols[1:]}, "raw": {"headers": headers, "cols": cols}})
    return out


def scrape_player_stats(sess: requests.Session) -> list[dict]:
    # Player stats page path can vary; use a best-effort.
    candidates = [
        "/playerstats.php",
        "/player.php",
    ]
    html = None
    for p in candidates:
        try:
            html = fetch_html(sess, p)
            if html and ("Player" in html or "ORtg" in html or "Usage" in html):
                break
        except Exception:
            html = None
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    headers, rows = _table_headers_and_rows(table)
    
    # Robust column mapping
    h_idx = {h.lower(): i for i, h in enumerate(headers)}
    player_i = h_idx.get('player', 0)
    team_i = h_idx.get('team', 1)

    out = []
    for cols in rows:
        if len(cols) <= max(player_i, team_i):
            continue
        player = cols[player_i]
        team = cols[team_i]
        if not player or player.lower() in ("player", "name", "rk"):
            continue
        # For the metrics, we pass the full cols and the headers
        out.append({"player_name": player, "team_name": team, "metrics": {"headers": headers, "cols": cols}, "raw": {"headers": headers, "cols": cols}})
    return out


def _to_float(x):
    try:
        if x is None:
            return None
        s = str(x).replace('%','').replace('+','').strip()
        if s == '':
            return None
        return float(s)
    except Exception:
        return None


def _pair_headers(headers: list[str] | None, cols: list | None) -> dict:
    if not headers or not cols:
        return {}
    m = min(len(headers), len(cols))
    out = {}
    for i in range(m):
        k = str(headers[i]).strip() if headers[i] is not None else ''
        if not k:
            continue
        out[k] = cols[i]
    return out


def _find(mapping: dict, candidates: list[str]):
    for k, v in (mapping or {}).items():
        lk = str(k).lower()
        if any(c.lower() in lk for c in candidates):
            return v
    return None


def normalize_player_rows(player_rows: list[dict]) -> list[dict]:
    """Convert raw player rows -> typed columns best-effort."""
    out = []
    for r in player_rows or []:
        m = (r.get('metrics') or {})
        headers = m.get('headers') or []
        cols = m.get('cols') or []
        mapping = _pair_headers(headers, cols)

        # Common KenPom headers (vary): Min%, Min, ORtg, Usage, eFG%, TS%, Ast%, OR%, DR%, TO%, FT Rate, 3PA Rate
        min_pct = _to_float(_find(mapping, ['min%','min %','%min','minutes%','minutes %']))
        minutes = _to_float(_find(mapping, ['min', 'minutes']))
        usage = _to_float(_find(mapping, ['usage']))
        ortg = _to_float(_find(mapping, ['ortg','off rtg','offensive rating']))
        efg = _to_float(_find(mapping, ['efg']))
        ts = _to_float(_find(mapping, ['ts%','ts %','true shooting']))
        ast_rate = _to_float(_find(mapping, ['ast%','assist%','assist %']))
        orb_rate = _to_float(_find(mapping, ['or%','off reb','off reb%','orb%']))
        drb_rate = _to_float(_find(mapping, ['dr%','def reb','def reb%','drb%']))
        tov_rate = _to_float(_find(mapping, ['to%','tov%','turnover%','turnover %']))
        ft_rate = _to_float(_find(mapping, ['ft rate','ftr']))
        three_par = _to_float(_find(mapping, ['3pa rate','3par','3pa/fg','3pa / fg']))

        out.append({
            'player_name': r.get('player_name'),
            'team_name': r.get('team_name') or '',
            'min_pct': min_pct,
            'minutes': minutes,
            'usage': usage,
            'ortg': ortg,
            'efg': efg,
            'ts': ts,
            'ast_rate': ast_rate,
            'orb_rate': orb_rate,
            'drb_rate': drb_rate,
            'tov_rate': tov_rate,
            'ft_rate': ft_rate,
            'three_par': three_par,
            'raw': {
                'headers': headers,
                'cols': cols,
            }
        })
    return out


def compute_team_player_agg(norm_rows: list[dict]) -> list[dict]:
    """Compute team-level rotation-weighted aggregates for modeling."""
    by_team = {}
    for r in norm_rows or []:
        t = (r.get('team_name') or '').strip()
        if not t:
            continue
        by_team.setdefault(t, []).append(r)

    outs = []
    for team, rows in by_team.items():
        # Weight by min_pct if available else minutes else 1
        def w_of(x):
            w = x.get('min_pct')
            if w is None:
                w = x.get('minutes')
            if w is None:
                w = 1.0
            try:
                return float(w)
            except Exception:
                return 1.0

        # Top-7 minute concentration
        ws = sorted([w_of(r) for r in rows], reverse=True)
        top7 = sum(ws[:7]) if ws else 0.0
        totw = sum(ws) if ws else 0.0
        top7_pct = (top7 / totw) if totw else None

        def wavg(field: str):
            num = 0.0
            den = 0.0
            for r in rows:
                v = r.get(field)
                if v is None:
                    continue
                w = w_of(r)
                num += w * float(v)
                den += w
            return (num / den) if den else None

        reb_rate_w = None
        # If we have both, use sum.
        if any(r.get('orb_rate') is not None for r in rows) or any(r.get('drb_rate') is not None for r in rows):
            # compute wavg of (orb+drb)
            num = 0.0
            den = 0.0
            for r in rows:
                o = r.get('orb_rate')
                d = r.get('drb_rate')
                if o is None and d is None:
                    continue
                w = w_of(r)
                num += w * float((o or 0.0) + (d or 0.0))
                den += w
            reb_rate_w = (num / den) if den else None

        outs.append({
            'team_name': team,
            'n_players': len(rows),
            'minutes_weight_sum': float(totw) if totw else None,
            'ortg_w': wavg('ortg'),
            'usage_w': wavg('usage'),
            'efg_w': wavg('efg'),
            'ts_w': wavg('ts'),
            'ast_rate_w': wavg('ast_rate'),
            'reb_rate_w': reb_rate_w,
            'tov_rate_w': wavg('tov_rate'),
            'ft_rate_w': wavg('ft_rate'),
            'three_par_w': wavg('three_par'),
            'top7_minutes_pct': top7_pct,
            'raw': {
                'fields_present': sorted({k for r in rows for k,v in r.items() if v is not None}),
            }
        })

    return outs


def upsert_daily(table: str, asof_date: str, rows: list[dict], key_fields: list[str]):
    if not rows:
        return 0

    with get_db_connection() as conn:
        n = 0
        for r in rows:
            payload = dict(r)
            payload["asof_date"] = asof_date

            if table == 'kenpom_team_ratings_daily':
                # Update snapshot table
                _exec(conn, """
                INSERT INTO kenpom_team_ratings_daily(asof_date, team_name, rank, adj_em, adj_o, adj_d, adj_t, conf, record, raw, updated_at)
                VALUES (%(asof_date)s, %(team_name)s, %(rank)s, %(adj_em)s, %(adj_o)s, %(adj_d)s, %(adj_t)s, %(conf)s, %(record)s, %(raw)s::jsonb, NOW())
                ON CONFLICT (asof_date, team_name) DO UPDATE SET
                  rank=EXCLUDED.rank,
                  adj_em=EXCLUDED.adj_em,
                  adj_o=EXCLUDED.adj_o,
                  adj_d=EXCLUDED.adj_d,
                  adj_t=EXCLUDED.adj_t,
                  conf=EXCLUDED.conf,
                  record=EXCLUDED.record,
                  raw=EXCLUDED.raw,
                  updated_at=NOW();
                """, {**payload, "raw": json.dumps(payload.get("raw") or {})})

                # ALSO update the live "kenpom_ratings" table
                _exec(conn, """
                INSERT INTO kenpom_ratings(team_name, rank, conference, record, adj_em, adj_o, adj_d, adj_t, updated_at)
                VALUES (%(team_name)s, %(rank)s, %(conf)s, %(record)s, %(adj_em)s, %(adj_o)s, %(adj_d)s, %(adj_t)s, NOW())
                ON CONFLICT (team_name) DO UPDATE SET
                  rank=EXCLUDED.rank,
                  conference=EXCLUDED.conference,
                  record=EXCLUDED.record,
                  adj_em=EXCLUDED.adj_em,
                  adj_o=EXCLUDED.adj_o,
                  adj_d=EXCLUDED.adj_d,
                  adj_t=EXCLUDED.adj_t,
                  updated_at=NOW();
                """, payload)
                n += 1

            elif table == 'kenpom_home_court_daily':
                _exec(conn, """
                INSERT INTO kenpom_home_court_daily(asof_date, team_name, hca, raw, updated_at)
                VALUES (%(asof_date)s, %(team_name)s, %(hca)s, %(raw)s::jsonb, NOW())
                ON CONFLICT (asof_date, team_name) DO UPDATE SET
                  hca=EXCLUDED.hca,
                  raw=EXCLUDED.raw,
                  updated_at=NOW();
                """, {**payload, "raw": json.dumps(payload.get("raw") or {})})
                n += 1

            elif table == 'kenpom_ref_ratings_daily':
                _exec(conn, """
                INSERT INTO kenpom_ref_ratings_daily(asof_date, ref_name, metrics, raw, updated_at)
                VALUES (%(asof_date)s, %(ref_name)s, %(metrics)s::jsonb, %(raw)s::jsonb, NOW())
                ON CONFLICT (asof_date, ref_name) DO UPDATE SET
                  metrics=EXCLUDED.metrics,
                  raw=EXCLUDED.raw,
                  updated_at=NOW();
                """, {
                    **payload,
                    "metrics": json.dumps(payload.get("metrics") or {}),
                    "raw": json.dumps(payload.get("raw") or {}),
                })
                n += 1

            elif table == 'kenpom_player_stats_daily':
                team_name = payload.get('team_name')
                if team_name is None:
                    team_name = ''
                payload['team_name'] = team_name
                _exec(conn, """
                INSERT INTO kenpom_player_stats_daily(asof_date, player_name, team_name, metrics, raw, updated_at)
                VALUES (%(asof_date)s, %(player_name)s, %(team_name)s, %(metrics)s::jsonb, %(raw)s::jsonb, NOW())
                ON CONFLICT (asof_date, player_name, team_name) DO UPDATE SET
                  metrics=EXCLUDED.metrics,
                  raw=EXCLUDED.raw,
                  updated_at=NOW();
                """, {
                    **payload,
                    "metrics": json.dumps(payload.get("metrics") or {}),
                    "raw": json.dumps(payload.get("raw") or {}),
                })
                n += 1

            elif table == 'kenpom_player_stats_norm_daily':
                team_name = payload.get('team_name')
                if team_name is None:
                    team_name = ''
                payload['team_name'] = team_name
                _exec(conn, """
                INSERT INTO kenpom_player_stats_norm_daily(
                  asof_date, player_name, team_name,
                  min_pct, minutes, usage, ortg, efg, ts,
                  ast_rate, orb_rate, drb_rate, tov_rate,
                  ft_rate, three_par,
                  raw, updated_at
                )
                VALUES (
                  %(asof_date)s, %(player_name)s, %(team_name)s,
                  %(min_pct)s, %(minutes)s, %(usage)s, %(ortg)s, %(efg)s, %(ts)s,
                  %(ast_rate)s, %(orb_rate)s, %(drb_rate)s, %(tov_rate)s,
                  %(ft_rate)s, %(three_par)s,
                  %(raw)s::jsonb, NOW()
                )
                ON CONFLICT (asof_date, player_name, team_name) DO UPDATE SET
                  min_pct=EXCLUDED.min_pct,
                  minutes=EXCLUDED.minutes,
                  usage=EXCLUDED.usage,
                  ortg=EXCLUDED.ortg,
                  efg=EXCLUDED.efg,
                  ts=EXCLUDED.ts,
                  ast_rate=EXCLUDED.ast_rate,
                  orb_rate=EXCLUDED.orb_rate,
                  drb_rate=EXCLUDED.drb_rate,
                  tov_rate=EXCLUDED.tov_rate,
                  ft_rate=EXCLUDED.ft_rate,
                  three_par=EXCLUDED.three_par,
                  raw=EXCLUDED.raw,
                  updated_at=NOW();
                """, {**payload, "raw": json.dumps(payload.get('raw') or {})})
                n += 1

            elif table == 'kenpom_team_player_agg_daily':
                team_name = payload.get('team_name')
                if team_name is None:
                    team_name = ''
                payload['team_name'] = team_name
                _exec(conn, """
                INSERT INTO kenpom_team_player_agg_daily(
                  asof_date, team_name,
                  n_players, minutes_weight_sum,
                  ortg_w, usage_w, efg_w, ts_w,
                  ast_rate_w, reb_rate_w, tov_rate_w,
                  ft_rate_w, three_par_w, top7_minutes_pct,
                  raw, updated_at
                )
                VALUES (
                  %(asof_date)s, %(team_name)s,
                  %(n_players)s, %(minutes_weight_sum)s,
                  %(ortg_w)s, %(usage_w)s, %(efg_w)s, %(ts_w)s,
                  %(ast_rate_w)s, %(reb_rate_w)s, %(tov_rate_w)s,
                  %(ft_rate_w)s, %(three_par_w)s, %(top7_minutes_pct)s,
                  %(raw)s::jsonb, NOW()
                )
                ON CONFLICT (asof_date, team_name) DO UPDATE SET
                  n_players=EXCLUDED.n_players,
                  minutes_weight_sum=EXCLUDED.minutes_weight_sum,
                  ortg_w=EXCLUDED.ortg_w,
                  usage_w=EXCLUDED.usage_w,
                  efg_w=EXCLUDED.efg_w,
                  ts_w=EXCLUDED.ts_w,
                  ast_rate_w=EXCLUDED.ast_rate_w,
                  reb_rate_w=EXCLUDED.reb_rate_w,
                  tov_rate_w=EXCLUDED.tov_rate_w,
                  ft_rate_w=EXCLUDED.ft_rate_w,
                  three_par_w=EXCLUDED.three_par_w,
                  top7_minutes_pct=EXCLUDED.top7_minutes_pct,
                  raw=EXCLUDED.raw,
                  updated_at=NOW();
                """, {**payload, "raw": json.dumps(payload.get('raw') or {})})
                n += 1

        conn.commit()
        return n


def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] ingest_kenpom")

    cookie = (os.getenv("KENPOM_COOKIE") or "").strip()
    if not cookie:
        raise RuntimeError("KENPOM_COOKIE is required for subscription scrape")

    ensure_tables()
    asof = _asof_date_et()

    sess = _session()

    # Be polite.
    time.sleep(1.0)

    teams = scrape_team_ratings(sess)
    n_team = upsert_daily('kenpom_team_ratings_daily', asof, teams, ['team_name'])
    print(f"teams: scraped={len(teams)} upserted={n_team}")

    time.sleep(1.0)
    hca = scrape_home_court(sess)
    n_hca = upsert_daily('kenpom_home_court_daily', asof, hca, ['team_name'])
    print(f"home_court: scraped={len(hca)} upserted={n_hca}")

    time.sleep(1.0)
    refs = scrape_ref_ratings(sess)
    n_refs = upsert_daily('kenpom_ref_ratings_daily', asof, refs, ['ref_name'])
    print(f"refs: scraped={len(refs)} upserted={n_refs}")

    # Player stats can be large. Run daily, but keep it best-effort.
    time.sleep(1.0)
    players = scrape_player_stats(sess)
    n_players = upsert_daily('kenpom_player_stats_daily', asof, players, ['player_name','team_name'])
    print(f"players: scraped={len(players)} upserted={n_players}")

    # Normalize player rows -> typed columns, then compute team aggregates.
    n_players_norm = 0
    n_team_agg = 0
    try:
        norm = normalize_player_rows(players)
        n_players_norm = upsert_daily('kenpom_player_stats_norm_daily', asof, norm, ['player_name','team_name'])
        aggs = compute_team_player_agg(norm)
        n_team_agg = upsert_daily('kenpom_team_player_agg_daily', asof, aggs, ['team_name'])
        print(f"players_norm: upserted={n_players_norm} team_player_agg: upserted={n_team_agg}")
    except Exception as e:
        print(f"[kenpom] normalize/agg failed: {e}")

    # Update data_health row
    try:
        from src.scripts.update_data_health import upsert
        total = int(n_team or 0) + int(n_hca or 0) + int(n_refs or 0) + int(n_players or 0) + int(n_players_norm or 0) + int(n_team_agg or 0)
        status = 'ok' if (n_team and n_team > 0) else 'stale'
        upsert('kenpom', status=status, row_count=total, notes=f"team={n_team} hca={n_hca} refs={n_refs} players={n_players} players_norm={n_players_norm} team_agg={n_team_agg}")
    except Exception as e:
        print(f"[kenpom] data_health upsert failed: {e}")


if __name__ == '__main__':
    main()
