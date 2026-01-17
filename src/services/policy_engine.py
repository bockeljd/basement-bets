
from typing import List, Dict
from datetime import datetime, timedelta
from src.database import (
    get_db_connection, _exec, 
    aggregate_daily_performance, 
    get_market_performance_window,
    get_market_allowlist,
    update_market_status
)

class PolicyEngine:
    """
    The Brain of the Operation.
    Curates weights ($w_M$, $w_T$), expands/contracts sigma ($\sigma$), 
    and manages the market allowlist based on realized performance.
    """

    def refresh_policies(self):
        """
        Daily Cron Job:
        1. Aggregate yesterday's performance.
        2. Calculate Rolling Metrics (30d).
        3. Update Allowlist Status (Shadow -> Available).
        4. Adjust Weights (Hill Climbing / Pid Controller style).
        """
        print("[Policy] Starting Daily Refresh...")
        
        # 1. Aggregate Yesterday
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        aggregate_daily_performance(yesterday)
        
        # 2. Curate
        self._curate_allowlist()
        self._curate_ncaam_weights()
        
        print("[Policy] Refresh Complete.")

    def _curate_ncaam_weights(self):
        """
        Adjust weights based on rolling CLV.
        """
        market_types = ['Spread', 'Total']
        
        for mkt in market_types:
            stats = get_market_performance_window(league="basketball_ncaab", market_type=mkt, days=30)
            if not stats: continue
            
            clv_mean = stats.get('clv', 0.0)
            n = stats.get('sample_size', 0)
            
            # Simple Controller Logic
            # If N > 50 and CLV > 0.5% => Trust Model More (Boost Weight?) OR Trust Market Less?
            # Actually, CLV = (Closing - Bet). +/- means Model beat Closing Line?
            # If avg_clv > 0, Model is finding value. Maintain or Boost Model Weight.
            # If avg_clv < 0, Model is losing to market. Decrease Model Weight ($w_T$).
            
            # Current Weight (Mock)
            current_w = 0.5 # Default balanced
            new_w = current_w
            
            if n > 50:
                if clv_mean > 0.5:
                    # Model beating market. Trust Torvik/Model.
                    new_w = min(0.80, current_w + 0.05)
                    print(f"[Policy] {mkt}: Boosting Model Weight {current_w:.2f} -> {new_w:.2f} (CLV: {clv_mean:.2f}%, N={n})")
                elif clv_mean < -0.5:
                    # Model losing. Trust Market.
                    new_w = max(0.20, current_w - 0.05)
                    print(f"[Policy] {mkt}: Reducing Model Weight {current_w:.2f} -> {new_w:.2f} (CLV: {clv_mean:.2f}%, N={n})")
            
            # TODO: Write new weight to model_registry
            # For now, just logging decision.

    def _curate_allowlist(self):
        """
        Move markets between Shadow and Active based on performance.
        """
        # Tier 1: Spread, Total
        market_types = ['Spread', 'Total']
        current_status_map = get_market_allowlist()
        
        for mkt in market_types:
            stats = get_market_performance_window(league="basketball_ncaab", market_type=mkt, days=30)
            if not stats: continue
            
            roi = stats.get('roi', 0.0)
            n = stats.get('sample_size', 0)
            
            # Current Status
            key = ("basketball_ncaab", mkt)
            status = current_status_map.get(key, 'SHADOW')
            
            # Promotion Logic: N > 20, ROI > 2%
            if status == 'SHADOW' and n > 20 and roi > 0.02:
                update_market_status("basketball_ncaab", mkt, 'ENABLED', f"Promoted: ROI {roi:.1%} over {n} bets")
                
            # Demotion Logic: ROI < -5% (Stop Loss)
            elif status == 'ENABLED' and n > 20 and roi < -0.05:
                update_market_status("basketball_ncaab", mkt, 'SHADOW', f"Demoted: ROI {roi:.1%} over {n} bets")

if __name__ == "__main__":
    engine = PolicyEngine()
    engine.refresh_policies()
