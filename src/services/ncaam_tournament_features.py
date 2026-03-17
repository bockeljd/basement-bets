import traceback
from typing import Dict, Any, List

class NCAAMTournamentFeatures:
    """
    Extracts deep analytics for a given team, calculating:
    - Continuity
    - Luck
    - Top-7 minutes %
    - Turnover rate
    - Upset Risk Score
    - Dark Horse Index
    - Q1 strength
    - Player aggregates
    These are used as bounded tournament modifiers.
    """
    
    def __init__(self):
        # We import here to avoid circular dependencies if any
        from src.services.kenpom_client import KenPomClient
        from src.utils.team_matcher import TeamMatcher
        self.kp_client = KenPomClient()
        self.matcher = TeamMatcher()
        self._profile_cache = {} # memoize team profiles for simulation loop
        
    def _safe_float(self, v, default=0.0):
        try:
            return float(str(v).replace('%','').replace('+','').strip())
        except Exception:
            return default

    def _parse_metric(self, metrics_jsonb, *candidates):
        if not metrics_jsonb:
            return None
        headers = metrics_jsonb.get('headers') or []
        cols = metrics_jsonb.get('cols') or []
        m = min(len(headers), len(cols))
        for i in range(m):
            hdr = str(headers[i] or '').lower()
            if any(c.lower() in hdr for c in candidates):
                return self._safe_float(cols[i])
        return None

    def get_team_tournament_profile(self, team: str, conn=None) -> Dict[str, Any]:
        if team in self._profile_cache:
            return self._profile_cache[team]
            
        if conn:
             return self._exec_profile(team, conn)
        else:
             from src.database import get_db_connection
             with get_db_connection() as c:
                  return self._exec_profile(team, c)

    def _exec_profile(self, team, conn):
        from src.database import _exec
        
        try:
            # 1. KenPom team rating
            kp_name = self.matcher.find_source_name(team, 'kenpom_ratings', 'team_name') or team
            kp_row = _exec(conn, """
                SELECT team_name, rank, conference, record, adj_em, adj_o, adj_d, adj_t
                FROM kenpom_ratings WHERE team_name = %s LIMIT 1
            """, (kp_name,)).fetchone()
            kenpom = dict(kp_row) if kp_row else {}

            # 2. NET rankings
            net_row = _exec(conn, """
                SELECT team_name, rank as net_rank, record,
                       quad1, quad2, quad3, quad4, home, road, neutral
                FROM ncaam_net_rankings
                WHERE LOWER(REPLACE(team_name,' ','')) = LOWER(REPLACE(%s,' ',''))
                LIMIT 1
            """, (team,)).fetchone()
            if not net_row:
                net_row = _exec(conn, """
                    SELECT team_name, rank as net_rank, record,
                           quad1, quad2, quad3, quad4, home, road, neutral
                    FROM ncaam_net_rankings
                    WHERE team_name ILIKE %s LIMIT 1
                """, (f'%{team.split()[0]}%',)).fetchone()
            net = dict(net_row) if net_row else {}

            # 3. Torvik / BartTorvik deep metrics
            torvik_name = self.matcher.find_source_name(team, 'bt_team_metrics_daily', 'team_text')
            torvik_row = None
            if torvik_name:
                try:
                    torvik_row = _exec(conn, """
                        SELECT adj_off, adj_def, adj_tempo, luck, continuity, torvik_rank, record
                        FROM bt_team_metrics_daily
                        WHERE team_text = %s
                        ORDER BY date DESC LIMIT 1
                    """, (torvik_name,)).fetchone()
                except Exception:
                    pass
            torvik = dict(torvik_row) if torvik_row else {}

            # Barthag from torvik_ratings
            torvik_rat_name = self.matcher.find_source_name(team, 'torvik_ratings', 'team_name')
            barthag = None
            if torvik_rat_name:
                try:
                    tr = _exec(conn, """
                        SELECT barthag, rank, adj_o, adj_d
                        FROM torvik_ratings WHERE team_name = %s LIMIT 1
                    """, (torvik_rat_name,)).fetchone()
                    if tr:
                        barthag = tr['barthag']
                        if not torvik.get('adj_off'):
                            torvik['adj_off'] = tr['adj_o']
                        if not torvik.get('adj_def'):
                            torvik['adj_def'] = tr['adj_d']
                        if not torvik.get('torvik_rank'):
                            torvik['torvik_rank'] = tr['rank']
                except Exception:
                    pass
            torvik['barthag'] = barthag

            # 4. Player stats
            raw_players = self.kp_client.get_player_stats_for_team(team, limit=40, conn=conn)

            def _player_minutes(p):
                return self._parse_metric(p.get('metrics'), 'min', 'minute') or 0

            raw_players.sort(key=_player_minutes, reverse=True)

            players = []
            for p in raw_players[:8]:
                m = p.get('metrics') or {}
                players.append({
                    'name':    p.get('player_name', 'Unknown'),
                    'ppg':     self._parse_metric(m, 'pts', 'ppg', 'points'),
                    'apg':     self._parse_metric(m, 'ast', 'apg', 'assist'),
                    'rpg':     self._parse_metric(m, 'reb', 'rpg', 'rebound'),
                    'ortg':    self._parse_metric(m, 'o-rat', 'ortg', 'off rat'),
                    'usg':     self._parse_metric(m, 'usag', 'usg', 'usage'),
                    'efg':     self._parse_metric(m, 'efg', 'eff fg', 'effective'),
                    'min_pct': self._parse_metric(m, '%min', 'min%', 'min pct', 'minute%') or _player_minutes(p),
                })

            # 5. Team player aggregates
            team_agg_row = self.kp_client.get_team_player_agg(team, conn=conn)
            team_agg = {}
            if team_agg_row:
                team_agg = {k: v for k, v in {
                    'ortg_w':       team_agg_row.get('ortg_w'),
                    'efg_w':        team_agg_row.get('efg_w'),
                    'ts_w':         team_agg_row.get('ts_w'),
                    'ast_rate_w':   team_agg_row.get('ast_rate_w'),
                    'reb_rate_w':   team_agg_row.get('reb_rate_w'),
                    'tov_rate_w':   team_agg_row.get('tov_rate_w'),
                    'top7_min_pct': team_agg_row.get('top7_minutes_pct'),
                    'n_players':    team_agg_row.get('n_players'),
                }.items() if v is not None}

            # 6. Upset Risk Score
            upset_score = 0
            upset_factors = []
            luck = self._safe_float(torvik.get('luck'), 0)
            continuity = self._safe_float(torvik.get('continuity'), 0)
            top7_min = self._safe_float(team_agg.get('top7_min_pct'), 0)
            kp_rank = int(kenpom.get('rank') or 50)
            net_rank_v = int(net.get('net_rank') or 50)
            tov_rate = self._safe_float(team_agg.get('tov_rate_w'), 0)

            if luck > 0.04:
                upset_score += 25
                upset_factors.append(f"Lucky season (+{luck:.2f}) — regression risk in pressure games")
            if top7_min > 88:
                upset_score += 20
                upset_factors.append(f"Over-reliant on top 7 ({top7_min:.0f}% mins) — foul trouble = collapse risk")
            if 0 < continuity < 60:
                upset_score += 20
                upset_factors.append(f"Low roster continuity ({continuity:.0f}%) — limited NCAA tournament experience")
            rank_gap = net_rank_v - kp_rank
            if rank_gap > 15:
                upset_score += 20
                upset_factors.append(f"Over-seeded: NET #{net_rank_v} vs KenPom #{kp_rank} (+{rank_gap} gap)")
            if tov_rate > 20:
                upset_score += 15
                upset_factors.append(f"High turnovers ({tov_rate:.1f}%) — vulnerable under pressure-game execution")
            if not upset_factors:
                upset_factors.append("No significant upset flags detected — solid fundamentals")

            # 7. Dark Horse Index
            dh_score = 0
            dh_factors = []
            adj_em = self._safe_float(kenpom.get('adj_em'), 0)
            bath_v = self._safe_float(barthag, 0)
            q1_raw = net.get('quad1') or '0-0'
            try:
                q1_wins = int(str(q1_raw).split('-')[0])
            except Exception:
                q1_wins = 0

            if bath_v > 0.88:
                dh_score += 30
                dh_factors.append(f"Elite Barthag ({bath_v*100:.1f}%) — underlying quality outpaces seeding")
            if luck < 0.00:
                dh_score += 20
                dh_factors.append(f"Unlucky season ({luck:.2f}) — due for positive regression in bracket")
            if continuity >= 75:
                dh_score += 20
                dh_factors.append(f"High roster continuity ({continuity:.0f}%) — experienced tournament rotation")
            if kp_rank > 12 and adj_em > 22:
                dh_score += 20
                dh_factors.append(f"Underrated efficiency: KP #{kp_rank} with AdjEM +{adj_em:.1f}")
            if q1_wins >= 6:
                dh_score += 10
                dh_factors.append(f"Strong Q1 resume ({q1_wins} wins) — proven vs elite")
            if not dh_factors:
                dh_factors.append("No significant dark horse signals — team is accurately seeded")

            def _clean(d):
                return {k: (str(v) if hasattr(v, 'isoformat') else v) for k, v in (d or {}).items()}

            return {
                'team_name':  team,
                'kenpom':     _clean(kenpom),
                'net':        _clean(net),
                'torvik':     _clean(torvik),
                'team_agg':   _clean(team_agg),
                'players':    players,
                'upset_risk': {'score': min(upset_score, 100), 'factors': upset_factors},
                'dark_horse': {'score': min(dh_score, 100), 'factors': dh_factors},
                
                # Extracted metrics for bounded multipliers
                'luck': luck,
                'continuity': continuity,
                'top7_min_pct': top7_min,
                'tov_rate': tov_rate,
                'q1_wins': q1_wins
            }
            self._profile_cache[team] = res
            return res

        except Exception as e:
            traceback.print_exc()
            return {
                'team_name': team,
                'error': str(e),
                'luck': 0.0,
                'continuity': 0.0,
                'top7_min_pct': 0.0,
                'tov_rate': 0.0,
                'q1_wins': 0,
                'upset_risk': {'score': 0, 'factors': []},
                'dark_horse': {'score': 0, 'factors': []}
            }

    def get_tournament_modifiers(self, team_name: str, conn=None) -> Dict[str, float]:
        """
        Calculates bounded modifiers for a specific team, specifically for use
        in tournament game simulation models.
        """
        profile = self.get_team_tournament_profile(team_name, conn=conn)
        
        # Bounded Modifiers:
        luck_modifier = 0.0
        # Luck > 0.04 implies lucky, negative for model (spread penalty)
        # Cap regression penalty strictly at ±1.5 points
        luck_val = profile.get('luck', 0)
        if luck_val > 0.04:
            luck_modifier = min(-1.5, -abs(luck_val * 10))
            luck_modifier = max(-2.5, luck_modifier) # Cap penalty
        elif luck_val < -0.04:
            luck_modifier = max(1.0, abs(luck_val * 10))
            luck_modifier = min(2.0, luck_modifier) # Cap bonus
            
        continuity_modifier = 0.0
        # High continuity = stability bump (Cap at ±0.5 points)
        cont_val = profile.get('continuity', 0)
        if cont_val > 75:
            continuity_modifier = 0.5
        elif cont_val < 50:
            continuity_modifier = -0.5
            
        turnover_modifier = 0.0
        # High turnovers = liability in tournament play (Cap at -1.0 points)
        if profile.get('tov_rate', 0) > 20:
            turnover_modifier = -1.0
            
        q1_modifier = 0.0
        # High end resume strength (Cap at +1.0 points)
        if profile.get('q1_wins', 0) >= 6:
            q1_modifier = 1.0

        top7_variance = 1.0
        # Missing starters / shallow bench (Cap at 15% variance boost)
        if profile.get('top7_min_pct', 0) > 85:
            top7_variance = 1.15
            
        modifiers = {
            'luck_adj_points': luck_modifier,
            'continuity_adj_points': continuity_modifier,
            'turnover_adj_points': turnover_modifier,
            'q1_adj_points': q1_modifier,
            'variance_multiplier': top7_variance,
            'upset_risk_score': profile.get('upset_risk', {}).get('score', 0),
            'upset_factors': profile.get('upset_risk', {}).get('factors', []),
            'dark_horse_score': profile.get('dark_horse', {}).get('score', 0),
            'dark_horse_factors': profile.get('dark_horse', {}).get('factors', [])
        }
        return modifiers
