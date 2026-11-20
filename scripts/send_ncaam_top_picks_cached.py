"""Publish and print the immutable daily NCAAM Top 6."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.services.ncaam_publisher import publish_slate

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--force", action="store_true", help="Read the frozen slate on retry")
    args = parser.parse_args()
    result = publish_slate(args.date)
    print(f"{result['status']} · {result['slate_id']}")
    for item in result["items"][:max(0, args.limit)]:
        price = f"{item['bet_price']:+d}" if item['bet_price'] is not None else "odds unavailable"
        print(f"{item['rank']}) {item['away_team']} @ {item['home_team']} · "
              f"{item['selection']} ({price}) · {item['book'] or 'book unavailable'} · "
              f"EV {item['edge'] or 'unavailable'}")
