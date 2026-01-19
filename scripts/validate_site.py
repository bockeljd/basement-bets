#!/usr/bin/env python3
"""
Comprehensive validation script to test all API endpoints and functionality
"""
import requests
import json
from datetime import datetime
import os

BASE_URL = "http://localhost:8000"

# Get password from environment
PASSWORD = os.environ.get("BASEMENT_PASSWORD", "")
HEADERS = {"X-Password": PASSWORD} if PASSWORD else {}

def test_endpoint(name, endpoint):
    """Test a single API endpoint"""
    try:
        response = requests.get(f"{BASE_URL}{endpoint}", headers=HEADERS, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return f"✓ {name}: {len(data) if isinstance(data, list) else 'OK'}"
        else:
            return f"✗ {name}: HTTP {response.status_code}"
    except Exception as e:
        return f"✗ {name}: {str(e)[:50]}"

def main():
    print("="*80)
    print(f"BASEMENT BETS - COMPREHENSIVE VALIDATION")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    # Test all major endpoints
    tests = [
        ("Stats Summary", "/api/stats"),
        ("All Bets", "/api/bets"),
        ("Sport Breakdown", "/api/breakdown/sport"),
        ("Bet Type Breakdown", "/api/breakdown/bet_type"),
        ("Player Performance", "/api/breakdown/player"),
        ("Monthly Performance", "/api/breakdown/monthly"),
        ("Balances", "/api/balances"),
        ("Financials", "/api/financials"),
        ("Time Series", "/api/analytics/series"),
        ("Drawdown", "/api/analytics/drawdown"),
        ("Research Data", "/api/research"),
    ]
    
    print("\n📊 API ENDPOINT HEALTH:\n")
    for name, endpoint in tests:
        result = test_endpoint(name, endpoint)
        print(f"  {result}")
    
    # Check Research endpoint specifically for live data
    print("\n🔴 RESEARCH TAB - LIVE DATA CHECK:\n")
    try:
        response = requests.get(f"{BASE_URL}/api/research", headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            
            live_edges = data.get('edges', [])
            history = data.get('history', [])
            
            print(f"  ✓ Live Edges: {len(live_edges)} predictions")
            print(f"  ✓ History: {len(history)} past predictions")
            
            if live_edges:
                sample = live_edges[0]
                print(f"\n  Sample Live Edge:")
                print(f"    Game: {sample.get('game', 'N/A')}")
                print(f"    Sport: {sample.get('sport', 'N/A')}")
                print(f"    Edge: {sample.get('edge', 0):.2f}%")
                print(f"    Time: {sample.get('game_time', 'N/A')}")
            else:
                print(f"\n  ⚠ No live edges found (check if model is running)")
                
        else:
            print(f"  ✗ Research endpoint failed: HTTP {response.status_code}")
    except Exception as e:
        print(f"  ✗ Research endpoint error: {e}")
    
    # Check Financial Summary
    print("\n💰 FINANCIAL TOTALS VERIFICATION:\n")
    try:
        response = requests.get(f"{BASE_URL}/api/financials", headers=HEADERS, timeout=5)
        if response.status_code == 200:
            data = response.json()
            breakdown = data.get('breakdown', [])
            
            targets = {
                'DraftKings': {'deposited': 747.38, 'withdrawn': 1035.38},
                'Barstool': {'deposited': 58.36, 'withdrawn': 89.76},
                'FanDuel': {'deposited': 120.00, 'withdrawn': 491.34},
                'Other': {'deposited': 0.0, 'withdrawn': 210.00}
            }
            
            for provider_data in breakdown:
                prov = provider_data['provider']
                dep = provider_data['deposited']
                wit = provider_data['withdrawn']
                
                if prov in targets:
                    target = targets[prov]
                    dep_match = abs(dep - target['deposited']) < 0.01
                    wit_match = abs(wit - target['withdrawn']) < 0.01
                    
                    dep_marker = "✓" if dep_match else "✗"
                    wit_marker = "✓" if wit_match else "✗"
                    
                    print(f"  {prov:15} | Deposits: ${dep:8.2f} {dep_marker} | Withdrawals: ${wit:8.2f} {wit_marker}")
    except Exception as e:
        print(f"  ✗ Financial check error: {e}")
    
    # Check Bet Type Distribution
    print("\n📋 BET TYPE STANDARDIZATION:\n")
    try:
        response = requests.get(f"{BASE_URL}/api/breakdown/bet_type", headers=HEADERS, timeout=5)
        if response.status_code == 200:
            data = response.json()
            
            standard_types = {'Winner (ML)', 'Spread', 'Over / Under', 'Prop', 'SGP', '2 Leg Parlay', '3 Leg Parlay', '4+ Parlay'}
            
            for bet_type_data in data[:10]:  # Top 10
                bet_type = bet_type_data.get('bet_type', 'Unknown')
                count = bet_type_data.get('bets', 0)
                wins = bet_type_data.get('wins', 0)
                win_rate = bet_type_data.get('win_rate', 0)
                
                marker = "✓" if bet_type in standard_types else "⚠"
                print(f"  {marker} {bet_type:20} | {count:3} bets | {wins:2} wins | {win_rate:.1f}% WR")
    except Exception as e:
        print(f"  ✗ Bet type check error: {e}")
    
    print("\n" + "="*80)
    print("VALIDATION COMPLETE")
    print("="*80)
    
if __name__ == "__main__":
    main()
