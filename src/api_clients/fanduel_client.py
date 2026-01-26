
import requests
import json
from datetime import datetime
from typing import List, Dict, Any

class FanDuelAPIClient:
    """
    Direct API Client for FanDuel Sportsbook.
    Uses headers extracted from browser session to fetch bet history.
    """
    
    BASE_URL = "https://api.sportsbook.fanduel.com/sbapi/fetch-my-bets"
    
    def __init__(self, auth_token: str, app_version: str = "2.135.2", region: str = "OH"):
        self.auth_token = auth_token
        self.headers = {
            'accept': 'application/json',
            'accept-language': 'en-US,en;q=0.9',
            'origin': f'https://{region.lower()}.sportsbook.fanduel.com',
            'referer': f'https://{region.lower()}.sportsbook.fanduel.com/',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
            'x-app-version': app_version,
            'x-application': 'FhMFpcPWXMeyZxOx', # App Key seems static
            'x-authentication': auth_token,
            'x-sportsbook-region': region
        }

    def fetch_bets(self, from_record=1, to_record=50) -> List[Dict]:
        """
        Fetches settled bets from the API.
        """
        params = {
            'isSettled': 'true',
            'fromRecord': from_record,
            'toRecord': to_record,
            'sortDir': 'DESC',
            'sortParam': 'SETTLEMENT_DATE',
            'adaptiveTokenEnabled': 'false',
            '_ak': 'FhMFpcPWXMeyZxOx'
        }
        
        try:
            response = requests.get(self.BASE_URL, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            return self._parse_api_response(data)
        except Exception as e:
            print(f"[FanDuelAPI] Error: {e}")
            if hasattr(e, 'response') and e.response:
                print(e.response.text)
            return []

    def _parse_api_response(self, data: Dict) -> List[Dict]:
        """
        Parses the JSON response into our standard Bet format.
        """
        if not data or 'bets' not in data:
            return []
            
        parsed_bets = []
        for bet in data.get('bets', []):
            try:
                # Extract fields
                # Date: 2026-01-25T00:18:46.000Z
                date_raw = bet.get('placedDate')
                if isinstance(date_raw, str):
                    # Handle Z if needed (Python < 3.11 might need replace, but 3.13 is fine. Let's be safe)
                    date_obj = datetime.fromisoformat(date_raw.replace('Z', '+00:00'))
                    date_str = date_obj.strftime('%Y-%m-%d')
                else:
                    # Fallback for timestamp
                    placed_ts = int(date_raw or 0)
                    date_str = datetime.fromtimestamp(placed_ts / 1000).strftime('%Y-%m-%d')
                
                # Wager & Payout
                stake = float(bet.get('betPrice', 0))
                
                # Payout might be 'payout', 'winnings', or inferred
                # In the debug, 'originalPotentialWin' was seen.
                # If result is LOSS, payout is 0.
                payout = float(bet.get('payout', 0))
                # Fallback if payout keys are weird or missing on Wins
                # But mostly we care about profit.
                
                profit = payout - stake
                
                # Status
                # "settledResult": "WIN", "LOSS"
                result = bet.get('settledResult', 'UNKNOWN')
                status = "LOST"
                if result == "WIN":
                    status = "WON"
                elif result == "VOID":
                    status = "VOID"
                elif result == "CASHOUT":
                    status = "WON" # Realized
                    
                # Description
                bet_type = bet.get('betType', 'Straight')
                
                descriptions = []
                sport = "Unknown"
                
                # Legs -> Parts
                legs = bet.get('legs', [])
                for leg in legs:
                    parts = leg.get('parts', [])
                    for part in parts:
                        sel_name = part.get('selectionName', '')
                        market_name = part.get('eventMarketDescription', '')
                        event_name = part.get('eventDescription', '')
                        
                        desc_str = f"{sel_name} ({market_name})"
                        descriptions.append(desc_str)
                        
                        # Infer Sport from competitionName
                        comp = part.get('competitionName', '').lower()
                        if 'ufc' in comp or 'mma' in comp: sport = 'MMA'
                        elif 'nfl' in comp: sport = 'NFL'
                        elif 'nba' in comp: sport = 'NBA'
                        elif 'college basketball' in comp: sport = 'NCAAM'
                        elif 'college football' in comp: sport = 'NCAAF'
                        elif 'mlb' in comp: sport = 'MLB'
                        elif 'nhl' in comp: sport = 'NHL'
                
                full_desc = " | ".join(descriptions)
                if not full_desc:
                    full_desc = f"{bet_type} (No legs found)"
                
                bet_obj = {
                    "provider": "FanDuel",
                    "date": date_str,
                    "sport": sport,
                    "bet_type": bet_type,
                    "wager": stake,
                    "profit": profit,
                    "status": status,
                    "description": full_desc, # Short summary
                    "selection": full_desc,
                    "odds": bet.get('odds', {}).get('american', 0), # Might be deeper
                    "is_live": False, # TODO check flags
                    "is_bonus": bet.get('isBonus', False),
                    "raw_text": str(bet) # Storing full JSON as raw for debug
                }
                
                parsed_bets.append(bet_obj)
            except Exception as e:
                print(f"Failed to parse bet: {e}")
                
        return parsed_bets
