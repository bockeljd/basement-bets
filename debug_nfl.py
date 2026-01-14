import nfl_data_py as nfl
import sys

print(f"nfl_data_py version: {nfl.__version__}")

try:
    print("Attempting 2024 download...")
    pbp = nfl.import_pbp_data([2024], downcast=True, cache=False)
    print(f"Success! Rows: {len(pbp)}")
except Exception as e:
    print(f"2024 Failed: {e}")

try:
    print("Attempting 2025 download...")
    pbp = nfl.import_pbp_data([2025], downcast=True, cache=False)
    print(f"Success! Rows: {len(pbp)}")
except Exception as e:
    print(f"2025 Failed: {e}")
