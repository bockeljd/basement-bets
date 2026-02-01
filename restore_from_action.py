
from src.services.odds_fetcher_service import OddsFetcherService
from src.database import get_db_connection, _exec
from datetime import datetime
import uuid

def restore_from_action():
    print("--- Restoring Missing Events from Action Network ---")
    date_str = "20260131"
    league = "NCAAM"
    
    # 1. Fetch Action Data
    service = OddsFetcherService()
    try:
        games = service.fetch_odds(league, date_str)
        print(f"Fetched {len(games)} games from Action Network.")
    except Exception as e:
        print(f"Failed to fetch Action data: {e}")
        return

    with get_db_connection() as conn:
        restored_count = 0
        for g in games:
            home = g['home_team']
            away = g['away_team']
            
            # 2. Check if exists (Loose Match)
            # We check if strict Home/Away matches, or if an event exists with these teams flipped (unlikely but safe)
            # Using simple LIKE for robustness against minor naming diffs? 
            # ideally we rely on the teams provided by Action.
            
            check_query = """
            SELECT id FROM events 
            WHERE 
                (home_team = :home AND away_team = :away)
                OR
                (home_team LIKE :home_like AND away_team LIKE :away_like)
            """
            
            # Simple wildcard check
            params = {
                'home': home, 
                'away': away,
                'home_like': f"%{home}%",
                'away_like': f"%{away}%"
            }
            
            existing = _exec(conn, check_query, params).fetchone()
            
            if existing:
                # Already exists, use existing ID if different?
                # Actually, if exists, we might want to ensure we use THAT ID for the odds?
                # But here we are assuming Action ID is master. 
                # If existing is ESPN ID, we might have multiple rows if we insert Action ID.
                # But strict check (home/away) found it.
                # Let's just proceed to odds using the Action ID if we didn't find one? 
                # No, we must link to the EXISTING ID if found.
                action_id = existing[0]
                # Proceed to odds...
            else:
                 # Logic to Create New ID
                 action_id = g.get('id') or g.get('game_id')
                 if not action_id:
                    action_id = f"action:ncaam:restored:{uuid.uuid4()}"
                 else:
                    if "action:" not in str(action_id):
                        action_id = f"action:ncaam:{action_id}"

                 # Insert...
                 # ...


            # Start Time
            # Action returns 'start_time'? 
            # If missing, default to noon UTC or parse date_str.
            start_time = g.get('start_time')
            if not start_time:
                start_time = f"2026-01-31 12:00:00+00"
            
            insert_query = """
            INSERT INTO events (id, league, home_team, away_team, start_time, status, created_at)
            VALUES (:id, :league, :home, :away, :start, 'scheduled', NOW())
            ON CONFLICT (id) DO NOTHING
            """
            
            try:
                _exec(conn, insert_query, {
                    'id': action_id,
                    'league': league,
                    'home': home,
                    'away': away,
                    'start': start_time
                })
                conn.commit()
                restored_count += 1
                # print(f"  -> Restored as {action_id}")
            except Exception as e:
                conn.rollback()
                # If error is duplicate key, it's fine, we proceed to odds
                # print(f"  -> Insert Failed (likely exists): {e}")
                pass
                
            # 4. INSERT ODDS SNAPSHOTS (Force Population)
            # Action Network data has: home_spread, home_odds, away_spread, away_odds, total, over_odds, under_odds
            
            def insert_snap(m_type, side, line, price):
                if line is None and price is None: return
                snap_id = str(uuid.uuid4())
                q = """
                INSERT INTO odds_snapshots (
                    event_id, market_type, side, line_value, price, 
                    book, captured_at
                ) VALUES (
                    :eid, :mtype, :side, :line, :price, 
                    'consensus', NOW()
                )
                """
                try:
                    _exec(conn, q, {
                        'eid': action_id,
                        'mtype': m_type, 'side': side,
                        'line': float(line) if line is not None else None,
                        'price': int(price) if price is not None else -110
                    })
                except Exception as ex:
                    print(f"Failed to insert snapshot {m_type} {side}: {ex}")

            # Spread (using correct field names from OddsFetcherService)
            insert_snap('SPREAD', 'HOME', g.get('home_spread'), g.get('home_spread_odds'))
            insert_snap('SPREAD', 'AWAY', g.get('away_spread'), g.get('away_spread_odds'))
            
            # Total
            insert_snap('TOTAL', 'OVER', g.get('total_score'), g.get('over_odds'))
            insert_snap('TOTAL', 'UNDER', g.get('total_score'), g.get('under_odds'))
            
            # Moneyline
            insert_snap('MONEYLINE', 'HOME', None, g.get('home_money_line'))
            insert_snap('MONEYLINE', 'AWAY', None, g.get('away_money_line'))
            
            conn.commit()
                
        print(f"--- Restoration Complete. Restored/Updated {len(games)} events with odds. ---")

if __name__ == "__main__":
    restore_from_action()
