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
        "LowVig": 3,
        "Bookmaker": 4,
        "DraftKings": 10,
        "FanDuel": 11,
        "BetMGM": 12,
        "Caesars": 13,
        "bet365": 14,
        "BetRivers": 15,
        "Bovada": 20,
        "BetOnline": 21
    }
    
    DEFAULT_PRIORITY = 99

    EXCLUDED_LIVE_BOOKS = {"action_open", "open"}
    SHARP_BENCHMARK_BOOKS = {
        "pinnacle",
        "circa sports",
        "circa",
        "lowvig",
        "bookmaker",
        "betonline",
        "betonlineag",
    }

    @classmethod
    def _is_live_book(cls, book_name: Optional[str]) -> bool:
        return str(book_name or "").strip().lower() not in cls.EXCLUDED_LIVE_BOOKS

    @classmethod
    def _is_sharp_benchmark(cls, book_name: Optional[str]) -> bool:
        b = str(book_name or "").strip().lower()
        return b in cls.SHARP_BENCHMARK_BOOKS or any(k in b for k in cls.SHARP_BENCHMARK_BOOKS)

    @classmethod
    def _is_named_retail_or_consensus(cls, book_name: Optional[str]) -> bool:
        b = str(book_name or "").strip().lower()
        return cls._is_live_book(b) and not b.startswith("action_book_")

    def _book_priority_for(self, book_name: Optional[str]) -> int:
        b = str(book_name or "Unknown")
        if b.strip().lower() == "consensus":
            return 50
        for key, val in self.BOOK_PRIORITY.items():
            if key.lower() in b.lower():
                return val
        return self.DEFAULT_PRIORITY

    def select_best_snapshot(self, snapshots: List[Dict], market_type: str, side: str = None) -> Optional[Dict]:
        """
        Selects the most representative 'market' snapshot from a list of candidates.
        """
        if not snapshots:
            return None

        # 1. Enrich with Priority and Timestamp
        annotated = []
        for snap in snapshots:
            if snap['market_type'] != market_type:
                continue
            if side and snap.get('side') != side:
                continue
            book_name = snap.get('book', 'Unknown')
            if not self._is_live_book(book_name):
                continue

            prio = self._book_priority_for(book_name)
            annotated.append({
                "snap": snap,
                "priority": prio,
                "ts": snap['captured_at']
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

    def get_consensus_line(self, snapshots: List[Dict], market_type: str, side: str = None) -> Optional[float]:
        """
        Compute median line value from all live books (excluding opening-line baselines).
        """
        filtered = [
            s for s in snapshots
            if s.get('market_type') == market_type and self._is_live_book(s.get('book'))
        ]
        if side:
            filtered = [s for s in filtered if s.get('side') == side]
        lines = [s['line_value'] for s in filtered if s.get('line_value') is not None]
        if not lines: return None
        return statistics.median(lines)

    def get_consensus_snapshot(
        self,
        snapshots: List[Dict],
        market_type: str,
        side: str = None,
        exclude_sharp_benchmarks: bool = True,
    ) -> Optional[Dict]:
        """
        Get a "consensus" snapshot with median line and median price.
        This represents what the "market average" thinks.
        By default excludes sharp benchmark books when non-sharp retail books are present
        so sharp benchmarks can be weighed explicitly without double-counting.
        """
        filtered = [
            s for s in snapshots
            if s.get('market_type') == market_type and self._is_live_book(s.get('book'))
        ]
        if side:
            filtered = [s for s in filtered if s.get('side') == side]

        if exclude_sharp_benchmarks:
            non_sharp = [s for s in filtered if not self._is_sharp_benchmark(s.get('book'))]
            if non_sharp:
                filtered = non_sharp
        
        lines = [s['line_value'] for s in filtered if s.get('line_value') is not None]
        prices = [s['price'] for s in filtered if s.get('price') is not None]
        
        if not lines:
            return None
        
        median_line = statistics.median(lines)
        median_price = statistics.median(prices) if prices else -110
        
        return {
            'market_type': market_type,
            'side': side,
            'line_value': median_line,
            'price': int(median_price),
            'book': 'Consensus',
            'selection_method': 'median_consensus'
        }

    def get_sharp_benchmark_snapshot(
        self,
        snapshots: List[Dict],
        market_type: str,
        side: str = None,
    ) -> Optional[Dict]:
        """Select the sharpest fresh offshore/sharp benchmark snapshot (Pinnacle > LowVig > BetOnline)."""
        if not snapshots:
            return None

        mkt_upper = str(market_type or '').upper()
        filtered = [
            s for s in snapshots
            if str(s.get('market_type') or '').upper() == mkt_upper
            and (side is None or s.get('side') == side)
            and self._is_live_book(s.get('book'))
            and self._is_sharp_benchmark(s.get('book'))
            and (mkt_upper == 'MONEYLINE' or s.get('line_value') is not None)
        ]
        if not filtered:
            return None

        latest_by_book: Dict[str, Dict] = {}
        for s in filtered:
            book_key = str(s.get('book') or '__unknown__')
            prev = latest_by_book.get(book_key)
            if prev is None or str(s.get('captured_at') or '') > str(prev.get('captured_at') or ''):
                latest_by_book[book_key] = s

        candidates = list(latest_by_book.values())

        def _parse_ts(val) -> Optional[float]:
            if isinstance(val, datetime):
                return val.timestamp()
            if isinstance(val, str) and val.strip():
                try:
                    return datetime.fromisoformat(val.strip().replace('Z', '+00:00')).timestamp()
                except Exception:
                    return None
            return None

        ts_vals = [t for t in (_parse_ts(c.get('captured_at')) for c in candidates) if t is not None]
        if ts_vals:
            max_ts = max(ts_vals)
            recent = [
                c for c in candidates
                if (_parse_ts(c.get('captured_at')) or max_ts) >= (max_ts - 5400.0)
            ]
            if recent:
                candidates = recent

        candidates.sort(
            key=lambda x: (
                self._book_priority_for(x.get('book')),
                -(_parse_ts(x.get('captured_at')) or 0.0),
            )
        )
        best = candidates[0].copy()
        best['selection_method'] = 'sharp_benchmark'
        return best

    def get_best_price_for_side(
        self,
        snapshots: List[Dict],
        market_type: str,
        side: str,
        target_line: Optional[float] = None,
        exclude_sharp_benchmarks: bool = True,
    ) -> Optional[Dict]:
        """Find the best available price for a specific side (HOME/AWAY or OVER/UNDER).

        Deduplicates by book (keeping newest ``captured_at``), restricts SPREAD/TOTAL
        shopping to within 0.5 pts of ``target_line`` (or the median line), and ranks
        by most favorable line first then highest American price.
        When ``exclude_sharp_benchmarks`` is True, keeps sharp benchmark books (Pinnacle,
        LowVig, BetOnline, Circa, Bookmaker) out of bet-card recommendations whenever
        playable US retail books exist.
        """
        filtered = [
            s for s in snapshots
            if s.get('market_type') == market_type
            and s.get('side') == side
            and s.get('price') is not None
            and self._is_live_book(s.get('book'))
        ]
        if not filtered:
            return None
        if exclude_sharp_benchmarks:
            non_sharp = [s for s in filtered if not self._is_sharp_benchmark(s.get('book'))]
            if non_sharp:
                filtered = non_sharp
        named_only = [s for s in filtered if self._is_named_retail_or_consensus(s.get('book'))]
        if named_only:
            filtered = named_only

        # Keep latest snapshot per book so stale outlier prices never win line-shopping.
        latest_by_book: Dict[str, Dict] = {}
        ordered_books: List[str] = []
        for s in filtered:
            book_key = str(s.get('book') or '__unknown__')
            prev = latest_by_book.get(book_key)
            if prev is None:
                latest_by_book[book_key] = s
                ordered_books.append(book_key)
            else:
                ts_new = str(s.get('captured_at') or '')
                ts_old = str(prev.get('captured_at') or '')
                if ts_new and ts_new > ts_old:
                    latest_by_book[book_key] = s
        candidates = [latest_by_book[b] for b in ordered_books]

        mkt_upper = str(market_type or '').upper()
        side_upper = str(side or '').upper()

        if mkt_upper in ('SPREAD', 'TOTAL'):
            with_lines = [s for s in candidates if s.get('line_value') is not None]
            if with_lines:
                anchor = (
                    float(target_line)
                    if target_line is not None
                    else statistics.median(float(s['line_value']) for s in with_lines)
                )
                near = [s for s in with_lines if abs(float(s['line_value']) - anchor) <= 0.5]
                if near:
                    near.sort(
                        key=lambda x: (
                            (-float(x['line_value']) if (mkt_upper == 'TOTAL' and side_upper == 'OVER') else float(x['line_value'])),
                            int(x.get('price', -999)),
                            -self._book_priority_for(x.get('book')),
                        ),
                        reverse=True,
                    )
                    best = near[0].copy()
                else:
                    with_lines.sort(
                        key=lambda x: (
                            -abs(float(x['line_value']) - anchor),
                            (-float(x['line_value']) if (mkt_upper == 'TOTAL' and side_upper == 'OVER') else float(x['line_value'])),
                            int(x.get('price', -999)),
                            -self._book_priority_for(x.get('book')),
                        ),
                        reverse=True,
                    )
                    best = with_lines[0].copy()
                best['selection_method'] = 'best_price'
                return best

        candidates.sort(
            key=lambda x: (int(x.get('price', -999)), -self._book_priority_for(x.get('book'))),
            reverse=True,
        )
        best = candidates[0].copy()
        best['selection_method'] = 'best_price'
        return best
