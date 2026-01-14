import pandas as pd
import requests
import re
import json
import ssl
from datetime import datetime

# Bypass SSL if needed
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

class EPLService:
    """
    Service to fetch EPL advanced metrics (PPDA) from Understat.
    Manually parses JSON from script tags to avoid lxml/soccerdata dependency issues.
    """
    
    BASE_URL = "https://understat.com/league/EPL"
    
    def get_ppda_stats(self, season: str = None):
        """
        Fetches PPDA (Passes Allowed Per Defensive Action) stats for the current season.
        """
        if not season:
            season = "2024" # Understat uses start year.
            
        # Understat URL for specific season? e.g. /league/EPL/2024
        url = f"{self.BASE_URL}/{season}"
        print(f"  [EPL] Fetching PPDA stats from {url}...")
        
        try:
            resp = requests.get(url)
            if resp.status_code != 200:
                print(f"  [EPL] Failed to fetch page: {resp.status_code}")
                return pd.DataFrame()
                
            html = resp.text
            
            # Find the datesData or teamsData JSON
            # Pattern: var teamsData = JSON.parse('...');
            # Note: The JSON string inside parse is often hex/encoded? No, usually decoded.
            
            # Look for: var teamsData = JSON.parse('...');
            match = re.search(r"var teamsData\s*=\s*JSON\.parse\('([^']+)'\)", html)
            if not match:
                # Try double quotes
                match = re.search(r'var teamsData\s*=\s*JSON\.parse\("([^"]+)"\)', html)
                
            if not match:
                print("  [EPL] Could not find teamsData in script.")
                return pd.DataFrame()

            # The string might be hex-encoded: \x22 -> "
            json_str = match.group(1)
            # Python's string-escape or similar decoding
            # Actually, `json.loads` might handle standard escapes, but if it's hex escaped...
            # Browsers handle \x sequences. Python might need `literal_eval` or `codecs`.
            
            try:
                # Raw decode
                decoded_str = bytes(json_str, 'utf-8').decode('unicode_escape')
                data = json.loads(decoded_str)
            except:
                # If decode fails, try direct load
                try:
                    data = json.loads(json_str)
                except:
                    print("  [EPL] JSON decode failed.")
                    return pd.DataFrame()
            
            # Data structure: { "TeamID": { "id": "...", "title": "Arsenal", "history": [...], "ppda": 8.5? } }
            # Wait, inspection needed. Usually teamsData has aggregated stats or we sum from history.
            
            stats_list = []
            
            for team_id, team_data in data.items():
                title = team_data.get('title')
                history = team_data.get('history', [])
                
                # Calculate season PPDA
                total_ppda_allowed = 0
                total_def_actions = 0
                
                # Understat structure usually: history = [ { "ppda": {"att": X, "def": Y}, ... } ]
                # ppda_coeff = att / def
                
                att_sum = 0
                def_sum = 0
                
                for match in history:
                    ppda = match.get('ppda', {})
                    att = ppda.get('att', 0)
                    defn = ppda.get('def', 0)
                    att_sum += att
                    def_sum += defn
                
                if def_sum > 0:
                    season_ppda = att_sum / def_sum
                else:
                    season_ppda = 0.0
                    
                stats_list.append({
                    "team": title,
                    "ppda": round(season_ppda, 2),
                    "matches": len(history)
                })
                
            df = pd.DataFrame(stats_list)
            if not df.empty:
                df = df.sort_values('ppda', ascending=True) # Low PPDA = High Intensity
                
            return df

        except Exception as e:
            print(f"  [EPL] Error fetching stats: {e}")
            return pd.DataFrame()

    def get_luck_mismatches(self):
        """
        Returns teams with lowest PPDA (Pressing Monsters).
        """
        df = self.get_ppda_stats()
        if df.empty: return []
        
        # Take top 5 pressers
        return df.head(5).to_dict('records')

if __name__ == "__main__":
    svc = EPLService()
    print("Top 5 Pressing Teams (Low PPDA):")
    mismatches = svc.get_luck_mismatches()
    for m in mismatches:
        print(m)
