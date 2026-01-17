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
        # Get Key from Header
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
        doc = {
            "user_id": user_id,
            "account_id": bet_data.get("account_id"),
            "provider": bet_data.get("sportsbook"),
            "date": bet_data.get("placed_at", "").split("T")[0],
            "sport": bet_data.get("sport"),
            "bet_type": bet_data.get("market_type"),
            "wager": bet_data.get("stake"),
            "profit": (bet_data.get("stake") * (bet_data.get("price", {}).get("decimal", 0) - 1)) if bet_data.get("status") == "WON" else 0.0,
            "status": bet_data.get("status") or "PENDING",
            "description": bet_data.get("event_name"),
            "selection": bet_data.get("selection"),
            "odds": bet_data.get("price", {}).get("american"),
            "is_live": bet_data.get("is_live", False),
            "is_bonus": bet_data.get("is_bonus", False),
            "raw_text": bet_data.get("raw_text") # Should have been passed back
        }
        
        from src.database import insert_bet
        insert_bet(doc)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
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
async def get_research_edges(user: dict = Depends(get_current_user)):
    """
    Runs all predictive models (NFL, NCAAM, EPL) and returns actionable edges.
    """
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
