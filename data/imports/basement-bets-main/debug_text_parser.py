from src.parsers.draftkings_text import DraftKingsTextParser
import json

with open("data/imports/dk_copypaste_sample.txt", "r") as f:
    content = f.read()
    
parser = DraftKingsTextParser()
bets = parser.parse(content)

print(f"Parsed {len(bets)} bets.")
for bet in bets:
    print(json.dumps(bet, indent=2, default=str))
