#!/bin/sh
set -eu
repo=bockeljd/basement-bets
workflow=ncaam_jobs.yml
# GitHub's scheduler may be delayed. Leave a recent or active worker alone.
latest=$(gh run list --repo "$repo" --workflow "$workflow" --limit 1 --json status,createdAt)
if /usr/bin/python3 -c '
import datetime, json, sys
runs=json.load(sys.stdin)
if not runs:
    sys.exit(1)
run=runs[0]
age=datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(run["createdAt"].replace("Z","+00:00"))
sys.exit(0 if run["status"] != "completed" or age.total_seconds() < 900 else 1)
' <<JSON
$latest
JSON
then
    exit 0
fi
gh workflow run "$workflow" --repo "$repo" --ref main
