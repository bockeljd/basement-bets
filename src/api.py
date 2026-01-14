from fastapi import FastAPI, HTTPException, Request, Security
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
import os

from src.models.odds_client import OddsAPIClient
from src.database import fetch_all_bets, insert_model_prediction, fetch_model_history, init_db
from typing import Optional

app = FastAPI()

# --- Security Configuration ---
API_KEY_NAME = "X-BASEMENT-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

@app.middleware("http")
async def check_access_key(request: Request, call_next):
    # Allow public access to root, favicon, or OPTIONS (CORS preflight)
    if request.method == "OPTIONS":
         return await call_next(request)
         
    if request.url.path.startswith("/api"):
        # Get Key from Header
        client_key = request.headers.get(API_KEY_NAME)
        server_key = os.environ.get("BASEMENT_PASSWORD")
        
        # If Password is set on Server, enforce it
        # Note: If server_key is NOT set (e.g. dev), we might skip check or enforce empty?
        # User prompt implies: "If Password is set on Server, enforce it".
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
_analytics_cache = None
_last_analytics_refresh = None
ANALYTICS_TTL = timedelta(seconds=60) # Cache for 60 seconds

def get_analytics_engine():
    global _analytics_cache, _last_analytics_refresh
    now = datetime.now()
    
    # Refresh if None or expired
    if _analytics_cache is None or (_last_analytics_refresh and now - _last_analytics_refresh > ANALYTICS_TTL):
        from src.analytics import AnalyticsEngine
        print("[API] Refreshing Analytics Engine...")
        _analytics_cache = AnalyticsEngine()
        _last_analytics_refresh = now
    
    return _analytics_cache

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
async def get_stats():
    engine = get_analytics_engine()
    return engine.get_summary()

@app.get("/api/breakdown/{field}")
async def get_breakdown(field: str):
    engine = get_analytics_engine()
    if field == "player":
        return engine.get_player_performance()
    if field == "monthly":
        return engine.get_monthly_performance()
    return engine.get_breakdown(field)

@app.get("/api/bets")
async def get_bets(): 
    engine = get_analytics_engine()
    return engine.get_all_activity()

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
async def get_balances():
    engine = get_analytics_engine()
    return engine.get_balances()

@app.get("/api/stats/period")
async def get_period_stats(days: Optional[int] = None, year: Optional[int] = None):
    engine = get_analytics_engine()
    return engine.get_period_stats(days=days, year=year)

@app.get("/api/financials")
async def get_financials():
    engine = get_analytics_engine()
    return engine.get_financial_summary()



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
async def get_research_edges():
    """
    Runs all predictive models (NFL, NCAAM, EPL) and returns actionable edges.
    """
    edges = []
    
    # Lazy Import to avoid circular deps or startup lag
    from src.models.nfl_model import NFLModel
    from src.models.ncaam_model import NCAAMModel
    from src.models.epl_model import EPLModel
    from src.services.auditor import ResearchAuditor
    
    auditor = ResearchAuditor()
    
    # Helper to sanitize numpy types
    def sanitize(val):
        if hasattr(val, 'item'): 
            return val.item()
        return val

    # 1. NFL (Spread)
    try:
        nfl = NFLModel()
        nfl_edges = nfl.find_edges()
        for e in nfl_edges:
            e['sport'] = 'NFL'
            e['market'] = 'Spread'
            e['logic'] = 'Monte Carlo (Gaussian)'
            # Sanitize
            e['is_actionable'] = bool(sanitize(e.get('is_actionable', False)))
            e['edge'] = sanitize(e.get('edge'))
            edges.append(e)
    except Exception as e:
        print(f"[API] NFL Model Failed: {e}")

    # 2. NCAAM (Totals)
    try:
        ncaam = NCAAMModel()
        ncaam_edges = ncaam.find_edges()
        for e in ncaam_edges:
            e['sport'] = 'NCAAM'
            e['market'] = 'Total'
            e['logic'] = 'KenPom Efficiency + Tempo'
             # Sanitize
            e['is_actionable'] = bool(sanitize(e.get('is_actionable', False)))
            e['edge'] = sanitize(e.get('edge'))
            edges.append(e)
    except Exception as e:
        print(f"[API] NCAAM Model Failed: {e}")
        
    # 3. EPL (Winning)
    try:
        epl = EPLModel()
        epl_edges = epl.find_edges()
        for e in epl_edges:
            e['sport'] = 'EPL'
            e['market'] = 'Moneyline'
            e['logic'] = 'Poisson Distribution (xG)'
            # Normalize keys for frontend
            e['market_line'] = sanitize(e.get('market_odds'))
            e['fair_line'] = sanitize(e.get('fair_odds'))
            e['edge'] = sanitize(e.get('edge'))
            e['is_actionable'] = bool(sanitize(e.get('is_actionable', False)))
            edges.append(e)
    except Exception as e:
        print(f"[API] EPL Model Failed: {e}")
        
    
    # Auto-Track Actionable Edges
    for edge in edges:
        if edge.get('is_actionable'):
            # Must ensure game_id is present. Models should return it.
            # NFL/NCAAM/EPL models generally don't put 'game_id' in local edges dict?
            # They put 'game_id' in prediction, but maybe not in final edge dict.
            # Let's double check model outputs or add it if missing.
            # For now, we try to insert. Dictionary keys must match SQL params.
            # Helper to map fields:
            
            try:
                # Safe convert edge string (e.g. "10.5% EV" or None)
                edge_val_str = str(edge.get('edge', '0')).replace('% EV', '').replace('%', '')
                try:
                    edge_val = float(edge_val_str)
                except:
                    edge_val = 0.0

                # --- Audit ---
                audit_result = auditor.audit(edge)
                edge['audit_class'] = audit_result['audit_class']
                edge['audit_reason'] = audit_result['audit_reason']

                doc = {
                    "game_id": edge.get('game_id') or edge.get('game'), # Fallback
                    "sport": edge.get('sport'),
                    "start_time": edge.get('start_time'), # Maps to :start_time / date
                    "game": edge.get('game'),             # Maps to :game / matchup
                    "bet_on": str(edge.get('bet_on')),
                    "market": edge.get('market'),
                    "market_line": edge.get('market_line') or edge.get('market_spread') or 0,
                    "fair_line": edge.get('fair_line') or edge.get('fair_spread') or 0,
                    "edge": edge_val,
                    "is_actionable": True
                }
                
                insert_model_prediction(doc)
            except Exception as e:
                # Log full trace if needed, but simple error is fine
                print(f"[API] Failed to auto-track edge for {edge.get('game')}: {e}")

    return edges
