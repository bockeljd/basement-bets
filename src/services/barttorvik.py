import pandas as pd
import re
from datetime import datetime
import time
from io import StringIO
from io import StringIO
from src.database import insert_player_stats

class BartTorvikClient:
    """
    Scrapes daily projections from BartTorvik.com using Selenium
    URL: https://barttorvik.com/schedule.php?date=YYYYMMDD
    """
    
    BASE_URL = "https://barttorvik.com/schedule.php"

    def fetch_daily_projections(self, date_str: str = None) -> dict:
        """
        Fetches projections for a specific date (YYYYMMDD).
        """
        if not date_str:
            date_str = datetime.now().strftime("%Y%m%d")
            
        url = f"{self.BASE_URL}?date={date_str}&conlimit="
        print(f"  [TORVIK] Fetching daily stats from {url} via Selenium...")
        
        driver = SeleniumDriverFactory.create_driver(headless=True)
        if not driver:
            print("  [TORVIK] Failed to init Selenium driver.")
            return {}

        try:
            driver.get(url)
            # Wait for JS challenge/redirect
            time.sleep(5) 
            
            html = driver.page_source
            
            # Parse Tables
            try:
                dfs = pd.read_html(StringIO(html))
            except ValueError:
                print(f"  [TORVIK] ValueError parsing tables.")
                return {}
            
            if not dfs:
                print("  [TORVIK] No tables found.")
                return {}
                
            df = dfs[0]
            
            projections = {}
            print(f"  [TORVIK] Processing {len(df)} rows...")
            
            for _, row in df.iterrows():
                try:
                    matchup_raw = str(row.get('Matchup', ''))
                    line_raw = str(row.get('T-Rank Line', ''))
                    
                    if 'at' not in matchup_raw: continue
                    
                    # Parse Matchup: "6 Iowa St. at 18 Kansas ESPN"
                    parts = matchup_raw.split(' at ')
                    if len(parts) != 2: continue
                    
                    away_part = parts[0]
                    home_part = parts[1]
                    
                    # Clean names
                    away_team = re.sub(r'^\d+\s+', '', away_part).strip()
                    
                    # Remove trailing TV station
                    tv_stations = ['ESPN', 'ESPN2', 'ESPNU', 'FS1', 'FS2', 'FOX', 'CBS', 'CBSSN', 'ACCN', 'SECN', 'BTN', 'PAC12', 'PEACOCK', 'CW', 'TRU']
                    for tv in tv_stations:
                        if home_part.endswith(tv):
                            home_part = home_part.replace(tv, '').strip()
                        if home_part.endswith(tv + " "): # Handle spaces
                             home_part = home_part.replace(tv + " ", '').strip()
                    
                    home_team = re.sub(r'^\d+\s+', '', home_part).strip()
                    
                    # Parse Line: "Iowa St. -0.7 74-73 (53%)"
                    score_match = re.search(r'(\d+)-(\d+)', line_raw)
                    if not score_match: continue
                    
                    s1 = int(score_match.group(1))
                    s2 = int(score_match.group(2))
                    total = s1 + s2
                    
                    spread_val = 0.0
                    # Basic spread extraction logic if needed
                    # For now just reliable totals

                    data = {
                        "opponent": home_team,
                        "total": float(total),
                        "projected_score": f"{s1}-{s2}",
                        "spread": spread_val,
                        "raw_line": line_raw
                    }
                    
                    projections[away_team] = {**data, "opponent": home_team, "team": away_team}
                    projections[home_team] = {**data, "opponent": away_team, "team": home_team}
                    
                except Exception as e:
                    continue
                    
            print(f"  [TORVIK] Parsed {len(projections)} team projections.")
            return projections

        except Exception as e:
            print(f"  [TORVIK] Failed to fetch: {e}")
            return {}
        finally:
            driver.quit()

    def fetch_player_stats(self, year: int = 2026, start_date: str = '20250801', end_date: str = None) -> list:
        """
        Fetches player stats by extracting JSON data from script tags.
        """
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
            
        url = f"https://barttorvik.com/playerstat.php?link=y&minGP=1&year={year}&start={start_date}&end={end_date}"
        print(f"  [TORVIK] Fetching player stats from {url}...")
        
        url = f"https://barttorvik.com/playerstat.php?link=y&minGP=1&year={year}&start={start_date}&end={end_date}"
        print(f"  [TORVIK] Fetching player stats from {url}...")
        
        try:
            from src.selenium_client import SeleniumDriverFactory
            driver = SeleniumDriverFactory.create_driver(headless=True)
        except ImportError:
             print("  [TORVIK] Selenium not available.")
             return []

        if not driver: return []
        
        import json
        
        try:
            driver.get(url)
            time.sleep(5) 
            
            # Strategy: Regex scan all script tags for the data array
            # scripts = driver.find_elements(By.TAG_NAME, "script") 
            # Simplified: use page Source and regex on the whole HTML
            html = driver.page_source
            
            # DEBUG: Save source to inspect
            with open("torvik_source.html", "w") as f:
                f.write(html)
            print("  [TORVIK] Saved page source to torvik_source.html")
            
            # Pattern for massive 2D array: var X = [[...]];
            # We look for a 2D array starting with a number (Rank) or string
            # e.g., [[1, "Player Name", ...], [2, ...]]
            
            # Regex to find array of arrays
            # We'll enable dotall
            
            print(f"  [TORVIK] Scanning HTML (len={len(html)}) for JSON data...")
            
            stats_list = []
            
            # Helper to parse potential JSON
            def try_parse_stats(json_str):
                try:
                    data = json.loads(json_str)
                    if isinstance(data, list) and len(data) > 20 and isinstance(data[0], list):
                         return data
                    return None
                except:
                    return None

            # 1. Look for 'var pstats = ...' or similar assignments
            # Common markers in Torvik:
            matches = re.findall(r'(\w+)\s*=\s*(\[\[.*?\]\])', html, re.DOTALL)
            
            candidate_data = None
            
            for var_name, content in matches:
                 parsed = try_parse_stats(content)
                 if parsed:
                      print(f"    -> Found candidate variable '{var_name}' with {len(parsed)} rows.")
                      if len(parsed) > 0:
                          row0 = parsed[0]
                          print(f"      -> Sample Row 0: {row0}")
                          
                          # Heuristic: Check for player-like data (name string)
                          # Transfers array might be the main one?
                          if len(parsed) > 100:
                              candidate_data = parsed
                              print(f"      -> TENTATIVELY SELECTED '{var_name}'")
            
            if not candidate_data:
                print("  [TORVIK] No JSON data found via Regex.")
                return []
            
            # Process Data
            print(f"  [TORVIK] Processing {len(candidate_data)} rows...")
            today = datetime.now().strftime("%Y-%m-%d")
            
            for row in candidate_data:
                try:
                    # Check validity
                    if len(row) < 15: continue
                    
                    # Mapping (Indices are inferred from previous manual checks or standard format)
                    # 0: Rank (Int) or String
                    # 1: Player Name (HTML link usually? Or just name)
                    # 2: Team (HTML link?)
                    
                    # Torvik JSON usually has HTML in name/team fields: 
                    # '<a href="...">Name</a>'
                    
                    name_raw = str(row[1])
                    team_raw = str(row[2])
                    
                    # Strip HTML tags
                    name = re.sub(r'<[^>]+>', '', name_raw).strip()
                    team = re.sub(r'<[^>]+>', '', team_raw).strip()
                    
                    if not name or name == 'Player': continue
                    
                    # Check if row looks like stats
                    if not str(row[0]).isdigit() and row[0] != '-': 
                         # Maybe header row?
                         continue

                    # Helper for floats
                    def get_val(idx):
                        try:
                            val = str(row[idx])
                            val = re.sub(r'<[^>]+>', '', val) # remove tags
                            val = val.replace(',', '').replace('%', '')
                            if val == '' or val == '-': return 0.0
                            return float(val)
                        except:
                            return 0.0

                    # 4: GP, 5: MPG, ... 
                    # Validation: GP should be integer-like
                    
                    stats = {
                        "player_id": f"{name}_{team}", 
                        "name": name,
                        "team": team,
                        "date": today,
                        "games": int(get_val(4)),
                        "mpg": get_val(5),
                        "ortg": get_val(6),
                        "usg": get_val(7),
                        "efg": get_val(8),
                        "ts_pct": get_val(9),
                        "orb_pct": get_val(10),
                        "drb_pct": get_val(11),
                        "ast_pct": get_val(12),
                        "to_pct": get_val(13),
                        "blk_pct": get_val(14),
                        "stl_pct": get_val(15),
                        "ftr": get_val(16),
                        "pfr": get_val(17),
                        "three_p_pct": get_val(18),
                        "two_p_pct": get_val(19)
                    }
                    stats_list.append(stats)
                except Exception as e:
                    continue

            print(f"  [TORVIK] Parsed {len(stats_list)} valid player stats.")
            
            # Save to DB
            insert_player_stats(stats_list)
            
            return stats_list

        except Exception as e:
            print(f"  [TORVIK] Error fetching player stats: {e}")
            return []
        finally:
            driver.quit()

    def get_efficiency_ratings(self, year: int = 2026):
        """
        Fetches AdjOE, AdjDE, and Tempo from team_results.json.
        Indices (inferred):
        1: Name
        4: AdjOE
        6: AdjDE
        22: Tempo
        """
        url = f"https://barttorvik.com/{year}_team_results.json"
        print(f"  [TORVIK] Fetching Efficiency Ratings from {url}...")
        
        try:
            import requests
            resp = requests.get(url, verify=False)
            data = resp.json()
            
            ratings = {}
            for row in data:
                # [rank, name, conf, record, adjOE, ..., adjDE, ..., ..., tempo, ...]
                name = row[1]
                adj_oe = float(row[4])
                adj_de = float(row[6])
                
                # Heuristic for Tempo: Look for value between 55 and 85 in likely indices
                # Index 21, 22, 23?
                # Default to 68.0 if not found
                tempo = 68.0
                candidates = row[20:30] # Check a range
                for val in candidates:
                    try:
                        v = float(val)
                        if 55.0 < v < 85.0:
                            tempo = v
                            break
                    except:
                        pass
                
                # Manual override if index known (e.g. index 11? 27.5? No)
                # If we rely on generic 68.0, it's safer than 0.6.
                
                ratings[name] = {
                    "off_rating": adj_oe,
                    "def_rating": adj_de,
                    "tempo": tempo
                }
            
            return ratings
        except Exception as e:
            print(f"  [TORVIK] Error fetching ratings: {e}")
            return {}

    def get_team_volatility(self, year: int = 2026):
        """Return default volatility."""
        return {} 

if __name__ == "__main__":
    client = BartTorvikClient()
    # Test Projections
    # date = "20260113"
    # data = client.fetch_daily_projections(date)
    # print("Sample Data:", list(data.items())[:3])
    
    # Test Player Stats
    print("Testing Player Stats...")
    stats = client.fetch_player_stats()
    print("Sample Stats:", stats[:3] if stats else "None")
