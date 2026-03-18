from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from src.database import get_db_connection, _exec
from src.services.ncaam_bracket_seed_loader import get_seed_source_metadata, load_manual_bracket_seeds
from src.services.ncaam_tournament_service import NCAAMTournamentPredictionService, TournamentGameInput
from src.utils.naming import standardize_team_name

logger = logging.getLogger("basement_bets.ncaam_bracket_state")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

SlotKey = Tuple[Optional[str], str, int]
PairKey = Tuple[str, str]

LIVE_STATUS_TOKENS = {
    "IN_PROGRESS", "LIVE", "HALFTIME", "Q1", "Q2", "Q3", "Q4", "FIRST_HALF", "SECOND_HALF"
}

REGIONAL_ROUND_SPECS = {
    "round_of_64": [
        {"slot": 0, "left": {1}, "right": {16}},
        {"slot": 1, "left": {8}, "right": {9}},
        {"slot": 2, "left": {5}, "right": {12}},
        {"slot": 3, "left": {4}, "right": {13}},
        {"slot": 4, "left": {6}, "right": {11}},
        {"slot": 5, "left": {3}, "right": {14}},
        {"slot": 6, "left": {7}, "right": {10}},
        {"slot": 7, "left": {2}, "right": {15}}
    ],
    "round_of_32": [
        {"slot": 0, "left": {1, 16}, "right": {8, 9}},
        {"slot": 1, "left": {5, 12}, "right": {4, 13}},
        {"slot": 2, "left": {6, 11}, "right": {3, 14}},
        {"slot": 3, "left": {7, 10}, "right": {2, 15}}
    ],
    "sweet_16": [
        {"slot": 0, "left": {1, 16, 8, 9}, "right": {5, 12, 4, 13}},
        {"slot": 1, "left": {6, 11, 3, 14}, "right": {7, 10, 2, 15}}
    ],
    "elite_8": [
        {"slot": 0, "left": {1, 16, 8, 9, 5, 12, 4, 13}, "right": {6, 11, 3, 14, 7, 10, 2, 15}}
    ]
}

FINAL_FOUR_PAIRS = [
    ({"East", "West"}, 0),
    ({"South", "Midwest"}, 1)
]

ET_ZONE = ZoneInfo("America/New_York")

class BracketGameStatus:
    FINAL = "final"
    LIVE = "live"
    SCHEDULED = "scheduled"


def _expand_team_names(raw: str) -> List[str]:
    if not raw:
        return []
    if " / " in raw:
        return [t.strip() for t in raw.split(" / ") if t.strip()]
    return [raw.strip()]


def _normalize_status(raw_status: Optional[str], final_flag: bool) -> str:
    if final_flag:
        return BracketGameStatus.FINAL
    if not raw_status:
        return BracketGameStatus.SCHEDULED
    upper = raw_status.upper()
    if upper in LIVE_STATUS_TOKENS or any(tok in upper for tok in LIVE_STATUS_TOKENS):
        return BracketGameStatus.LIVE
    return BracketGameStatus.SCHEDULED


def _format_tip_et(start_time: Optional[datetime]) -> Optional[str]:
    if not start_time:
        return None
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    try:
        est = start_time.astimezone(ET_ZONE)
    except Exception:
        est = start_time
    return est.strftime("%Y-%m-%d %H:%M")


def _pair_key(team_a: str, team_b: str) -> PairKey:
    return tuple(sorted([standardize_team_name(team_a), standardize_team_name(team_b)]))


def _seed_for_team(seed_lookup: Dict[str, Dict[str, Any]], team_name: str) -> Optional[int]:
    key = standardize_team_name(team_name)
    info = seed_lookup.get(key)
    return info.get("seed") if info else None


