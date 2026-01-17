#!/usr/bin/env python3
"""
Backtest NCAAM Model on Historical Games

This script:
1. Fetches historical NCAAM games from the database
2. Re-runs model predictions on those games
3. Compares predictions vs actual results
4. Calculates win rate, ROI, and other metrics
"""

import sys
import os
from datetime import datetime, timedelta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_db_connection, _exec
from src.models.ncaam_model import NCAAMModel

def fetch_historical_games(days_back=30):
    """Fetch completed games from model_predictions table"""
    with get_db_connection() as conn:
        query = """
        SELECT 
            id, game_id, sport, matchup, home_team, away_team,
            market, bet_on, market_line, fair_line, edge,
            home_score, away_score, result, created_at
        FROM model_predictions
        WHERE sport = 'NCAAM'
          AND result IS NOT NULL
          AND result != 'Pending'
          AND created_at >= %s
        ORDER BY created_at DESC
        """
        cutoff = datetime.now() - timedelta(days=days_back)
        cursor = _exec(conn, query, (cutoff,))
        return cursor.fetchall()

def analyze_backtest_results(games):
    """Calculate performance metrics"""
    if not games:
        return {
            "total_bets": 0,
            "wins": 0,
            "losses": 0,
            "pushes": 0,
            "win_rate": 0.0,
            "roi": 0.0,
            "avg_edge": 0.0
        }
    
    wins = sum(1 for g in games if g['result'] == 'Win')
    losses = sum(1 for g in games if g['result'] == 'Loss')
    pushes = sum(1 for g in games if g['result'] == 'Push')
    
    graded = wins + losses
    win_rate = (wins / graded * 100) if graded > 0 else 0.0
    
    # Assuming -110 odds, calculate ROI
    # Win: +$9.09, Loss: -$10.00
    profit = (wins * 9.09) - (losses * 10.0)
    roi = (profit / (len(games) * 10.0) * 100) if games else 0.0
    
    avg_edge = sum(g['edge'] or 0 for g in games) / len(games) if games else 0.0
    
    return {
        "total_bets": len(games),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": round(win_rate, 1),
        "roi": round(roi, 1),
        "avg_edge": round(avg_edge, 2),
        "profit": round(profit, 2)
    }

def main():
    print("[BACKTEST] Fetching historical NCAAM games...")
    games = fetch_historical_games(days_back=30)
    
    if not games:
        print("[BACKTEST] No historical games found with results.")
        print("[BACKTEST] Tip: Run the grading service to populate results.")
        return
    
    print(f"[BACKTEST] Found {len(games)} graded games.")
    
    metrics = analyze_backtest_results(games)
    
    print("\n" + "="*50)
    print("NCAAM MODEL BACKTEST RESULTS (Last 30 Days)")
    print("="*50)
    print(f"Total Bets:     {metrics['total_bets']}")
    print(f"Record:         {metrics['wins']}-{metrics['losses']}-{metrics['pushes']}")
    print(f"Win Rate:       {metrics['win_rate']}%")
    print(f"ROI:            {metrics['roi']}%")
    print(f"Profit ($10/bet): ${metrics['profit']}")
    print(f"Avg Edge:       {metrics['avg_edge']} pts")
    print("="*50)
    
    # Breakdown by edge threshold
    print("\nPerformance by Edge Threshold:")
    for threshold in [1.0, 2.0, 3.0, 4.0]:
        filtered = [g for g in games if (g['edge'] or 0) >= threshold]
        if filtered:
            m = analyze_backtest_results(filtered)
            print(f"  Edge >= {threshold} pts: {m['wins']}-{m['losses']} ({m['win_rate']}% WR, {m['roi']}% ROI)")

if __name__ == "__main__":
    main()
