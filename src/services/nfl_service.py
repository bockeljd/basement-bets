import pandas as pd
from datetime import datetime
import ssl

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

class NFLService:
    """
    Service to fetch NFL Next Gen Stats and identify betting edges.
    Key Metrics: CPOE (Completion % Over Expected), Air Yards.
    """
    
    # NFLVerse data is hosted here
    NGS_URL_TEMPLATE = "https://github.com/nflverse/nflverse-data/releases/download/nextgen_stats/ngs_{year}_{stat_type}.csv.gz"
    GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
    PBP_URL_TEMPLATE = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{year}.csv.gz"

    def get_passing_ngs(self, year: int = None):
        if not year:
            year = datetime.now().year
            # Fallback for early 2026 -> use 2024 season (most recent complete)
            if datetime.now().month < 8: 
                year = 2024
        
        print(f"  [NFL] Fetching NGS Passing data for {year}...")
        try:
            url = self.NGS_URL_TEMPLATE.format(year=year, stat_type='passing')
            df = pd.read_csv(url, compression='gzip', low_memory=False)
            return df
        except Exception as e:
            print(f"  [NFL] Error fetching NGS data from {url}: {e}")
            return pd.DataFrame()
            
    def get_games_data(self, year: int = None):
        """Fetches games file for volatility calc."""
        if not year: year = 2024 # Default to latest full
        
        print(f"  [NFL] Fetching Games data from {self.GAMES_URL}...")
        try:
            df = pd.read_csv(self.GAMES_URL, low_memory=False)
            df = df[df['season'] == year]
            print(f"  [NFL] Games found for {year}: {len(df)}")
            return df
        except Exception as e:
            print(f"  [NFL] Error fetching Games data: {e}")
            return pd.DataFrame()
            
    def get_team_volatility(self, year=2024, window=10):
        """
        Calculates Standard Deviation of points scored over last X games.
        """
        games = self.get_games_data(year)
        if games.empty: return {}
        
        # Melt to get team-level scores
        # Cols: home_team, away_team, home_score, away_score, week
        home_df = games[['week', 'home_team', 'home_score']].rename(columns={'home_team': 'team', 'home_score': 'score'})
        away_df = games[['week', 'away_team', 'away_score']].rename(columns={'away_team': 'team', 'away_score': 'score'})
        
        scores_df = pd.concat([home_df, away_df]).sort_values(['team', 'week'])
        
        volatility = {}
        for team, group in scores_df.groupby('team'):
            # Take last 'window' games
            recent = group.tail(window)
            if len(recent) < 3: 
                vol = 10.0 # Default fallback
            else:
                vol = recent['score'].std()
            volatility[team] = round(vol, 2)
            
        return volatility

    def get_team_epa(self, year=2024):
        """
        Calculates Offensive and Defensive EPA/Play from PBP.
        """
        url = self.PBP_URL_TEMPLATE.format(year=year)
        print(f"  [NFL] Fetching PBP for EPA ({url})...")
        try:
            # We only need specific columns to save memory
            cols = ['posteam', 'defteam', 'epa', 'play_type', 'week']
            df = pd.read_csv(url, compression='gzip', usecols=cols, low_memory=False)
            
            # Filter non-plays
            df = df.dropna(subset=['epa', 'posteam', 'defteam'])
            
            # Offense EPA
            off_epa = df.groupby('posteam')['epa'].mean()
            
            # Defense EPA
            def_epa = df.groupby('defteam')['epa'].mean()
            
            # Combine
            ratings = {}
            # Standardize names if needed (nflverse usually consistently uses abbreviations)
            
            for team in off_epa.index:
                # We need Off and Def
                o_epa = off_epa.get(team, 0.0)
                d_epa = def_epa.get(team, 0.0)
                ratings[team] = {
                    'off_epa': round(o_epa, 3),
                    'def_epa': round(d_epa, 3)
                }
                
            return ratings
            
        except Exception as e:
            print(f"  [NFL] Error calculating EPA: {e}")
            return {}

    def get_buy_low_qbs(self, year: int = None, min_attempts: int = 200):
        """
        Identifies QBs with high CPOE but low Passing Yards.
        """
        df = self.get_passing_ngs(year)
        if df.empty: return []
        
        print(f"  [NFL] Raw NGS rows: {len(df)}")
        
        # NGS CSV columns are often snake_case.
        # Check specific column names for 'attempts' (might be 'attempts' or 'pass_attempts')
        
        # Standard NGS columns: week, player_display_name, player_position, team_abbr, ...
        # We likely want season aggregate?
        # The CSV is typically weekly. We need to aggregate it.
        
        if 'week' in df.columns:
             # Calculate weighted averages or totals
             # For CPOE, it's an average of averages? Or does the csv have totals?
             # Usually NextGenStats data structure is row per player per week.
             
             # Filter QBs only?
             if 'player_position' in df.columns:
                 df = df[df['player_position'] == 'QB']
             
             # Group by player
             # We need to compute season stats.
             # attempts -> sum
             # cpoe -> average weighted by attempts? Or just mean? 
             # completion_percentage_above_expectation is a rate stat.
             # Weighted average is best: sum(cpoe * attempts) / sum(attempts)
             
             # Let's simplify: take the mean for now, but weighted is better.
             
             df['w_cpoe'] = df['completion_percentage_above_expectation'] * df['attempts']
             df['w_air_yards'] = df['avg_intended_air_yards'] * df['attempts']
             
             grouped = df.groupby(['player_display_name', 'team_abbr']).agg({
                 'attempts': 'sum',
                 'w_cpoe': 'sum',
                 'w_air_yards': 'sum',
                 'aggressiveness': 'mean', 
                 'avg_time_to_throw': 'mean'
             }).reset_index()
             
             grouped['cpoe'] = grouped['w_cpoe'] / grouped['attempts']
             grouped['air_yards'] = grouped['w_air_yards'] / grouped['attempts']
             
             df = grouped

        if 'attempts' in df.columns:
            df = df[df['attempts'] >= min_attempts]
            
        # Sort by CPOE descending
        if 'cpoe' in df.columns:
            df = df.sort_values('cpoe', ascending=False)
            
        results = []
        for _, row in df.iterrows():
            results.append({
                "name": row.get('player_display_name'),
                "team": row.get('team_abbr'),
                "cpoe": round(row.get('cpoe', 0), 2),
                "air_yards": round(row.get('air_yards', 0), 1),
                "aggression": round(row.get('aggressiveness', 0), 1),
                "tt_throw": round(row.get('avg_time_to_throw', 0), 2),
                "attempts": int(row.get('attempts', 0))
            })
            
        return results

if __name__ == "__main__":
    svc = NFLService()
    
    print("--- Testing Buy Low QBs ---")
    qbs = svc.get_buy_low_qbs()
    print("Top 5 CPOE QBs:")
    for qb in qbs[:5]:
        print(qb)
        
    print("\n--- Testing Volatility ---")
    volMap = svc.get_team_volatility(2024)
    print(f"Fetched volatility for {len(volMap)} teams.")
    if volMap:
        print(f"Sample (KAN): {volMap.get('KAN', 'N/A')}")
        print(f"Sample (BAL): {volMap.get('BAL', 'N/A')}")

    print("\n--- Testing EPA ---")
    epaMap = svc.get_team_epa(2024)
    print(f"Fetched EPA for {len(epaMap)} teams.")
    if epaMap:
        print(f"Keys: {list(epaMap.keys())[:10]}")
        print(f"Sample (KC): {epaMap.get('KC', 'N/A')}")
        print(f"Sample (SF): {epaMap.get('SF', 'N/A')}")
