
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import init_db, init_model_history, init_transactions_tab, init_player_stats_db, init_games_db, init_events_db, init_ingestion_runs_db, init_settlement_db, init_model_registry_db, init_team_metrics_db, init_props_parlays_db, init_ingestion_backbone_db, init_team_identity_db, migrate_events_v2_schema, init_game_results_db, init_linking_queue_db

def initialize_all():
    print("Initializing Database Schema...")
    init_db()
    init_model_history()
    init_transactions_tab()
    init_player_stats_db()
    init_games_db()
    init_events_db()
    init_ingestion_runs_db()
    init_settlement_db()
    init_model_registry_db()
    init_team_metrics_db()
    init_props_parlays_db()
    init_ingestion_backbone_db()
    init_team_identity_db()
    migrate_events_v2_schema()
    init_game_results_db()
    init_linking_queue_db()
    print("All tables initialized successfully.")

if __name__ == "__main__":
    initialize_all()
