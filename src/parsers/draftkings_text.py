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
        # Regex to find the footer line of each bet
        footer_pattern = re.compile(r'([A-Z][a-z]{2} \d{1,2}, \d{4}, \d{1,2}:\d{2}:\d{2} [AP]M)(DK\d+)')
        
        lines = content.split('\n')
        buffer = []
        
        for line in lines:
            line = line.strip()
            if not line: continue
            
            match = footer_pattern.search(line)
            if match:
                raw_date = match.group(1)
                bet_id = match.group(2)
                
                bet = self._parse_block(buffer, raw_date, bet_id)
                if bet:
                    bets.append(bet)
                
                buffer = []
            else:
                buffer.append(line)
                
        return bets


    def _parse_block(self, lines: List[str], date_str: str, bet_id: str) -> Optional[Dict]:
        try:
            # 0. Pre-filter Noise
            filter_patterns = [
                r'^\d+$', # Single numbers (scorecard)
                r'^Final Score', 
                r'^View Picks',
                r'^\w{3} \d{1,2}, \d{4}', # Date inside block
                r'Parlay Boost',
                r'^T$', # Single T from scorecard
                r'^Paste Bet Slip',
                r'^Sportsbook',
                r'^Bankroll Account',
                r'^Main Bankroll',
                r'^Paste Slip Text',
                r'^Review Details',
                r'^DraftKings$'
            ]
            
            cleaned_lines = []
            for l in lines:
                 l = l.strip()
                 if not l: continue
                 # Normalize dashes
                 l = l.replace('\u2212', '-').replace('\u2013', '-').replace('\u2014', '-')
                 
                 is_noise = False
                 for p in filter_patterns:
                     if re.search(p, l): is_noise = True; break
                 
                 if ("Wager:" in l or "Paid:" in l or "Payout:" in l):
                     is_noise = False # Always keep financial lines
                     
                 if not is_noise:
                     cleaned_lines.append(l)
            
            lines = cleaned_lines
            if not lines: return None

            # 1. Identify Lines by Content
            status = "PENDING"
            status_idx = -1
            wager = 0.0
            paid = 0.0
            wager_idx = -1
            matchup = ""
            matchup_idx = -1
            header = ""
            header_idx = -1
            odds = None
            
            for i, l in enumerate(lines):
                # Normalize dashes to standard hyphen (Already done above, but safe to keep or remove)
                l_up = l.upper()
                
                # Odds / Header (PARLAY, SGP, Pick, ML, OR [+-]\d{3,})
                # We enforce 3+ digits for odds to avoid matching spread points like -2.5
                if header_idx == -1:
                    odds_matches = re.findall(r'[+-]\d{3,}', l)
                    keywords = ["PARLAY", "SGP", "PICK", "ML", "MONEYLINE", "STRAIGHT", "LEG", "SPREAD", "TOTAL", "OVER", "UNDER", "PROP", "TEASER", "ROUND ROBIN"]
                    if odds_matches or any(x in l_up for x in keywords):
                        header = l
                        header_idx = i
                        if odds_matches:
                            odds = int(odds_matches[-1])

                # Status
                if status == "PENDING" and any(x in l_up for x in ["WON", "LOST", "CASHED OUT"]):
                    if "WON" in l_up: status = "WON"
                    elif "LOST" in l_up: status = "LOST"
                    elif "CASHED OUT" in l_up: status = "CASHED OUT"
                    status_idx = i
                
                # Wager
                if "Wager:" in l:
                    w_match = re.search(r'Wager:[\s\xa0]*\$([\d\.,]+)', l)
                    if w_match: wager = float(w_match.group(1).replace(',', ''))
                    wager_idx = i
                
                # Paid/Payout on any line
                p_match = re.search(r'(?:Paid|Payout):[\s\xa0]*\$([\d\.,]+)', l)
                if p_match:
                    paid = float(p_match.group(1).replace(',', ''))

            # Matchup & Team Detection
            teams_found = []
            
            # Team Keywords (Expanded)
            nfl_teams = ["chiefs", "bills", "ravens", "lions", "packers", "buccaneers", "49ers", "cowboys", "eagles", "nfl", "touchdown", "rushing", "passing", "qb", "yardage", "interception", "chargers", "patriots", "steelers", "bengals", "browns", "titans", "colts", "jaguars", "texans", "broncos", "raiders", "giants", "commanders", "rams", "cardinals", "seahawks", "saints", "falcons", "panthers", "vikings", "bears", "dolphins", "jets", "niners"]
            nba_teams = ["lakers", "celtics", "warriors", "bucks", "suns", "mavs", "knicks", "nba", "rebounds", "assists", "points", "threes", "block", "steals", "sixers", "nets", "raptors", "bulls", "cavs", "pistons", "pacers", "heat", "magic", "hawks", "hornets", "wizards", "nuggets", "wolves", "thunder", "blazers", "jazz", "kings", "clippers", "rockets", "spurs", "grizzlies", "pelicans"]
            ncaam_teams = ["purdue", "kansas", "duke", "unc", "marquette", "gonzaga", "uconn", "kentucky", "jayhawks", "ncaam", "ncaa", "basketball", "college basketball", "march madness", "iu indianapolis", "detroit mercy", "crimson tide", "wildcats", "spartans", "wolverines", "buckeyes", "hoosiers", "boilermakers", "illini", "badgers", "gophers", "huskies", "hawkeyes", "longhorns", "sooners", "cowboys", "bears", "cyclones", "raiders", "tigers", "bulldogs", "volunteers", "gamecocks", "commodity", "commodores"]
            mlb_teams = ["dodgers", "yankees", "red sox", "cubs", "astros", "braves", "mlb", "innings", "runs", "strikeouts", "stolen base", "home run"]
            nhl_teams = ["bruins", "leafs", "rangers", "oilers", "golden knights", "nhl", "puck line", "goalie", "slapshot", "icing"]
            soccer_teams = ["liverpool", "arsenal", "chelsea", "man city", "real madrid", "barcelona", "soccer", "epl", "champions league", "premier league", "la liga", "bundesliga", "man united", "tottenham", "bayern", "dormund"]

            for l in lines:
                l_lower = l.lower()
                # Existing Matchup Check
                if matchup_idx == -1 and ("@" in l or " vs " in l_lower or " v " in l_lower):
                    matchup = l
                    matchup_idx = i
                
                # Team Scanning (if no typical matchup line found)
                for t in nfl_teams + nba_teams + ncaam_teams + mlb_teams + nhl_teams + soccer_teams:
                    if t in l_lower and len(t) > 3: # Avoid short noise
                        # Store the actual team name (title cased), not the full line
                        team_name = t.title()
                        if team_name not in teams_found:
                            teams_found.append(team_name)
                        break  # Only capture first team match per line to avoid duplicates

            # 2. Bet Type Normalization
            # PRIORITY: Check for explicit bet type keywords on their own lines FIRST
            explicit_bet_type = None
            explicit_bet_type_keywords = {
                "SPREAD": "Spread", "POINT SPREAD": "Spread",
                "MONEYLINE": "ML", "MONEY LINE": "ML", "ML": "ML",
                "TOTAL": "Over/Under", "OVER/UNDER": "Over/Under", "OVER / UNDER": "Over/Under",
                "OVER": "Over/Under", "UNDER": "Over/Under",
                "PROP": "Prop", "PLAYER PROP": "Prop",
                "SGP": "SGP", "SAME GAME PARLAY": "SGP",
                "PARLAY": "Parlay", "2 LEG": "2 leg parlay", "3 LEG": "3 leg parlay", "4+ LEG": "4+ leg parlay",
            }
            for l in lines:
                l_stripped = l.strip().upper()
                if l_stripped in explicit_bet_type_keywords:
                    explicit_bet_type = explicit_bet_type_keywords[l_stripped]
                    break
            
            # If we found an explicit keyword, use it. Otherwise, fall back to header parsing.
            if explicit_bet_type:
                bet_type = explicit_bet_type
            else:
                bet_type_raw = header if header else "Straight"
                bet_type = bet_type_raw
                # Remove odds from bet type
                # Handle concatenated odds in header like "SGP2 Picks+100+130" -> extract +130
                odds_matches = re.findall(r'[+-]\d{3,}', bet_type)
                if odds_matches:
                     # Use the last match as the odds for the bet
                     try: odds = int(odds_matches[-1]) 
                     except: pass
                     for o in odds_matches:
                         bet_type = bet_type.replace(o, "")
                bet_type = bet_type.strip()
                
                bet_type_upper = bet_type.upper()
                
                # Check SGP in header
                if "SGP" in bet_type_upper or "SAME GAME PARLAY" in bet_type_upper:
                    # Keep leg count if available
                    leg_match = re.search(r'(\d+)', bet_type_upper)
                    if leg_match:
                         bet_type = f"{leg_match.group(1)} Leg SGP"
                    else:
                         bet_type = "SGP"
                elif any(x in bet_type_upper for x in ["WINNER (ML)", "STRAIGHT", "MONEYLINE", "MONEY LINE", "ML"]):
                    bet_type = "ML"
                elif any(x in bet_type_upper for x in ["PARLAY", "LEG", "PICK"]):
                    leg_match = re.search(r'(\d+)', bet_type)
                    if leg_match: bet_type = f"{leg_match.group(1)} leg parlay"
                    elif "4+" in bet_type_upper or "4 LEG" in bet_type_upper: bet_type = "4 leg parlay"
                    else: bet_type = "parlay"
                elif any(x in bet_type_upper for x in ["OVER / UNDER", "TOTAL OVER/UNDER", "TOTAL (OVER/UNDER)", "TOTAL", "OVER", "UNDER"]):
                    bet_type = "Over/Under"
                elif "PROP" in bet_type_upper:
                    bet_type = "Prop"
                elif "SPREAD" in bet_type_upper or "POINT SPREAD" in bet_type_upper:
                    bet_type = "Spread"
                else:
                     # Last ditch check if Spread/ML is mentioned in other lines
                     text_all = " ".join(lines).upper()
                     if "SPREAD" in text_all: bet_type = "Spread"
                     elif "MONEYLINE" in text_all: bet_type = "ML"
                     elif "TOTAL" in text_all or "OVER" in text_all: bet_type = "Over/Under"
                     else: bet_type = "Straight" # Default fallback


            # 3. Selection Identification
            selection_lines = []
            filter_patterns = [
                r'^\d+$', # Single numbers (scorecard)
                r'^Final Score', 
                r'^View Picks',
                r'^\w{3} \d{1,2}, \d{4}', # Date inside block
                r'Parlay Boost',
                r'^T$', # Single T from scorecard
                r'^Paste Bet Slip',
                r'^Sportsbook',
                r'^Bankroll Account',
                r'^Main Bankroll',
                r'^Paste Slip Text',
                r'^Review Details',
                r'^DraftKings$'
            ]
            
            for i, l in enumerate(lines):
                if i in [header_idx, status_idx, wager_idx, matchup_idx]: continue
                
                # Filter noise
                is_noise = False
                for p in filter_patterns:
                    if re.search(p, l): is_noise = True; break
                if is_noise: continue
                
                selection_lines.append(l)
            
            selection = ", ".join(selection_lines) if selection_lines else ""
            
            # Construct Matchup from detected Teams if implicit
            if not matchup and len(teams_found) >= 2:
                matchup = f"{teams_found[0]} vs {teams_found[1]}"
            
            if not matchup: matchup = selection or "Unknown Matchup"
            if not selection: selection = matchup

            # 4. Profit Calculation
            status_up = status.upper()
            if status_up == "WON" or status_up == "CASHED OUT":
                if paid > 0:
                    profit = paid - wager
                elif odds:
                    if odds > 0: profit = wager * (odds / 100)
                    else: profit = wager * (100 / abs(odds))
                else:
                    profit = 0.0
            else:
                profit = -wager
            
            dt = datetime.strptime(date_str, "%b %d, %Y, %I:%M:%S %p")
            description = matchup

            # 5. Sport Inference
            sport = "Unknown"
            text_to_scan = (" ".join(lines) + " " + selection + " " + matchup).lower()
            
            if any(t in text_to_scan for t in nfl_teams): sport = "NFL"
            elif any(t in text_to_scan for t in nba_teams): sport = "NBA"
            elif any(t in text_to_scan for t in ncaam_teams): sport = "NCAAM"
            elif any(t in text_to_scan for t in mlb_teams): sport = "MLB"
            elif any(t in text_to_scan for t in nhl_teams): sport = "NHL"
            elif any(t in text_to_scan for t in soccer_teams): sport = "SOCCER"

            return {
                "provider": "DraftKings",
                "date": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "sport": sport,
                "bet_type": bet_type,
                "wager": wager,
                "profit": round(profit, 2),
                "status": status.upper(),
                "description": description,
                "selection": selection,
                "odds": odds,
                "is_live": "LIVE" in " ".join(lines).upper(),
                "is_bonus": "Boost" in "".join(lines) or "Bonus" in "".join(lines),
                "raw_text": "\n".join(lines) + f"\n{date_str}{bet_id}"
            }
            
        except Exception as e:
            print(f"Error parsing block: {e}")
            return None
