
from src.database import store_daily_evaluation
from datetime import datetime

if __name__ == "__main__":
    today = datetime.now().strftime("%Y-%m-%d")
    metrics = [{
        "date": today,
        "model_version_id": "manual",
        "league": "NCAAM", 
        "market_type": "Spread",
        "metric_name": "roi",
        "metric_value": 0.05,
        "sample_size": 10
    }]
    print(f"Seeding metrics for {today}...")
    store_daily_evaluation(metrics)
    print("Seeded.")
