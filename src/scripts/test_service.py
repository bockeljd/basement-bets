
from src.services.draftkings_service import DraftKingsService
import sys

def test():
    print("🧪 Starting Service Diagnostic...")
    try:
        service = DraftKingsService()
        print("✅ Service Initialized. calling scrape_history()...")
        bets = service.scrape_history()
        print(f"✅ Scrape Complete. Found {len(bets)} bets.")
        for b in bets[:3]:
            print(f"   - {b['date']}: {b['description']} ({b['status']})")
    except Exception as e:
        print(f"❌ Diagnostic Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test()