class NCAAMBracketStateService:
    def __init__(self, season: str = "2025-26"):
        self.season = season
        self.seed_rows = self._load_seed_rows()
        self.seed_lookup = self._build_seed_lookup(self.seed_rows)
        self.region_seeds = self._group_seeds_by_region()
        self.round_defs = self._build_round_definitions()

    def _load_seed_rows(self) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            rows = _exec(conn, """
                SELECT team_name, seed, region
                FROM ncaam_tournament_seeds
                WHERE season = %s
            """, (self.season,)).fetchall()

        if rows:
            return [dict(r) for r in rows]

        logger.warning("Bracket seeds missing; falling back to manual loader.")
        manual = load_manual_bracket_seeds(self.season)
        expanded = []
        for region, entries in manual.items():
            for entry in entries:
                expanded.append({"team_name": entry["team_name"], "seed": entry["seed"], "region": region})
        return expanded

    def _build_seed_lookup(self, rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        lookup: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            region = row.get("region")
            seed = row.get("seed")
            for raw in _expand_team_names(row.get("team_name")):
                key = standardize_team_name(raw)
                if key:
                    lookup[key] = {"region": region, "seed": seed, "raw": raw}
        return lookup

    def _group_seeds_by_region(self) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in self.seed_rows:
            region = row.get("region")
            if not region:
                continue
            grouped.setdefault(region, []).append({
                "seed": row.get("seed"),
                "team_name": row.get("team_name")
            })
        return grouped

    def _build_round_definitions(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        return {
            region: {
                round_name: [
                    {
                        "slot_index": spec["slot"],
                        "left_seeds": spec["left"].copy(),
                        "right_seeds": spec["right"].copy(),
                        "assigned": False
                    }
                    for spec in specs
                ]
                for round_name, specs in REGIONAL_ROUND_SPECS.items()
            }
            for region in ["East", "West", "South", "Midwest"]
        }

    def _fetch_actual_events(self) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            rows = _exec(conn, """
                SELECT e.id, e.home_team, e.away_team, e.start_time, e.status, gr.home_score, gr.away_score, gr.final
                FROM events e
                LEFT JOIN game_results gr ON gr.event_id = e.id
                WHERE e.league = 'NCAAM'
                  AND e.start_time >= NOW() - INTERVAL '90 days'
                ORDER BY e.start_time ASC
            """).fetchall()
        return [dict(r) for r in rows]

    def _normalize_match_key(self, home: str, away: str) -> Tuple[str, str]:
        return tuple(sorted([standardize_team_name(home), standardize_team_name(away)]))

    def _match_round_slot(self, region: str, left_seed: int, right_seed: int) -> Optional[Tuple[str, int, bool]]:
        defs = self.round_defs.get(region, {})
        seed_set = {left_seed, right_seed}
        for round_name in ["round_of_64", "round_of_32", "sweet_16", "elite_8"]:
            for slot in defs.get(round_name, []):
                if slot["assigned"]:
                    continue
                left_seeds = slot["left_seeds"]
                right_seeds = slot["right_seeds"]
                if left_seed in left_seeds and right_seed in right_seeds:
                    slot["assigned"] = True
                    return round_name, slot["slot_index"], True
                if left_seed in right_seeds and right_seed in left_seeds:
                    slot["assigned"] = True
                    return round_name, slot["slot_index"], False
        return None

    def _assign_final_four_slot(self, regions: Tuple[str, str]) -> Optional[int]:
        region_set = set(regions)
        for pair, index in FINAL_FOUR_PAIRS:
            if region_set == pair:
                return index
        return None

    def _collect_override_data(self, event: Dict[str, Any], slot_key: SlotKey, left_team: str, right_team: str,
                               left_seed: Optional[int], right_seed: Optional[int], status: str,
                               tip_et: Optional[str]) -> Dict[str, Any]:
        home_score = event.get("home_score")
        away_score = event.get("away_score")
        score_map = {
            event.get("home_team", ""): home_score,
            event.get("away_team", ""): away_score
        }
        score_a = int(score_map.get(left_team)) if score_map.get(left_team) is not None else None
        score_b = int(score_map.get(right_team)) if score_map.get(right_team) is not None else None
        winner = left_team if (score_a if score_a is not None else 0) >= (score_b if score_b is not None else 0) else right_team
        actual_winner = None
        if score_a is not None and score_b is not None and status == BracketGameStatus.FINAL:
            actual_winner = winner
        return {
            "slot_key": slot_key,
            "team_a": left_team,
            "team_b": right_team,
            "seed_a": left_seed,
            "seed_b": right_seed,
            "score_a": score_a,
            "score_b": score_b,
            "status": status,
            "actual_winner": actual_winner,
            "scheduled_tip_et": tip_et,
            "tv_network": None,
            "site": None
        }

    def build_bracket_payload(self) -> Dict[str, Any]:
        seeded_payload: Dict[str, List[Dict[str, Any]]] = {
            region: [{"team_name": w["team_name"], "seed": w["seed"]} for w in teams]
            for region, teams in self.region_seeds.items()
        }

        override_by_pair: Dict[PairKey, Dict[str, Any]] = {}
        locked_matchups: List[Dict[str, Any]] = []

        events = self._fetch_actual_events()
        for event in events:
            home = event.get("home_team") or ""
            away = event.get("away_team") or ""
            home_std = standardize_team_name(home)
            away_std = standardize_team_name(away)
            if home_std not in self.seed_lookup or away_std not in self.seed_lookup:
                continue

            home_info = self.seed_lookup[home_std]
            away_info = self.seed_lookup[away_std]

            # Use canonical seed/raw names so we match simulated bracket team strings.
            home_raw = home_info.get("raw") or home
            away_raw = away_info.get("raw") or away

            status = _normalize_status(event.get("status"), bool(event.get("final")))
            tip_et = _format_tip_et(event.get("start_time"))

            pair: PairKey = _pair_key(home_raw, away_raw)

            # Collect override data but do NOT attempt to assign it to a bracket slot yet.
            # Slot assignment happens after simulation by matching simulated matchup teams.
            override_by_pair[pair] = self._collect_override_data(
                event,
                (None, "unknown", 0),
                home_raw,
                away_raw,
                home_info.get("seed"),
                away_info.get("seed"),
                status,
                tip_et,
            )

            if status == BracketGameStatus.FINAL and override_by_pair[pair].get("actual_winner"):
                locked_matchups.append({
                    "team_a": home_raw,
                    "team_b": away_raw,
                    "winner": override_by_pair[pair]["actual_winner"],
                })

        prediction_service = NCAAMTournamentPredictionService()
        simulation = prediction_service.simulate_bracket(seeded_payload, simulations=2500, locked_matchups=locked_matchups)
        payload = simulation.model_dump()
        payload["v"] = "7-actual-first-pair-match"
        payload["seed_metadata"] = get_seed_source_metadata()
        payload["updated_at"] = datetime.utcnow().isoformat()
        payload["model_version"] = payload.get("model_version", "tournament_ensemble_v1")

        overrides_by_slot: Dict[SlotKey, Dict[str, Any]] = {}
        for slot_key, match in self._iter_all_matches(payload):
            pair = _pair_key(match.get("team_a", ""), match.get("team_b", ""))
            if pair in override_by_pair:
                ov = dict(override_by_pair[pair])
                ov["slot_key"] = slot_key
                overrides_by_slot[slot_key] = ov

        self._apply_overrides(payload, overrides_by_slot)
        # Rebuild deterministic downstream rounds so actual winners advance consistently
        self._rebuild_after_actuals(payload, prediction_service, override_by_pair)
        issue_count = len(payload.get("data_issues", []))
        payload["champion_trust_low"] = bool(payload.get("degraded_simulation") and issue_count > 3)
        return payload

    def _iter_all_matches(self, payload: Dict[str, Any]):
        """Yield (SlotKey, match_dict) for every match in the payload."""
        for region, rounds in payload.get("regions", {}).items():
            for round_name, matches in rounds.items():
                for idx, match in enumerate(matches):
                    yield (region, round_name, idx), match
        for idx, match in enumerate(payload.get("final_four", []) or []):
            yield (None, "final_four", idx), match
        champ = payload.get("championship")
        if champ:
            yield (None, "championship", 0), champ


    def _rebuild_region_rounds(self, payload: Dict[str, Any], region: str, prediction_service: NCAAMTournamentPredictionService, override_by_pair: Dict[PairKey, Dict[str, Any]]) -> None:
        """Recompute downstream rounds so that actual winners advance consistently."""
        rounds = payload.get("regions", {}).get(region, {})
        if not rounds:
            return

        def _winner_for(match: Dict[str, Any]) -> Optional[str]:
            return match.get("display_winner") or match.get("predicted_winner") or match.get("winner")

        def _project_match(team_a: str, team_b: str) -> Dict[str, Any]:
            gi = TournamentGameInput(team_a=team_a, team_b=team_b, round_index=0, region=region, neutral_site=True)
            pred = prediction_service.predict_game(gi, conn=None)
            d = pred.model_dump()
            d["seed_a"] = _seed_for_team(self.seed_lookup, team_a)
            d["seed_b"] = _seed_for_team(self.seed_lookup, team_b)
            return d

        order = ["round_of_64", "round_of_32", "sweet_16", "elite_8"]
        for idx in range(1, len(order)):
            prev_round = order[idx - 1]
            cur_round = order[idx]

            prev_matches = rounds.get(prev_round) or []
            prev_winners = [_winner_for(m) for m in prev_matches]
            if any(w is None for w in prev_winners):
                continue

            new_matches: List[Dict[str, Any]] = []
            for i in range(0, len(prev_winners), 2):
                if i + 1 >= len(prev_winners):
                    continue
                ta = prev_winners[i]
                tb = prev_winners[i + 1]

                new_m = _project_match(ta, tb)

                pair = _pair_key(ta, tb)
                if pair in override_by_pair:
                    ov = dict(override_by_pair[pair])
                    ov["team_a"] = ta
                    ov["team_b"] = tb
                    ov["seed_a"] = _seed_for_team(self.seed_lookup, ta)
                    ov["seed_b"] = _seed_for_team(self.seed_lookup, tb)
                    ov["slot_key"] = (region, cur_round, len(new_matches))
                    self._overlay_match(new_m, ov)
                else:
                    self._overlay_match(new_m, None)

                new_matches.append(new_m)

            rounds[cur_round] = new_matches

        payload["regions"][region] = rounds

    def _rebuild_after_actuals(self, payload: Dict[str, Any], prediction_service: NCAAMTournamentPredictionService, override_by_pair: Dict[PairKey, Dict[str, Any]]) -> None:
        for region in ["East", "West", "South", "Midwest"]:
            self._rebuild_region_rounds(payload, region, prediction_service, override_by_pair)
    def _apply_overrides(self, payload: Dict[str, Any], overrides: Dict[SlotKey, Dict[str, Any]]) -> None:
        for region, rounds in payload.get("regions", {}).items():
            for round_name, matches in rounds.items():
                for idx, match in enumerate(matches):
                    key: SlotKey = (region, round_name, idx)
                    self._overlay_match(match, overrides.get(key))
        for idx, four in enumerate(payload.get("final_four", [])):
            self._overlay_match(four, overrides.get((None, "final_four", idx)))
        champ = payload.get("championship")
        if champ:
            self._overlay_match(champ, overrides.get((None, "championship", 0)))

    def _overlay_match(self, match: Dict[str, Any], override: Optional[Dict[str, Any]]) -> None:
        baseline = {
            "predicted_winner": match.get("winner"),
            "predicted_win_prob_a": match.get("win_prob_a"),
            "predicted_win_prob_b": match.get("win_prob_b"),
            "projection_debug": match.get("debug", {})
        }
        match.update(baseline)
        match["projection_source"] = f"model:{match.get('model_type', 'tournament_ensemble_v1')}"

        if override:
            # If we reorder/rename team_a/team_b using overrides, remap win_prob_* so probabilities follow the team names
            old_team_a = match.get('team_a')
            old_team_b = match.get('team_b')
            old_win_prob_a = match.get('win_prob_a')
            old_win_prob_b = match.get('win_prob_b')
            old_pred_win_prob_a = match.get('predicted_win_prob_a')
            old_pred_win_prob_b = match.get('predicted_win_prob_b')
            prob_by_team = {old_team_a: old_win_prob_a, old_team_b: old_win_prob_b}
            pred_prob_by_team = {old_team_a: old_pred_win_prob_a, old_team_b: old_pred_win_prob_b}
            match["team_a"] = override["team_a"]
            match["team_b"] = override["team_b"]
            # Remap probabilities to follow the overridden team ordering
            match["win_prob_a"] = prob_by_team.get(override["team_a"], old_win_prob_a)
            match["win_prob_b"] = prob_by_team.get(override["team_b"], old_win_prob_b)
            match["predicted_win_prob_a"] = pred_prob_by_team.get(override["team_a"], old_pred_win_prob_a)
            match["predicted_win_prob_b"] = pred_prob_by_team.get(override["team_b"], old_pred_win_prob_b)
            match["seed_a"] = override["seed_a"]
            match["seed_b"] = override["seed_b"]
            match["status"] = override["status"]
            match["actual_score_a"] = override["score_a"]
            match["actual_score_b"] = override["score_b"]
            match["actual_winner"] = override["actual_winner"]
            match["scheduled_tip_et"] = override.get("scheduled_tip_et") or match.get("scheduled_tip_et")
            match["tv_network"] = override.get("tv_network") or match.get("tv_network")
            match["site"] = override.get("site") or match.get("site")
            match["display_winner"] = match.get("predicted_winner")
            match["winner_source"] = "projection"
            if match["status"] == BracketGameStatus.FINAL and override["actual_winner"]:
                match["display_winner"] = override["actual_winner"]
                match["winner_source"] = "final"
            elif match["status"] == BracketGameStatus.LIVE:
                if override["actual_winner"]:
                    match["display_winner"] = override["actual_winner"]
                    match["winner_source"] = "live"
            elif match["status"] == BracketGameStatus.SCHEDULED:
                match["display_winner"] = match.get("predicted_winner")
                match["winner_source"] = "projection"
        else:
            match["status"] = match.get("status") or BracketGameStatus.SCHEDULED
            match["display_winner"] = match.get("predicted_winner")
            match["winner_source"] = "projection"
            match["actual_score_a"] = None
            match["actual_score_b"] = None
            match["actual_winner"] = None

        match["draw_hint"] = override["slot_key"] if override else None

    def get_seed_metadata(self) -> Dict[str, Any]:
        return get_seed_source_metadata()

    def get_region_seeds(self) -> Dict[str, List[Dict[str, Any]]]:
        return self.region_seeds
