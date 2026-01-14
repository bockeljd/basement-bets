from src.parsers.manual_tsv import ManualTSVParser
import re

with open("bet_tracker/data/imports/manual_history.txt", "r") as f:
    content = f.read()

parser = ManualTSVParser()

# Monkey patch or just duplicate logic to debug
lines = content.split('\n')
for i, line in enumerate(lines):
    if "Leg" in line and "See Below" not in line:
        print(f"--- Line {i} ---")
        print(f"Raw: {repr(line)}")
        
        cols = line.split('\t')
        print(f"Tab Split Len: {len(cols)}")
        print(f"Tab Split Cols: {cols}")
        
        if len(cols) < 5 and len(line) > 20:
            cols = re.split(r'\s{2,}', line)
            print(f"Regex Split Used. Cols: {cols}")
        
        print(f"Col[0]: '{cols[0]}'")
        if len(cols) > 3:
             print(f"Col[3]: '{cols[3]}'")
        
        if i > 50: break
