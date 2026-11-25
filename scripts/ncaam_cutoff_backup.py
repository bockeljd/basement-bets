"""Run the live cutoff checker during game windows if GitHub scheduling slips."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen


def run_production_check():
    base = "https://basement-bets.vercel.app/api/jobs/"
    headers = {"Authorization": "Bearer " + os.environ["CRON_SECRET"]}

    def call(path):
        request = Request(base + path, headers=headers)
        with urlopen(request, timeout=60) as response:
            return json.load(response)

    result = call("ncaam_top6_cutoffs")
    if result.get("checkpoint_refresh_due"):
        refresh = call("ingest_odds?scope=ncaam_checkpoints")
        print("Checkpoint odds refresh", refresh.get("status"), refresh.get("counts"), flush=True)
    return result.get("next_checkpoint_check_at")


def main():
    schedule = Path(__file__).with_suffix(".next")
    if sys.argv[1:] == ["--check"]:
        next_at = run_production_check()
        if next_at:
            schedule.write_text(str(dt.datetime.fromisoformat(next_at).timestamp()))
        print("Live cutoff check completed", dt.datetime.now(dt.timezone.utc).isoformat(), flush=True)
        return
    try:
        # Recheck within half an hour for schedule changes.
        delay = float(schedule.read_text()) - time.time()
        if 0 < delay <= 1800:
            return
    except (OSError, ValueError):
        pass
    # Vercel supplies the existing production cron credential only to the child process.
    subprocess.run(["vercel", "env", "run", "-e", "production", "--",
                    sys.executable, str(Path(__file__).resolve()), "--check"], check=True)


if __name__ == "__main__":
    main()
