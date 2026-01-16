import csv
import re
from datetime import datetime
from typing import List, Dict, Optional, Any

class LegacySheetParser:
    def __init__(self, file_path: str):
        self.file_path = file_path
        # Column mapping based on CSV inspection (0-indexed)
        # 0: Bet #
        # 1: Date
        # 2: Bookmaker
        # 3: Bet Type
        # 4: League
        # 5: Home Team
        # 6: Away Team
        # 7: Bet Placed (Selection)
        # 8: Odds
        # 9: Stake
        # 11: Win (Yes/No)
        # 19: Profit / Loss (Column T)
        self.COL_BET_NUM = 0
        self.COL_DATE = 1
        self.COL_BOOKMAKER = 2
        self.COL_BET_TYPE = 3
        self.COL_LEAGUE = 4
        self.COL_SELECTION = 7
        self.COL_ODDS = 8
        self.COL_STAKE = 9
        self.COL_WIN = 11
        self.COL_PROFIT = 19

    def parse(self) -> List[Dict[str, Any]]:
        parsed_bets = []
        current_parlay_parent = None

        with open(self.file_path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f)
            
            # Skip first 2 header rows
            try:
                next(reader)
                next(reader)
            except StopIteration:
                return []

            for row_idx, row in enumerate(reader, start=3):
                if not row or len(row) < 5:
                    continue

                # Clean all cells
                row = [cell.strip() for cell in row]

                bet_num = row[self.COL_BET_NUM]
                
                # Check if it's a Parent Row
                if bet_num and bet_num != "#VALUE!":
                    # If we had a previous parent, save it (it's already in the list, just updating state)
                    # Reset parent for new bet
                    current_parlay_parent = None

                    bet_data = self._extract_parent_row(row, row_idx)
                    if bet_data:
                        parsed_bets.append(bet_data)
                        
                        # Check if this is a parlay that will have children
                        # Logic: "See Below" in selection OR "Parlay" in bet type
                        if "See Below" in row[self.COL_SELECTION] or "Parlay" in row[self.COL_BET_TYPE]:
                            current_parlay_parent = bet_data
                            current_parlay_parent['legs'] = []

                # Check if it's a Leg Row (No Bet #, but has Bet Type or Selection)
                elif not bet_num and current_parlay_parent:
                    # It's a leg for the current parlay
                    leg_desc = self._extract_leg_row(row)
                    if leg_desc:
                        current_parlay_parent['legs'].append(leg_desc)

        # Post-process: Update descriptions with legs
        for bet in parsed_bets:
            if 'legs' in bet and bet['legs']:
                bet['description'] += " | " + " / ".join(bet['legs'])
                del bet['legs'] # Cleanup

        return parsed_bets

    def _extract_parent_row(self, row: List[str], row_idx: int) -> Optional[Dict[str, Any]]:
        try:
            date_str = row[self.COL_DATE]
            if not date_str:
                return None
            
            # Date parsing (M/D/YYYY)
            try:
                dt = datetime.strptime(date_str, "%m/%d/%Y")
                date_formatted = dt.strftime("%Y-%m-%d")
            except ValueError:
                # Try 2-digit year if needed, or return raw/skip
                return None

            bookmaker = row[self.COL_BOOKMAKER]
            bet_type = row[self.COL_BET_TYPE]
            selection = row[self.COL_SELECTION]
            stake_str = row[self.COL_STAKE]
            profit_str = row[self.COL_PROFIT]
            win_str = row[self.COL_WIN] # "Yes" or "No" usually determines Win, but Profit is source of truth

            stake = self._clean_currency(stake_str)
            profit = self._clean_currency(profit_str)

            # Determine Status
            # We trust the profit column mostly. 
            # If profit > 0 -> WON
            # If profit < 0 (negative) -> LOST
            # If profit == 0:
            #   If win_str == "Yes" -> Push/Void? Or just break even?
            #   Usually 0 profit means Push.
            
            if profit > 0:
                status = "WON"
            elif profit < 0:
                status = "LOST"
                # Correction: "Lost" usually means you lost the stake. 
                # The spreadsheet likely shows `$(20.00)` for a loss of 20.
                # Our system expects profit to be negative for losses.
            else:
                # Check 'Win' column for Push logic if profit is 0
                if win_str.lower() == "push" or "void" in win_str.lower():
                    status = "VOID"
                else:
                    status = "VOID" # Default to void if $0.00 profit

            odds = row[self.COL_ODDS]
            try:
                odds_val = int(odds)
            except:
                odds_val = None

            try:
                odds_val = int(odds)
            except:
                odds_val = None

            # Sport
            sport = row[self.COL_LEAGUE] if len(row) > self.COL_LEAGUE else "Unknown"

            # Construct Description
            # Start with primary selection. If "See Below", we'll append legs later.
            description = selection

            return {
                "external_id": f"legacy_sheet_{row[self.COL_BET_NUM]}", # Use Bet # as ID (for reference)
                "date_placed": date_formatted,
                "sportsbook": bookmaker,
                "bet_type": bet_type,
                "wager": stake,
                "profit": profit,
                "status": status,
                "description": description,
                "odds": odds_val,
                "sport": sport,
                "raw_row": row_idx
            }

        except Exception as e:
            print(f"Error parsing row {row_idx}: {e}")
            return None

    def _extract_leg_row(self, row: List[str]) -> Optional[str]:
        # Selection is at COL_SELECTION
        # Home Team at 5, Away Team at 6
        # E.g. Leg selection might be in 'Selection' column 
        selection = row[self.COL_SELECTION]
        if selection and selection != "See Below:":
            return selection
        
        # Fallback: check teams content if selection is empty? 
        # Usually selection has the pic (e.g., "Eagles -5.5")
        return None

    def _clean_currency(self, value_str: str) -> float:
        if not value_str:
            return 0.0
        
        # Handle accounting format $(20.00) -> -20.00
        is_negative = False
        if "(" in value_str and ")" in value_str:
            is_negative = True
        
        cleaned = re.sub(r'[^\d\.]', '', value_str)
        try:
            val = float(cleaned)
            if is_negative:
                val = -val
            return val
        except ValueError:
            return 0.0

if __name__ == "__main__":
    # Test run
    import json
    parser = LegacySheetParser("/Users/jordanbockelman/Basement Bets/bet_tracker/data/imports/legacy_history.csv")
    bets = parser.parse()
    print(f"Parsed {len(bets)} bets.")
    if bets:
        print(json.dumps(bets[0], indent=2))
        print(json.dumps(bets[1], indent=2)) # likely a parlay
