import os
import sys
import json

# Add root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import get_db_connection, _exec

def _to_float(x):
    try:
        if x is None:
            return None
        s = str(x).replace('%','').replace('+','').strip()
        if s == '':
            return None
        return float(s)
    except Exception:
        return None

def _pair_headers(headers, cols):
    if not headers or not cols:
        return {}
    m = min(len(headers), len(cols))
    out = {}
    for i in range(m):
        k = str(headers[i]).strip() if headers[i] is not None else ''
        if not k:
            continue
        out[k] = cols[i]
    return out

def _find(mapping, candidates):
    for k, v in (mapping or {}).items():
        lk = str(k).lower()
        if any(c.lower() in lk for c in candidates):
            return v
    return None

def normalize_player_rows_standalone(player_rows):
    out = []
    for r in player_rows or []:
        m = (r.get('metrics') or {})
        headers = m.get('headers') or []
        cols = m.get('cols') or []
        mapping = _pair_headers(headers, cols)

        min_pct = _to_float(_find(mapping, ['min%','min %','%min','minutes%','minutes %']))
        minutes = _to_float(_find(mapping, ['min', 'minutes']))
        usage = _to_float(_find(mapping, ['usage']))
        ortg = _to_float(_find(mapping, ['ortg','off rtg','offensive rating']))
        efg = _to_float(_find(mapping, ['efg']))
        ts = _to_float(_find(mapping, ['ts%','ts %','true shooting']))
        ast_rate = _to_float(_find(mapping, ['ast%','assist%','assist %']))
        orb_rate = _to_float(_find(mapping, ['or%','off reb','off reb%','orb%']))
        drb_rate = _to_float(_find(mapping, ['dr%','def reb','def reb%','drb%']))
        tov_rate = _to_float(_find(mapping, ['to%','tov%','turnover%','turnover %']))
        ft_rate = _to_float(_find(mapping, ['ft rate','ftr']))
        three_par = _to_float(_find(mapping, ['3pa rate','3par','3pa/fg','3pa / fg']))

        out.append({
            'player_name': r.get('player_name'),
            'team_name': r.get('team_name') or '',
            'min_pct': min_pct,
            'minutes': minutes,
            'usage': usage,
            'ortg': ortg,
            'efg': efg,
            'ts': ts,
            'ast_rate': ast_rate,
            'orb_rate': orb_rate,
            'drb_rate': drb_rate,
            'tov_rate': tov_rate,
            'ft_rate': ft_rate,
            'three_par': three_par,
            'raw': {
                'headers': headers,
                'cols': cols,
            }
        })
    return out

def fix_all_player_stats():
    print("Beginning full re-normalization of player stats in DB...")
    with get_db_connection() as conn:
        # Fetch rows where player_name is likely a rank (indicates old bad format)
        rows = _exec(conn, "SELECT asof_date, player_name, team_name, raw FROM kenpom_player_stats_norm_daily WHERE player_name ~ '^[0-9]+$'").fetchall()
        print(f"Found {len(rows)} entries to fix.")
        
        # Group by asof_date
        by_date = {}
        for r in rows:
            d = r['asof_date']
            by_date.setdefault(d, []).append(r)
            
        total_updated = 0
        for asof, date_rows in by_date.items():
            print(f"Processing {asof} ({len(date_rows)} players)...")
            
            input_rows = []
            for r in date_rows:
                old_p = r['player_name'] # Rank
                old_t = r['team_name']   # Player Name
                raw = r['raw']           # {"headers": [...], "cols": [Team, Metrics...]}
                
                headers = raw.get('headers', [])
                partial_cols = raw.get('cols', [])
                
                # Reconstruct full cols
                full_cols = [old_p, old_t] + partial_cols
                
                # Use headers to find correct names
                h_idx = {h.lower(): i for i, h in enumerate(headers)}
                p_idx = h_idx.get('player', 1)
                t_idx = h_idx.get('team', 2)
                
                player = full_cols[p_idx] if len(full_cols) > p_idx else old_t
                team = full_cols[t_idx] if len(full_cols) > t_idx else "Unknown"
                
                input_rows.append({
                    'player_name': player,
                    'team_name': team,
                    'metrics': {'headers': headers, 'cols': full_cols}
                })
            
            # Normalize properly
            normed = normalize_player_rows_standalone(input_rows)
            
            # Delete old bad rows for this date (the ones with rank as name)
            _exec(conn, "DELETE FROM kenpom_player_stats_norm_daily WHERE asof_date = %s AND player_name ~ '^[0-9]+$'", (asof,))
            
            for p in normed:
                _exec(conn, """
                    INSERT INTO kenpom_player_stats_norm_daily (
                        asof_date, player_name, team_name,
                        min_pct, minutes, usage, ortg, efg, ts,
                        ast_rate, orb_rate, drb_rate, tov_rate,
                        ft_rate, three_par,
                        raw, updated_at
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        %s, NOW()
                    )
                    ON CONFLICT (asof_date, player_name, team_name) DO UPDATE SET
                        min_pct=EXCLUDED.min_pct,
                        minutes=EXCLUDED.minutes,
                        usage=EXCLUDED.usage,
                        ortg=EXCLUDED.ortg,
                        efg=EXCLUDED.efg,
                        ts=EXCLUDED.ts,
                        ast_rate=EXCLUDED.ast_rate,
                        orb_rate=EXCLUDED.orb_rate,
                        drb_rate=EXCLUDED.drb_rate,
                        tov_rate=EXCLUDED.tov_rate,
                        ft_rate=EXCLUDED.ft_rate,
                        three_par=EXCLUDED.three_par,
                        raw=EXCLUDED.raw,
                        updated_at=NOW()
                """, (
                    asof, p['player_name'], p['team_name'],
                    p['min_pct'], p['minutes'], p['usage'], p['ortg'], p['efg'], p['ts'],
                    p['ast_rate'], p['orb_rate'], p['drb_rate'], p['tov_rate'],
                    p['ft_rate'], p['three_par'],
                    json.dumps(p['raw'])
                ))
                total_updated += 1
        
        conn.commit()
    print(f"Successfully re-normalized {total_updated} player entries.")

if __name__ == "__main__":
    fix_all_player_stats()
