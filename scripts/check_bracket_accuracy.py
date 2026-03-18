#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

sys.path.append(os.getcwd())
from src.services.ncaam_bracket_seed_loader import load_manual_bracket_seeds
from src.utils.naming import standardize_team_name


def expand_team_names(name: str):
    if not name:
        return []
    if ' / ' in name:
        return [part.strip() for part in name.split(' / ') if part.strip()]
    return [name.strip()]


def build_seed_map():
    manual = load_manual_bracket_seeds()
    seed_map = {}
    for region, entries in manual.items():
        for entry in entries:
            seed = entry['seed']
            for team in expand_team_names(entry['team_name']):
                seed_map[standardize_team_name(team)] = {
                    'seed': seed,
                    'region': region,
                    'name': team
                }
    return seed_map


def main():
    data_path = Path('data/tournament_predictions_2026.json')
    if not data_path.exists():
        print('Bracket prediction file not found at', data_path)
        return

    predictions = json.loads(data_path.read_text())
    seed_map = build_seed_map()

    round_advancement = predictions.get('round_advancement_probs') or []
    champion_probs = [team.get('champion_prob', 0) for team in round_advancement]
    total_champion_prob = sum(champion_probs)
    title_odds = predictions.get('title_odds', {})

    r64_losses = []
    one_seed_results = []

    for region, rounds in predictions.get('rounds', {}).items():
        for match in rounds.get('round_of_64', []):
            team_a = match.get('team_a')
            team_b = match.get('team_b')
            winner = match.get('winner')
            probs = {team_a: float(match.get('win_prob_a') or 0), team_b: float(match.get('win_prob_b') or 0)}
            for team in (team_a, team_b):
                info = seed_map.get(standardize_team_name(team))
                if info and info['seed'] == 1:
                    expected = 'win' if winner == team else 'loss'
                    one_seed_results.append({
                        'region': region,
                        'match': f"{team_a} vs {team_b}",
                        'seed1': team,
                        'winner': winner,
                        'result': expected,
                        'fav_pct': probs[team],
                    })
                    if expected == 'loss':
                        r64_losses.append(one_seed_results[-1])

    print('\n--- Simulation Accuracy Review ---')
    if champion_probs:
        print(f"Champion probabilities sum to {total_champion_prob:.2f}% (target 100%).")
    elif title_odds:
        print('Champion probabilities are not exposed in the payload; falling back to title odds for ranking.')
    else:
        print('Champion probabilities are not available in this payload.')
    print(f"Champion pick: {predictions.get('champion')} (final game: {predictions.get('championship', {}).get('team_a')} vs {predictions.get('championship', {}).get('team_b')}).")

    wins = sum(1 for res in one_seed_results if res['result'] == 'win')
    total = len(one_seed_results)
    print(f"One seeds in Round of 64: {total} monitored, {wins} predicted to win (so far {wins/total*100 if total else 0:.1f}%).")
    if r64_losses:
        print('One-seed upsets predicted:')
        for loss in r64_losses:
            print(f"  {loss['region']}: {loss['seed1']} (fav {loss['fav_pct']}%) losing to {loss['winner']} in {loss['match']}")
    else:
        print('No Round-of-64 upset is currently predicted for a 1 seed.')

    print('\nTop Final Four / Champion chances:')
    if round_advancement:
        top = sorted(round_advancement, key=lambda x: (x.get('champion_prob', 0), x.get('final_four_prob', 0)), reverse=True)[:5]
        for team in top:
            print(f"  {team['team_name']} (seed {team['seed']}) — Final Four {team.get('final_four_prob')}%, Champion {team.get('champion_prob')}%")
    elif title_odds:
        for team, prob in sorted(title_odds.items(), key=lambda item: item[1], reverse=True)[:5]:
            print(f"  {team} — Title odds {prob}%")
    else:
        print('  No advancement or odds data available.')


if __name__ == '__main__':
    main()
