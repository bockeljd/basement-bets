import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field

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

    def predict_game(self, game_input: TournamentGameInput) -> TournamentGamePrediction:
        """
        Predict a single tournament game using the canonical model tournament mode.
        """
        res = self.model.analyze_tournament_game(
            team_a=game_input.team_a,
            team_b=game_input.team_b,
            event_context={"start_time": datetime.now(), "id": game_input.event_id},
            market_snapshot=game_input.market_snapshot,
            persist=False,
            neutral_site=game_input.neutral_site
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

    def simulate_bracket(self, seeds: Dict[str, List[Dict[str, Any]]], simulations: int = 10000) -> TournamentBracketSimulation:
        """
        Simulate the entire tournament using Monte Carlo traversal.
        """
        import random
        
        # 1. Parsing and Play-In Identification
        # seeds is { "East": [ {"team_name": "...", "seed": 1}, ... ] }
        
        base_regions = ["East", "South", "West", "Midwest"]
        play_in_matchups = [] # Base tuples for play-ins: (region, seed, team_a, team_b)
        
        # Parse teams per region
        region_teams = {r: {} for r in base_regions} # region -> {seed: team_name or list}
        
        for region, team_list in seeds.items():
            if region not in base_regions: continue
            for item in team_list:
                seed = item['seed']
                tname = item['team_name']

                if seed in region_teams[region]:
                    # Multiple entries for same seed -> play in!
                    existing = region_teams[region][seed]
                    if isinstance(existing, list):
                        existing.append(tname)
                    else:
                        region_teams[region][seed] = [existing, tname]
                        play_in_matchups.append((region, seed, existing, tname))
                else:
                    region_teams[region][seed] = [tname]

        # Flatten strictly to 64 if possible
        # We need a quick way to cache games
        _cache = {}
        
        def _get_game_result(target_a: str, target_b: str, round_name: str) -> TournamentGamePrediction:
            # Sort for cache key consistency
            k = tuple(sorted([target_a, target_b]))
            if k not in _cache:
                # Need neutral site, no market data for futures
                gi = TournamentGameInput(
                    team_a=target_a, 
                    team_b=target_b, 
                    round_index=0, 
                    neutral_site=True
                )
                try:
                    res = self.predict_game(gi)
                except Exception as e:
                    # Explicit error if missing data or any other failure during simulation
                    raise SimulatorDataError(f"Failed to predict {target_a} vs {target_b}: {e}")
                _cache[k] = res
                
            # We must return it mapped to team_a and team_b specifically as requested
            cached = _cache[k]
            # If cached used target_a as team_a
            if cached.team_a == target_a:
                prob_a = cached.win_prob_a
                prob_b = cached.win_prob_b
                p_spread_a = cached.projected_spread_a
            else:
                prob_a = cached.win_prob_b
                prob_b = cached.win_prob_a
                p_spread_a = -cached.projected_spread_a
                
            return TournamentGamePrediction(
                team_a=target_a,
                team_b=target_b,
                winner=cached.winner,
                winner_side="team_a" if cached.winner == target_a else "team_b",
                projected_spread_a=p_spread_a,
                projected_total=cached.projected_total,
                win_prob_a=prob_a,
                win_prob_b=prob_b,
                confidence_0_100=cached.confidence_0_100,
                market_data_used=cached.market_data_used,
                fallback_used=cached.fallback_used,
                reason_codes=cached.reason_codes,
                risk_flags=cached.risk_flags,
                debug=cached.debug
            )
            
        def _sim_matchup(ta: str, tb: str, rd: str) -> str:
            pred = _get_game_result(ta, tb, rd)
            return ta if random.random() < (pred.win_prob_a / 100.0) else tb

        def _most_likely_winner(ta: str, tb: str, rd: str) -> TournamentGamePrediction:
            return _get_game_result(ta, tb, rd)

        # 2. Tracking structures for MC
        # team_name -> counts
        advancements = {}
        for region, seeds_dict in region_teams.items():
            for seed, tlist in seeds_dict.items():
                for t in tlist:
                    advancements[t] = {
                        'R32': 0, 'S16': 0, 'E8': 0, 'FF': 0, 'NCG': 0, 'CHAMP': 0,
                        'seed': seed, 'region': region
                    }

        base_pairings = [(1, 16), (8, 9), (5, 12), (4, 13), (6, 11), (3, 14), (7, 10), (2, 15)]

        # Determine deterministic bracket for main payload display
        # First Four Deterministic
        first_four_det = []
        det_region_teams = {r: {} for r in base_regions}
        for region, sdict in region_teams.items():
            for seed, lst in sdict.items():
                if len(lst) == 2:
                    pred = _most_likely_winner(lst[0], lst[1], "First Four")
                    first_four_det.append(pred)
                    det_region_teams[region][seed] = pred.winner
                else:
                    det_region_teams[region][seed] = lst[0]

        det_regions = {}
        e8_winners_det = {}
        for region in base_regions:
            tm = det_region_teams[region]
            r64 = []
            for (s1, s2) in base_pairings:
                if s1 in tm and s2 in tm: r64.append(_most_likely_winner(tm[s1], tm[s2], "R64"))
            r32 = []
            for i in range(0, len(r64), 2):
                if i+1 < len(r64): r32.append(_most_likely_winner(r64[i].winner, r64[i+1].winner, "R32"))
            s16 = []
            for i in range(0, len(r32), 2):
                if i+1 < len(r32): s16.append(_most_likely_winner(r32[i].winner, r32[i+1].winner, "S16"))
            e8 = []
            for i in range(0, len(s16), 2):
                if i+1 < len(s16): 
                    e8.append(_most_likely_winner(s16[i].winner, s16[i+1].winner, "E8"))
                    e8_winners_det[region] = e8[-1].winner
            det_regions[region] = {"round_of_64": r64, "round_of_32": r32, "sweet_16": s16, "elite_8": e8}

        final_four_det = []
        if "East" in e8_winners_det and "West" in e8_winners_det:
             final_four_det.append(_most_likely_winner(e8_winners_det["East"], e8_winners_det["West"], "FF"))
        if "South" in e8_winners_det and "Midwest" in e8_winners_det:
             final_four_det.append(_most_likely_winner(e8_winners_det["South"], e8_winners_det["Midwest"], "FF"))
             
        championship_det = None
        champion_det = None
        if len(final_four_det) == 2:
             championship_det = _most_likely_winner(final_four_det[0].winner, final_four_det[1].winner, "NCG")
             champion_det = championship_det.winner

        # 3. Fast MC Simulation Loop
        for _ in range(simulations):
            # Play in
            mc_region_teams = {r: {} for r in base_regions}
            for region, sdict in region_teams.items():
                for seed, lst in sdict.items():
                    if len(lst) == 2:
                        mc_region_teams[region][seed] = _sim_matchup(lst[0], lst[1], "First Four")
                    else:
                        mc_region_teams[region][seed] = lst[0]
                        
            # Regions
            e8_winners = {}
            for region in base_regions:
                tm = mc_region_teams[region]
                # R64
                r64_w = []
                for (s1, s2) in base_pairings:
                    if s1 in tm and s2 in tm: r64_w.append(_sim_matchup(tm[s1], tm[s2], "R64"))
                for w in r64_w: advancements[w]['R32'] += 1
                
                # R32
                r32_w = []
                for i in range(0, len(r64_w), 2):
                    if i+1 < len(r64_w): r32_w.append(_sim_matchup(r64_w[i], r64_w[i+1], "R32"))
                for w in r32_w: advancements[w]['S16'] += 1
                
                # S16
                s16_w = []
                for i in range(0, len(r32_w), 2):
                    if i+1 < len(r32_w): s16_w.append(_sim_matchup(r32_w[i], r32_w[i+1], "S16"))
                for w in s16_w: advancements[w]['E8'] += 1
                
                # E8
                e8_w = []
                for i in range(0, len(s16_w), 2):
                    if i+1 < len(s16_w): e8_w.append(_sim_matchup(s16_w[i], s16_w[i+1], "E8"))
                for w in e8_w: advancements[w]['FF'] += 1
                
                if e8_w: e8_winners[region] = e8_w[0]
                
            # Final Four
            ff_w = []
            if "East" in e8_winners and "West" in e8_winners:
                 w = _sim_matchup(e8_winners["East"], e8_winners["West"], "FF")
                 ff_w.append(w)
                 advancements[w]['NCG'] += 1
            if "South" in e8_winners and "Midwest" in e8_winners:
                 w = _sim_matchup(e8_winners["South"], e8_winners["Midwest"], "FF")
                 ff_w.append(w)
                 advancements[w]['NCG'] += 1
                 
            # Championship
            if len(ff_w) == 2:
                 ncg_w = _sim_matchup(ff_w[0], ff_w[1], "NCG")
                 advancements[ncg_w]['CHAMP'] += 1

        # Calculate final probs
        adv_probs = []
        for t, counts in advancements.items():
            adv_probs.append(TournamentTeamAdvancement(
                team_name=t,
                seed=counts['seed'],
                region=counts['region'],
                r32_prob=round((counts['R32'] / simulations) * 100, 2),
                s16_prob=round((counts['S16'] / simulations) * 100, 2),
                e8_prob=round((counts['E8'] / simulations) * 100, 2),
                final_four_prob=round((counts['FF'] / simulations) * 100, 2),
                championship_prob=round((counts['NCG'] / simulations) * 100, 2),
                champion_prob=round((counts['CHAMP'] / simulations) * 100, 2)
            ))
            
        adv_probs.sort(key=lambda x: x.champion_prob, reverse=True)
            
        title_odds = {a.team_name: a.champion_prob for a in adv_probs if a.champion_prob > 0.0}

        return TournamentBracketSimulation(
            season="2025-26",
            simulated_at=datetime.now().isoformat(),
            model_version="tournament_ensemble_v1",
            regions=det_regions,
            first_four=first_four_det,
            final_four=final_four_det,
            championship=championship_det,
            champion=champion_det,
            title_odds=title_odds,
            round_advancement_probs=adv_probs,
            data_issues=[]
        )
