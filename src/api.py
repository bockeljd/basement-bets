from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import fetch_all_bets
from analytics import AnalyticsEngine

app = FastAPI()

# Allow CORS for local React dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, set to specific origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Betting Analytics API is running"}

@app.get("/api/stats")
def get_stats():
    engine = AnalyticsEngine()
    return engine.get_summary()

@app.get("/api/breakdown/{field}")
def get_breakdown(field: str):
    engine = AnalyticsEngine()
    # Field options: 'sport', 'bet_type', 'status', 'provider'
    return engine.get_breakdown(field)

@app.get("/api/bets")
def get_bets():
    return fetch_all_bets()
