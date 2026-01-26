
from src.parsers.draftkings_text import DraftKingsTextParser
import json

raw_text_1 = """Share
DraftKings Brand
Icon representing a Winning Celebration
Icon representing DK Logo
SGP
2 Picks
+232
+278
Xavier, Over 161.5
Won
Wager: $10.00
Paid: $37.80
Information
Providence
Xavier
Down
Jan 10, 2026, 5:10:28 PM
DK639036798270574968"""

raw_text_2 = """Share
DraftKings Brand
Brandin Cooks
+475
Anytime TD Scorer
Lost
Wager: $5.00
KING OF THE ENDZONE
BUF Bills
DEN Broncos
Jan 17, 2026, 11:32:15 AM
DK639042643347517723"""

parser = DraftKingsTextParser()

print("--- Test 1 ---")
res1 = parser.parse(raw_text_1)
for r in res1:
    print(f"Selection: {r['selection']}")
    print(f"Odds: {r['odds']}")

print("\n--- Test 2 ---")
res2 = parser.parse(raw_text_2)
for r in res2:
    print(f"Selection: {r['selection']}")
    print(f"Odds: {r['odds']}")
