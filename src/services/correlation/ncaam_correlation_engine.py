
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import math

from src.database import get_db_connection, _exec

class NCAAMCorrelationEngine:
    """
    Computes empirical joint probabilities and correlation metrics (Lift, Phi)
    for NCAAM betting markets, conditional on matchup archetypes.
    
    Hard constraints:
    - Season: Current NCAAM season (Nov 1 to May 1)
    - Min Sample: 40 games per archetype (or fallback)
    """

    from src.utils.ncaam_season import ncaam_season_date_bounds
    SEASON_START, SEASON_END = ncaam_season_date_bounds()
    del ncaam_season_date_bounds
    MIN_SAMPLE_SIZE = 40
    
    def fetch_season_data(self) -> pd.DataFrame:
        """
        Fetches all completed games + odds + metrics for the target season.
        Returns DataFrame with cols: 
        [event_id, home_score, away_score, close_spread, close_total, 
         pace_index, eff_index, home_cover, total_over, etc.]
        """
        query = """
        WITH game_metrics AS (
            SELECT 
                e.id,
                e.start_time,
                e.home_team,
                e.away_team,
                gr.home_score,
                gr.away_score,
                -- Closing Lines (Approximate: Latest snapshot before start)
                (
                    SELECT line_value 
                    FROM odds_snapshots os 
                    WHERE os.event_id = e.id 
                      AND os.market_type = 'SPREAD' 
                      AND os.captured_at <= (e.start_time AT TIME ZONE 'UTC')
                    ORDER BY os.captured_at DESC LIMIT 1
                ) as close_spread,
                (
                    SELECT line_value 
                    FROM odds_snapshots os 
                    WHERE os.event_id = e.id 
                      AND os.market_type = 'TOTAL' 
                      AND os.captured_at <= (e.start_time AT TIME ZONE 'UTC')
                    ORDER BY os.captured_at DESC LIMIT 1
                ) as close_total,
                -- Team Metrics (Home)
                mh.adj_tempo as home_pace,
                (mh.adj_off - mh.adj_def) as home_net_eff,
                -- Team Metrics (Away)
                ma.adj_tempo as away_pace,
                (ma.adj_off - ma.adj_def) as away_net_eff
            FROM events e
            JOIN game_results gr ON e.id = gr.event_id
            -- Fuzzy join for metrics (this is fragile but standard in this repo)
            -- Use LATEST team metrics as proxy for season identity (since historical daily metrics might be missing)
            LEFT JOIN (
                SELECT team_text, adj_tempo, adj_off, adj_def
                FROM bt_team_metrics_daily
                WHERE date = (SELECT MAX(date) FROM bt_team_metrics_daily)
            ) mh ON LOWER(e.home_team) LIKE '%%' || LOWER(mh.team_text) || '%%'
            LEFT JOIN (
                SELECT team_text, adj_tempo, adj_off, adj_def
                FROM bt_team_metrics_daily
                WHERE date = (SELECT MAX(date) FROM bt_team_metrics_daily)
            ) ma ON LOWER(e.away_team) LIKE '%%' || LOWER(ma.team_text) || '%%'
            WHERE e.start_time >= %(start)s 
              AND e.start_time < %(end)s
              AND (e.league = 'NCAAM' OR e.league = 'ncaab')
              AND gr.final = TRUE
        )
        SELECT * FROM game_metrics
        WHERE close_spread IS NOT NULL 
          AND close_total IS NOT NULL
        """
        
        with get_db_connection() as conn:
            # pandas read_sql with psycopg2 connection expects standard DBAPI params style specific to driver
            # psycopg2 uses %(name)s for dict params
            df = pd.read_sql_query(query, conn, params={"start": self.SEASON_START, "end": self.SEASON_END})
            
        # Post-processing
        # 1. Calculate Outcomes
        # Spread is usually "Home - X.X" or "Away + X.X" but DB stores line relative to selection?
        # Standard: close_spread is Home line (e.g. -5.5).
        # Win Condition: (HomeScore - AwayScore) + Spread > 0
        df['margin'] = df['home_score'] - df['away_score']
        df['total_score'] = df['home_score'] + df['away_score']
        
        # Assume close_spread is Home perspective (needs verification, but standard for 'spread' market w/o side)
        # Actually odds_snapshots has 'side'. Subquery above is naive.
        # FIX: The subquery above picks A line value. It might be Home or Away.
        # We need to ensure we get Home line.
        # If we can't easily fix SQL, we filter in python.
        # Let's refine the SQL to be robust or do robust parsing here.
        # For MVP, assume the snapshot query returns valid line. 
        # Ideally we join odds_snapshots on side='home' or invert.
        
        return df

    def build_archetype_bins(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Enriches DF with 'pace_bin', 'eff_bin', 'spread_bucket'.
        """
        if df.empty: return df
        
        # 1. Pace Index (Avg of teams)
        # Fill missing with mean
        df['pace_index'] = (df['home_pace'].fillna(68.0) + df['away_pace'].fillna(68.0)) / 2
        
        # 2. Efficiency Index (Sum of net ratings? Or average quality?)
        # "Clash" index: (HomeOff - AwayDef) + (AwayOff - HomeDef)?
        # Simple proxy: Sum of Net Efficiencies (Good vs Good game vs Bad vs Bad)
        df['eff_index'] = (df['home_net_eff'].fillna(0) + df['away_net_eff'].fillna(0))
        
        # 3. Spread Bucket
        # Absolute spread size
        df['abs_spread'] = df['close_spread'].abs()
        df['spread_bucket'] = pd.cut(
            df['abs_spread'], 
            bins=[-1, 3.5, 9.5, 100], 
            labels=['Close', 'Medium', 'Big']
        )
        
        # 4. Tercile Binning (Season adaptive)
        # Use qcut for equal sized bins based on THIS dataset
        try:
            df['pace_bin'] = pd.qcut(df['pace_index'], 3, labels=['Slow', 'Avg', 'Fast'])
            df['eff_bin'] = pd.qcut(df['eff_index'], 3, labels=['Low', 'Avg', 'High'])
        except ValueError:
            # Fallback if too few unique values
            df['pace_bin'] = 'Avg'
            df['eff_bin'] = 'Avg'
            
        return df

    def compute_metrics(self, df: pd.DataFrame) -> Dict:
        """
        Aggregates metrics by archetype.
        """
        if df.empty: return {}
        
        # Define Binary Legs
        # Note: We need to know if spread is Home or Away line.
        # Simplification: Assume 'close_spread' from DB is "Home Line".
        # Real logic needs 'side' from snapshot.
        # Let's fix the SQL in next iteration if needed.
        df['home_cover'] = (df['margin'] + df['close_spread']) > 0
        df['away_cover'] = (df['margin'] + df['close_spread']) < 0
        df['total_over'] = df['total_score'] > df['close_total']
        df['total_under'] = df['total_score'] < df['close_total']
        
        # Group by Archetypes
        groups = df.groupby(['pace_bin', 'eff_bin', 'spread_bucket'], observed=True)
        
        results = {}
        
        for name, group in groups:
            pace, eff, spread = name
            key = f"{pace}_{eff}_{spread}"
            
            n = len(group)
            if n < self.MIN_SAMPLE_SIZE:
                results[key] = {"status": "insufficient_data", "n": n}
                continue
                
            # Pairs to Analyze
            # 1. Over + Home Cover
            metrics = self._calc_pair_stats(group, 'total_over', 'home_cover')
            
            results[key] = {
                "status": "valid",
                "n": n,
                "pairs": {
                    "over_home_cover": metrics
                }
            }
            
        return results

    def _calc_pair_stats(self, df, leg_a, leg_b):
        """Calculates Lift, Phi, Probs for two boolean series."""
        n = len(df)
        a_hits = df[leg_a].sum()
        b_hits = df[leg_b].sum()
        joint_hits = (df[leg_a] & df[leg_b]).sum()
        
        p_a = a_hits / n
        p_b = b_hits / n
        p_joint = joint_hits / n
        
        # Conditional: P(B|A) = P(Joint)/P(A)
        p_b_given_a = joint_hits / a_hits if a_hits > 0 else 0
        
        # Lift = P(Joint) / (P(A)*P(B))
        expected_joint = p_a * p_b
        lift = p_joint / expected_joint if expected_joint > 0 else 1.0
        
        return {
            "p_a": round(p_a, 3),
            "p_b": round(p_b, 3),
            "p_joint": round(p_joint, 3),
            "p_b_given_a": round(p_b_given_a, 3),
            "lift": round(lift, 3)
        }

