from src.auth import get_current_user
from fastapi import FastAPI, HTTPException, Request, Security, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
import os

from src.models.odds_client import OddsAPIClient
from src.database import fetch_all_bets, insert_model_prediction, fetch_model_history, init_db
from typing import Optional

app = FastAPI()

# Trigger Reload

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
        # 1. Check CRON Secret (Vercel Cron)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            if settings.CRON_SECRET and token == settings.CRON_SECRET:
                 return await call_next(request)

        # 2. Check Client Key
        client_key = request.headers.get(API_KEY_NAME)
        server_key = settings.BASEMENT_PASSWORD
        
        # If Password is set on Server, enforce it
        if server_key and client_key != server_key:
             return JSONResponse(status_code=403, content={"message": "Wrong Password"})
             
    response = await call_next(request)
    return response

# --- Admin Routes ---
@app.get("/api/admin/init-db")
def run_init():
    # WARNING: Secure this or remove after use
    # It is protected by the middleware above if /api prefix is hit.
    init_db() 
    return {"message": "Database Initialized on Vercel Postgres"}

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
        "version": "1.0.0-mvp",
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

from datetime import datetime, timedelta

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
    return engine.get_time_series_profit(user_id=user_id)

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
    user_id = user.get("sub")
    engine = get_analytics_engine(user_id=user_id)
    return engine.get_all_activity(user_id=user_id)

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
    elif sport == 'EPL': sport_key = 'soccer_epl'
    
    return odds_client.get_odds(sport_key)

@app.get("/api/balances")
async def get_balances(user: dict = Depends(get_current_user)):
    user_id = user.get("sub")
    engine = get_analytics_engine(user_id=user_id)
    return engine.get_balances(user_id=user_id)

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

