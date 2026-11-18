import os
import math
import requests
import json
import time
import datetime
from typing import Dict, Any, Optional, Tuple
from zoneinfo import ZoneInfo

from src.database import get_db_connection, _exec  # Use shared DB logic

# Load env
from dotenv import load_dotenv
load_dotenv()

class OddsAPIClient:
    """
    The 'Toyota Hilux' of API Clients.
    Robust, Postgres-cached, and strictly capped within free-tier daily/monthly budgets.
    """
    BASE_URL = "https://api.the-odds-api.com/v4/sports"
    CACHE_DURATION = 3600  # 1 hour in seconds
    QUOTA_STATE_KEY = "odds_api:quota:state"
    SHARP_CACHE_KEY = "odds_api:sharp:basketball_ncaab"

    DEFAULT_MONTHLY_BUDGET = 460   # Free starter tier is 500/mo; reserve 40 safety buffer
    DEFAULT_DAILY_CAP = 14         # 14/day * 31 = 434/mo max (~7 calls/day at 2 credits/call)
    DEFAULT_MIN_REMAINING = 35     # Hard stop if live header x-requests-remaining drops <= 35
    DEFAULT_SHARP_BOOKMAKERS = "pinnacle,lowvig,betonlineag"  # <= 10 books = 1 region-equivalent
    DEFAULT_SHARP_MARKETS = "spreads,totals"  # 2 markets * 1 region = 2 credits/call

    def __init__(self):
        self.api_key = os.getenv("ODDS_API_KEY")
        if not self.api_key:
            print("[WARN] ODDS_API_KEY not found.")

        self._mem_cache: Dict[str, Tuple[Any, float]] = {}
        self._init_cache()

    @staticmethod
    def _db_disabled() -> bool:
        return str(os.getenv("REQUIRE_DATABASE", "")).strip() == "0"

    def _init_cache(self):
        """Initialize the cache table if not exists."""
        if self._db_disabled():
            return
        query = """
            CREATE TABLE IF NOT EXISTS api_cache (
                key TEXT PRIMARY KEY,
                response TEXT,
                timestamp REAL
            )
        """
        try:
            with get_db_connection() as conn:
                _exec(conn, query)
                conn.commit()
        except Exception as e:
            print(f"[OddsAPI] Cache Init Failed (Non-Fatal): {e}")

    def _get_cache_key(self, endpoint: str, params: Dict) -> str:
        """Generate a unique key for the request."""
        clean_params = {k: v for k, v in (params or {}).items() if k != "apiKey"}
        param_str = json.dumps(clean_params, sort_keys=True)
        return f"{endpoint}:{param_str}"

    def _read_cache_entry(self, key: str) -> Optional[Tuple[Any, float]]:
        """Read (parsed_payload, timestamp) from DB cache (or memory fallback)."""
        if self._db_disabled():
            return self._mem_cache.get(key)
        query = "SELECT response, timestamp FROM api_cache WHERE key = :k"
        try:
            with get_db_connection() as conn:
                row = _exec(conn, query, {"k": key}).fetchone()
                if row:
                    resp_raw = row["response"] if isinstance(row, dict) else row[0]
                    ts_raw = row["timestamp"] if isinstance(row, dict) else row[1]
                    return json.loads(resp_raw), float(ts_raw)
        except Exception as e:
            print(f"[OddsAPI] Cache Read Error: {e}")
        return self._mem_cache.get(key)

    def _get_from_cache(self, key: str, max_age: Optional[float] = None) -> Optional[Any]:
        """Retrieve from cache if within max_age (defaults to CACHE_DURATION)."""
        entry = self._read_cache_entry(key)
        if not entry:
            return None
        payload, ts = entry
        age = time.time() - float(ts)
        ttl = self.CACHE_DURATION if max_age is None else float(max_age)
        if age < ttl:
            print(f"  [CACHE HIT] Using cached data ({int(age)}s old)")
            return payload
        print(f"  [CACHE STALE] Data is {int(age)}s old")
        return None

    def _save_to_cache(self, key: str, data: Any):
        """Save response to cache atomically."""
        now_ts = time.time()
        self._mem_cache[key] = (data, now_ts)
        if self._db_disabled():
            return
        query = """
            INSERT INTO api_cache (key, response, timestamp)
            VALUES (:k, :resp, :ts)
            ON CONFLICT (key) DO UPDATE SET
              response = EXCLUDED.response,
              timestamp = EXCLUDED.timestamp
        """
        try:
            with get_db_connection() as conn:
                _exec(conn, query, {"k": key, "resp": json.dumps(data, default=str), "ts": now_ts})
                conn.commit()
        except Exception as e:
            print(f"[OddsAPI] Cache Write Error: {e}")

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        try:
            raw = os.getenv(name)
            return int(raw) if raw is not None and str(raw).strip() != "" else int(default)
        except Exception:
            return int(default)

    @classmethod
    def estimate_credit_cost(
        cls,
        markets: str = DEFAULT_SHARP_MARKETS,
        *,
        regions: Optional[str] = None,
        bookmakers: Optional[str] = None,
    ) -> int:
        """Compute The Odds API live credit cost: len(markets) * region_equivalents."""
        mkt_list = [m.strip() for m in str(markets or "").split(",") if m.strip()]
        n_mkts = max(1, len(mkt_list))
        if bookmakers:
            bk_list = [b.strip() for b in str(bookmakers).split(",") if b.strip()]
            n_reg = max(1, math.ceil(len(bk_list) / 10.0)) if bk_list else 1
        elif regions:
            rg_list = [r.strip() for r in str(regions).split(",") if r.strip()]
            n_reg = max(1, len(rg_list))
        else:
            n_reg = 1
        return n_mkts * n_reg

    def _load_quota_state(self) -> Dict[str, Any]:
        """Load and roll over daily (ET) & monthly quota counters."""
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        now_et = now_utc.astimezone(ZoneInfo("America/New_York"))
        day_et = now_et.strftime("%Y-%m-%d")
        month_ym = now_utc.strftime("%Y-%m")

        entry = self._read_cache_entry(self.QUOTA_STATE_KEY)
        state = dict(entry[0]) if (entry and isinstance(entry[0], dict)) else {}

        if state.get("month_ym") != month_ym:
            state["month_ym"] = month_ym
            state["month_credits_used"] = 0
            state["last_remaining"] = None
        if state.get("day_et") != day_et:
            state["day_et"] = day_et
            state["day_credits_used"] = 0

        state.setdefault("month_credits_used", 0)
        state.setdefault("day_credits_used", 0)
        state.setdefault("last_remaining", None)
        state.setdefault("last_used_header", None)
        state.setdefault("last_fetch_ts", 0.0)
        state.setdefault("cooldown_until", 0.0)
        state.setdefault("last_error", None)
        return state

    def _save_quota_state(self, state: Dict[str, Any]) -> None:
        self._save_to_cache(self.QUOTA_STATE_KEY, state)

    def get_budget_status(self) -> Dict[str, Any]:
        """Return current daily/monthly free-tier budget counters & hard caps."""
        st = self._load_quota_state()
        return {
            "month_ym": st.get("month_ym"),
            "day_et": st.get("day_et"),
            "month_credits_used": int(st.get("month_credits_used") or 0),
            "monthly_budget": self._env_int("ODDS_API_MONTHLY_BUDGET", self.DEFAULT_MONTHLY_BUDGET),
            "day_credits_used": int(st.get("day_credits_used") or 0),
            "daily_cap": self._env_int("ODDS_API_DAILY_CAP", self.DEFAULT_DAILY_CAP),
            "last_remaining": st.get("last_remaining"),
            "min_remaining": self._env_int("ODDS_API_MIN_REMAINING", self.DEFAULT_MIN_REMAINING),
            "last_error": st.get("last_error"),
        }

    def _can_spend_credits(self, state: Dict[str, Any], cost: int) -> Tuple[bool, str]:
        if not self.api_key:
            return False, "missing_api_key"
        now_ts = time.time()
        if float(state.get("cooldown_until") or 0.0) > now_ts:
            return False, "error_cooldown"

        daily_cap = self._env_int("ODDS_API_DAILY_CAP", self.DEFAULT_DAILY_CAP)
        monthly_budget = self._env_int("ODDS_API_MONTHLY_BUDGET", self.DEFAULT_MONTHLY_BUDGET)
        min_remaining = self._env_int("ODDS_API_MIN_REMAINING", self.DEFAULT_MIN_REMAINING)

        day_used = int(state.get("day_credits_used") or 0)
        month_used = int(state.get("month_credits_used") or 0)
        last_rem = state.get("last_remaining")

        if (day_used + cost) > daily_cap:
            return False, f"daily_cap_reached ({day_used}/{daily_cap})"
        if (month_used + cost) > monthly_budget:
            return False, f"monthly_budget_reached ({month_used}/{monthly_budget})"
        if last_rem is not None and (int(last_rem) - cost) < min_remaining:
            return False, f"min_remaining_guard ({last_rem} < {min_remaining + cost})"
        return True, "ok"

    def _record_api_response(
        self,
        state: Dict[str, Any],
        cost: int,
        headers: Optional[Dict[str, Any]] = None,
        *,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        hdrs = {str(k).lower(): v for k, v in (headers or {}).items()}
        rem_raw = hdrs.get("x-requests-remaining")
        used_raw = hdrs.get("x-requests-used")
        last_raw = hdrs.get("x-requests-last")

        actual_cost = cost
        if last_raw is not None:
            try:
                actual_cost = max(0, int(float(last_raw)))
            except Exception:
                actual_cost = cost

        if error is None:
            state["day_credits_used"] = int(state.get("day_credits_used") or 0) + actual_cost
            state["month_credits_used"] = int(state.get("month_credits_used") or 0) + actual_cost
            state["last_fetch_ts"] = time.time()
            state["cooldown_until"] = 0.0
            state["last_error"] = None
        else:
            state["last_error"] = str(error)[:200]
            state["cooldown_until"] = time.time() + 1800

        if rem_raw is not None:
            try:
                state["last_remaining"] = int(float(rem_raw))
            except Exception:
                pass
        if used_raw is not None:
            try:
                state["last_used_header"] = int(float(used_raw))
            except Exception:
                pass

        self._save_quota_state(state)
        return state

    def _active_ncaam_tip_window(self, horizon_hours: int = 10) -> Tuple[int, Optional[float]]:
        """Return (unstarted_event_count, minutes_until_next_tip) for NCAAM."""
        if self._db_disabled():
            return 1, 60.0
        q = """
        SELECT COUNT(*) AS cnt,
               EXTRACT(EPOCH FROM (MIN(start_time) - NOW())) / 60.0 AS mins_to_next
        FROM events
        WHERE league = 'NCAAM'
          AND start_time > NOW()
          AND start_time <= (NOW() + (:hrs * INTERVAL '1 hour'))
        """
        try:
            with get_db_connection() as conn:
                row = _exec(conn, q, {"hrs": int(horizon_hours)}).fetchone()
                if not row:
                    return 0, None
                cnt = int(row["cnt"] if isinstance(row, dict) else row[0] or 0)
                mins = row["mins_to_next"] if isinstance(row, dict) else row[1]
                return cnt, (float(mins) if mins is not None else None)
        except Exception as e:
            print(f"[OddsAPI] Active tip window check failed (skipping): {e}")
            return 0, None

    def fetch_ncaam_sharp_odds_budgeted(
        self,
        *,
        bookmakers: Optional[str] = None,
        markets: Optional[str] = None,
        odds_format: str = "american",
        force: bool = False,
    ) -> Dict[str, Any]:
        """Fetch NCAAM sharp bookmaker odds (Pinnacle/LowVig/BetOnline) strictly within free limits."""
        books = bookmakers or os.getenv("ODDS_API_SHARP_BOOKMAKERS") or self.DEFAULT_SHARP_BOOKMAKERS
        mkts = markets or os.getenv("ODDS_API_SHARP_MARKETS") or self.DEFAULT_SHARP_MARKETS
        cost = self.estimate_credit_cost(mkts, bookmakers=books)
        state = self._load_quota_state()

        cached_entry = self._read_cache_entry(self.SHARP_CACHE_KEY)
        cached_events = cached_entry[0] if (cached_entry and isinstance(cached_entry[0], list)) else []
        cache_age = (time.time() - float(cached_entry[1])) if cached_entry else None

        active_games, mins_to_next = self._active_ncaam_tip_window(horizon_hours=10)
        if not force and active_games <= 0:
            return {
                "status": "no_upcoming_games",
                "source": "skipped",
                "events": [],
                "credits_spent": 0,
                "budget": self.get_budget_status(),
            }

        # Peak pre-tip TTL (75m within 2.5h of tip), else 4h quiet TTL -> ~5-7 calls/day <= 14 credits
        peak_ttl = self._env_int("ODDS_API_PEAK_TTL_SECONDS", 4500)
        quiet_ttl = self._env_int("ODDS_API_QUIET_TTL_SECONDS", 14400)
        eff_ttl = peak_ttl if (mins_to_next is not None and mins_to_next <= 150.0) else quiet_ttl

        if not force and cached_entry is not None and cache_age is not None and cache_age < eff_ttl:
            return {
                "status": "cache_fresh",
                "source": "cache",
                "events": cached_events,
                "credits_spent": 0,
                "cache_age_seconds": int(cache_age),
                "ttl_seconds": int(eff_ttl),
                "budget": self.get_budget_status(),
            }

        ok, reason = self._can_spend_credits(state, cost)
        if not ok:
            return {
                "status": reason,
                "source": "stale_cache" if cached_events else "skipped",
                "events": cached_events,
                "credits_spent": 0,
                "budget": self.get_budget_status(),
            }

        url = f"{self.BASE_URL}/basketball_ncaab/odds"
        params = {
            "apiKey": self.api_key,
            "bookmakers": books,
            "markets": mkts,
            "oddsFormat": odds_format,
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                self._record_api_response(
                    state,
                    cost,
                    resp.headers,
                    error=f"HTTP {resp.status_code}: {(resp.text or '')[:120]}",
                )
                return {
                    "status": f"http_{resp.status_code}",
                    "source": "stale_cache" if cached_events else "error",
                    "events": cached_events,
                    "credits_spent": 0,
                    "budget": self.get_budget_status(),
                }

            data = resp.json()
            if not isinstance(data, list):
                data = []
            self._record_api_response(state, cost, resp.headers)
            self._save_to_cache(self.SHARP_CACHE_KEY, data)
            return {
                "status": "ok",
                "source": "live",
                "events": data,
                "credits_spent": cost,
                "budget": self.get_budget_status(),
            }
        except requests.exceptions.RequestException as e:
            self._record_api_response(state, cost, error=str(e))
            return {
                "status": "request_error",
                "source": "stale_cache" if cached_events else "error",
                "events": cached_events,
                "credits_spent": 0,
                "budget": self.get_budget_status(),
            }

    def _request(self, endpoint: str, params: Dict = {}) -> Any:
        """Internal request method with Postgres caching + free-tier budget guard."""
        req_params = dict(params or {})
        cache_key = self._get_cache_key(endpoint, req_params)

        cached_data = self._get_from_cache(cache_key)
        if cached_data is not None:
            return cached_data

        cost = self.estimate_credit_cost(
            req_params.get("markets", "h2h"),
            regions=req_params.get("regions"),
            bookmakers=req_params.get("bookmakers"),
        )
        state = self._load_quota_state()
        ok, reason = self._can_spend_credits(state, cost)
        if not ok:
            print(f"  [BUDGET GUARD] Skipping Odds API call ({reason})")
            return None

        req_params["apiKey"] = self.api_key
        url = f"{self.BASE_URL}/{endpoint}" if endpoint else self.BASE_URL
        print(f"  [API FETCH] Requesting {url}...")
        try:
            resp = requests.get(url, params=req_params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            self._record_api_response(state, cost, resp.headers)
            remaining = resp.headers.get('x-requests-remaining', '?')
            print(f"  [API USAGE] Remaining requests: {remaining}")
            self._save_to_cache(cache_key, data)
            return data
        except requests.exceptions.RequestException as e:
            resp_hdrs = getattr(getattr(e, "response", None), "headers", None)
            self._record_api_response(state, cost, resp_hdrs, error=str(e))
            print(f"  [API ERROR] {e}")
            return None

    def get_odds(self, sport_key: str, regions: str = 'us', markets: str = 'h2h,spreads,totals', odds_format: str = 'american') -> Any:
        """
        Fetch odds for a specific sport.
        Falls back to Action Network (Selenium) if Odds API is exhausted.
        """
        endpoint = f"{sport_key}/odds"
        params = {
            'regions': regions,
            'markets': markets,
            'oddsFormat': odds_format
        }
        
        # 1. Try Primary API
        data = self._request(endpoint, params)
        
        if data is not None:
             return data
        
        # 2. Fallback: ESPN (Free, Robust) - Specific for NCAAM
        if sport_key == "basketball_ncaab":
             print(f"  [FALLBACK] Odds API failed. Engaging ESPN Client for {sport_key}...")
             try:
                 cache_key = f"espn:odds:{sport_key}:{datetime.date.today()}"
                 cached = self._get_from_cache(cache_key)
                 if cached:
                     print("  [CACHE HIT] Using cached ESPN data.")
                     return cached
                 
                 from src.services.espn_ncaa_client import ESPNNCAAClient
                 espn = ESPNNCAAClient()
                 # Force today explicitly to avoid implicit TZ issues
                 today_str = datetime.date.today().strftime('%Y%m%d')
                 espn_data = espn.fetch_odds(date=today_str)
                 
                 if espn_data:
                      print(f"  [FALLBACK SUCCESS] Retrieved {len(espn_data)} events from ESPN.")
                      self._save_to_cache(cache_key, espn_data)
                      return espn_data
             except Exception as e:
                 print(f"  [ESPN FALLBACK ERROR] {e}")

        # 3. Fallback: Action Network (API)
        print(f"  [FALLBACK] Odds API failed. Engaging Action Network (API) for {sport_key}...")
        try:
            cache_key = f"action:odds:{sport_key}:{datetime.date.today()}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                 print(f"  [CACHE HIT] Using cached Action Network data.")
                 return cached_data

            from src.action_network import ActionNetworkClient
            scraper = ActionNetworkClient()
            fallback_data = scraper.fetch_odds(sport_key)
            
            if fallback_data:
                print(f"  [FALLBACK SUCCESS] Retrieved {len(fallback_data)} events from Action Network.")
                self._save_to_cache(cache_key, fallback_data)
                return fallback_data
            else:
                return []
        except Exception as e:
            print(f"  [FALLBACK ERROR] {e}")
            return []

    def get_scores(self, sport_key: str, days_from: int = 3) -> Any:
        """
        Fetch scores for a specific sport.
        Falls back to Action Network if Odds API is exhausted.
        """
        endpoint = f"{sport_key}/scores"
        params = {'daysFrom': days_from}
        
        # 1. Try Primary API
        data = self._request(endpoint, params)
        if data is not None:
            return data
            
        # 2. Fallback: Action Network (API)
        print(f"  [FALLBACK] Odds API failed. Engaging Action Network (API) for scores ({sport_key})...")
        try:
            cache_key = f"action:scores:{sport_key}:{datetime.date.today()}:{days_from}"
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                print("  [CACHE HIT] Using cached Action Network scores.")
                return cached_data

            from src.action_network import ActionNetworkClient
            scraper = ActionNetworkClient()
            
            # Generate list of dates for the last N days
            date_list = []
            today = datetime.date.today()
            for i in range(days_from + 1): 
                d = today - datetime.timedelta(days=i)
                date_list.append(d.strftime('%Y%m%d'))
            
            # fetch_odds returns full event objects which include scores/status
            fallback_data = scraper.fetch_odds(sport_key, date_list) 
            
            if fallback_data:
                self._save_to_cache(cache_key, fallback_data)
                return fallback_data
            return []
        except Exception as e:
            print(f"  [FALLBACK ERROR] {e}")
            return []


    def get_sports(self) -> Any:
        """List available sports."""
        return self._request("")

if __name__ == "__main__":
    # Test Driver
    try:
        client = OddsAPIClient()
        print("Testing OddsAPIClient...")
        
        # Test 2: Get NFL Odds (Example)
        odds = client.get_odds('americanfootball_nfl')
        if odds:
            print(f"Retrieved {len(odds)} NFL games.")
            if len(odds) > 0:
                 print(f"Sample: {odds[0].get('home_team')} vs {odds[0].get('away_team')}")
        else:
            print("Failed to retrieve odds.")

    except Exception as e:
        print(f"Initialization Error: {e}")
