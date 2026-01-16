import sys
import os
import json

# Ensure root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_db_connection, _exec
from src.services.event_resolver import EventResolver

def link_legs():
    resolver = EventResolver()
    
    print("--- Linking Bet Legs to Events ---")
    
    with get_db_connection() as conn:
        # Get unlinked legs
        # Join with bets to get date and sport
        query = """
        SELECT l.id, l.selection, l.leg_type, b.sport, b.date, b.description
        FROM bet_legs l
        JOIN bets b ON l.bet_id = b.id
        WHERE l.event_id IS NULL
        AND l.status = 'PENDING'
        """
        legs = _exec(conn, query).fetchall()
        print(f"Found {len(legs)} unlinked legs.")
        
        linked_count = 0
        unmatched_count = 0
        
        for leg in legs:
            leg_id = leg[0]
            leg_data = {
                'selection': leg[1],
                'leg_type': leg[2]
            }
            sport = leg[3]
            date = leg[4]
            description = leg[5]
            
            event_id = resolver.resolve_event_id_for_leg(leg_data, sport, date, description)
            
            if event_id:
                # Update Leg
                _exec(conn, "UPDATE bet_legs SET event_id = :eid WHERE id = :lid", {
                    "eid": event_id, "lid": leg_id
                })
                linked_count += 1
            else:
                # Add to Queue
                # check if already exists
                check = "SELECT leg_id FROM unmatched_legs_queue WHERE leg_id = :lid"
                if not _exec(conn, check, {"lid": leg_id}).fetchone():
                    insert_q = """
                    INSERT INTO unmatched_legs_queue (leg_id, reason, candidates_json)
                    VALUES (:lid, 'Resolver returned None', :cand)
                    """
                    _exec(conn, insert_q, {"lid": leg_id, "cand": json.dumps([])})
                unmatched_count += 1
                
        conn.commit()
    
    print(f"Linked: {linked_count}")
    print(f"Unmatched: {unmatched_count}")

if __name__ == "__main__":
    link_legs()
