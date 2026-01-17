#!/usr/bin/env python3
"""
Backtest Ensemble Model on Yesterday's Games

Compares ensemble predictions vs actual results from Jan 16, 2026
"""

import sys
import os
from datetime import datetime, timedelta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_db_connection, _exec

def backtest_yesterday():
    """Backtest ensemble model on yesterday's completed games"""
    
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    print(f"[BACKTEST] Testing ensemble model on games from {yesterday}")
    
    with get_db_connection() as conn:
        # Fetch yesterday's completed games with results
        query = """
        SELECT 
            id, game_id, sport, matchup, home_team, away_team,
            market, bet_on, market_line, fair_line, edge,
            home_score, away_score, result, created_at
        FROM model_predictions
        WHERE sport = 'NCAAM'
          AND DATE(created_at) = %s
          AND result IS NOT NULL
          AND result != 'Pending'
        ORDER BY created_at DESC
        """
        cursor = _exec(conn, query, (yesterday,))
        games = cursor.fetchall()
    
    if not games:
        print(f"[BACKTEST] No completed games found for {yesterday}")
        print("[BACKTEST] Trying last 7 days...")
        
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
            LIMIT 20
            """
            week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
            cursor = _exec(conn, query, (week_ago,))
            games = cursor.fetchall()
    
    if not games:
        print("[BACKTEST] No completed games found in last 7 days")
        return
    
    print(f"[BACKTEST] Found {len(games)} completed games\n")
    
    # Analyze results
    wins = sum(1 for g in games if g['result'] == 'Win')
    losses = sum(1 for g in games if g['result'] == 'Loss')
    pushes = sum(1 for g in games if g['result'] == 'Push')
    
    graded = wins + losses
    win_rate = (wins / graded * 100) if graded > 0 else 0.0
    
    # Calculate ROI (assuming -110 odds)
    profit = (wins * 9.09) - (losses * 10.0)
    roi = (profit / (len(games) * 10.0) * 100) if games else 0.0
    
    print("="*60)
    print("ENSEMBLE MODEL BACKTEST RESULTS")
    print("="*60)
    print(f"Total Bets:     {len(games)}")
    print(f"Record:         {wins}-{losses}-{pushes}")
    print(f"Win Rate:       {win_rate:.1f}%")
    print(f"ROI:            {roi:.1f}%")
    print(f"Profit ($10/bet): ${profit:.2f}")
    print("="*60)
    
    # Show sample games
    print("\nSample Games:")
    for i, game in enumerate(games[:5]):
        print(f"\n{i+1}. {game['matchup']} - {game['market']}")
        print(f"   Bet: {game['bet_on']} {game['market_line']}")
        print(f"   Edge: {game['edge']} pts")
        print(f"   Result: {game['result']}")
        if game['home_score'] and game['away_score']:
            print(f"   Score: {game['home_score']}-{game['away_score']}")
    
    # Performance by edge threshold
    print("\n" + "="*60)
    print("Performance by Edge Threshold:")
    print("="*60)
    for threshold in [0.5, 1.0, 2.0, 3.0]:
        filtered = [g for g in games if (g['edge'] or 0) >= threshold]
        if filtered:
            w = sum(1 for g in filtered if g['result'] == 'Win')
            l = sum(1 for g in filtered if g['result'] == 'Loss')
            wr = (w / (w + l) * 100) if (w + l) > 0 else 0.0
            p = (w * 9.09) - (l * 10.0)
            r = (p / (len(filtered) * 10.0) * 100) if filtered else 0.0
            print(f"  Edge >= {threshold} pts: {w}-{l} ({wr:.1f}% WR, {r:.1f}% ROI, n={len(filtered)})")

if __name__ == "__main__":
    backtest_yesterday()
