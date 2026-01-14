from typing import List, Dict, Optional
import re
from datetime import datetime

class DraftKingsTextParser:
    def parse(self, content: str) -> List[Dict]:
        """
        Parses raw copy-pasted text from DraftKings 'My Bets' view.
        Blocks end with a specific Date+ID signature line:
        'Jan 11, 2026, 9:20:07 PMDK6390...'
        """
        bets = []
        # Normalization
        # There might be blank lines.
        # Strategy: Split by the ID pattern which acts as a delimiter at the end of a bet.
        # Pattern: Date Time AM/PM DK[Digits]
        
        # Regex to find the footer line of each bet
        # Jan 11, 2026, 9:20:07 PMDK639037812077482961
        footer_pattern = re.compile(r'([A-Z][a-z]{2} \d{1,2}, \d{4}, \d{1,2}:\d{2}:\d{2} [AP]M)(DK\d+)')
        
        # Split entire content by this footer? 
        # Actually, iterate through lines. Buffer lines until footer found.
        
        lines = content.split('\n')
        buffer = []
        
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # Check if this line is the footer
            match = footer_pattern.search(line)
            if match:
                # End of a bet block
                raw_date = match.group(1) # Jan 11, 2026, 9:20:07 PM
                bet_id = match.group(2)   # DK6390...
                
                # Parse buffer
                bet = self._parse_block(buffer, raw_date, bet_id)
                if bet:
                    bets.append(bet)
                
                buffer = [] # Reset
            else:
                buffer.append(line)
                
        return bets

    def _parse_block(self, lines: List[str], date_str: str, bet_id: str) -> Optional[Dict]:
        if not lines: return None
        
        try:
            # Line 0: Type + Odds
            # "SGP3 Picks+104" or "SGP4 Picks+122+159" (Two odds? Boosted?)
            # "4 Picks Parlay+212+256"
            header = lines[0]
            
            # Extract Odds (last number with + or -)
            # Sometimes multiple: "+122+159" -> Old odds + New odds (boosted)
            # We want the LAST one usually (the effective odds).
            odds_matches = re.findall(r'[+-]\d+', header)
            odds = int(odds_matches[-1]) if odds_matches else None
            
            # Type is everything before odds
            bet_type = header
            if odds_matches:
                 # Remove all odds strings
                 for o in odds_matches:
                     bet_type = bet_type.replace(o, "")
            bet_type = bet_type.strip()
            
            # Normalization
            if bet_type.upper() in ["WINNER (ML)", "STRAIGHT", "MONEYLINE"]:
                bet_type = "Moneyline"
            elif "Prop" in bet_type:
                bet_type = "Prop"
            elif any(x in bet_type for x in ["Over / Under", "Total Over/Under", "Total (Over/Under)", "Total"]):
                bet_type = "Total (Over/Under)"
            elif any(x in bet_type.upper() for x in ["PARLAY", "SGP", "LEG", "PICK"]):
                match = re.search(r'(\d+)', bet_type)
                if match:
                    count = int(match.group(1))
                    if count >= 4:
                        bet_type = "4+ Leg Parlay"
                    else:
                        bet_type = f"{count}-Leg Parlay"
                elif "4+" in bet_type or "4 leg" in bet_type.lower():
                    bet_type = "4+ Leg Parlay"
                else:
                    bet_type = "Parlay (includes SGP)"



            # Line 1: Selection
            # "Over 25.5, 200+, 200+"
            selection = lines[1]
            
            # Line 2: Status
            # "Lost", "Won", "Cashed Out"
            status = lines[2]
            
            # Line 3: Wager (+ Payout?)
            # "Wager: $10.00"
            # "Wager: $10.00Paid: $37.80"
            wager_line = lines[3]
            wager = 0.0
            profit = 0.0
            
            wager_match = re.search(r'Wager: \$([\d\.]+)', wager_line)
            if wager_match:
                wager = float(wager_match.group(1))
            
            paid_match = re.search(r'Paid: \$([\d\.]+)', wager_line)
            paid = float(paid_match.group(1)) if paid_match else 0.0
            
            # Calculate Profit
            if status == "Won" or status == "Cashed Out":
                profit = paid - wager
            else:
                profit = -wager
            
            # Parse Date
            dt = datetime.strptime(date_str, "%b %d, %Y, %I:%M:%S %p")
            
            # Description:
            description = selection # Default
            
            return {
                "provider": "DraftKings",
                "date": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "sport": "Unknown", # Use sport inference if possible
                "bet_type": bet_type,
                "wager": wager,
                "profit": profit,
                "status": status.upper(),
                "description": description,
                "selection": selection,
                "odds": odds,
                "is_live": False, # Could detect "LIVE" text
                "is_bonus": "Boost" in "".join(lines),
                "raw_text": "\n".join(lines) + f"\n{date_str}{bet_id}"
            }
            
        except Exception as e:
            print(f"Error parsing block: {e}")
            return None
