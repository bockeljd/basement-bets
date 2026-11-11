import json
import time
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from src.database import get_db_connection, _exec
from src.services.ncaam_bracket_state_service import NCAAMBracketStateService
from src.utils.ncaam_season import current_ncaam_season_short, format_ncaam_season_short

router = APIRouter()

# Local memory cache per season for ultra-fast hits (seconds)
_LOCAL_CACHE = {}
LOCAL_TTL = 180
DB_CACHE_TTL = 180


def _resolve_season_short(season_year: Optional[int] = None) -> str:
    if season_year is None:
        return current_ncaam_season_short()
    if season_year < 2024 or season_year > 2100:
        raise HTTPException(status_code=400, detail=f"Unsupported bracket season year: {season_year}")
    return format_ncaam_season_short(season_year)


def _get_db_cache(season: Optional[str] = None):
    """Fetch simulation from ncaam_bracket_cache table for the given season."""
    target_season = season or current_ncaam_season_short()
    try:
        with get_db_connection() as conn:
            row = _exec(
                conn,
                "SELECT data_json, updated_at FROM ncaam_bracket_cache WHERE season = %s",
                (target_season,),
            ).fetchone()
            if row:
                return {"data": row['data_json'], "updated_at": row['updated_at']}
    except Exception as e:
        print(f"[bracket-api] Cache read error ({target_season}): {e}")
    return None


def _save_db_cache(data, season: Optional[str] = None):
    """Save simulation to ncaam_bracket_cache table for the given season."""
    target_season = season or (data.get("season") if isinstance(data, dict) else None) or current_ncaam_season_short()
    try:
        with get_db_connection() as conn:
            _exec(conn, """
                INSERT INTO ncaam_bracket_cache (season, data_json, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (season) DO UPDATE SET data_json = EXCLUDED.data_json, updated_at = NOW()
            """, (target_season, json.dumps(data)))
            conn.commit()
            print(f"[bracket-api] Cache persisted to DB ({target_season}).")
    except Exception as e:
        print(f"[bracket-api] Cache write error ({target_season}): {e}")


def _debug_bracket_impl(season_short: str):
    db_cache = _get_db_cache(season=season_short)
    service = NCAAMBracketStateService(season=season_short)
    payload = service.build_bracket_payload()
    local_entry = _LOCAL_CACHE.get(season_short) or {"data": None, "expiry": 0}

    return {
        "status": "healthy",
        "season": season_short,
        "seed_source": payload.get("seed_metadata") or {},
        "local_cache": {
            "active": local_entry["data"] is not None,
            "expiry": local_entry["expiry"],
            "remaining": max(0, int(local_entry["expiry"] - time.time()))
        },
        "db_cache": {
            "present": db_cache is not None,
            "size": len(json.dumps(db_cache)) if db_cache else 0
        },
        "system_time": time.time()
    }


async def _get_bracket_impl(season_short: str, refresh: bool = False):
    current_time = time.time()
    local_entry = _LOCAL_CACHE.get(season_short)

    # 1. Local Memory Cache (Fastest)
    if not refresh and local_entry and local_entry.get("data") and current_time < local_entry.get("expiry", 0):
        return local_entry["data"]

    # 2. DB Cache (Faster than simulation)
    if not refresh:
        cached = _get_db_cache(season=season_short)
        if cached:
            cache_age = current_time - cached["updated_at"].timestamp()
            if cache_age < DB_CACHE_TTL:
                _LOCAL_CACHE[season_short] = {"data": cached["data"], "expiry": current_time + LOCAL_TTL}
                return cached["data"]

    # 3. Live Simulation (Compute)
    print(f"[bracket-api] Cache miss or refresh requested ({season_short}). Starting actual-first pipeline...")
    try:
        service = NCAAMBracketStateService(season=season_short)
        bracket_payload = service.build_bracket_payload()

        if isinstance(bracket_payload, dict) and bracket_payload.get("regions"):
            _save_db_cache(bracket_payload, season=season_short)
            _LOCAL_CACHE[season_short] = {"data": bracket_payload, "expiry": current_time + LOCAL_TTL}

        return bracket_payload

    except Exception as e:
        print(f"[bracket-api] Fatal Error ({season_short}): {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/ncaam/bracket/current/debug")
async def get_current_bracket_debug(request: Request):
    """Internal debug endpoint for active season bracket prediction health."""
    return _debug_bracket_impl(current_ncaam_season_short())


@router.post("/api/ncaam/bracket/current/recompute")
async def recompute_current_bracket(request: Request):
    """Force re-run the active season simulation and update the DB cache."""
    return await _get_bracket_impl(current_ncaam_season_short(), refresh=True)


@router.get("/api/ncaam/bracket/current")
async def get_current_bracket(request: Request, refresh: bool = False):
    """Return the active season bracket structure with real-time or cached simulations."""
    return await _get_bracket_impl(current_ncaam_season_short(), refresh=refresh)


@router.get("/api/ncaam/bracket/{season_year}/debug")
async def get_bracket_debug(season_year: int, request: Request):
    """Internal debug endpoint for bracket prediction health."""
    return _debug_bracket_impl(_resolve_season_short(season_year))


@router.post("/api/ncaam/bracket/{season_year}/recompute")
async def recompute_bracket(season_year: int, request: Request):
    """Force re-run the simulation and update the DB cache."""
    return await _get_bracket_impl(_resolve_season_short(season_year), refresh=True)


@router.get("/api/ncaam/bracket/{season_year}")
async def get_season_bracket(season_year: int, request: Request, refresh: bool = False):
    """Return the full bracket structure for season_year (e.g. 2027) with real-time or cached simulations."""
    return await _get_bracket_impl(_resolve_season_short(season_year), refresh=refresh)
