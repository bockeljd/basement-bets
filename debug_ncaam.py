import sys
import os
import json
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from models.ncaam_model import NCAAMModel

def test_mapping():
    print("Initializing NCAAM Model (Torvik)...")
    model = NCAAMModel()
    
    # Load Data (will cache)
    stats = model.fetch_data()
    print(f"Loaded {len(stats)} teams.")
    
    # Test Common Mismatches
    test_cases = [
        "UConn", "Connecticut", 
        "Ole Miss", "Mississippi",
        "NC State", "North Carolina St.", "N.C. State",
        "Miami (FL)", "Miami FL", "Miami",
        "Iowa State", "Iowa St.",
        "Penn State", "Penn St.",
        "St. John's", "St Johns",
        "Saint Mary's", "St. Mary's (CA)",
        "VCU", "Va Commonwealth"
    ]
    
    print("\n--- Testing Mappings ---")
    failures = []
    for name in test_cases:
        mapped = model._map_name(name)
        if mapped in stats:
            print(f"✅ '{name}' -> '{mapped}'")
        else:
            print(f"❌ '{name}' -> '{mapped}' (Not found in stats)")
            failures.append(name)
            
    # Also Check League Averages
    print(f"\nLeague Avg: {model.league_avg}")

if __name__ == "__main__":
    test_mapping()
