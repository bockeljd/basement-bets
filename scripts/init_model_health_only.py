
from src.database import init_model_health_db, init_model_health_insights_db

if __name__ == "__main__":
    print("Initializing Model Health DB...")
    init_model_health_db()
    init_model_health_insights_db()
    print("Done.")
    print("Done.")
