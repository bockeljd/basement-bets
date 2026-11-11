
import sys
import os
import json
import logging
from datetime import datetime

# Allow imports from src
sys.path.append(os.getcwd())

from src.services.correlation.ncaam_correlation_engine import NCAAMCorrelationEngine
from src.utils.ncaam_season import current_ncaam_season_long

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_cache():
    season_long = current_ncaam_season_long()
    cache_file = f"data/correlation_cache_{season_long.replace('-', '_')}.json"
    logger.info(f"Starting Correlation Cache Build ({season_long})...")
    
    engine = NCAAMCorrelationEngine()
    
    # 1. Fetch Data
    logger.info("Fetching season data...")
    df = engine.fetch_season_data()
    logger.info(f"Fetched {len(df)} games.")
    
    # 2. Build Bins
    df = engine.build_archetype_bins(df)
    
    # 3. Compute Metrics
    logger.info("Computing metrics...")
    metrics = engine.compute_metrics(df)
    
    # 4. Save
    output = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "season": season_long,
            "games_count": len(df)
        },
        "archetypes": metrics
    }
    
    with open(cache_file, "w") as f:
        json.dump(output, f, indent=2)
        
    logger.info(f"Cache saved to {cache_file}")

if __name__ == "__main__":
    build_cache()
