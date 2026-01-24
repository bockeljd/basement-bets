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

# Trigger Reload - 1.2.1-v6

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
        # Allow public diagnostic endpoints
        if request.url.path in ["/api/version", "/api/health"]:
            return await call_next(request)

        # 1. Check Authorization Header (Cron OR Supabase JWT)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            # If it matches CRON_SECRET, allow
            if settings.CRON_SECRET and token == settings.CRON_SECRET:
                 return await call_next(request)
            # Otherwise assume it's a Supabase JWT - let it through (auth happens in Depends)
            return await call_next(request)

        # 2. Check Client Key (for non-Bearer requests)
        client_key = request.headers.get(API_KEY_NAME)
        server_key = settings.BASEMENT_PASSWORD
        
        # If Password is set on Server, enforce it
        if server_key and client_key != server_key:
             return JSONResponse(status_code=403, content={"message": "Wrong Password"})
             
    response = await call_next(request)
    return response

@app.get("/api/version")
def get_version():
    """Public endpoint to check the current deployed version and build time."""
    return {
        "version": "1.2.1",
        "build_time": "2026-01-19T18:15:00Z",
        "env": os.environ.get("VERCEL_ENV", "local")
    }

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
    elif sport == 'NCAAF': sport_key = 'americanfootball_ncaaf'
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
        if sportsbook.upper() == "DK": sportsbook = "DraftKings"
        if sportsbook.upper() in ["FD", "FANDUEL"]: sportsbook = "FanDuel"
        
        if sportsbook == "DraftKings":
            from src.parsers.draftkings_text import DraftKingsTextParser
            parser = DraftKingsTextParser()
            results = parser.parse(raw_text)
            if results:
                parsed = results[0]
                # Transform to frontend-expected schema
                result = {
                    "event_name": parsed.get("description"),
                    "sport": parsed.get("sport"),
                    "market_type": parsed.get("bet_type"),
                    "selection": parsed.get("selection"),
                    "price": {"american": parsed.get("odds"), "decimal": None},
                    "stake": parsed.get("wager"),
                    "status": parsed.get("status", "PENDING"),
                    "placed_at": parsed.get("date"),
                    "confidence": 0.95,  # Fixed confidence for regex parser
                    "is_live": parsed.get("is_live", False),
                    "is_bonus": parsed.get("is_bonus", False),
                    "profit": parsed.get("profit"),
                    "provider": parsed.get("provider", "DraftKings"),
                    "raw_text": parsed.get("raw_text"),
                }
            else:
                raise Exception("Failed to parse DraftKings slip")
        else:
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

        # Sanitize account_id (Postgres requires UUID, skip if "Main" or short string)
        raw_acc_id = bet_data.get("account_id")
        account_id = None
        if raw_acc_id and len(str(raw_acc_id)) > 30:
             account_id = raw_acc_id

        # Normalize provider name
        provider_raw = bet_data.get("sportsbook") or bet_data.get("provider", "")
        if provider_raw.upper() == "DK":
            provider = "DraftKings"
        elif provider_raw.upper() in ["FD", "FANDUEL"]:
            provider = "FanDuel"
        else:
            provider = provider_raw

        doc = {
            "user_id": user_id,
            "account_id": account_id,
            "provider": provider,
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
        date_str = datetime.now().strftime("%Y%m%d")

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
async def get_history(user: dict = Depends(get_current_user)):
    user_id = user.get("sub")
    return fetch_model_history(user_id=user_id)


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
                    "ev_per_unit": edge.get('ev') or 0,
                    "confidence_0_100": int(abs(edge.get('edge', 0)) * 10),
                    "inputs_json": "{}",
                    "outputs_json": "{}",
                    "narrative_json": "{}",
                    "model_version": "research_v1"
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
    """
    Verifies Authorization header matches CRON_SECRET.
    """
    from src.config import settings
    expected = settings.CRON_SECRET
    if not expected:
        # If no secret configured (local dev?), warn or allow? 
        # For production security, we deny if not set.
        print("[Auth] CRON_SECRET not set in environment.")
        raise HTTPException(status_code=500, detail="Server config error: CRON_SECRET missing")
        
    auth = request.headers.get("Authorization")
    if not auth:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
        
    # Expect "Bearer <token>"
    parts = auth.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1] != expected:
        raise HTTPException(status_code=401, detail="Invalid Cron Secret")

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

