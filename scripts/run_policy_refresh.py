
from src.services.policy_engine import PolicyEngine
from datetime import datetime

if __name__ == "__main__":
    print(f"[{datetime.now()}] Starting Daily Policy Refresh...")
    try:
        engine = PolicyEngine()
        engine.evaluate_markets()
        engine.evaluate_models()
        print(f"[{datetime.now()}] Policy Refresh Completed Successfully.")
    except Exception as e:
        print(f"[{datetime.now()}] Policy Refresh Failed: {e}")
        exit(1)
