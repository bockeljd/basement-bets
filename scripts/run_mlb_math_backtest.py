import datetime
import statistics
from unittest.mock import patch
from src.services.mlb_service import MLBService
from src.models.mlb_model import MLBModel

def run_math_backtest():
    print("==========================================================")
    print(" MLB Math Validation Backtest (Raw Win % & Run Totals) ")
    print("==========================================================")
    print("NOTE: This uses end-of-season stats to predict matchups, ")
    print("so it has lookahead bias. It is designed to test the ")
    print("underlying Sabermetric equations (Pythagorean, Log5, Poisson)")
    print("rather than true point-in-time betting profitability.\n")

    mlb_service = MLBService()
    model = MLBModel()
    
    start_date = datetime.date(2024, 7, 10)
    end_date = datetime.date(2024, 7, 14)
    
    games_to_test = []
    current = start_date
    while current <= end_date:
        date_str = current.strftime("%Y-%m-%d")
        schedule = mlb_service.get_schedule(date_str)
        for g in schedule:
            if "final" in (g.get("status") or "").lower():
                games_to_test.append((date_str, g))
        current += datetime.timedelta(days=1)
        
    print(f"Found {len(games_to_test)} completed games between {start_date} and {end_date}.")
    
    results = []
    
    # We will patch datetime so that `mlb_service` sees the year as 2024.
    class MockDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(2024, 7, 15)

    def analyze_game(item):
        date_str, g = item
        home = g["home_team"]
        away = g["away_team"]
        
        actual_home_runs = g.get("home_score", 0)
        actual_away_runs = g.get("away_score", 0)
        actual_total = actual_home_runs + actual_away_runs
        actual_home_win = actual_home_runs > actual_away_runs
        
        event_ctx = {
            "id": g.get("game_pk"),
            "home_team": home,
            "away_team": away,
            "start_time": g.get("game_date"),
            "home_pitcher": g.get("home_pitcher"),
            "away_pitcher": g.get("away_pitcher"),
        }
        
        analysis = model.analyze(
            event_id=str(g.get("game_pk")),
            market_snapshot={},
            event_context=event_ctx,
            persist=False
        )
        
        if not analysis.get("is_actionable"):
            return None
        
        proj = analysis.get("projections", {})
        mdl = analysis.get("model", {})
        
        proj_tot = proj.get("total_runs", 0)
        prob_home_win = mdl.get("prob_home_win", 0.5)
        
        return {
            "matchup": f"{away} @ {home}",
            "actual_winner": "HOME" if actual_home_win else "AWAY",
            "model_prob_home": prob_home_win,
            "correct_winner": (prob_home_win > 0.5 and actual_home_win) or (prob_home_win <= 0.5 and not actual_home_win),
            "actual_total": actual_total,
            "proj_total": proj_tot,
            "total_error": abs(actual_total - proj_tot)
        }
        
    print("Analyzing games (fetching stats)...")
    
    # Patch datetime.date in mlb_service
    with patch('src.services.mlb_service.datetime.date', MockDate):
        with patch('src.models.mlb_model.datetime.date', MockDate):
            for item in games_to_test:
                try:
                    res = analyze_game(item)
                    if res:
                        results.append(res)
                        print(f"[{res['correct_winner'] and '✅' or '❌'}] {res['matchup']} | Proj: {res['model_prob_home']*100:.1f}% Home Win | Proj Total: {res['proj_total']:.1f} vs Act: {res['actual_total']}")
                    else:
                        print(f"[SKIP] {item[1]['away_team']} @ {item[1]['home_team']} (Insufficient data)")
                except Exception as e:
                    print(f"Error on {item[1]['game_pk']}: {e}")

    correct_picks = sum(1 for r in results if r["correct_winner"])
    total_games = len(results)
    win_pct = correct_picks / total_games if total_games else 0
    
    avg_total_err = statistics.mean([r["total_error"] for r in results]) if results else 0
    
    print("\n==========================================================")
    print(" BACKTEST RESULTS ")
    print("==========================================================")
    print(f"Games Analyzed: {total_games}")
    print(f"Straight-Up Winner Accuracy: {win_pct*100:.1f}% ({correct_picks}/{total_games})")
    print(f"Average Total Runs Error: {avg_total_err:.2f} runs")
    print("==========================================================")

if __name__ == '__main__':
    run_math_backtest()
