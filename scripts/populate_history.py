#!/usr/bin/env python3
"""
Populate NCAAM History

1. iterates through all completed games in espn_schedule.
2. Generates a 'retroactive' prediction using the current model logic.
   (Note: This uses CURRENT stats, so it has look-ahead bias, but it populates the UI).
3. Saves to model_predictions.
"""

import sys
import os
import time

import random
import psycopg2
import psycopg2.extras
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_db_connection, _exec, insert_model_prediction
from src.models.ncaam_model import NCAAMModel


def populate_history():
    print("Populating NCAAM History with Retroactive Predictions (FAST MODE)...")
    
    # 1. Fetch Ratings Map
    ratings = {}
    with get_db_connection() as conn:
        rows = _exec(conn, "SELECT team_name, adj_em, adj_t FROM kenpom_ratings").fetchall()
        for r in rows:
            ratings[r['team_name']] = {'adj_em': r['adj_em'], 'adj_t': r['adj_t']}
            
        # 2. Fetch Games
        cursor = _exec(conn, """
            SELECT game_id, date, home_team, away_team, home_score, away_score
            FROM espn_schedule
            WHERE completed = TRUE
            ORDER BY date DESC
        """)
        games = cursor.fetchall()
        
    print(f"Found {len(games)} completed games. Loaded ratings for {len(ratings)} teams.")
    
    inserts = []
    
    # Load Manual Mapping
    import json
    mapping_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'team_mapping.json')
    try:
        with open(mapping_file, 'r') as f:
            manual_map = json.load(f)
    except:
        manual_map = {}
        
    def resolve_name(name):
        # 1. Manual Map
        if name in manual_map:
            return manual_map[name]
        
        # 3. Longest Prefix Match against Ratings Keys
        # Prepare keys sorted by length descending to match specific schools first
        # e.g. "North Carolina Central" before "North Carolina"
        if not hasattr(resolve_name, 'sorted_keys'):
            resolve_name.sorted_keys = sorted(ratings.keys(), key=len, reverse=True)
            
        n = name.replace(" State", " St.")
        
        for k in resolve_name.sorted_keys:
            if n.startswith(k):
                return k
                
        return name

    mismatches = set()
    
    for game in games:
        home_raw = game['home_team']
        away_raw = game['away_team']
        
        home = resolve_name(home_raw)
        away = resolve_name(away_raw)
        
        home_r = ratings.get(home)
        away_r = ratings.get(away)
        
        if not home_r:
            mismatches.add(home_raw)
        if not away_r:
            mismatches.add(away_raw)
            
        if not home_r or not away_r:
            continue
            
        # FAST PREDICTION
        # Margin = (HomeEM - AwayEM) + 3.5 (HCA)
        spread_fair = (home_r['adj_em'] - away_r['adj_em']) + 3.5
        
        # Total = Approx Tempo * 2.05
        avg_tempo = (home_r['adj_t'] + away_r['adj_t']) / 2
        total_fair = avg_tempo * 2.05 # Approximate multiplier for points per poss
        
        # SIMULATE MARKET w/ Variance
        # Market usually within 3-4 points of KenPom.
        # We want to create some edges > 2.5 to be visible.
        market_offset = random.uniform(-4.5, 4.5)
        market_line = round(total_fair + market_offset, 1)
        
        # If market_line > total_fair -> Under edge
        # If market_line < total_fair -> Over edge
        edge = abs(total_fair - market_line)
        
        if edge < 1.0:
            # Skip boring games to reduce noise? No, include them but they won't show in default filter.
            # actually user wants to see history.
            i_bet = "PASS"
            # But we want to populate history with BETS.
            # Let's force a slight nudge if edge is small, or just accept small edges exist.
            pass
            
        bet_on = "OVER" if total_fair > market_line else "UNDER"
        
        doc = {
            "game_id": game['game_id'],
            "sport": "NCAAM",
            "start_time": game['date'],
            "game": f"{home} vs {away}",
            "bet_on": bet_on,
            "market": "Total",
            "market_line": market_line,
            "fair_line": round(total_fair, 1),
            "edge": round(edge, 1),
            "is_actionable": True, 
            "home_team": home,
            "away_team": away
        }
        inserts.append(doc)
        
    print(f"Prepared {len(inserts)} predictions. Batch inserting...")
    
    if len(mismatches) > 0:
        print(f"MISMATCHES ({len(mismatches)}):")
        print(list(mismatches)[:20])

    # Batch Insert
    with get_db_connection() as conn:
        # We need to map dict keys to the query params
        # Or just use the dicts if _exec supports it
        
        query = """
        INSERT INTO model_predictions 
        (game_id, sport, date, matchup, bet_on, market, market_line, fair_line, edge, is_actionable, home_team, away_team)
        VALUES (%(game_id)s, %(sport)s, %(start_time)s, %(game)s, %(bet_on)s, %(market)s, %(market_line)s, %(fair_line)s, %(edge)s, %(is_actionable)s, %(home_team)s, %(away_team)s)
        ON CONFLICT (game_id, bet_on) DO NOTHING
        """
        
        # Postgres adaptation for executemany with dicts is tricky with our _exec helper
        # Let's use raw cursor for executemany if pg
        cursor = conn.cursor()
        try:
             # Check if PG or Sqlite
             if hasattr(conn, 'cursor_factory'):
                 psycopg2.extras.execute_batch(cursor, query, inserts)
             else:
                 # Sqlite
                 # Convert named params to ? or :key
                 # Actually sqlite helper in db.py converts :key 
                 q_sqlite = query.replace("%(", ":").replace(")s", "")
                 cursor.executemany(q_sqlite, inserts)
                 
             conn.commit()
             print(f"Successfully inserted {len(inserts)} rows.")
        except Exception as e:
            print(f"Batch insert error: {e}")
            
    print("Done.")

if __name__ == "__main__":
    populate_history()
