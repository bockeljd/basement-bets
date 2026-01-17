"""
Helper method for NCAAM model to calculate injury impact on spread/total
"""

def get_injury_adjustment(espn_client, home_team: str, away_team: str) -> dict:
    """
    Calculate spread and total adjustments based on ESPN injury data
    
    Args:
        espn_client: ESPNNCAAClient instance
        home_team: Home team name
        away_team: Away team name
        
    Returns:
        Dict with spread_adj, total_adj, injury_summary
    """
    if not espn_client:
        return {'spread_adj': 0.0, 'total_adj': 0.0, 'injury_summary': 'No injury data'}
    
    try:
        context = espn_client.get_game_context(home_team, away_team)
        injuries = context.get('injuries', [])
        
        if not injuries:
            return {'spread_adj': 0.0, 'total_adj': 0.0, 'injury_summary': 'No injuries reported'}
        
        home_impact = 0.0
        away_impact = 0.0
        
        for injury in injuries:
            # Estimate impact based on position
            # Guards/Forwards: -1.5 to -2.5 pts
            # Centers: -2.0 to -3.0 pts
            # Bench: -0.5 pts
            position = injury.get('position', '')
            
            if 'G' in position or 'F' in position:
                impact = 2.0  # Guard/Forward
            elif 'C' in position:
                impact = 2.5  # Center
            else:
                impact = 1.0  # Unknown/Bench
            
            # Apply to correct team
            team_name = injury.get('team', '')
            if home_team.lower() in team_name.lower():
                home_impact -= impact
            elif away_team.lower() in team_name.lower():
                away_impact -= impact
        
        # Spread adjustment: home_impact - away_impact
        # If home loses a star (-2.5) and away is healthy (0), spread moves -2.5 toward away
        spread_adj = home_impact - away_impact
        
        # Total adjustment: sum of absolute impacts * 0.4
        # Injuries generally lower scoring
        total_adj = -(abs(home_impact) + abs(away_impact)) * 0.4
        
        injury_summary = f"{len(injuries)} injury report(s)"
        
        return {
            'spread_adj': round(spread_adj, 1),
            'total_adj': round(total_adj, 1),
            'injury_summary': injury_summary,
            'injury_count': len(injuries)
        }
        
    except Exception as e:
        print(f"[INJURY] Error getting injury data: {e}")
        return {'spread_adj': 0.0, 'total_adj': 0.0, 'injury_summary': 'Error fetching injuries'}
