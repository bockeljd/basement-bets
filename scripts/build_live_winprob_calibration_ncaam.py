"""Rebuild live in-game win-probability calibration from settled live_trend_snapshots.

Run locally with DATABASE_URL configured:
  ./venv/bin/python scripts/build_live_winprob_calibration_ncaam.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.services.live_calibration_service import rebuild_live_calibration


def main() -> None:
    artifact = rebuild_live_calibration(persist=True)
    print(json.dumps({
        "status": artifact.get("status"),
        "active": artifact.get("active"),
        "n_obs": artifact.get("n_obs"),
        "newly_graded": artifact.get("newly_graded", 0),
        "brier_raw": artifact.get("brier_raw"),
        "brier_calibrated": artifact.get("brier_calibrated"),
        "params": artifact.get("params"),
        "points_count": len(artifact.get("points") or []),
    }, indent=2))


if __name__ == "__main__":
    main()