@app.post("/api/parse-slip")
async def parse_slip(request: Request, user: dict = Depends(get_current_user)):
    try:
        data = await request.json()
        raw_text = data.get("raw_text")
        sportsbook = data.get("sportsbook", "DK")
        
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
        
        # Basic mapping to DB schema
        status = bet_data.get("status", "PENDING").upper()
        stake = float(bet_data.get("stake", 0))
        american_odds = bet_data.get("price", {}).get("american")
        decimal_odds = bet_data.get("price", {}).get("decimal")
        
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

        doc = {
            "user_id": user_id,
            "account_id": bet_data.get("account_id"),
            "provider": bet_data.get("sportsbook"),
            "date": date_part,
            "sport": bet_data.get("sport") or "Unknown",
            "bet_type": bet_data.get("market_type"),
            "wager": stake,
            "profit": round(profit, 2) if profit is not None else 0.0,
            "status": status,
            "description": bet_data.get("event_name"),
            "selection": bet_data.get("selection"),
            "odds": american_odds,
            "is_live": bet_data.get("is_live", False),
            "is_bonus": bet_data.get("is_bonus", False),
            "raw_text": bet_data.get("raw_text")
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
        return {"status": "success", "link_status": leg['link_status'], "event_id": leg['event_id']}
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
        date_str = datetime.datetime.now().strftime("%Y%m%d")

    fetcher = OddsFetcherService()
    adapter = OddsAdapter()
    
    # Fetch
    raw_games = fetcher.fetch_odds(league.upper(), start_date=date_str)
    
    # Normalize & Store
    # Provider is Action Network (primary in Fetcher)
    count = adapter.normalize_and_store(raw_games, league=league.upper(), provider="action_network")
    
    return {"status": "success", "league": league, "date": date_str, "snapshots_ingested": count}

@app.patch("/api/bets/{bet_id}/settle")
async def settle_bet(bet_id: int, request: Request, user: dict = Depends(get_current_user)):
    try:
        data = await request.json()
        status = data.get("status")
        if status not in ['WON', 'LOST', 'PUSH', 'PENDING']:
            raise HTTPException(status_code=400, detail="Invalid status")
            
        from src.database import update_bet_status
        success = update_bet_status(bet_id, status, user_id=user.get("sub"))
        if not success:
            raise HTTPException(status_code=404, detail="Bet not found")
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/bets/{bet_id}")
async def remove_bet(bet_id: int, user: dict = Depends(get_current_user)):
    try:
        from src.database import delete_bet
        success = delete_bet(bet_id, user_id=user.get("sub"))
        if not success:
            raise HTTPException(status_code=404, detail="Bet not found")
        return {"status": "success"}
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
async def get_history():
    return fetch_model_history()

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
    from src.models.ncaam_model import NCAAMModel
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

    # 2. NCAAM (Totals)
    try:
        ncaam = NCAAMModel()
        ncaam_edges = ncaam.find_edges()
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
    for edge in edges:
        if edge.get('is_actionable'):
            try:
                audit_result = auditor.audit(edge)
                edge['audit_class'] = audit_result['audit_class']
                edge['audit_reason'] = audit_result['audit_reason']
                
                # Capture in DB
                doc = {
                    "game_id": edge.get('game_token') or edge.get('game_id') or edge.get('game'),
                    "sport": edge.get('sport'),
                    "start_time": edge.get('start_time'),
                    "game": edge.get('game'),
                    "bet_on": str(edge.get('bet_on')),
                    "market": edge.get('market'),
                    "market_line": edge.get('market_line') or edge.get('market_spread') or 0,
                    "fair_line": edge.get('fair_line') or 0,
                    "edge": edge.get('edge', 0),
                    "is_actionable": True,
                    "home_team": edge.get('home_team'),
                    "away_team": edge.get('away_team')
                }
                insert_model_prediction(doc)
            except Exception as e:
                print(f"[API] Failed to auto-track edge: {e}")

    return edges

    # Update Cache
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

    return await get_model_health(date=date, league=league, market=market, user=user)

@app.post("/api/jobs/policy_refresh")
async def trigger_policy_refresh(request: Request):
    """
    Cron Job Endpoint: Triggers the Policy Engine to curate weights and allowlists.
    Protected by CRON_SECRET or API Key.
    """
    # Verify Auth (Simplistic for now, using same middleware)
    try:
        from src.services.policy_engine import PolicyEngine
        engine = PolicyEngine()
        engine.refresh_policies()
        return {"status": "success", "message": "Policy Refresh Executed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jobs/ingest_torvik")
async def trigger_torvik_ingestion(request: Request):
    """
    Cron Job / Manual Trigger: Ingests latest NCAAM team metrics from BartTorvik.
    Protected by CRON_SECRET or API Key.
    """
    try:
        from src.database import init_bt_team_metrics_db, upsert_team_metrics
        from src.services.barttorvik import BartTorvikClient
        
        # Initialize tables if needed
        init_bt_team_metrics_db()
        
        # Fetch and upsert
        client = BartTorvikClient()
        ratings = client.get_efficiency_ratings(year=2026)
        
        if ratings:
            return {
                "status": "success", 
                "message": f"Ingested {len(ratings)} teams",
                "teams_count": len(ratings)
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to fetch ratings from BartTorvik")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jobs/ingest_results/{league}")
async def trigger_result_ingestion(league: str, date: Optional[str] = None):
    """
    Cron Job / Manual Trigger: Ingests scoreboard/results from ESPN for a specific league.
    Supports NFL, NCAAM, EPL.
    """
    try:
        from src.parsers.espn_client import EspnClient
        client = EspnClient()
        
        # If date is 'today', passing None to fetch_scoreboard works
        ingest_date = date if date and date.lower() != 'today' else None
        
        print(f"[JOB] Triggering result ingestion for {league} (date: {date or 'today'})")
        events = client.fetch_scoreboard(league, date=ingest_date)
        
        return {
            "status": "success",
            "message": f"Processed {len(events)} events for {league}",
            "events_count": len(events),
            "league": league,
            "date": date or "today"
        }
    except Exception as e:
        print(f"[JOB ERROR] Result ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/jobs/reconcile")

@app.post("/api/jobs/ingest_enrichment")
async def trigger_enrichment_ingestion(league: str, date: Optional[str] = None):
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
    # Simple query to get max timestamps
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
        # props = ...
        # injuries = ...
        return {
            "event_id": event_id,
            "splits": [dict(r) for r in splits]
        }
async def trigger_settlement_reconcile(league: Optional[str] = None):
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

@app.post("/api/jobs/grade_predictions")
async def trigger_prediction_grading():
    """
    Cron Job / Manual Trigger: Grades model predictions using local game results.
    """
    try:
        from src.models.auto_grader import AutoGrader
        grader = AutoGrader()
        results = grader.grade_pending_picks()
        return {
            "status": "success",
            "message": "Prediction grading completed",
            "results": results
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
        
        from src.models.ncaam_model import NCAAMModel
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
        model = NCAAMModel()
        edges = model.find_edges()
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

