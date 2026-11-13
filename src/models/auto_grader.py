"""Legacy AutoGrader wrapper backed by GradingService."""

from src.services.grading_service import GradingService


class AutoGrader:
    """Backward-compatible entry point delegating grading to GradingService."""

    def __init__(self):
        self.service = GradingService()

    def grade_pending_picks(
        self,
        *,
        backfill_days: int = 3,
        backfill_pending: bool = False,
        max_grade_rows: int = 5000,
        skip_clv: bool = False,
    ):
        res = self.service.grade_predictions(
            backfill_days=backfill_days,
            backfill_pending=backfill_pending,
            max_grade_rows=max_grade_rows,
            skip_clv=skip_clv,
            include_all_ev=True,
        )
        return {
            "graded_count": int(res.get("graded") or 0),
            "logs": [],
            **res,
        }
