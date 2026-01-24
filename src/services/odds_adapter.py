from datetime import datetime, timedelta
from typing import List, Dict, Optional
from src.services.team_identity_service import TeamIdentityService
from src.database import store_odds_snapshots, get_db_connection, _exec

class OddsAdapter:
    def __init__(self):
        self.identity = TeamIdentityService()

    def _resolve_canonical_event_id(self, league, home_team, away_team, start_time):
        """
        Tries to find the canonical ID in 'events' table by matching teams and timing.
        """
        hid = self.identity.get_team_by_name(home_team, league)
        aid = self.identity.get_team_by_name(away_team, league)
        
        if not hid or not aid:
            return None
            
        # Search events
        query = """
        SELECT id FROM events 
        WHERE league = :l 
          AND home_team_id = :h AND away_team_id = :a
          AND start_time >= :start AND start_time <= :end
        """
        # Time window: +/- 6 hours
        if isinstance(start_time, str):
            try:
                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            except:
                dt = datetime.now() # Fallback
        else:
            dt = start_time

        start_window = dt - timedelta(hours=6)
        end_window = dt + timedelta(hours=6)
        
        with get_db_connection() as conn:
            row = _exec(conn, query, {
                "l": league,
                "h": hid,
                "a": aid,
                "start": start_window.isoformat(),
                "end": end_window.isoformat()
            }).fetchone()
            if row:
                return row[0]
        return None

    def _make_snap(self, eid, book, mkt, side, line, price, cat, cub):
        # Enforce non-null line for uniqueness constraint (NULL != NULL in SQL)
        if line is None:
            line = 0.0
        
        # Filter out NaN or invalid prices
        try:
            import math
            if price is None or math.isnan(float(price)):
                return None
        except:
            return None

        return {
            "event_id": str(eid),
            "book": book,
            "market_type": mkt,
            "side": side,
            "line": round(float(line), 1),
            "price": round(float(price), 3),
            "captured_at": cat,
            "captured_bucket": cub
        }

    def normalize_and_store(self, raw_data: List[Dict], league: str = None, provider: str = "odds_api"):
        """
        raw_data: List of events with odds.
        """
        if not raw_data:
            return 0
            
        final_snapshots = []
        captured_at = datetime.now()

        for event in raw_data:
            if provider == "action_network":
                snap = self._from_action_network(event, league, captured_at)
                if snap: final_snapshots.append(snap)
            else:
                # Default Odds API
                snaps = self._from_odds_api(event, league, captured_at)
                final_snapshots.extend(snaps)
        
        if not final_snapshots:
            return 0
            
        store_odds_snapshots(final_snapshots)
        return len(final_snapshots)

    def _from_odds_api(self, event, league, captured_at):
        final_snaps = []
        home_team = event.get('home_team')
        away_team = event.get('away_team')
        start_time = event.get('commence_time')

        event_id = self._resolve_canonical_event_id(league, home_team, away_team, start_time)
        if not event_id: return []

        bookmakers = event.get('bookmakers', [])
        for bm in bookmakers:
            book_key = bm.get('key')
            for mkt in bm.get('markets', []):
                mkt_key = self._normalize_market(mkt.get('key'))
                for out in mkt.get('outcomes', []):
                    side = self._detect_side(out.get('name'), home_team, away_team)
                    snap = {
                        "event_id": event_id,
                        "provider": "odds_api",
                        "book": book_key,
                        "market_type": mkt_key,
                        "side": side,
                        "line_value": out.get('point'),
                        "price": out.get('price'),
                        "captured_at": captured_at,
                        "raw_json": None # Optional enrichment
                    }
                    final_snaps.append(snap)
        return final_snaps

    def _from_action_network(self, event, league, captured_at):
        home_team = event.get('home_team')
        away_team = event.get('away_team')
        start_time = event.get('start_time')

        event_id = self._resolve_canonical_event_id(league, home_team, away_team, start_time)
        if not event_id: return []

        snaps = []
        # Spread
        if event.get('home_spread') is not None:
             snaps.append({
                 "event_id": event_id, "provider": "ACTION_NETWORK", "book": "consensus",
                 "market_type": "SPREAD", "side": "HOME", "line_value": event.get('home_spread'),
                 "price": event.get('home_spread_odds'), "captured_at": captured_at
             })
             snaps.append({
                 "event_id": event_id, "provider": "ACTION_NETWORK", "book": "consensus",
                 "market_type": "SPREAD", "side": "AWAY", "line_value": -event.get('home_spread'),
                 "price": event.get('away_spread_odds'), "captured_at": captured_at
             })
        # Total
        if event.get('total_score') is not None:
             snaps.append({
                 "event_id": event_id, "provider": "ACTION_NETWORK", "book": "consensus",
                 "market_type": "TOTAL", "side": "OVER", "line_value": event.get('total_score'),
                 "price": event.get('over_odds'), "captured_at": captured_at
             })
             snaps.append({
                 "event_id": event_id, "provider": "ACTION_NETWORK", "book": "consensus",
                 "market_type": "TOTAL", "side": "UNDER", "line_value": event.get('total_score'),
                 "price": event.get('under_odds'), "captured_at": captured_at
             })
        # ML
        if event.get('home_money_line') is not None:
             snaps.append({
                 "event_id": event_id, "provider": "ACTION_NETWORK", "book": "consensus",
                 "market_type": "ML", "side": "HOME", "line_value": None,
                 "price": event.get('home_money_line'), "captured_at": captured_at
             })
             snaps.append({
                 "event_id": event_id, "provider": "ACTION_NETWORK", "book": "consensus",
                 "market_type": "ML", "side": "AWAY", "line_value": None,
                 "price": event.get('away_money_line'), "captured_at": captured_at
             })
        return snaps

    def _detect_side(self, outcome_name, home_team, away_team):
        if home_team and outcome_name == home_team: return "HOME"
        if away_team and outcome_name == away_team: return "AWAY"
        return self._normalize_side(outcome_name)

    def _normalize_market(self, m):
        m = m.lower()
        if m in ('h2h', 'moneyline', 'ml'): return 'MONEYLINE'
        if m in ('spreads', 'spread'): return 'SPREAD'
        if m in ('totals', 'total'): return 'TOTAL'
        return m.upper()

    def _normalize_side(self, s):
        s = str(s).upper()
        if s in ('OVER', 'O'): return 'OVER'
        if s in ('UNDER', 'U'): return 'UNDER'
        if s in ('DRAW', 'X'): return 'DRAW'
        return s
