import os
import json
from datetime import datetime, timedelta
import hashlib

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

from src.database import get_db_connection, _exec
from src.services.kenpom_client import KenPomClient

class ProfileGeneratorService:
    """
    Generates rich March Madness Team Profiles by aggregating 
    KenPom, Torvik, and NCAA NET ratings, and utilizing an LLM 
    to synthesize tactical scouting reports and player metrics.
    """
    def __init__(self):
        self.gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        
        self.client = None
        if self.openai_key and OpenAI:
            self.client = OpenAI(api_key=self.openai_key)
        
        if self.gemini_key and genai:
            genai.configure(api_key=self.gemini_key)
            self.gemini_model = genai.GenerativeModel('gemini-2.5-flash-lite')
        else:
            self.gemini_model = None

        self.model = "gpt-4-turbo-preview"
        self.kp_client = KenPomClient()

    def aggregate_team_data(self, team_name: str) -> dict:
        """Fetch all raw stats for a team from the DB."""
        data = {
            "team_name": team_name,
            "kenpom": None,
            "torvik": None,
            "net": None
        }

        with get_db_connection() as conn:
            # 1. KenPom
            kp_row = _exec(conn, "SELECT * FROM kenpom_ratings WHERE team_name ILIKE %s LIMIT 1", (f"%{team_name}%",)).fetchone()
            if kp_row:
                data["kenpom"] = dict(kp_row)
            
            # 2. Torvik (Check generic metrics)
            # Torvik data might have a slightly different name format. Let's do ILIKE
            bt_row = _exec(conn, "SELECT * FROM bt_team_metrics_daily WHERE team_text ILIKE %s ORDER BY date DESC LIMIT 1", (f"%{team_name}%",)).fetchone()
            if bt_row:
                data["torvik"] = dict(bt_row)
            
            # 3. NET Rankings
            net_team_name = team_name
            net_overrides = {
                "Connecticut": "UConn",
                "Miami FL": "Miami (FL)",
                "N.C. State": "NC State"
            }
            if team_name in net_overrides:
                net_team_name = net_overrides[team_name]
            
            # Use exact match if we mapped it, else ILIKE
            if net_team_name != team_name:
                net_row = _exec(conn, "SELECT * FROM ncaam_net_rankings WHERE team_name = %s LIMIT 1", (net_team_name,)).fetchone()
            else:
                net_row = _exec(conn, "SELECT * FROM ncaam_net_rankings WHERE team_name ILIKE %s LIMIT 1", (f"%{team_name}%",)).fetchone()
                
            if net_row:
                data["net"] = dict(net_row)

        return data

    def get_cached_profile(self, team_name: str) -> dict:
        """Check if an LLM profile was already generated recently."""
        with get_db_connection() as conn:
            # Make sure table exists
            _exec(conn, """
                CREATE TABLE IF NOT EXISTS ncaam_team_profiles (
                    team_name TEXT PRIMARY KEY,
                    profile_json JSONB,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

            row = _exec(conn, "SELECT profile_json, updated_at FROM ncaam_team_profiles WHERE team_name = %s", (team_name,)).fetchone()
            if row:
                # Cache for 24 hours
                if (datetime.now() - row['updated_at']).total_seconds() < 86400:
                    return row['profile_json']
        return None

    def save_cached_profile(self, team_name: str, profile: dict):
        with get_db_connection() as conn:
            _exec(conn, """
                INSERT INTO ncaam_team_profiles (team_name, profile_json, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (team_name) 
                DO UPDATE SET profile_json = EXCLUDED.profile_json, updated_at = CURRENT_TIMESTAMP
            """, (team_name, json.dumps(profile)))
            conn.commit()

    def generate_profile(self, team_name: str, force_refresh: bool = False) -> dict:
        """
        Main entry point. Fetches DB stats, and if no cached LLM narrative/roster exists, 
        generates one using current aggregated stats.
        """
        # 1. Check Cache
        if not force_refresh:
            cached = self.get_cached_profile(team_name)
            if cached:
                return cached

        # 2. Extract Data
        raw_data = self.aggregate_team_data(team_name)
        
        # 3. Build Resume & Stats Block (Factual from DB)
        profile = {
            "team_name": raw_data["net"]["team_name"] if raw_data.get("net") else team_name,
            "kenpom_rank": raw_data["kenpom"]["rank"] if raw_data.get("kenpom") else None,
            "net": raw_data["net"]["rank"] if raw_data.get("net") else None,
            "record": raw_data["net"]["record"] if raw_data.get("net") else "0-0",
            "torvik": {},
            "resume": {
                "records": {
                    "overall": raw_data["net"]["record"] if raw_data.get("net") else "0-0",
                    "home": raw_data["net"]["home"] if raw_data.get("net") else "0-0",
                    "away": raw_data["net"]["road"] if raw_data.get("net") else "0-0",
                    "neutral": raw_data["net"]["neutral"] if raw_data.get("net") else "0-0"
                },
                "quads": {
                    "q1": raw_data["net"]["quad1"] if raw_data.get("net") else "0-0",
                    "q2": raw_data["net"]["quad2"] if raw_data.get("net") else "0-0",
                    "q3": raw_data["net"]["quad3"] if raw_data.get("net") else "0-0",
                    "q4": raw_data["net"]["quad4"] if raw_data.get("net") else "0-0"
                }
            },
            "metrics": {
                "adjO": raw_data["kenpom"]["adj_o"] if raw_data.get("kenpom") else None,
                "adjD": raw_data["kenpom"]["adj_d"] if raw_data.get("kenpom") else None,
                "tempo": raw_data["kenpom"]["adj_t"] if raw_data.get("kenpom") else None,
            },
            "players": []
        }
        
        # Pull real player stats if available (sorted by playing time/rank)
        real_players = []
        
        # Load from our offline static master repo First (guarantees 2026 accuracy and 100% uptime)
        try:
            with open("data/static/master_rosters_2026.json", "r") as f:
                master_data = json.load(f)
                if team_name in master_data:
                    real_players = master_data[team_name]
        except Exception as e:
            pass

        if not real_players:
            import logging
            logging.info(f"[ProfileGen] Offline Master missing {team_name}, falling back to KenPom DB.")
            # Fallback to Database KenPom
            real_players = self.kp_client.get_player_stats_for_team(team_name, limit=12)
            def get_min(p):
                m = p.get('metrics', {}).get('cols', [])
                h = p.get('metrics', {}).get('headers', [])
                try:
                    idx = next(i for i, x in enumerate(h) if 'min' in x.lower())
                    return float(str(m[idx]).replace('%',''))
                except:
                    return 0
            
            real_players = sorted(real_players, key=get_min, reverse=True)[:6]


        # 4. Generate Narrative & Player Stats via LLM
        prompt = f"""
        You are a sharp, analytical college basketball betting scout.
        
        Season context: 2025-26 Season (Current)
        Team: {team_name}
        Current Profile: {json.dumps(profile["metrics"])}
        NET/Quads: {json.dumps(profile["resume"])}
        Available Real Player Stats: {json.dumps(real_players)}
        
        Task:
        1. Process the 'Available Real Player Stats' for the EXCLUSIVE context of the 2025-26 season. For the top 6 players found, use their REAL names and metrics. Include their position, a completely factual current descriptive role for the 2025-2026 season, and factual current season per-game stats. If specific per-game stats are missing, estimate them based on their advanced profile, but KEEP NAMES FACTUAL.
        2. Generate a 'narrative' object containing a 2-sentence scout summary, an array of exactly 3 bullet points for 'offense' (e.g., scheme, pace, strengths), an array of exactly 3 bullet points for 'defense' (e.g., coverage type, rim protection), and a 1-sentence 'upsetFlags' highlighting an exact schematic vulnerability.
        
        Output MUST be pure JSON fitting this strict schema:
        {{
            "narrative": {{
                "summary": "string",
                "offense": ["string", "string", "string"],
                "defense": ["string", "string", "string"],
                "upsetFlags": "string"
            }},
            "players": [
                {{
                    "name": "string",
                    "pos": "string",
                    "role": "string",
                    "stats": "15.0 PPG | 5.0 APG",
                    "adv": {{ "ortg": 110.5, "usg": 24.5, "min": 80.0, "efg": 52.5 }}
                }}
            ]
        }}
        """

        result_json = None
        
        # Try OpenAI First
        if self.openai_key and self.client:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are an elite college basketball data journalist."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2
                )
                result_json = json.loads(response.choices[0].message.content)
            except Exception as e:
                print(f"[ProfileGen] OpenAI Error: {e}")

        # Fallback to Gemini
        if not result_json and self.gemini_model:
            print(f"[ProfileGen] Using Gemini fallback for {team_name}...")
            try:
                # Gemini prompt needs slightly different handling for JSON
                gemini_prompt = prompt + "\n\nIMPORTANT: Return ONLY a valid JSON object. No markdown, no triple backticks."
                
                response = self.gemini_model.generate_content(gemini_prompt, request_options={"timeout": 60})
                text = response.text.strip()
                
                # Clean up markdown if present
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()
                
                result_json = json.loads(text)
            except Exception as e:
                print(f"[ProfileGen] Gemini Error: {e}")

        if result_json:
            profile["narrative"] = result_json.get("narrative")
            profile["players"] = result_json.get("players")
        else:
            # Absolute Fallback
            print(f"[ProfileGen] All LLMs failed for {team_name}. Using descriptive placeholder.")
            profile["narrative"] = {
                "summary": f"{team_name} is a high-major program known for their disciplined execution and tactical depth.",
                "offense": ["Heavy ball-screen usage", "Excellent floor spacing", "Strong offensive rebounding concentration"],
                "defense": ["No-middle defensive principle", "High pressure on ball handlers", "Elite rim protection"],
                "upsetFlags": "Vulnerable to high-variance 3-point shooting teams if perimeter rotations lag."
            }
            # If no real players, use generic list
            if not real_players:
                profile["players"] = [
                    {"name": "Lead Guard", "pos": "G", "role": "Primary Facilitator", "stats": "14.2 PPG | 5.4 APG", "adv": {"ortg": 108.2, "usg": 24.5, "min": 82.0, "efg": 51.5}},
                    {"name": "Scoring Wing", "pos": "F", "role": "Versatile Scorer", "stats": "16.5 PPG | 4.8 RPG", "adv": {"ortg": 112.5, "usg": 22.0, "min": 78.0, "efg": 54.2}},
                    {"name": "Big Man", "pos": "C", "role": "Rim Protector", "stats": "10.8 PPG | 9.2 RPG", "adv": {"ortg": 115.0, "usg": 18.5, "min": 65.0, "efg": 62.1}},
                    {"name": "Glue Guy", "pos": "F", "role": "Defensive Stopper", "stats": "8.4 PPG | 6.2 RPG", "adv": {"ortg": 105.4, "usg": 15.2, "min": 72.0, "efg": 48.9}},
                    {"name": "Sharpshooter", "pos": "G", "role": "3pt Specialist", "stats": "11.2 PPG | 2.1 RPG", "adv": {"ortg": 118.2, "usg": 14.8, "min": 60.0, "efg": 58.5}},
                    {"name": "Sixth Man", "pos": "G", "role": "Spark Plug", "stats": "9.5 PPG | 3.2 APG", "adv": {"ortg": 102.1, "usg": 21.4, "min": 45.0, "efg": 46.8}}
                ]
            else:
                # We have real players but no AI narrative, let's at least show the real names
                profile["players"] = []
                for p in real_players[:6]:
                    def get_metric(player, header_fragment, default=0):
                        m = player.get('metrics', {}).get('cols', [])
                        h = player.get('metrics', {}).get('headers', [])
                        try:
                            idx = next(i for i, x in enumerate(h) if header_fragment.lower() in str(x).lower())
                            val = str(m[idx]).replace('%', '')
                            if val.replace('.', '', 1).isdigit():
                                return float(val)
                            return float(val) if val else default
                        except:
                            return default
                            
                    profile["players"].append({
                        "name": p.get('name', p.get('player_name', 'Unknown')),
                        "pos": "TBD", 
                        "role": "Key Rotation Player", 
                        "stats": "Stats Pending", 
                        "adv": {
                            "ortg": get_metric(p, 'o-rat', 0) or get_metric(p, 'ortg', 0), 
                            "usg": get_metric(p, 'usag', 0) or get_metric(p, 'usg', 0), 
                            "min": get_metric(p, 'min', 0), 
                            "efg": get_metric(p, 'efg', 0)
                        }
                    })

        # 5. Save to Cache
        self.save_cached_profile(team_name, profile)
        return profile

    def generate_matchup_analysis(self, team_a: str, team_b: str) -> dict:
        """
        Loads the generated profiles for both teams and generates a tactical
        head-to-head matchup analysis using the LLM.
        """
        profile_a = self.generate_profile(team_a)
        profile_b = self.generate_profile(team_b)
        
        prompt = f"""
        You are a sharp, analytical college basketball betting scout.
        
        Task: Provide a detailed, tactical head-to-head analysis between Team A ({team_a}) and Team B ({team_b}) for the 2025-26 season.
        
        Team A Profile: {json.dumps(profile_a.get('metrics', {}))} - NET: {profile_a.get('net')}
        Team A Tactics: {json.dumps(profile_a.get('narrative', {}))}

        Team B Profile: {json.dumps(profile_b.get('metrics', {}))} - NET: {profile_b.get('net')}
        Team B Tactics: {json.dumps(profile_b.get('narrative', {}))}
        
        Output MUST be pure JSON fitting this strict schema:
        {{
            "predicted_winner": "Team Name (e.g. Duke)",
            "confidence": "High/Medium/Low",
            "summary": "1-2 sentence overall tactical summary.",
            "team_a_advantages": ["Advantage 1", "Advantage 2"],
            "team_b_advantages": ["Advantage 1", "Advantage 2"],
            "key_matchup": "Description of the deciding positional or schematic battle"
        }}
        """

        result_json = None
        
        # Try OpenAI First
        if self.openai_key and self.client:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are an elite college basketball data journalist."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2
                )
                result_json = json.loads(response.choices[0].message.content)
            except Exception as e:
                print(f"[MatchupGen] OpenAI Error: {e}")

        # Fallback to Gemini
        if not result_json and self.gemini_model:
            print(f"[MatchupGen] Using Gemini fallback for {team_a} vs {team_b}...")
            try:
                gemini_prompt = prompt + "\n\nIMPORTANT: Return ONLY a valid JSON object. No markdown, no triple backticks."
                
                response = self.gemini_model.generate_content(gemini_prompt, request_options={"timeout": 60})
                text = response.text.strip()

                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()
                
                result_json = json.loads(text)
            except Exception as e:
                print(f"[MatchupGen] Gemini Error: {e}")
                
        if not result_json:
            result_json = {
                "predicted_winner": "TBD",
                "confidence": "Low",
                "summary": "Matchup analysis currently unavailable due to AI service disruption.",
                "team_a_advantages": [f"{team_a} overall efficiency"],
                "team_b_advantages": [f"{team_b} overall efficiency"],
                "key_matchup": "Tempo vs Execution"
            }
            
        return result_json

if __name__ == "__main__":
    from pprint import pprint
    svc = ProfileGeneratorService()
    profile = svc.generate_profile("Connecticut")
    print("Generated Profile:")
    pprint(profile)
