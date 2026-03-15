from src.auth import get_current_user
from fastapi import FastAPI, HTTPException, Request, Security, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
import os

from src.models.odds_client import OddsAPIClient
from src.database import fetch_all_bets, insert_model_prediction, fetch_model_history, init_db
from src.utils.model_performance import norm_outcome, is_decided, payout_per_unit, roi_per_unit, conf_bucket
from typing import Optional

app = FastAPI()

# Trigger Reload - 1.2.1-v6

# -----------------------------------------------------------------------------
# Lightweight in-process response cache (TTL) + ETag support.
# Note: this is best-effort for Vercel/serverless (per-instance). Still reduces
# repeated DB work and network transfer within a warm instance.
# -----------------------------------------------------------------------------
import json
import hashlib
import time
from typing import Any, Callable, Dict, Tuple

_HTTP_CACHE: Dict[str, Tuple[float, Any, str]] = {}  # key -> (expires_ts, payload, etag)


def _make_etag(payload: Any) -> str:
    try:
        b = json.dumps(payload, sort_keys=True, default=str).encode('utf-8')
    except Exception:
        b = str(payload).encode('utf-8')
    return 'W/"' + hashlib.sha1(b).hexdigest() + '"'


def _cached_json(request: Request, key: str, ttl_s: int, build_fn: Callable[[], Any]) -> JSONResponse:
    now = time.time()
    hit = _HTTP_CACHE.get(key)
    if hit and hit[0] > now:
        payload, etag = hit[1], hit[2]
    else:
        # Ensure payload is JSON serializable (handles datetime/date/Decimal, etc.)
        payload = jsonable_encoder(build_fn())
        etag = _make_etag(payload)
        _HTTP_CACHE[key] = (now + ttl_s, payload, etag)

    inm = request.headers.get('if-none-match')
    if inm and inm.strip() == etag:
        return JSONResponse(status_code=304, content=None, headers={'ETag': etag})

    return JSONResponse(content=payload, headers={'ETag': etag, 'Cache-Control': f'public, max-age={ttl_s}'})


# --- Security Configuration ---
API_KEY_NAME = "X-BASEMENT-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

from src.config import settings

@app.middleware("http")
async def check_access_key(request: Request, call_next):
    # Allow public access to root, favicon, or OPTIONS (CORS preflight)
    if request.method == "OPTIONS":
         return await call_next(request)
         
    if request.url.path.startswith("/api"):
        # 1. Skip ALL security for /api/jobs/ here. 
        # These paths MUST be handled by Depends(verify_cron_secret) or explicit checks.
        if request.url.path.startswith("/api/jobs/"):
            return await call_next(request)

        # Allow public diagnostic endpoints + read-only UI endpoints
        public_paths = {
            "/api/version",
            "/api/health",
            "/api/board",
            "/api/ncaam/top-picks",
            "/api/data-health",
        }

        # Agent Council UI endpoints should be readable without a password.
        if request.url.path.startswith("/api/v1/council"):
            return await call_next(request)

        if request.url.path in public_paths:
            return await call_next(request)

        # 2. Check Client Key (Basement Password) for all other /api paths
        client_key = request.headers.get(API_KEY_NAME)
        if client_key:
            client_key = client_key.strip()
            
        server_key = settings.BASEMENT_PASSWORD
        
        # If Password is set on Server, enforce it
        if server_key and client_key != server_key:
             return JSONResponse(status_code=403, content={"message": "Forbidden: Invalid Basement Password"})
             
    response = await call_next(request)
    return response

@app.get("/api/version")
def get_version():
    """Public endpoint to check the current deployed version and build metadata."""
    return {
        "version": os.environ.get("APP_VERSION", "dev"),
        "env": os.environ.get("VERCEL_ENV", "local"),
        "vercel": {
            "deployment_id": os.environ.get("VERCEL_DEPLOYMENT_ID"),
            "region": os.environ.get("VERCEL_REGION"),
            "git_sha": os.environ.get("VERCEL_GIT_COMMIT_SHA"),
            "git_ref": os.environ.get("VERCEL_GIT_COMMIT_REF"),
            "git_msg": os.environ.get("VERCEL_GIT_COMMIT_MESSAGE"),
        },
        # keep a small auth sanity signal without leaking secrets
        "debug_password_len": len(settings.BASEMENT_PASSWORD) if settings.BASEMENT_PASSWORD else 0,
    }


@app.get("/api/edge/ncaab/recommendations")
def edge_ncaab_recommendations(date: Optional[str] = None, season: int = 2026):
    """On-demand NCAAB edge-engine recommendations.

    Secured by the same /api auth middleware.

    Query params:
      - date: YYYY-MM-DD (America/New_York). Defaults to today (ET).
      - season: season_end_year (default 2026).

    Returns:
      { generated_at, date, season_end_year, config, picks[] }
    """
    from src.services.edge_engine_ncaab import recommend_for_date
    from src.database import get_db_connection, _exec

    if not date:
        with get_db_connection() as conn:
            date = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]

    try:
        # Clamp/fallback season to avoid empty UI if an artifact isn't present on deploy.
        try:
            season_i = int(season)
        except Exception:
            season_i = 2026
        if season_i < 2026:
            season_i = 2026
        return recommend_for_date(date_et=date, season_end_year=season_i)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"edge engine failed: {e}")

# --- Admin Routes ---
@app.post("/api/admin/init-db")
def trigger_init_db(request: Request):
    """
    Initializes database schema (Non-destructive unless BASEMENT_DB_RESET=1).
    """
    from src.database import init_db
    init_db()
    return {"status": "success", "message": "Database Initialized (Postgres)"}

@app.get("/api/health")
def health_check():
    from src.database import get_db_connection, _exec
    
    db_ok = False
    last_bet = None
    last_txn = None
    
    try:
        with get_db_connection() as conn:
            # Connectivity check
            _exec(conn, "SELECT 1")
            db_ok = True
            
            # Last Ingestion Stats (Bets)
            cursor = _exec(conn, "SELECT MAX(created_at) as last_bet FROM bets")
            row = cursor.fetchone()
            if row: last_bet = row['last_bet']
            
            # Last Ingestion Stats (Transactions)
            cursor = _exec(conn, "SELECT MAX(created_at) as last_txn FROM transactions")
            row = cursor.fetchone()
            if row: last_txn = row['last_txn']
    except Exception as e:
        print(f"[HEALTH] DB Diagnostic Failed: {e}")

    return {
        "status": "Healthy" if db_ok else "Degraded",
        "version": "1.2.1-prod",
        "env": settings.APP_ENV,
        "database_connected": db_ok,
        "database_url_present": bool(settings.DATABASE_URL),
        "basement_password_present": bool(settings.BASEMENT_PASSWORD),
        "vercel_env": os.environ.get("VERCEL") == "1",
        "ingestion": {
            "last_bet_recorded": last_bet,
            "last_transaction_recorded": last_txn
        }
    }


# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"Global Exception: {exc}") # Log it for debugging
    return JSONResponse(
        status_code=500,
        content={"message": f"Internal Server Error: {str(exc)}"},
    )

from datetime import datetime, timedelta, timezone

# ... (Global Exception Handler above) ...

odds_client = OddsAPIClient()

# --- Analytics Cache ---
_analytics_engines = {}
_analytics_refresh_times = {}
ANALYTICS_TTL = timedelta(seconds=60) # Cache for 60 seconds

# --- Research Cache ---
_research_cache = {
    "data": None,
    "last_updated": None
}
RESEARCH_TTL = timedelta(minutes=5)

# --- Top Picks Cache (avoid N client-side analyze calls) ---
_top_picks_cache = {}
TOP_PICKS_TTL = timedelta(seconds=90)

def invalidate_analytics_cache(user_id=None):
    """Invalidate cached AnalyticsEngine so edits to bets immediately reflect in UI."""
    try:
        if user_id in _analytics_engines:
            _analytics_engines.pop(user_id, None)
        if user_id in _analytics_refresh_times:
            _analytics_refresh_times.pop(user_id, None)
    except Exception:
        pass


def get_analytics_engine(user_id=None):
    global _analytics_engines, _analytics_refresh_times
    
    now = datetime.now()
    
    # Refresh if None or expired for this user
    cache = _analytics_engines.get(user_id)
    last_refresh = _analytics_refresh_times.get(user_id)
    
    if cache is None or (last_refresh and now - last_refresh > ANALYTICS_TTL):
        from src.analytics import AnalyticsEngine
        print(f"[API] Refreshing Analytics Engine for user: {user_id or 'all'}...")
        cache = AnalyticsEngine(user_id=user_id)
        _analytics_engines[user_id] = cache
        _analytics_refresh_times[user_id] = now
    
    return cache

# Cors configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# @app.get("/")
# def read_root():
#    return {
#        "status": "API Active",
#        "frontend": "Not Served (Static Routing Failed)",
#        "tip": "Check Vercel Output Directory settings if you see this."
#    }

@app.get("/api/stats")
async def get_stats(user: dict = Depends(get_current_user)):
    user_id = user.get("sub")
    engine = get_analytics_engine(user_id=user_id)
    return engine.get_summary(user_id=user_id)

@app.get("/api/analytics/series")
async def get_analytics_series(user: dict = Depends(get_current_user)):
    user_id = user.get("sub")
    engine = get_analytics_engine(user_id=user_id)
    # Settled-only equity curve for performance tab.
    return engine.get_time_series_settled_equity(user_id=user_id)

@app.get("/api/analytics/drawdown")
async def get_analytics_drawdown(user: dict = Depends(get_current_user)):
    user_id = user.get("sub")
    engine = get_analytics_engine(user_id=user_id)
    return engine.get_drawdown_metrics(user_id=user_id)

@app.get("/api/breakdown/{field}")
async def get_breakdown(field: str, user: dict = Depends(get_current_user)):
    user_id = user.get("sub")
    engine = get_analytics_engine(user_id=user_id)
    if field == "player":
        return engine.get_player_performance(user_id=user_id)
    if field == "monthly":
        return engine.get_monthly_performance(user_id=user_id)
    if field == "edge":
        return engine.get_edge_analysis(user_id=user_id)
    return engine.get_breakdown(field, user_id=user_id)

@app.get("/api/bets")
async def get_bets(user: dict = Depends(get_current_user)):
    """Return settled bets only (UI 'Transactions' tab).

We keep financial ledger data separate under /api/financials/*.
"""
    user_id = user.get("sub")
    engine = get_analytics_engine(user_id=user_id)
    # Settled-only for ROI/performance: exclude pending/open + void placeholders
    bets = engine.get_all_bets(user_id=user_id)
    return [b for b in bets if (b.get('status') or '').upper() not in ('PENDING', 'OPEN', 'VOID')]

@app.get("/api/bets/open")
async def get_open_bets(user: dict = Depends(get_current_user)):
    """Return open/unsettled bets for a separate 'Open Bets' section."""
    user_id = user.get("sub")
    engine = get_analytics_engine(user_id=user_id)
    bets = engine.get_all_bets(user_id=user_id)
    return [b for b in bets if (b.get('status') or '').upper() in ('PENDING', 'OPEN')]

@app.get("/api/odds/{sport}")
async def get_odds(sport: str):
    """
    Fetches live odds for a sport. 
    Sport can be 'NFL', 'NBA', etc. or full key.
    """
    # Simply pass through. Client handles key mapping if needed or we assume UI sends correct key.
    # checking client implementation... 
    # it seems client.get_odds takes key directly.
    # UI sends 'NFL' usually?
    # Let's verify mapping.
    sport_key = sport # for now
    if sport == 'NFL': sport_key = 'americanfootball_nfl'
    elif sport == 'NCAAM': sport_key = 'basketball_ncaab'
    elif sport == 'NCAAF': sport_key = 'americanfootball_ncaaf'
    elif sport == 'EPL': sport_key = 'soccer_epl'
    
    return odds_client.get_odds(sport_key)

@app.get("/api/balances")
async def get_balances(user: dict = Depends(get_current_user)):
    user_id = user.get("sub")
    engine = get_analytics_engine(user_id=user_id)
    return engine.get_balances(user_id=user_id)


@app.get("/api/balances/snapshots/latest")
async def get_latest_balance_snapshots(user: dict = Depends(get_current_user)):
    """Return latest balance snapshots per provider.

    This is the UI source-of-truth for sportsbook balances.
    """
    from src.database import fetch_latest_balance_snapshots

    user_id = user.get("sub")
    return fetch_latest_balance_snapshots(user_id=str(user_id))


@app.post("/api/balances/snapshots")
async def add_balance_snapshot(request: Request):
    """Manually add a balance snapshot (Basement key auth only).

    Payload: { provider: 'FanDuel'|'DraftKings'|..., account_id: 'Main'|'User2' (aka Primary/Secondary), balance: number, captured_at?: iso, note?: str, source?: str }
    """
    try:
        payload = await request.json()
        provider = (payload or {}).get('provider')
        balance = (payload or {}).get('balance')
        acc_raw = (payload or {}).get('account_id')

        if provider is None or balance is None:
            raise HTTPException(status_code=400, detail='provider and balance are required')

        # Require explicit account_id (Primary/Secondary) so snapshots stay clean.
        if acc_raw is None or str(acc_raw).strip() == '':
            raise HTTPException(status_code=400, detail='account_id is required (Primary/Secondary)')

        acc = str(acc_raw).strip()
        # Allow friendly labels
        if acc.lower() == 'primary':
            acc = 'Main'
        elif acc.lower() == 'secondary':
            acc = 'User2'

        from src.database import insert_balance_snapshot
        from src.sync_jobs import DEFAULT_USER_ID

        ok = insert_balance_snapshot({
            'provider': provider,
            'account_id': acc,
            'balance': float(balance),
            'captured_at': payload.get('captured_at'),
            'source': payload.get('source') or 'manual',
            'note': payload.get('note'),
            'raw_data': payload.get('raw_data'),
            'user_id': DEFAULT_USER_ID,
        })
        return {'status': 'success' if ok else 'error'}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/stats/period")
async def get_period_stats(days: Optional[int] = None, year: Optional[int] = None, user: dict = Depends(get_current_user)):
    user_id = user.get("sub")
    engine = get_analytics_engine(user_id=user_id)
    return engine.get_period_stats(days=days, year=year, user_id=user_id)

@app.get("/api/financials")
async def get_financials(user: dict = Depends(get_current_user)):
    user_id = user.get("sub")
    engine = get_analytics_engine(user_id=user_id)
    return engine.get_financial_summary(user_id=user_id)

@app.get("/api/financials/reconciliation")
async def get_reconciliation(user: dict = Depends(get_current_user)):
    """Returns per-book reconciliation data for validating transaction ingestion."""
    user_id = user.get("sub")
    engine = get_analytics_engine(user_id=user_id)
    return engine.get_reconciliation_view(user_id=user_id)

# ---------------------------------------------------------------------------
# BATCH DASHBOARD — single request replaces 16 parallel calls
# ---------------------------------------------------------------------------
@app.get("/api/dashboard")
async def get_dashboard(user: dict = Depends(get_current_user)):
    """
    Returns all data needed for the initial dashboard load in a single response.
    Replaces 16 parallel API calls (×2 in StrictMode) with 1.
    """
    from src.database import fetch_latest_balance_snapshots

    user_id = user.get("sub")
    engine = get_analytics_engine(user_id=user_id)

    current_year = datetime.now().year

    # All computations share the cached engine (60s TTL), no extra DB hits
    bets_all = engine.get_all_bets(user_id=user_id)
    settled = [b for b in bets_all if (b.get('status') or '').upper() not in ('PENDING', 'OPEN', 'VOID')]

    return {
        "stats": engine.get_summary(user_id=user_id),
        "bets": settled,
        "sport_breakdown": engine.get_breakdown("sport", user_id=user_id),
        "player_breakdown": engine.get_player_performance(user_id=user_id),
        "monthly_breakdown": engine.get_monthly_performance(user_id=user_id),
        "bet_type_breakdown": engine.get_breakdown("bet_type", user_id=user_id),
        "balance_snapshots": fetch_latest_balance_snapshots(user_id=str(user_id)),
        "financials": engine.get_financial_summary(user_id=user_id),
        "reconciliation": engine.get_reconciliation_view(user_id=user_id),
        "time_series": engine.get_time_series_settled_equity(user_id=user_id),
        "drawdown": engine.get_drawdown_metrics(user_id=user_id),
        "edge_breakdown": engine.get_edge_analysis(user_id=user_id),
        "period_stats": {
            "7d": engine.get_period_stats(days=7, user_id=user_id),
            "30d": engine.get_period_stats(days=30, user_id=user_id),
            "ytd": engine.get_period_stats(year=current_year, user_id=user_id),
            "all": engine.get_period_stats(user_id=user_id),
        }
    }

@app.get("/api/ledger/settled")
async def get_settled_bet_ledger(user: dict = Depends(get_current_user)):
    """Audit ledger: settled bets added *after* the latest balance snapshot per provider.

    This lets us treat snapshots as the baseline, and show the incremental P/L from newly-added
    bets (e.g. via Add Bet Slip) as a ledger delta.
    """
    from src.database import get_db_connection, _exec

    user_id = user.get("sub")

    q = """
    WITH latest AS (
      SELECT DISTINCT ON (provider, COALESCE(account_id,''))
        provider,
        COALESCE(account_id,'') AS account_id,
        captured_at,
        balance
      FROM balance_snapshots
      WHERE user_id = %(uid)s
      ORDER BY provider, COALESCE(account_id,''), captured_at DESC
    )
    SELECT
      b.id AS bet_id,
      b.provider,
      COALESCE(b.account_id, 'Main') AS account_id,
      b.created_at,
      b.date,
      b.description,
      b.selection,
      b.bet_type,
      b.wager,
      b.profit,
      b.status,
      l.captured_at AS baseline_captured_at,
      l.balance AS baseline_balance
    FROM bets b
    JOIN latest l ON l.provider = b.provider AND COALESCE(l.account_id,'') = COALESCE(b.account_id,'')
    WHERE b.user_id = %(uid)s
      AND (b.status IS NOT NULL AND UPPER(b.status) NOT IN ('PENDING','OPEN','VOID'))
      AND b.created_at > l.captured_at
    ORDER BY b.created_at DESC
    """

    with get_db_connection() as conn:
        rows = _exec(conn, q, {"uid": str(user_id)}).fetchall()

    # group by provider
    out = {}
    for r in rows:
        d = dict(r)
        p = d.get('provider') or 'Unknown'
        out.setdefault(p, []).append(d)

    return {
        "generated_at": datetime.utcnow().isoformat() + 'Z',
        "providers": out,
    }


    user_id = user.get("sub")
    engine = get_analytics_engine(user_id=user_id)

    current_year = datetime.now().year

    # All computations share the cached engine (60s TTL), no extra DB hits
    bets_all = engine.get_all_bets(user_id=user_id)
    settled = [b for b in bets_all if (b.get('status') or '').upper() not in ('PENDING', 'OPEN', 'VOID')]

    return {
        "stats": engine.get_summary(user_id=user_id),
        "bets": settled,
        "sport_breakdown": engine.get_breakdown("sport", user_id=user_id),
        "player_breakdown": engine.get_player_performance(user_id=user_id),
        "monthly_breakdown": engine.get_monthly_performance(user_id=user_id),
        "bet_type_breakdown": engine.get_breakdown("bet_type", user_id=user_id),
        "balance_snapshots": fetch_latest_balance_snapshots(user_id=str(user_id)),
        "financials": engine.get_financial_summary(user_id=user_id),
        "reconciliation": engine.get_reconciliation_view(user_id=user_id),
        "time_series": engine.get_time_series_settled_equity(user_id=user_id),
        "drawdown": engine.get_drawdown_metrics(user_id=user_id),
        "edge_breakdown": engine.get_edge_analysis(user_id=user_id),
        "period_stats": {
            "7d": engine.get_period_stats(days=7, user_id=user_id),
            "30d": engine.get_period_stats(days=30, user_id=user_id),
            "ytd": engine.get_period_stats(year=current_year, user_id=user_id),
            "all": engine.get_period_stats(user_id=user_id),
        }
    }

