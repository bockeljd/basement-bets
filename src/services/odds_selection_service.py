from datetime import datetime
from typing import List, Dict, Optional
import statistics

class OddsSelectionService:
    """
    Intelligent Odds Selection Policy.
    Prioritizes sharper books and recent lines over stale or soft books.
    """
    
    # Priority: Lower index = Higher priority (Sharper)
    BOOK_PRIORITY = {
        "Pinnacle": 1,
        "Circa Sports": 2,
        "Bookmaker": 3,
        "DraftKings": 10,
        "FanDuel": 11,
        "BetMGM": 12,
        "Caesars": 13,
        "Bovada": 20,
        "BetOnline": 21
    }
    
    DEFAULT_PRIORITY = 99

    def select_best_snapshot(self, snapshots: List[Dict], market_type: str, side: str = None) -> Optional[Dict]:
        """
        Selects the most representative 'market' snapshot from a list of candidates.
        
        Policy:
        1. Filter by market_type (already done by caller usually, but good to verify).
        2. Sort by:
           - Recency (Bucketed? Or strict?) -> Let's prioritize Recency first if gap is large.
           - Book Priority (Sharpest first).
        
        Refined Policy:
        - If we have a 'Sharp' book (Pinnacle/Circa) within last 30 mins, use it.
        - Else, use the most recent line from any major book.
        - If multiple books have same timestamp, use Priority.
        """
        if not snapshots:
            return None
            
        # 1. Enrich with Priority and Timestamp
        annotated = []
        for snap in snapshots:
            # Basic filters
            if snap['market_type'] != market_type:
                continue
            if side and snap.get('side') != side:
                continue
            
            book_name = snap.get('book', 'Unknown')
            # Check priority
            prio = self.DEFAULT_PRIORITY
            for key, val in self.BOOK_PRIORITY.items():
                if key.lower() in book_name.lower():
                    prio = val
                    break
            
            annotated.append({
                "snap": snap,
                "priority": prio,
                "ts": snap['captured_at'] # ISO String
            })
            
        if not annotated:
            return None
            
        # 2. Sort
        # We want: Most Recent > Highest Priority (Lowest val)
        # But if Recency diff is small (e.g. 5 mins), Priority wins.
        # Let's simple sort by ts desc, then priority.
        # Actually, standard sort works tuple-wise.
        # ISO strings sort correctly.
        annotated.sort(key=lambda x: (x['ts'], -x['priority']), reverse=True)
        
        # This gives newest first. If tie in time, higher priority (lower val, so -prio is higher) comes first?
        # Wait: Priority 1 is better than 10.
        # If we sort reverse=True (Desc):
        # Time: 10:00 > 09:00. Correct.
        # Priority: We want 1 before 10.
        # If we use -priority: -1 > -10. Correct.
        # So key=(ts, -priority) with reverse=True works.
        
        best = annotated[0]
        
        # 3. Consensus / Median Check (Optional future enhancement)
        # If the top 3 are all very recent, maybe take median?
        # For now, sticking to "Best Available" logic (Top of sort).
        
        res = best['snap'].copy()
        res['selection_method'] = 'priority_recency'
        return res

    def get_consensus_line(self, snapshots: List[Dict], market_type: str) -> Optional[float]:
        """
        Compute value-weighted or simple median line.
        """
        lines = [s['line_value'] for s in snapshots if s['line_value'] is not None]
        if not lines: return None
        return statistics.median(lines)
