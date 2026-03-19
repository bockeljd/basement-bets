import os
import time
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, Tuple
from pydantic import BaseModel, Field

from src.utils.naming import standardize_team_name

# --- Logging Setup ---
logger = logging.getLogger("basement_bets.ncaam_tournament")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# --- Canonical Typing Contracts ---

class TournamentGameInput(BaseModel):
    team_a: str
    team_b: str
    round_index: int
    region: Optional[str] = None
    market_snapshot: Optional[Dict[str, Any]] = None
    neutral_site: bool = True
    event_id: Optional[str] = None

class TournamentDataIssue(BaseModel):
    team: str
    issue_type: str
    description: str

class TournamentGamePrediction(BaseModel):
    team_a: str
    team_b: str
    winner: str
    winner_side: str  # 'team_a' or 'team_b'
    projected_spread_a: float
    projected_total: float
    win_prob_a: float
    win_prob_b: float
    confidence_0_100: float

    # Human-readable explanation for UI (2-3 short sentences).
    narrative: Optional[str] = None

    model_type: str = "tournament_ensemble_v1"
    neutral_site: bool = True
    market_data_used: bool = False
    fallback_used: bool = False
    reason_codes: List[str] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)
    debug: Dict[str, Any] = Field(default_factory=dict)
    scheduled_tip_et: Optional[str] = None
    tv_network: Optional[str] = None
    site: Optional[str] = None

# Round structure used in bracket simulation
class TournamentRoundPrediction(BaseModel):
    round_name: str
    matchups: List[TournamentGamePrediction]

class TournamentTeamAdvancement(BaseModel):
    team_name: str
    seed: int
    region: str
    r32_prob: float
    s16_prob: float
    e8_prob: float
    final_four_prob: float
    championship_prob: float
    champion_prob: float

class TournamentBracketSimulation(BaseModel):
    season: str
    simulated_at: str
    model_version: str
    regions: Dict[str, Dict[str, List[TournamentGamePrediction]]]
    first_four: List[TournamentGamePrediction]
    final_four: List[TournamentGamePrediction]
    championship: Optional[TournamentGamePrediction] = None
    champion: Optional[str] = None

    # A second bracket view intended for "perfect bracket" attempts.
    # Backend should populate it with a deterministic max-likelihood path.
    most_likely_bracket: Optional[Dict[str, Any]] = None

    title_odds: Dict[str, float] = Field(default_factory=dict)
    round_advancement_probs: List[TournamentTeamAdvancement] = Field(default_factory=list)
    degraded_simulation: bool = False
    data_issues: List[TournamentDataIssue] = Field(default_factory=list)

# --- Canonical Tournament Service ---

class SimulatorDataError(Exception):
    """Raised when critical data for simulation is missing."""
    pass


