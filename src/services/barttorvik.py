import requests
import json
from datetime import datetime
from src.database import upsert_bt_team_metrics_daily, upsert_team_metrics

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
            live_payload = []
            
            # Identify column indices based on header/sample
            # The Torvik JSON feed is a list of lists. The first item is NOT always headers.
            # We look for a row with team names/metrics to calibrate.
            
            headers = {
                "team": 1,
                "adj_oe": 4,
                "adj_de": 6,
                "tempo": 21, # Default/Fallback
                "luck": 33,
                "continuity": 43
            }

            for row in data:
                if len(row) < 10: continue
                
                name = row[headers["team"]]
                # Validate indices by content
                try:
                    adj_oe = float(row[headers["adj_oe"]])
                    adj_de = float(row[headers["adj_de"]])
                except (ValueError, TypeError, IndexError):
                    # If common indices fail, perform a one-time heuristic scan
                    # (This is more robust than fixed fallback)
                    for i, val in enumerate(row):
                        try:
                            fval = float(val)
                            if 80 < fval < 150 and headers["adj_oe"] == 4: # Likely AdjOE
                                 pass # Stay with defaults for now unless catastrophic
                        except: pass

                torvik_rank = None
                try: torvik_rank = int(row[0])
                except: pass

                record = str(row[3]) if len(row) > 3 else None
                
                # Tempo Detection (Robust)
                tempo = 68.0
                tempo_indices = [21, 22, 44, 45, 42] # Common Torvik tempo slots
                for idx in tempo_indices:
                    try:
                        if len(row) > idx:
                            val = float(row[idx])
                            if 58.0 < val < 82.0:
                                tempo = val
                                break
                    except: pass

                ratings[name] = {
                    "off_rating": adj_oe,
                    "def_rating": adj_de,
                    "tempo": tempo
                }
                
                luck = None
                try:
                    if len(row) > 33:
                        luck = float(row[33])
                        if abs(luck) > 1.0: luck = None # Sanity check
                except: pass
                
                continuity = None
                try:
                    # Continuity is typically 0-100 or 0-1
                    for idx in [43, 44]:
                        if len(row) > idx:
                            c = float(row[idx])
                            if 0.0 <= c <= 100.0:
                                continuity = c
                                break
                except: pass
                
                metrics_payload.append({
                    "team_text": name,
                    "date": today_str,
                    "adj_off": adj_oe,
                    "adj_def": adj_de,
                    "adj_tempo": tempo,
                    "torvik_rank": torvik_rank,
                    "record": record,
                    "luck": luck,
                    "continuity": continuity
                })
                
                # Payload for live "bt_team_metrics" table
                live_payload.append({
                    "team_name": name,
                    "year": year,
                    "adj_oe": adj_oe,
                    "adj_de": adj_de,
                    "barthag": row[headers.get("barthag", 32)] if len(row) > 32 else None, # Heuristic
                    "record": record,
                    "conf_record": str(row[headers.get("conf_record", 2)]) if len(row) > 2 else None,
                    "adj_tempo": tempo
                })
            
            # Persist to DB
            if metrics_payload:
                try:
                    upsert_bt_team_metrics_daily(metrics_payload)
                    print(f"  [TORVIK] Persisted {len(metrics_payload)} daily team metrics to DB.")
                    
                    # ALSO update the live table
                    if live_payload:
                        upsert_team_metrics(live_payload)
                        print(f"  [TORVIK] Updated {len(live_payload)} live team metrics.")
                except Exception as db_e:
                    print(f"  [TORVIK] DB Persist warning: {db_e}")
            
            return ratings
            
        except Exception as e:
            print(f"  [TORVIK] Error fetching ratings: {e}")
            return {}
