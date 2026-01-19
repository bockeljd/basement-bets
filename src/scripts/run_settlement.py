import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.services.settlement_service import SettlementEngine

def main():
    engine = SettlementEngine()
    print("[Settlement] Starting cycle...")
    stats = engine.run_settlement_cycle()
    print(f"[Settlement] Stats: {stats}")

if __name__ == "__main__":
    main()
