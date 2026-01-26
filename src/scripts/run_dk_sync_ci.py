
import os
import sys
import hashlib
import logging

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.services.draftkings_service import DraftKingsService
from src.database import insert_bet_v2, init_db
from src.services.event_linker import EventLinker

# Configure Logging
logging.basicConfig(level=logging.INFO)

def run_sync():
    # 1. Environment & Setup
    user_id = os.getenv("BASEMENT_USER_ID")
    if not user_id:
        print("❌ Error: BASEMENT_USER_ID env var is required.")
        sys.exit(1)
        
    print(f"🔄 Starting DK Sync for User {user_id}...")
    
    try:
        init_db()
    except Exception as e:
        print(f"⚠️ DB Init Warning (might be fine if already exists): {e}")

    # 2. Scrape (Headless)
    # We rely on previous session cookies if cached in ./chrome_profile
    service = DraftKingsService(profile_path="./chrome_profile")
    try:
        bets = service.scrape_history(headless=True)
    except Exception as e:
        print(f"❌ Scrape Failed: {e}")
        bets = []
    
    if not bets:
        print("⚠️ No bets found. Possible reasons: Login required, Network error, or minimal history.")
        sys.exit(0)

    print(f"🔍 Processing {len(bets)} bets...")

    # 3. Process & Save
    linker = EventLinker()
    saved_count = 0
    
    for bet in bets:
        try:
            # Construct Doc (Mirroring api.py logic)
            doc = {
                "user_id": user_id,
                "account_id": f"DK_{user_id}", 
                "provider": "DraftKings",
                "date": bet['date'],
                "sport": bet['sport'],
                "bet_type": bet['bet_type'],
                "wager": bet['wager'],
                "profit": round(bet['profit'], 2),
                "status": bet['status'],
                "description": bet['description'],
                "selection": bet['selection'],
                "odds": bet.get('odds', 0),
                "is_live": bet.get('is_live', False),
                "is_bonus": bet.get('is_bonus', False),
                "raw_text": bet.get('raw_text')
            }
            
            # Generate Hash
            raw_string = f"{user_id}|DraftKings|{doc['date']}|{doc['description']}|{doc['wager']}"
            doc['hash_id'] = hashlib.sha256(raw_string.encode()).hexdigest()
            doc['is_parlay'] = "parlay" in str(doc['bet_type']).lower() or "sgp" in str(doc['bet_type']).lower()
            
            # Create Leg
            leg = {
                "leg_type": doc['bet_type'], 
                "selection": doc['selection'],
                "market_key": doc['bet_type'],
                "odds_american": doc['odds'],
                "status": doc['status'],
                "subject_id": None, 
                "side": None, 
                "line_value": None
            }
            
            # Matchup Link
            link_result = linker.link_leg(leg, doc['sport'], doc['date'], doc['description'])
            leg['event_id'] = link_result['event_id']
            leg['link_status'] = link_result['link_status']
            
            # Validation Logic
            errors = []
            if doc['sport'] == 'Unknown':
                errors.append("Unknown Sport")
            if doc['status'] == 'WON' and doc['profit'] <= 0:
                errors.append("Invalid Profit (WON <= 0)")
            if doc['odds'] is None:
                errors.append("Missing Odds")
            
            doc['validation_errors'] = ", ".join(errors) if errors else None
            
            insert_bet_v2(doc, legs=[leg])
            saved_count += 1
            
        except Exception as e:
            print(f"⚠️ Failed to save bet {bet.get('description')}: {e}")
            continue
            
    print(f"✅ Sync Complete. Saved {saved_count}/{len(bets)} bets.")

if __name__ == "__main__":
    run_sync()