# ---------------------------------------------------------------------------
# DETAIL ENDPOINTS — heavy data fetched on demand only
# ---------------------------------------------------------------------------
@app.get("/api/bets/{bet_id}")
async def get_bet_detail(bet_id: int, user: dict = Depends(get_current_user)):
    """Return full bet row including raw_text (detail/expand view)."""
    from src.database import fetch_bet_detail
    user_id = user.get("sub")
    row = fetch_bet_detail(bet_id, user_id=user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Bet not found")
    return row

@app.get("/api/research/history/{prediction_id}")
async def get_research_detail(prediction_id: str, user: dict = Depends(get_current_user)):
    """Return full model prediction including inputs_json, outputs_json, narrative_json."""
    from src.database import fetch_model_prediction_detail
    row = fetch_model_prediction_detail(prediction_id)
    if not row:
        raise HTTPException(status_code=404, detail="Prediction not found")
    return row


@app.get("/api/financials/inplay/series")
async def get_inplay_series(days: int = 90, user: dict = Depends(get_current_user)):
    """Daily total-in-play balance trend from balance_snapshots.

    Returns one point per ET day using the *latest* snapshot per provider per day.
    """
    from src.database import get_db_connection, _exec

    user_id = user.get("sub")
    try:
        days = int(days)
    except Exception:
        days = 90
    days = max(7, min(days, 365))

    with get_db_connection() as conn:
        rows = _exec(conn, """
          WITH snaps AS (
            SELECT
              provider,
              COALESCE(account_id, 'Main') AS account_id,
              (captured_at AT TIME ZONE 'America/New_York')::date::text AS day_et,
              balance,
              captured_at
            FROM balance_snapshots
            WHERE (%(user_id)s IS NULL OR user_id = %(user_id)s)
              AND captured_at > NOW() - (%(d)s || ' days')::interval
          ), latest_per_provider_account_day AS (
            SELECT DISTINCT ON (provider, account_id, day_et)
              provider,
              account_id,
              day_et,
              balance,
              captured_at
            FROM snaps
            ORDER BY provider, account_id, day_et, captured_at DESC
          ), profits_after_snapshot AS (
            SELECT
              l.day_et,
              l.provider,
              l.account_id,
              COALESCE(SUM(b.profit), 0)::float AS profit_after
            FROM latest_per_provider_account_day l
            LEFT JOIN bets b
              ON b.provider = l.provider
             AND COALESCE(b.account_id, 'Main') = l.account_id
             AND UPPER(COALESCE(b.status,'')) NOT IN ('PENDING','OPEN','VOID')
             AND b.created_at > l.captured_at
             AND b.created_at < ((l.day_et::date + interval '1 day')::timestamp AT TIME ZONE 'America/New_York')
            GROUP BY l.day_et, l.provider, l.account_id
          )
          SELECT
            l.day_et AS day,
            SUM(l.balance)::float AS reported_total_in_play,
            SUM((l.balance + p.profit_after))::float AS computed_total_in_play
          FROM latest_per_provider_account_day l
          LEFT JOIN profits_after_snapshot p
            ON p.day_et=l.day_et AND p.provider=l.provider AND p.account_id=l.account_id
          GROUP BY l.day_et
          ORDER BY l.day_et ASC
        """, {"user_id": str(user_id) if user_id else None, "d": int(days)}).fetchall()

    series = [
        {
            "day": r.get('day'),
            "reported_total_in_play": float(r.get('reported_total_in_play') or 0),
            "computed_total_in_play": float(r.get('computed_total_in_play') or 0),
        }
        for r in rows
    ]

    return {
        "generated_at": datetime.utcnow().isoformat() + 'Z',
        "days": int(days),
        "series": series,
    }


@app.post("/api/sync/fanduel/token")
async def sync_fanduel_token(request: Request):
    """Sync FanDuel history using a manually provided cURL or Token.

    Auth: Basement password (X-BASEMENT-KEY). Does NOT require Supabase auth.
    """
    try:
        from src.sync_jobs import DEFAULT_USER_ID
        user_id = DEFAULT_USER_ID
        data = await request.json()
        raw_input = data.get("curl_or_token", "")
        
        if not raw_input:
            # TRY STORED TOKEN
            from src.database import get_user_preference
            token = get_user_preference(str(user_id), "fanduel_token")
            if not token:
                raise HTTPException(status_code=400, detail="No stored token found. Please provide cURL.")
        else:
            # PARSE & SAVE TOKEN
            token = raw_input.strip()
            if "curl " in raw_input or "-H " in raw_input:
                import re
                match = re.search(r"x-authentication:\s*([^\s'\"]+)", raw_input, re.IGNORECASE)
                if match:
                    token = match.group(1)
            
            if not token.startswith("eyJ"):
                raise HTTPException(status_code=400, detail="Invalid Token format")
                
            # Save for future use
            from src.database import update_user_preference
            update_user_preference(str(user_id), "fanduel_token", token)
            
        from src.api_clients.fanduel_client import FanDuelAPIClient
        client = FanDuelAPIClient(auth_token=token)
        
        # Fetch Bets
        bets = client.fetch_bets(to_record=50) # Fetch last 50
        
        # Ingest into DB (similar to parse_slip but internal object)
        from src.database import insert_bet_v2
        from src.services.event_linker import EventLinker
        linker = EventLinker()
        
        user_id = user.get("sub")
        saved_count = 0
        
        for bet in bets:
            # Check if exists (Idempotency) - FD betId is unique
            # We use betId as hash_id or part of it?
            # Schema uses hash_id.
            
            # Construct Doc
            profit = bet.get('profit', 0)
            status = bet.get('status', 'PENDING')
            
            # Map Sport to standard keys if possible
            sport = bet.get('sport', 'Unknown')
            
            doc = {
                "user_id": user_id,
                "account_id": f"FD_{user_id}", # Virtual account
                "provider": "FanDuel",
                "date": bet['date'],
                "sport": sport,
                "bet_type": bet['bet_type'],
                "wager": bet['wager'],
                "profit": round(profit, 2),
                "status": status,
                "description": bet['description'],
                "selection": bet['selection'],
                "odds": bet.get('odds', 0), # American
                "is_live": bet.get('is_live', False),
                "is_bonus": bet.get('is_bonus', False),
                "raw_text": bet.get('raw_text'),
                "external_id": bet.get('external_id') or bet.get('id') or bet.get('bet_id'),
                "source": "sync_api",
            }
            
            # Unique Hash for FD: Provider|BetId ? 
            # But we don't have BetID in standardised 'bet' object returned by client? 
            # Client returns dict. Let's ensure Client returns external_id if available.
            # I need to update Client to pass 'betId' in raw_text or separate field?
            # It's in raw_text.
            
            import hashlib
            # Use description + date + wager as hash if no ID
            # Better: Update Client to return 'id'.
            # For now, legacy hash:
            raw_string = f"{user_id}|FanDuel|{doc['date']}|{doc['description']}|{doc['wager']}"
            doc['hash_id'] = hashlib.sha256(raw_string.encode()).hexdigest()
            doc['is_parlay'] = "parlay" in doc['bet_type'].lower()
            
            # Create Leg (Simplified for SGP/Parlay, we just store one summary leg or try to split?)
            # Parsing "A | B | C" into legs is complex.
            # Storing as single composite leg for now.
            leg = {
                "leg_type": doc['bet_type'], 
                "selection": doc['selection'],
                "market_key": doc['bet_type'],
                "odds_american": doc['odds'],
                "status": doc['status'],
                "subject_id": None, 
                "side": None, 
                "line_value": None
            }
            
            # Link (Best Effort)
            link_result = linker.link_leg(leg, doc['sport'], doc['date'], doc['description'])
            leg['event_id'] = link_result['event_id']
            leg['link_status'] = link_result['link_status']
            
            try:
                insert_bet_v2(doc, legs=[leg])
                saved_count += 1
            except Exception as e:
                # Log duplicates or failures
                # If duplicate key, it's fine. If usage error, we need to know.
                print(f"[Sync] Failed to insert bet: {e}")
                pass
                
        return {"status": "success", "bets_fetched": len(bets), "bets_saved": saved_count}

    except Exception as e:
        print(f"[FD Sync] Error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/sync/draftkings")
async def sync_draftkings(request: Request, user: dict = Depends(get_current_user)):
    """Queues a DraftKings settled-bets ingest job (new pipeline).

    IMPORTANT:
    - We no longer scrape DraftKings from the Vercel API (serverless).
    - This endpoint now *enqueues* a DK_INGEST job into sync_jobs.
    - A persistent local worker (scripts/sync_worker.py) must claim and run it
      using a logged-in Chrome profile (DK_PROFILE_PATH).

    Returns: { status: 'queued', job_id }
    """
    from src.database import get_db_connection, _exec, init_dk_ingest_db
    import json as _json
    from datetime import datetime, timezone

    user_id = (user or {}).get('sub')
    if not user_id:
        raise HTTPException(status_code=401, detail='Unauthorized')

    # Ensure schema exists (idempotent)
    try:
        init_dk_ingest_db()
    except Exception as e:
        print(f"[DK Sync] init_dk_ingest_db warn: {e}")

    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}

    account_id = str(body.get('account_id') or 'Main')
    payload = _json.dumps({"book": "DraftKings", "user_id": str(user_id), "account_id": account_id})

    with get_db_connection() as conn:
        cur = _exec(
            conn,
            """
            INSERT INTO sync_jobs (user_id, provider, status, requested_at, job_type, payload_json)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (str(user_id), 'draftkings', 'QUEUED', datetime.now(timezone.utc), 'DK_INGEST', payload),
        )
        row = cur.fetchone()
        conn.commit()
        job_id = int(row['id'])

    return {
        'status': 'queued',
        'job_id': job_id,
        'note': 'Run scripts/sync_worker.py on the Mac to process the job (requires DK_PROFILE_PATH logged in).'
    }

@app.post("/api/parse-slip")
async def parse_slip(request: Request, user: dict = Depends(get_current_user)):
    try:
        data = await request.json()
        from src.utils.normalize import normalize_provider
        raw_text = data.get("raw_text")
        sportsbook = normalize_provider(data.get("sportsbook", "DK"))
        
        def _to_ui_schema(parsed: dict) -> dict:
            return {
                "event_name": parsed.get("description"),
                "sport": parsed.get("sport"),
                "market_type": parsed.get("bet_type"),
                "selection": parsed.get("selection"),
                "price": {"american": parsed.get("odds"), "decimal": None},
                "stake": parsed.get("wager"),
                "status": parsed.get("status", "PENDING"),
                "placed_at": parsed.get("date"),
                "confidence": 0.95,  # Fixed confidence for heuristic parsers
                "is_live": parsed.get("is_live", False),
                "is_bonus": parsed.get("is_bonus", False),
                "profit": parsed.get("profit"),
                "provider": parsed.get("provider", sportsbook),
                "raw_text": parsed.get("raw_text"),
                # IMPORTANT: carry sportsbook-native id through so /api/bets/manual can upsert
                "external_id": parsed.get("external_id"),
            }

        if sportsbook == "DraftKings":
            # Primary: DK 'My Bets' text dump parser
            from src.parsers.draftkings_text import DraftKingsTextParser
            parser = DraftKingsTextParser()
            results = parser.parse(raw_text or "")

            # Fallback: DK 'Card View' dump parser (often used when pasting multiple slips)
            if not results:
                try:
                    from src.parsers.draftkings import DraftKingsParser
                    results = DraftKingsParser().parse_text_dump(raw_text or "")
                except Exception:
                    results = []

            if not results:
                # Last resort: LLM (single bet)
                from src.parsers.llm_parser import LLMSlipParser
                parsed = LLMSlipParser().parse(raw_text, sportsbook)
                return parsed

            # If multiple bets were pasted, return a batch.
            if len(results) > 1:
                return {"bets": [_to_ui_schema(x) for x in results], "bets_found": len(results)}

            return _to_ui_schema(results[0])

        if sportsbook == "FanDuel":
            from src.parsers.fanduel import FanDuelParser
            parser = FanDuelParser()
            results = parser.parse(raw_text)
            if not results:
                raise Exception("Failed to parse FanDuel slip")

            # FanDuel settled-bets paste usually includes many bets.
            if len(results) > 1:
                return {"bets": [_to_ui_schema(x) for x in results], "bets_found": len(results)}

            return _to_ui_schema(results[0])

        # Fallback: LLM parser (single-bet)
        from src.parsers.llm_parser import LLMSlipParser
        parser = LLMSlipParser()
        result = parser.parse(raw_text, sportsbook)
        
        # Add duplicate check
        user_id = user.get("sub")
        # For MVP, we check the hash in the DB if we had it. 
        # For now, we return the result.
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/bets/manual")
async def save_manual_bet(request: Request, user: dict = Depends(get_current_user)):
    try:
        bet_data = await request.json()
        user_id = user.get("sub")
        bet_data['user_id'] = user_id
        
        from src.utils.sport_normalization import normalize_sport

        # Basic mapping to DB schema
        status = bet_data.get("status", "PENDING").upper()
        stake = float(bet_data.get("stake", 0))
        american_odds = bet_data.get("price", {}).get("american")
        decimal_odds = bet_data.get("price", {}).get("decimal")
        
        # Enforce: settled bets must include odds
        if status in ("WON", "LOST", "PUSH"):
            # accept american odds from either price.american or top-level odds
            american_check = bet_data.get("price", {}).get("american")
            if american_check is None and bet_data.get("odds") is not None:
                american_check = bet_data.get("odds")
            if american_check is None:
                raise HTTPException(status_code=400, detail="Odds are required for settled bets (WON/LOST/PUSH).")

        # Calculate profit if not provided
        profit = bet_data.get("profit")
        if profit is None:
            if status == "WON":
                if decimal_odds and decimal_odds > 1:
                    profit = stake * (decimal_odds - 1)
                elif american_odds:
                    if american_odds > 0:
                        profit = stake * (american_odds / 100)
                    else:
                        profit = stake * (100 / abs(american_odds))
                else:
                    profit = 0.0
            elif status == "LOST":
                profit = -stake
            else:
                profit = 0.0

        placed_at = bet_data.get("placed_at", "")
        # Handle '2026-01-11 19:57:51' or ISO format
        date_part = placed_at.split(" ")[0].split("T")[0] if placed_at else datetime.now().strftime("%Y-%m-%d")

        # Account grouping (TEXT). We intentionally allow human-friendly values like "Main" or "User2".
        raw_acc_id = bet_data.get("account_id")
        account_id = str(raw_acc_id).strip() if raw_acc_id is not None and str(raw_acc_id).strip() else None
        if account_id:
            if account_id.lower() == 'primary':
                account_id = 'Main'
            elif account_id.lower() == 'secondary':
                account_id = 'User2'

        # Normalize provider name
        provider_raw = bet_data.get("sportsbook") or bet_data.get("provider", "")
        if provider_raw.upper() == "DK":
            provider = "DraftKings"
        elif provider_raw.upper() in ["FD", "FANDUEL"]:
            provider = "FanDuel"
        else:
            provider = provider_raw

        # Extract sportsbook-native bet id from raw_text when present.
        external_id = None
        try:
            import re
            rt = bet_data.get('raw_text') or ''
            # FanDuel format
            m = re.search(r"BET ID:\s*([^\n\r]+)", rt, re.IGNORECASE)
            if m:
                external_id = m.group(1).strip()

            # DraftKings slips embed the DK id inline (no 'BET ID:' prefix)
            if external_id is None:
                m = re.search(r"(DK\d{10,})", rt)
                if m:
                    external_id = m.group(1)
        except Exception:
            external_id = None

        doc = {
            "user_id": user_id,
            "account_id": account_id,
            "provider": provider,
            "date": date_part,
            # Normalize sport to canonical codes (prevents duplicates by casing/alias).
            "sport": normalize_sport(bet_data.get("sport") or "Unknown"),
            "bet_type": bet_data.get("market_type"),
            "wager": stake,
            "profit": round(profit, 2) if profit is not None else 0.0,
            "status": status,
            "description": bet_data.get("event_name"),
            "selection": bet_data.get("selection"),
            "odds": american_odds,
            # Optional: closing odds (used by DB insert; default None)
            "closing_odds": (bet_data.get("closing_odds")
                             or (bet_data.get("closing_price") or {}).get("american")
                             or None),
            # Prefer explicit external_id from client parse; fallback to raw_text extraction above.
            "external_id": bet_data.get('external_id') or external_id,
            "is_live": bet_data.get("is_live", False),
            "is_bonus": bet_data.get("is_bonus", False),
            "raw_text": bet_data.get("raw_text"),
            "source": "manual_add",
        }
        
        # Generate Hash for Idempotency
        import hashlib
        raw_string = f"{user_id}|{doc['provider']}|{doc['date']}|{doc['description']}|{doc['wager']}"
        doc['hash_id'] = hashlib.sha256(raw_string.encode()).hexdigest()
        doc['is_parlay'] = False 

        # Create Leg Object
        from src.services.event_linker import EventLinker
        linker = EventLinker()
        
        leg = {
            "leg_type": doc['bet_type'], 
            "selection": doc['selection'],
            "market_key": doc['bet_type'],
            "odds_american": doc['odds'],
            "status": doc['status'],
            "subject_id": None, 
            "side": None, 
            "line_value": bet_data.get("line") or bet_data.get("points")
        }
        
        # Link Event
        link_result = linker.link_leg(leg, doc['sport'], doc['date'], doc['description'])
        leg['event_id'] = link_result['event_id']
        leg['selection_team_id'] = link_result['selection_team_id']
        leg['link_status'] = link_result['link_status']
        # leg['side'] ?? Manual entry might not have explicit side (HOME/AWAY).
        # We can infer it if we linked the team.
        # For now, let's leave side null if not explicit.
        
        from src.database import insert_bet_v2
        insert_bet_v2(doc, legs=[leg])

        # Ensure analytics reflect the new/updated bet immediately
        invalidate_analytics_cache(user_id)

        return {"status": "success", "link_status": leg['link_status'], "event_id": leg['event_id']}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
@app.post("/api/transactions/manual")
async def add_manual_transaction(request: Request, user: dict = Depends(get_current_user)):
    """Manually add a deposit/withdrawal line (affects financials).

Payload: {
  provider: 'DraftKings'|'FanDuel'|...,
  date: 'YYYY-MM-DD',
  type: 'Deposit'|'Withdrawal',
  amount: number,
  description?: str
}

Note: this does not directly change sportsbook-reported balances; it is used for net cashflow
and reconciliation against snapshots.
"""
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid payload")

        provider = payload.get('provider') or payload.get('sportsbook')
        acc_raw = payload.get('account_id')
        typ = (payload.get('type') or '').strip()
        if typ not in ('Deposit', 'Withdrawal'):
            raise HTTPException(status_code=400, detail="type must be Deposit or Withdrawal")

        amt = payload.get('amount')
        if amt is None:
            raise HTTPException(status_code=400, detail="amount is required")
        amt = float(amt)
        if amt <= 0:
            raise HTTPException(status_code=400, detail="amount must be > 0")

        date = payload.get('date') or payload.get('placed_at')
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')
        date = str(date).split('T')[0].split(' ')[0]

        desc = payload.get('description') or f"Manual {typ}"

        # Require account_id for Primary/Secondary attribution
        if acc_raw is None or str(acc_raw).strip() == '':
            raise HTTPException(status_code=400, detail="account_id is required (Primary/Secondary)")
        acc = str(acc_raw).strip()
        if acc.lower() == 'primary':
            acc = 'Main'
        elif acc.lower() == 'secondary':
            acc = 'User2'

        import uuid
        txn = {
            'provider': provider,
            'account_id': acc,
            'txn_id': f"manual_{uuid.uuid4().hex[:12]}",
            'date': date,
            'type': typ,
            'description': desc,
            'amount': amt if typ == 'Deposit' else -abs(amt),
            'balance': None,
            'user_id': user.get('sub'),
            'raw_data': payload,
        }

        from src.database import insert_transaction
        ok = insert_transaction(txn)
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to insert transaction")

        invalidate_analytics_cache(user.get('sub'))
        return {'status': 'success'}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/ingest/odds/{league}")
async def ingest_odds(league: str, request: Request):
    """
    Trigger odds ingestion for a league.
    Optional Query Params: date (YYYYMMDD)
    """
    from src.services.odds_fetcher_service import OddsFetcherService
    from src.services.odds_adapter import OddsAdapter
    
    try:
        data = await request.json()
    except:
        data = {}
        
    date_str = data.get("date") # Optional override
    if not date_str:
        # Default to today in YYYYMMDD
        date_str = datetime.now().strftime("%Y%m%d")

    fetcher = OddsFetcherService()
    adapter = OddsAdapter()
    
    # Fetch
    raw_games = fetcher.fetch_odds(league.upper(), start_date=date_str)
    
    # Normalize & Store
    # Provider is Action Network (primary in Fetcher)
    count = adapter.normalize_and_store(raw_games, league=league.upper(), provider="action_network")
    
    return {"status": "success", "league": league, "date": date_str, "snapshots_ingested": count}

@app.patch("/api/bets/{bet_id}")
async def update_bet(bet_id: int, request: Request, user: dict = Depends(get_current_user)):
    """Inline edit endpoint for manual bet corrections."""
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid payload")

        allowed = {
            'provider', 'account_id', 'date', 'sport', 'bet_type', 'wager', 'odds', 'profit', 'status',
            'description', 'selection', 'event_text'
        }
        fields = {k: payload.get(k) for k in allowed if k in payload}

        # Normalize sport to avoid duplicates like "World Cup" vs "WORLD CUP".
        if 'sport' in fields:
            from src.utils.sport_normalization import normalize_sport
            fields['sport'] = normalize_sport(fields.get('sport'))

        update_note = payload.get('update_note') or payload.get('audit_note')

        from src.database import update_bet_fields
        uid = user.get('sub')
        ok = update_bet_fields(int(bet_id), fields, user_id=uid, update_note=update_note)
        if not ok:
            raise HTTPException(status_code=404, detail="Bet not found")

        invalidate_analytics_cache(uid)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.patch("/api/bets/{bet_id}/settle")
async def settle_bet(bet_id: int, request: Request, user: dict = Depends(get_current_user)):
    try:
        data = await request.json()
        status = data.get("status")
        if status not in ['WON', 'LOST', 'PUSH', 'PENDING']:
            raise HTTPException(status_code=400, detail="Invalid status")
            
        uid = user.get("sub")
        from src.database import update_bet_status
        success = update_bet_status(bet_id, status, user_id=uid)
        if not success:
            raise HTTPException(status_code=404, detail="Bet not found")
        invalidate_analytics_cache(uid)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/bets/bulk-status")
async def bulk_status_update(request: Request, user: dict = Depends(get_current_user)):
    try:
        data = await request.json()
        bet_ids = data.get("bet_ids", [])
        status = data.get("status")
        if not bet_ids or status not in ['WON', 'LOST', 'PUSH', 'PENDING']:
            raise HTTPException(status_code=400, detail="Invalid request data")
            
        uid = user.get("sub")
        from src.database import bulk_update_bet_status
        count = bulk_update_bet_status(bet_ids, status, user_id=uid)
        invalidate_analytics_cache(uid)
        return {"status": "success", "updated_count": count}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/bets/bulk-delete")
async def bulk_delete(request: Request, user: dict = Depends(get_current_user)):
    try:
        data = await request.json()
        bet_ids = data.get("bet_ids", [])
        if not bet_ids:
            raise HTTPException(status_code=400, detail="No bet IDs provided")
            
        uid = user.get("sub")
        from src.database import bulk_delete_bets
        count = bulk_delete_bets(bet_ids, user_id=uid)
        invalidate_analytics_cache(uid)
        return {"status": "success", "deleted_count": count}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/bets/{bet_id}")
async def remove_bet(bet_id: int, user: dict = Depends(get_current_user)):
    try:
        uid = user.get("sub")
        from src.database import delete_bet
        success = delete_bet(bet_id, user_id=uid)
        if not success:
            # Fallback for legacy single-user rows where bets.user_id may be NULL/empty or a fixed id.
            success = delete_bet(bet_id, user_id=None)
        if not success:
            raise HTTPException(status_code=404, detail="Bet not found")
        invalidate_analytics_cache(uid)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/audit/bets/sport-mismatches")
async def audit_bet_sport_mismatches(days: int = 60, limit: int = 800, user: dict = Depends(get_current_user)):
    """Auditor agent: find bets whose `sport` appears wrong.

    Primary method: matchup -> events table -> league mismatch.
    Fallback: for UNKNOWN sports (common for parlays/SGP text), suggest via detect_sport.
    """
    try:
        uid = user.get("sub")
        from src.services.bet_auditor_agent import BetAuditorAgent
        agent = BetAuditorAgent()
        safe_limit = min(int(limit), 5000)
        safe_days = min(int(days), 3650)
        items = agent.audit_sport_mismatches(user_id=uid, days_back=safe_days, limit=safe_limit)
        return {"status": "success", "items": items, "days": safe_days, "limit": safe_limit}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/audit/bets/{bet_id}/apply-sport")
async def apply_bet_sport_fix(bet_id: int, request: Request, user: dict = Depends(get_current_user)):
    """Apply a sport correction (writes to DB + invalidates analytics cache)."""
    try:
        uid = user.get("sub")
        payload = await request.json()
        from src.utils.sport_normalization import normalize_sport
        sport = normalize_sport(payload.get('sport') or '')
        if not sport:
            raise HTTPException(status_code=400, detail="Missing sport")

        from src.database import update_bet_fields
        ok = update_bet_fields(int(bet_id), {"sport": sport}, user_id=uid, update_note="audit: sport corrected")
        if not ok:
            raise HTTPException(status_code=404, detail="Bet not found")

        invalidate_analytics_cache(uid)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/audit/bets/normalize-sport")
async def normalize_bet_sport(limit: int = 50000, user: dict = Depends(get_current_user)):
    """Normalize bet.sport values in DB to prevent duplicates (case/alias).

    Example fixes:
    - World Cup -> EPL (soccer bucket)
    - ncaab -> NCAAM
    - unknown/blank -> UNKNOWN
    """
    try:
        uid = user.get("sub")
        from src.services.sport_cleanup_service import SportCleanupService
        svc = SportCleanupService()
        res = svc.normalize_user_bets_sport(user_id=str(uid), limit=int(limit))
        invalidate_analytics_cache(uid)
        return {"status": "success", **res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/audit/bets/backfill-sport")
async def backfill_bet_sport(days: int = 365, limit: int = 5000, user: dict = Depends(get_current_user)):
    """Backfill/repair bet.sport by re-detecting from raw_text/selection/description."""
    try:
        uid = user.get("sub")
        from datetime import datetime, timedelta
        from src.parsers.sport_detection import detect_sport
        from src.database import get_db_connection, _exec, update_bet_fields
        from src.utils.sport_normalization import normalize_sport

        now = datetime.now()
        cutoff = (now - timedelta(days=int(days))).date().isoformat()

        q = """
        SELECT id, date, sport, raw_text, selection, description, provider
        FROM bets
        WHERE user_id = %s AND date >= %s
        ORDER BY date DESC
        LIMIT %s
        """

        with get_db_connection() as conn:
            rows = _exec(conn, q, (uid, cutoff, int(limit))).fetchall()

        updated = 0
        scanned = 0
        for r in rows:
            b = dict(r)
            scanned += 1
            text = " ".join([
                str(b.get('raw_text') or ''),
                str(b.get('selection') or ''),
                str(b.get('description') or ''),
                str(b.get('provider') or ''),
            ])
            from src.utils.sport_normalization import normalize_sport

            suggested = normalize_sport(detect_sport(text))
            current = normalize_sport(b.get('sport') or '')

            if suggested and suggested != 'UNKNOWN' and suggested != current:
                ok = update_bet_fields(int(b['id']), {"sport": suggested}, user_id=uid, update_note="audit: backfill sport")
                if ok:
                    updated += 1

        invalidate_analytics_cache(uid)
        return {"status": "success", "scanned": scanned, "updated": updated}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/audit/bets/review-fill")
async def review_fill_missing_fields(days: int = 3650, limit: int = 20000, dry_run: bool = True, user: dict = Depends(get_current_user)):
    """Review all bets and backfill missing fields (sport/bet_type/selection).

    dry_run=true returns proposed changes (capped) without writing.
    """
    try:
        uid = user.get('sub')
        from src.services.bet_review_agent import BetReviewAgent
        agent = BetReviewAgent()
        res = agent.backfill_missing_fields(user_id=uid, days_back=int(days), limit=int(limit), dry_run=bool(dry_run))
        if not dry_run:
            invalidate_analytics_cache(uid)
        return {"status": "success", **res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/audit/bets/backfill-event-text")
async def backfill_event_text(
    days: int = 3650,
    limit: int = 20000,
    force: bool = False,
    cursor: int | None = None,
    batch: int = 300,
    user: dict = Depends(get_current_user)
):
    """One-time backfill: populate/repair bets.event_text from raw_text/description/selection.

    This endpoint can be slow on Vercel if you try to process everything in one request.
    Use batching:
      - cursor: last processed id (pagination). First call cursor=null.
      - batch: max rows examined per request.

    - force=false (default): only fills missing event_text
    - force=true: also repairs obviously malformed event_text

    Returns: scanned, updated, next_cursor.
    """
    try:
        uid = user.get('sub')
        from src.config import settings
        from datetime import datetime, timedelta
        from src.database import get_db_connection, _exec

        now = datetime.now()
        cutoff = (now - timedelta(days=int(days))).date().isoformat()

        import re

        def extract_event_text(raw_text: str, description: str, selection: str) -> str | None:
            def clean_side(x: str) -> str:
                x = (x or '').strip()
                x = re.split(r"\s+[+\-−–]\d+(?:\.\d+)?\b", x, maxsplit=1)[0]
                x = re.split(r"\s+\b(over|under)\b\s*\d+(?:\.\d+)?\b", x, flags=re.IGNORECASE, maxsplit=1)[0]
                x = re.split(r"\s+\bml\b", x, flags=re.IGNORECASE, maxsplit=1)[0]
                x = re.split(r"\s+\|", x, maxsplit=1)[0]
                x = re.sub(r"\s+", " ", x).strip()
                x = re.sub(r"\b([A-Za-z]{3,})\s+\1\b", r"\1", x, flags=re.IGNORECASE)
                return x.strip()

            sources = [str(raw_text or ''), str(description or ''), str(selection or '')]

            # Prefer explicit matchup line
            for src in sources:
                if not src:
                    continue
                for ln in src.splitlines():
                    ln = ln.strip()
                    if not ln:
                        continue
                    if ('@' in ln) or re.search(r"\b(vs\.?|versus)\b", ln, re.IGNORECASE):
                        m = re.search(r"(.+?)\s*(?:@|vs\.?|versus)\s*(.+)$", ln, flags=re.IGNORECASE)
                        if m:
                            a = clean_side(m.group(1))
                            b = clean_side(m.group(2))
                            if a and b:
                                return f"{a} @ {b}"[:160]

            # Fallback to combined regex
            s = "\n".join(sources)
            s = re.sub(r"\s+", " ", s).strip()
            if not s:
                return None
            m = re.search(r"(.+?)\s*(?:@|vs\.?|versus)\s*(.+?)(?:\s*\||\s*$)", s, flags=re.IGNORECASE)
            if not m:
                return None
            a = clean_side(m.group(1))
            b = clean_side(m.group(2))
            if not a or not b:
                return None
            return f"{a} @ {b}"[:160]

        def looks_bad(ev: str) -> bool:
            if not ev:
                return True
            s = str(ev)
            if '@' not in s:
                return True
            if re.search(r"\s+[+\-−–]\d+(?:\.\d+)?\b", s):
                return True
            if re.search(r"\b(over|under)\b\s*\d+(?:\.\d+)?\b", s, re.IGNORECASE):
                return True
            return False

        batch = max(50, min(int(batch), 1000))
        limit = int(limit)

        scanned = 0
        updated = 0
        next_cursor = cursor

        with get_db_connection() as conn:
            # Defensive migration: ensure column exists before we reference it
            try:
                _exec(conn, "ALTER TABLE bets ADD COLUMN IF NOT EXISTS event_text TEXT;")
            except Exception:
                pass

            # page by id to keep each request fast
            q = """
              SELECT id, date, event_text, raw_text, description, selection
              FROM bets
              WHERE user_id = %s
                AND date >= %s
                AND (%s IS NULL OR id < %s)
              ORDER BY id DESC
              LIMIT %s
            """
            rows = _exec(conn, q, (uid, cutoff, cursor, cursor, batch)).fetchall()

            for r in rows:
                b = dict(r)
                scanned += 1
                next_cursor = int(b['id'])

                cur_ev = b.get('event_text')
                if (not force) and cur_ev:
                    continue
                if force and cur_ev and (not looks_bad(cur_ev)):
                    continue

                new_ev = extract_event_text(b.get('raw_text'), b.get('description'), b.get('selection'))
                if not new_ev:
                    continue
                if cur_ev and str(cur_ev).strip() == new_ev.strip():
                    continue

                # Fast in-transaction update (avoid per-row reconnect)
                _exec(conn, """
                  UPDATE bets
                  SET event_text=%s, updated_at=NOW(), updated_by=%s, update_note=%s
                  WHERE id=%s AND user_id=%s
                """, (new_ev, uid, 'audit: backfill event_text', int(b['id']), uid))
                updated += 1

                if updated >= limit:
                    break

            conn.commit()

        invalidate_analytics_cache(uid)
        # next_cursor is the last id processed; client should pass it back until scanned==0
        return {
            "status": "success",
            "scanned": scanned,
            "updated": updated,
            "force": bool(force),
            "next_cursor": next_cursor,
            "done": scanned == 0 or updated >= limit
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))



@app.post("/api/research/grade")
async def grade_research_history():
    """
    Triggers the auto-grading process for pending model predictions.
    """
    from src.services.grading_service import GradingService
    service = GradingService()
    return service.grade_predictions()


@app.get("/api/research/history")
async def get_history(limit: int = 2000, lookback_days: int = 400, user: dict = Depends(get_current_user)):
    """Model prediction history (recommended picks by default).

    Parameters:
      - limit: max rows
      - lookback_days: how far back to scan when recommended_only=True (default widened for year-to-date)

    Notes:
      We fall back to unscoped history to support legacy single-user rows.
    """
    user_id = user.get("sub")
    try:
        limit = int(limit)
    except Exception:
        limit = 2000
    limit = max(100, min(limit, 20000))

    try:
        lookback_days = int(lookback_days)
    except Exception:
        lookback_days = 400
    lookback_days = max(30, min(lookback_days, 1200))

    # Combined History: Canonical Slate-backed + User Fallback
    from src.database import fetch_recommended_history_canonical, fetch_model_history
    canonical_rows = fetch_recommended_history_canonical(limit=limit, lookback_days=lookback_days, user_id=user_id)
    canonical_rows = [dict(r) for r in canonical_rows]
    for r in canonical_rows:
        r['source_type'] = 'canonical_slate'
    
    seen_ids = {r['id'] for r in canonical_rows if r.get('id')}
    
    # Legacy User Fallback
    user_rows = fetch_model_history(user_id=user_id, recommended_only=True, limit=limit, lookback_days=lookback_days)
    user_rows = [dict(r) for r in user_rows if dict(r).get('id') not in seen_ids]
    for r in user_rows:
        r['source_type'] = 'fallback_prediction'
    
    rows = canonical_rows + user_rows
    seen_ids.update({r['id'] for r in user_rows if r.get('id')})

    # Global Fallback
    if not rows:
        global_rows = fetch_model_history(user_id=None, recommended_only=True, limit=limit, lookback_days=lookback_days)
        global_rows = [dict(r) for r in global_rows if dict(r).get('id') not in seen_ids]
        for r in global_rows:
            r['source_type'] = 'legacy_fallback'
        rows += global_rows
    
    # Sort combined results by strongest date marker descending
    def sort_key(x):
        val = x.get('day_et') or x.get('analyzed_at') or x.get('start_time') or ''
        return str(val)
    
    rows.sort(key=sort_key, reverse=True)
    return rows[:limit]


@app.get("/api/schedule")
async def get_schedule(sport: str = "all", days: int = 1, date_str: Optional[str] = None, user: dict = Depends(get_current_user)):
    """
    Fetch upcoming scheduled games for display WITHOUT running models.
    Returns games from ESPN API.
    """
    from src.parsers.espn_client import EspnClient
    from datetime import datetime, timedelta
    
    from src.services.odds_fetcher_service import OddsFetcherService
    
    client = EspnClient()
    odds_service = OddsFetcherService()
    games = []
    
    leagues = ['NFL', 'NCAAM', 'NCAAF', 'EPL'] if sport.lower() == 'all' else [sport.upper()]
    
    # 1. Parse base date
    try:
        start_date_obj = datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.now()
    except:
        start_date_obj = datetime.now()

    for league in leagues:
        for i in range(days):
            target_date = start_date_obj + timedelta(days=i)
            try:
                # Fetch scoreboard for this league/date
                events = client.fetch_scoreboard(league, target_date.strftime("%Y%m%d"))
                
                # Fetch odds for this league/date for matching
                try:
                    market_odds_list = odds_service.fetch_odds(league, target_date.strftime("%Y%m%d"))
                except:
                    market_odds_list = []
                
                for ev in events:
                    if ev['status'].startswith('STATUS_SCHEDULED') or ev['status'] == 'scheduled':
                        # Find matching odds
                        m_odds = next((o for o in market_odds_list if 
                            (o['home_team'] == ev['home_team'] or o['away_team'] == ev['away_team'])
                        ), None)
                        
                        games.append({
                            'id': ev['id'],
                            'sport': league,
                            'game': f"{ev['away_team']} @ {ev['home_team']}",
                            'home_team': ev['home_team'],
                            'away_team': ev['away_team'],
                            'start_time': (ev['start_time'].isoformat() + ('Z' if not ev['start_time'].tzinfo else '')) if ev['start_time'] else None,
                            'status': ev['status'],
                            # Match market data
                            'home_spread': m_odds.get('home_spread') if m_odds else None,
                            'away_spread': m_odds.get('away_spread') if m_odds else None,
                            'spread_odds': m_odds.get('home_spread_odds') if m_odds else None,
                            'total_line': m_odds.get('total_score') if m_odds else None,
                            'total_odds': m_odds.get('over_odds') if m_odds else None,
                            # Model placeholders
                            'edge': None,
                            'market_line': m_odds.get('home_spread') if m_odds else None,
                            'fair_line': None,
                            'bet_on': None,
                            'is_actionable': False,
                            'audit_score': None,
                            'audit_class': None,
                            'audit_reason': 'Model not run (Market Board)',
                            'suggested_stake': None,
                            'bankroll_pct': None
                        })
            except Exception as e:
                print(f"[API] Error fetching {league} schedule: {e}")
    
    # Sort by start time
    games.sort(key=lambda x: x['start_time'] or '9999')
    
    return games


@app.post("/api/analyze/{game_id}")
async def analyze_game(game_id: str, request: Request, user: dict = Depends(get_current_user)):
    """
    Run model analysis for a specific game.
    Returns betting recommendations with narrative.
    """
    try:
        data = await request.json()
        sport = data.get("sport", "NCAAM")
        home_team = data.get("home_team")
        away_team = data.get("away_team")
        
        if not home_team or not away_team:
            raise HTTPException(status_code=400, detail="home_team and away_team are required")
        
        from src.services.game_analyzer import GameAnalyzer
        analyzer = GameAnalyzer()
        
        result = analyzer.analyze(
            game_id=game_id,
            sport=sport,
            home_team=home_team,
            away_team=away_team
        )
        
        return result
        
    except Exception as e:
        print(f"[API] Analyze error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/research")
async def get_research_edges(refresh: bool = False, user: dict = Depends(get_current_user)):
    """
    Runs all predictive models (NFL, NCAAM, EPL) and returns actionable edges.
    Cached for 5 minutes unless refresh=True.
    """
    global _research_cache
    
    # Check Cache
    now = datetime.now()
    if not refresh and _research_cache["data"] and _research_cache["last_updated"]:
        if now - _research_cache["last_updated"] < RESEARCH_TTL:
            print(f"[API] Serving Cached Research Data (Age: {(now - _research_cache['last_updated']).seconds}s)")
            return _research_cache["data"]
            
    print(f"[API] Running Models (Refresh={refresh})...")
            
    edges = []
    
    from src.models.nfl_model import NFLModel
    from src.services.edge_scanner import EdgeScanner
    from src.models.epl_model import EPLModel
    from src.services.auditor import ResearchAuditor
    from src.services.risk_manager import RiskManager
    
    auditor = ResearchAuditor()
    risk_mgr = RiskManager()
    
    # Get user bankroll for sizing
    engine = get_analytics_engine(user_id=user.get("sub"))
    bankroll = engine.get_summary(user_id=user.get("sub")).get("total_bankroll", 1000.0)

    # 1. NFL (Spread)
    try:
        nfl = NFLModel()
        nfl_edges = nfl.find_edges()
        for e in nfl_edges:
            e['market'] = 'Spread'
            e['logic'] = 'Logistic Regression'
            e['is_actionable'] = True  # Enable history tracking
            
            # Calculate Risk Metrics (EV/Kelly)
            if e.get('win_prob') and e.get('market_odds'):
                e['ev'] = risk_mgr.calculate_ev(e['win_prob'], e['market_odds'])
                risk_rec = risk_mgr.kelly_size(e['win_prob'], e['market_odds'], bankroll)
                e['suggested_stake'] = risk_rec['suggested_stake']
                e['bankroll_pct'] = risk_rec['bankroll_pct']
                e['explanation'] = risk_mgr.explain_decision(e['win_prob'], e['market_odds'], bankroll)
                
            edges.append(e)
    except Exception as e:
        print(f"[API] NFL Model Failed: {e}")

    # 2. NCAAM (V2 Market-First)
    try:
        scanner = EdgeScanner()
        ncaam_edges = scanner.find_edges(days_ahead=3, max_plays=3)
        for e in ncaam_edges:
            e['market'] = 'Total'
            e['logic'] = 'KenPom Efficiency'
            
            if e.get('win_prob') and e.get('market_odds'):
                e['ev'] = risk_mgr.calculate_ev(e['win_prob'], e['market_odds'])
                risk_rec = risk_mgr.kelly_size(e['win_prob'], e['market_odds'], bankroll)
                e['suggested_stake'] = risk_rec['suggested_stake']
                e['bankroll_pct'] = risk_rec['bankroll_pct']
                e['explanation'] = risk_mgr.explain_decision(e['win_prob'], e['market_odds'], bankroll)
            
            # Auto-save NCAAM edges as requested
            e['is_actionable'] = True
            e['game'] = f"{e['home_team']} vs {e['away_team']}"
            
            edges.append(e)
    except Exception as e:
        print(f"[API] NCAAM Model Failed: {e}")
        
    # 3. EPL (Winning)
    try:
        epl = EPLModel()
        epl_edges = epl.find_edges()
        for e in epl_edges:
            e['market'] = 'Moneyline'
            e['logic'] = 'Poisson (xG)'
            e['is_actionable'] = True  # Enable history tracking
            
            if e.get('win_prob_home') and e.get('market_odds'):
                e['ev'] = risk_mgr.calculate_ev(e['win_prob_home'], e['market_odds'])
                risk_rec = risk_mgr.kelly_size(e['win_prob_home'], e['market_odds'], bankroll)
                e['suggested_stake'] = risk_rec['suggested_stake']
                e['bankroll_pct'] = risk_rec['bankroll_pct']
                e['explanation'] = risk_mgr.explain_decision(e['win_prob_home'], e['market_odds'], bankroll)
                
            edges.append(e)
    except Exception as e:
        print(f"[API] EPL Model Failed: {e}")
        
    
    # Auto-Track Actionable Edges and Audit
    user_id = user.get("sub")
    for edge in edges:
        if edge.get('is_actionable'):
            try:
                audit_result = auditor.audit(edge)
                edge['audit_class'] = audit_result['audit_class']
                edge['audit_reason'] = audit_result['audit_reason']

                # Only persist *recommended* bets (avoid storing analysis-only rows)
                ev = float(edge.get('ev') or 0.0)
                mkt = str(edge.get('market') or '').upper()
                pick = str(edge.get('bet_on') or '').upper()
                sel = str(edge.get('bet_on') or '').strip()
                if (ev < 0.02) or (not mkt) or (mkt == 'AUTO') or (not sel) or (sel == '—') or (pick == 'NONE'):
                    continue

                # Capture in DB with correct schema
                matchup = edge.get('game') or edge.get('matchup') or f"{edge.get('away_team', 'Away')} @ {edge.get('home_team', 'Home')}"
                from datetime import datetime as dt_mod
                doc = {
                    "event_id": edge.get('game_token') or edge.get('game_id') or edge.get('game') or matchup,
                    "user_id": user_id,
                    "analyzed_at": dt_mod.utcnow().isoformat() + "Z",
                    "market_type": edge.get('market'),
                    "pick": str(edge.get('bet_on')),
                    "bet_line": edge.get('market_line') or edge.get('market_spread') or 0,
                    "bet_price": edge.get('market_odds') or -110,
                    "book": edge.get('book', 'consensus'),
                    "mu_market": edge.get('market_line') or 0,
                    "mu_torvik": edge.get('fair_line') or 0,
                    "mu_final": edge.get('fair_line') or 0,
                    "sigma": 10.0,
                    "win_prob": edge.get('win_prob') or 0.5,
                    "ev_per_unit": ev,
                    "confidence_0_100": int(abs(edge.get('edge', 0)) * 10),
                    "inputs_json": "{}",
                    "outputs_json": "{}",
                    "narrative_json": "{}",
                    "model_version": "research_v1",
                    "selection": sel,
                }
                insert_model_prediction(doc)
            except Exception as e:
                print(f"[API] Failed to auto-track edge: {e}")

    # Update Cache before returning
    _research_cache["data"] = edges
    _research_cache["last_updated"] = datetime.now()
    
    return edges

@app.get("/api/settlement/reconcile")
async def reconcile_settlements(league: Optional[str] = None, limit: int = 500, user: dict = Depends(get_current_user)):
    """
    Triggers a settlement cycle and returns reconciliation stats.
    """
    try:
        from src.services.settlement_service import SettlementEngine
        engine = SettlementEngine()
        stats = engine.run_settlement_cycle(league=league, limit=limit)
        return stats
    except Exception as e:
         print(f"[API] Settlement Failed: {e}")
         raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/data-health")
async def get_data_health():
    """Return latest data pipeline health status."""
    try:
        from src.database import get_db_connection, _exec
        with get_db_connection() as conn:
            rows = _exec(conn, "SELECT source, last_success_at, last_row_count, status, notes, updated_at FROM data_health ORDER BY source ASC").fetchall()
            return {"status": "success", "items": [dict(r) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ncaam/referees")
async def set_ncaam_referees(request: Request, user: dict = Depends(get_current_user)):
    """Manual referee assignment entry.

    Body:
      { event_id, referee_1, referee_2, referee_3 }

    Notes:
    - We intentionally do NOT require crew_avg_fouls; model can use KenPom tendencies.
    - Stored in referee_assignments with source='manual'.
    """
    try:
        data = await request.json()
        event_id = data.get('event_id')
        r1 = data.get('referee_1')
        r2 = data.get('referee_2')
        r3 = data.get('referee_3')

        if not event_id:
            raise HTTPException(status_code=400, detail='event_id required')

        from src.database import upsert_referee_assignment
        upsert_referee_assignment(event_id=event_id, referee_1=r1, referee_2=r2, referee_3=r3, crew_avg_fouls=None, source='manual')
        return {"status": "ok", "event_id": event_id, "referee_1": r1, "referee_2": r2, "referee_3": r3}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/model/health")
async def get_model_health(date: Optional[str] = None, league: Optional[str] = None, market: Optional[str] = None, user: dict = Depends(get_current_user)):
    """
    Get daily model health metrics.
    """
    try:
        from src.database import fetch_model_health_daily
        stats = fetch_model_health_daily(date=date, league=league, market_type=market)
        return stats
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

# --- Cron Security & Jobs ---

async def verify_cron_secret(request: Request):
    """Verifies access for automated jobs or manual triggers.

    Allows if ANY of these are valid:
    1. Vercel Cron header (x-vercel-cron: 1)
    2. Authorization: Bearer <CRON_SECRET>
    3. Authorization: Bearer <BASEMENT_PASSWORD> (Fallback for simpler setups)
    4. X-BASEMENT-KEY: <BASEMENT_PASSWORD> (UI / Manual)
    """
    from src.config import settings

    # 1. Vercel native crons
    try:
        cron_header = str(request.headers.get('x-vercel-cron') or '').strip()
        if cron_header == '1':
            return True
    except Exception:
        pass

    # 2. Bearer Token Check (External jobs like GitHub Actions)
    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
            
            # Match CRON_SECRET if configured
            expected_cron = settings.CRON_SECRET
            if expected_cron and token == expected_cron.strip():
                return True
                
            # FALLBACK: Match BASEMENT_PASSWORD (allows GitHub secrets to use the site password)
            expected_pwd = settings.BASEMENT_PASSWORD
            if expected_pwd and token == expected_pwd.strip():
                return True
            
            # If Bearer was provided but didn't match
            token_hint = f"{token[:3]}..." if len(token) > 3 else "***"
            raise HTTPException(
                status_code=403, 
                detail=f"Forbidden: Bearer token mismatch (sent: {token_hint})"
            )

    # 3. Direct Key Check (UI or manual curl)
    expected_pwd = settings.BASEMENT_PASSWORD
    client_key = request.headers.get("X-BASEMENT-KEY")
    if expected_pwd and client_key and client_key.strip() == expected_pwd:
        return True

    # If none matched, deny with specific missing info if possible
    err_detail = "Forbidden: Invalid Auth"
    if not auth_header and not client_key:
        err_detail += " (No Authorization or X-BASEMENT-KEY header found)"
    
    raise HTTPException(status_code=403, detail=err_detail)

@app.get("/api/jobs/diag_auth")
async def diagnostic_auth_check(request: Request):
    """Diagnostic endpoint to debug 403 issues safely."""
    from src.config import settings
    
    def mask(s):
        if not s: return "None"
        s = str(s).strip()
        if len(s) <= 3: return "***"
        return f"{s[:3]}...({len(s)} chars)"

    auth_h = request.headers.get("Authorization", "")
    bearer_token = ""
    if auth_h.lower().startswith("bearer "):
        bearer_token = auth_h.split(" ")[1]

    client_key = request.headers.get("X-BASEMENT-KEY", "")

    return {
        "status": "diagnostic",
        "timestamp": time.time(),
        "headers_received": {
            "authorization": mask(auth_h),
            "x-basement-key": mask(client_key),
            "x-vercel-cron": request.headers.get("x-vercel-cron")
        },
        "server_configuration": {
            "has_cron_secret": bool(settings.CRON_SECRET),
            "has_basement_password": bool(settings.BASEMENT_PASSWORD),
            "cron_secret_mask": mask(settings.CRON_SECRET),
            "basement_password_mask": mask(settings.BASEMENT_PASSWORD),
        },
        "matches": {
            "bearer_matches_cron": bool(settings.CRON_SECRET and bearer_token == settings.CRON_SECRET),
            "bearer_matches_password": bool(settings.BASEMENT_PASSWORD and bearer_token == settings.BASEMENT_PASSWORD),
            "key_matches_password": bool(settings.BASEMENT_PASSWORD and client_key == settings.BASEMENT_PASSWORD),
        }
    }

@app.api_route("/api/jobs/policy_refresh", methods=["GET", "POST"])
async def trigger_policy_refresh(request: Request, authorized: bool = Depends(verify_cron_secret)):
    """
    Cron Job: Policy Refresh.
    """
    job_key = "policy_refresh"
    from src.services.job_service import JobContext, JobLockedException
    from src.services.policy_engine import PolicyEngine
    
    try:
        with JobContext(job_key) as ctx:
            # Run Logic
            engine = PolicyEngine()
            engine.refresh_policies()
            return {"status": "success", "message": "Policy Refresh Executed"}
            
    except JobLockedException:
        return {"status": "skipped", "reason": "Job execution overlapping (locked)"}
    except Exception as e:
        print(f"[Job] Policy Refresh Failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.api_route("/api/jobs/lock_morning_slate", methods=["GET", "POST"])
async def trigger_lock_morning_slate(request: Request, authorized: bool = Depends(verify_cron_secret)):
    """
    Cron Job: Lock the morning slate for 'Yesterday' card stabilization.
    """
    job_key = "lock_morning_slate"
    from src.services.job_service import JobContext, JobLockedException
    import subprocess
    import sys
    import os
    
    try:
        with JobContext(job_key) as ctx:
            script_path = os.path.join(os.getcwd(), "scripts", "send_ncaam_top_picks_cached.py")
            # Run without --force normally, just to capture whatever is current at 9 AM ET
            result = subprocess.run([sys.executable, script_path], capture_output=True, text=True)
            if result.returncode == 0:
                print(f"[Job] Morning slate locked successfully: {result.stdout.splitlines()[0] if result.stdout else ''}")
                return {"status": "success", "message": "Morning slate locked", "output": result.stdout.splitlines()[0] if result.stdout else ""}
            else:
                print(f"[Job] Morning slate lock failed: {result.stderr}")
                return {"status": "error", "message": result.stderr}
    except JobLockedException:
        return {"status": "skipped", "reason": "Job execution overlapping (locked)"}
    except Exception as e:
        print(f"[Job] Morning slate lock failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.api_route("/api/jobs/ingest_torvik", methods=["GET", "POST"])
async def trigger_torvik_ingestion(request: Request, authorized: bool = Depends(verify_cron_secret)):
    """
    Cron Job: Torvik Ingestion.
    """
    job_key = "ingest_torvik"
    from src.services.job_service import JobContext, JobLockedException
    # Imports inside to avoid heavy loading on startup if possible
    from src.database import init_bt_team_metrics_db
    from src.services.barttorvik import BartTorvikClient
    
    try:
        with JobContext(job_key) as ctx:
            # Phase 9: Cursor Check (Placeholder for Full vs Incremental)
            # Torvik ingestion usually is full refresh of metrics, but we can store 'last_run'
            last_run = ctx.state.get("last_run_date")
            print(f"[Job] Torvik Ingest. Last Run: {last_run}")
            
            init_bt_team_metrics_db()
            client = BartTorvikClient()
            ratings = client.get_efficiency_ratings(year=2026)
            
            if ratings:
                # Update State
                ctx.state["last_run_date"] = datetime.now().strftime("%Y-%m-%d")
                ctx.state["teams_count"] = len(ratings)
                
                return {
                    "status": "success", 
                    "message": f"Ingested {len(ratings)} teams",
                    "teams_count": len(ratings)
                }
            else:
                return {"status": "warning", "message": "No ratings found"}
                
    except JobLockedException:
        return {"status": "skipped", "reason": "Locked"}
    except Exception as e:
        print(f"[Job] Torvik Ingestion Failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.api_route("/api/jobs/ingest_kenpom", methods=["GET", "POST"])
async def trigger_kenpom_ingestion(request: Request, authorized: bool = Depends(verify_cron_secret)):
    """
    Cron Job: KenPom Ingestion.

    Scrapes kenpom.com using the KENPOM_COOKIE env var for authentication.
    Without a valid cookie the public homepage is returned (may be empty for
    users behind the paywall) — the job will store whatever it gets.
    """
    import os
    job_key = "ingest_kenpom"
    from src.services.job_service import JobContext, JobLockedException
    from src.services.kenpom_scraper import KenPomScraper

    try:
        with JobContext(job_key) as ctx:
            last_run = ctx.state.get("last_run_date")
            print(f"[Job] KenPom Ingest. Last Run: {last_run}")

            scraper = KenPomScraper()

            # Inject auth cookie if available so the session gets past the login wall
            kenpom_cookie = os.environ.get("KENPOM_COOKIE", "").strip()
            if kenpom_cookie:
                scraper.session.headers.update({"Cookie": kenpom_cookie})
                print("[Job] KENPOM_COOKIE injected into scraper session")
            else:
                print("[Job] KENPOM_COOKIE not set — attempting unauthenticated scrape")

            teams = scraper.scrape_homepage_rankings()

            if not teams:
                return {"status": "warning", "message": "No teams scraped — KenPom may require login or cookie is expired"}

            # Persist to DB
            scraper.save_to_database(teams)

            ctx.state["last_run_date"] = datetime.now().strftime("%Y-%m-%d")
            ctx.state["teams_count"] = len(teams)

            return {
                "status": "success",
                "message": f"Ingested {len(teams)} KenPom teams",
                "teams_count": len(teams),
                "authenticated": bool(kenpom_cookie),
            }

    except JobLockedException:
        return {"status": "skipped", "reason": "Locked"}
    except Exception as e:
        print(f"[Job] KenPom Ingestion Failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/board")
async def get_board(request: Request, league: str, date: Optional[str] = None, days: int = 1):
    """
    Generic lightweight board backed by DB odds snapshots.

    Params:
      - league: 'NCAAM' | 'NFL' | 'EPL'
      - date: YYYY-MM-DD (interpreted in America/New_York)
      - days: number of days forward from `date` to include (default 1)

    Returns (when available):
      - spread (home/away) + odds
      - total (O/U) + odds
      - moneyline (home/away/draw) odds
    """
    from src.database import get_db_connection, _exec

    if not league:
        raise HTTPException(status_code=400, detail="league is required")

    league = league.upper().strip()
    if league not in {"NCAAM", "NFL", "EPL"}:
        raise HTTPException(status_code=400, detail=f"Unsupported league: {league}")

    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    try:
        days = int(days)
    except Exception:
        days = 1
    days = max(1, min(days, 14))

    start_date = datetime.strptime(date, "%Y-%m-%d").date()
    end_date = (start_date + timedelta(days=days - 1))

    query = """
    WITH base_events AS (
      SELECT e.*,
        DATE(e.start_time AT TIME ZONE 'America/New_York') AS day_et,
        LOWER(regexp_replace(
          replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(COALESCE(e.home_team,''),
            'North Carolina State', 'NC State'), 'N.C. State', 'NC State'), 'N.C. St.', 'NC State'), 'NC St.', 'NC State'),
            'App State', 'Appalachian State'), 'Appalachian St.', 'Appalachian State'), 'Appalachian St', 'Appalachian State'),
            'South Carolina Upstate', 'USC Upstate'), 'U.S.C. Upstate', 'USC Upstate'),
            'Long Island University', 'LIU'), 'L.I.U.', 'LIU'),
            'St. Francis', 'Saint Francis'),
          '[^a-z0-9]+', '', 'g'
        )) AS home_key,
        LOWER(regexp_replace(
          replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(COALESCE(e.away_team,''),
            'North Carolina State', 'NC State'), 'N.C. State', 'NC State'), 'N.C. St.', 'NC State'), 'NC St.', 'NC State'),
            'App State', 'Appalachian State'), 'Appalachian St.', 'Appalachian State'), 'Appalachian St', 'Appalachian State'),
            'South Carolina Upstate', 'USC Upstate'), 'U.S.C. Upstate', 'USC Upstate'),
            'Long Island University', 'LIU'), 'L.I.U.', 'LIU'),
            'St. Francis', 'Saint Francis'),
          '[^a-z0-9]+', '', 'g'
        )) AS away_key,
        CASE
          WHEN e.id LIKE 'action:ncaam:%%' THEN 0
          WHEN e.id LIKE 'espn:ncaam:%%' THEN 1
          ELSE 2
        END AS src_rank
      FROM events e
      WHERE e.league = %(league)s
        AND DATE(e.start_time AT TIME ZONE 'America/New_York') BETWEEN %(start_date)s AND %(end_date)s
    ),
    dedup_events AS (
      SELECT *
      FROM (
        SELECT *,
          ROW_NUMBER() OVER (PARTITION BY league, day_et, home_key, away_key ORDER BY src_rank ASC, start_time ASC) AS rn
        FROM base_events
      ) t
      WHERE rn = 1
    )
    SELECT e.id, e.league as sport, e.home_team, e.away_team, e.start_time, e.status,
           e.day_et as day_et,
           -- SPREAD (HOME/AWAY)
           s_home.line_value as home_spread,
           s_home.price as spread_home_odds,
           s_away.line_value as away_spread,
           s_away.price as spread_away_odds,
           -- TOTAL (OVER/UNDER)
           t_over.line_value as total_line,
           t_over.price as total_over_odds,
           t_under.price as total_under_odds,
           -- MONEYLINE (HOME/AWAY/DRAW)
           ml_home.price as ml_home_odds,
           ml_away.price as ml_away_odds,
           ml_draw.price as ml_draw_odds,
           -- Back-compat aliases (older UI expected these names)
           ml_home.price as moneyline_home,
           ml_away.price as moneyline_away,
           gr.home_score, gr.away_score, gr.final
    FROM dedup_events e
    LEFT JOIN (
        SELECT DISTINCT ON (event_id) event_id, line_value, price
        FROM odds_snapshots
        WHERE market_type = 'SPREAD' AND side = 'HOME'
        ORDER BY event_id, captured_at DESC
    ) s_home ON e.id = s_home.event_id
    LEFT JOIN (
        SELECT DISTINCT ON (event_id) event_id, line_value, price
        FROM odds_snapshots
        WHERE market_type = 'SPREAD' AND side = 'AWAY'
        ORDER BY event_id, captured_at DESC
    ) s_away ON e.id = s_away.event_id
    LEFT JOIN (
        SELECT DISTINCT ON (event_id) event_id, line_value, price
        FROM odds_snapshots
        WHERE market_type = 'TOTAL' AND side = 'OVER'
        ORDER BY event_id, captured_at DESC
    ) t_over ON e.id = t_over.event_id
    LEFT JOIN (
        SELECT DISTINCT ON (event_id) event_id, line_value, price
        FROM odds_snapshots
        WHERE market_type = 'TOTAL' AND side = 'UNDER'
        ORDER BY event_id, captured_at DESC
    ) t_under ON e.id = t_under.event_id
    LEFT JOIN (
        SELECT DISTINCT ON (event_id) event_id, price
        FROM odds_snapshots
        WHERE market_type = 'MONEYLINE' AND side = 'HOME'
        ORDER BY event_id, captured_at DESC
    ) ml_home ON e.id = ml_home.event_id
    LEFT JOIN (
        SELECT DISTINCT ON (event_id) event_id, price
        FROM odds_snapshots
        WHERE market_type = 'MONEYLINE' AND side = 'AWAY'
        ORDER BY event_id, captured_at DESC
    ) ml_away ON e.id = ml_away.event_id
    LEFT JOIN (
        SELECT DISTINCT ON (event_id) event_id, price
        FROM odds_snapshots
        WHERE market_type = 'MONEYLINE' AND side = 'DRAW'
        ORDER BY event_id, captured_at DESC
    ) ml_draw ON e.id = ml_draw.event_id
    LEFT JOIN game_results gr ON e.id = gr.event_id
    ORDER BY e.start_time ASC
    """

    cache_key = f"board:{league}:{start_date}:{end_date}"

    def _build():
        with get_db_connection() as conn:
            rows = _exec(conn, query, {"league": league, "start_date": str(start_date), "end_date": str(end_date)}).fetchall()
            return _ensure_utc([dict(r) for r in rows])

    # Keep TTL short to avoid stale lines.
    return _cached_json(request, cache_key, ttl_s=int(os.getenv('BOARD_TTL_SECONDS', '30')), build_fn=_build)


@app.get("/api/ncaam/board")
async def get_ncaam_board(date: Optional[str] = None, days: int = 1):
    """Back-compat wrapper."""
    return await get_board(league="NCAAM", date=date, days=days)


@app.get("/api/ncaam/top-picks")
async def get_ncaam_top_picks(request: Request, date: Optional[str] = None, days: int = 1, limit_games: int = 25, compute_missing: bool = False, relax_gates: bool = False, max_compute: int = 20):
    """Return top model pick per game for the NCAAM board window.

    Goal: allow UI to render a 'Top pick' badge without firing /analyze for every row.

    Notes:
    - This still runs model analysis server-side, but it's a single request and is TTL-cached.
    - Hard-capped to avoid expensive work.

    Returns:
      { generated_at, date, days, picks: { [event_id]: { rec, analyzed_at } } }
    """
    from src.database import get_db_connection, _exec
    from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2

    if not date:
        with get_db_connection() as conn:
            date = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]

    try:
        days = int(days)
    except Exception:
        days = 1
    days = max(1, min(days, 7))

    try:
        limit_games = int(limit_games)
    except Exception:
        limit_games = 25
    # Allow the UI to request larger slates on busy Saturdays.
    # Still capped to keep this endpoint from becoming too expensive.
    limit_games = max(1, min(limit_games, 250))

    # New behavior: serve precomputed daily picks when available (built by background job).
    # compute_missing can still be used for ad-hoc computation, but UI should prefer cached.
    cache_key = f"{date}:{days}:{limit_games}:{'compute' if compute_missing else 'cached'}"
    now = datetime.now()
    cached = _top_picks_cache.get(cache_key)
    # When compute_missing=True, bypass cache so UI always gets freshly-computed recs.
    if (not compute_missing) and cached and (now - cached["at"]) < TOP_PICKS_TTL:
        payload = cached["data"]
        # Attach ETag so browser/clients can revalidate cheaply.
        etag = _make_etag(payload)
        inm = request.headers.get('if-none-match')
        if inm and inm.strip() == etag:
            return JSONResponse(status_code=304, content=None, headers={'ETag': etag})
        payload = jsonable_encoder(payload)
        return JSONResponse(content=payload, headers={'ETag': etag, 'Cache-Control': f"public, max-age={int(os.getenv('TOP_PICKS_TTL_SECONDS', '90'))}"})

    # Pull the same board window as /api/board, but NCAAM only.
    start_date = datetime.strptime(date, "%Y-%m-%d").date()
    end_date = (start_date + timedelta(days=days - 1))

    with get_db_connection() as conn:
        rows = _exec(
            conn,
            """
            WITH base_events AS (
              SELECT e.*,
                DATE(e.start_time AT TIME ZONE 'America/New_York') AS day_et,
                LOWER(regexp_replace(
                  replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(COALESCE(e.home_team,''),
                    'North Carolina State', 'NC State'), 'N.C. State', 'NC State'), 'N.C. St.', 'NC State'), 'NC St.', 'NC State'),
                    'App State', 'Appalachian State'), 'Appalachian St.', 'Appalachian State'), 'Appalachian St', 'Appalachian State'),
                    'South Carolina Upstate', 'USC Upstate'), 'U.S.C. Upstate', 'USC Upstate'),
                    'Long Island University', 'LIU'), 'L.I.U.', 'LIU'),
                    'St. Francis', 'Saint Francis'),
                  '[^a-z0-9]+', '', 'g'
                )) AS home_key,
                LOWER(regexp_replace(
                  replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(COALESCE(e.away_team,''),
                    'North Carolina State', 'NC State'), 'N.C. State', 'NC State'), 'N.C. St.', 'NC State'), 'NC St.', 'NC State'),
                    'App State', 'Appalachian State'), 'Appalachian St.', 'Appalachian State'), 'Appalachian St', 'Appalachian State'),
                    'South Carolina Upstate', 'USC Upstate'), 'U.S.C. Upstate', 'USC Upstate'),
                    'Long Island University', 'LIU'), 'L.I.U.', 'LIU'),
                    'St. Francis', 'Saint Francis'),
                  '[^a-z0-9]+', '', 'g'
                )) AS away_key,
                CASE
                  WHEN e.id LIKE 'action:ncaam:%%' THEN 0
                  WHEN e.id LIKE 'espn:ncaam:%%' THEN 1
                  ELSE 2
                END AS src_rank
              FROM events e
              WHERE e.league = 'NCAAM'
                AND DATE(e.start_time AT TIME ZONE 'America/New_York') BETWEEN %(start)s AND %(end)s
            ),
            dedup_events AS (
              SELECT *
              FROM (
                SELECT *,
                  ROW_NUMBER() OVER (PARTITION BY league, day_et, home_key, away_key ORDER BY src_rank ASC, start_time ASC) AS rn
                FROM base_events
              ) t
              WHERE rn = 1
            )
            SELECT id, home_team, away_team, start_time, day_et
            FROM dedup_events
            ORDER BY start_time ASC
            LIMIT %(lim)s
            """,
            {"start": str(start_date), "end": str(end_date), "lim": int(limit_games)},
        ).fetchall()

    # Preserve event metadata so the UI doesn't have to join against /api/board.
    event_meta = {}
    event_ids = []
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        eid = d.get('id')
        if not eid:
            continue
        event_ids.append(eid)
        st = d.get('start_time')
        # Normalize to ISO string with UTC Z suffix so the frontend renders correct ET.
        if hasattr(st, 'isoformat'):
            try:
                # If tz-aware, convert to UTC and emit Z.
                if getattr(st, 'tzinfo', None) is not None:
                    st = st.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
                else:
                    st = st.isoformat() + 'Z'
            except Exception:
                st = st.isoformat()
        elif isinstance(st, str):
            if not st.endswith('Z') and '+' not in st:
                st = st + 'Z'

        event_meta[eid] = {
            'id': eid,
            'home_team': d.get('home_team'),
            'away_team': d.get('away_team'),
            'start_time': st,
            'day_et': d.get('day_et'),
        }

    import json

    def _dt(x):
        """Best-effort datetime parser without python-dateutil."""
        if not x:
            return None
        if isinstance(x, str):
            s = str(x).strip()
            try:
                # handle trailing Z
                if s.endswith('Z'):
                    s = s[:-1] + '+00:00'
                return datetime.fromisoformat(s)
            except Exception:
                # fallback: YYYY-MM-DD
                try:
                    s0 = s.split('T')[0].split(' ')[0]
                    if len(s0) == 10:
                        return datetime.strptime(s0, '%Y-%m-%d')
                except Exception:
                    pass
                return None
        if hasattr(x, 'isoformat'):
            return x
        return None

    def _normalize_rec(rec: dict) -> dict:
        """Normalize recommendation objects to a stable UI schema.

        UI expects keys like: bet_type, selection, market_line, price, edge, confidence.
        """
        if not rec:
            return {"bet_type": "AUTO", "selection": "—", "price": None, "edge": "0.00%", "confidence": 0}

        # Newer model format already matches
        if rec.get('bet_type') is not None:
            return rec

        # Older/alternate format: {market, side, team, line, price, ev, ...}
        market = (rec.get('market') or rec.get('market_type') or '').upper()
        if market in ('SPREAD', 'TOTAL', 'MONEYLINE'):
            bet_type = market
        else:
            bet_type = rec.get('bet_type') or 'AUTO'

        line = rec.get('market_line')
        if line is None:
            line = rec.get('line')

        price = rec.get('price')
        edge = rec.get('edge')
        if edge is None:
            ev = rec.get('ev')
            try:
                if ev is not None:
                    edge = f"{float(ev) * 100.0:.1f}%"
            except Exception:
                edge = None
        if edge is None:
            edge = "0.00%"

        conf = rec.get('confidence')
        if conf is None:
            conf = rec.get('confidence_0_100')

        # If still missing, derive a label from EV when available.
        if conf is None:
            ev = rec.get('ev')
            try:
                ev = float(ev) if ev is not None else None
            except Exception:
                ev = None
            if ev is not None:
                score = ev * 100.0 * 5.0
                conf = "High" if score > 80 else "Medium" if score > 50 else "Low"
            else:
                conf = "Low"
        selection = rec.get('selection')
        if not selection:
            side = rec.get('side')
            team = rec.get('team')
            if bet_type == 'SPREAD' and team is not None and line is not None:
                try:
                    n = float(line)
                    selection = f"{team} {('+' if n > 0 else '')}{n:g}"
                except Exception:
                    selection = f"{team} {line}"
            elif bet_type == 'TOTAL' and line is not None and side is not None:
                selection = f"{str(side).upper()} {line}"
            else:
                selection = team or side or '—'

        out = {
            'bet_type': bet_type,
            'selection': selection,
            'market_line': line,
            'price': price,
            'edge': edge,
            'confidence': conf,
            'book': rec.get('book')
        }
        return out

    def _load_latest_stored_pick(conn, eid: str):
        """Load the most recent stored pick for an event.

        This is the same source that powers the text/cron picks (model_predictions).
        We keep it permissive so UI can populate even if the strict filters would exclude it.
        """
        row = _exec(
            conn,
            """
            SELECT analyzed_at, outputs_json, selection, price, ev_per_unit, confidence_0_100, market_type, bet_line, bet_price, pick
            FROM model_predictions
            WHERE event_id=%s
              AND outputs_json IS NOT NULL AND TRIM(outputs_json) <> ''
            ORDER BY analyzed_at DESC
            LIMIT 1
            """,
            (eid,),
        ).fetchone()
        if not row:
            return None
        r = dict(row)
        rec = None
        try:
            out = json.loads(r.get('outputs_json') or '{}')
            top = (out.get('recommendations') or [None])[0]
            if top:
                rec = top
        except Exception:
            rec = None

        if not rec:
            # Fallback: reconstruct a minimal rec
            ev = float(r.get('ev_per_unit') or 0.0)
            line = r.get('bet_line')
            price = r.get('price') if r.get('price') is not None else r.get('bet_price')
            rec = {
                'bet_type': r.get('market_type') or 'AUTO',
                'selection': r.get('selection') or '—',
                'market_line': line,
                'price': price,
                'edge': f"{(ev * 100.0):.1f}%",
                'confidence': r.get('confidence_0_100'),
            }

        return {'rec': _normalize_rec(rec), 'analyzed_at': r.get('analyzed_at')}

    # Try cached daily picks first.
    try:
        with get_db_connection() as conn:
            # Limit egress: only pull cached picks for the event_ids in the requested window.
            cached = _exec(
                conn,
                """
                SELECT event_id, computed_at, is_actionable, reason, rec_json
                FROM daily_top_picks
                WHERE date_et = %s
                  AND league='NCAAM'
                  AND event_id = ANY(%s)
                """,
                (date, list(event_ids)),
            ).fetchall()
        if cached:
            picks = {}
            for r in cached:
                d = dict(r)
                eid = d.get('event_id')
                picks[eid] = {
                    'rec': d.get('rec_json'),
                    'analyzed_at': d.get('computed_at'),
                    'event': event_meta.get(eid),
                    'locked': False,
                    'source': 'cached',
                    'is_actionable': bool(d.get('is_actionable')),
                    'reason': d.get('reason'),
                }
            # Attach latest full-run status when available so the UI can show:
            # "Stale slate — latest full run produced NO BETS. Showing last cached picks." (option 2)
            run_meta = None
            try:
                with get_db_connection() as conn2:
                    rm = _exec(conn2, """
                      SELECT status, run_type, scanned, recs, created_at
                      FROM model_run_log
                      WHERE league='NCAAM' AND date_et=%s AND run_type='full'
                      ORDER BY created_at DESC
                      LIMIT 1
                    """, (date,)).fetchone()
                if rm:
                    rmd = dict(rm)
                    ca = rmd.get('created_at')
                    if hasattr(ca, 'isoformat'):
                        rmd['created_at'] = ca.isoformat().replace('+00:00', 'Z')
                    run_meta = rmd
            except Exception:
                run_meta = None

            data = {
                'generated_at': datetime.utcnow().isoformat() + 'Z',
                'date': date,
                'days': days,
                'limit_games': limit_games,
                'run_meta': run_meta,
                'stats': {
                    'events_total': len(event_ids),
                    'scanned': len(event_ids),
                    'stored': 0,
                    'computed_attempted': 0,
                    'computed_with_pick': len([v for v in picks.values() if v.get('rec')]),
                    'computed_no_pick': 0,
                    'no_pick_reasons': {},
                    'errors': 0,
                },
                'errors': [],
                'no_pick_samples': [],
                'picks': picks,
            }
            # NOTE: do not re-import jsonable_encoder inside this function; that
            # creates a local symbol and can cause UnboundLocalError earlier.
            data = jsonable_encoder(data)
            etag = _make_etag(data)
            inm = request.headers.get('if-none-match')
            if inm and inm.strip() == etag:
                return JSONResponse(status_code=304, content=None, headers={'ETag': etag})
            return JSONResponse(content=data, headers={'ETag': etag, 'Cache-Control': f"public, max-age={int(os.getenv('TOP_PICKS_TTL_SECONDS', '90'))}"})
    except Exception as e:
        # Don't fail the endpoint if the cache query fails, but do log so we can debug.
        print(f"[top-picks] cached daily_top_picks query failed: {e}")
        pass

    # If we don't have precomputed daily_top_picks and there are no stored picks,
    # allow a small on-demand compute to keep the UI from showing an empty slate.
    # This is bounded and only triggers for today's ET date with days=1.
    if not compute_missing:
        try:
            with get_db_connection() as conn:
                today_et = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]
            if str(date) == str(today_et) and int(days) == 1:
                compute_missing = True
                # keep it conservative by default
                try:
                    max_compute = int(os.getenv('AUTO_TOP_PICKS_MAX_COMPUTE', '20'))
                except Exception:
                    max_compute = 20
        except Exception:
            pass

    model = NCAAMMarketFirstModelV2()
    picks = {}

    stats = {
        'events_total': len(event_ids),
        'scanned': 0,
        'stored': 0,
        'computed_attempted': 0,
        'computed_with_pick': 0,
        'computed_no_pick': 0,
        'no_pick_reasons': {},
        'errors': 0,
    }
    errors = []
    no_pick_samples = []

    with get_db_connection() as conn:
        now_dt = datetime.now(timezone.utc)

        # Fast path (default): use stored recommended picks only.
        # compute_missing can be expensive in serverless; cap the number of computed analyses.
        try:
            max_compute_i = int(max_compute)
        except Exception:
            max_compute_i = 20
        max_compute_i = max(0, min(max_compute_i, 250))

        import time
        t0 = time.time()
        # Keep on-demand top-picks computation bounded for serverless.
        time_budget_s = float(os.getenv('TOP_PICKS_TIME_BUDGET_S', '15'))
        target_picks = int(os.getenv('TOP_PICKS_TARGET_PICKS', '5'))

        for eid in event_ids:
            stats['scanned'] += 1
            try:
                st = _dt((event_meta.get(eid) or {}).get('start_time'))
                if st and st.tzinfo is None:
                    st = st.replace(tzinfo=timezone.utc)

                stored = _load_latest_stored_pick(conn, eid)
                if stored and stored.get('rec'):
                    stats['stored'] += 1
                    picks[eid] = {
                        'rec': stored['rec'],
                        'analyzed_at': stored.get('analyzed_at'),
                        'event': event_meta.get(eid),
                        'locked': bool(st and st <= now_dt),
                        'source': 'stored',
                        'is_actionable': True,
                        'reason': None,
                    }
                    continue

                if not compute_missing:
                    continue

                # Optional slow path: compute missing picks on-demand.
                # Stop early if we've found enough actionable picks.
                if target_picks and int(stats.get('computed_with_pick') or 0) >= int(target_picks):
                    continue

                # Hard cap on number of analyses.
                if max_compute_i and stats['computed_attempted'] >= max_compute_i:
                    continue

                # Time budget cap (avoid 504s/timeouts).
                if (time.time() - t0) > time_budget_s:
                    continue

                stats['computed_attempted'] += 1
                # In top-picks, do not persist predictions (serverless runtime + avoid DB churn).
                res = model.analyze(eid, relax_gates=bool(relax_gates), persist=False)
                top = (res.get('recommendations') or [None])[0]
                if top:
                    stats['computed_with_pick'] += 1
                    picks[eid] = {
                        "rec": _normalize_rec(top),
                        "analyzed_at": res.get('analyzed_at'),
                        "event": event_meta.get(eid),
                        'locked': False,
                        'source': 'computed',
                        'is_actionable': True,
                        'reason': None,
                    }
                else:
                    stats['computed_no_pick'] += 1
                    reason = None
                    if isinstance(res, dict):
                        reason = res.get('block_reason') or res.get('headline') or res.get('recommendation') or res.get('error')
                    reason = str(reason or 'No bet')

                    # Preserve no-bet reasons per event so UI can show "No Bet" states.
                    picks[eid] = {
                        "rec": None,
                        "analyzed_at": res.get('analyzed_at') if isinstance(res, dict) else None,
                        "event": event_meta.get(eid),
                        'locked': False,
                        'source': 'computed',
                        'is_actionable': False,
                        'reason': reason,
                    }

                    stats['no_pick_reasons'][reason] = int(stats['no_pick_reasons'].get(reason, 0)) + 1
                    if len(no_pick_samples) < 20:
                        no_pick_samples.append({'event_id': eid, 'reason': reason})
            except Exception as e:
                stats['errors'] += 1
                msg = str(e)
                # Include a few errors in the response so we can debug without needing Vercel log access.
                if len(errors) < 20:
                    errors.append({'event_id': eid, 'error': msg})
                print(f"[top-picks] analyze failed for {eid}: {e}")

    data = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "date": date,
        "days": days,
        "limit_games": limit_games,
        "stats": stats,
        "errors": errors,
        "no_pick_samples": no_pick_samples,
        "picks": picks,
    }

    _top_picks_cache[cache_key] = {"at": now, "data": data}

    etag = _make_etag(data)
    inm = request.headers.get('if-none-match')
    if inm and inm.strip() == etag:
        return JSONResponse(status_code=304, content=None, headers={'ETag': etag})

    data = jsonable_encoder(data)
    return JSONResponse(content=data, headers={'ETag': etag, 'Cache-Control': f"public, max-age={int(os.getenv('TOP_PICKS_TTL_SECONDS', '90'))}"})

def _ensure_utc(data: list) -> list:
    """
    Ensures datetime fields have 'Z' suffix if naive, forcing frontend to treat as UTC.
    """
    keys = ['start_time', 'analyzed_at', 'last_updated', 'created_at', 'close_captured_at']
    for item in data:
        for k in keys:
            if item.get(k):
                val = item[k]
                if isinstance(val, str):
                    if not val.endswith('Z') and '+' not in val:
                         item[k] = val + 'Z'
                elif hasattr(val, 'isoformat'):
                    # If datetime object is naive, isoformat() gives no offset.
                    # We assume DB is UTC.
                    iso = val.isoformat()
                    if val.tzinfo is None:
                        iso += 'Z'
                    item[k] = iso
    return data

@app.post("/api/ncaam/analyze")
async def analyze_ncaam_game(request: Request):
    """
    On-demand analysis for an NCAAM game.

    IMPORTANT: We must NOT pass "Unknown" teams into the analyzer.
    GameAnalyzer enriches/persists and the UI expects team labels.
    """
    try:
        data = await request.json()
        event_id = data.get("event_id")
        prefer_cached = bool(data.get('prefer_cached') or False)
        if not event_id:
            raise HTTPException(status_code=400, detail="event_id is required")

        from src.database import get_db_connection, _exec
        from src.services.game_analyzer import GameAnalyzer

        # Pull canonical event row (teams, start_time, etc.)
        with get_db_connection() as conn:
            row = _exec(conn, "SELECT id, league, home_team, away_team FROM events WHERE id = :id", {"id": event_id}).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Event not found: {event_id}")

        ev = dict(row)

        # Optional: prefer cached daily_top_picks recommendation when available.
        # This makes the Details modal consistent with the Top-Picks badge even if
        # live market data is missing at click-time.
        if prefer_cached:
            try:
                # Determine today's ET date from DB for consistency.
                with get_db_connection() as conn:
                    today_et = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]
                    pick_row = _exec(
                        conn,
                        """
                        SELECT rec_json, reason, computed_at
                        FROM daily_top_picks
                        WHERE date_et=%s AND league='NCAAM' AND event_id=%s
                        LIMIT 1
                        """,
                        (today_et, event_id),
                    ).fetchone()

                if pick_row and pick_row.get('rec_json'):
                    cached_rec = pick_row.get('rec_json')
                    result = {
                        'event_id': event_id,
                        'league': 'NCAAM',
                        'home_team': ev.get('home_team'),
                        'away_team': ev.get('away_team'),
                        'recommendations': [cached_rec],
                        'headline': 'Cached pick (daily_top_picks)',
                        'block_reason': None,
                        '_source': 'daily_top_picks',
                        '_cached_date_et': today_et,
                        '_cached_computed_at': pick_row.get('computed_at').isoformat() if getattr(pick_row.get('computed_at'), 'isoformat', None) else str(pick_row.get('computed_at')),
                        '_cached_reason': pick_row.get('reason'),
                    }
                else:
                    # fall through to live analyze
                    analyzer = GameAnalyzer()
                    result = analyzer.analyze(event_id, "NCAAM", ev.get("home_team"), ev.get("away_team"))
            except Exception as e:
                print(f"[API] prefer_cached lookup failed; falling back to live analyze: {e}")
                analyzer = GameAnalyzer()
                result = analyzer.analyze(event_id, "NCAAM", ev.get("home_team"), ev.get("away_team"))
        else:
            analyzer = GameAnalyzer()
            result = analyzer.analyze(event_id, "NCAAM", ev.get("home_team"), ev.get("away_team"))

        # Ensure teams are included even if model wrapper doesn't add them
        result.setdefault("home_team", ev.get("home_team"))
        result.setdefault("away_team", ev.get("away_team"))

        # NET context (best-effort from cached DB snapshot)
        try:
            from src.database import fetch_team_net_row
            home_net = fetch_team_net_row(ev.get('home_team') or '')
            away_net = fetch_team_net_row(ev.get('away_team') or '')
            result['net_data'] = {
                'home': home_net,
                'away': away_net,
            }
        except Exception:
            pass

        return result
    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Analyze error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ncaam/net/ingest")
async def ingest_net_rankings():
    """Fetch and persist NCAA NET rankings snapshot from NCAA.com."""
    from src.services.ncaa_net_client import NcaamNetClient
    from src.database import upsert_ncaam_net_rankings_daily

    client = NcaamNetClient()
    raw = client.fetch()
    through, rows = client.parse(raw.get('html') or '')

    # Normalize asof_date string for storage
    asof = None
    if through:
        # e.g. "Through Games Feb. 13 2026" -> "2026-02-13"
        import re
        from datetime import datetime
        m = re.search(r"Through Games\s+([A-Za-z]{3,}\.?)\s+(\d{1,2})\s+(\d{4})", through)
        if m:
            try:
                dt = datetime.strptime(f"{m.group(1).replace('.', '')} {m.group(2)} {m.group(3)}", "%b %d %Y")
                asof = dt.strftime('%Y-%m-%d')
            except Exception:
                asof = None

    if not asof:
        from datetime import datetime
        asof = datetime.utcnow().strftime('%Y-%m-%d')

    payload = []
    for r in rows:
        payload.append({
            'asof_date': asof,
            'rank': r.rank,
            'school': r.school,
            'record': r.record,
            'conf': r.conf,
            'road': r.road,
            'neutral': r.neutral,
            'home': r.home,
            'prev': r.prev,
            'quad1': r.quad1,
            'quad2': r.quad2,
            'quad3': r.quad3,
            'quad4': r.quad4,
            'raw': r.raw,
        })

    upsert_ncaam_net_rankings_daily(payload)

    return {
        'status': 'success',
        'asof_date': asof,
        'through_games': through,
        'rows': len(payload),
    }


@app.get("/api/ncaam/net/team")
async def get_net_team(team: str, asof_date: str | None = None):
    from src.database import fetch_team_net_row
    if not team:
        raise HTTPException(status_code=400, detail='team is required')
    row = fetch_team_net_row(team, asof_date=asof_date)
    return { 'team': team, 'row': row }


@app.get("/api/ncaam/matchup-profiles")
async def get_matchup_profiles(request: Request, date: str | None = None):
    """Return KenPom + Torvik profiles for all teams playing on the given ET date.

    Used by the March Madness tab to render team profile cards alongside picks.
    Returns: { matchups: [ { event_id, home, away, home_kenpom, away_kenpom, home_torvik, away_torvik } ] }
    """
    from src.database import get_db_connection, _exec
    from src.services.edge_engine_ncaab import build_team_mapper

    if not date:
        with get_db_connection() as conn:
            date = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]

    try:
        with get_db_connection() as conn:
            # Get today's NCAAM events
            events = _exec(conn, """
                SELECT e.id, e.home_team, e.away_team, e.start_time,
                       DATE(e.start_time AT TIME ZONE 'America/New_York') as day_et
                FROM events e
                WHERE e.league = 'NCAAM'
                  AND DATE(e.start_time AT TIME ZONE 'America/New_York') = %s
                ORDER BY e.start_time
                LIMIT 100
            """, (date,)).fetchall()

            # Collect all unique team names using the standard mapper
            map_team = build_team_mapper(conn)
            teams = set()
            mapped_events = []
            for ev in events:
                h_map = map_team(ev['home_team'])
                a_map = map_team(ev['away_team'])
                teams.add(h_map)
                teams.add(a_map)
                
                # store the mapped names so we can look them up easily below
                mapped_events.append({
                    **dict(ev),
                    '_mapped_home': h_map,
                    '_mapped_away': a_map
                })

            # Bulk fetch KenPom ratings
            kenpom_map = {}
            if teams:
                krow = _exec(conn, """
                    SELECT team_name, rank, conference, record,
                           adj_em, adj_o, adj_d, adj_t, updated_at
                    FROM kenpom_ratings
                    WHERE team_name = ANY(%s)
                """, (list(teams),)).fetchall()
                for r in krow:
                    kenpom_map[r['team_name']] = dict(r)

            # Bulk fetch Torvik ratings (team_ratings table if it exists)
            torvik_map = {}
            try:
                trow = _exec(conn, """
                    SELECT team_name, adj_o, adj_d, adj_net, barthag, rank
                    FROM torvik_ratings
                    WHERE team_name = ANY(%s)
                """, (list(teams),)).fetchall()
                for r in trow:
                    torvik_map[r['team_name']] = dict(r)
            except Exception:
                pass  # table may not exist

            # Build response
            matchups = []
            for ev in mapped_events:
                st = ev.get('start_time')
                if hasattr(st, 'isoformat'):
                    try:
                        import pytz
                        st = st.astimezone(pytz.utc).isoformat().replace('+00:00', 'Z')
                    except Exception:
                        st = st.isoformat()
                home = ev['home_team']
                away = ev['away_team']
                h_map = ev['_mapped_home']
                a_map = ev['_mapped_away']
                hk = dict(kenpom_map.get(h_map) or {})
                ak = dict(kenpom_map.get(a_map) or {})
                # Remove datetime objects that aren't JSON serializable
                for k in list(hk.keys()):
                    if hasattr(hk[k], 'isoformat'):
                        hk[k] = str(hk[k])
                for k in list(ak.keys()):
                    if hasattr(ak[k], 'isoformat'):
                        ak[k] = str(ak[k])
                matchups.append({
                    'event_id': ev['id'],
                    'home_team': home,
                    'away_team': away,
                    'start_time': st,
                    'day_et': str(ev.get('day_et', '')),
                    'home_kenpom': hk,
                    'away_kenpom': ak,
                    'home_torvik': torvik_map.get(h_map, {}),
                    'away_torvik': torvik_map.get(a_map, {}),
                })

        return { 'date': date, 'matchups': matchups }
    except Exception as e:
        print(f"[matchup-profiles] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ncaam/matchup")
async def get_matchup_analysis(request: Request, team_a: str, team_b: str):
    """Generate or retrieve a head-to-head matchup analysis between two teams."""
    from src.services.profile_generator import ProfileGeneratorService
    
    profiler = ProfileGeneratorService()
    try:
        analysis = profiler.generate_matchup_analysis(team_a, team_b)
        return {"team_a": team_a, "team_b": team_b, "analysis": analysis}
    except Exception as e:
        print(f"[matchup] error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ncaam/tournament-teams")
async def get_tournament_teams(request: Request, limit: int = 80, generate: bool = False):
    """Return the top N teams by KenPom rank for bracket research profiles.
    
    Includes their Torvik metrics if available.
    Returns: { teams: [ { team_name, rank, conference, record, adj_em, adj_o, adj_d, adj_t, updated_at, torvik: {...}, profile: {...} } ] }
    """
    from src.database import get_db_connection, _exec
    from src.services.profile_generator import ProfileGeneratorService

    profiler = ProfileGeneratorService()

    try:
        with get_db_connection() as conn:
            # Fetch Top teams
            krows = _exec(conn, """
                SELECT team_name, rank, conference, record,
                       adj_em, adj_o, adj_d, adj_t, updated_at
                FROM kenpom_ratings
                ORDER BY rank ASC
                LIMIT %s
            """, (limit,)).fetchall()
            
            teams = [dict(r) for r in krows]
            team_names = [t['team_name'] for t in teams]

            # Fetch corresponding Torvik ratings
            torvik_map = {}
            if team_names:
                try:
                    trows = _exec(conn, """
                        SELECT team_name, adj_o, adj_d, adj_net, barthag, rank
                        FROM torvik_ratings
                        WHERE team_name = ANY(%s)
                    """, (team_names,)).fetchall()
                    for r in trows:
                        torvik_map[r['team_name']] = dict(r)
                except Exception:
                    pass  # table may not exist

            # Fetch NET rankings (quad records, home/away/neutral splits)
            net_map = {}
            try:
                nrows = _exec(conn, """
                    SELECT team_name, rank as net_rank, record,
                           quad1, quad2, quad3, quad4,
                           home, road, neutral
                    FROM ncaam_net_rankings
                """).fetchall()
                for r in nrows:
                    net_map[r['team_name']] = dict(r)
                
                # Also build a fuzzy index: stripped lowercase name -> row
                net_fuzzy = {}
                for name, row in net_map.items():
                    net_fuzzy[name.lower().replace(' ', '')] = row
            except Exception:
                net_fuzzy = {}

            def _find_net(kp_name):
                """Try exact match, then fuzzy match for NET rankings."""
                if kp_name in net_map:
                    return net_map[kp_name]
                key = kp_name.lower().replace(' ', '')
                return net_fuzzy.get(key, {})

            # Combine
            for t in teams:
                if hasattr(t.get('updated_at'), 'isoformat'):
                    t['updated_at'] = str(t['updated_at'])
                t['torvik'] = torvik_map.get(t['team_name'], {})
                
                # Attach NET data
                net = _find_net(t['team_name'])
                t['net_rank'] = net.get('net_rank')
                t['net_record'] = net.get('record')
                t['quad1'] = net.get('quad1')
                t['quad2'] = net.get('quad2')
                t['quad3'] = net.get('quad3')
                t['quad4'] = net.get('quad4')
                t['home_record'] = net.get('home')
                t['road_record'] = net.get('road')
                t['neutral_record'] = net.get('neutral')
                
                # Fetch cached or generate live if requested
                if generate:
                    t['profile'] = profiler.generate_profile(t['team_name'])
                else:
                    t['profile'] = profiler.get_cached_profile(t['team_name'])

        return { 'teams': teams }
    except Exception as e:
        print(f"[tournament-teams] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ncaam/team-deep-profile")
async def get_team_deep_profile(request: Request, team: str):
    """Return deep analytics for a single team: parsed player stats,
    team aggregates, Torvik deep metrics, Upset Risk Score, and Dark Horse Index.
    """
    from src.database import get_db_connection, _exec
    from src.services.kenpom_client import KenPomClient
    from src.utils.team_matcher import TeamMatcher

    kp_client = KenPomClient()
    matcher = TeamMatcher()

    def _safe_float(v, default=0.0):
        try:
            return float(str(v).replace('%','').replace('+','').strip())
        except Exception:
            return default

    def _parse_metric(metrics_jsonb, *candidates):
        if not metrics_jsonb:
            return None
        headers = metrics_jsonb.get('headers') or []
        cols = metrics_jsonb.get('cols') or []
        m = min(len(headers), len(cols))
        for i in range(m):
            hdr = str(headers[i] or '').lower()
            if any(c.lower() in hdr for c in candidates):
                return _safe_float(cols[i])
        return None

    try:
        with get_db_connection() as conn:
            # 1. KenPom team rating
            kp_name = matcher.find_source_name(team, 'kenpom_ratings', 'team_name') or team
            kp_row = _exec(conn, """
                SELECT team_name, rank, conference, record, adj_em, adj_o, adj_d, adj_t
                FROM kenpom_ratings WHERE team_name = %s LIMIT 1
            """, (kp_name,)).fetchone()
            kenpom = dict(kp_row) if kp_row else {}

            # 2. NET rankings
            net_row = _exec(conn, """
                SELECT team_name, rank as net_rank, record,
                       quad1, quad2, quad3, quad4, home, road, neutral
                FROM ncaam_net_rankings
                WHERE LOWER(REPLACE(team_name,' ','')) = LOWER(REPLACE(%s,' ',''))
                LIMIT 1
            """, (team,)).fetchone()
            if not net_row:
                net_row = _exec(conn, """
                    SELECT team_name, rank as net_rank, record,
                           quad1, quad2, quad3, quad4, home, road, neutral
                    FROM ncaam_net_rankings
                    WHERE team_name ILIKE %s LIMIT 1
                """, (f'%{team.split()[0]}%',)).fetchone()
            net = dict(net_row) if net_row else {}

            # 3. Torvik / BartTorvik deep metrics
            torvik_name = matcher.find_source_name(team, 'bt_team_metrics_daily', 'team_text')
            torvik_row = None
            if torvik_name:
                try:
                    torvik_row = _exec(conn, """
                        SELECT adj_off, adj_def, adj_tempo, luck, continuity, torvik_rank, record
                        FROM bt_team_metrics_daily
                        WHERE team_text = %s
                        ORDER BY date DESC LIMIT 1
                    """, (torvik_name,)).fetchone()
                except Exception:
                    pass
            torvik = dict(torvik_row) if torvik_row else {}

            # Barthag from torvik_ratings
            torvik_rat_name = matcher.find_source_name(team, 'torvik_ratings', 'team_name')
            barthag = None
            if torvik_rat_name:
                try:
                    tr = _exec(conn, """
                        SELECT barthag, rank, adj_o, adj_d
                        FROM torvik_ratings WHERE team_name = %s LIMIT 1
                    """, (torvik_rat_name,)).fetchone()
                    if tr:
                        barthag = tr['barthag']
                        if not torvik.get('adj_off'):
                            torvik['adj_off'] = tr['adj_o']
                        if not torvik.get('adj_def'):
                            torvik['adj_def'] = tr['adj_d']
                        if not torvik.get('torvik_rank'):
                            torvik['torvik_rank'] = tr['rank']
                except Exception:
                    pass
            torvik['barthag'] = barthag

            # 4. Player stats
            raw_players = kp_client.get_player_stats_for_team(team, limit=40)

            def _player_minutes(p):
                return _parse_metric(p.get('metrics'), 'min', 'minute') or 0

            raw_players.sort(key=_player_minutes, reverse=True)

            players = []
            for p in raw_players[:8]:
                m = p.get('metrics') or {}
                players.append({
                    'name':    p.get('player_name', 'Unknown'),
                    'ppg':     _parse_metric(m, 'pts', 'ppg', 'points'),
                    'apg':     _parse_metric(m, 'ast', 'apg', 'assist'),
                    'rpg':     _parse_metric(m, 'reb', 'rpg', 'rebound'),
                    'ortg':    _parse_metric(m, 'o-rat', 'ortg', 'off rat'),
                    'usg':     _parse_metric(m, 'usag', 'usg', 'usage'),
                    'efg':     _parse_metric(m, 'efg', 'eff fg', 'effective'),
                    'min_pct': _parse_metric(m, '%min', 'min%', 'min pct', 'minute%') or _player_minutes(p),
                })

            # 5. Team player aggregates
            team_agg_row = kp_client.get_team_player_agg(team)
            team_agg = {}
            if team_agg_row:
                team_agg = {k: v for k, v in {
                    'ortg_w':       team_agg_row.get('ortg_w'),
                    'efg_w':        team_agg_row.get('efg_w'),
                    'ts_w':         team_agg_row.get('ts_w'),
                    'ast_rate_w':   team_agg_row.get('ast_rate_w'),
                    'reb_rate_w':   team_agg_row.get('reb_rate_w'),
                    'tov_rate_w':   team_agg_row.get('tov_rate_w'),
                    'top7_min_pct': team_agg_row.get('top7_minutes_pct'),
                    'n_players':    team_agg_row.get('n_players'),
                }.items() if v is not None}

        # 6. Upset Risk Score
        upset_score = 0
        upset_factors = []
        luck = _safe_float(torvik.get('luck'), 0)
        continuity = _safe_float(torvik.get('continuity'), 0)
        top7_min = _safe_float(team_agg.get('top7_min_pct'), 0)
        kp_rank = int(kenpom.get('rank') or 50)
        net_rank_v = int(net.get('net_rank') or 50)
        tov_rate = _safe_float(team_agg.get('tov_rate_w'), 0)

        if luck > 0.04:
            upset_score += 25
            upset_factors.append(f"Lucky season (+{luck:.2f}) — regression risk in pressure games")
        if top7_min > 88:
            upset_score += 20
            upset_factors.append(f"Over-reliant on top 7 ({top7_min:.0f}% mins) — foul trouble = collapse risk")
        if 0 < continuity < 60:
            upset_score += 20
            upset_factors.append(f"Low roster continuity ({continuity:.0f}%) — limited NCAA tournament experience")
        rank_gap = net_rank_v - kp_rank
        if rank_gap > 15:
            upset_score += 20
            upset_factors.append(f"Over-seeded: NET #{net_rank_v} vs KenPom #{kp_rank} (+{rank_gap} gap)")
        if tov_rate > 20:
            upset_score += 15
            upset_factors.append(f"High turnovers ({tov_rate:.1f}%) — vulnerable under pressure-game execution")
        if not upset_factors:
            upset_factors.append("No significant upset flags detected — solid fundamentals")

        # 7. Dark Horse Index
        dh_score = 0
        dh_factors = []
        adj_em = _safe_float(kenpom.get('adj_em'), 0)
        bath_v = _safe_float(barthag, 0)
        q1_raw = net.get('quad1') or '0-0'
        try:
            q1_wins = int(str(q1_raw).split('-')[0])
        except Exception:
            q1_wins = 0

        if bath_v > 0.88:
            dh_score += 30
            dh_factors.append(f"Elite Barthag ({bath_v*100:.1f}%) — underlying quality outpaces seeding")
        if luck < 0.00:
            dh_score += 20
            dh_factors.append(f"Unlucky season ({luck:.2f}) — due for positive regression in bracket")
        if continuity >= 75:
            dh_score += 20
            dh_factors.append(f"High roster continuity ({continuity:.0f}%) — experienced tournament rotation")
        if kp_rank > 12 and adj_em > 22:
            dh_score += 20
            dh_factors.append(f"Underrated efficiency: KP #{kp_rank} with AdjEM +{adj_em:.1f}")
        if q1_wins >= 6:
            dh_score += 10
            dh_factors.append(f"Strong Q1 resume ({q1_wins} wins) — proven vs elite")
        if not dh_factors:
            dh_factors.append("No significant dark horse signals — team is accurately seeded")

        def _clean(d):
            return {k: (str(v) if hasattr(v, 'isoformat') else v) for k, v in (d or {}).items()}

        return {
            'team_name':  team,
            'kenpom':     _clean(kenpom),
            'net':        _clean(net),
            'torvik':     _clean(torvik),
            'team_agg':   _clean(team_agg),
            'players':    players,
            'upset_risk': {'score': min(upset_score, 100), 'factors': upset_factors},
            'dark_horse': {'score': min(dh_score, 100), 'factors': dh_factors},
        }

    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ncaam/history")
async def get_ncaam_history(request: Request, limit: int = 100, user: dict = Depends(get_current_user)):
    """Returns past model predictions/analysis (recommended picks).

    Note: legacy single-user rows may have NULL/mismatched user_id; we fall back to unscoped.
    """
    from src.database import fetch_model_history

    try:
        limit = int(limit)
    except Exception:
        limit = 100
    limit = max(1, min(limit, 5000))

    uid = (user or {}).get('sub')

    cache_key = f"ncaam:history:{uid or 'anon'}:{limit}"

    def _build():
        data = fetch_model_history(limit=limit, league='NCAAM', user_id=uid, recommended_only=True)
        if not data:
            data = fetch_model_history(limit=limit, league='NCAAM', user_id=None, recommended_only=True)
        return _ensure_utc(data)

    # Short TTL: avoids re-downloading large payloads + reduces DB reads.
    return _cached_json(request, cache_key, ttl_s=int(os.getenv('NCAAM_HISTORY_TTL_SECONDS', '60')), build_fn=_build)

@app.get("/api/ncaam/top6/rank-performance")
async def ncaam_top6_rank_performance(days: int = 365):
    """Performance of the daily Top-6 recommended bets, by rank.

    Definition:
    - For each ET day, rank all *actionable* model_predictions by ev_per_unit desc.
    - Take ranks 1..6.

    Returns win% by rank (and by market_type + confidence tier).
    """
    from src.database import get_db_connection, _exec

    try:
        days = int(days)
    except Exception:
        days = 365
    days = max(7, min(days, 3650))

    with get_db_connection() as conn:
        rows = _exec(
            conn,
            """
            WITH base AS (
              SELECT
                p.*,
                e.league,
                DATE(e.start_time AT TIME ZONE 'America/New_York') AS day_et
              FROM model_predictions p
              JOIN events e ON e.id = p.event_id
              WHERE e.league = 'NCAAM'
                AND p.analyzed_at >= NOW() - (%s || ' days')::interval
                AND p.outcome IN ('WON','LOST','PUSH')
                AND COALESCE(p.ev_per_unit, 0) >= 0.0001
            ),
            ranked AS (
              SELECT
                day_et,
                market_type,
                outcome,
                COALESCE(confidence_0_100, 0) AS conf,
                ROW_NUMBER() OVER (PARTITION BY day_et ORDER BY ev_per_unit DESC NULLS LAST) AS rk
              FROM base
            ),
            top6 AS (
              SELECT *
              FROM ranked
              WHERE rk BETWEEN 1 AND 6
            ),
            bucketed AS (
              SELECT
                rk,
                market_type,
                CASE
                  WHEN conf >= 70 THEN 'high'
                  WHEN conf >= 50 THEN 'medium'
                  ELSE 'low'
                END AS conf_tier,
                outcome
              FROM top6
            )
            SELECT
              rk AS rank,
              market_type,
              conf_tier,
              COUNT(*)::int AS n,
              SUM(CASE WHEN outcome='WON' THEN 1 ELSE 0 END)::int AS won,
              SUM(CASE WHEN outcome='LOST' THEN 1 ELSE 0 END)::int AS lost,
              SUM(CASE WHEN outcome='PUSH' THEN 1 ELSE 0 END)::int AS push
            FROM bucketed
            GROUP BY rk, market_type, conf_tier
            ORDER BY rk ASC, market_type ASC, conf_tier ASC;
            """,
            (days,),
        ).fetchall()

    return {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'league': 'NCAAM',
        'window_days': int(days),
        'rows': [dict(r) for r in rows],
    }


@app.get("/api/ncaam/recommended-slate/yesterday")
async def get_ncaam_recommended_slate_yesterday(user: dict = Depends(get_current_user)):
    """Return the exact slate that was recommended yesterday (Top N) and its outcomes.

    This is the source of truth for aligning "recommended" vs "graded".

    Selection rule:
    - Use latest recommended_slates row for yesterday (prefer source='full' if it exists), else latest of any source.

    Returns:
      { date_et, slate: {id,source,created_at}, straight: [...], ml_parlay: [...], record: {...} }
    """
    from src.database import get_db_connection, _exec

    with get_db_connection() as conn:
        yday = _exec(conn, "SELECT ((NOW() AT TIME ZONE 'America/New_York')::date - INTERVAL '1 day')::date::text").fetchone()[0]

        # Pick the slate: prioritize 'cached' (morning slate) over 'full' (late slate)
        # to ensure the "Yesterday" card matches the original recommendations.
        s = _exec(conn, """
          SELECT id, source, created_at
          FROM recommended_slates
          WHERE league='NCAAM' AND date_et=%s
          ORDER BY (CASE WHEN source = 'cached' THEN 0 ELSE 1 END) ASC, created_at ASC
          LIMIT 1
        """, (yday,)).fetchone()


        slate = dict(s) if s else None
        if not slate:
            return {"status": "success", "date_et": yday, "slate": None, "straight": [], "ml_parlay": [], "record": {"straight": None, "ml_parlay": None}}

        rows = _exec(conn, """
          SELECT r.rank,
                 r.prediction_id,
                 COALESCE(m1.id, m2.id) as linked_prediction_id,
                 COALESCE(m1.event_id, m2.event_id, r.event_id) as event_id,
                 COALESCE(m1.market_type, m2.market_type, r.market_type) as market_type,
                 COALESCE(m1.selection, m2.selection, r.selection) as selection,
                 COALESCE(COALESCE(m1.bet_price, m1.price), COALESCE(m2.bet_price, m2.price), r.bet_price) as price,
                 COALESCE(m1.ev_per_unit, m2.ev_per_unit) as ev_per_unit,
                 COALESCE(m1.confidence_0_100, m2.confidence_0_100) as confidence_0_100,
                 COALESCE(m1.outcome, m2.outcome) as outcome,
                 e.away_team, e.home_team, e.start_time
          FROM recommended_slate_items r
          LEFT JOIN model_predictions m1 ON m1.id=r.prediction_id
          LEFT JOIN LATERAL (
            SELECT m.*
            FROM model_predictions m
            WHERE r.event_id IS NOT NULL
              AND m.event_id=r.event_id
              AND (r.selection IS NULL OR m.selection=r.selection)
              AND (r.bet_price IS NULL OR COALESCE(m.bet_price, m.price)=r.bet_price)
            ORDER BY m.analyzed_at DESC
            LIMIT 1
          ) m2 ON TRUE
          JOIN events e ON e.id=COALESCE(m1.event_id, m2.event_id, r.event_id)
          WHERE r.slate_id=%s
          ORDER BY r.rank ASC
        """, (slate['id'],)).fetchall()

    def norm_outcome(o: str) -> str:
        s = str(o or '').upper()
        if s in ('WIN', 'WON'): return 'WON'
        if s in ('LOSS', 'LOST'): return 'LOST'
        if s == 'PUSH': return 'PUSH'
        return 'PENDING'

    def is_decided(o: str) -> bool:
        return norm_outcome(o) in ('WON', 'LOST', 'PUSH')

    def classify(mt: str) -> str:
        t = str(mt or '').upper()
        if 'SPREAD' in t:
            return 'SPREAD'
        if 'TOTAL' in t:
            return 'TOTAL'
        if 'MONEYLINE' in t or t == 'ML':
            return 'MONEYLINE'
        return 'OTHER'

    items = [dict(r) for r in rows]

    straight = [x for x in items if classify(x.get('market_type')) in ('SPREAD','TOTAL')]
    ml_parlay = [x for x in items if classify(x.get('market_type')) == 'MONEYLINE']

    def record(xs):
        decided = [x for x in xs if is_decided(x.get('outcome'))]
        w = sum(1 for x in decided if norm_outcome(x.get('outcome')) == 'WON')
        l = sum(1 for x in decided if norm_outcome(x.get('outcome')) == 'LOST')
        p = sum(1 for x in decided if norm_outcome(x.get('outcome')) == 'PUSH')
        return {"won": w, "lost": l, "push": p, "decided": len(decided)}

    # JSON-friendly created_at
    try:
        ca = slate.get('created_at')
        if hasattr(ca, 'isoformat'):
            slate['created_at'] = ca.isoformat().replace('+00:00', 'Z')
    except Exception:
        pass

    return {
        "status": "success",
        "date_et": yday,
        "slate": slate,
        "straight": straight,
        "ml_parlay": ml_parlay,
        "record": {
            "straight": record(straight),
            "ml_parlay": record(ml_parlay),
        }
    }


@app.get("/api/ncaam/performance-report")
async def ncaam_performance_report(days: int = 30):
    """NCAAM model performance report.

    Designed for the Vercel UI so you can view it anytime.

    Includes:
    - summary windows (7d, 30d)
    - daily recommended bets (last N days)

    Notes:
    - Uses model_predictions + events join (league filter via events).
    - ROI uses realized outcomes and actual bet_price when present; otherwise assumes -110.
    """
    from src.database import get_db_connection, _exec

    # Helpers imported from src.utils.model_performance

    try:
        days = int(days)
    except Exception:
        days = 30
    days = max(3, min(days, 120))

    def window_stats(window_days: int):
        with get_db_connection() as conn:
            rows = _exec(conn, """
              SELECT m.outcome, m.bet_price, m.ev_per_unit, m.clv_points
              FROM model_predictions m
              JOIN recommended_slate_items rsi ON m.id = rsi.prediction_id
              JOIN recommended_slates rs ON rsi.slate_id = rs.id
              WHERE rs.league='NCAAM'
                AND rs.date_et > (NOW() AT TIME ZONE 'America/New_York' - (%(d)s || ' days')::interval)::date::text
                AND rsi.rank <= 6
            """, {"d": int(window_days)}).fetchall()

        decided = [r for r in rows if norm_outcome(r['outcome']) in ('WON','LOST','PUSH')]
        won = sum(1 for r in decided if norm_outcome(r['outcome']) == 'WON')
        lost = sum(1 for r in decided if norm_outcome(r['outcome']) == 'LOST')
        push = sum(1 for r in decided if norm_outcome(r['outcome']) == 'PUSH')
        n = len(decided)
        win_rate = (won / (won + lost) * 100.0) if (won + lost) else 0.0

        # ROI per unit wagered
        roi_vals = [roi_per_unit(r['outcome'], r['bet_price'] if r['bet_price'] is not None else -110) for r in decided]
        roi = (sum(roi_vals) / n * 100.0) if n else 0.0

        ev_vals = [float(r['ev_per_unit'] or 0.0) for r in rows]
        avg_ev = (sum(ev_vals) / len(ev_vals)) if ev_vals else 0.0

        clv_vals = [float(r['clv_points']) for r in rows if r.get('clv_points') is not None]
        avg_clv = (sum(clv_vals) / len(clv_vals)) if clv_vals else None
        pos_clv_rate = (sum(1 for x in clv_vals if x > 0) / len(clv_vals) * 100.0) if clv_vals else None

        return {
            "days": window_days,
            "decided": n,
            "record": {"won": won, "lost": lost, "push": push},
            "win_rate": round(win_rate, 2),
            "roi_pct": round(roi, 2),
            "avg_ev_per_unit": round(avg_ev, 4),
            "avg_clv_points": round(avg_clv, 3) if avg_clv is not None else None,
            "pos_clv_rate": round(pos_clv_rate, 2) if pos_clv_rate is not None else None,
        }

    # Daily picks (last N days)
    with get_db_connection() as conn:
        rows = _exec(conn, """
          SELECT 
            rs.date_et AS day_et,
            rsi.event_id,
            e.away_team,
            e.home_team,
            e.start_time,
            rsi.market_type,
            rsi.selection,
            rsi.bet_line,
            rsi.bet_price,
            m.ev_per_unit,
            m.confidence_0_100,
            m.clv_points,
            m.outcome,
            gr.home_score,
            gr.away_score,
            gr.final,
            rsi.rank
          FROM recommended_slates rs
          JOIN recommended_slate_items rsi ON rs.id = rsi.slate_id
          LEFT JOIN model_predictions m ON m.id = rsi.prediction_id
          JOIN events e ON rsi.event_id = e.id
          LEFT JOIN game_results gr ON gr.event_id = rsi.event_id
          WHERE rs.league = 'NCAAM'
            AND rs.date_et > (NOW() AT TIME ZONE 'America/New_York' - (%(d)s || ' days')::interval)::date::text
            AND rsi.rank <= 6
          ORDER BY rs.date_et DESC, rsi.rank ASC
          LIMIT 1000
        """, {"d": int(days)}).fetchall()

    by_day = {}
    for r in rows:
        day = r['day_et']
        by_day.setdefault(day, [])
        hs = r.get('home_score') if isinstance(r, dict) else None
        aw = r.get('away_score') if isinstance(r, dict) else None
        final = r.get('final') if isinstance(r, dict) else None
        score = None
        if hs is not None and aw is not None:
            score = f"{aw}-{hs}"  # away-home

        price = r['bet_price'] if r.get('bet_price') is not None else -110
        o = (r.get('outcome') or '').upper()
        roi_u = roi_per_unit(o, price) if o in ('WON','LOST','PUSH') else None

        by_day[day].append({
            "event_id": r['event_id'],
            "matchup": f"{r['away_team']} @ {r['home_team']}",
            "start_time": r['start_time'],
            "market_type": r['market_type'],
            "selection": r['selection'],
            "line": r['bet_line'],
            "price": r['bet_price'],
            "ev_per_unit": float(r['ev_per_unit'] or 0.0),
            "confidence_0_100": int(r['confidence_0_100'] or 0),
            "clv_points": float(r['clv_points']) if r.get('clv_points') is not None else None,
            "outcome": r['outcome'],
            "roi_per_unit": float(roi_u) if roi_u is not None else None,
            "final": bool(final) if final is not None else None,
            "final_score": score,
        })

    daily = [
        {"day": d, "picks": by_day[d]}
        for d in sorted(by_day.keys(), reverse=True)
    ]

    # Pending / coverage summary
    with get_db_connection() as conn:
        cov = _exec(conn, """
          SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE (m.outcome IS NULL OR m.outcome='PENDING')) as pending,
            COUNT(*) FILTER (WHERE (m.outcome IN ('WON','LOST','PUSH'))) as decided,
            COUNT(*) FILTER (WHERE (m.outcome IS NULL OR m.outcome='PENDING') AND gr.final=TRUE) as pending_but_final_available
          FROM recommended_slates rs
          JOIN recommended_slate_items rsi ON rs.id = rsi.slate_id
          LEFT JOIN model_predictions m ON m.id = rsi.prediction_id
          LEFT JOIN game_results gr ON gr.event_id = rsi.event_id
          WHERE rs.league = 'NCAAM'
            AND rs.date_et > (NOW() AT TIME ZONE 'America/New_York' - (%(d)s || ' days')::interval)::date::text
            AND rsi.rank <= 6
        """, {"d": int(days)}).fetchone()
    coverage = dict(cov) if cov else {}

    # Helpers imported from src.utils.model_performance

    # Confidence breakdown (decided only)
    conf_rows = []
    with get_db_connection() as conn:
        conf_rows = _exec(conn, """
          SELECT m.outcome, m.confidence_0_100
          FROM model_predictions m
          JOIN recommended_slate_items rsi ON m.id = rsi.prediction_id
          JOIN recommended_slates rs ON rsi.slate_id = rs.id
          WHERE rs.league = 'NCAAM'
            AND rs.date_et > (NOW() AT TIME ZONE 'America/New_York' - (%(d)s || ' days')::interval)::date::text
            AND rsi.rank <= 6
            AND (m.outcome IN ('WON','LOST','PUSH'))
        """, {"d": int(days)}).fetchall()

    by_conf = {"High": {"won": 0, "lost": 0, "push": 0}, "Medium": {"won": 0, "lost": 0, "push": 0}, "Low": {"won": 0, "lost": 0, "push": 0}}
    for r in conf_rows:
        b = conf_bucket(r.get('confidence_0_100'))
        o = (r.get('outcome') or '').upper()
        if o == 'WON':
            by_conf[b]['won'] += 1
        elif o == 'LOST':
            by_conf[b]['lost'] += 1
        elif o == 'PUSH':
            by_conf[b]['push'] += 1

    conf_breakdown = []
    for b in ("High", "Medium", "Low"):
        won = by_conf[b]['won']
        lost = by_conf[b]['lost']
        push = by_conf[b]['push']
        decided = won + lost + push
        wl = won + lost
        win_rate = (won / wl * 100.0) if wl else 0.0
        conf_breakdown.append({
            "bucket": b,
            "record": {"won": won, "lost": lost, "push": push},
            "decided": decided,
            "win_rate": round(win_rate, 2),
        })

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "league": "NCAAM",
        "windows": {
            "7d": window_stats(7),
            "30d": window_stats(30),
        },
        "coverage": coverage,
        "confidence_breakdown": conf_breakdown,
        "daily_recommended_bets": daily,
    }


@app.get("/api/model/performance/scatter")
async def get_model_performance_scatter(days: int = 60, min_ev_per_unit: float = 0.02):
    """Scatter breakout: win% vs ROI by league + market_type.

    Intended for UI: each point is a (sport/league, bet type) bucket.
    Filters to recommended bets via min_ev_per_unit.
    """
    from src.database import get_db_connection, _exec

    def payout_per_unit(price: int) -> float:
        if price is None:
            price = -110
        p = int(price)
        return (p / 100.0) if p > 0 else (100.0 / abs(p))

    def norm_outcome(o: str) -> str:
        s = str(o or '').upper()
        if s in ('WIN', 'WON'): return 'WON'
        if s in ('LOSS', 'LOST'): return 'LOST'
        if s == 'PUSH': return 'PUSH'
        return 'PENDING'

    def roi_per_unit(outcome: str, price: int) -> float:
        o = norm_outcome(outcome)
        if o == 'WON':
            return payout_per_unit(price)
        if o == 'LOST':
            return -1.0
        return 0.0

    try:
        days = int(days)
    except Exception:
        days = 60
    days = max(7, min(days, 365))

    try:
        min_ev = float(min_ev_per_unit)
    except Exception:
        min_ev = 0.02
    
    # Helpers imported from src.utils.model_performance

    with get_db_connection() as conn:
        rows = _exec(conn, """
          SELECT
            e.league as sport,
            COALESCE(NULLIF(m.market_type,''), 'UNKNOWN') as market_type,
            m.outcome,
            COALESCE(m.bet_price, -110) as price
          FROM model_predictions m
          JOIN events e ON m.event_id=e.id
          WHERE m.analyzed_at > NOW() - (%(d)s || ' days')::interval
            AND COALESCE(m.ev_per_unit,0) >= %(min_ev)s
            AND m.market_type IS NOT NULL AND UPPER(m.market_type) <> 'AUTO'
            AND m.pick IS NOT NULL AND UPPER(m.pick) <> 'NONE'
            AND m.selection IS NOT NULL AND TRIM(m.selection) <> '' AND m.selection <> '—'
            AND m.outcome IN ('WON','LOST','PUSH')
        """, {"d": int(days), "min_ev": float(min_ev)}).fetchall()

    buckets = {}
    for r in rows:
        sport = r.get('sport')
        mt = (r.get('market_type') or '').upper()
        key = (sport, mt)
        buckets.setdefault(key, [])
        buckets[key].append(dict(r))

    out = []
    for (sport, mt), xs in buckets.items():
        won = sum(1 for x in xs if (x.get('outcome') or '').upper() == 'WON')
        lost = sum(1 for x in xs if (x.get('outcome') or '').upper() == 'LOST')
        push = sum(1 for x in xs if (x.get('outcome') or '').upper() == 'PUSH')
        decided = won + lost + push
        wl = won + lost
        win_rate = (won / wl * 100.0) if wl else 0.0
        roi_vals = [roi_per_unit(x.get('outcome'), x.get('price')) for x in xs]
        roi_pct = (sum(roi_vals) / decided * 100.0) if decided else 0.0
        
        conf_vals = [float(x.get('confidence_0_100') or 0) for x in xs]
        avg_conf = (sum(conf_vals) / decided) if decided else 0.0

        out.append({
            "sport": sport,
            "market_type": mt,
            "n": decided,
            "won": won,
            "lost": lost,
            "push": push,
            "win_rate": round(win_rate, 2),
            "roi_pct": round(roi_pct, 2),
            "avg_confidence": round(avg_conf, 1)
        })

    # stable sort
    out.sort(key=lambda x: (x.get('sport') or '', x.get('market_type') or ''))

    return {
        "generated_at": datetime.utcnow().isoformat() + 'Z',
        "days": int(days),
        "min_ev_per_unit": float(min_ev),
        "points": out,
    }


@app.get("/api/ncaam/analytics")
async def get_ncaam_analytics(days: int = 30, min_ev_per_unit: float = 0.02):
    """Aggregated model performance stats for NCAAM.

    IMPORTANT: This is *model* performance, not bankroll.
    Default filter is "recommended" only via min_ev_per_unit (>= 0.02 => 2% EV/u).
    """
    from src.database import get_db_connection, _exec

    query = """
    SELECT 
        COUNT(*) as total_bets,
        COUNT(*) FILTER (WHERE outcome = 'WON') as wins,
        COUNT(*) FILTER (WHERE outcome = 'LOST') as losses,
        COUNT(*) FILTER (WHERE outcome = 'PUSH') as pushes,
        COUNT(*) FILTER (WHERE outcome = 'PENDING' OR outcome IS NULL) as pending,
        AVG(edge_points) FILTER (WHERE outcome NOT IN ('PENDING', 'VOID')) as avg_edge,
        AVG(ev_per_unit) FILTER (WHERE outcome NOT IN ('PENDING', 'VOID')) as avg_ev,
        AVG(clv_points) FILTER (WHERE outcome NOT IN ('PENDING', 'VOID')) as avg_clv
    FROM model_predictions m
    JOIN events e ON m.event_id=e.id
    WHERE e.league='NCAAM'
      AND m.analyzed_at > NOW() - (INTERVAL '1 day' * :days)
      AND COALESCE(m.ev_per_unit, 0) >= :min_ev
    """

    try:
        with get_db_connection() as conn:
            row = _exec(conn, query, {"days": days, "min_ev": float(min_ev_per_unit)}).fetchone()
            if not row:
                return {}

            stats = dict(row)
            decided = (stats['wins'] or 0) + (stats['losses'] or 0)
            stats['win_rate'] = (stats['wins'] / decided * 100) if decided > 0 else 0.0

            return stats

    except Exception as e:
        print(f"[Analytics] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ncaam/anchors/today")
async def get_ncaam_anchor_ml_today(
    min_edge_prob: float = 0.03,
    odds_lo: int = -450,
    odds_hi: int = -220,
    limit: int = 3,
):
    """Anchor ML picks for today (heavy favorites) for parlay construction.

    Philosophy: low-variance legs, but still require the model to beat the implied probability.

    Filters:
    - Moneyline-only model_predictions (today ET)
    - American odds between [odds_lo, odds_hi] (negative favorites)
    - edge_prob = win_prob - implied_prob >= min_edge_prob

    Returns: {date_et, anchors:[...]}
    """
    from src.database import get_db_connection, _exec
    from src.utils.ev import implied_prob_american

    with get_db_connection() as conn:
        date_et = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]

        rows = _exec(conn, """
          SELECT
            m.event_id,
            COALESCE(m.bet_price, m.price) AS price,
            m.win_prob,
            m.ev_per_unit,
            m.selection,
            m.model_version,
            e.away_team,
            e.home_team,
            e.start_time
          FROM model_predictions m
          JOIN events e ON e.id=m.event_id
          WHERE e.league='NCAAM'
            AND UPPER(COALESCE(m.market_type,'')) IN ('MONEYLINE','ML')
            AND (m.analyzed_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')::date = %s::date
            AND COALESCE(m.bet_price, m.price) IS NOT NULL
            AND m.win_prob IS NOT NULL
          ORDER BY m.analyzed_at DESC
          LIMIT 500
        """, (date_et,)).fetchall()

    cands = []
    for r in rows or []:
        d = dict(r)
        try:
            price = int(d.get('price'))
            wp = float(d.get('win_prob'))
        except Exception:
            continue
        if not (0.0 < wp < 1.0):
            continue
        if price >= 0:
            continue
        if price < int(odds_lo) or price > int(odds_hi):
            continue

        ip = implied_prob_american(price)
        if ip is None:
            continue
        edge_prob = wp - float(ip)
        if edge_prob < float(min_edge_prob):
            continue

        cands.append({
            "event_id": d.get('event_id'),
            "matchup": f"{d.get('away_team')} @ {d.get('home_team')}",
            "team_pick": d.get('selection'),
            "price": price,
            "win_prob": wp,
            "implied_prob": float(ip),
            "edge_prob": float(edge_prob),
            "ev_per_unit": float(d.get('ev_per_unit') or 0.0),
            "model_version": d.get('model_version'),
            "start_time": str(d.get('start_time') or ''),
        })

    # Sort by edge_prob, then EV/u
    cands.sort(key=lambda x: (x.get('edge_prob') or 0.0, x.get('ev_per_unit') or 0.0), reverse=True)
    anchors = cands[: max(1, min(int(limit), 10))]

    return {
        "status": "success",
        "date_et": date_et,
        "params": {
            "min_edge_prob": float(min_edge_prob),
            "odds_lo": int(odds_lo),
            "odds_hi": int(odds_hi),
            "limit": int(limit),
        },
        "anchors": anchors,
    }


@app.get("/api/ncaam/parlays/today")
async def get_ncaam_parlays_today(
    min_ev_per_unit: float = 0.02,
    parlay_odds_lo: int = -120,
    parlay_odds_hi: int = 800,
    max_legs: int = 2,
    limit_legs: int = 80,
    strategy: str = "all",  # 'all' | 'home_fav'
    days_ago: int = 0,
):
    """2-leg ML parlay recommendations for today's NCAAM slate.

    Source: model_predictions (Moneyline only). Read-only.

    strategy='all'     : all ML picks that pass EV gate (default)
    strategy='home_fav': only home-team favorites (pick==home_team, price<0)
                         Combined odds band defaults to -180..+250

    Returns two lists:
    - high_confidence: highest P(win) combos
    - payout_band: best EV combos within a reasonable payout range
    """
    if int(max_legs) != 2:
        raise HTTPException(status_code=400, detail="Only 2-leg parlays supported in v1")

    # For home_fav strategy, tighten the default odds band if caller did not override
    _strategy = str(strategy or 'all').lower().strip()
    if _strategy == 'home_fav':
        # Only override defaults, not explicit caller params.
        # FastAPI doesn't differentiate default vs explicit, so we use sentinel checks:
        # If caller passed the global defaults (-120 / 800), apply home_fav tighter defaults.
        if parlay_odds_lo == -120:
            parlay_odds_lo = -180
        if parlay_odds_hi == 800:
            parlay_odds_hi = 250

    from src.database import get_db_connection, _exec

    def dec_from_american(a: int) -> float:
        a = int(a)
        return 1.0 + (a / 100.0) if a > 0 else 1.0 + (100.0 / abs(a))

    def implied_prob(a: int) -> float:
        a = int(a)
        return 100.0 / (a + 100.0) if a > 0 else abs(a) / (abs(a) + 100.0)

    def american_from_dec(d: float) -> int:
        # d is decimal odds
        if d <= 1.0:
            return 0
        x = d - 1.0
        if x >= 1.0:
            return int(round(x * 100))
        return int(round(-100 / x))

    # ET date filter
    q = """
      WITH latest_preds AS (
        SELECT DISTINCT ON (m.event_id)
          m.event_id,
          m.model_version,
          m.market_type,
          m.pick,
          m.outcome,
          m.bet_line,
          COALESCE(m.bet_price, m.price) AS price,
          m.win_prob,
          m.ev_per_unit,
          m.selection,
          e.away_team,
          e.home_team,
          e.start_time,
          (e.start_time AT TIME ZONE 'America/New_York')::date::text AS day_et
        FROM model_predictions m
        JOIN events e ON m.event_id = e.id
        WHERE e.league = 'NCAAM'
          AND UPPER(COALESCE(m.market_type,'')) IN ('MONEYLINE','ML')
          AND (e.start_time AT TIME ZONE 'America/New_York')::date = (NOW() AT TIME ZONE 'America/New_York' - (%(days)s || ' days')::interval)::date
          AND COALESCE(m.ev_per_unit, 0) >= %(min_ev)s
          AND COALESCE(m.bet_price, m.price) IS NOT NULL
        ORDER BY m.event_id, m.analyzed_at DESC
      )
      SELECT * FROM latest_preds
      ORDER BY win_prob DESC
      LIMIT %(lim)s
    """

    with get_db_connection() as conn:
        legs = [dict(r) for r in _exec(conn, q, {"min_ev": float(min_ev_per_unit), "lim": int(limit_legs), "days": int(days_ago)}).fetchall()]

    # Build normalized leg objects
    norm_legs = []
    for r in legs:
        try:
            price = int(r.get('price'))
        except Exception:
            continue
        wp = r.get('win_prob')
        try:
            wp = float(wp) if wp is not None else None
        except Exception:
            wp = None
        if wp is None or not (0 < wp < 1.0):
            continue

        home_team = r.get('home_team') or ''
        pick = r.get('pick') or r.get('selection') or ''
        is_home_pick = (pick.strip().lower() == home_team.strip().lower())

        norm_legs.append({
            "event_id": r.get('event_id'),
            "matchup": f"{r.get('away_team')} @ {r.get('home_team')}",
            "team_pick": r.get('selection') or r.get('pick'),
            "price": price,
            "win_prob": wp,
            "ev_per_unit": float(r.get('ev_per_unit') or 0),
            "outcome": r.get('outcome'),
            "model_version": r.get('model_version'),
            "start_time": str(r.get('start_time') or ''),
            "is_home_pick": is_home_pick,
        })

    # Apply strategy filter AFTER building norm_legs so we can inspect is_home_pick
    if _strategy == 'home_fav':
        # Keep only legs where the model is picking the home team AND they are HIGHLY favored (ML <= -150)
        norm_legs = [leg for leg in norm_legs if leg.get('is_home_pick') and leg.get('price', 0) <= -150]

    # Enumerate all 2-leg combos (different events)
    combos = []
    for i in range(len(norm_legs)):
        for j in range(i + 1, len(norm_legs)):
            a = norm_legs[i]
            b = norm_legs[j]
            if not a.get('event_id') or a.get('event_id') == b.get('event_id'):
                continue

            parlay_outcome = None
            oa = str(a.get('outcome') or '').upper()
            ob = str(b.get('outcome') or '').upper()
            if oa in ('PENDING', '') or ob in ('PENDING', ''):
                parlay_outcome = 'PENDING'
            elif oa == 'LOST' or ob == 'LOST':
                parlay_outcome = 'LOST'
            elif oa == 'WON' and ob == 'WON':
                parlay_outcome = 'WON'
            elif oa == 'PUSH' and ob == 'PUSH':
                parlay_outcome = 'PUSH'
            elif oa == 'VOID' or ob == 'VOID':
                parlay_outcome = 'VOID'
            elif (oa == 'WON' and ob == 'PUSH') or (oa == 'PUSH' and ob == 'WON'):
                parlay_outcome = 'WON (partial)' 
            else:
                parlay_outcome = 'PENDING'

            p = float(a['win_prob']) * float(b['win_prob'])
            dec = dec_from_american(a['price']) * dec_from_american(b['price'])
            amer = american_from_dec(dec)
            # EV approximation using independent p
            ev = p * (dec - 1.0) - (1.0 - p)
            combos.append({
                "legs": [a, b],
                "p_win": p,
                "decimal_odds": dec,
                "american_odds": amer,
                "ev": ev,
                "outcome": parlay_outcome,
            })

    # Filter combos by TOTAL parlay odds band (user spec)
    def in_parlay_band(c):
        try:
            a = int(c.get('american_odds') or 0)
        except Exception:
            return False
        return a >= int(parlay_odds_lo) and a <= int(parlay_odds_hi)

    combos_in_band = [c for c in combos if in_parlay_band(c)]

    # Helper to enforce absolute leg independence
    def get_independent_combos(combo_list, limit, avoid_eids=None):
        used = set(avoid_eids) if avoid_eids else set()
        accepted = []
        for c in combo_list:
            e1 = c['legs'][0].get('event_id')
            e2 = c['legs'][1].get('event_id')
            if e1 not in used and e2 not in used:
                accepted.append(c)
                used.add(e1)
                used.add(e2)
            if len(accepted) >= limit:
                break
        return accepted, used

    # 1. High confidence shortlist (within band)
    sorted_by_win = sorted(combos_in_band, key=lambda x: (x['p_win'], x['ev']), reverse=True)
    high_conf, used_eids = get_independent_combos(sorted_by_win, 5)

    # 2. Payout band shortlist (Value Matchups)
    # Priority 1: Target Plus Money (+100 or better) that share NO legs with top High Confidence parlays
    plus_money = [c for c in combos_in_band if (c.get('american_odds') or 0) >= 100]
    sorted_plus_money = sorted(plus_money, key=lambda x: (x['ev'], x['p_win']), reverse=True)
    payout_band, payout_eids = get_independent_combos(sorted_plus_money, 5, avoid_eids=used_eids)
    
    # Priority 2: Fill in with chalk parlays that are independent from BOTH high_conf and the plus_money ones we just added
    if len(payout_band) < 5:
        sorted_chalk = sorted([c for c in combos_in_band if c not in plus_money], key=lambda x: (x['ev'], x['p_win']), reverse=True)
        combined_avoid = used_eids.union(payout_eids)
        extra_chalk, _ = get_independent_combos(sorted_chalk, 5 - len(payout_band), avoid_eids=combined_avoid)
        payout_band.extend(extra_chalk)

    # Priority 3 (Fallback): If absolutely no independent parlays exist, just grab the best remaining independent combos overall
    if not payout_band:
        payout_band, _ = get_independent_combos(sorted_by_win, 5, avoid_eids=used_eids)
        if not payout_band:
            payout_band = [c for c in sorted_by_win if c not in high_conf][:5]

    # Optional: persist the single recommended parlay so performance/grading can track it.
    # (UI can call with persist=1; duplicates are avoided via unique key.)
    try:
        if persist and (high_conf or payout_band):
            from src.database import get_admin_db_connection
            import hashlib

            # prefer the highest confidence combo; fallback to best EV in band
            chosen = (high_conf[0] if high_conf else payout_band[0])
            eids = sorted([str(chosen['legs'][0].get('event_id') or ''), str(chosen['legs'][1].get('event_id') or '')])
            pair_key = "|".join(eids)
            # Unique ID for this parlay on this ET date
            ukey = hashlib.sha256(("NCAAM|ML2|" + pair_key).encode()).hexdigest()

            # Create table if missing
            ddl = """
              CREATE TABLE IF NOT EXISTS recommended_parlays (
                id TEXT PRIMARY KEY,
                league TEXT NOT NULL,
                date_et TEXT NOT NULL,
                kind TEXT NOT NULL, -- e.g. 'ML2'
                bucket TEXT,        -- e.g. 'high_confidence' | 'payout_band'
                american_odds INTEGER,
                p_win REAL,
                ev REAL,
                event_id_1 TEXT,
                event_id_2 TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(league, date_et, kind, event_id_1, event_id_2)
              );
            """
            with get_admin_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(ddl)
                conn.commit()

            # Determine ET date
            date_et = None
            try:
                with get_db_connection() as conn:
                    date_et = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]
            except Exception:
                date_et = None
            if not date_et:
                date_et = datetime.utcnow().date().isoformat()

            bucket = 'high_confidence' if high_conf else 'payout_band'
            # Incorporate ET date into id so the same event-pair can be recommended again on another day.
            pid = hashlib.sha256((str(date_et) + "|" + ukey).encode()).hexdigest()

            with get_db_connection() as conn:
                _exec(conn, """
                  INSERT INTO recommended_parlays (id, league, date_et, kind, bucket, american_odds, p_win, ev, event_id_1, event_id_2)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                  ON CONFLICT (league, date_et, kind, event_id_1, event_id_2) DO UPDATE SET
                    american_odds=EXCLUDED.american_odds,
                    p_win=EXCLUDED.p_win,
                    ev=EXCLUDED.ev,
                    bucket=EXCLUDED.bucket
                """, (
                    pid, 'NCAAM', str(date_et), 'ML2', bucket,
                    int(chosen.get('american_odds') or 0),
                    float(chosen.get('p_win') or 0.0),
                    float(chosen.get('ev') or 0.0),
                    eids[0], eids[1],
                ))
                conn.commit()
    except Exception as e:
        try:
            print(f"[parlays] persist failed: {e}")
        except Exception:
            pass

    return {
        "status": "success",
        "strategy": _strategy,
        "legs_considered": len(norm_legs),
        "combos_considered": len(combos),
        "params": {
            "min_ev_per_unit": float(min_ev_per_unit),
            "odds_lo": int(parlay_odds_lo),
            "odds_hi": int(parlay_odds_hi),
        },
        "high_confidence": high_conf,
        "payout_band": payout_band,
    }


@app.get("/api/ncaam/parlays/performance-report")
async def ncaam_parlay_performance_report(days: int = 30):
    """Performance for *recommended* 2-leg ML parlays.

    Uses recommended_parlays table (populated by /api/ncaam/parlays/today?persist=1).
    """
    from src.database import get_db_connection, _exec

    def payout_per_unit(price: int) -> float:
        if price is None:
            return 0.0
        p = int(price)
        # payout when risking 1u
        return (p / 100.0) if p > 0 else (100.0 / abs(p))

    def parlay_outcome(o1: str, o2: str):
        a = (o1 or '').upper()
        b = (o2 or '').upper()
        decided = {'WON','LOST','PUSH'}
        if a not in decided or b not in decided:
            return 'PENDING'
        if a == 'LOST' or b == 'LOST':
            return 'LOST'
        # ML legs generally don't push; keep PUSH logic for completeness
        if a == 'PUSH' and b == 'PUSH':
            return 'PUSH'
        if a == 'PUSH' or b == 'PUSH':
            return 'PUSH'
        return 'WON'

    try:
        days = int(days)
    except Exception:
        days = 30
    days = max(3, min(days, 180))

    with get_db_connection() as conn:
        rows = _exec(conn, """
          SELECT
            p.id,
            p.date_et,
            p.american_odds,
            p.p_win,
            p.ev,
            p.bucket,
            p.event_id_1,
            p.event_id_2,
            e1.away_team AS away1,
            e1.home_team AS home1,
            e2.away_team AS away2,
            e2.home_team AS home2,
            m1.outcome AS o1,
            m2.outcome AS o2
          FROM recommended_parlays p
          JOIN events e1 ON e1.id=p.event_id_1
          JOIN events e2 ON e2.id=p.event_id_2
          LEFT JOIN LATERAL (
            SELECT outcome
            FROM model_predictions
            WHERE event_id=p.event_id_1 AND UPPER(COALESCE(market_type,'')) IN ('MONEYLINE','ML')
            ORDER BY analyzed_at DESC
            LIMIT 1
          ) m1 ON TRUE
          LEFT JOIN LATERAL (
            SELECT outcome
            FROM model_predictions
            WHERE event_id=p.event_id_2 AND UPPER(COALESCE(market_type,'')) IN ('MONEYLINE','ML')
            ORDER BY analyzed_at DESC
            LIMIT 1
          ) m2 ON TRUE
          WHERE p.league='NCAAM' AND p.kind='ML2'
            AND p.created_at > NOW() - (%(d)s || ' days')::interval
          ORDER BY p.created_at DESC
          LIMIT 1000
        """, {"d": int(days)}).fetchall()

    items = []
    for r in rows or []:
        d = dict(r)
        out = parlay_outcome(d.get('o1'), d.get('o2'))
        price = d.get('american_odds')
        roi = None
        if out == 'WON':
            roi = payout_per_unit(price)
        elif out == 'LOST':
            roi = -1.0
        elif out == 'PUSH':
            roi = 0.0

        items.append({
            "date_et": d.get('date_et'),
            "bucket": d.get('bucket'),
            "legs": [
                f"{d.get('away1')} @ {d.get('home1')}",
                f"{d.get('away2')} @ {d.get('home2')}",
            ],
            "american_odds": d.get('american_odds'),
            "p_win": float(d.get('p_win') or 0.0),
            "ev": float(d.get('ev') or 0.0),
            "outcome": out,
            "roi_per_unit": roi,
        })

    decided = [x for x in items if x['outcome'] in ('WON','LOST','PUSH')]
    won = sum(1 for x in decided if x['outcome'] == 'WON')
    lost = sum(1 for x in decided if x['outcome'] == 'LOST')
    push = sum(1 for x in decided if x['outcome'] == 'PUSH')
    pending = sum(1 for x in items if x['outcome'] == 'PENDING')

    roi_vals = [x['roi_per_unit'] for x in decided if x['roi_per_unit'] is not None]
    roi_pct = (sum(roi_vals) / len(roi_vals) * 100.0) if roi_vals else 0.0

    return {
        "generated_at": datetime.utcnow().isoformat() + 'Z',
        "league": "NCAAM",
        "kind": "ML2",
        "days": int(days),
        "record": {"won": won, "lost": lost, "push": push},
        "pending": pending,
        "roi_pct": round(roi_pct, 2),
        "items": items[:50],
    }


@app.get("/api/ncaam/model-performance/series")
async def get_ncaam_model_performance_series(days: int = 30, min_ev_per_unit: float = 0.02):
    """Daily model performance series for *recommended bets only*.

    Returns cumulative units curve based on realized outcomes.
    """
    from src.database import get_db_connection, _exec

    # Helpers imported from src.utils.model_performance

    days = max(3, min(int(days or 30), 180))

    with get_db_connection() as conn:
        rows = _exec(conn, """
          SELECT
            rs.date_et as day_et,
            m.outcome,
            COALESCE(m.bet_price, -110) as price,
            COALESCE(m.confidence_0_100, 0) as c0
          FROM recommended_slates rs
          JOIN recommended_slate_items rsi ON rs.id = rsi.slate_id
          LEFT JOIN model_predictions m ON m.id = rsi.prediction_id
          WHERE rs.league='NCAAM'
            AND rs.date_et > (NOW() AT TIME ZONE 'America/New_York' - (%(d)s || ' days')::interval)::date::text
            AND rsi.rank <= 6
            AND (m.outcome IN ('WON','LOST','PUSH'))
          ORDER BY rs.date_et ASC, rsi.rank ASC
        """, {"d": int(days)}).fetchall()

    def bucket(c0: int) -> str:
        try:
            n = int(c0 or 0)
        except Exception:
            n = 0
        if n >= 80:
            return 'high'
        if n >= 50:
            return 'medium'
        return 'low'

    by_day = {}
    for r in rows:
        day = r['day_et']
        b = bucket(r.get('c0'))
        by_day.setdefault(day, {"day": day, "units": 0.0, "n": 0, "units_high": 0.0, "n_high": 0, "units_medium": 0.0, "n_medium": 0, "units_low": 0.0, "n_low": 0})
        u = roi_per_unit(r['outcome'], r['price'])
        by_day[day]["units"] += u
        by_day[day]["n"] += 1
        if b == 'high':
            by_day[day]["units_high"] += u
            by_day[day]["n_high"] += 1
        elif b == 'medium':
            by_day[day]["units_medium"] += u
            by_day[day]["n_medium"] += 1
        else:
            by_day[day]["units_low"] += u
            by_day[day]["n_low"] += 1

    # build ordered series and cumulative (overall + buckets)
    series = []
    cum = cum_h = cum_m = cum_l = 0.0
    for day in sorted(by_day.keys()):
        d = by_day[day]
        cum += float(d["units"])
        cum_h += float(d["units_high"])
        cum_m += float(d["units_medium"])
        cum_l += float(d["units_low"])
        series.append({
            "day": day,
            "units": round(float(d["units"]), 3),
            "n": int(d["n"]),
            "cum_units": round(cum, 3),
            "cum_units_high": round(cum_h, 3),
            "cum_units_medium": round(cum_m, 3),
            "cum_units_low": round(cum_l, 3),
            "n_high": int(d["n_high"]),
            "n_medium": int(d["n_medium"]),
            "n_low": int(d["n_low"]),
        })

    return {
        "generated_at": datetime.utcnow().isoformat() + 'Z',
        "league": 'NCAAM',
        "days": int(days),
        "min_ev_per_unit": float(min_ev_per_unit),
        "series": series,
    }


@app.api_route("/api/jobs/ingest_events/{league}", methods=["GET", "POST"])
async def trigger_event_ingestion(league: str, date: Optional[str] = None, authorized: bool = Depends(verify_cron_secret)):
    """
    Cron Job / Manual Trigger: Ingests scheduled events from ESPN.
    """
    try:
        from src.parsers.espn_client import EspnClient
        client = EspnClient()
        # fetch_scoreboard automatically ingests via EventIngestionService
        events = client.fetch_scoreboard(league, date=date)
        return {
            "status": "success",
            "message": f"Ingested {len(events)} events for {league}",
            "count": len(events)
        }
    except Exception as e:
        print(f"[JOB ERROR] Event ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.api_route("/api/jobs/ingest_results/{league}", methods=["GET", "POST"])
async def trigger_result_ingestion(league: str, date: Optional[str] = None, authorized: bool = Depends(verify_cron_secret)):
    """Cron/manual: ingest finals/scores for a league.

    Auth:
    - If CRON_SECRET is configured, require it.
    - If CRON_SECRET is missing, allow Basement-key auth (X-BASEMENT-KEY) to run this endpoint.

    This keeps prod usable even when CRON_SECRET env isn't present.
    """
    # NOTE: We intentionally avoid JobContext here because result ingestion can take
    # long (external API calls) and holding a DB connection open can lead to
    # "connection already closed" errors in serverless.
    try:
        ingest_date = date if date and date.lower() != 'today' else None
        print(f"[JOB] Triggering result ingestion for {league} (date: {date or 'today'})")

        from src.services.grading_service import GradingService
        service = GradingService()
        # Ingest latest scores/finals into game_results.
        # (Side-effecting; returns None)
        service._ingest_latest_scores(league)

        return {
            "status": "success",
            "message": f"Ingested results for {league}",
            "date": ingest_date or "today",
            "note": "NCAAM uses Action Network web/v2 scoreboard (division=D1) for full-slate finals coverage."
        }

    except Exception as e:
        print(f"[JOB ERROR] Result ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jobs/ingest_enrichment")
async def trigger_enrichment_ingestion(league: str, date: Optional[str] = None, authorized: bool = Depends(verify_cron_secret)):
    """
    Ingests Action Network enrichment (Splits, Enrichment JSON).
    """
    try:
        from src.services.action_enrichment_service import ActionEnrichmentService
        service = ActionEnrichmentService()
        stats = service.ingest_enrichment_for_league(league, date_str=date)
        return {"status": "success", "stats": stats}
    except Exception as e:
        print(f"[JOB ERROR] Enrichment failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/enrichment/status")
async def get_enrichment_status():
    """
    Returns latest enrichment stats.
    """
    from src.database import get_db_connection, _exec
    stats = {}
    with get_db_connection() as conn:
        try:
            r1 = _exec(conn, "SELECT MAX(as_of_ts) as last_split FROM action_splits").fetchone()
            stats['last_split'] = r1['last_split'] if r1 else None
            
            r2 = _exec(conn, "SELECT MAX(as_of_ts) as last_raw FROM action_game_enrichment").fetchone()
            stats['last_raw'] = r2['last_raw'] if r2 else None
            
            r3 = _exec(conn, "SELECT COUNT(*) as count FROM action_splits").fetchone()
            stats['split_rows'] = r3['count'] if r3 else 0
        except Exception:
             pass
    return stats

@app.get("/api/enrichment/event/{event_id}")
async def get_event_enrichment(event_id: str):
    from src.database import get_db_connection, _exec
    with get_db_connection() as conn:
        splits = _exec(conn, "SELECT * FROM action_splits WHERE event_id = :eid ORDER BY as_of_ts DESC", {"eid": event_id}).fetchall()
        return {
            "event_id": event_id,
            "splits": [dict(r) for r in splits]
        }

@app.api_route("/api/jobs/reconcile", methods=["GET", "POST"])
async def trigger_settlement_reconcile(request: Request, league: Optional[str] = None, authorized: bool = Depends(verify_cron_secret)):
    """
    Cron Job / Manual Trigger: Settles pending bets using ingested results.
    """
    try:
        from src.services.settlement_service import SettlementEngine
        engine = SettlementEngine()
        stats = engine.run_settlement_cycle(league=league)
        return {
            "status": "success",
            "message": "Settlement reconciliation completed",
            "stats": stats
        }
    except Exception as e:
        print(f"[JOB ERROR] Settlement reconciliation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jobs/dedupe_model_predictions")
async def trigger_dedupe_model_predictions(request: Request, authorized: bool = Depends(verify_cron_secret)):
    """One-time maintenance: delete duplicate model_predictions and backfill prediction_key."""
    try:
        from src.scripts.dedupe_model_predictions import main as dedupe
        res = dedupe()
        return {"status": "success", **(res or {})}
    except Exception as e:
        print(f"[JOB ERROR] dedupe_model_predictions failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.api_route("/api/jobs/grade_predictions", methods=["GET", "POST"])
async def trigger_prediction_grading(
    request: Request, 
    fast: bool = True, 
    backfill_days: int = 10, 
    max_clv_rows: int = 250, 
    max_grade_rows: int = 500, 
    skip_clv: bool = False, 
    authorized: bool = Depends(verify_cron_secret)
):
    """Cron/manual: grade model_predictions using local game_results."""
    try:
        from src.services.grading_service import GradingService
        import time
        start_t = time.time()
        svc = GradingService()
        if fast:
            res = svc.grade_predictions(backfill_days=backfill_days, max_clv_rows=max_clv_rows, max_grade_rows=max_grade_rows, skip_clv=skip_clv)
        else:
            # Unbounded legacy behavior
            res = svc.grade_predictions(backfill_days=10, max_clv_rows=2000, max_grade_rows=5000, skip_clv=skip_clv)
        
        print(f"[JOB DONE] grade_predictions finished in {time.time() - start_t:.1f}s. Updates: {res}")
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "Prediction grading completed successfully.",
                "results": res,
                "params": {
                    "fast": fast,
                    "backfill_days": backfill_days
                }
            }
        )
    except Exception as e:
        print(f"[JOB ERROR] Grading failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Grading failed: {e}"}
        )


@app.api_route("/api/jobs/build_daily_top_picks", methods=["GET", "POST"])
async def trigger_build_daily_top_picks(
    request: Request,
    date: Optional[str] = None,
    limit_games: int = 250,
    offset: int = 0,
    max_events: int = 15,
    authorized: bool = Depends(verify_cron_secret),
):
    """Cron/manual: compute and upsert daily_top_picks for NCAAM.

    This powers /api/ncaam/top-picks fast-path (cached) and keeps the UI from
    needing to run expensive on-demand analysis.

    Serverless note:
    This endpoint must be **chunkable**. Vercel functions can time out; instead
    of processing the full slate, callers should run multiple small batches.

    Query params:
      - date: YYYY-MM-DD (ET)
      - limit_games: max slate size (<=500)
      - offset: starting index into the slate
      - max_events: max games to process this invocation

    Returns:
      { status, date, events_total, offset, processed, ok, err, next_offset, done }
    """

    # Resolve date_et in DB time so it matches backend.
    try:
        from src.database import get_db_connection, _exec
        if not date:
            with get_db_connection() as conn:
                date = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]
    except Exception:
        pass

    try:
        from src.scripts.build_daily_top_picks import ensure_table, fetch_event_ids_for_date, upsert_pick
        from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2

        ensure_table()

        # sanitize params
        try:
            limit_games = int(limit_games)
        except Exception:
            limit_games = 250
        limit_games = max(1, min(limit_games, 500))

        try:
            offset = int(offset)
        except Exception:
            offset = 0
        offset = max(0, offset)

        try:
            max_events = int(max_events)
        except Exception:
            max_events = 15
        max_events = max(1, min(max_events, 50))

        eids_all = fetch_event_ids_for_date(date, limit_games=limit_games)
        eids = eids_all[offset: offset + max_events]

        model = NCAAMMarketFirstModelV2()
        ok = 0
        err = 0

        # Batch DB writes to reduce Neon egress.
        from src.database import get_db_connection
        with get_db_connection() as conn:
            for eid in eids:
                try:
                    res = model.analyze(eid, relax_gates=False, persist=True)
                    upsert_pick(date, eid, res if isinstance(res, dict) else {}, conn=conn)
                    ok += 1
                except Exception as e:
                    err += 1
                    try:
                        upsert_pick(date, eid, {"recommendations": [], "error": str(e), "model_version": getattr(model, 'VERSION', None), "block_reason": str(e)}, conn=conn)
                    except Exception:
                        pass
            conn.commit()

        processed = ok + err
        next_offset = offset + processed
        done = next_offset >= len(eids_all)

        status = "success" if done else "partial"
        return {
            "status": status,
            "date": date,
            "events_total": len(eids_all),
            "offset": offset,
            "max_events": max_events,
            "processed": processed,
            "ok": ok,
            "err": err,
            "next_offset": next_offset,
            "done": done,
        }

    except Exception as e:
        print(f"[JOB ERROR] build_daily_top_picks failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.api_route("/api/jobs/run_council_today", methods=["GET", "POST"])
async def trigger_run_council_today(
    request: Request,
    date: Optional[str] = None,
    mode: str = "agents",
    authorized: bool = Depends(verify_cron_secret),
):
    """Cron/manual: Runs the Agent Council on today's actionable top picks."""
    if not settings.GEMINI_API_KEY:
        error_msg = "GEMINI_API_KEY missing. Please add to Vercel Dashboard and REDEPLOY."
        print(f"[JOB ERROR] {error_msg}")
        raise HTTPException(status_code=401, detail=error_msg)

    try:
        if mode == "agents":
            from src.agents.orchestrator import DecisionOrchestrator
            from src.agents.event_ops_agent import EventOpsAgent
            from src.agents.market_data_agent import MarketDataAgent
            from src.agents.pricing_agent_ncaam import PricingAgentNCAAM
            from src.agents.edge_ev_agent import EdgeEVAgent
            from src.agents.risk_manager_agent import RiskManagerAgent
            from src.agents.bet_builder_agent import BetBuilderAgent
            from src.agents.journal_agent import JournalAgent
            from src.agents.research_agent import ResearchAgent
            from src.agents.memory_agent import MemoryAgent
            from src.agents.oracle_agent import OracleAgent

            try:
                orchestrator = DecisionOrchestrator(league="NCAAM", model_version="agent_v1")
                orchestrator.run_pipeline(
                    event_ops_agent=EventOpsAgent(),
                    market_data_agent=MarketDataAgent(),
                    pricing_agent=PricingAgentNCAAM(),
                    edge_ev_agent=EdgeEVAgent(),
                    risk_manager_agent=RiskManagerAgent(),
                    bet_builder_agent=BetBuilderAgent(),
                    research_agent=ResearchAgent(),
                    memory_agent=MemoryAgent(),
                    oracle_agent=OracleAgent(),
                    journal_agent=JournalAgent(),
                    parameters={"mode": "manual_trigger", "date": date}
                )
                print(f"[JOB SUCCESS] DecisionOrchestrator completed for date={date or 'today'}")
                return {
                    "status": "success",
                    "message": "Full Agent Orchestrator job completed."
                }
            except Exception as e:
                print(f"[JOB ERROR] DecisionOrchestrator failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        else:
            from src.scripts.run_council_today import main as run_council
            
            try:
                run_council()
                print(f"[JOB SUCCESS] Agent Council completed for date={date or 'today'}")
                return {
                    "status": "success",
                    "message": "Agent Council job completed."
                }
            except Exception as e:
                print(f"[JOB ERROR] run_council_today failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        print(f"[JOB ERROR] run_council_today failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


    """Cron/manual: grade model_predictions using local game_results.

    Default mode is **fast/bounded** to avoid Vercel function timeouts.

    Params:
    - fast: if true, uses bounded defaults
    - backfill_days: results/CLV lookback window
    - max_clv_rows: max CLV updates per run
    - max_grade_rows: max outcome grades per run
    - skip_clv: skip CLV step (outcome-only)
    """
    try:
        from src.services.grading_service import GradingService
        svc = GradingService()
        if fast:
            res = svc.grade_predictions(backfill_days=backfill_days, max_clv_rows=max_clv_rows, max_grade_rows=max_grade_rows, skip_clv=skip_clv)
        else:
            # Unbounded legacy behavior (use carefully)
            res = svc.grade_predictions(backfill_days=10, max_clv_rows=2000, max_grade_rows=5000, skip_clv=skip_clv)
        return {
            "status": "success",
            "message": "Prediction grading completed",
            "results": res
        }
    except Exception as e:
        print(f"[JOB ERROR] Prediction grading failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reports/model-health")
async def get_model_health_report(request: Request):
    """
    Returns the markdown report for the Model Health Dashboard.
    """
    try:
        # Re-use the logic from scripts/generate_model_health_report.py
        # Ideally refactor that script to a service function, but for now we shell out or copy logic.
        # Let's import the logic if possible or just create a simple generated string here.
        # actually, let's use the script's logic if refactored, OR just implement valid generation here.
        
        from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
        from src.services.edge_scanner import EdgeScanner
        import datetime
        
        report = []
        report.append("# NCAAM Model Health Dashboard")
        report.append(f"**Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
        
        # 1. Market Performance (Mock for now, needs DB query)
        report.append("\n## 1. Market Performance (Rolling)")
        report.append("| Market | 7d CLV | 30d CLV | 7d ROI | 30d ROI | N (30d) | Status |")
        report.append("|---|---|---|---|---|---|---|")
        report.append("| Spread | +1.2% | +0.8% | +3.5% | +1.2% | 142 | ENABLED |")
        report.append("| Total  | -0.1% | +0.2% | -1.5% | +0.1% | 138 | ENABLED |")
        
        # 2. Config
        report.append("\n## 2. Configuration & Calibration")
        report.append("| Model | w_M | w_T | Sigma (Spread) | Sigma (Total) |")
        report.append("|---|---|---|---|---|")
        report.append("| v1_2024 | 0.60 | 0.20 | 2.6 | 3.8 |")
        
        # 3. Live Opps
        report.append("\n## 3. Top Opportunities (Live)")
        scanner = EdgeScanner()
        edges = scanner.find_edges(days_ahead=3, max_plays=3)
        if not edges:
             report.append("_No edges found currently._")
        else:
            edges = sorted(edges, key=lambda x: abs(x['edge']), reverse=True)[:10]
            report.append("| Matchup | Market | Bet | Line | Model | Edge | EV | Book |")
            report.append("|---|---|---|---|---|---|---|---|")
            for e in edges:
                 report.append(f"| {e['matchup']} | {e['market']} | {e['bet_on']} | {e['line']} | {e['model_line']} | {e['edge']} | {e['ev']} | {e['book']} |")
                 
        return {"report_markdown": "\n".join(report)}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Sync Endpoints ---

@app.post("/api/sync/request")
async def sync_request(payload: dict):
    """Queue a sync job for the local Mac worker.

    Auth: Basement password (X-BASEMENT-KEY). We intentionally do NOT require Supabase auth
    because this app primarily uses the Basement key gate.

    Payload:
      - FanDuel:   {"provider": "fanduel"}
      - DraftKings:{"provider": "draftkings", "account_id": "Main"|"User2"}

    DraftKings uses the new DK_INGEST pipeline (job_type=DK_INGEST + payload_json).
    """
    from datetime import datetime, timezone
    import json as _json

    from src.sync_jobs import create_sync_job, DEFAULT_USER_ID
    from src.database import get_db_connection, _exec, init_dk_ingest_db

    provider = (payload or {}).get("provider")
    provider = (provider or '').strip().lower()

    if provider == 'draftkings':
        account_id = str((payload or {}).get('account_id') or 'Main')
        if account_id not in ('Main', 'User2'):
            raise HTTPException(status_code=400, detail='account_id must be Main or User2')

        # Ensure schema exists (idempotent)
        try:
            init_dk_ingest_db()
        except Exception as e:
            print(f"[sync/request] init_dk_ingest_db warn: {e}")

        user_id = DEFAULT_USER_ID
        payload_json = _json.dumps({"book": "DraftKings", "user_id": str(user_id), "account_id": account_id})

        with get_db_connection() as conn:
            cur = _exec(
                conn,
                """
                INSERT INTO sync_jobs (user_id, provider, status, requested_at, job_type, payload_json)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                RETURNING id, user_id, provider, status, requested_at, job_type, payload_json;
                """,
                (str(user_id), 'draftkings', 'QUEUED', datetime.now(timezone.utc), 'DK_INGEST', payload_json),
            )
            row = cur.fetchone()
            conn.commit()
            return {"status": "queued", "job": dict(row)}

    # Default: legacy queue job (FanDuel)
    job = create_sync_job(provider=provider, user_id=DEFAULT_USER_ID)
    return {"status": "queued", "job": job}


@app.get("/api/sync/status")
async def sync_status():
    from src.sync_jobs import get_latest_jobs, DEFAULT_USER_ID
    return {"jobs": get_latest_jobs(user_id=DEFAULT_USER_ID, limit=10)}

@app.post("/api/sync/draftkings")
def sync_draftkings(payload: dict):
    """Deprecated legacy endpoint.

    DraftKings syncing now uses the DK_INGEST job queue (see /api/sync/request and
    /api/jobs/queue_sync/draftkings). This endpoint is kept only to avoid breaking
    older clients, and returns a 410.
    """
    raise HTTPException(status_code=410, detail="DraftKings sync moved to queued DK_INGEST pipeline. Use POST /api/sync/request {provider:'draftkings', account_id:'Main'|'User2'}. ")

@app.post("/api/sync/fanduel")
def sync_fanduel(payload: dict):
    # from src.scrapers.user_fanduel import FanDuelScraper # SELENIUM (Blocked)
    from src.scrapers.user_fanduel_pw import FanDuelScraperPW # PLAYWRIGHT
    from src.parsers.fanduel import FanDuelParser
    
    try:
        scraper = FanDuelScraperPW()
        raw_text = scraper.scrape()
        
        parser = FanDuelParser()
        parsed_bets = parser.parse(raw_text)
        
        return {
            "source": "FanDuel", 
            "status": "success", 
            "count": len(parsed_bets),
            "bets": parsed_bets
        }
    except Exception as e:
        print(f"Sync failed: {e}")
        return {"status": "error", "message": str(e)}


# --- Debug endpoints (results/graded coverage) ---

@app.get("/api/debug/ncaam/results-coverage")
async def debug_ncaam_results_coverage(date: Optional[str] = None, days: int = 1, authorized: bool = Depends(verify_cron_secret)):
    """Debug: show how many events have finals in game_results and how many predictions are still pending.

    Date is ET date (YYYY-MM-DD). Uses the same ET window logic as /api/board.
    """
    from src.database import get_db_connection, _exec

    if not date:
        with get_db_connection() as conn:
            date = _exec(conn, "SELECT (NOW() AT TIME ZONE 'America/New_York')::date::text").fetchone()[0]

    try:
        days = int(days)
    except Exception:
        days = 1
    days = max(1, min(days, 7))

    start_date = datetime.strptime(date, "%Y-%m-%d").date()
    end_date = (start_date + timedelta(days=days - 1))

    with get_db_connection() as conn:
        ev = _exec(conn, """
          SELECT e.id, e.start_time,
                 gr.final as final,
                 gr.home_score, gr.away_score,
                 COUNT(m.id) FILTER (WHERE (m.outcome IS NULL OR m.outcome='PENDING') AND COALESCE(m.ev_per_unit,0) >= 0.02) as pending_recs,
                 COUNT(m.id) FILTER (WHERE (m.outcome IN ('WON','LOST','PUSH')) AND COALESCE(m.ev_per_unit,0) >= 0.02) as decided_recs
          FROM events e
          LEFT JOIN game_results gr ON gr.event_id=e.id
          LEFT JOIN model_predictions m ON m.event_id=e.id
          WHERE e.league='NCAAM'
            AND DATE(e.start_time AT TIME ZONE 'America/New_York') BETWEEN %(start)s AND %(end)s
          GROUP BY e.id, e.start_time, gr.final, gr.home_score, gr.away_score
        """, {"start": str(start_date), "end": str(end_date)}).fetchall()

    rows = [dict(r) for r in ev]
    total_events = len(rows)
    finals = sum(1 for r in rows if r.get('final') is True)
    missing_results = sum(1 for r in rows if r.get('final') is None)
    not_final = sum(1 for r in rows if r.get('final') is False)
    pending_recs = sum(int(r.get('pending_recs') or 0) for r in rows)
    decided_recs = sum(int(r.get('decided_recs') or 0) for r in rows)

    sample_missing = [r for r in rows if r.get('final') is None]
    sample_missing = sorted(sample_missing, key=lambda x: x.get('start_time') or '')[:10]

    return {
        "date": date,
        "days": days,
        "events": {
            "total": total_events,
            "final_true": finals,
            "final_false": not_final,
            "missing_game_results": missing_results,
        },
        "recommended_bets": {
            "pending": pending_recs,
            "decided": decided_recs,
        },
        "sample_missing_game_results": [{"event_id": r.get('id'), "start_time": r.get('start_time')} for r in sample_missing],
    }


@app.get("/api/debug/event-result/{event_id}")
async def debug_event_result(event_id: str, authorized: bool = Depends(verify_cron_secret)):
    from src.database import get_db_connection, _exec
    with get_db_connection() as conn:
        e = _exec(conn, "SELECT id, league, start_time, home_team, away_team FROM events WHERE id=%s", (event_id,)).fetchone()
        gr = _exec(conn, "SELECT event_id, home_score, away_score, final, period, updated_at FROM game_results WHERE event_id=%s", (event_id,)).fetchone()
        return {
            "event": dict(e) if e else None,
            "game_results": dict(gr) if gr else None,
        }


@app.get("/api/ncaam/correlations/summary")
def get_correlation_summary(season: str = "2025-2026"):
    """
    Returns the full correlation matrix (cached).
    """
    import json
    cache_file = "data/correlation_cache_2025_2026.json"
    
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            return json.load(f)
            
    # If no cache, compute live (slow fallback)
    from src.services.correlation.ncaam_correlation_engine import NCAAMCorrelationEngine
    engine = NCAAMCorrelationEngine()
    df = engine.fetch_season_data()
    df = engine.build_archetype_bins(df)
    metrics = engine.compute_metrics(df)
    return {
        "metadata": {"type": "live_compute", "season": season, "games_count": len(df)},
        "archetypes": metrics
    }

@app.get("/api/ncaam/correlations/game")
def get_game_correlation(event_id: str):
    """
    Returns correlation data for a specific game based on its archetype.
    """
    from src.services.correlation.ncaam_correlation_engine import NCAAMCorrelationEngine
    from src.database import get_db_connection, _exec
    import pandas as pd
    
    # 1. Fetch Game Data to determine archetype
    query = """
    SELECT 
        e.id, 
        e.start_time,
        (
            SELECT line_value FROM odds_snapshots os 
            WHERE os.event_id = e.id AND os.market_type = 'SPREAD' AND os.captured_at <= NOW()
            ORDER BY os.captured_at DESC LIMIT 1
        ) as close_spread,
        mh.adj_tempo as home_pace,
        (mh.adj_off - mh.adj_def) as home_net_eff,
        ma.adj_tempo as away_pace,
        (ma.adj_off - ma.adj_def) as away_net_eff
    FROM events e
    -- Use LATEST team metrics as proxy for season identity (since historical daily metrics might be missing)
    LEFT JOIN (
        SELECT team_text, adj_tempo, adj_off, adj_def
        FROM bt_team_metrics_daily
        WHERE date = (SELECT MAX(date) FROM bt_team_metrics_daily)
    ) mh ON LOWER(e.home_team) LIKE '%%' || LOWER(mh.team_text) || '%%'
    LEFT JOIN (
        SELECT team_text, adj_tempo, adj_off, adj_def
        FROM bt_team_metrics_daily
        WHERE date = (SELECT MAX(date) FROM bt_team_metrics_daily)
    ) ma ON LOWER(e.away_team) LIKE '%%' || LOWER(ma.team_text) || '%%'
    WHERE e.id = :eid
    """
    with get_db_connection() as conn:
        row = _exec(conn, query, {"eid": event_id}).fetchone()
        
    if not row:
        raise HTTPException(status_code=404, detail="Game not found")
        
    # Validations
    if row['close_spread'] is None:
         return {"archetype": None, "correlations": None, "status": "no_spread"}

    # Convert to DataFrame row for binning
    try:
        if hasattr(row, '_index'):
            d = {k: row[k] for k in row._index}
        else:
            d = dict(row) # Fallback
            
        df = pd.DataFrame([d])
    except Exception as e:
        print(f"DEBUG DF Creation Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        raise e
    except Exception as e:
        print(f"DEBUG DF Creation Error: {e}")
        traceback.print_exc()
        raise e
    
    # Compute bins
    engine = NCAAMCorrelationEngine()
    df = engine.build_archetype_bins(df)
    
    if df.empty or 'pace_bin' not in df.columns:
        return {"archetype": None, "correlations": None}
        
    # Identify Archetype
    row_processed = df.iloc[0]
    archetype_key = f"{row_processed['pace_bin']}_{row_processed['eff_bin']}_{row_processed['spread_bucket']}"
    
    # Fetch Correlation Data from Cache or Engine
    # For speed, load summary (or implement granular lookup)
    # Using Summary Endpoint Logic reuse
    import json
    cache_file = "data/correlation_cache_2025_2026.json"
    correlations = None
    
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            full_data = json.load(f)
            correlations = full_data.get("archetypes", {}).get(archetype_key)
            
    return {
        "archetype": {
            "key": archetype_key,
            "pace": row_processed['pace_bin'],
            "eff": row_processed['eff_bin'],
            "spread": row_processed['spread_bucket']
        },
        "correlations": correlations
    }

# -----------------------------------------------------------------------------
# MULTI-AGENT DECISION SYSTEM ENDPOINTS (v1)
# -----------------------------------------------------------------------------
from src.agents.settings import AGENTS_ENABLED

@app.get("/api/v1/recommendations_v2")
def get_recommendations_v2(request: Request, mode: str = "default", days_ahead: int = 3):
    """
    Orchestrates the multi-agent pipeline to deliver BetRecommendations.
    Must be enabled via AGENTS_ENABLED=true or query param mode=agents.
    """
    if not AGENTS_ENABLED and mode != "agents":
        raise HTTPException(status_code=403, detail="Agent Orchestrator is disabled.")

    from src.agents.orchestrator import DecisionOrchestrator
    from src.agents.event_ops_agent import EventOpsAgent
    from src.agents.market_data_agent import MarketDataAgent
    from src.agents.pricing_agent_ncaam import PricingAgentNCAAM
    from src.agents.edge_ev_agent import EdgeEVAgent
    from src.agents.risk_manager_agent import RiskManagerAgent
    from src.agents.bet_builder_agent import BetBuilderAgent
    from src.agents.journal_agent import JournalAgent
    from src.agents.research_agent import ResearchAgent
    from src.agents.memory_agent import MemoryAgent
    from src.agents.oracle_agent import OracleAgent

    orchestrator = DecisionOrchestrator(league="NCAAM", model_version="agent_v1")
    
    run_payload = orchestrator.run_pipeline(
        event_ops_agent=EventOpsAgent(),
        market_data_agent=MarketDataAgent(),
        pricing_agent=PricingAgentNCAAM(),
        edge_ev_agent=EdgeEVAgent(),
        risk_manager_agent=RiskManagerAgent(),
        bet_builder_agent=BetBuilderAgent(),
        research_agent=ResearchAgent(),
        memory_agent=MemoryAgent(),
        oracle_agent=OracleAgent(),
        journal_agent=JournalAgent(),
        parameters={"days_ahead": days_ahead}
    )
    
    # Payload is automatically structured per Pydantic contracts
    return run_payload.model_dump()

@app.get("/api/v1/pending_decisions")
def get_pending_decisions():
    """Returns decisions staged for review by the orchestrator."""
    from src.database import get_db_connection, _exec
    with get_db_connection() as conn:
        rows = _exec(conn, "SELECT id, run_id, created_at, status, reason, payload_json FROM pending_decisions WHERE status = 'PENDING' ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

@app.post("/api/v1/pending_decisions/{decision_id}/approve")
def approve_pending_decision(decision_id: int):
    """Approves a staged model run for ledger recording."""
    from src.database import get_db_connection, _exec
    with get_db_connection() as conn:
        # We don't actively fire off the bet to a book yet (future phase)
        # We just transition status.
        _exec(conn, "UPDATE pending_decisions SET status = 'APPROVED' WHERE id = %s", (decision_id,))
        conn.commit()
    return {"status": "success", "message": f"Decision {decision_id} approved."}

@app.post("/api/v1/pending_decisions/{decision_id}/reject")
def reject_pending_decision(decision_id: int):
    """Rejects a staged model run."""
    from src.database import get_db_connection, _exec
    with get_db_connection() as conn:
        _exec(conn, "UPDATE pending_decisions SET status = 'REJECTED' WHERE id = %s", (decision_id,))
        conn.commit()
    return {"status": "success", "message": f"Decision {decision_id} rejected."}

@app.get("/api/v1/performance_reports")
def get_performance_reports(date: Optional[str] = None):
    """Nightly auditor results viewing endpoint."""
    from src.database import get_db_connection, _exec
    with get_db_connection() as conn:
        if date:
            rows = _exec(conn, "SELECT id, run_date, league, summary_json, created_at FROM performance_reports WHERE run_date = %s ORDER BY created_at DESC", (date,)).fetchall()
        else:
            rows = _exec(conn, "SELECT id, run_date, league, summary_json, created_at FROM performance_reports ORDER BY created_at DESC LIMIT 30").fetchall()
            
        reports = []
        import json
        for r in rows:
            mapped = dict(r)
            mapped['summary'] = json.loads(r['summary_json'])
            reports.append(mapped)
        return reports

@app.get("/api/v1/council")
def get_council_debate(event_id: Optional[str] = None):
    """Fetches the latest Agent Council debate and Oracle prediction for a specific game."""
    if not event_id:
        return {"status": "error", "message": "event_id query parameter is required."}
    from src.database import get_db_connection, _exec
    import json
    with get_db_connection() as conn:
        # Search the latest decision run that includes narrative for this event.
        # Since council_narrative is a JSON object keyed by event_id, we can check if that key exists.
        query = """
        SELECT run_id, council_narrative->%s AS narrative
        FROM decision_runs
        WHERE jsonb_exists(council_narrative, %s)
        ORDER BY created_at DESC LIMIT 1
        """
        row = _exec(conn, query, (event_id, event_id)).fetchone()

        run_id = None
        narrative = None
        if row is not None:
            try:
                run_id = row.get('run_id')
                narrative = row.get('narrative')
            except Exception:
                try:
                    run_id = row[0]
                    narrative = row[1]
                except Exception:
                    pass

        if narrative:
            try:
                if isinstance(narrative, str):
                    narrative = json.loads(narrative)
                
                # Fetch traces for this run
                traces = []
                if run_id:
                    trace_query = "SELECT agent_name, task_description, details, timestamp FROM agent_traces WHERE run_id = %s ORDER BY timestamp ASC"
                    trace_rows = _exec(conn, trace_query, (run_id,)).fetchall()
                    for t in trace_rows:
                        item = dict(t)
                        if item.get('details') and isinstance(item['details'], str):
                            item['details'] = json.loads(item['details'])
                        item['timestamp'] = item['timestamp'].isoformat() if hasattr(item['timestamp'], 'isoformat') else str(item['timestamp'])
                        traces.append(item)
                
                return {
                    "status": "success", 
                    "data": {
                        "narrative": narrative,
                        "traces": traces
                    }
                }
            except Exception as e:
                return {"status": "error", "message": f"Failed to parse council data: {e}"}
                
        return {"status": "error", "message": "No council debate found for this event."}

@app.get("/api/v1/council/memories")
def get_agent_memories(limit: int = 10):
    """Fetches recent lessons learned by the agents for display in the UI."""
    from src.database import get_db_connection, _exec
    with get_db_connection() as conn:
        rows = _exec(conn, "SELECT id, team_a, team_b, context, lesson, timestamp FROM agent_memories ORDER BY timestamp DESC LIMIT %s", (limit,)).fetchall()
        return {"status": "success", "data": [dict(r) for r in rows]}


def _dk_queue_auth(request: Request) -> bool:
    """
    Validate CRON_SECRET for the DK queue endpoint.
    - Production: REQUIRES Authorization: Bearer <CRON_SECRET> header.
    - Non-production: also accepts ?token=<CRON_SECRET> query param for local testing.
    Returns True if authorized, False otherwise.
    """
    cron_secret = os.environ.get("CRON_SECRET", "")
    if not cron_secret:
        # No secret configured → allow (dev convenience; warn loudly)
        print("[DK-Queue] WARN: CRON_SECRET not set — endpoint is unprotected!")
        return True

    # Primary: Authorization: Bearer <secret>
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        if token == cron_secret:
            return True

    # Fallback (non-production only): ?token=<secret>
    app_env = os.environ.get("APP_ENV", "local").lower()
    if app_env not in ("prod", "production"):
        token_param = request.query_params.get("token", "")
        if token_param == cron_secret:
            return True

    return False


@app.api_route("/api/jobs/queue_sync/draftkings", methods=["GET", "POST"])
async def queue_dk_sync_job(request: Request, authorized: bool = Depends(verify_cron_secret)):
    """
    Enqueue a DraftKings DK_INGEST job into sync_jobs.

    Vercel Cron calls this with GET at 07:00 UTC.
    Manual trigger: POST with optional JSON body or GET with ?token= param.

    Security:
    - Production: requires Authorization: Bearer <CRON_SECRET> header → 401 on failure.
    - Non-production: also accepts ?token=<CRON_SECRET> for local curl testing.

    No scraping is performed here — only a fast DB insert to enqueue the job.
    The persistent local worker (scripts/sync_worker.py) does the heavy work.
    """
    from src.database import get_db_connection, _exec, init_dk_ingest_db
    from src.sync_jobs import DEFAULT_USER_ID
    import json as _json
    from datetime import datetime, timezone

    # --- Auth gate ---
    if not _dk_queue_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized: valid CRON_SECRET required")

    # Ensure schema exists (idempotent)
    try:
        init_dk_ingest_db()
    except Exception as e:
        print(f"[DK-Queue] init_dk_ingest_db warn: {e}")

    # Parse optional body (POST) — GET has no body
    body: dict = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}

    user_id = str(body.get("user_id") or DEFAULT_USER_ID)
    account_id = str(body.get("account_id") or "Main")
    payload = _json.dumps({"book": "DraftKings", "user_id": user_id, "account_id": account_id})

    with get_db_connection() as conn:
        cur = _exec(
            conn,
            """
            INSERT INTO sync_jobs (user_id, provider, status, requested_at, job_type, payload_json)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (user_id, "draftkings", "QUEUED", datetime.now(timezone.utc),
             "DK_INGEST", payload),
        )
        row = cur.fetchone()
        conn.commit()
        job_id = int(row["id"])

    print(f"[DK-Queue] Queued DK_INGEST job_id={job_id} user={user_id} method={request.method}")
    return {"status": "queued", "job_id": job_id}


@app.get("/api/ingest/status")
def dk_ingest_status():
    """
    Returns the latest DraftKings book_ingest_runs row and recent DK_INGEST jobs.
    Distinct from the existing /api/sync/status endpoint.
    """
    from src.database import get_db_connection, _exec

    result: dict = {"last_ingest": None, "recent_jobs": []}

    try:
        with get_db_connection() as conn:
            cur = _exec(
                conn,
                """
                SELECT id, book, account_id, run_started_at, run_finished_at,
                       status, count_parsed, inserted, updated, message
                FROM book_ingest_runs
                WHERE book = 'DraftKings'
                ORDER BY run_started_at DESC
                LIMIT 1
                """,
            )
            row = cur.fetchone()
            if row:
                r = dict(row)
                for k in ("run_started_at", "run_finished_at"):
                    if r.get(k) and hasattr(r[k], "isoformat"):
                        r[k] = r[k].isoformat()
                result["last_ingest"] = r

            cur2 = _exec(
                conn,
                """
                SELECT id, status, job_type, requested_at, started_at, finished_at, error
                FROM sync_jobs
                WHERE job_type = 'DK_INGEST'
                ORDER BY requested_at DESC
                LIMIT 5
                """,
            )
            jobs = []
            for r in cur2.fetchall():
                j = dict(r)
                for k in ("requested_at", "started_at", "finished_at"):
                    if j.get(k) and hasattr(j[k], "isoformat"):
                        j[k] = j[k].isoformat()
                jobs.append(j)
            result["recent_jobs"] = jobs

    except Exception as e:
        result["error"] = str(e)

    return result

@app.get("/api/v1/diagnostics/env")
async def diagnostics_env(authorized: bool = Depends(verify_cron_secret)):
    """Safe diagnostic endpoint to see which environment variables are visible."""
    return {
        "APP_ENV": os.environ.get("APP_ENV"),
        "visible_keys": sorted(list(os.environ.keys())),
        "crucial_checks": {
            "HAS_GEMINI_KEY": "GEMINI_API_KEY" in os.environ,
            "HAS_POSTGRES_URL": "POSTGRES_URL" in os.environ,
            "HAS_DATABASE_URL": "DATABASE_URL" in os.environ,
        }
    }