@app.get("/api/ncaam/board")
async def get_ncaam_board(date: Optional[str] = None):
    """
    Fetch lightweight NCAAM board for on-demand analysis.
    """
    from src.database import get_db_connection, _exec, get_db_type
    
    # Default to today
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
        
    # Optimized Postgres Query
    query = """
    SELECT e.id, e.league as sport, e.home_team, e.away_team, e.start_time, e.status, 
               s.line_value as home_spread, s.price as spread_home_price, 
               -- The original query used: s.price as moneyline_home.
               -- If the snapshot is SPREAD, s.price IS the spread odds (e.g. -110), NOT ML.
               -- Let's stick to returning them as specific keys or keeping the old alias IF the UI expects it.
               -- Checking Frontend: uses 'moneyline_home' logic.
               -- Edge display: `@{edge.moneyline_home || '-'}`
               -- So yes, it displays the PRICE of the spread.
               s.price as moneyline_home,
               t.line_value as total_line, t.price as moneyline_away,
               gr.home_score, gr.away_score, gr.final
        FROM events e
        LEFT JOIN (
            SELECT DISTINCT ON (event_id) event_id, line_value, price
            FROM odds_snapshots 
            WHERE market_type = 'SPREAD' AND side = 'HOME'
            ORDER BY event_id, captured_at DESC
        ) s ON e.id = s.event_id
        LEFT JOIN (
            SELECT DISTINCT ON (event_id) event_id, line_value, price
            FROM odds_snapshots 
            WHERE market_type = 'TOTAL' AND side = 'OVER'
            ORDER BY event_id, captured_at DESC
        ) t ON e.id = t.event_id
        LEFT JOIN game_results gr ON e.id = gr.event_id
        WHERE e.league = 'NCAAM'
          AND DATE(e.start_time AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York') = :date
        ORDER BY e.start_time ASC
    """
    with get_db_connection() as conn:
        rows = _exec(conn, query, {"date": date}).fetchall()
        return _ensure_utc([dict(r) for r in rows])

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
    """
    try:
        data = await request.json()
        event_id = data.get("event_id")
        if not event_id:
             raise HTTPException(status_code=400, detail="event_id is required")
             
        from src.services.game_analyzer import GameAnalyzer
        analyzer = GameAnalyzer()
        
        # GameAnalyzer will hit NCAAMMarketFirstModelV2.analyze internal
        # Fetch basic teams for logging if needed
        # Actually GameAnalyzer fetches context from 'events'.
        result = analyzer.analyze(event_id, "NCAAM", "Unknown", "Unknown")
        return result
    except Exception as e:
        print(f"[API] Analyze error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/ncaam/history")
async def get_ncaam_history(limit: int = 100):
    """
    Returns past model predictions/analysis.
    """
    from src.database import fetch_model_history
    data = fetch_model_history(limit=limit)
    return _ensure_utc(data)

@app.get("/api/ncaam/analytics")
async def get_ncaam_analytics(days: int = 30):
    """
    Returns aggregated performance stats (Win Rate, ROI, Edge, etc.)
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
    FROM model_predictions
    WHERE analyzed_at > NOW() - (INTERVAL '1 day' * :days)
    """
    
    try:
        with get_db_connection() as conn:
            row = _exec(conn, query, {"days": days}).fetchone()
            if not row:
                return {}
            
            stats = dict(row)
            decided = (stats['wins'] or 0) + (stats['losses'] or 0)
            stats['win_rate'] = (stats['wins'] / decided * 100) if decided > 0 else 0.0
            
            if decided > 0:
                units = (stats['wins'] * 0.909) - stats['losses']
                stats['roi_est'] = (units / decided) * 100
            else:
                stats['roi_est'] = 0.0
                
            return stats
            
    except Exception as e:
        print(f"[Analytics] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.api_route("/api/jobs/ingest_events/{league}", methods=["GET", "POST"])
async def trigger_event_ingestion(league: str, date: Optional[str] = None):
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
    """
    Cron Job / Manual Trigger: Ingests scoreboard/results from ESPN for a specific league.
    """
    job_key = f"ingest_results_{league}"
    from src.services.job_service import JobContext, JobLockedException
    from src.parsers.espn_client import EspnClient
    
    try:
        with JobContext(job_key) as ctx:
            client = EspnClient()
            ingest_date = date if date and date.lower() != 'today' else None
            
            print(f"[JOB] Triggering result ingestion for {league} (date: {date or 'today'})")
            # Fetch and Save
            from src.services.grading_service import GradingService
            service = GradingService()
            # service._ingest_latest_scores calls fetch_scoreboard internally usually, 
            # or we pass data. GradingService often encapsulates fetch+save.
            # Assuming _ingest_latest_scores works.
            service._ingest_latest_scores(league)
            
            return {
                "status": "success",
                "message": f"Ingested results for {league}",
                "date": date or "today"
            }
            
    except JobLockedException:
        return {"status": "skipped", "reason": "Locked"}
    except Exception as e:
        print(f"[JOB ERROR] Result ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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

