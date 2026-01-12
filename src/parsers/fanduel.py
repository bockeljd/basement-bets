import re
from datetime import datetime

class FanDuelParser:
    def parse(self, raw_text):
        """
        Parses raw text from FanDuel 'Card View' copy-paste.
        Returns a list of bet dictionaries.
        """
        bets = []
        # Split into blocks based on "BET ID:" which is a reliable delimiter at the bottom of each card
        # Strategy: The "BET ID" line is near the end. We validly assume one file contains multiple bets.
        # We can regex split.
        
        # Normalize text
        raw_text = raw_text.strip()
        
        # Split by BET ID lines to separate bets approximately
        # Actually, "BET ID" is at the bottom. The text before it belongs to that bet.
        # Let's split by regex that captures the BET ID line, then iterate.
        
        # Pattern: BET ID: O/xxxx/xxxx
        # We find all end-markers, then slice the text? 
        # Or just split by "BET ID:" and reconstruct?
        
        # Let's try splitting by the PLACED date line, which usually follows BET ID.
        # Actually, let's look at the structure:
        # [Bet Details]
        # [Wager/Return]
        # BET ID: ...
        # PLACED: ...
        
        # We can split by "BET ID: O/" regex.
        chunks = re.split(r'(BET ID: O/\S+)', raw_text)
        
        # chunks[0] is text before first bet id (the body of first bet)
        # chunks[1] is the first bet id
        # chunks[2] is text after (includes PLACED line of first bet, then body of second bet)
        
        # We need to recombine carefully.
        # Actually, "PLACED: ..." follows "BET ID: ..." immediately.
        # So a bet block ends with "PLACED: ... ET".
        
        # Let's try a block-based approach using regex finditer.
        # We look for the "footer" of a bet and grab everything before it up to the previous footer.
        
        # But simpler: Split by "BET ID:".
        # segment `i` contains the body of bet `i`.
        # segment `i+1` starts with the ID, then PLACED, then body of bet `i+1`.
        
        # Let's clean this up. A bet ends essentially after the "PLACED: <date>" line.
        # Let's just iterate line by line to build blocks.
        
        lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
        current_block = []
        parsed_bets = []
        
        for i, line in enumerate(lines):
            current_block.append(line)
            if line.startswith("PLACED:"):
                # End of a bet block
                bet_data = self._parse_single_bet(current_block)
                if bet_data:
                    parsed_bets.append(bet_data)
                current_block = []
                
        return parsed_bets

    def _parse_single_bet(self, block):
        # Join for regex searching
        full_text = "\n".join(block)
        
        # 1. Date
        # Line: PLACED: 1/11/2026 4:28PM ET
        date_match = re.search(r'PLACED:\s+(\d{1,2}/\d{1,2}/\d{4}.*?ET)', full_text)
        if not date_match:
            return None
        date_str = date_match.group(1).replace("ET", "").strip()
        # Parse date buffer
        try:
            # 1/11/2026 4:28PM
            dt = datetime.strptime(date_str, "%m/%d/%Y %I:%M%p")
            formatted_date = dt.strftime("%Y-%m-%d")
        except:
            formatted_date = date_str

        # 2. Wager and Return
        # Search for lines starting with $
        # $10.00\nTOTAL WAGER
        # $0.00\nRETURNED
        # or $23.20\nWON ON FANDUEL
        
        wager = 0.0
        return_amount = 0.0
        status = "LOST" # Default
        
        # Find "TOTAL WAGER" and look at line before
        for i, line in enumerate(block):
            if "TOTAL WAGER" in line:
                # Wager is usually line before
                wager_line = block[i-1]
                wager = float(wager_line.replace('$', '').replace(',', ''))
            
            if "WON ON FANDUEL" in line or "RETURNED" in line:
                # Return is line before
                ret_line = block[i-1]
                return_amount = float(ret_line.replace('$', '').replace(',', ''))
        
        profit = return_amount - wager
        
        # Status Logic
        if return_amount > 0.01: # Check for > 0 essentially, strictly profit > -wager
             # If return < wager it's usually "Cashed Out" or partial win, but usually FD says "WON" if you get paid.
             # Strict logic: if profit >= 0, WON. If return > 0 but profit < 0, maybe "CASHED OUT" or "PARTIAL".
             # For now, let's treat any return > 0 as "WON" (or at least "NOT LOST")?
             # Actually, usually "WON ON FANDUEL" implies a win. "RETURNED" usually implies 0.00 (Loss) or Push (Return = Wager).
             if abs(profit) < 0.01:
                 status = "PUSH"
             elif profit > 0:
                 status = "WON"
             else:
                 status = "LOST" # Or cashed out for loss
        else:
             status = "LOST"

        # 3. Bet Type & Sport
        # Top lines usually have "Same Game Parlay", "2 leg parlay", or just Team Name (Moneyline/Spread)
        first_line = block[0]
        bet_type = "Straight"
        
        if "Parlay" in first_line:
            bet_type = "Parlay"
            if "Same Game" in first_line:
                bet_type = "SGP"
        elif "Round Robin" in first_line:
            bet_type = "Round Robin"
        else:
            bet_type = "Straight" # Likely Moneyline or Spread

        # Sport Inference (Heuristic)
        # Look for keywords in the whole block
        # NFL: "Quarterback", "Passing", "Rushing", "Touchdown", or team names (49ers, Chiefs)
        # NBA: "Points", "Assists", "Rebounds", "Spurs", "Pacers"
        # MLB: "Innings", "Strikeouts", "Dodgers", "Yankees"
        # NCAA: "Universities" (look for heuristics)
        
        sport = "Unknown"
        text_lower = full_text.lower()
        
        nfl_terms = ["passing", "rushing", "touchdown", "receptions", "quarterback", "nfl", "bills", "chiefs", "49ers", "eagles", "ravens", "bengals", "cowboys", "lions", "packers", "bears"]
        nba_terms = ["points", "assists", "rebounds", "nba", "spurs", "pacers", "lakers", "celtics", "threes"]
        ncaab_terms = ["ncaa", "gonzaga", "duke", "unc", "xavier", "marquette", "depaul", "indiana @ penn state"] # Intersection with CFB?
        ncaaf_terms = ["alabama", "georgia", "texas", "ohio state", "michigan", "cfb", "recieving yds"] # "receiving" vs "receptions"
        
        # Refine heuristics
        if any(t in text_lower for t in nfl_terms):
            sport = "NFL"
        elif any(t in text_lower for t in nba_terms):
            sport = "NBA"
        elif any(t in text_lower for t in ncaab_terms):
            sport = "NCAAB"
        elif any(t in text_lower for t in ncaaf_terms):
            sport = "NCAAF" # Hard to distinguish NCAA sports without team DB, but start basics
        
        # 4. Odds
        # Look for the first line starting with "+" or "-" that represents the total odds.
        # Often line 2 or 3.
        # Special case: Profit Boost.
        # +214
        # +320
        # profit boost
        # 50%
        
        odds = None
        # Try to find the odds in the first few lines
        # Usually it's the total odds for the bet
        for line in block[0:6]:
            if re.match(r'^[+-]\d+$', line):
                # Found an odds line.
                # If there are two, one might be the original, one boosted.
                # If "profit boost" follows, the second one is likely result?
                # FD usually lists: "Original Odds" then "Boosted Odds"
                # Ex: +214, +320.
                # So we take the last one found in the top header section?
                odds = int(line)
        
        # 5. Selection / Description
        # Just grab the block text excluding footer.
        # Maybe filter out common noise lines like "Finished", "profit boost", etc.
        selection_lines = []
        for line in block:
            if "BET ID:" in line: break
            if "TOTAL WAGER" in line: break
            if "$" in line: continue 
            if "Finished" in line: continue
            if "profit boost" in line: continue
            if "%" in line and len(line) < 5: continue # boost %
            if line == bet_type: continue
            
            selection_lines.append(line)
            
        selection = ", ".join(selection_lines[:5]) # First 5 lines as summary
        description = f"{bet_type} - {sport}"

        # 6. Live / Bonus
        is_live = "Live" in full_text
        is_bonus = "Bonus" in full_text or "Free Bet" in full_text or "profit boost" in text_lower

        return {
            "provider": "FanDuel",
            "date": formatted_date,
            "sport": sport,
            "bet_type": bet_type,
            "wager": wager,
            "profit": profit,
            "status": status,
            "description": description, 
            "selection": selection,
            "odds": odds,
            "is_live": is_live,
            "is_bonus": is_bonus,
            "raw_text": full_text
        }
