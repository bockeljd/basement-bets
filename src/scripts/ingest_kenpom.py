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

        CREATE TABLE IF NOT EXISTS kenpom_ratings (
          team_name TEXT PRIMARY KEY,
          rank INTEGER,
          conference TEXT,
          record TEXT,
          adj_em REAL,
          adj_o REAL,
          adj_d REAL,
          adj_t REAL,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

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

        CREATE TABLE IF NOT EXISTS kenpom_fanmatch_daily (
          asof_date DATE NOT NULL,
          home_team TEXT NOT NULL,
          away_team TEXT NOT NULL,
          pred_winner TEXT,
          winner_score REAL,
          loser_score REAL,
          win_prob REAL,
          thrill_score REAL,
          raw JSONB,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          PRIMARY KEY (asof_date, home_team, away_team)
        );
        CREATE INDEX IF NOT EXISTS ix_kp_fanmatch_asof ON kenpom_fanmatch_daily(asof_date);

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
    try:
        with get_db_connection() as conn:
            return _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]
    except Exception:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


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


def _expand_row_cells_with_colspan(tr) -> list[str]:
    out: list[str] = []
    for cell in tr.find_all(["th", "td"]):
        txt = cell.get_text(" ", strip=True)
        try:
            span = max(1, int(cell.get("colspan") or 1))
        except Exception:
            span = 1
        out.append(txt)
        for _ in range(1, span):
            out.append(f"{txt} Rank" if txt else "")
    return out


def _table_headers_and_rows(table) -> tuple[list[str], list[list[str]]]:
    """Return (headers, rows). Expands header colspan attributes best-effort."""
    if not table:
        return [], []

    headers: list[str] = []
    thead = table.find("thead")
    if thead:
        # Prefer last header row (often has the real column labels)
        trs = thead.find_all("tr")
        if trs:
            headers = _expand_row_cells_with_colspan(trs[-1])

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
        if any(str(x).lower() in ("rank", "rk", "team", "player") for x in first):
            headers = first
            rows = rows[1:]

    return headers, rows


def parse_kenpom_html_text(html_text: str, source_tag: str = "html_upload") -> list[dict]:
    """Parse a KenPom ratings HTML page or table fragment using header-aware column detection."""
    soup = BeautifulSoup(html_text or "", "html.parser")
    table = soup.find("table", {"id": "ratings-table"})
    if not table:
        for t in soup.find_all("table"):
            snippet = (t.get_text(" ", strip=True)[:800] or "").lower()
            if any(tok in snippet for tok in ("adjem", "netrtg", "adjoe", "ortg")):
                table = t
                break
    if not table:
        raise ValueError("Could not find a KenPom ratings table in the uploaded HTML.")

    headers, rows = _table_headers_and_rows(table)
    if not headers or not rows:
        return []
    return _parse_kenpom_rows(headers, rows, source_tag=source_tag, header_missing=False)


def scrape_team_ratings(sess: requests.Session) -> list[dict]:
    html = fetch_html(sess, "/")
    try:
        return parse_kenpom_html_text(html, source_tag="web_scrape")
    except ValueError:
        return []


