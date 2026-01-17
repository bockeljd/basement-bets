from datetime import datetime, timedelta
from typing import List, Dict, Optional
from src.services.team_identity_service import TeamIdentityService
from src.database import store_odds_snapshots, get_db_connection, _exec

class OddsAdapter:
    def __init__(self):
        self.identity = TeamIdentityService()

    def _resolve_canonical_event_id(self, league, home_team, away_team, start_time):
        """
        Tries to find the canonical UUID in events_v2 by matching teams and timing.
        """
        hid = self.identity.get_team_by_name(home_team, league)
        aid = self.identity.get_team_by_name(away_team, league)
        
        if not hid or not aid:
            return None
            
        # Search events_v2
        query = """
        SELECT id FROM events_v2 
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
            "line": float(line),
            "price": float(price),
            "captured_at": cat,
            "captured_bucket": cub
        }

    def normalize_and_store(self, raw_data: List[Dict], league: str = None, provider: str = "odds_api"):
        """
        raw_data: List of events with odds.
        """
        if not raw_data:
            return 0
            
        canonical_snapshots = []
        captured_at = datetime.now()
        # Bucket to 15 mins for idempotency
        bucket_mins = 15
        captured_bucket = captured_at.replace(
            minute=(captured_at.minute // bucket_mins) * bucket_mins,
            second=0,
            microsecond=0
        )

        for event in raw_data:
            if provider == "action_network":
                snapshots = self._from_action_network(event, league, captured_at, captured_bucket)
                canonical_snapshots.extend([s for s in snapshots if s is not None])
            else:
                # Default Odds API
                snapshots = self._from_odds_api(event, league, captured_at, captured_bucket)
                canonical_snapshots.extend([s for s in snapshots if s is not None])
        
        if not canonical_snapshots:
            return 0
            
        return store_odds_snapshots(canonical_snapshots)

    def _from_odds_api(self, event, league, captured_at, captured_bucket):
        snapshots = []
        raw_event_id = event.get('id')
        home_team = event.get('home_team')
        away_team = event.get('away_team')
        start_time = event.get('commence_time')

        # Try to resolve canonical ID
        event_id = self._resolve_canonical_event_id(league, home_team, away_team, start_time)
        if not event_id:
            event_id = raw_event_id # Fallback to provider ID if not linked

        bookmakers = event.get('bookmakers', [])
        for bm in bookmakers:
            book_key = bm.get('key')
            # ... rest of the logic ...
            # Wait, I should probably keep the existing logic and just swap the ID.
            # But I need to be careful with the loop.
            
            markets = bm.get('markets', [])
            for mkt in markets:
                mkt_key = self._normalize_market(mkt.get('key'))
                outcomes = mkt.get('outcomes', [])
                for out in outcomes:
                    outcome_name = out.get('name')
                    side = self._detect_side(outcome_name, home_team, away_team)
                    
                    snap = self._make_snap(
                        event_id, 
                        book_key, 
                        mkt_key, 
                        side, 
                        out.get('point'), 
                        out.get('price'), 
                        captured_at, 
                        captured_bucket
                    )
                    if snap:
                        snapshots.append(snap)
        return snapshots

    def _from_action_network(self, event, league, captured_at, captured_bucket):
        snapshots = []
        raw_event_id = event.get('game_id')
        if not raw_event_id: return []
        
        home_team = event.get('home_team')
        away_team = event.get('away_team')
        start_time = event.get('start_time')

        # Try to resolve canonical ID
        event_id = self._resolve_canonical_event_id(league, home_team, away_team, start_time)
        if not event_id:
            event_id = str(raw_event_id)

        # Moneyline
        if event.get('home_money_line'):
            snapshots.append(self._make_snap(event_id, "action", "MONEYLINE", "HOME", 0.0, event['home_money_line'], captured_at, captured_bucket))
        if event.get('away_money_line'):
            snapshots.append(self._make_snap(event_id, "action", "MONEYLINE", "AWAY", 0.0, event['away_money_line'], captured_at, captured_bucket))
            
        # Spread
        if event.get('home_spread'):
            snapshots.append(self._make_snap(event_id, "action", "SPREAD", "HOME", event['home_spread'], event.get('home_spread_odds', -110), captured_at, captured_bucket))
        if event.get('away_spread'):
            snapshots.append(self._make_snap(event_id, "action", "SPREAD", "AWAY", event['away_spread'], event.get('away_spread_odds', -110), captured_at, captured_bucket))
            
        # Total
        if event.get('total_score'):
            snapshots.append(self._make_snap(event_id, "action", "TOTAL", "OVER", event['total_score'], event.get('over_odds', -110), captured_at, captured_bucket))
            snapshots.append(self._make_snap(event_id, "action", "TOTAL", "UNDER", event['total_score'], event.get('under_odds', -110), captured_at, captured_bucket))
            
        return [s for s in snapshots if s is not None]

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
