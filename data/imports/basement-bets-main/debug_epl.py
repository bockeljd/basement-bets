import sys
import os

# Add src to path
sys.path.append(os.path.abspath('.'))

try:
    print("Importing EPLModel...")
    from src.models.epl_model import EPLModel
    print("Instantiating EPLModel...")
    epl = EPLModel()
    print("Running EPLModel...")
    edges = epl.find_edges()
    print(f"EPL Edges Found: {len(edges)} Total")
    for e in edges:
        print(f" - {e.get('game')}: {e.get('ev')}% EV (Actionable: {e.get('is_actionable')})")
except Exception as e:
    print(f"EPL FAILED: {e}")
    import traceback
    traceback.print_exc()
