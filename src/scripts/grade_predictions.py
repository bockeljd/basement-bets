"""CLI runner to ingest latest/backfill final scores and grade pending predictions."""

import argparse
import json
import os
import sys

# Ensure project root is on sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.services.grading_service import GradingService


def main() -> int:
    parser = argparse.ArgumentParser(description="Grade pending model predictions.")
    parser.add_argument("--backfill-days", type=int, default=int(os.getenv("GRADING_FINALS_BACKFILL_DAYS", "3")))
    parser.add_argument("--backfill-pending", action="store_true", default=os.getenv("GRADING_BACKFILL_PENDING", "0") == "1")
    parser.add_argument("--max-clv-rows", type=int, default=250)
    parser.add_argument("--max-grade-rows", type=int, default=5000)
    parser.add_argument("--skip-clv", action="store_true", default=False)
    args = parser.parse_args()

    print(
        f"[SCRIPT] Running prediction auto-grader "
        f"(backfill_days={args.backfill_days}, backfill_pending={args.backfill_pending})..."
    )
    svc = GradingService()
    res = svc.grade_predictions(
        backfill_days=args.backfill_days,
        backfill_pending=bool(args.backfill_pending),
        max_clv_rows=args.max_clv_rows,
        max_grade_rows=args.max_grade_rows,
        skip_clv=bool(args.skip_clv),
        include_all_ev=True,
    )
    print(f"[SCRIPT] Grading completed: {json.dumps(res, default=str)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
