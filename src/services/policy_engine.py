
from typing import List, Dict
import datetime
from src.database import get_db_connection, _exec

class PolicyEngine:
    """
    The Brain of the Operation.
    curates weights ($w_M$, $w_T$), expands/contracts sigma ($\sigma$), 
    and manages the market allowlist based on realized performance.
    """

    def refresh_policies(self):
        """
        Daily Cron Job:
        1. Calculate Rolling Metrics (7d, 30d) for each market type.
        2. Adjust Weights (Hill Climbing / Pid Controller style).
        3. Update Allowlist Status (Shadow -> Available).
        """
        print("[Policy] Starting Daily Refresh...")
        self._curate_ncaam_weights()
        self._curate_allowlist()
        print("[Policy] Refresh Complete.")

    def _curate_ncaam_weights(self):
        """
        Adjust weights based on rolling CLV.
        """
        # 1. Get current config
        # For MVP we assume single global config for NCAAM or per-market? 
        # User said "Each day, by market type".
        
        market_types = ['Spread', 'Total']
        
        for mkt in market_types:
            stats = self._fetch_performance(league="NCAAM", market_type=mkt, days=30)
            if not stats: continue
            
            clv_mean = stats.get('clv_mean', 0.0)
            n = stats.get('sample_size', 0)
            
            # Simple Controller Logic
            # If N > 50 and CLV > 0.5% => Boost
            # If N > 50 and CLV < -0.5% => Cut
            
            current_w = self._get_current_weight("NCAAM", mkt)
            new_w = current_w
            
            if n > 50:
                if clv_mean > 0.5:
                    new_w = min(0.50, current_w + 0.05)
                    print(f"[Policy] {mkt}: Promoting Weight {current_w:.2f} -> {new_w:.2f} (CLV: {clv_mean:.2f}%, N={n})")
                elif clv_mean < -0.5:
                    new_w = max(0.00, current_w - 0.05)
                    print(f"[Policy] {mkt}: Demoting Weight {current_w:.2f} -> {new_w:.2f} (CLV: {clv_mean:.2f}%, N={n})")
            
            if new_w != current_w:
                self._update_weight("NCAAM", mkt, new_w)

    def _get_current_weight(self, league, market_type):
        # Fetch from model_registry
        # Placeholder mock
        return 0.20
        
    def _update_weight(self, league, market_type, new_weight):
        # Update model_registry
        pass

    def _fetch_performance(self, league: str, market_type: str, days: int) -> Dict:
        # Query market_performance_daily
        query = """
        SELECT AVG(clv) as clv_mean, SUM(sample_size) as total_n
        FROM market_performance_daily
        WHERE league = :league AND market_type = :market_type
        AND date >= date('now', :days)
        """
        # Placeholder return for dry run
        return {'clv_mean': 1.2, 'sample_size': 60} # Fake success
 

    def _curate_allowlist(self):
        """
        Move markets between Shadow and Active based on performance.
        """
        # Tier 1: Spread, Total
        # Tier 2: 1H Spread/Total (Shadow until Tier 1 proven)
        
        market_types = ['Spread', 'Total']
        
        for mkt in market_types:
            stats = self._fetch_performance(league="NCAAM", market_type=mkt, days=30)
            if not stats: continue
            
            # Promotion Logic: N > 100, ROI > 2%, CLV > 0.5%
            # Demotion Logic: ROI < -5% (Stop Loss)
            
            roi = stats.get('roi', 0.0) # Need to fetch ROI too
            n = stats.get('sample_size', 0)
            
            if n > 100:
                if roi > 0.02:
                    print(f"[Policy] {mkt}: Promoting to ENABLED (ROI: {roi:.1%})")
                    # Update DB to ENABLED
                elif roi < -0.05:
                     print(f"[Policy] {mkt}: Demoting to SHADOW (ROI: {roi:.1%})")
                     # Update DB to SHADOW

    def _fetch_performance_window(self, league: str) -> List[Dict]:
        return []

if __name__ == "__main__":
    engine = PolicyEngine()
    engine.refresh_policies()
