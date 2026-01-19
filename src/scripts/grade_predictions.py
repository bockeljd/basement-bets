import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.models.auto_grader import AutoGrader

def main():
    grader = AutoGrader()
    print("[Grading] Starting prediction grading...")
    res = grader.grade_pending_picks()
    print(f"[Grading] Results: {res}")

if __name__ == "__main__":
    main()
