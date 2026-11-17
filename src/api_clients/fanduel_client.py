
import requests
import json
from datetime import datetime
from typing import List, Dict, Any

class FanDuelAPIClient:
    """
    Direct API Client for FanDuel Sportsbook.
    Uses headers extracted from browser session to fetch bet history.
    """

    BASE_URL = "https://api.sportsbook.fanduel.com/sbapi/fetch-my-bets"

    def __init__(self, auth_token: str, app_version: str = "2.135.2", region: str = "OH"):
        # Token often gets copied with whitespace/newlines; requests will reject invalid header values.
        if auth_token is None:
            auth_token = ""
        auth_token = str(auth_token).strip()
        # If someone accidentally pasted multiple tokens/lines, take the first whitespace-delimited chunk.
        if " " in auth_token or "\n" in auth_token or "\t" in auth_token:
            auth_token = auth_token.split()[0]

        self.auth_token = auth_token
        self.headers = {
            'accept': 'application/json',
            'accept-language': 'en-US,en;q=0.9',
            'origin': f'https://{region.lower()}.sportsbook.fanduel.com',
            'referer': f'https://{region.lower()}.sportsbook.fanduel.com/',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36',
            'x-app-version': app_version,
            'x-application': 'FhMFpcPWXMeyZxOx', # App Key seems static
            'x-authentication': auth_token,
            'x-sportsbook-region': region
        }

    def fetch_bets(self, from_record=1, to_record=50, is_settled: bool = True) -> List[Dict]:
        """
        Fetches settled or open bets from the FanDuel API.
        """
        params = {
            'isSettled': 'true' if is_settled else 'false',
            'fromRecord': from_record,
            'toRecord': to_record,
            'sortDir': 'DESC',
            'sortParam': 'SETTLEMENT_DATE' if is_settled else 'PLACED_DATE',
            'adaptiveTokenEnabled': 'false',
            '_ak': 'FhMFpcPWXMeyZxOx'
        }

        try:
            response = requests.get(self.BASE_URL, headers=self.headers, params=params, timeout=20)
            response.raise_for_status()
            data = response.json()
            return self._parse_api_response(data, default_settled=is_settled)
        except Exception as e:
            print(f"[FanDuelAPI] Error: {e}")
            if hasattr(e, 'response') and e.response:
                print(e.response.text)
            return []

    def fetch_all_recent_bets(self, settled_limit: int = 100, open_limit: int = 50) -> List[Dict]:
        """Fetch both open (PENDING) and settled bets, deduplicated by external_id."""
        combined: List[Dict] = []
        seen_ext = set()
        for is_settled, to_rec in ((False, open_limit), (True, settled_limit)):
            rows = self.fetch_bets(from_record=1, to_record=to_rec, is_settled=is_settled)
            for row in rows:
                ext = row.get("external_id")
                if ext:
                    if ext in seen_ext:
                        continue
                    seen_ext.add(ext)
                combined.append(row)
        return combined

    def _parse_api_response(self, data: Dict, default_settled: bool = True) -> List[Dict]:
        """
        Parses the JSON response into our standard Bet format.
        """
        if not data or 'bets' not in data:
            return []

        from src.services.bet_sync_service import (
            _resolve_sport_label,
            decimal_to_american,
            normalize_bet_status,
        )

        parsed_bets = []
        for bet in data.get('bets', []):
            try:
                # Extract fields
                date_raw = bet.get('placedDate') or bet.get('settledDate')
                placed_at_str = None
                if isinstance(date_raw, str):
                    date_obj = datetime.fromisoformat(date_raw.replace('Z', '+00:00'))
                    date_str = date_obj.strftime('%Y-%m-%d')
                    placed_at_str = date_obj.isoformat()
                else:
                    placed_ts = int(date_raw or 0)
                    dt_obj = datetime.fromtimestamp(placed_ts / 1000) if placed_ts else datetime.now()
                    date_str = dt_obj.strftime('%Y-%m-%d')
                    placed_at_str = dt_obj.isoformat()

                stake = float(bet.get('currentSize') or bet.get('betPrice') or bet.get('stake') or 0)
                payout = float(
                    bet.get('payout')
                    or bet.get('settledPayout')
                    or bet.get('paid')
                    or 0
                )

                is_settled_flag = bet.get('isSettled')
                if is_settled_flag is None:
                    is_settled_flag = default_settled

                raw_result = str(bet.get('settledResult') or bet.get('result') or bet.get('status') or '').strip().upper()
                if not is_settled_flag and not raw_result:
                    raw_result = 'PENDING'
                elif not raw_result:
                    raw_result = 'UNKNOWN'

                if raw_result in ('LOSS', 'LOST'):
                    payout = 0.0

                status = normalize_bet_status(
                    raw_result if raw_result != 'UNKNOWN' else ('WON' if payout > 0 else 'PENDING'),
                    profit=(payout - stake) if raw_result not in ('PENDING', 'OPEN', 'VOID', 'PUSH') else None,
                    wager=stake,
                    payout=payout,
                )

                if status == 'PENDING':
                    profit = 0.0
                elif status in ('VOID', 'PUSH'):
                    profit = 0.0
                elif status == 'LOST' and raw_result in ('LOSS', 'LOST'):
                    profit = -stake
                else:
                    profit = round(payout - stake, 2)

                # Bet type normalization
                raw_bt = str(bet.get('betType', 'Straight') or 'Straight').upper()
                legs = bet.get('legs', []) or []
                if raw_bt == 'SGL':
                    part_count = 0
                    for leg in legs:
                        part_count += len(leg.get('parts', []) or [])
                    bet_type = 'SGP' if (len(legs) > 1 or part_count > 1) else 'Straight'
                else:
                    bet_type = bet.get('betType', 'Straight')

                descriptions = []
                events = []
                sport = "Unknown"
                is_live = bool(bet.get('isInPlay') or bet.get('inPlay') or bet.get('isLive'))

                for leg in legs:
                    if leg.get('inPlay') or leg.get('isInPlay'):
                        is_live = True
                    parts = leg.get('parts', []) or []
                    for part in parts:
                        if part.get('inPlay') or part.get('isInPlay'):
                            is_live = True
                        sel_name = part.get('selectionName', '')
                        market_name = part.get('eventMarketDescription', '')
                        event_name = part.get('eventDescription', '')
                        if event_name and event_name not in events:
                            events.append(event_name)

                        desc_str = f"{sel_name} ({market_name})" if market_name else str(sel_name)
                        if desc_str.strip():
                            descriptions.append(desc_str)

                        comp = str(part.get('competitionName') or part.get('sportName') or '').strip()
                        if comp:
                            inferred = _resolve_sport_label(comp, description=event_name, selection=sel_name)
                            if inferred and inferred not in ('UNKNOWN', 'Other'):
                                sport = inferred

                full_desc = " | ".join(descriptions)
                if not full_desc:
                    full_desc = f"{bet_type} (No legs found)"
                event_summary = " / ".join(events[:2]) if events else None

                # Odds: prefer structured american odds on the bet; fall back to decimal or first part price.
                odds_val = None
                try:
                    raw_odds = bet.get('odds')
                    if isinstance(raw_odds, dict):
                        odds_val = raw_odds.get('american')
                        if not odds_val and raw_odds.get('decimal'):
                            odds_val = decimal_to_american(float(raw_odds['decimal']))
                    elif isinstance(raw_odds, (int, float)):
                        odds_val = int(raw_odds)
                except Exception:
                    odds_val = None
                if not odds_val:
                    try:
                        for leg in legs:
                            for part in (leg.get('parts', []) or []):
                                ap = part.get('americanPrice')
                                if ap is not None:
                                    odds_val = int(ap)
                                    raise StopIteration
                                dp = part.get('decimalPrice')
                                if dp is not None and float(dp) > 1.0:
                                    odds_val = decimal_to_american(float(dp))
                                    raise StopIteration
                    except StopIteration:
                        pass
                    except Exception:
                        pass

                ext_id = str(bet.get('betId') or bet.get('id') or '').strip() or None
                bet_obj = {
                    "provider": "FanDuel",
                    "external_id": ext_id,
                    "date": date_str,
                    "placed_at": placed_at_str,
                    "sport": sport,
                    "bet_type": bet_type,
                    "wager": stake,
                    "profit": profit,
                    "status": status,
                    "event_name": event_summary,
                    "description": event_summary or full_desc,
                    "selection": full_desc,
                    "odds": odds_val,
                    "is_live": is_live,
                    "is_bonus": bool(bet.get('isBonus') or bet.get('bonusBet')),
                    "source": "fanduel_api",
                    "raw_text": str(bet)
                }

                parsed_bets.append(bet_obj)
            except Exception as e:
                print(f"Failed to parse bet: {e}")

        return parsed_bets
