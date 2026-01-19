import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__)))) # Add scripts/ to path
# Also add root for src imports inside grade_ncaam_season
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from grade_ncaam_season import grade_predictions

if __name__ == "__main__":
    print("Forcing Grading Only...")
    grade_predictions()
    print("Done.")
