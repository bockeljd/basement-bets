#!/usr/bin/env python3
"""
Scrape ESPN NCAAM Schedule and Grade All Predictions

1. Scrapes all NCAAM games from ESPN (season to date)
2. Matches with model predictions
3. Grades predictions based on actual results
"""

import sys
import os
from datetime import datetime, timedelta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.services.espn_ncaa_client import ESPNNCAAClient
from src.database import get_db_connection, _exec

def scrape_season_schedule():
    """Scrape entire NCAAM season (Nov 1 - Mar 31)"""
    
    espn_client = ESPNNCAAClient()
    
    # NCAAM season: November 2025 - March 2026
    start_date = datetime(2025, 11, 1)
    end_date = datetime.now()  # Up to today
    
    print(f"[SCHEDULE] Scraping from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    
    all_games = []
    current = start_date
    
    while current <= end_date:
        date_str = current.strftime('%Y%m%d')
        
        try:
            scoreboard = espn_client.get_scoreboard(date=date_str)
            events = scoreboard.get('events', [])
            
            for event in events:
                game = parse_event(event)
                if game:
                    all_games.append(game)
            
            if events:
                print(f"[SCHEDULE] {current.strftime('%Y-%m-%d')}: {len(events)} games")
        except Exception as e:
            print(f"[SCHEDULE] Error on {current.strftime('%Y-%m-%d')}: {e}")
        
        current += timedelta(days=1)
    
    return all_games

def parse_event(event):
    """Parse ESPN event into game dict"""
    try:
        game_id = event.get('id')
        date = event.get('date')
        
        competition = event.get('competitions', [{}])[0]
        competitors = competition.get('competitors', [])
        
        if len(competitors) < 2:
            return None
        
        home = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0])
        away = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[1])
        
        home_team = home.get('team', {}).get('displayName', '')
        away_team = away.get('team', {}).get('displayName', '')
        home_score = home.get('score')
        away_score = away.get('score')
        
        status = competition.get('status', {})
        completed = status.get('type', {}).get('name') == 'STATUS_FINAL'
        
        return {
            'game_id': game_id,
            'date': date,
            'home_team': home_team,
            'away_team': away_team,
            'home_score': float(home_score) if home_score else None,
            'away_score': float(away_score) if away_score else None,
            'completed': completed
        }
    except:
        return None

def save_schedule(games):
    """Save games to database"""
    with get_db_connection() as conn:
        _exec(conn, """
            CREATE TABLE IF NOT EXISTS espn_schedule (
                game_id TEXT PRIMARY KEY,
                date TIMESTAMP,
                home_team TEXT,
                away_team TEXT,
                home_score REAL,
                away_score REAL,
                completed BOOLEAN
            )
        """)
        
        for game in games:
            _exec(conn, """
                INSERT INTO espn_schedule 
                (game_id, date, home_team, away_team, home_score, away_score, completed)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (game_id) DO UPDATE SET
                    home_score = EXCLUDED.home_score,
                    away_score = EXCLUDED.away_score,
                    completed = EXCLUDED.completed
            """, (game['game_id'], game['date'], game['home_team'], game['away_team'],
                  game['home_score'], game['away_score'], game['completed']))
        
        conn.commit()

def grade_predictions():
    """Grade all NCAAM predictions against ESPN results"""
    
    with get_db_connection() as conn:
        # Get all pending NCAAM predictions
        cursor = _exec(conn, """
            SELECT id, matchup, home_team, away_team, market, bet_on, market_line
            FROM model_predictions
            WHERE sport = 'NCAAM'
              AND (result IS NULL OR result = 'Pending')
        """)
        predictions = cursor.fetchall()
        
        print(f"\n[GRADING] Found {len(predictions)} predictions to grade")
        
        graded = 0
        for pred in predictions:
            # Find matching game in ESPN schedule
            cursor = _exec(conn, """
                SELECT home_score, away_score, completed
                FROM espn_schedule
                WHERE (home_team LIKE %s OR away_team LIKE %s)
                  AND (home_team LIKE %s OR away_team LIKE %s)
                  AND completed = TRUE
                LIMIT 1
            """, (f'%{pred["home_team"]}%', f'%{pred["home_team"]}%',
                  f'%{pred["away_team"]}%', f'%{pred["away_team"]}%'))
            
            game = cursor.fetchone()
            
            if not game:
                continue
            
            home_score = game['home_score']
            away_score = game['away_score']
            
            if not home_score or not away_score:
                continue
            
            # Grade the prediction
            result = grade_bet(pred, home_score, away_score)
            
            # Update prediction
            _exec(conn, """
                UPDATE model_predictions
                SET home_score = %s, away_score = %s, result = %s
                WHERE id = %s
            """, (home_score, away_score, result, pred['id']))
            
            graded += 1
        
        conn.commit()
        print(f"[GRADING] Graded {graded} predictions")

def grade_bet(pred, home_score, away_score):
    """Grade a single bet"""
    market = pred['market']
    bet_on = pred['bet_on']
    line = pred['market_line']
    
    if market == 'Spread':
        # Spread: home_score + line vs away_score
        cover = (home_score + line) - away_score
        if abs(cover) < 0.5:
            return 'Push'
        if bet_on == pred['home_team']:
            return 'Win' if cover > 0 else 'Loss'
        else:
            return 'Win' if cover < 0 else 'Loss'
    
    elif market == 'Total':
        total = home_score + away_score
        diff = abs(total - line)
        if diff < 0.5:
            return 'Push'
        if bet_on == 'OVER':
            return 'Win' if total > line else 'Loss'
        else:
            return 'Win' if total < line else 'Loss'
    
    return 'Pending'

if __name__ == "__main__":
    print("="*60)
    print("NCAAM SEASON GRADING SYSTEM")
    print("="*60)
    
    # Step 1: Scrape schedule
    print("\nStep 1: Scraping ESPN schedule...")
    games = scrape_season_schedule()
    completed = sum(1 for g in games if g['completed'])
    print(f"\nTotal games: {len(games)}")
    print(f"Completed: {completed}")
    
    # Step 2: Save to database
    print("\nStep 2: Saving to database...")
    save_schedule(games)
    
    # Step 3: Grade predictions
    print("\nStep 3: Grading predictions...")
    grade_predictions()
    
    print("\n" + "="*60)
    print("GRADING COMPLETE!")
    print("="*60)
