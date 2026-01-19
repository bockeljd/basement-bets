import sys
import os
import csv
from datetime import datetime
import uuid

# Ensure src is importable
sys.path.append(os.getcwd())

from src.database import get_db_connection, _exec

def parse_currency(val):
    if not val: return 0.0
    val = val.replace('$', '').replace(' ', '').replace(',', '')
    if '(' in val and ')' in val:
        val = val.replace('(', '').replace(')', '')
        return -float(val)
    if val == '-': return 0.0
    try:
        return float(val)
    except:
        return 0.0

def main():
    filepath = '/Users/jordanbockelman/Basement Bets/data/imports/Basement Bets 11826.csv'
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return

    bets = []
    current_bet = None
    
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        for i, row in enumerate(reader):
            # Strict Parsing based on Bet #
            bet_id_val = row.get('Bet #', '').strip()
            
            # If start of file or empty row, skip if no data
            if not bet_id_val and not row.get('Date', '').strip():
                continue

            if bet_id_val:
                # NEW MAIN BET
                if current_bet:
                    bets.append(current_bet)
                
                # Parse fields
                bet_type = row.get('Bet Type', '').strip()
                date_str = row.get('Date', '')
                try:
                    dt = datetime.strptime(date_str, '%m/%d/%Y')
                    # Add random time to avoid Unique Constraint on (user, provider, desc, date, wager)
                    # Use fixed Hour 12, but random Minute/Second
                    import random
                    rand_min = random.randint(0, 59)
                    rand_sec = random.randint(0, 59)
                    iso_date = dt.strftime(f'%Y-%m-%d 12:{rand_min:02d}:{rand_sec:02d}')
                except:
                    iso_date = date_str 
                
                home = row.get('Home Team', '').strip()
                away = row.get('Away Team', '').strip()
                desc = f"{away} @ {home}" if home and away else row.get('League', 'Unknown')
                
                wager = parse_currency(row.get('Stake', '0'))
                # Empty string key corresponds to 'Profit / Loss' column based on fieldnames
                profit = parse_currency(row.get('', '0'))
                
                is_live = row.get('Live Bet?', '').strip().lower() == 'yes'
                is_bonus = row.get('Bonus Bet?', '').strip().lower() == 'yes'
                is_parlay = 'parlay' in bet_type.lower()
                if bet_type.strip() == 'Leg': is_parlay = True 

                win_status = row.get('Win', '').lower()
                bet_result = row.get('Bet Result', '').lower()
                
                status = "PENDING"
                if win_status == 'yes': status = "WON"
                elif win_status == 'no': status = "LOST"
                elif profit > 0: status = "WON"
                elif profit < 0: status = "LOST"
                
                # Check for Push/Void
                if 'push' in bet_result or 'void' in bet_result or 'tie' in bet_result:
                    status = "PUSH"
                    profit = 0.0

                odds_val = row.get('Odds', '').replace(',', '')
                try: odds = int(odds_val)
                except: odds = None

                current_bet = {
                    "date": iso_date,
                    "sport": row.get('League', 'Unknown').upper().replace('NCAAW', 'NCAAM'), 
                    "bet_type": bet_type,
                    "wager": wager,
                    "profit": profit,
                    "status": status,
                    "description": desc,
                    "selection": row.get('Bet Placed', ''),
                    "odds": odds,
                    "provider": row.get('Bookmaker', 'Unknown'),
                    "is_live": is_live,
                    "is_bonus": is_bonus,
                    "raw_id": bet_id_val,
                    "legs": []
                }
            else:
                # LEG ROW
                if current_bet:
                    leg_sel = row.get('Bet Placed', '').strip()
                    leg_res = row.get('Win', '').strip()
                    if leg_sel:
                        current_bet['legs'].append({
                            'selection': leg_sel,
                            'result': leg_res
                        })
        
        # Last bet
        if current_bet:
            bets.append(current_bet)

    print(f"Parsed {len(bets)} bets.")
    
    with get_db_connection() as conn:
        print("Clearing bets table in Postgres (and dependencies)...")
        # Clear dependencies first to avoid FK violation
        try:
            print("Deleting unmatched_legs_queue...")
            _exec(conn, "DELETE FROM unmatched_legs_queue")
            print("Deleting bet_legs...")
            _exec(conn, "DELETE FROM bet_legs")
            print("Deleting bets...")
            _exec(conn, "DELETE FROM bets")
        except Exception as e:
            print(f"Error clearing tables: {e}")
            conn.rollback() # Reset transaction
            return 
        
        inserted = 0
        for b in bets:
            if b['legs']:
                leg_desc = " | ".join([l['selection'] for l in b['legs']])
                if not b['selection'] or b['selection'].lower() == 'see below:' or b['selection'].lower() == 'see below':
                   b['selection'] = leg_desc
                else:
                   b['selection'] = f"{b['selection']} ({leg_desc})"
            
            # Use dev default UUID
            u_id = "00000000-0000-0000-0000-000000000000"
            
            q = """
                INSERT OR IGNORE INTO bets 
                (user_id, date, sport, bet_type, wager, profit, status, description, selection, odds, provider, is_live, is_bonus, raw_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            try:
                _exec(conn, q, (
                    u_id, b['date'], b['sport'], b['bet_type'], b['wager'], b['profit'], b['status'],
                    b['description'], b['selection'], b['odds'], b['provider'],
                    b['is_live'], b['is_bonus'],
                    f"Imported from CSV ID {b.get('raw_id')}"
                ))
                inserted += 1
            except Exception as e:
                print(f"Skipped duplicate or error for bet {b.get('raw_id')}: {e}")
                
        conn.commit()
        print(f"Successfully inserted {inserted} bets into Postgres via src.database.")

if __name__ == "__main__":
    main()