def _extract_headers_and_rows_from_any(
    text_or_html: str,
    header_tokens: tuple[str, ...] = (),
    min_cols: int = 2,
) -> tuple[list[str], list[list[str]]]:
    """Parse an HTML table or TSV/CSV paste into (headers, rows), skipping leading browser nav lines."""
    import csv
    import io
    import re

    raw_text = (
        (text_or_html or "")
        .lstrip("\ufeff")
        .replace("\u2212", "-")
        .replace("\u2013", "-")
        .replace("\xa0", " ")
        .strip()
    )
    if not raw_text:
        return [], []

    lower_head = raw_text[:6000].lower()
    if (
        raw_text.startswith("<")
        and any(tok in lower_head for tok in ("<table", "<!doctype", "<html", "<tr"))
    ) or ("<table" in lower_head and "</tr>" in raw_text.lower()):
        soup = BeautifulSoup(raw_text, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return [], []
        target = tables[0]
        if header_tokens:
            for tbl in tables:
                snip = (tbl.get_text(" ", strip=True)[:1000] or "").lower()
                if any(tok in snip for tok in header_tokens):
                    target = tbl
                    break
        elif len(tables) > 1:
            target = max(tables, key=lambda tbl: len(tbl.find_all("tr")))
        return _table_headers_and_rows(target)

    sample_lines = raw_text.splitlines()[:8]
    sample = "\n".join(sample_lines)
    if raw_text.count("\t") >= 5 or sample.count("\t") >= max(1, sample.count(",")):
        rows_raw = [r for r in csv.reader(io.StringIO(raw_text), delimiter="\t") if r and any(c.strip() for c in r)]
    elif sample.count(",") >= max(2, len(sample_lines)):
        rows_raw = [r for r in csv.reader(io.StringIO(raw_text), delimiter=",") if r and any(c.strip() for c in r)]
    else:
        rows_raw = [re.split(r"\s{2,}", line.strip()) for line in raw_text.splitlines() if line.strip()]
        if rows_raw and max(len(r) for r in rows_raw) < min_cols:
            rows_raw = [r for r in csv.reader(io.StringIO(raw_text), delimiter=",") if r and any(c.strip() for c in r)]

    if not rows_raw:
        return [], []

    header_idx = None
    if header_tokens:
        for idx, r in enumerate(rows_raw[:120]):
            if len(r) < min_cols:
                continue
            joined = " ".join(c.strip().lower() for c in r)
            if any(tok in joined for tok in header_tokens):
                header_idx = idx
                break

    if header_idx is None:
        for idx, r in enumerate(rows_raw[:120]):
            if len(r) >= min_cols and any(str(c).strip().lower() in ("team", "teamname", "player", "official", "ref", "game") for c in r):
                header_idx = idx
                break

    if header_idx is not None:
        return [c.strip() for c in rows_raw[header_idx]], rows_raw[header_idx + 1 :]
    return [], rows_raw


def _align_kp_row_with_headers(headers: list[str], row: list[str]) -> list[str]:
    """Strip interleaved 1..400 rank cells from a pasted HTML table row when headers omit rank columns."""
    if not headers or len(row) <= len(headers) + 1:
        return row
    if any("rank" in str(h).lower() or str(h).strip().lower() == "rk" for h in headers[2:]):
        return row
    out: list[str] = []
    excess = len(row) - len(headers)
    for idx, cell in enumerate(row):
        if (
            excess > 0
            and idx >= 2
            and _looks_like_kp_rank_cell(cell)
            and out
            and ("." in str(out[-1]) or "%" in str(out[-1]))
        ):
            excess -= 1
            continue
        out.append(cell)
    return out


def parse_kenpom_four_factors_text(text_or_html: str) -> list[dict]:
    """Parse KenPom Team Stats / Four Factors (/stats.php) HTML or TSV/CSV."""
    headers, rows = _extract_headers_and_rows_from_any(
        text_or_html,
        header_tokens=("efg", "ftrate", "to%", "or%"),
        min_cols=6,
    )
    if not rows:
        return []
    norm_headers = ["".join(ch for ch in str(h or "").lower() if ch.isalnum()) for h in headers]

    def _find_all_cols(cands: tuple[str, ...]) -> list[int]:
        idxs: list[int] = []
        for idx, nh in enumerate(norm_headers):
            if nh.endswith("rank"):
                continue
            if nh in cands:
                idxs.append(idx)
        return idxs

    idx_team = next((i for i, h in enumerate(norm_headers) if h in ("team", "teamname", "school")), None)
    if idx_team is None:
        if headers and any(h in ("rk", "rank") for h in norm_headers[:1]):
            idx_team = 1
        elif headers:
            idx_team = 0
        else:
            return []

    def _col(name_cands: tuple[str, ...]) -> int | None:
        for c in name_cands:
            for i, nh in enumerate(norm_headers):
                if not nh.endswith("rank") and nh == c:
                    return i
        return None

    efg_cols = _find_all_cols(("efg", "efgpct"))
    to_cols = _find_all_cols(("to", "tov", "topct", "tovpct"))
    or_cols = _find_all_cols(("or", "orb", "orpct", "orbpct"))
    ftr_cols = _find_all_cols(("ftrate", "ftr", "ft"))

    idx_off_efg = _col(("offefg", "oefg")) or (efg_cols[0] if len(efg_cols) >= 1 else None)
    idx_def_efg = _col(("defefg", "defg")) or (efg_cols[1] if len(efg_cols) >= 2 else None)
    idx_off_to = _col(("offto", "offtov", "oto")) or (to_cols[0] if len(to_cols) >= 1 else None)
    idx_def_to = _col(("defto", "deftov", "dto")) or (to_cols[1] if len(to_cols) >= 2 else None)
    idx_off_or = _col(("offor", "offorb", "oor")) or (or_cols[0] if len(or_cols) >= 1 else None)
    idx_def_or = _col(("defor", "deforb", "dor")) or (or_cols[1] if len(or_cols) >= 2 else None)
    idx_off_ftr = _col(("offftr", "offftrate", "oftr")) or (ftr_cols[0] if len(ftr_cols) >= 1 else None)
    idx_def_ftr = _col(("defftr", "defftrate", "dftr")) or (ftr_cols[1] if len(ftr_cols) >= 2 else None)

    if idx_off_efg is None and idx_def_efg is None:
        return []

    def _pct(vals: list[str], idx: int | None) -> float | None:
        if idx is None or idx >= len(vals):
            return None
        v = _to_float(vals[idx])
        if v is None or v < 0.0 or v > 100.0:
            return None
        return round(v, 2)

    out: list[dict] = []
    for raw_row in rows:
        row = _align_kp_row_with_headers(headers, raw_row)
        if len(row) <= idx_team:
            continue
        team = _clean_kp_team_name(row[idx_team])
        if not team or team.lower() in ("team", "teamname", "rk", "rank"):
            continue
        rec = {
            "team_name": team,
            "off_efg": _pct(row, idx_off_efg),
            "off_to": _pct(row, idx_off_to),
            "off_or": _pct(row, idx_off_or),
            "off_ftr": _pct(row, idx_off_ftr),
            "def_efg": _pct(row, idx_def_efg),
            "def_to": _pct(row, idx_def_to),
            "def_or": _pct(row, idx_def_or),
            "def_ftr": _pct(row, idx_def_ftr),
        }
        if rec["off_efg"] is None and rec["def_efg"] is None:
            continue
        out.append(rec)
    return out


def parse_kenpom_height_text(text_or_html: str) -> list[dict]:
    """Parse KenPom Height / Experience / Bench / Continuity (/height.php) HTML or TSV/CSV."""
    import re

    headers, rows = _extract_headers_and_rows_from_any(
        text_or_html,
        header_tokens=("avghgt", "effhgt", "continuity", "exp", "bench"),
        min_cols=5,
    )
    if not rows:
        return []
    norm_headers = ["".join(ch for ch in str(h or "").lower() if ch.isalnum()) for h in headers]

    def _col(cands: tuple[str, ...]) -> int | None:
        for c in cands:
            for i, nh in enumerate(norm_headers):
                if nh.endswith("rank"):
                    continue
                if nh == c:
                    return i
        return None

    idx_team = _col(("team", "teamname", "school"))
    if idx_team is None:
        return []
    idx_hgt = _col(("avghgt", "hgt", "height"))
    idx_eff_hgt = _col(("effhgt", "effectivehgt", "size"))
    idx_exp = _col(("experience", "exp"))
    idx_bench = _col(("bench", "benchmin", "benchpct"))
    idx_cont = _col(("continuity", "cont"))
    if all(i is None for i in (idx_exp, idx_cont, idx_hgt, idx_eff_hgt, idx_bench)):
        return []

    def _parse_hgt(vals: list[str], idx: int | None) -> float | None:
        if idx is None or idx >= len(vals):
            return None
        s = str(vals[idx] or "").replace('"', "").strip()
        m = re.match(r"^(\d)-(\d+(?:\.\d+)?)$", s)
        if m:
            return round(int(m.group(1)) * 12.0 + float(m.group(2)), 2)
        v = _to_float(s)
        if v is None or v < -15.0 or v > 90.0:
            return None
        return round(v, 2)

    out: list[dict] = []
    for raw_row in rows:
        row = _align_kp_row_with_headers(headers, raw_row)
        if len(row) <= idx_team:
            continue
        team = _clean_kp_team_name(row[idx_team])
        if not team or team.lower() in ("team", "teamname", "rk", "rank"):
            continue
        rec = {
            "team_name": team,
            "avg_hgt": _parse_hgt(row, idx_hgt),
            "eff_hgt": _parse_hgt(row, idx_eff_hgt),
            "experience": _to_float(row[idx_exp]) if (idx_exp is not None and idx_exp < len(row)) else None,
            "bench_pct": _to_float(row[idx_bench]) if (idx_bench is not None and idx_bench < len(row)) else None,
            "continuity": _to_float(row[idx_cont]) if (idx_cont is not None and idx_cont < len(row)) else None,
        }
        if all(rec[k] is None for k in ("avg_hgt", "eff_hgt", "experience", "bench_pct", "continuity")):
            continue
        out.append(rec)
    return out


def parse_kenpom_hca_text(text_or_html: str) -> list[dict]:
    """Parse KenPom Home Court Advantage (/hca.php) HTML or TSV/CSV."""
    headers, rows = _extract_headers_and_rows_from_any(
        text_or_html,
        header_tokens=("hca", "home court", "home"),
        min_cols=2,
    )
    if not rows:
        return []
    norm_headers = ["".join(ch for ch in str(h or "").lower() if ch.isalnum()) for h in headers]

    idx_team = next((i for i, h in enumerate(norm_headers) if h in ("team", "teamname", "school")), None)
    idx_hca = next((i for i, h in enumerate(norm_headers) if h in ("hca", "homecourt", "homecourtadvantage", "pts", "adv")), None)
    if idx_team is None:
        if norm_headers and norm_headers[0] in ("rk", "rank"):
            idx_team = 1
        else:
            idx_team = 0

    out: list[dict] = []
    for raw_row in rows:
        row = _align_kp_row_with_headers(headers, raw_row)
        if len(row) <= idx_team + 1:
            continue
        team = _clean_kp_team_name(row[idx_team])
        if not team or team.lower() in ("team", "teamname", "rk", "rank"):
            continue
        hca_val = None
        if idx_hca is not None and idx_hca < len(row):
            hca_val = _parse_kp_float(row[idx_hca])
        else:
            for c_idx in range(idx_team + 1, len(row)):
                if "." in str(row[c_idx]) or str(row[c_idx]).strip().startswith(("+", "-")):
                    cand = _parse_kp_float(row[c_idx])
                    if cand is not None and -3.0 <= cand <= 9.0:
                        hca_val = cand
                        break
        if hca_val is None or hca_val < -3.0 or hca_val > 9.0:
            continue
        out.append({"team_name": team, "hca": round(hca_val, 2), "raw": {"headers": headers, "cols": row}})
    return out


def parse_kenpom_player_stats_text(text_or_html: str) -> list[dict]:
    """Parse KenPom Player Stats (/playerstats.php) HTML or TSV/CSV."""
    headers, rows = _extract_headers_and_rows_from_any(
        text_or_html,
        header_tokens=("player", "ortg", "usage", "%min", "%poss", "min%"),
        min_cols=4,
    )
    if not headers or not rows:
        return []
    norm_headers = ["".join(ch for ch in str(h or "").lower() if ch.isalnum()) for h in headers]
    player_i = next((i for i, h in enumerate(norm_headers) if h in ("player", "name")), 0)
    team_i = next((i for i, h in enumerate(norm_headers) if h in ("team", "school", "teamname")), 1 if player_i != 1 else 2)

    out: list[dict] = []
    for raw_row in rows:
        row = _align_kp_row_with_headers(headers, raw_row)
        if len(row) <= max(player_i, team_i):
            continue
        player = str(row[player_i] or "").strip()
        team = _clean_kp_team_name(row[team_i])
        if not player or not team or player.lower() in ("player", "name", "rk", "rank"):
            continue
        out.append({
            "player_name": player,
            "team_name": team,
            "metrics": {"headers": headers, "cols": row},
            "raw": {"headers": headers, "cols": row},
        })
    return out


def parse_kenpom_refs_text(text_or_html: str) -> list[dict]:
    """Parse KenPom Referee Ratings (/officials.php or /refs.php) HTML or TSV/CSV."""
    headers, rows = _extract_headers_and_rows_from_any(
        text_or_html,
        header_tokens=("official", "referee", "ref", "pf", "foul", "rtg"),
        min_cols=2,
    )
    if not rows:
        return []
    norm_headers = ["".join(ch for ch in str(h or "").lower() if ch.isalnum()) for h in headers]
    idx_name = next((i for i, h in enumerate(norm_headers) if h in ("official", "referee", "ref", "name")), None)
    if idx_name is None:
        idx_name = 1 if (norm_headers and norm_headers[0] in ("rk", "rank")) else 0

    out: list[dict] = []
    for raw_row in rows:
        row = _align_kp_row_with_headers(headers, raw_row)
        if len(row) <= idx_name:
            continue
        name = str(row[idx_name] or "").strip()
        if not name or name.isdigit() or name.lower() in ("official", "ref", "referee", "rk", "rank"):
            continue
        out.append({
            "ref_name": name,
            "metrics": {"headers": headers, "cols": row},
            "raw": {"headers": headers, "cols": row},
        })
    return out


def parse_kenpom_fanmatch_text(text_or_html: str) -> list[dict]:
    """Parse KenPom FanMatch daily game predictions (/fanmatch.php) HTML or TSV/CSV."""
    import re

    headers, rows = _extract_headers_and_rows_from_any(
        text_or_html,
        header_tokens=("prediction", "thrill", "game"),
        min_cols=2,
    )
    if not rows:
        return []
    norm_headers = ["".join(ch for ch in str(h or "").lower() if ch.isalnum()) for h in headers]
    idx_game = next((i for i, h in enumerate(norm_headers) if h in ("game", "matchup")), None)
    idx_pred = next((i for i, h in enumerate(norm_headers) if h in ("prediction", "pred", "projected", "line")), None)
    idx_thrill = next((i for i, h in enumerate(norm_headers) if "thrill" in h), None)

    def _clean_fm_team(s: str) -> str:
        t = re.sub(r"^\s*\d{1,3}\s+", "", str(s or "").strip())
        return _clean_kp_team_name(t)

    out: list[dict] = []
    for row in rows:
        if not row:
            continue
        game_txt = row[idx_game] if (idx_game is not None and idx_game < len(row)) else ""
        if not game_txt:
            game_txt = next((c for c in row if (" at " in c or " vs " in c or " vs. " in c)), "")
        if not game_txt:
            continue

        if " at " in game_txt:
            parts = game_txt.split(" at ", 1)
        elif " vs. " in game_txt:
            parts = game_txt.split(" vs. ", 1)
        elif " vs " in game_txt:
            parts = game_txt.split(" vs ", 1)
        else:
            continue
        away_team = _clean_fm_team(parts[0])
        home_team = _clean_fm_team(parts[1])
        if not away_team or not home_team or away_team.lower() == "game":
            continue

        pred_txt = row[idx_pred] if (idx_pred is not None and idx_pred < len(row)) else ""
        if not pred_txt:
            pred_txt = next((c for c in row if re.search(r"\d{2,3}\s*[-–]\s*\d{2,3}", c)), "")

        pred_winner = None
        winner_score = None
        loser_score = None
        win_prob = None
        if pred_txt:
            m = re.match(r"^\s*(.+?)\s+(\d{2,3})\s*[-–]\s*(\d{2,3})(?:\s*\((\d+(?:\.\d+)?)%?\))?", pred_txt)
            if m:
                pred_winner = _clean_fm_team(m.group(1))
                winner_score = float(m.group(2))
                loser_score = float(m.group(3))
                win_prob = float(m.group(4)) if m.group(4) else None

        thrill = _to_float(row[idx_thrill]) if (idx_thrill is not None and idx_thrill < len(row)) else None
        out.append({
            "home_team": home_team,
            "away_team": away_team,
            "pred_winner": pred_winner,
            "winner_score": winner_score,
            "loser_score": loser_score,
            "win_prob": win_prob,
            "thrill_score": thrill,
            "raw": {"headers": headers, "cols": row},
        })
    return out


def scrape_home_court(sess: requests.Session) -> list[dict]:
    for p in ("/hca.php", "/home.php", "/homeratings.php"):
        try:
            html = fetch_html(sess, p)
            if html and ("HCA" in html or ("Home" in html and "Court" in html)):
                parsed = parse_kenpom_hca_text(html)
                if parsed:
                    return parsed
        except Exception:
            pass
    return []


def scrape_ref_ratings(sess: requests.Session) -> list[dict]:
    for p in ("/officials.php", "/refs.php", "/ref.php", "/refstats.php"):
        try:
            html = fetch_html(sess, p)
            if html and ("Official" in html or "Ref" in html):
                parsed = parse_kenpom_refs_text(html)
                if parsed:
                    return parsed
        except Exception:
            pass
    return []


def scrape_player_stats(sess: requests.Session) -> list[dict]:
    for p in ("/playerstats.php?s=ORtg", "/playerstats.php", "/player.php"):
        try:
            html = fetch_html(sess, p)
            if html and ("Player" in html or "ORtg" in html or "Usage" in html):
                parsed = parse_kenpom_player_stats_text(html)
                if parsed:
                    return parsed
        except Exception:
            pass
    return []


def scrape_four_factors(sess: requests.Session) -> list[dict]:
    for p in ("/stats.php",):
        try:
            html = fetch_html(sess, p)
            if html and ("eFG" in html or "FTRate" in html):
                parsed = parse_kenpom_four_factors_text(html)
                if parsed:
                    return parsed
        except Exception:
            pass
    return []


def scrape_height(sess: requests.Session) -> list[dict]:
    for p in ("/height.php",):
        try:
            html = fetch_html(sess, p)
            if html and ("Continuity" in html or "Experience" in html or "Hgt" in html):
                parsed = parse_kenpom_height_text(html)
                if parsed:
                    return parsed
        except Exception:
            pass
    return []


def scrape_fanmatch(sess: requests.Session) -> list[dict]:
    for p in ("/fanmatch.php",):
        try:
            html = fetch_html(sess, p)
            if html and ("Prediction" in html or "Thrill" in html):
                parsed = parse_kenpom_fanmatch_text(html)
                if parsed:
                    return parsed
        except Exception:
            pass
    return []


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

        # Common KenPom headers (vary): Min%, Min, ORtg, Usage/%Poss, eFG%, TS%, Ast%/ARate, OR%, DR%, TO%, FT Rate, 3PA Rate
        min_pct = _to_float(_find(mapping, ['min%','min %','%min','minutes%','minutes %']))
        minutes = _to_float(_find(mapping, ['min', 'minutes']))
        usage = _to_float(_find(mapping, ['usage', '%poss', 'poss%']))
        ortg = _to_float(_find(mapping, ['ortg','o-rat','off rtg','offensive rating']))
        efg = _to_float(_find(mapping, ['efg']))
        ts = _to_float(_find(mapping, ['ts%','ts %','true shooting']))
        ast_rate = _to_float(_find(mapping, ['ast%','assist%','assist %','arate']))
        orb_rate = _to_float(_find(mapping, ['or%','off reb','off reb%','orb%']))
        drb_rate = _to_float(_find(mapping, ['dr%','def reb','def reb%','drb%']))
        tov_rate = _to_float(_find(mapping, ['to%','tov%','turnover%','turnover %']))
        ft_rate = _to_float(_find(mapping, ['ft rate','ftr','ftrate']))
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
                  raw=COALESCE(kenpom_team_ratings_daily.raw, '{}'::jsonb) || EXCLUDED.raw,
                  updated_at=NOW();
                """, {**payload, "raw": json.dumps(payload.get("raw") or {}, default=str)})

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
                """, {**payload, "raw": json.dumps(payload.get("raw") or {}, default=str)})
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
                    "metrics": json.dumps(payload.get("metrics") or {}, default=str),
                    "raw": json.dumps(payload.get("raw") or {}, default=str),
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
                    "metrics": json.dumps(payload.get("metrics") or {}, default=str),
                    "raw": json.dumps(payload.get("raw") or {}, default=str),
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
                """, {**payload, "raw": json.dumps(payload.get('raw') or {}, default=str)})
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
                """, {**payload, "raw": json.dumps(payload.get('raw') or {}, default=str)})
                n += 1

            elif table == 'kenpom_fanmatch_daily':
                _exec(conn, """
                INSERT INTO kenpom_fanmatch_daily(
                  asof_date, home_team, away_team,
                  pred_winner, winner_score, loser_score, win_prob, thrill_score,
                  raw, updated_at
                )
                VALUES (
                  %(asof_date)s, %(home_team)s, %(away_team)s,
                  %(pred_winner)s, %(winner_score)s, %(loser_score)s, %(win_prob)s, %(thrill_score)s,
                  %(raw)s::jsonb, NOW()
                )
                ON CONFLICT (asof_date, home_team, away_team) DO UPDATE SET
                  pred_winner=EXCLUDED.pred_winner,
                  winner_score=EXCLUDED.winner_score,
                  loser_score=EXCLUDED.loser_score,
                  win_prob=EXCLUDED.win_prob,
                  thrill_score=EXCLUDED.thrill_score,
                  raw=EXCLUDED.raw,
                  updated_at=NOW();
                """, {**payload, "raw": json.dumps(payload.get("raw") or {}, default=str)})
                n += 1

        conn.commit()
        return n


