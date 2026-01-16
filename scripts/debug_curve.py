import sys
import os
import sqlite3

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.analytics import AnalyticsEngine

def debug_curve():
    print("--- DEBUGGING BANKROLL CURVE ---")
    engine = AnalyticsEngine()
    
    # 1. Get the raw series data
    series = engine.get_time_series_profit()
    
    print(f"{'Date':<12} | {'Daily PnL':>10} | {'Cumulative':>10}")
    print("-" * 40)
    
    # Print first 10, last 10, and any large jumps
    print(f"{'Date':<12} | {'Daily Net':>10} | {'Cumulative':>10}")
    
    # Also fetch raw breakdown for specific dates to debug
    # specific_dates = ['2023-12-25', '2025-11-14']
    
    for i, pt in enumerate(series):
        if i < 10 or i > len(series) - 10 or abs(pt['profit']) > 500:
             print(f"{pt['date']:<12} | {pt['profit']:>10.2f} | {pt['cumulative']:>10.2f}")

    print("-" * 40)
    print(f"Total Points: {len(series)}")
    print(f"Final Cumulative: {series[-1]['cumulative'] if series else 0}")
    
    # Check specific dates if user mentioned 2023
    print("\n[Spot Check 2023 Deposits]")
    # Look for the dates where we know deposits happened (from previous audit)
    # e.g. 2023-12-25 ($125)
    
    target_date = '2023-12-25'
    found = next((x for x in series if target_date in x['date']), None)
    if found:
        print(f"On {target_date}: Daily PnL = {found['profit']} (Expected +125.0 approx)")
    else:
        print(f"Date {target_date} not found in series.")

if __name__ == "__main__":
    debug_curve()
