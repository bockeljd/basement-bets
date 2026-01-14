import argparse
import sys
import os

# Add src to path so imports work
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from database import init_db, insert_bet, init_player_stats_db
from parsers.draftkings import DraftKingsParser
from analytics import AnalyticsEngine

def import_file(filepath):
    print(f"Processing {os.path.basename(filepath)}...")
    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: File {filepath} not found.")
        return 0

    if "WON ON FANDUEL" in content or "BET ID: O/" in content:
        # print("Detected: FanDuel")
        from src.parsers.fanduel import FanDuelParser
        parser = FanDuelParser()
        bets = parser.parse(content)
    elif content.strip().startswith("Bet #") or content.strip().startswith("1\t"):
        # print("Detected: Manual TSV")
        from src.parsers.manual_tsv import ManualTSVParser
        parser = ManualTSVParser()
        bets = parser.parse(content)
    elif "Picks" in content and "Wager: $" in content:
        # Detected: DraftKings Text Dump (Copy-Paste)
        from src.parsers.draftkings_text import DraftKingsTextParser
        parser = DraftKingsTextParser()
        bets = parser.parse(content)
    else:
        # print("Detected: DraftKings")
        dk_parser = DraftKingsParser()
        bets = dk_parser.parse_text_dump(content)
    
    count = 0
    for bet in bets:
        try:
            insert_bet(bet)
            count += 1
        except Exception as e:
            pass
    print(f"  -> {count} new bets.")
    return count

def main():
    parser = argparse.ArgumentParser(description="Betting Analytics Platform")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Init Command
    subparsers.add_parser("init", help="Initialize the database")
    
    # Import Command
    import_parser = subparsers.add_parser("import", help="Import betting data")
    import_parser.add_argument("file", help="Path to file to import")
    import_parser.add_argument("--provider", default="draftkings", choices=["draftkings", "fanduel"], help="Bookmaker name")
    
    # Ingest Command
    subparsers.add_parser("ingest", help="Bulk import all files from data/imports/")

    # Report Command
    subparsers.add_parser("report", help="Show performance report")
    
    # Enrich Command
    subparsers.add_parser("enrich", help="Fetch closing odds for pending bets")
    
    args = parser.parse_args()
    
    if args.command == "init":
        init_db()
        init_player_stats_db()
        
    elif args.command == "import":
        import_file(args.file)
            
    elif args.command == "ingest":
        imports_dir = os.path.join(os.path.dirname(__file__), 'data', 'imports')
        if not os.path.exists(imports_dir):
            print(f"Directory {imports_dir} does not exist.")
            return
            
        files = [f for f in os.listdir(imports_dir) if f.endswith('.txt') or f.endswith('.csv') or f.endswith('.html')]
        print(f"Found {len(files)} files to ingest...")
        
        total_bets = 0
        for filename in sorted(files):
             filepath = os.path.join(imports_dir, filename)
             # Skip manual financial files which are handled by their own scripts for now, 
             # OR ensure import_file handles them safely (it returns 0 if not matched).
             # The existing import_file seems robust enough.
             total_bets += import_file(filepath)
             
        print(f"=== Total Ingested: {total_bets} bets ===")
        
        # Auto-Enrich
        print("\n=== Fetching Closing Odds ===")
        from src.services.clv import ClosingOddsFetcher
        fetcher = ClosingOddsFetcher()
        fetcher.run()
            
    elif args.command == "enrich":
        from src.services.clv import ClosingOddsFetcher
        fetcher = ClosingOddsFetcher()
        fetcher.run()

    elif args.command == "report":
        engine = AnalyticsEngine()
        summary = engine.get_summary()
        
        if summary['total_bets'] == 0:
            print("No bets found in database. Run 'import' first.")
            return
            
        print("\n=== All-Time Performance ===")
        print(f"Total Bets:     {summary['total_bets']}")
        print(f"Total Wagered:  ${summary['total_wagered']:.2f}")
        print(f"Net Profit:     ${summary['net_profit']:.2f}")
        print(f"ROI:            {summary['roi']:.2f}%")
        print(f"Win Rate:       {summary['win_rate']:.1f}%")
        print("============================")
        
        print("\n=== By Sport ===")
        for row in engine.get_breakdown("sport"):
            print(f"{row['sport']:<20} | ${row['profit']:>8.2f} | {row['win_rate']:>3.0f}% Win Rate")
            
    elif args.command == "predict":
        engine = AnalyticsEngine()
        green, red = engine.get_predictions()
        
        print("\n🟢 GREEN LIGHT (Keep doing this) 🟢")
        if green:
            for item in green:
                print(f" - {item}")
        else:
            print(" - None yet. Need more profitable data.")
            
        print("\n🛑 RED LIGHT (Stay away) 🛑")
        if red:
            for item in red:
                print(f" - {item}")
        else:
            print(" - None yet. You're doing great!")
            
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