def merge_team_supplement_daily(asof_date: str, rows: list[dict]) -> int:
    """Merge extra team-level metrics (Four Factors, Height/Exp/Continuity) into kenpom_team_ratings_daily.raw."""
    if not rows:
        return 0
    n = 0
    with get_db_connection() as conn:
        for r in rows:
            team = (r.get("team_name") or "").strip()
            if not team:
                continue
            patch = {k: v for k, v in r.items() if k != "team_name" and v is not None}
            if not patch:
                continue
            patch_json = json.dumps(patch, default=str)
            cur = _exec(
                conn,
                """
                UPDATE kenpom_team_ratings_daily
                SET raw = COALESCE(raw, '{}'::jsonb) || %(patch)s::jsonb,
                    updated_at = NOW()
                WHERE asof_date = %(asof_date)s AND LOWER(team_name) = LOWER(%(team_name)s)
                """,
                {"asof_date": asof_date, "team_name": team, "patch": patch_json},
            )
            if int(getattr(cur, "rowcount", 0) or 0) == 0:
                cur = _exec(
                    conn,
                    """
                    UPDATE kenpom_team_ratings_daily
                    SET raw = COALESCE(raw, '{}'::jsonb) || %(patch)s::jsonb,
                        updated_at = NOW()
                    WHERE (asof_date, team_name) = (
                      SELECT asof_date, team_name
                      FROM kenpom_team_ratings_daily
                      WHERE LOWER(team_name) = LOWER(%(team_name)s)
                      ORDER BY asof_date DESC
                      LIMIT 1
                    )
                    """,
                    {"team_name": team, "patch": patch_json},
                )
            n += int(getattr(cur, "rowcount", 0) or 0)
        conn.commit()
    return n


