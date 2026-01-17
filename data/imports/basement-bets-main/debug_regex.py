import re

line = 'Wager: $10.00Paid: $37.80'
print(f"Test Line: {repr(line)}")

pattern = r'Paid:[\s\xa0]*\$([\d\.]+)'
print(f"Pattern: {pattern}")

match = re.search(pattern, line)
print(f"Match: {match}")
if match:
    print(f"Group 1: {match.group(1)}")
else:
    print("NO MATCH")
