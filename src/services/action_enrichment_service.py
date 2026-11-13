import hashlib
import json
import datetime
import uuid
from typing import Dict, List, Optional
from src.database import get_db_connection, _exec
from src.services.odds_fetcher_service import OddsFetcherService
from src.services.event_linker import EventLinker

class ActionEnrichmentService:
    def __init__(self):
        self.fetcher = OddsFetcherService()
        self.linker = EventLinker()
        
    def _generate_fingerprint(self, *args) -> str:
        s = "|".join(str(a) for a in args)
        return hashlib.sha256(s.encode()).hexdigest()

    def ingest_enrichment_for_league(self, league: str, date_str: str = None) -> Dict:
        """
        Main entry point.
        """
        if not date_str:
            date_str = datetime.datetime.now().strftime("%Y%m%d")
            
        print(f"[Enrichment] Fetching {league} for {date_str}...")
        
        # 1. Fetch from Action Network (reuse existing fetcher logic)
        # Note: fetch_odds parses data. We might need raw data for enrichment payload.
        # But fetch_odds returns a cleaned list. 
        # The prompt requires storing the "payload_json". 
        # So I should probably modify OddsFetcher to return raw or re-request here.
        # To avoid breaking existing code, I'll re-request similar to fetch_odds but keep raw.
        
        # Actually, OddsFetcher parses internal structure. 
        # I'll implement a raw fetch here to get the full json for `action_game_enrichment`.
        
        raw_games = self._fetch_raw(league, date_str)
        print(f"[Enrichment] Found {len(raw_games)} games.")
        
        stats = {
            "games_processed": 0,
            "enrichment_saved": 0,
            "splits_saved": 0,
            "errors": 0
        }
        
        for game in raw_games:
            try:
                saved_cnt = self._process_game(game, league)
                stats["games_processed"] += 1
                stats["splits_saved"] += int(saved_cnt or 0)
            except Exception as e:
                print(f"[Enrichment] Failed to process game {game.get('id')}: {e}")
                stats["errors"] += 1
                
        return stats

    def _fetch_raw(self, league: str, date_str: str) -> List[Dict]:
        """
        Direct fetch to get full v2 scoreboard JSON payload (including markets book 15 bet_info splits).
        """
        sport_map = {
            'NBA': 'nba', 'NFL': 'nfl', 'MLB': 'mlb', 
            'NCAAM': 'ncaab', 'NCAAF': 'ncaaf', 'EPL': 'soccer'
        }
        api_sport = sport_map.get(league, league.lower())
        
        url = f"https://api.actionnetwork.com/web/v2/scoreboard/{api_sport}?date={date_str}"
        if api_sport == 'ncaab':
            url += "&division=D1"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Origin': 'https://www.actionnetwork.com',
            'Referer': 'https://www.actionnetwork.com/',
        }
        
        import requests
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        return data.get('games', [])

    def _resolve_direct_action_event_id(self, game: Dict, league: str) -> Optional[str]:
        """Resolve exact `action:<league>:<id>` row in events table before fuzzy linking."""
        an_id = game.get('id')
        if not an_id:
            return None
        candidate_id = f"action:{league.lower()}:{an_id}"
        try:
            with get_db_connection() as conn:
                row = _exec(conn, "SELECT id FROM events WHERE id = %s LIMIT 1", (candidate_id,)).fetchone()
                if row:
                    return dict(row).get("id") if isinstance(row, dict) or hasattr(row, "keys") else row[0]
        except Exception:
            return None
        return None

    def _process_game(self, game: Dict, league: str):
        # 1. Resolve Canonical Event ID
        # First check exact action:<league>:<id> primary key; fallback to (Home, Away, Date ET) fuzzy link.
        event_id = self._resolve_direct_action_event_id(game, league)

        home_team_id = game.get('home_team_id')
        away_team_id = game.get('away_team_id')
        
        # Extract names from teams array
        home_name = "Unknown"
        away_name = "Unknown"
        for t in game.get('teams', []):
            if t.get('id') == home_team_id:
                home_name = t.get('full_name') or t.get('display_name') or home_name
            if t.get('id') == away_team_id:
                away_name = t.get('full_name') or t.get('display_name') or away_name
            
        if not event_id:
            start_time_iso = game.get('start_time')
            try:
                from zoneinfo import ZoneInfo
                dt = datetime.datetime.fromisoformat(str(start_time_iso).replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                date_str = dt.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
            except Exception:
                date_str = datetime.datetime.now().strftime("%Y-%m-%d")

            mock_leg = {"selection": home_name, "team": home_name}
            description = f"{home_name} vs {away_name}"
            link_res = self.linker.link_leg(mock_leg, league, date_str, description=description)
            event_id = link_res.get('event_id')
            if not event_id or link_res.get('link_status') != 'LINKED':
                mock_leg_away = {"selection": away_name, "team": away_name}
                link_res = self.linker.link_leg(mock_leg_away, league, date_str, description=description)
                event_id = link_res.get('event_id')
                if not event_id:
                    return

        # 2. Store Raw Enrichment
        self._store_raw_enrichment(event_id, game)
        
        # 3. Extract Splits
        return self._extract_splits(event_id, game)
        
        # 4. Extract Props/Injuries (Placeholder)
        pass

    def _store_raw_enrichment(self, event_id: str, game_data: Dict):
        payload_str = json.dumps(game_data, default=str)
        provider_game_id = str(game_data.get('id'))
        
        # Fingerprint: event_id + time_bucket (e.g. hourly) + payload_hash
        # Actually payload hash alone is good for dedupe if identical
        payload_hash = hashlib.sha256(payload_str.encode()).hexdigest()
        
        # But we want to capture history. So timestamp matters.
        # Let's bucket timestamp to 1 hour to avoid noise? 
        # Or just insert unique payloads.
        # Using payload_hash ensuring we only store NEW data.
        fingerprint = self._generate_fingerprint(event_id, payload_hash)
        
        with get_db_connection() as conn:
            # UUID handler for Postgres vs Sqlite? 
            # In SQLite we use string. In PG we use string for input and let driver cast or ensure we pass UUID obj.
            # For simplicity, passing string usually works if driver handles it, or explicit.
            
            # Simple Insert w/ IGNORE on fingerprint
            ins = """
            INSERT INTO action_game_enrichment 
            (id, event_id, provider_game_id, payload_json, fingerprint)
            VALUES (?, ?, ?, ?, ?)
            """
            # Adjust params for PG in _exec helper
            
            # ID generation
            row_id = str(uuid.uuid4())
            
            try:
                _exec(conn, ins, (row_id, str(event_id), provider_game_id, payload_str, fingerprint))
                conn.commit()
            except Exception as e:
                # Likely Unique Constraint -> Data hasn't changed
                pass

    @staticmethod
    def parse_splits_from_game(game_data: Dict) -> List[Dict]:
        """Parse public ticket % and money % from Action Network v2 `markets` (fallback: legacy `odds`)."""
        splits: List[Dict] = []

        def _sharp_tag(bet_pct, handle_pct):
            if bet_pct is None or handle_pct is None:
                return None
            diff = float(handle_pct) - float(bet_pct)
            if float(bet_pct) < 45.0 and float(handle_pct) >= 55.0 and diff >= 12.0:
                return "RLM"
            if diff >= 12.0 and float(handle_pct) >= 55.0:
                return "SHARP_MONEY"
            return None

        markets = (game_data or {}).get("markets") or {}
        book_payload = None
        if isinstance(markets, dict):
            # Prefer book '15' (Action consensus), else first book with an 'event' map.
            if isinstance(markets.get("15"), dict) and isinstance(markets["15"].get("event"), dict):
                book_payload = markets["15"]["event"]
            else:
                for bk in markets.values():
                    if isinstance(bk, dict) and isinstance(bk.get("event"), dict):
                        book_payload = bk["event"]
                        break

        if isinstance(book_payload, dict):
            market_map = (("spread", "SPREAD"), ("total", "TOTAL"), ("moneyline", "ML"))
            for v2_key, canon_mkt in market_map:
                items = book_payload.get(v2_key) or []
                if not isinstance(items, list):
                    continue
                # Prefer pregame outcomes (is_live False) or outcomes with non-zero split info.
                selected_by_side: Dict[str, Dict] = {}
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    side = str(item.get("side") or "").upper().strip()
                    if not side:
                        continue
                    bet_info = item.get("bet_info") or {}
                    t_pct = ((bet_info.get("tickets") or {}).get("percent"))
                    m_pct = ((bet_info.get("money") or {}).get("percent"))
                    if t_pct is None and m_pct is None:
                        continue
                    is_live = bool(item.get("is_live"))
                    prev = selected_by_side.get(side)
                    score = (0 if is_live else 2) + (1 if ((t_pct or 0) + (m_pct or 0)) > 0 else 0)
                    if prev is None or score > prev["_score"]:
                        line_val = item.get("value")
                        if canon_mkt == "ML":
                            line_val = None
                        selected_by_side[side] = {
                            "_score": score,
                            "market": canon_mkt,
                            "selection": side,
                            "line": line_val,
                            "bet_pct": t_pct,
                            "handle_pct": m_pct,
                            "sharp_indicator": _sharp_tag(t_pct, m_pct),
                        }
                for row in selected_by_side.values():
                    row.pop("_score", None)
                    if (row.get("bet_pct") or 0) > 0 or (row.get("handle_pct") or 0) > 0:
                        splits.append(row)

        if splits:
            return splits

        # Legacy v1 fallback (`game['odds']`)
        odds_list = (game_data or {}).get("odds") or []
        if not odds_list:
            return []
        target_odd = next(
            (o for o in odds_list if o.get("ml_home_public") is not None or o.get("spread_home_money") is not None),
            None,
        )
        if not target_odd:
            return []

        legacy_specs = (
            ("ML", "HOME", None, target_odd.get("ml_home_public"), target_odd.get("ml_home_money")),
            ("ML", "AWAY", None, target_odd.get("ml_away_public"), target_odd.get("ml_away_money")),
            ("SPREAD", "HOME", target_odd.get("spread_home"), target_odd.get("spread_home_public"), target_odd.get("spread_home_money")),
            ("SPREAD", "AWAY", target_odd.get("spread_away"), target_odd.get("spread_away_public"), target_odd.get("spread_away_money")),
            ("TOTAL", "OVER", target_odd.get("total"), target_odd.get("total_over_public"), target_odd.get("total_over_money")),
            ("TOTAL", "UNDER", target_odd.get("total"), target_odd.get("total_under_public"), target_odd.get("total_under_money")),
        )
        for mkt, sel, ln, bp, hp in legacy_specs:
            if bp is not None or hp is not None:
                splits.append({
                    "market": mkt,
                    "selection": sel,
                    "line": ln,
                    "bet_pct": bp,
                    "handle_pct": hp,
                    "sharp_indicator": _sharp_tag(bp, hp),
                })
        return splits

    def _extract_splits(self, event_id: str, game_data: Dict) -> int:
        splits = self.parse_splits_from_game(game_data)
        if not splits:
            return 0

        saved = 0
        ts_bucket = datetime.datetime.now().strftime("%Y%m%d%H")
        with get_db_connection() as conn:
            for s in splits:
                row_id = str(uuid.uuid4())
                fp = self._generate_fingerprint(
                    event_id,
                    s["market"],
                    s["selection"],
                    s.get("bet_pct"),
                    s.get("handle_pct"),
                    ts_bucket,
                )
                ins = """
                INSERT INTO action_splits
                (id, event_id, market_type, selection, line, bet_pct, handle_pct, sharp_indicator, as_of_ts, fingerprint)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                ON CONFLICT (fingerprint) DO UPDATE SET
                    line = EXCLUDED.line,
                    bet_pct = EXCLUDED.bet_pct,
                    handle_pct = EXCLUDED.handle_pct,
                    sharp_indicator = EXCLUDED.sharp_indicator,
                    as_of_ts = CURRENT_TIMESTAMP
                """
                try:
                    _exec(
                        conn,
                        ins,
                        (
                            row_id,
                            str(event_id),
                            s["market"],
                            s["selection"],
                            s.get("line"),
                            s.get("bet_pct"),
                            s.get("handle_pct"),
                            s.get("sharp_indicator"),
                            fp,
                        ),
                    )
                    conn.commit()
                    saved += 1
                except Exception as exc:
                    print(f"[Enrichment] Split insert error for {event_id} ({s.get('market')} {s.get('selection')}): {exc}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass
        return saved
