import os
import json
from datetime import datetime, timedelta
import hashlib

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from src.database import get_db_connection, _exec

class ProfileGeneratorService:
    """
    Generates rich March Madness Team Profiles by aggregating 
    KenPom, Torvik, and NCAA NET ratings, and utilizing an LLM 
    to synthesize tactical scouting reports and player metrics.
    """
    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.client = None
        if self.api_key and OpenAI:
            self.client = OpenAI(api_key=self.api_key)
        self.model = "gpt-4-turbo-preview"

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

    def generate_profile(self, team_name: str) -> dict:
        """
        Main entry point. Fetches DB stats, and if no cached LLM narrative/roster exists, 
        generates one using current aggregated stats.
        """
        # 1. Check Cache
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
            }
        }
        
        if raw_data.get("torvik"):
            # Estimate Barthag or just pass raw ratings
            profile["torvik"]["adj_off"] = raw_data["torvik"].get("adj_off")
            profile["torvik"]["adj_def"] = raw_data["torvik"].get("adj_def")
            # Usually barthag isn't directly in the daily table, but we can compute it if needed
            # For now just use an estimated win% based on eff margin
            margin = (raw_data["torvik"].get("adj_off", 100) - raw_data["torvik"].get("adj_def", 100))
            profile["torvik"]["barthag"] = min(0.99, max(0.01, 0.5 + (margin * 0.02)))

        # 4. Generate Narrative & Player Stats via LLM
        prompt = f"""
        You are a sharp, analytical college basketball betting scout.
        
        Team: {team_name}
        Current Profile: {json.dumps(profile["metrics"])}
        NET/Quads: {json.dumps(profile["resume"])}
        
        Task:
        1. Generate exactly 6 players for their current top 6 rotation. Include their position, a completely factual current descriptive role, and factual current season per-game stats ("PPG | RPG" or "PPG | APG"). Emulate KenPom advanced stats like ORtg, Usg%, eFG%, and Min% realistically for these players based on their identity.
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

        if not self.api_key or not self.client:
            print("[ProfileGen] No API Key. Using generic fallback.")
            profile["narrative"] = {
                "summary": f"{team_name} plays a standard brand of college basketball. They execute well in the half-court but can occasionally go cold from outside.",
                "offense": ["Picks and rolls", "Spot up shooting", "Offensive rebounding"],
                "defense": ["Drop coverage against ball screens", "Switching 1 through 4", "Good defensive rebounding"],
                "upsetFlags": "High reliance on three pointers can lead to variance-based losses."
            }
            profile["players"] = [
                {"name": "Player 1", "pos": "G", "role": "Lead guard", "stats": "12.0 PPG | 4.0 APG", "adv": {"ortg": 105.0, "usg": 22.0, "min": 75.0, "efg": 50.0}},
                {"name": "Player 2", "pos": "F", "role": "Scoring wing", "stats": "14.5 PPG | 5.0 RPG", "adv": {"ortg": 110.0, "usg": 24.0, "min": 80.0, "efg": 54.0}},
                {"name": "Player 3", "pos": "C", "role": "Rim protector", "stats": "10.0 PPG | 8.0 RPG", "adv": {"ortg": 115.0, "usg": 18.0, "min": 60.0, "efg": 60.0}},
                {"name": "Player 4", "pos": "G", "role": "Shooter", "stats": "9.0 PPG | 2.0 APG", "adv": {"ortg": 108.0, "usg": 15.0, "min": 65.0, "efg": 58.0}},
                {"name": "Player 5", "pos": "F", "role": "Energy guy", "stats": "7.0 PPG | 6.0 RPG", "adv": {"ortg": 102.0, "usg": 14.0, "min": 55.0, "efg": 48.0}},
                {"name": "Player 6", "pos": "G", "role": "Backup point", "stats": "5.0 PPG | 3.0 APG", "adv": {"ortg": 100.0, "usg": 16.0, "min": 40.0, "efg": 45.0}}
            ]
        else:
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
                result = json.loads(response.choices[0].message.content)
                profile["narrative"] = result["narrative"]
                profile["players"] = result["players"]
            except Exception as e:
                print(f"[ProfileGen] LLM Error: {e}")
                # Fallback on LLM failure
                profile["narrative"] = {"summary": "Data unavailable.", "offense": [], "defense": [], "upsetFlags": ""}
                profile["players"] = []

        # 5. Save to Cache
        self.save_cached_profile(team_name, profile)
        return profile

if __name__ == "__main__":
    from pprint import pprint
    svc = ProfileGeneratorService()
    profile = svc.generate_profile("Connecticut")
    print("Generated Profile:")
    pprint(profile)
