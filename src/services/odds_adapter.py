from src.utils.normalize import normalize_market, normalize_side, normalize_feed_provider

    # ... (existing imports)

    # In methods, replace self._normalize_market(x) with normalize_market(x)

from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone
from src.database import store_odds_snapshots, get_db_connection, _exec
from src.services.team_identity_service import TeamIdentityService

class OddsAdapter:
    def __init__(self):
        self.identity = TeamIdentityService()

    def _get_canonical_name(self, name, league):
        """
        Resolve raw name to canonical name via Identity service.
        """
        if not name: return None
        # Get canonical ID
        tid = self.identity.get_team_by_name(name, league)
        if tid:
            # Fetch official name for this ID
            with get_db_connection() as conn:
                row = _exec(conn, "SELECT name FROM teams WHERE id=%s", (tid,)).fetchone()
                if row: return row[0]
        return name

    def _resolve_canonical_event_id(self, league, home_team, away_team, start_time):
        """
        Map provider event to internal event_id using Text-based matching on names.
        """
        if not home_team or not away_team:
            return None
            
        # 1. Canonicalize names
        home_canon = self._get_canonical_name(home_team, league) or home_team
        away_canon = self._get_canonical_name(away_team, league) or away_team

        # 2. Parse Start Time
        if isinstance(start_time, str):
            try:
                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            except:
                dt = datetime.now(timezone.utc)
        elif isinstance(start_time, (int, float)):
            # Assume milliseconds if large
            if start_time > 20000000000: 
                dt = datetime.fromtimestamp(start_time / 1000.0, timezone.utc)
            else:
                dt = datetime.fromtimestamp(start_time, timezone.utc)
        elif isinstance(start_time, datetime):
            dt = start_time
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
             dt = datetime.now(timezone.utc)

        start_window = dt - timedelta(hours=6)
        end_window = dt + timedelta(hours=6)
        
        # 3. Query events by text matching
        # 3. Query events in window and fuzzy match
        # Fetch candidates
        query_candidates = """
        SELECT id, home_team, away_team FROM events
        WHERE league = :l
          AND start_time BETWEEN :start AND :end
        """
        
        candidates = []
        with get_db_connection() as conn:
            rows = _exec(conn, query_candidates, {
                "l": league,
                "start": start_window,
                "end": end_window
            }).fetchall()
            candidates = [dict(r) for r in rows]

        # Fuzzy Matcher Helper
        def matches(provider_name, event_team_name):
            if not provider_name or not event_team_name: return False
            p = provider_name.lower().replace('.', '').strip()
            e = event_team_name.lower().replace('.', '').strip()
            # Check containment (e.g. "xavier" in "xavier musketeers")
            if p in e or e in p:
                return True
            # Check team matcher logic if imported, or alias
            return False

        # Find best match
        best_match = None
        for cand in candidates:
            # Check both home/away (provider might have them flipped or normalized differently)
            # Direct: Home-Home, Away-Away
            if matches(home_canon, cand['home_team']) and matches(away_canon, cand['away_team']):
                best_match = cand['id']
                break
            # Swap: Home-Away, Away-Home
            if matches(home_canon, cand['away_team']) and matches(away_canon, cand['home_team']):
                best_match = cand['id']
                break
        
        if best_match:
            return best_match
        
        # Debug Log on failure
        # print(f"[OddsAdapter] Failed to resolve: {league} | {home_team} vs {away_team} | {dt}")
        return None

    def normalize_and_store(self, raw_data: List[Dict], league: str = None, provider: str = "odds_api", captured_at: datetime = None):
        """
        Normalize raw odds data and store snapshots.
        """
        if not raw_data:
            return 0
            
        final_snapshots = []
        if captured_at is None:
            captured_at = datetime.now(timezone.utc)

        provider = normalize_feed_provider(provider)

        dropped = {
            'missing_price': 0,
            'bad_price': 0,
            'bad_line': 0,
            'other': 0,
        }

        def _good_price(p):
            # American odds should almost always have magnitude >= 100.
            # Reject common ingestion bugs like -9, +12, etc.
            if p is None:
                return False
            try:
                p = int(p)
            except Exception:
                return False
            if p == 0:
                return False
            if abs(p) < 100:
                return False
            # reject absurd values
            if abs(p) > 5000:
                return False
            return True

        def _good_line(market_type, line_value):
            if market_type not in ('SPREAD', 'TOTAL'):
                return True
            if line_value is None:
                return False
            try:
                x = float(line_value)
            except Exception:
                return False
            # Very wide, league-agnostic sanity bounds
            if market_type == 'SPREAD':
                return abs(x) <= 80
            if market_type == 'TOTAL':
                return 0 <= x <= 400
            return True

        for event in raw_data:
            if provider == "action_network":
                snaps = self._from_action_network(event, league, captured_at) or []
            else:
                snaps = self._from_odds_api(event, league, captured_at) or []

            for s in snaps:
                try:
                    if s.get('price') is None:
                        dropped['missing_price'] += 1
                        continue
                    if not _good_price(s.get('price')):
                        dropped['bad_price'] += 1
                        continue
                    if not _good_line((s.get('market_type') or '').upper(), s.get('line_value')):
                        dropped['bad_line'] += 1
                        continue
                    final_snapshots.append(s)
                except Exception:
                    dropped['other'] += 1

        # Expose latest ingest stats to callers (cron can persist to data_health)
        self.last_ingest_stats = {
            'kept': len(final_snapshots),
            'dropped': int(sum(dropped.values())),
            'dropped_by_reason': dropped,
            'provider': provider,
            'league': league,
        }

        if not final_snapshots:
            return 0

        return store_odds_snapshots(final_snapshots)

    def _from_odds_api(self, event: Dict, league: str, captured_at: datetime) -> List[Dict]:
        """
        Convert Odds API event to snapshots.
        """
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
                mkt_key = normalize_market(mkt.get('key'))
                for out in mkt.get('outcomes', []):
                    # Safety Filter: Price is None
                    if out.get('price') is None: continue
                    
                    side = self._detect_side(out.get('name'), home_team, away_team)
                    
                    # Safety Filter: Line value numeric check for SPREAD/TOTAL
                    line_val = out.get('point')
                    if mkt_key in ('SPREAD', 'TOTAL') and line_val is None:
                         continue

                    snap = {
                        "event_id": event_id,
                        "provider": "odds_api",
                        "book": book_key,
                        "market_type": mkt_key,
                        "side": side,
                        "line_value": line_val,
                        "price": out.get('price'),
                        "captured_at": captured_at,
                        "raw_json": None
                    }
                    final_snaps.append(snap)
        return final_snaps

    def _upsert_action_network_event(self, league: str, event: Dict, start_time) -> Optional[str]:
        """Create/Upsert a canonical event when ESPN schedule is missing.

        This is critical for NCAAM where ESPN scoreboard may return only a subset.

        We generate a stable id based on Action Network game_id so odds_snapshots can FK it.
        """
        gid = event.get('game_id')
        if not gid:
            return None
            
        # Debug print removed (too noisy in cron)

        event_id = f"action:{(league or '').lower()}:{gid}"

        # Parse start_time
        dt = None
        if isinstance(start_time, str):
            try:
                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            except Exception as e:
                print(f"DEBUG Upsert Error: {e} for {start_time}")
                dt = None
        elif isinstance(start_time, datetime):
            dt = start_time
        elif isinstance(start_time, (int, float)):
            try:
                # seconds vs ms
                if start_time > 20000000000:
                    dt = datetime.fromtimestamp(start_time / 1000.0, timezone.utc)
                else:
                    dt = datetime.fromtimestamp(start_time, timezone.utc)
            except Exception:
                dt = None

        # Fallback
        if dt is None:
            dt = datetime.now(timezone.utc)

        home_team = event.get('home_team')
        away_team = event.get('away_team')
        status = event.get('status')

        q = """
        INSERT INTO events (id, league, home_team, away_team, start_time, status)
        VALUES (:id, :league, :home, :away, :start_time, :status)
        ON CONFLICT (id) DO UPDATE SET
          league=EXCLUDED.league,
          home_team=EXCLUDED.home_team,
          away_team=EXCLUDED.away_team,
          start_time=EXCLUDED.start_time,
          status=EXCLUDED.status,
          updated_at=CURRENT_TIMESTAMP
        """

        # (Debug logging removed; this runs frequently in cron)

        with get_db_connection() as conn:
            _exec(conn, q, {
                "id": event_id,
                "league": league,
                "home": home_team,
                "away": away_team,
                "start_time": dt,
                "status": status,
            })
            conn.commit()

        return event_id

    def _from_action_network(self, event, league, captured_at):
        home_team = event.get('home_team')
        away_team = event.get('away_team')
        # ActionNetwork fetcher returns `start_time` (ISO). Some older helpers use `commence_time`.
        start_time = event.get('commence_time') or event.get('start_time')

        # Action Network is the canonical board source for NCAAM now.
        # Use a stable Action-based event_id to avoid expensive fuzzy matching.
        if (league or '').upper() == 'NCAAM' and event.get('game_id'):
            event_id = self._upsert_action_network_event(league, event, start_time)
        else:
            event_id = self._resolve_canonical_event_id(league, home_team, away_team, start_time)
            if not event_id:
                # Fall back to creating an event from Action Network game_id
                event_id = self._upsert_action_network_event(league, event, start_time)

        if not event_id:
            return []

        def _append_book_snaps(book_name: str, payload: Dict, out: List[Dict]):
            if not isinstance(payload, dict):
                return
            hs = payload.get('home_spread')
            if hs is not None:
                try:
                    hs_f = float(hs)
                except Exception:
                    hs_f = None
                if hs_f is not None:
                    if payload.get('home_spread_odds') is not None:
                        out.append({
                            "event_id": event_id, "provider": "ACTION_NETWORK", "book": book_name,
                            "market_type": "SPREAD", "side": "HOME", "line_value": hs_f,
                            "price": payload.get('home_spread_odds'), "captured_at": captured_at,
                        })
                    if payload.get('away_spread_odds') is not None:
                        away_line = payload.get('away_spread')
                        try:
                            away_line_f = float(away_line) if away_line is not None else -hs_f
                        except Exception:
                            away_line_f = -hs_f
                        out.append({
                            "event_id": event_id, "provider": "ACTION_NETWORK", "book": book_name,
                            "market_type": "SPREAD", "side": "AWAY", "line_value": away_line_f,
                            "price": payload.get('away_spread_odds'), "captured_at": captured_at,
                        })
            tot = payload.get('total_score')
            if tot is not None:
                if payload.get('over_odds') is not None:
                    out.append({
                        "event_id": event_id, "provider": "ACTION_NETWORK", "book": book_name,
                        "market_type": "TOTAL", "side": "OVER", "line_value": tot,
                        "price": payload.get('over_odds'), "captured_at": captured_at,
                    })
                if payload.get('under_odds') is not None:
                    out.append({
                        "event_id": event_id, "provider": "ACTION_NETWORK", "book": book_name,
                        "market_type": "TOTAL", "side": "UNDER", "line_value": tot,
                        "price": payload.get('under_odds'), "captured_at": captured_at,
                    })
            if payload.get('home_money_line') is not None:
                out.append({
                    "event_id": event_id, "provider": "ACTION_NETWORK", "book": book_name,
                    "market_type": "MONEYLINE", "side": "HOME", "line_value": None,
                    "price": payload.get('home_money_line'), "captured_at": captured_at,
                })
            if payload.get('away_money_line') is not None:
                out.append({
                    "event_id": event_id, "provider": "ACTION_NETWORK", "book": book_name,
                    "market_type": "MONEYLINE", "side": "AWAY", "line_value": None,
                    "price": payload.get('away_money_line'), "captured_at": captured_at,
                })

        snaps = []
        book_lines = event.get('book_lines')
        if isinstance(book_lines, dict) and book_lines:
            for bname, bpayload in book_lines.items():
                if str(bname or '').strip().lower() in ('action_open', 'open'):
                    continue
                _append_book_snaps(str(bname), bpayload, snaps)
            if 'consensus' not in book_lines:
                _append_book_snaps('consensus', event, snaps)
        else:
            _append_book_snaps('consensus', event, snaps)

        open_lines = event.get('open_lines')
        if isinstance(open_lines, dict) and open_lines:
            _append_book_snaps('action_open', open_lines, snaps)
        return snaps

    def _detect_side(self, outcome_name, home_team, away_team):
        if home_team and outcome_name == home_team: return "HOME"
        if away_team and outcome_name == away_team: return "AWAY"
        return normalize_side(outcome_name)


