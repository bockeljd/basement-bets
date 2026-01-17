from typing import List, Dict, Optional
import datetime
import re

class ManualTSVParser:
    def __init__(self):
        pass

    def parse(self, content: str) -> List[Dict]:
        """
        Parses the manual TSV format.
        Handles strict tab separation and aggregates parlay legs.
        """
        lines = content.split('\n')
        parsed_bets = []
        current_bet: Optional[Dict] = None

        # Headers usually line 0-1. We'll skip lines until we find a data row.
        # Data row start with an Integer ID in col 0.
        
        for line in lines:
            line = line.rstrip()
            if not line:
                continue
            
            # Split by Tab
            cols = line.split('\t')
            
            # Fallback: if tabs failed (len=1) and line is long, try splitting by 2+ spaces
            if len(cols) < 5 and len(line) > 20:
                cols = re.split(r'\s{2,}', line)
            
            # Check if this is a new bet row (First column is an ID number)
            # Use regex to check if col[0] is strictly digits
            is_new_bet = False
            # Clean col[0] of whitespace
            col0 = cols[0].strip()
            if col0.isdigit():
                is_new_bet = True
            
            if is_new_bet:
                # Save previous bet if exists
                if current_bet:
                    parsed_bets.append(current_bet)
                
                # Start new bet
                current_bet = self._parse_parent_row(cols)
            
            elif not cols[0].strip() and current_bet:
                # This could be a "Leg" row.
                if len(cols) > 4 and "Leg" in cols[3]:
                    selection = cols[7].strip() if len(cols) > 7 else ""
                    if selection:
                        current_bet['description'] += f" | {selection}"
                        if "See Below" in current_bet['selection']:
                            current_bet['selection'] = current_bet['selection'].replace("See Below:", "").replace("See Below", "").strip()
                        
                        if current_bet['selection']:
                            current_bet['selection'] += f", {selection}"
                        else:
                            current_bet['selection'] = selection
            else:
                if current_bet:
                     pass

        # Append last bet
        if current_bet:
            parsed_bets.append(current_bet)
            
        return parsed_bets

    def _parse_parent_row(self, cols: List[str]) -> Dict:
        # Defaults
        bet = {
            "provider": "Unknown",
            "date": "Unknown",
            "sport": "Unknown",
            "bet_type": "Unknown",
            "wager": 0.0,
            "profit": 0.0,
            "status": "UNKNOWN",
            "description": "",
            "selection": "",
            "odds": None,
            "is_live": False,
            "is_bonus": False,
            "raw_text": "\t".join(cols)
        }
        
        # Mappings based on user provided columns
        # 0: ID
        # 1: Date
        # 2: Bookmaker
        # 3: Bet Type
        # 4: League
        # 5: Home
        # 6: Away
        # 7: Selection
        # 8: Odds
        # 9: Stake
        # 10: Live?
        # 11: Win?
        # 12: Bonus?
        # ...
        # 20ish: Profit/Loss
        
        try:
            # 1. Date
            if len(cols) > 1:
                raw_date = cols[1].strip()
                try:
                    dt = datetime.datetime.strptime(raw_date, "%m/%d/%Y")
                    bet['date'] = dt.strftime("%Y-%m-%d")
                except:
                    bet['date'] = raw_date
            
            # 2. Bookmaker -> Provider
            if len(cols) > 2:
                bet['provider'] = cols[2].strip()
                
            # 3. Bet Type
            if len(cols) > 3:
                bet['bet_type'] = cols[3].strip()
                
            # 4. League -> Sport
            if len(cols) > 4:
                bet['sport'] = self._normalize_sport(cols[4].strip())
                
            # 5/6. Matchup -> Description
            home = cols[5].strip() if len(cols) > 5 else ""
            away = cols[6].strip() if len(cols) > 6 else ""
            bet['description'] = f"{away} @ {home}" if home and away else (home or away or "Unknown Matchup")
            
            # 7. Selection
            if len(cols) > 7:
                bet['selection'] = cols[7].strip()
                
            # 8. Odds
            if len(cols) > 8:
                raw_odds = cols[8].replace(",", "").strip()
                try:
                    bet['odds'] = int(float(raw_odds))
                except:
                    pass
            
            # 9. Stake -> Wager
            if len(cols) > 9:
                bet['wager'] = self._parse_currency(cols[9])
                
            # 10. Live?
            if len(cols) > 10 and "Yes" in cols[10]:
                bet['is_live'] = True
                
            # 12. Bonus?
            if len(cols) > 12 and "Yes" in cols[12]:
                bet['is_bonus'] = True
                
            # Find Profit Column. It is usually near the end.
            # In sample it is index 20 (approx). 
            # Strategy: look for last non-empty column? Or specific index?
            # From sample: " $ (20.00) " is the last column
            # Let's grab the last non-empty column or scan columns > 15
            profit_found = False
            for i in range(len(cols) - 1, 15, -1):
                val = cols[i].strip()
                if "$" in val or "(" in val or val.replace('.','').replace('-','').isdigit():
                     # Likely the profit column
                     bet['profit'] = self._parse_currency(val)
                     profit_found = True
                     break
            
            # Status derivation
            # If profit > 0 -> WON
            # If profit < 0 (but not equal to -wager) -> LOST? Or CASHED_OUT?
            # If profit == -wager -> LOST
            # If profit == 0 -> PUSH?
            # Also check "Win" column (index 11)
            won_col = cols[11].strip().lower() if len(cols) > 11 else ""
            
            if bet['profit'] > 0:
                bet['status'] = "WON"
            elif bet['profit'] == 0 and bet['wager'] > 0:
                bet['status'] = "PUSH" # Or unprocessed?
            elif bet['profit'] < 0:
                bet['status'] = "LOST"
                
            if won_col == "yes" and bet['status'] != "WON" and bet['profit'] >= 0:
                 bet['status'] = "WON"
            
        except Exception as e:
            print(f"Error parsing row: {e}")
            
        return bet

    YEAR_MAP = "2023" # Default if year missing, but user data has year.

    def _parse_currency(self, val: str) -> float:
        """
        Parses $20.00 or $(20.00) or -10.5
        $(20.00) denotes negative 20.00
        """
        val = val.strip().replace("$", "").replace(" ", "").replace(",", "")
        if val == "-": return 0.0
        
        # Accounting format: (20.00) -> -20.00
        if val.startswith("(") and val.endswith(")"):
            inner = val[1:-1]
            try:
                return -float(inner)
            except:
                return 0.0
                
        try:
            return float(val)
        except:
            return 0.0

    def _normalize_sport(self, league: str) -> str:
        league = league.upper().replace(".", "")
        if "NFL" in league: return "NFL"
        if "NBA" in league: return "NBA"
        if "MLB" in league: return "MLB"
        if "NCAAM" in league or "COLLEGE BASKETBALL" in league: return "NCAAB"
        if "NCAAF" in league or "COLLEGE FOOTBALL" in league: return "NCAAF"
        if "NHL" in league: return "NHL"
        if "UFC" in league or "MMA" in league: return "UFC"
        if "TENNIS" in league: return "Tennis"
        if "SOCCER" in league or "PREMIER" in league or "MLS" in league or "CHAMPIONS" in league: return "Soccer"
        if "GOLF" in league or "PGA" in league: return "Golf"
        return league.title()
