
import sys
import os

# Ensure root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.services.settlement_service import SettlementEngine

if __name__ == "__main__":
    print("Starting Settlement Cycle...")
    engine = SettlementEngine()
    engine.run_settlement_cycle()
    print("Settlement Cycle Complete.")