def _build_narrative(res: Dict[str, Any]) -> str:
    """Generate a 2-3 sentence narrative with concrete matchup facts.

    Uses best-effort KenPom team metrics + key players + news flags when available.
    Never throws.
    """

    def _f(d: Any, k: str) -> Optional[float]:
        try:
            if not isinstance(d, dict):
                return None
            v = d.get(k)
            return float(v) if v is not None else None
        except Exception:
            return None

    try:
        team_a = res.get('team_a')
        team_b = res.get('team_b')
        winner = res.get('winner')
        win_a = float(res.get('win_prob_a') or 0)
        win_b = float(res.get('win_prob_b') or 0)
        conf = float(res.get('confidence_0_100') or max(win_a, win_b))
        spread_a = res.get('projected_spread_a')
        total = res.get('projected_total')
        dbg = res.get('debug') or {}
        fallback = bool(res.get('fallback_used'))

        winner_prob = win_a if winner == team_a else win_b

        # implied margin from team_a spread
        margin = None
        try:
            if spread_a is not None:
                sa = float(spread_a)
                margin = abs((-sa) if winner == team_a else (sa))
        except Exception:
            margin = None

        sents: List[str] = []

        # 1) core prediction sentence
        try:
            if margin is not None and total is not None:
                sents.append(
                    f"{winner} is projected to advance as about a {margin:.1f}-point favorite on a neutral court "
                    f"({winner_prob:.0f}% win; confidence {conf:.0f}%), with an expected total of {float(total):.1f}."
                )
            elif margin is not None:
                sents.append(
                    f"{winner} is projected to advance as about a {margin:.1f}-point favorite on a neutral court "
                    f"({winner_prob:.0f}% win; confidence {conf:.0f}%)."
                )
            else:
                sents.append(f"{winner} is projected to advance ({winner_prob:.0f}% win; confidence {conf:.0f}%).")
        except Exception:
            sents.append(f"{winner} is projected to advance ({winner_prob:.0f}% win; confidence {conf:.0f}%).")

        # 2) style matchup (KenPom team metrics in debug)
        kp_a = dbg.get('kp_team_a')
        kp_b = dbg.get('kp_team_b')
        a_off, a_def = _f(kp_a, 'adj_o'), _f(kp_a, 'adj_d')
        b_off, b_def = _f(kp_b, 'adj_o'), _f(kp_b, 'adj_d')
        if a_off is not None and a_def is not None and b_off is not None and b_def is not None:
            if winner == team_a:
                sents.append(
                    f"Matchup-wise, {team_a}'s offense (AdjO {a_off:.1f}) tests {team_b}'s defense (AdjD {b_def:.1f}), "
                    f"and {team_a}'s defense (AdjD {a_def:.1f}) can pressure {team_b}'s offense (AdjO {b_off:.1f})."
                )
            else:
                sents.append(
                    f"Matchup-wise, {team_b}'s offense (AdjO {b_off:.1f}) tests {team_a}'s defense (AdjD {a_def:.1f}), "
                    f"and {team_b}'s defense (AdjD {b_def:.1f}) can disrupt {team_a}'s offense (AdjO {a_off:.1f})."
                )

        # 3) players + news notes (semicolon separated)
        tail: List[str] = []
        players = dbg.get('kp_key_players_a') if winner == team_a else dbg.get('kp_key_players_b')
        if isinstance(players, list) and players:
            bits = []
            for p in players[:2]:
                if not isinstance(p, dict):
                    continue
                nm = p.get('name')
                if not nm:
                    continue
                frag = nm
                try:
                    if p.get('ppg') is not None:
                        frag += f" ({float(p['ppg']):.1f} ppg)"
                    if p.get('usg') is not None:
                        frag += f" on {float(p['usg']):.0f}% usage"
                except Exception:
                    pass
                bits.append(frag)
            if bits:
                tail.append("Key creators: " + ", ".join(bits))

        if dbg.get('news_summary'):
            if dbg.get('news_has_injury'):
                tail.append(f"Injury/lineup headlines flagged ({dbg.get('news_summary')}); check sources before locking")
            else:
                tail.append(str(dbg.get('news_summary')))

        mod_diff = dbg.get('modifier_points_diff_a_minus_b')
        try:
            if mod_diff is not None and abs(float(mod_diff)) >= 1.0:
                if winner == team_a and float(mod_diff) > 0:
                    tail.append(f"Situational modifiers favor {team_a} by about {float(mod_diff):+.1f} pts")
                elif winner == team_b and float(mod_diff) < 0:
                    tail.append(f"Situational modifiers favor {team_b} by about {(-float(mod_diff)):+.1f} pts")
        except Exception:
            pass

        if fallback:
            tail.append("Data note: seed-based fallback used (missing a core metric feed)")

        if tail:
            sents.append("; ".join(tail) + ".")

        sents = [s.strip() for s in sents if s and s.strip()]
        return " ".join([s.rstrip('.') + '.' for s in sents[:3]])

    except Exception:
        return ""


