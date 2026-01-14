from sportsreference.ncaab.teams import Teams
import datetime

# Determine Season (Jan 2026 -> 2026 Season)
year = datetime.datetime.now().year
if datetime.datetime.now().month > 6:
    year += 1

print(f"Fetching NCAAM Teams for Season {year}...")

try:
    teams = Teams(year=year)
    for team in teams:
        print(f"{team.name}: {team.points} PPG, Pace: {team.pace}")
        break  # Just need one to verify
except Exception as e:
    print(f"Library Failed: {e}")