def _clean_kp_team_name(raw_name: str) -> str:
    """Clean trailing tournament seed numbers/markers (e.g. 'Duke 1*' -> 'Duke')."""
    import re
    s = str(raw_name or "").replace("\xa0", " ").strip().strip('"').strip("'")
    s = re.sub(r"([A-Za-z\).'])\s+\d{1,2}\*?$", r"\1", s).strip()
    s = re.sub(r"\*+$", "", s).strip()
    return s


def _parse_kp_float(val) -> float | None:
    if val is None:
        return None
    s = (
        str(val)
        .replace("\u2212", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\xa0", " ")
        .replace("+", "")
        .replace(",", "")
        .strip()
    )
    if not s or s in ("-", "N/A", "NA", "--"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def _parse_kp_int(val) -> int | None:
    f = _parse_kp_float(val)
    return int(round(f)) if f is not None else None


def _looks_like_kp_rank_cell(val: str) -> bool:
    s = str(val or "").strip()
    return s.isdigit() and 1 <= int(s) <= 400


def _parse_kenpom_rows(
    headers: list[str],
    data_rows: list[list[str]],
    source_tag: str = "csv_upload",
    header_missing: bool = False,
) -> list[dict]:
    norm_headers = ["".join(ch for ch in str(h or "").lower() if ch.isalnum()) for h in headers]

    def _find_col(candidates: tuple[str, ...], start: int = 0) -> int | None:
        for cand in candidates:
            for idx in range(start, len(norm_headers)):
                if norm_headers[idx] == cand:
                    return idx
        return None

    idx_team = _find_col(("teamname", "team", "school"))
    if idx_team is None:
        raise ValueError("Missing required 'Team' or 'TeamName' column in CSV")

    idx_rank = _find_col(("rk", "rank", "rankadjem", "ranknetrtg"))
    idx_conf = _find_col(("conf", "confshort", "conference"))
    idx_rec = _find_col(("wl", "record"))
    idx_wins = _find_col(("wins", "w"))
    idx_losses = _find_col(("losses", "l"))
    idx_em = _find_col(("adjem", "netrtg", "em"))
    idx_o = _find_col(("adjo", "adjoe", "ortg", "oe"))
    idx_d = _find_col(("adjd", "adjde", "drtg", "de"))
    idx_t = _find_col(("adjt", "adjtempo", "tempo"))
    after_t = (idx_t + 1) if idx_t is not None else 0
    idx_luck = _find_col(("luck",), start=after_t)
    idx_sos = _find_col(("sosadjem", "sosnetrtg", "sos", "netrtg"), start=(idx_luck + 1 if idx_luck is not None else after_t))
    idx_opp_o = _find_col(("oppo", "sosoppo", "ortg", "adjo", "adjoe"), start=(idx_sos + 1 if idx_sos is not None else after_t))
    idx_opp_d = _find_col(("oppd", "sosoppd", "drtg", "adjd", "adjde"), start=(idx_opp_o + 1 if idx_opp_o is not None else after_t))
    idx_ncsos = _find_col(("ncsosadjem", "ncsosnetrtg", "ncsos", "netrtg"), start=(idx_opp_d + 1 if idx_opp_d is not None else after_t))
    has_colspan_ranks = (
        idx_t is not None
        and (idx_t + 1) < len(norm_headers)
        and "rank" in norm_headers[idx_t + 1]
    )

    if idx_em is None and (idx_o is None or idx_d is None):
        raise ValueError("CSV must contain NetRtg/AdjEM or both ORtg/AdjO and DRtg/AdjD columns")

    def _safe_metric(row_vals: list[str], col_idx: int | None, lo: float, hi: float) -> float | None:
        if col_idx is None or col_idx >= len(row_vals):
            return None
        val = _parse_kp_float(row_vals[col_idx])
        if val is None or val < lo or val > hi:
            return None
        return val

    out: list[dict] = []
    for row in data_rows:
        if len(row) <= idx_team:
            continue
        team = _clean_kp_team_name(row[idx_team])
        if not team or team.lower() in ("team", "teamname"):
            continue
        if idx_em is not None and len(row) > idx_em and str(row[idx_em]).strip().lower() in ("adjem", "netrtg"):
            continue

        # Detect interleaved integer rank cells when pasted directly from kenpom.com HTML table
        row_has_interleaved_ranks = (
            idx_o is not None
            and idx_d is not None
            and idx_d == idx_o + 1
            and (header_missing or len(row) > len(headers) + 1)
            and len(row) > idx_o + 2
            and _looks_like_kp_rank_cell(row[idx_o + 1])
            and (_parse_kp_float(row[idx_o + 2]) or 0.0) >= 65.0
        )

        eff_idx_o = idx_o
        eff_idx_d = (idx_o + 2) if row_has_interleaved_ranks else idx_d
        eff_idx_t = (idx_o + 4) if (row_has_interleaved_ranks and idx_t is not None) else idx_t

        if row_has_interleaved_ranks and eff_idx_t is not None:
            eff_idx_luck = eff_idx_t + 2
            eff_idx_sos = eff_idx_t + 4
            eff_idx_opp_o = eff_idx_t + 6
            eff_idx_opp_d = eff_idx_t + 8
            eff_idx_ncsos = eff_idx_t + 10
        elif has_colspan_ranks and eff_idx_t is not None:
            eff_idx_luck = idx_luck if idx_luck is not None else eff_idx_t + 2
            eff_idx_sos = idx_sos if idx_sos is not None else eff_idx_t + 4
            eff_idx_opp_o = idx_opp_o if idx_opp_o is not None else eff_idx_t + 6
            eff_idx_opp_d = idx_opp_d if idx_opp_d is not None else eff_idx_t + 8
            eff_idx_ncsos = idx_ncsos if idx_ncsos is not None else eff_idx_t + 10
        else:
            eff_idx_luck = idx_luck
            eff_idx_sos = idx_sos
            eff_idx_opp_o = idx_opp_o
            eff_idx_opp_d = idx_opp_d
            eff_idx_ncsos = idx_ncsos

        adj_o = _parse_kp_float(row[eff_idx_o]) if (eff_idx_o is not None and len(row) > eff_idx_o) else None
        adj_d = _parse_kp_float(row[eff_idx_d]) if (eff_idx_d is not None and len(row) > eff_idx_d) else None
        adj_em = _parse_kp_float(row[idx_em]) if (idx_em is not None and len(row) > idx_em) else None
        if adj_em is None and adj_o is not None and adj_d is not None:
            adj_em = round(adj_o - adj_d, 2)
        adj_t = _parse_kp_float(row[eff_idx_t]) if (eff_idx_t is not None and len(row) > eff_idx_t) else None
        luck = _safe_metric(row, eff_idx_luck, -0.5, 0.5)
        sos_adj_em = _safe_metric(row, eff_idx_sos, -40.0, 40.0)
        opp_o = _safe_metric(row, eff_idx_opp_o, 70.0, 140.0)
        opp_d = _safe_metric(row, eff_idx_opp_d, 70.0, 140.0)
        ncsos_adj_em = _safe_metric(row, eff_idx_ncsos, -40.0, 40.0)
        rank = _parse_kp_int(row[idx_rank]) if (idx_rank is not None and len(row) > idx_rank) else None
        conf = str(row[idx_conf]).strip() if (idx_conf is not None and len(row) > idx_conf and str(row[idx_conf]).strip()) else None

        record = str(row[idx_rec]).strip() if (idx_rec is not None and len(row) > idx_rec and str(row[idx_rec]).strip()) else None
        if not record and idx_wins is not None and idx_losses is not None and len(row) > max(idx_wins, idx_losses):
            w_val = _parse_kp_int(row[idx_wins])
            l_val = _parse_kp_int(row[idx_losses])
            if w_val is not None and l_val is not None:
                record = f"{w_val}-{l_val}"

        if adj_em is None and adj_o is None and adj_d is None:
            continue

        out.append({
            "team_name": team,
            "rank": rank,
            "adj_em": adj_em,
            "adj_o": adj_o,
            "adj_d": adj_d,
            "adj_t": adj_t,
            "luck": luck,
            "sos_adj_em": sos_adj_em,
            "opp_o": opp_o,
            "opp_d": opp_d,
            "ncsos_adj_em": ncsos_adj_em,
            "conf": conf,
            "record": record,
            "raw": {
                "source": source_tag,
                "luck": luck,
                "sos_adj_em": sos_adj_em,
                "opp_o": opp_o,
                "opp_d": opp_d,
                "ncsos_adj_em": ncsos_adj_em,
                "row": row,
            },
        })

    if out and any(r.get("rank") is None for r in out):
        out.sort(key=lambda r: float(r.get("adj_em") or -999), reverse=True)
        for i, r in enumerate(out, start=1):
            if r.get("rank") is None:
                r["rank"] = i
    return out


def parse_kenpom_csv_text(csv_text: str) -> list[dict]:
    """Parse KenPom ratings CSV/TSV export, saved HTML page, or copied web table into canonical rows.

    Supports:
    - Saved KenPom HTML pages (File -> Save Page As... .html / .htm) with colspan headers
    - KenPom summary CSV headers (Season, TeamName, AdjTempo, AdjOE, AdjDE, AdjEM, ...)
    - Copied table headers (Rk/Rank, Team, Conf, W-L/Record, NetRtg/AdjEM, ORtg/AdjO, DRtg/AdjD, AdjT)
      including live kenpom.com HTML copy-paste where integer rank cells sit next to ORtg/DRtg/AdjT
    - Unicode minus signs (U+2212) and headerless tab/multi-space table pastes
    """
    import csv
    import io
    import re

    raw_text = (
        (csv_text or "")
        .lstrip("\ufeff")
        .replace("\u2212", "-")
        .replace("\u2013", "-")
        .replace("\xa0", " ")
        .strip()
    )
    if not raw_text:
        return []

    lower_head = raw_text[:4000].lower()
    if (raw_text.startswith("<") and ("<table" in lower_head or "<!doctype html" in lower_head or "<html" in lower_head or "<tr" in lower_head)) or (
        "<table" in lower_head and "</tr>" in raw_text.lower()
    ):
        return parse_kenpom_html_text(raw_text, source_tag="html_upload")

    sample_lines = raw_text.splitlines()[:8]
    sample = "\n".join(sample_lines)
    if raw_text.count("\t") >= 20 or sample.count("\t") >= max(1, sample.count(",")):
        reader = csv.reader(io.StringIO(raw_text), delimiter="\t")
        rows_raw = [r for r in reader if r and any(c.strip() for c in r)]
    elif sample.count(",") >= len(sample_lines):
        reader = csv.reader(io.StringIO(raw_text), delimiter=",")
        rows_raw = [r for r in reader if r and any(c.strip() for c in r)]
    else:
        rows_raw = [
            re.split(r"\s{2,}", line.strip())
            for line in raw_text.splitlines()
            if line.strip()
        ]
        if rows_raw and max(len(r) for r in rows_raw) < 4:
            reader = csv.reader(io.StringIO(raw_text), delimiter=",")
            rows_raw = [r for r in reader if r and any(c.strip() for c in r)]

    if not rows_raw:
        return []

    header_idx = None
    for idx, r in enumerate(rows_raw[:80]):
        joined = " ".join(c.strip().lower() for c in r)
        if ("team" in joined or "school" in joined) and any(
            tok in joined for tok in ("adjem", "netrtg", "adjoe", "ortg")
        ):
            header_idx = idx
            break
    if header_idx is None:
        for idx, r in enumerate(rows_raw[:80]):
            joined = " ".join(c.strip().lower() for c in r)
            if any(tok in joined for tok in ("team", "adjem", "netrtg", "adjoe", "ortg")):
                header_idx = idx
                break

    if header_idx is None:
        # Check for headerless KenPom web-table paste (skipping up to 80 leading nav lines if Cmd+A was used)
        data_start_idx = None
        for idx, candidate in enumerate(rows_raw[:80]):
            if (
                len(candidate) >= 6
                and _looks_like_kp_rank_cell(candidate[0])
                and re.match(r"^\d+-\d+$", str(candidate[3] or "").strip())
                and _parse_kp_float(candidate[4]) is not None
            ):
                data_start_idx = idx
                break
        if data_start_idx is None:
            raise ValueError("Missing required 'Team' or 'TeamName' column in KenPom table")
        headers = ["Rk", "Team", "Conf", "W-L", "NetRtg", "ORtg", "DRtg", "AdjT"]
        data_rows = rows_raw[data_start_idx:]
    else:
        headers = [c.strip() for c in rows_raw[header_idx]]
        data_rows = rows_raw[header_idx + 1:]

    return _parse_kenpom_rows(
        headers,
        data_rows,
        source_tag="csv_upload",
        header_missing=(header_idx is None),
    )


def fetch_kenpom_official_api(api_key: str, year: int | None = None, timeout: int = 20) -> list[dict]:
    """Fetch KenPom ratings via official subscription API (kenpom.com/register-api.php)."""
    from src.utils.ncaam_season import current_ncaam_season_end_year

    key = (api_key or "").strip()
    if not key:
        raise ValueError("KenPom API key is empty.")

    y = int(year or current_ncaam_season_end_year())
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": "BasementBets/1.0",
    }
    resp = requests.get(
        "https://kenpom.com/api.php",
        params={"endpoint": "ratings", "y": y},
        headers=headers,
        timeout=timeout,
    )
    if resp.status_code == 403:
        # Retry with cloudscraper if installed (handles Cloudflare bot challenges in local/CI environments)
        try:
            sess = _make_cloudscraper()
            resp = sess.get(
                "https://kenpom.com/api.php",
                params={"endpoint": "ratings", "y": y},
                headers=headers,
                timeout=timeout,
            )
        except Exception:
            pass

    if resp.status_code == 401:
        raise ValueError("KenPom rejected that API key (HTTP 401). Double-check the key from kenpom.com/register-api.php.")
    if resp.status_code == 403:
        raise RuntimeError("KenPom blocked this server request (HTTP 403 Cloudflare challenge). Paste the ratings table directly or run via GitHub Actions.")
    resp.raise_for_status()
    payload = resp.json()
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(f"Unexpected KenPom API payload type: {type(rows).__name__}")

    out: list[dict] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        team = _clean_kp_team_name(item.get("TeamName") or item.get("team_name") or item.get("Team") or "")
        if not team:
            continue
        adj_o = _parse_kp_float(item.get("AdjOE") or item.get("AdjO") or item.get("ORtg") or item.get("adj_o"))
        adj_d = _parse_kp_float(item.get("AdjDE") or item.get("AdjD") or item.get("DRtg") or item.get("adj_d"))
        adj_em = _parse_kp_float(item.get("AdjEM") or item.get("NetRtg") or item.get("adj_em"))
        if adj_em is None and adj_o is not None and adj_d is not None:
            adj_em = round(adj_o - adj_d, 2)
        adj_t = _parse_kp_float(item.get("AdjTempo") or item.get("AdjT") or item.get("adj_t"))
        rank = _parse_kp_int(item.get("RankAdjEM") or item.get("Rank") or item.get("Rk") or item.get("rank"))
        conf = item.get("ConfShort") or item.get("Conf") or item.get("conf") or None
        wins = item.get("Wins")
        losses = item.get("Losses")
        record = item.get("Record") or (f"{wins}-{losses}" if wins is not None and losses is not None else None)
        out.append({
            "team_name": team,
            "rank": rank,
            "adj_em": adj_em,
            "adj_o": adj_o,
            "adj_d": adj_d,
            "adj_t": adj_t,
            "conf": conf,
            "record": record,
            "raw": {"source": "official_api", "data": item},
        })
    return out


def get_kenpom_status() -> dict:
    """Return plain-English diagnostic status of KenPom activation & server configuration (never exposes secrets)."""
    from datetime import date as _date
    from src.utils.ncaam_season import current_ncaam_season_end_year, season_start_date_for_game

    end_year = int(current_ncaam_season_end_year())
    season_label = f"{end_year - 1}-{str(end_year)[-2:]}"
    season_floor = str(season_start_date_for_game(_date.today()))

    has_api_key = bool((os.getenv("KENPOM_API_KEY") or "").strip())
    has_creds = bool((os.getenv("KENPOM_EMAIL") or "").strip() and (os.getenv("KENPOM_PASSWORD") or "").strip())
    has_cookie = bool((os.getenv("KENPOM_COOKIE") or "").strip())

    latest_asof_date = None
    team_count = 0
    health_status = "missing"
    health_notes = None
    db_error = None
    datasets = {
        "ratings": 0,
        "four_factors": 0,
        "height_experience": 0,
        "home_court": 0,
        "player_stats": 0,
        "ref_ratings": 0,
        "fanmatch_games": 0,
    }

    try:
        with get_db_connection() as conn:
            row = _exec(
                conn,
                """
                SELECT asof_date::text AS asof_date, COUNT(*) AS n
                FROM kenpom_team_ratings_daily
                GROUP BY asof_date
                ORDER BY asof_date DESC
                LIMIT 1
                """,
            ).fetchone()
            if row:
                d_row = dict(row)
                latest_asof_date = str(d_row.get("asof_date") or "")[:10] or None
                team_count = int(d_row.get("n") or 0)

            dh = _exec(
                conn,
                "SELECT status, notes, last_success_at FROM data_health WHERE source = 'kenpom' LIMIT 1",
            ).fetchone()
            if dh:
                dh_d = dict(dh)
                health_status = str(dh_d.get("status") or "missing").lower()
                health_notes = dh_d.get("notes")

            if latest_asof_date and latest_asof_date >= season_floor and team_count > 0:
                datasets["ratings"] = team_count
                try:
                    r_extra = _exec(
                        conn,
                        """
                        SELECT
                          COUNT(*) FILTER (WHERE raw ? 'off_efg') AS ff_n,
                          COUNT(*) FILTER (WHERE raw ? 'experience' OR raw ? 'continuity') AS hgt_n
                        FROM kenpom_team_ratings_daily
                        WHERE asof_date = %s
                        """,
                        (latest_asof_date,),
                    ).fetchone()
                    if r_extra:
                        re_d = dict(r_extra)
                        if re_d.get("ff_n") is not None:
                            datasets["four_factors"] = int(re_d.get("ff_n") or 0)
                        if re_d.get("hgt_n") is not None:
                            datasets["height_experience"] = int(re_d.get("hgt_n") or 0)
                except Exception:
                    pass

                for tbl_key, tbl_name in (
                    ("home_court", "kenpom_home_court_daily"),
                    ("player_stats", "kenpom_player_stats_daily"),
                    ("ref_ratings", "kenpom_ref_ratings_daily"),
                    ("fanmatch_games", "kenpom_fanmatch_daily"),
                ):
                    try:
                        rc = _exec(
                            conn,
                            f"SELECT COUNT(*) AS c FROM {tbl_name} WHERE asof_date >= %s",
                            (season_floor,),
                        ).fetchone()
                        if rc:
                            rc_d = dict(rc)
                            if rc_d.get("c") is not None:
                                datasets[tbl_key] = int(rc_d.get("c") or 0)
                    except Exception:
                        pass
    except Exception as e:
        db_error = str(e)

    active_for_season = bool(latest_asof_date and latest_asof_date >= season_floor and team_count > 0)

    if active_for_season:
        human_summary = (
            f"KenPom is active for the {season_label} season "
            f"(latest snapshot {latest_asof_date}, {team_count} teams)."
        )
        next_step = "Daily ratings are active in the model blend. You can refresh anytime below."
    elif latest_asof_date:
        human_summary = (
            f"KenPom is turned off for {season_label} games because the newest ratings in your database "
            f"are from {latest_asof_date} (prior season)."
        )
        next_step = (
            "Open kenpom.com while logged in and click Send KenPom to Basement Bets on your Chrome Bookmarks Bar, "
            "or run the daily Mac auto-sync script."
        )
    else:
        human_summary = f"KenPom is turned off because no {season_label} team ratings have been imported yet."
        next_step = (
            "Open kenpom.com while logged in and click Send KenPom to Basement Bets on your Chrome Bookmarks Bar, "
            "or run the daily Mac auto-sync script."
        )

    return {
        "active": active_for_season,
        "season_label": season_label,
        "season_end_year": end_year,
        "season_floor": season_floor,
        "latest_asof_date": latest_asof_date,
        "team_count": team_count,
        "health_status": health_status,
        "health_notes": health_notes,
        "db_error": db_error,
        "datasets": datasets,
        "configured_methods": {
            "official_api_key": has_api_key,
            "credentials": has_creds,
            "cookie": has_cookie,
        },
        "human_summary": human_summary,
        "next_step": next_step,
    }


def _merge_team_supplement_into_rows(teams: list[dict], supp_rows: list[dict]) -> int:
    """Attach supplementary team metrics directly into ratings rows' raw dicts in memory."""
    by_lc = {(t.get("team_name") or "").strip().lower(): t for t in teams if t.get("team_name")}
    merged = 0
    for sr in supp_rows or []:
        tname = (sr.get("team_name") or "").strip().lower()
        target = by_lc.get(tname)
        if not target:
            continue
        raw = target.setdefault("raw", {})
        for k, v in sr.items():
            if k != "team_name" and v is not None:
                raw[k] = v
        merged += 1
    return merged


def run_kenpom_sync(
    api_key: str | None = None,
    asof_date: str | None = None,
    include_extras: bool = False,
) -> dict:
    """Sync KenPom ratings via Official API (preferred) or web session credentials."""
    from src.scripts.update_data_health import upsert as upsert_health

    ensure_tables()
    asof = (asof_date or _asof_date_et())[:10]
    key = (api_key or os.getenv("KENPOM_API_KEY") or "").strip()

    if key:
        teams = fetch_kenpom_official_api(key)
        if len(teams) < 10:
            raise RuntimeError(
                f"KenPom Official API returned only {len(teams)} teams for this season; nothing was overwritten."
            )
        n_team = upsert_daily("kenpom_team_ratings_daily", asof, teams, ["team_name"])
        try:
            upsert_health(
                "kenpom",
                status="ok" if n_team > 0 else "stale",
                row_count=n_team,
                notes=f"Synced {n_team} teams via Official API ({asof})",
            )
        except Exception as e:
            print(f"[kenpom] data_health upsert failed: {e}")
        return {
            "status": "ok",
            "method": "official_api",
            "asof_date": asof,
            "rows": n_team,
            "message": f"Synced {n_team} KenPom teams for {asof} via Official API.",
        }

    cookie = (os.getenv("KENPOM_COOKIE") or "").strip()
    email = (os.getenv("KENPOM_EMAIL") or "").strip()
    password = (os.getenv("KENPOM_PASSWORD") or "").strip()
    if not cookie and not (email and password):
        return {
            "status": "needs_setup",
            "method": None,
            "asof_date": asof,
            "rows": 0,
            "message": (
                "No KenPom login email or cookie is configured on this server. "
                "Use the Chrome bookmarklet on kenpom.com or run the daily Mac auto-sync script."
            ),
        }

    sess = _session()
    time.sleep(0.5)
    teams = scrape_team_ratings(sess)
    if not teams:
        msg = (
            "KenPom returned 0 teams (login failed or Cloudflare blocked the server request). "
            "Use the Chrome bookmarklet on kenpom.com or run the daily Mac auto-sync script."
        )
        try:
            upsert_health("kenpom", status="stale", row_count=0, notes=msg[:240])
        except Exception:
            pass
        return {"status": "warning", "method": "web_session", "asof_date": asof, "rows": 0, "message": msg}

    n_ff = n_hgt = n_hca = n_refs = n_players = n_players_norm = n_team_agg = n_fm = 0

    if include_extras:
        try:
            time.sleep(0.6)
            ff = scrape_four_factors(sess)
            n_ff = _merge_team_supplement_into_rows(teams, ff)
        except Exception as e:
            print(f"[kenpom] four_factors skipped: {e}")
        try:
            time.sleep(0.6)
            hgt = scrape_height(sess)
            n_hgt = _merge_team_supplement_into_rows(teams, hgt)
        except Exception as e:
            print(f"[kenpom] height/exp skipped: {e}")

    n_team = upsert_daily("kenpom_team_ratings_daily", asof, teams, ["team_name"])

    if include_extras:
        try:
            time.sleep(0.6)
            hca = scrape_home_court(sess)
            n_hca = upsert_daily("kenpom_home_court_daily", asof, hca, ["team_name"])
        except Exception as e:
            print(f"[kenpom] hca skipped: {e}")
        try:
            time.sleep(0.6)
            refs = scrape_ref_ratings(sess)
            n_refs = upsert_daily("kenpom_ref_ratings_daily", asof, refs, ["ref_name"])
        except Exception as e:
            print(f"[kenpom] refs skipped: {e}")
        try:
            time.sleep(0.6)
            players = scrape_player_stats(sess)
            n_players = upsert_daily("kenpom_player_stats_daily", asof, players, ["player_name", "team_name"])
            norm = normalize_player_rows(players)
            n_players_norm = upsert_daily("kenpom_player_stats_norm_daily", asof, norm, ["player_name", "team_name"])
            aggs = compute_team_player_agg(norm)
            n_team_agg = upsert_daily("kenpom_team_player_agg_daily", asof, aggs, ["team_name"])
        except Exception as e:
            print(f"[kenpom] players skipped: {e}")
        try:
            time.sleep(0.6)
            fm = scrape_fanmatch(sess)
            n_fm = upsert_daily("kenpom_fanmatch_daily", asof, fm, ["home_team", "away_team"])
        except Exception as e:
            print(f"[kenpom] fanmatch skipped: {e}")

    try:
        total = int(n_team or 0) + int(n_hca or 0) + int(n_refs or 0) + int(n_players or 0) + int(n_fm or 0)
        upsert_health(
            "kenpom",
            status="ok" if n_team > 0 else "stale",
            row_count=total,
            notes=f"Synced {n_team} teams, {n_ff} FF, {n_hgt} exp/hgt, {n_hca} HCA, {n_players} players, {n_refs} refs, {n_fm} FanMatch ({asof})",
        )
    except Exception as e:
        print(f"[kenpom] data_health upsert failed: {e}")

    return {
        "status": "ok",
        "method": "web_session",
        "asof_date": asof,
        "rows": n_team,
        "datasets_synced": {
            "ratings": n_team,
            "four_factors": n_ff,
            "height_experience": n_hgt,
            "home_court": n_hca,
            "player_stats": n_players,
            "ref_ratings": n_refs,
            "fanmatch_games": n_fm,
        },
        "message": f"Synced {n_team} KenPom teams + extra datasets for {asof}.",
    }


def ingest_kenpom_bundle(bundle: dict, asof_date: str | None = None) -> dict:
    """Ingest a multi-dataset KenPom JSON bundle emitted by the Chrome bookmarklet or Mac auto-sync."""
    from src.scripts.update_data_health import upsert as upsert_health

    ensure_tables()
    asof = (asof_date or _asof_date_et())[:10]
    counts = {
        "ratings": 0,
        "four_factors": 0,
        "height_experience": 0,
        "home_court": 0,
        "player_stats": 0,
        "ref_ratings": 0,
        "fanmatch_games": 0,
    }
    warnings: list[str] = []

    teams: list[dict] = []
    if bundle.get("ratings"):
        teams = parse_kenpom_csv_text(str(bundle["ratings"]))

    ff_rows: list[dict] = []
    if bundle.get("stats"):
        try:
            ff_rows = parse_kenpom_four_factors_text(str(bundle["stats"]))
            if teams and ff_rows:
                counts["four_factors"] = _merge_team_supplement_into_rows(teams, ff_rows)
        except Exception as e:
            warnings.append(f"stats: {e}")

    hgt_rows: list[dict] = []
    if bundle.get("height"):
        try:
            hgt_rows = parse_kenpom_height_text(str(bundle["height"]))
            if teams and hgt_rows:
                counts["height_experience"] = _merge_team_supplement_into_rows(teams, hgt_rows)
        except Exception as e:
            warnings.append(f"height: {e}")

    if teams:
        if len(teams) < 10 and not any((bundle.get("stats"), bundle.get("height"), bundle.get("hca"), bundle.get("playerstats"), bundle.get("refs"), bundle.get("fanmatch"))):
            raise ValueError(f"Parsed only {len(teams)} valid teams; expected a full KenPom table (>=10 rows).")
        if len(teams) >= 10:
            counts["ratings"] = upsert_daily("kenpom_team_ratings_daily", asof, teams, ["team_name"])
    else:
        if ff_rows:
            try:
                counts["four_factors"] = merge_team_supplement_daily(asof, ff_rows)
            except Exception as e:
                warnings.append(f"stats_merge: {e}")
        if hgt_rows:
            try:
                counts["height_experience"] = merge_team_supplement_daily(asof, hgt_rows)
            except Exception as e:
                warnings.append(f"height_merge: {e}")

    if bundle.get("hca"):
        try:
            hca_rows = parse_kenpom_hca_text(str(bundle["hca"]))
            if hca_rows:
                counts["home_court"] = upsert_daily("kenpom_home_court_daily", asof, hca_rows, ["team_name"])
        except Exception as e:
            warnings.append(f"hca: {e}")

    if bundle.get("playerstats"):
        try:
            player_rows = parse_kenpom_player_stats_text(str(bundle["playerstats"]))
            if player_rows:
                counts["player_stats"] = upsert_daily(
                    "kenpom_player_stats_daily", asof, player_rows, ["player_name", "team_name"]
                )
                norm = normalize_player_rows(player_rows)
                upsert_daily("kenpom_player_stats_norm_daily", asof, norm, ["player_name", "team_name"])
                aggs = compute_team_player_agg(norm)
                upsert_daily("kenpom_team_player_agg_daily", asof, aggs, ["team_name"])
        except Exception as e:
            warnings.append(f"playerstats: {e}")

    if bundle.get("refs"):
        try:
            ref_rows = parse_kenpom_refs_text(str(bundle["refs"]))
            if ref_rows:
                counts["ref_ratings"] = upsert_daily("kenpom_ref_ratings_daily", asof, ref_rows, ["ref_name"])
        except Exception as e:
            warnings.append(f"refs: {e}")

    if bundle.get("fanmatch"):
        try:
            fm_rows = parse_kenpom_fanmatch_text(str(bundle["fanmatch"]))
            if fm_rows:
                counts["fanmatch_games"] = upsert_daily(
                    "kenpom_fanmatch_daily", asof, fm_rows, ["home_team", "away_team"]
                )
        except Exception as e:
            warnings.append(f"fanmatch: {e}")

    total_synced = sum(counts.values())
    if total_synced == 0:
        raise ValueError("Could not parse any valid KenPom rows from the uploaded bundle.")

    notes = (
        f"Imported bundle ({asof}): ratings={counts['ratings']}, four_factors={counts['four_factors']}, "
        f"height_exp={counts['height_experience']}, hca={counts['home_court']}, "
        f"players={counts['player_stats']}, refs={counts['ref_ratings']}, fanmatch={counts['fanmatch_games']}"
    )
    upsert_health(
        "kenpom",
        "ok",
        row_count=counts["ratings"] or total_synced,
        notes=notes[:240],
    )
    return {
        "status": "ok",
        "asof_date": asof,
        "rows": counts["ratings"] or total_synced,
        "datasets_synced": counts,
        "warnings": warnings,
    }


def ingest_kenpom_csv(csv_text: str, asof_date: str | None = None) -> dict:
    """Parse and upsert KenPom ratings (or multi-dataset JSON bundle) into DB and update data_health."""
    from src.scripts.update_data_health import upsert as upsert_health

    raw_stripped = (csv_text or "").lstrip("\ufeff").strip()
    if raw_stripped.startswith("{"):
        try:
            bundle = json.loads(raw_stripped)
        except Exception as e:
            raise ValueError(f"Invalid KenPom JSON bundle: {e}") from e
        if isinstance(bundle, dict) and (
            bundle.get("_kp_bundle")
            or any(k in bundle for k in ("ratings", "stats", "height", "hca", "playerstats", "refs", "fanmatch"))
        ):
            return ingest_kenpom_bundle(bundle, asof_date=asof_date)
        raise ValueError("JSON payload is missing KenPom dataset keys.")

    try:
        teams = parse_kenpom_csv_text(csv_text)
    except ValueError:
        teams = []

    if len(teams) >= 10:
        ensure_tables()
        asof = (asof_date or _asof_date_et())[:10]
        n_saved = upsert_daily("kenpom_team_ratings_daily", asof, teams, ["team_name"])
        upsert_health(
            "kenpom",
            "ok",
            row_count=n_saved,
            notes=f"Imported {n_saved} teams from pasted/uploaded table ({asof})",
        )
        return {"status": "ok", "asof_date": asof, "rows": n_saved, "datasets_synced": {"ratings": n_saved}}

    # Also allow standalone single-page supplemental KenPom pastes (HCA, Four Factors, Height/Exp, Players, Refs, FanMatch)
    supp_checks = [
        ("stats", parse_kenpom_four_factors_text, 10),
        ("height", parse_kenpom_height_text, 10),
        ("hca", parse_kenpom_hca_text, 10),
        ("playerstats", parse_kenpom_player_stats_text, 10),
        ("refs", parse_kenpom_refs_text, 10),
        ("fanmatch", parse_kenpom_fanmatch_text, 1),
    ]
    for key, parser_fn, min_rows in supp_checks:
        try:
            parsed = parser_fn(csv_text)
            if len(parsed) >= min_rows:
                return ingest_kenpom_bundle({key: csv_text}, asof_date=asof_date)
        except Exception:
            continue

    raise ValueError(f"Parsed only {len(teams)} valid teams from CSV; expected a full KenPom table (>=10 rows).")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Ingest KenPom daily ratings via CSV, Official API, or web session")
    parser.add_argument("--csv", type=str, default=None, help="Path to KenPom ratings CSV/TSV file")
    parser.add_argument("--date", type=str, default=None, help="Override asof_date (YYYY-MM-DD)")
    args = parser.parse_args()

    print(f"[{datetime.now(timezone.utc).isoformat()}] ingest_kenpom")

    if args.csv:
        with open(args.csv, "r", encoding="utf-8", errors="replace") as f:
            res = ingest_kenpom_csv(f.read(), asof_date=args.date)
        print(f"csv_upload: asof={res['asof_date']} rows={res['rows']}")
        return

    res = run_kenpom_sync(asof_date=args.date, include_extras=True)
    if res.get("status") == "needs_setup":
        raise RuntimeError("Set KENPOM_API_KEY, --csv <path>, or KENPOM_EMAIL/KENPOM_PASSWORD/KENPOM_COOKIE")
    print(f"sync [{res.get('method')}]: status={res.get('status')} rows={res.get('rows')} msg={res.get('message')}")


if __name__ == '__main__':
    main()
