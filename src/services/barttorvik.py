import requests
import json
from datetime import datetime
from src.database import upsert_bt_team_metrics_daily

# NOTE: Do NOT import selenium / undetected_chromedriver at import-time.
# Vercel/serverless Python often lacks distutils/Chrome and will crash.
# If we ever need a selenium fallback, we import it lazily inside the fallback block.

class BartTorvikClient:
    """
    Serverless Client for BartTorvik.com Data.
    Uses JSON endpoints exclusively.
    """
    
    BASE_URL = "https://barttorvik.com"

    def fetch_daily_projections(self, date_str: str = None) -> dict:
        """
        Fetches projections using the hidden JSON parameter.
        URL: https://barttorvik.com/schedule.php?date=YYYYMMDD&json=1
        """
        if not date_str:
            date_str = datetime.now().strftime("%Y%m%d")
            
        url = f"{self.BASE_URL}/schedule.php?date={date_str}&json=1"
        print(f"  [TORVIK] Fetching daily projections from {url}...")
        
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            # data is a list of lists or list of dicts? usually list of dicts or objects in JS var.
            # actually users say &json=1 returns raw JSON list.
            try:
                data = resp.json()
            except:
                # Fallback: Sometimes it might wrap in HTML or text?
                print("  [TORVIK] Response was not pure JSON, checking content...")
                data = None
            
            projections = {}
            if not data:
                # Let it fall through to Selenium Logic below
                pass
            else:
                for item in data:
                    # Structure of JSON items for schedule.php?json=1
                    # typically: {'away': 'Team A', 'home': 'Team B', 't_rank_line': '-5', ...}
                    # Let's handle generic fields based on common Torvik patterns
                    
                    away = item.get('away', item.get('team_away', ''))
                    home = item.get('home', item.get('team_home', ''))
                    line = item.get('line', item.get('t_rank_line', 0))
                    total = item.get('total', 0)
                    
                    if not away or not home: continue
                    
                    proj_data = {
                        "opponent": home,
                        "total": float(total) if total else 0.0,
                        "projected_score": f"{item.get('score_away')}-{item.get('score_home')}", # Post game or proj?
                        "spread": float(line) if line else 0.0,
                        "raw_line": str(line)
                    }
                    
                    projections[away] = {**proj_data, "opponent": home, "team": away}
                    projections[home] = {**proj_data, "opponent": away, "team": home}
                
            if not projections:
                # Serverless-safe: do NOT attempt selenium fallback by default.
                # BartTorvik frequently blocks automation; on Vercel we prefer to fail fast.
                print("  [TORVIK] Requests failed or blocked. No Selenium fallback in serverless.")
                return {}
            return projections

        except Exception as e:
            print(f"  [TORVIK] Fetch Error: {e}")
            return {}

    def get_efficiency_ratings(self, year: int = 2026):
        """
        Fetches 2026_team_results.json for efficiency metrics.
        Returns dict and optionally optionally persists to DB.
        """
        url = f"{self.BASE_URL}/{year}_team_results.json"
        print(f"  [TORVIK] Fetching Efficiency Ratings from {url}...")
        
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            # Handle potential HTML response
            try:
                data = resp.json()
            except:
                print("  [TORVIK] Ratings response was not JSON.")
                return {}
            
            ratings = {}
            metrics_payload = []
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            for row in data:
                # Indices:
                # 1: Name
                # 4: AdjOE
                # 6: AdjDE
                # Tempo is harder, usually dynamic index. 
                # Known indices for 2024/25:
                # 0: Rk, 1: Team, 2: Conf, 3: Record, 
                # 4: AdjOE, 5: Rank, 6: AdjDE, 7: Rank,
                # 8: Barthag, 9: Rank, 
                # ...
                # 21: Adj T, 22: Rank? Or 
                # Let's inspect typical row length or use heuristic again.
                # Actually, index 21/22 is typically Tempo.
                
                name = row[1]
                adj_oe = float(row[4])
                adj_de = float(row[6])
                
                # Heuristic for Tempo: Look for value ~60-80 around index 20-25
                tempo = 68.0
                for idx in range(20, 26):
                    try:
                        val = float(row[idx])
                        if 55.0 < val < 85.0:
                            tempo = val
                            break
                    except:
                        continue
                
                ratings[name] = {
                    "off_rating": adj_oe,
                    "def_rating": adj_de,
                    "tempo": tempo,
                    "efg_off": None,
                    "efg_def": None,
                    "to_off": None,
                    "to_def": None,
                    "or_off": None,
                    "or_def": None,
                    "ftr_off": None,
                    "ftr_def": None
                }
                
                metrics_payload.append({
                    "team_text": name,
                    "date": today_str,
                    "adj_off": adj_oe,
                    "adj_def": adj_de,
                    "adj_tempo": tempo,
                    "efg_off": None,
                    "efg_def": None,
                    "to_off": None,
                    "to_def": None,
                    "or_off": None,
                    "or_def": None,
                    "ftr_off": None,
                    "ftr_def": None
                })
            
            # Persist to DB
            if metrics_payload:
                try:
                    upsert_bt_team_metrics_daily(metrics_payload)
                    print(f"  [TORVIK] Persisted {len(metrics_payload)} team metrics to DB.")
                except Exception as db_e:
                    print(f"  [TORVIK] DB Persist warning: {db_e}")
            
            return ratings
            
        except Exception as e:
            print(f"  [TORVIK] Error fetching ratings: {e}")
            return {}
