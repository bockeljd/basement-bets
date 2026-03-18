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
    title_odds: Dict[str, float] = Field(default_factory=dict)
    round_advancement_probs: List[TournamentTeamAdvancement] = Field(default_factory=list)
    degraded_simulation: bool = False
    data_issues: List[TournamentDataIssue] = Field(default_factory=list)

# --- Canonical Tournament Service ---

class SimulatorDataError(Exception):
    """Raised when critical data for simulation is missing."""
    pass

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

        for _ in range(simulations):
            mc_region_teams = {r: {} for r in base_regions}
            for region, sdict in region_teams.items():
                for seed, lst in sdict.items():
                    if len(lst) == 2:
                        mc_region_teams[region][seed] = _sim_matchup(lst[0], lst[1], "First Four")
                    else:
                        mc_region_teams[region][seed] = lst[0]
            
            e8_winners = {}
            for region in base_regions:
                tm = mc_region_teams[region]
                r64_w = [_sim_matchup(tm[s1], tm[s2], "R64") for (s1, s2) in base_pairings if s1 in tm and s2 in tm]
                for w in r64_w: advancements[w]['R32'] += 1
                
                r32_w = [_sim_matchup(r64_w[i], r64_w[i+1], "R32") for i in range(0, len(r64_w), 2) if i+1 < len(r64_w)]
                for w in r32_w: advancements[w]['S16'] += 1
                
                s16_w = [_sim_matchup(r32_w[i], r32_w[i+1], "S16") for i in range(0, len(r32_w), 2) if i+1 < len(r32_w)]
                for w in s16_w: advancements[w]['E8'] += 1
                
                e8_w = [_sim_matchup(s16_w[i], s16_w[i+1], "E8") for i in range(0, len(s16_w), 2) if i+1 < len(s16_w)]
                for w in e8_w: advancements[w]['FF'] += 1
                if e8_w: e8_winners[region] = e8_w[0]
                
            ff_w = []
            if "East" in e8_winners and "West" in e8_winners:
                 w = _sim_matchup(e8_winners["East"], e8_winners["West"], "FF")
                 ff_w.append(w)
                 advancements[w]['NCG'] += 1
            if "South" in e8_winners and "Midwest" in e8_winners:
                 w = _sim_matchup(e8_winners["South"], e8_winners["Midwest"], "FF")
                 ff_w.append(w)
                 advancements[w]['NCG'] += 1
                 
            if len(ff_w) == 2:
                 ncg_w = _sim_matchup(ff_w[0], ff_w[1], "NCG")
                 advancements[ncg_w]['CHAMP'] += 1

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
            
        return TournamentBracketSimulation(
            season="2025-26",
            simulated_at=datetime.now().isoformat(),
            model_version="tournament_ensemble_v1",
            regions=det_regions,
            first_four=first_four_det,
            final_four=final_four_det,
            championship=championship_det,
            champion=champion_det,
            title_odds={a.team_name: a.champion_prob for a in adv_probs if a.champion_prob > 0.0},
            round_advancement_probs=adv_probs,
            degraded_simulation=degraded_simulation,
            data_issues=data_issues
        )
