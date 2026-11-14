"""
KenPom Client for Ensemble Model

Fetches KenPom efficiency ratings from database and calculates adjustments
"""

import json
from typing import Dict, Optional, List, Any
from src.database import get_db_connection, _exec
from src.utils.ncaam_season import season_start_date_for_game
from src.utils.team_matcher import TeamMatcher

class KenPomClient:
    """Client for KenPom efficiency data + related daily tables."""
    
    def __init__(self):
        self.matcher = TeamMatcher()
        self._rating_cache = {} # memoize ratings for simulation loops

    def _latest_asof_date(self, table: str, asof_date: Optional[str] = None) -> Optional[str]:
        season_start = season_start_date_for_game(asof_date)
        with get_db_connection() as conn:
            row = _exec(
                conn,
                f"SELECT MAX(asof_date)::text AS d FROM {table} WHERE asof_date >= %s",
                (season_start,),
            ).fetchone()
            return row['d'] if row and row.get('d') else None

    def _pair_headers(self, headers: list[str] | None, cols: list[Any] | None) -> Dict[str, Any]:
        if not headers or not cols:
            return {}
        # Normalize lengths
        m = min(len(headers), len(cols))
        out = {}
        for i in range(m):
            k = str(headers[i]).strip() if headers[i] is not None else ''
            if not k:
                continue
            out[k] = cols[i]
        return out

    def _find_numeric(self, mapping: Dict[str, Any], candidates: List[str]) -> Optional[float]:
        """Fuzzy find numeric value by header substring candidates."""
        def to_f(x):
            try:
                if x is None:
                    return None
                s = str(x).replace('%','').replace('+','').strip()
                return float(s)
            except Exception:
                return None
        for k, v in (mapping or {}).items():
            lk = str(k).lower()
            if any(c.lower() in lk for c in candidates):
                f = to_f(v)
                if f is not None:
                    return f
        return None

    def get_team_rating(self, team_name: str, conn=None) -> Optional[Dict]:
        """
        Get KenPom rating for a team
        
        Args:
            team_name: Team name to lookup
            conn: Optional database connection to reuse
            
        Returns:
            Dict with adj_em, adj_o, adj_d, adj_t or None
        """
        # Ratings are stored as daily snapshots.
        matched_name = self.matcher.find_source_name(team_name, "kenpom_team_ratings_daily", "team_name")
        if not matched_name:
            return None

        if matched_name in self._rating_cache:
            return self._rating_cache[matched_name]

        if conn:
            return self._exec_rating_query(conn, matched_name)
        else:
            with get_db_connection() as c:
                return self._exec_rating_query(c, matched_name)

    def _exec_rating_query(self, conn, matched_name, asof_date: Optional[str] = None):
        season_start = season_start_date_for_game(asof_date)
        query = """
        SELECT team_name, rank, adj_em, adj_o, adj_d, adj_t, raw
        FROM kenpom_team_ratings_daily
        WHERE team_name = %s AND asof_date >= %s
        ORDER BY asof_date DESC
        LIMIT 1
        """
        cursor = _exec(conn, query, (matched_name, season_start))
        row = cursor.fetchone()
        
        res = None
        if row:
            raw_val = row.get('raw') if isinstance(row, dict) else (row[6] if len(row) > 6 else None)
            if isinstance(raw_val, str):
                try:
                    raw_val = json.loads(raw_val)
                except Exception:
                    raw_val = {}
            raw_dict = raw_val if isinstance(raw_val, dict) else {}
            res = {
                'team': row['team_name'] if isinstance(row, dict) else row[0],
                'rank': row['rank'] if isinstance(row, dict) else row[1],
                'adj_em': row['adj_em'] if isinstance(row, dict) else row[2],
                'adj_o': row['adj_o'] if isinstance(row, dict) else row[3],
                'adj_d': row['adj_d'] if isinstance(row, dict) else row[4],
                'adj_t': row['adj_t'] if isinstance(row, dict) else row[5],
                'luck': raw_dict.get('luck'),
                'sos_adj_em': raw_dict.get('sos_adj_em'),
                'opp_o': raw_dict.get('opp_o'),
                'opp_d': raw_dict.get('opp_d'),
                'ncsos_adj_em': raw_dict.get('ncsos_adj_em'),
                'off_efg': raw_dict.get('off_efg'),
                'off_to': raw_dict.get('off_to'),
                'off_or': raw_dict.get('off_or'),
                'off_ftr': raw_dict.get('off_ftr'),
                'def_efg': raw_dict.get('def_efg'),
                'def_to': raw_dict.get('def_to'),
                'def_or': raw_dict.get('def_or'),
                'def_ftr': raw_dict.get('def_ftr'),
                'avg_hgt': raw_dict.get('avg_hgt'),
                'eff_hgt': raw_dict.get('eff_hgt'),
                'experience': raw_dict.get('experience'),
                'bench_pct': raw_dict.get('bench_pct'),
                'continuity': raw_dict.get('continuity'),
            }
        
        self._rating_cache[matched_name] = res
        return res

    def get_home_court(self, team_name: str, conn=None) -> Optional[Dict]:
        matched_name = self.matcher.find_source_name(team_name, "kenpom_home_court_daily", "team_name")
        if not matched_name:
            return None

        if conn:
            return self._exec_home_court(conn, matched_name)
        else:
            with get_db_connection() as c:
                return self._exec_home_court(c, matched_name)

    def _exec_home_court(self, conn, matched_name, asof_date: Optional[str] = None):
        season_start = season_start_date_for_game(asof_date)
        row = _exec(conn, """
            SELECT team_name, hca, asof_date
            FROM kenpom_home_court_daily
            WHERE team_name=%s AND asof_date >= %s
            ORDER BY asof_date DESC
            LIMIT 1
        """, (matched_name, season_start)).fetchone()
        if not row:
            return None
        return {"team": row["team_name"], "hca": row["hca"], "asof_date": row["asof_date"]}

    def get_ref_metrics(self, ref_names: List[str], conn=None) -> List[Dict]:
        if not ref_names:
            return []
        
        if conn:
             return self._exec_ref_metrics(conn, ref_names)
        else:
             with get_db_connection() as c:
                  return self._exec_ref_metrics(c, ref_names)

    def _exec_ref_metrics(self, conn, ref_names):
        asof = self._latest_asof_date_internal(conn, 'kenpom_ref_ratings_daily')
        if not asof:
            return []

        outs = []
        for nm in ref_names:
            if not nm:
                continue
            row = _exec(conn, """
                SELECT ref_name, metrics, asof_date
                FROM kenpom_ref_ratings_daily
                WHERE asof_date=%s AND LOWER(ref_name)=LOWER(%s)
                LIMIT 1
            """, (asof, nm)).fetchone()
            if row:
                outs.append({"ref_name": row["ref_name"], "metrics": row["metrics"], "asof_date": row["asof_date"]})
        return outs

    def _latest_asof_date_internal(self, conn, table: str, asof_date: Optional[str] = None) -> Optional[str]:
        season_start = season_start_date_for_game(asof_date)
        row = _exec(
            conn,
            f"SELECT MAX(asof_date)::text AS d FROM {table} WHERE asof_date >= %s",
            (season_start,),
        ).fetchone()
        return row['d'] if row and row.get('d') else None

    def estimate_crew_avg_fouls(self, ref_names: List[str], conn=None) -> Optional[float]:
        """Best-effort: derive a crew avg fouls number from kenpom ref metrics, if headers exist."""
        refs = self.get_ref_metrics(ref_names, conn=conn)
        if not refs:
            return None

        vals = []
        for r in refs:
            m = r.get('metrics') or {}
            headers = m.get('headers') or []
            cols = m.get('cols') or []
            mapping = self._pair_headers(headers, cols)
            v = self._find_numeric(mapping, ["foul", "pf", "fouls/game", "fouls per game"])
            if v is not None:
                vals.append(v)
        if not vals:
            return None
        return sum(vals) / len(vals)

    def estimate_league_avg_ref_fouls(self, conn=None) -> Optional[float]:
        """Aggregate baseline when we *don't* have a crew assignment.

        Computes an average of whatever foul-rate column KenPom provides on the ref table.
        """
        if conn:
            return self._exec_league_avg_ref_fouls(conn)
        else:
            with get_db_connection() as c:
                return self._exec_league_avg_ref_fouls(c)

    def _exec_league_avg_ref_fouls(self, conn):
        asof = self._latest_asof_date_internal(conn, 'kenpom_ref_ratings_daily')
        if not asof:
            return None

        vals = []
        rows = _exec(conn, """
            SELECT metrics
            FROM kenpom_ref_ratings_daily
            WHERE asof_date=%s
        """, (asof,)).fetchall()
        for row in rows or []:
            m = (row['metrics'] if isinstance(row, dict) else row[0]) or {}
            headers = m.get('headers') or []
            cols = m.get('cols') or []
            mapping = self._pair_headers(headers, cols)
            v = self._find_numeric(mapping, ["foul", "pf", "fouls/game", "fouls per game"])
            if v is not None:
                vals.append(v)

        if not vals:
            return None
        return sum(vals) / len(vals)

    def get_team_player_agg(self, team_name: str, conn=None) -> Optional[Dict]:
        matched = self.matcher.find_source_name(team_name, "kenpom_team_player_agg_daily", "team_name")
        if not matched:
            return None
        
        if conn:
             return self._exec_player_agg(conn, matched)
        else:
             with get_db_connection() as c:
                  return self._exec_player_agg(c, matched)

    def _exec_player_agg(self, conn, matched):
        asof = self._latest_asof_date_internal(conn, 'kenpom_team_player_agg_daily')
        if not asof:
            return None

        row = _exec(conn, """
            SELECT team_name, asof_date, n_players, minutes_weight_sum,
                   ortg_w, usage_w, efg_w, ts_w, ast_rate_w, reb_rate_w,
                   tov_rate_w, ft_rate_w, three_par_w, top7_minutes_pct
            FROM kenpom_team_player_agg_daily
            WHERE asof_date=%s AND team_name=%s
            LIMIT 1
        """, (asof, matched)).fetchone()
        if not row:
            return None
        return dict(row)

    def get_player_stats_for_team(self, team_name: str, limit: int = 40, conn=None) -> List[Dict]:
        matched = self.matcher.find_source_name(team_name, "kenpom_player_stats_daily", "team_name")
        if not matched:
            return []
        
        if conn:
             return self._exec_player_stats(conn, matched, limit)
        else:
             with get_db_connection() as c:
                  return self._exec_player_stats(c, matched, limit)

    def _exec_player_stats(self, conn, matched, limit):
        asof = self._latest_asof_date_internal(conn, 'kenpom_player_stats_daily')
        if not asof:
            return []

        rows = _exec(conn, """
            SELECT player_name, team_name, metrics
            FROM kenpom_player_stats_daily
            WHERE asof_date=%s AND team_name=%s
            LIMIT %s
        """, (asof, matched, int(limit))).fetchall()
        out = []
        for row in rows or []:
            out.append({"player_name": row["player_name"], "team_name": row["team_name"], "metrics": row["metrics"]})
        return out

    def get_fanmatch_prediction(self, home_team: str, away_team: str, conn=None) -> Optional[Dict]:
        """Best-effort lookup of KenPom FanMatch daily prediction for home_team vs away_team."""
        try:
            matcher = getattr(self, "matcher", None)
            if matcher is None:
                return None
            h_match = matcher.find_source_name(home_team, "kenpom_fanmatch_daily", "home_team") or home_team
            a_match = matcher.find_source_name(away_team, "kenpom_fanmatch_daily", "away_team") or away_team
            season_start = season_start_date_for_game(None)

            def _query(c):
                row = _exec(
                    c,
                    """
                    SELECT asof_date::text AS asof_date, home_team, away_team,
                           pred_winner, winner_score, loser_score, win_prob, thrill_score
                    FROM kenpom_fanmatch_daily
                    WHERE asof_date >= %s
                      AND (
                        (LOWER(home_team) = LOWER(%s) AND LOWER(away_team) = LOWER(%s))
                        OR (LOWER(home_team) = LOWER(%s) AND LOWER(away_team) = LOWER(%s))
                      )
                    ORDER BY asof_date DESC
                    LIMIT 1
                    """,
                    (season_start, h_match, a_match, a_match, h_match),
                ).fetchone()
                if not row:
                    return None
                d = dict(row)
                w_sc = d.get("winner_score")
                l_sc = d.get("loser_score")
                winner = str(d.get("pred_winner") or "").strip()
                total = (float(w_sc) + float(l_sc)) if (w_sc is not None and l_sc is not None) else None
                margin_abs = abs(float(w_sc) - float(l_sc)) if (w_sc is not None and l_sc is not None) else None
                home_won = bool(
                    winner
                    and (
                        winner.lower() == str(h_match).lower()
                        or winner.lower() == str(home_team).lower()
                    )
                )
                home_margin = None
                if margin_abs is not None and winner:
                    home_margin = margin_abs if home_won else -margin_abs
                proj_score = None
                if w_sc is not None and l_sc is not None:
                    h_pts = int(round(w_sc if home_won else l_sc))
                    a_pts = int(round(l_sc if home_won else w_sc))
                    proj_score = f"{a_pts}-{h_pts}"
                return {
                    "asof_date": d.get("asof_date"),
                    "pred_winner": d.get("pred_winner"),
                    "winner_score": w_sc,
                    "loser_score": l_sc,
                    "win_prob": d.get("win_prob"),
                    "thrill_score": d.get("thrill_score"),
                    "fair_margin": home_margin,
                    "fair_total": total,
                    "projected_score": proj_score,
                }

            if conn is not None:
                return _query(conn)
            with get_db_connection() as c:
                return _query(c)
        except Exception:
            return None

    def calculate_kenpom_adjustment(
        self,
        home_team: str,
        away_team: str,
        conn=None,
        neutral_site: bool = False,
    ) -> Dict:
        """
        Calculate projected fair margin and total adjustment based on KenPom ratings.

        Logic:
        - AdjEM is neutral-court efficiency margin per 100 possessions.
        - Pace-scaled neutral margin = (Home AdjEM - Away AdjEM) * (avg_tempo / 100.0).
        - Fair home margin = neutral_margin + HCA (~3.2 pts on home court, 0.0 on neutral).
        - Total adjustment = (avg_tempo - 68.0) * 0.3.
        """
        home_rating = self.get_team_rating(home_team, conn=conn)
        away_rating = self.get_team_rating(away_team, conn=conn)

        if not home_rating or not away_rating:
            return {
                'spread_adj': 0.0,
                'neutral_margin': 0.0,
                'fair_margin': 0.0,
                'total_adj': 0.0,
                'summary': 'KenPom data not available'
            }

        baseline_tempo = 68.0
        h_tempo = float(home_rating.get('adj_t') or baseline_tempo)
        a_tempo = float(away_rating.get('adj_t') or baseline_tempo)
        avg_tempo = (h_tempo + a_tempo) / 2.0
        expected_tempo = (
            max(55.0, min(85.0, h_tempo + a_tempo - baseline_tempo))
            if (h_tempo > 40.0 and a_tempo > 40.0)
            else avg_tempo
        )

        em_diff = float(home_rating.get('adj_em') or 0.0) - float(away_rating.get('adj_em') or 0.0)
        neutral_margin = em_diff * (avg_tempo / 100.0)
        hca = 0.0 if neutral_site else 3.2
        fair_margin = neutral_margin + hca
        spread_adj = fair_margin

        # Total adjustment based on tempo (preserved for backwards-compatible callers/tests)
        total_adj = (avg_tempo - baseline_tempo) * 0.3

        # True efficiency-based total projection when AdjO & AdjD are available
        h_adj_o = float(home_rating.get('adj_o') or 0.0)
        h_adj_d = float(home_rating.get('adj_d') or 0.0)
        a_adj_o = float(away_rating.get('adj_o') or 0.0)
        a_adj_d = float(away_rating.get('adj_d') or 0.0)
        fair_total = None
        projected_score = None
        if h_adj_o > 50.0 and h_adj_d > 50.0 and a_adj_o > 50.0 and a_adj_d > 50.0:
            d1_avg_eff = 106.5
            hca_ppp = 0.0 if neutral_site else (hca * 0.5)
            h_ppp = ((h_adj_o * a_adj_d) / d1_avg_eff) + hca_ppp
            a_ppp = ((a_adj_o * h_adj_d) / d1_avg_eff) - hca_ppp
            home_score = h_ppp * (expected_tempo / 100.0)
            away_score = a_ppp * (expected_tempo / 100.0)
            fair_total = round(home_score + away_score, 1)
            projected_score = f"{int(round(away_score))}-{int(round(home_score))}"

        def _opt_float(v):
            try:
                return float(v) if v is not None else None
            except Exception:
                return None

        h_luck = _opt_float(home_rating.get('luck'))
        a_luck = _opt_float(away_rating.get('luck'))
        h_sos = _opt_float(home_rating.get('sos_adj_em'))
        a_sos = _opt_float(away_rating.get('sos_adj_em'))
        h_ncsos = _opt_float(home_rating.get('ncsos_adj_em'))
        a_ncsos = _opt_float(away_rating.get('ncsos_adj_em'))

        luck_diff = round(h_luck - a_luck, 3) if (h_luck is not None and a_luck is not None) else None
        sos_diff = round(h_sos - a_sos, 2) if (h_sos is not None and a_sos is not None) else None
        ncsos_diff = round(h_ncsos - a_ncsos, 2) if (h_ncsos is not None and a_ncsos is not None) else None
        raw_sos_adj = ((sos_diff or 0.0) * 0.05) + ((ncsos_diff or 0.0) * 0.03)
        sos_spread_adj = round(max(-1.0, min(1.0, raw_sos_adj)), 2) if (sos_diff is not None or ncsos_diff is not None) else 0.0

        # Four Factors matchup edge (eFG%, TO%, OR%, FTRate)
        h_off_efg = _opt_float(home_rating.get('off_efg'))
        h_def_efg = _opt_float(home_rating.get('def_efg'))
        a_off_efg = _opt_float(away_rating.get('off_efg'))
        a_def_efg = _opt_float(away_rating.get('def_efg'))
        four_factors_adj = 0.0
        if None not in (h_off_efg, h_def_efg, a_off_efg, a_def_efg):
            efg_diff = ((h_off_efg - a_def_efg) - (a_off_efg - h_def_efg)) * 0.5
            h_off_to = _opt_float(home_rating.get('off_to'))
            h_def_to = _opt_float(home_rating.get('def_to'))
            a_off_to = _opt_float(away_rating.get('off_to'))
            a_def_to = _opt_float(away_rating.get('def_to'))
            to_diff = 0.0
            if None not in (h_off_to, h_def_to, a_off_to, a_def_to):
                to_diff = ((a_off_to + h_def_to) - (h_off_to + a_def_to)) * 0.5
            h_off_or = _opt_float(home_rating.get('off_or'))
            h_def_or = _opt_float(home_rating.get('def_or'))
            a_off_or = _opt_float(away_rating.get('off_or'))
            a_def_or = _opt_float(away_rating.get('def_or'))
            or_diff = 0.0
            if None not in (h_off_or, h_def_or, a_off_or, a_def_or):
                or_diff = ((h_off_or + a_def_or) - (a_off_or + h_def_or)) * 0.5
            h_off_ftr = _opt_float(home_rating.get('off_ftr'))
            h_def_ftr = _opt_float(home_rating.get('def_ftr'))
            a_off_ftr = _opt_float(away_rating.get('off_ftr'))
            a_def_ftr = _opt_float(away_rating.get('def_ftr'))
            ftr_diff = 0.0
            if None not in (h_off_ftr, h_def_ftr, a_off_ftr, a_def_ftr):
                ftr_diff = ((h_off_ftr + a_def_ftr) - (a_off_ftr + h_def_ftr)) * 0.5
            raw_ff = (efg_diff * 0.12) + (to_diff * 0.08) + (or_diff * 0.06) + (ftr_diff * 0.04)
            four_factors_adj = round(max(-1.2, min(1.2, raw_ff)), 2)

        # Experience & Effective Height matchup edge
        h_exp = _opt_float(home_rating.get('experience'))
        a_exp = _opt_float(away_rating.get('experience'))
        h_eff_hgt = _opt_float(home_rating.get('eff_hgt')) or _opt_float(home_rating.get('avg_hgt'))
        a_eff_hgt = _opt_float(away_rating.get('eff_hgt')) or _opt_float(away_rating.get('avg_hgt'))
        raw_eh = 0.0
        if h_exp is not None and a_exp is not None:
            raw_eh += (h_exp - a_exp) * 0.30
        if h_eff_hgt is not None and a_eff_hgt is not None:
            raw_eh += (h_eff_hgt - a_eff_hgt) * 0.10
        exp_height_adj = round(max(-0.75, min(0.75, raw_eh)), 2) if (
            (h_exp is not None and a_exp is not None) or (h_eff_hgt is not None and a_eff_hgt is not None)
        ) else 0.0

        h_cont = _opt_float(home_rating.get('continuity'))
        a_cont = _opt_float(away_rating.get('continuity'))
        fanmatch = self.get_fanmatch_prediction(home_team, away_team, conn=conn) if hasattr(self, "get_fanmatch_prediction") else None

        summary = f"KenPom: {home_rating['team']} (#{home_rating['rank']}) vs {away_rating['team']} (#{away_rating['rank']})"

        return {
            'spread_adj': round(spread_adj, 1),
            'neutral_margin': round(neutral_margin, 1),
            'fair_margin': round(fair_margin, 1),
            'total_adj': round(total_adj, 1),
            'fair_total': fair_total,
            'projected_score': projected_score,
            'expected_tempo': round(expected_tempo, 1),
            'avg_tempo': round(avg_tempo, 1),
            'luck_diff': luck_diff,
            'sos_diff': sos_diff,
            'ncsos_diff': ncsos_diff,
            'sos_spread_adj': sos_spread_adj,
            'four_factors_adj': four_factors_adj,
            'exp_height_adj': exp_height_adj,
            'home_continuity': h_cont,
            'away_continuity': a_cont,
            'home_experience': h_exp,
            'away_experience': a_exp,
            'fanmatch': fanmatch,
            'home_luck': h_luck,
            'away_luck': a_luck,
            'home_sos': h_sos,
            'away_sos': a_sos,
            'home_ncsos': h_ncsos,
            'away_ncsos': a_ncsos,
            'summary': summary,
            'home_adj_em': home_rating['adj_em'],
            'away_adj_em': away_rating['adj_em'],
            'home_rank': home_rating.get('rank'),
            'away_rank': away_rating.get('rank'),
        }


# Example usage
if __name__ == "__main__":
    client = KenPomClient()
    
    # Test lookup
    duke = client.get_team_rating("Duke")
    if duke:
        print(f"Duke: #{duke['rank']} - AdjEM {duke['adj_em']:.2f}")
    
    # Test adjustment
    adj = client.calculate_kenpom_adjustment("Duke", "North Carolina")
    print(f"\nKenPom Adjustment:")
    print(f"  Spread: {adj['spread_adj']:+.1f} pts")
    print(f"  Total: {adj['total_adj']:+.1f} pts")
    print(f"  {adj['summary']}")
