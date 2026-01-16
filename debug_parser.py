import sys
import os
import re

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.parsers.draftkings_text import DraftKingsTextParser

def debug_parser():
    filepath = 'data/imports/2026-01-11_draftkings.txt'
    with open(filepath, 'r') as f:
        content = f.read()

    parser = DraftKingsTextParser()
    bets = parser.parse(content)
    
    print(f"Parsed {len(bets)} bets.")
    for b in bets:
        if b['status'] == 'WON':
            print(f"Status: {b['status']} | Wager: {b['wager']} | Profit: {b['profit']} | Selection: {b['selection'][:30]}...")
            
            # Find the raw wager line in raw_text if possible, or just re-read file?
            # bet object stores raw_text.
            raw = b.get('raw_text', '')
            lines = raw.split('\n')
            if len(lines) > 3:
                vline = lines[3]
                print(f"   Line 3 Repr: {repr(vline)}")
                print(f"   'Paid' in line: {'Paid' in vline}")
                
            break # Just one

if __name__ == "__main__":
    debug_parser()