class NCAAMTournamentPredictionService:
    """
    Canonical Service for NCAAM Tournament Game Predictions & Bracket Monte Carlo.
    This replaces scattershot logic in API routes, old model facades, and ad-hoc scripts.
    """
    
    def __init__(self):
        # We will lazy-load the model to avoid circular imports during initialization
        self._model = None
        
    @property
    def model(self):
        if self._model is None:
            from src.models.ncaam_market_first_model_v2 import NCAAMMarketFirstModelV2
            self._model = NCAAMMarketFirstModelV2()
        return self._model

    def predict_game(self, game_input: TournamentGameInput, conn=None) -> TournamentGamePrediction:
        """
        Predict a single tournament game using the canonical model tournament mode.
        """
        res = self.model.analyze_tournament_game(
            team_a=game_input.team_a,
            team_b=game_input.team_b,
            event_context={"start_time": datetime.now(), "id": game_input.event_id},
            market_snapshot=game_input.market_snapshot,
            persist=False,
            neutral_site=game_input.neutral_site,
            conn=conn
        )
        
        return TournamentGamePrediction(
            team_a=res['team_a'],
            team_b=res['team_b'],
            winner=res['winner'],
            winner_side=res['winner_side'],
            projected_spread_a=res['projected_spread_a'],
            projected_total=res['projected_total'],
            win_prob_a=res['win_prob_a'],
            win_prob_b=res['win_prob_b'],
            confidence_0_100=res['confidence_0_100'],
            narrative=_build_narrative(res),
            market_data_used=res['market_data_used'],
            fallback_used=res['fallback_used'],
            reason_codes=res['reason_codes'],
            risk_flags=res['risk_flags'],
            debug=res.get('debug', {}),
            neutral_site=game_input.neutral_site
        )

    def _normalize_match_key(self, team_a: str, team_b: str) -> Tuple[str, str]:
        return tuple(sorted([standardize_team_name(team_a), standardize_team_name(team_b)]))

    def preheat_cache(self, team_names: Set[str]) -> None:
        """
        Fetch all necessary data for the given teams upfront.
        Ensures simulation hits 0 database queries during the MC loop.
        Uses parallelism to overcome sequential DB latency.
        """
        from concurrent.futures import ThreadPoolExecutor
        
        # We share the model's service instances so their internal caches are populated
        def _heat_one(tname):
            from src.database import get_db_connection
            try:
                with get_db_connection() as conn:
                    # 1. Profile (Populates tf._profile_cache)
                    tf = self.model.tournament_features
                    tf.get_team_tournament_profile(tname, conn=conn)
                    
                    # 2. Torvik Metrics (Populates services._metrics_cache)
                    self.model.torvik_service._get_latest_metrics(tname, conn=conn)
                    
                    # 3. KenPom Ratings (Populates kp_client cache)
                    self.model.kenpom_client.get_team_rating(tname, conn=conn)
            except Exception as e:
                logging.error(f"Error preheating {tname}: {e}")

        # Use 10 workers to balance speed and connection limits
        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(_heat_one, team_names))

    def simulate_bracket(
        self,
        seeds: Dict[str, List[Dict[str, Any]]],
        simulations: int = 2500,
        locked_matchups: Optional[List[Dict[str, Any]]] = None
    ) -> TournamentBracketSimulation:
        """
        High-performance bracket simulation.
        1. Front-loads all DB reads.
        2. Executes MC in memory.
        """
        import time
        import random
        start_time = time.time()
        
        base_regions = ["East", "West", "South", "Midwest"]
        region_teams = {r: {} for r in base_regions}
        play_in_matchups = []
        all_team_names = set()
        locked_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
        if locked_matchups:
            for locked in locked_matchups:
                key = self._normalize_match_key(locked.get("team_a", ""), locked.get("team_b", ""))
                locked_map[key] = locked
        
        for region, team_list in seeds.items():
            if region not in base_regions: continue
            for item in team_list:
                seed = item['seed']
                tname = item['team_name']
                all_team_names.add(tname)

                if seed in region_teams[region]:
                    existing = region_teams[region][seed]
                    if isinstance(existing, list):
                        existing.append(tname)
                    else:
                        region_teams[region][seed] = [existing, tname]
                        play_in_matchups.append((region, seed, existing, tname))
                else:
                    region_teams[region][seed] = [tname]

        # 2. Exhaustive Front-load
        data_issues = []
        degraded_simulation = False
        fallback_count = 0
        affected_teams = set()
        _shared_cache = {}

        from src.database import get_db_connection
        with get_db_connection() as conn:
            # HEAT EVERYTHING (Parallel)
            preheat_start = time.time()
            self.preheat_cache(all_team_names)
            preheat_duration = time.time() - preheat_start
            logging.info(f"Preheated {len(all_team_names)} teams in {preheat_duration:.2f}s")
            
            def _get_game_result(target_a: str, target_b: str, round_name: str, conn=None) -> TournamentGamePrediction:
                nonlocal degraded_simulation, fallback_count
                k = tuple(sorted([target_a, target_b]))
                if k not in _shared_cache:
                    gi = TournamentGameInput(team_a=target_a, team_b=target_b, round_index=0, neutral_site=True)
                    try:
                        # Shared connection is critical here to reuse preheated caches
                        res = self.predict_game(gi, conn=conn)
                    except Exception as e:
                        degraded_simulation = True
                        fallback_count += 1
                        affected_teams.add(target_a)
                        affected_teams.add(target_b)
                        
                        # Seed-based prior fallback
                        seed_a = 8
                        seed_b = 8
                        for r_name, r_seeds in region_teams.items():
                            for s, tnames in r_seeds.items():
                                if target_a in tnames: seed_a = s
                                if target_b in tnames: seed_b = s
                        
                        raw_prob_a = 0.5 + (seed_b - seed_a) * 0.04
                        prob_a = max(0.05, min(0.95, raw_prob_a)) * 100.0
                        
                        data_issues.append(TournamentDataIssue(
                            team=f"{target_a}/{target_b}",
                            issue_type="MISSING_DATA",
                            description=f"Fallback used. Missing Torvik/KenPom metrics. Error: {str(e)}"
                        ))
                        
                        res = TournamentGamePrediction(
                            team_a=target_a, team_b=target_b,
                            winner=target_a if random.random() < (prob_a/100.0) else target_b,
                            winner_side="team_a",
                            projected_spread_a=-(seed_b - seed_a) * 2.0,
                            projected_total=142.0,
                            win_prob_a=prob_a,
                            win_prob_b=100.0 - prob_a,
                            confidence_0_100=40.0,
                            market_data_used=False,
                            fallback_used=True,
                            reason_codes=[f"Seed-based fallback prior used ({seed_a} vs {seed_b})."],
                            risk_flags=["MISSING_DATA", "DEGRADED_SIMULATION"],
                            neutral_site=True
                        )
                    _shared_cache[k] = res
                
                cached = _shared_cache[k]
                if cached.team_a == target_a:
                    return cached
                    
                # Swap logic
                swapped_k = (target_a, target_b, "swapped")
                if swapped_k not in _shared_cache:
                    _shared_cache[swapped_k] = TournamentGamePrediction(
                        team_a=target_a, team_b=target_b,
                        winner=cached.winner,
                        winner_side="team_a" if cached.winner == target_a else "team_b",
                        projected_spread_a=-cached.projected_spread_a,
                        projected_total=cached.projected_total,
                        win_prob_a=cached.win_prob_b,
                        win_prob_b=cached.win_prob_a,
                        confidence_0_100=cached.confidence_0_100,
                        market_data_used=cached.market_data_used,
                        fallback_used=cached.fallback_used,
                        reason_codes=cached.reason_codes,
                        risk_flags=cached.risk_flags,
                        debug=cached.debug,
                        neutral_site=True
                    )
                return _shared_cache[swapped_k]

            def _resolve_locked_winner(ta: str, tb: str) -> Optional[str]:
                norm_key = self._normalize_match_key(ta, tb)
                if norm_key not in locked_map:
                    return None
                locked = locked_map[norm_key]
                winner = locked.get("winner", ta)
                if winner not in (ta, tb):
                    winner = ta if standardize_team_name(winner) == standardize_team_name(ta) else tb
                return winner

            def _get_game_result_with_lock(ta: str, tb: str, rd: str, conn=None):
                """Return prediction object, but force winner if matchup is locked."""
                pred = _get_game_result(ta, tb, rd, conn=conn)
                locked_w = _resolve_locked_winner(ta, tb)
                if locked_w:
                    pred.winner = locked_w
                    pred.winner_side = 'team_a' if locked_w == ta else 'team_b'
                return pred

            # 3. Deterministic Bracket Construction (Front-loads cache)
            first_four_det = []
            det_region_teams = {r: {} for r in base_regions}
            for region, sdict in region_teams.items():
                for seed, lst in sdict.items():
                    if len(lst) == 2:
                        pred = _get_game_result_with_lock(lst[0], lst[1], "First Four", conn=conn)
                        first_four_det.append(pred)
                        det_region_teams[region][seed] = pred.winner
                    else:
                        det_region_teams[region][seed] = lst[0]

            det_regions = {}
            e8_winners_det = {}
            base_pairings = [(1, 16), (8, 9), (5, 12), (4, 13), (6, 11), (3, 14), (7, 10), (2, 15)]
            for region in base_regions:
                tm = det_region_teams[region]
                r64 = []
                for (s1, s2) in base_pairings:
                    if s1 in tm and s2 in tm: r64.append(_get_game_result_with_lock(tm[s1], tm[s2], "R64", conn=conn))
                r32 = []
                for i in range(0, len(r64), 2):
                    if i+1 < len(r64): r32.append(_get_game_result_with_lock(r64[i].winner, r64[i+1].winner, "R32", conn=conn))
                s16 = []
                for i in range(0, len(r32), 2):
                    if i+1 < len(r32): s16.append(_get_game_result_with_lock(r32[i].winner, r32[i+1].winner, "S16", conn=conn))
                e8 = []
                for i in range(0, len(s16), 2):
                    if i+1 < len(s16):
                        e8.append(_get_game_result_with_lock(s16[i].winner, s16[i+1].winner, "E8", conn=conn))
                        e8_winners_det[region] = e8[-1].winner
                det_regions[region] = {"round_of_64": r64, "round_of_32": r32, "sweet_16": s16, "elite_8": e8}

            final_four_det = []
            if "East" in e8_winners_det and "West" in e8_winners_det:
                 final_four_det.append(_get_game_result_with_lock(e8_winners_det["East"], e8_winners_det["West"], "FF", conn=conn))
            if "South" in e8_winners_det and "Midwest" in e8_winners_det:
                 final_four_det.append(_get_game_result_with_lock(e8_winners_det["South"], e8_winners_det["Midwest"], "FF", conn=conn))
            
            championship_det = None
            champion_det = None
            if len(final_four_det) == 2:
                 championship_det = _get_game_result_with_lock(final_four_det[0].winner, final_four_det[1].winner, "NCG", conn=conn)
                 champion_det = championship_det.winner

        # 4. In-Memory MC Simulation Loop
        advancements = {}
        for region, seeds_dict in region_teams.items():
            for seed, tlist in seeds_dict.items():
                for t in tlist:
                    advancements[t] = {
                        'R32': 0, 'S16': 0, 'E8': 0, 'FF': 0, 'NCG': 0, 'CHAMP': 0,
                        'seed': seed, 'region': region
                    }

        def _sim_matchup(ta: str, tb: str, rd: str) -> str:
            locked_w = _resolve_locked_winner(ta, tb)
            if locked_w:
                return locked_w
            pred = _get_game_result(ta, tb, rd)  # Hits memory cache
            return ta if random.random() < (pred.win_prob_a / 100.0) else tb

        # Track the most common full bracket observed across MC.
        # We only retain an example for the best signature to keep memory bounded.
        bracket_path_counts: Dict[Tuple[str, ...], int] = {}
        best_sig: Optional[Tuple[str, ...]] = None
        best_sig_count = 0
        best_sig_example: Optional[Dict[str, Any]] = None

        for _ in range(simulations):
            mc_region_teams = {r: {} for r in base_regions}
            for region, sdict in region_teams.items():
                for seed, lst in sdict.items():
                    if len(lst) == 2:
                        mc_region_teams[region][seed] = _sim_matchup(lst[0], lst[1], "First Four")
                    else:
                        mc_region_teams[region][seed] = lst[0]

            signature: List[str] = []
            sim_regions: Dict[str, Dict[str, List[Dict[str, Any]]]] = {r: {} for r in base_regions}

            e8_winners = {}
            for region in base_regions:
                tm = mc_region_teams[region]

                # R64
                r64_w = []
                r64_matches = []
                for (s1, s2) in base_pairings:
                    if s1 in tm and s2 in tm:
                        pred = _get_game_result(tm[s1], tm[s2], "R64")
                        w = tm[s1] if random.random() < (pred.win_prob_a / 100.0) else tm[s2]
                        r64_w.append(w)
                        signature.append(w)
                        dd = pred.model_dump()
                        dd['winner'] = w
                        dd['winner_side'] = 'team_a' if w == dd.get('team_a') else 'team_b'
                        r64_matches.append(dd)
                for w in r64_w:
                    advancements[w]['R32'] += 1
                sim_regions[region]['round_of_64'] = r64_matches

                # R32
                r32_w = []
                r32_matches = []
                for i in range(0, len(r64_w), 2):
                    if i + 1 < len(r64_w):
                        pred = _get_game_result(r64_w[i], r64_w[i + 1], "R32")
                        w = r64_w[i] if random.random() < (pred.win_prob_a / 100.0) else r64_w[i + 1]
                        r32_w.append(w)
                        signature.append(w)
                        dd = pred.model_dump()
                        dd['winner'] = w
                        dd['winner_side'] = 'team_a' if w == dd.get('team_a') else 'team_b'
                        r32_matches.append(dd)
                for w in r32_w:
                    advancements[w]['S16'] += 1
                sim_regions[region]['round_of_32'] = r32_matches

                # S16
                s16_w = []
                s16_matches = []
                for i in range(0, len(r32_w), 2):
                    if i + 1 < len(r32_w):
                        pred = _get_game_result(r32_w[i], r32_w[i + 1], "S16")
                        w = r32_w[i] if random.random() < (pred.win_prob_a / 100.0) else r32_w[i + 1]
                        s16_w.append(w)
                        signature.append(w)
                        dd = pred.model_dump()
                        dd['winner'] = w
                        dd['winner_side'] = 'team_a' if w == dd.get('team_a') else 'team_b'
                        s16_matches.append(dd)
                for w in s16_w:
                    advancements[w]['E8'] += 1
                sim_regions[region]['sweet_16'] = s16_matches

                # E8
                e8_w = []
                e8_matches = []
                for i in range(0, len(s16_w), 2):
                    if i + 1 < len(s16_w):
                        pred = _get_game_result(s16_w[i], s16_w[i + 1], "E8")
                        w = s16_w[i] if random.random() < (pred.win_prob_a / 100.0) else s16_w[i + 1]
                        e8_w.append(w)
                        signature.append(w)
                        dd = pred.model_dump()
                        dd['winner'] = w
                        dd['winner_side'] = 'team_a' if w == dd.get('team_a') else 'team_b'
                        e8_matches.append(dd)
                for w in e8_w:
                    advancements[w]['FF'] += 1
                sim_regions[region]['elite_8'] = e8_matches
                if e8_w:
                    e8_winners[region] = e8_w[0]

            # Final Four + Championship
            sim_final_four = []
            ff_w = []
            if "East" in e8_winners and "West" in e8_winners:
                pred = _get_game_result(e8_winners["East"], e8_winners["West"], "FF")
                w = pred.team_a if random.random() < (pred.win_prob_a / 100.0) else pred.team_b
                ff_w.append(w)
                signature.append(w)
                dd = pred.model_dump()
                dd['winner'] = w
                dd['winner_side'] = 'team_a' if w == dd.get('team_a') else 'team_b'
                sim_final_four.append(dd)
                advancements[w]['NCG'] += 1
            if "South" in e8_winners and "Midwest" in e8_winners:
                pred = _get_game_result(e8_winners["South"], e8_winners["Midwest"], "FF")
                w = pred.team_a if random.random() < (pred.win_prob_a / 100.0) else pred.team_b
                ff_w.append(w)
                signature.append(w)
                dd = pred.model_dump()
                dd['winner'] = w
                dd['winner_side'] = 'team_a' if w == dd.get('team_a') else 'team_b'
                sim_final_four.append(dd)
                advancements[w]['NCG'] += 1

            sim_championship = None
            sim_champion = None
            if len(ff_w) == 2:
                pred = _get_game_result(ff_w[0], ff_w[1], "NCG")
                w = pred.team_a if random.random() < (pred.win_prob_a / 100.0) else pred.team_b
                signature.append(w)
                dd = pred.model_dump()
                dd['winner'] = w
                dd['winner_side'] = 'team_a' if w == dd.get('team_a') else 'team_b'
                sim_championship = dd
                sim_champion = w
                advancements[w]['CHAMP'] += 1

            sig = tuple(signature)
            c = bracket_path_counts.get(sig, 0) + 1
            bracket_path_counts[sig] = c
            if c > best_sig_count:
                best_sig_count = c
                best_sig = sig
                best_sig_example = {
                    'regions': sim_regions,
                    'final_four': sim_final_four,
                    'championship': sim_championship,
                    'champion': sim_champion,
                }

        duration = time.time() - start_time
        logger.info(f"Bracket simulation completed: {simulations} iterations in {duration:.2f}s. Fallbacks: {fallback_count}. Degraded: {degraded_simulation}")
        if affected_teams:
            logger.warning(f"Teams affected by fallbacks: {list(affected_teams)}")

        adv_probs = [
            TournamentTeamAdvancement(
                team_name=t,
                seed=c['seed'],
                region=c['region'],
                r32_prob=round((c['R32'] / simulations) * 100, 2),
                s16_prob=round((c['S16'] / simulations) * 100, 2),
                e8_prob=round((c['E8'] / simulations) * 100, 2),
                final_four_prob=round((c['FF'] / simulations) * 100, 2),
                championship_prob=round((c['NCG'] / simulations) * 100, 2),
                champion_prob=round((c['CHAMP'] / simulations) * 100, 2)
            ) for t, c in advancements.items()
        ]
        adv_probs.sort(key=lambda x: x.champion_prob, reverse=True)
            
        # "Perfect" dashboard uses the most common full bracket observed in Monte Carlo.
        most_likely = best_sig_example or {
            "regions": {r: {k: [m.model_dump() for m in v] for k, v in rounds.items()} for r, rounds in det_regions.items()},
            "final_four": [m.model_dump() for m in final_four_det],
            "championship": championship_det.model_dump() if championship_det else None,
            "champion": champion_det,
        }

        return TournamentBracketSimulation(
            season="2025-26",
            simulated_at=datetime.now().isoformat(),
            model_version="tournament_ensemble_v1",
            regions=det_regions,
            first_four=first_four_det,
            final_four=final_four_det,
            championship=championship_det,
            champion=champion_det,
            most_likely_bracket=most_likely,
            title_odds={a.team_name: a.champion_prob for a in adv_probs if a.champion_prob > 0.0},
            round_advancement_probs=adv_probs,
            degraded_simulation=degraded_simulation,
            data_issues=data_issues
        )
