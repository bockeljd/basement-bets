"""
Install, uninstall, or inspect the local macOS LaunchAgent for Basement Bets sportsbook sync worker.
Runs `scripts/sync_worker.py --loop --sleep 30` automatically in the background on this Mac
so queued DraftKings / FanDuel sync jobs execute without manually keeping a terminal open.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


LAUNCHD_LABEL = "com.basementbets.syncworker"


def build_launchd_plist(
    repo_dir: Path,
    python_bin: Path,
    log_path: Path,
    dk_profile_path: Path,
    sleep_seconds: int = 30,
) -> Dict[str, Any]:
    env_vars: Dict[str, str] = {
        "PYTHONUNBUFFERED": "1",
        "DK_HEADLESS": "1",
        "DK_ALLOW_INTERACTIVE_AUTH": "0",
        "DK_PROFILE_PATH": str(dk_profile_path),
    }
    for key in ("DATABASE_URL", "NEON_DATABASE_URL", "BASEMENT_PASSWORD"):
        val = os.getenv(key)
        if val:
            env_vars[key] = val

    return {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [
            str(python_bin),
            str(repo_dir / "scripts" / "sync_worker.py"),
            "--loop",
            "--sleep",
            str(int(sleep_seconds)),
        ],
        "WorkingDirectory": str(repo_dir),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
        "EnvironmentVariables": env_vars,
    }


def install_agent(sleep_seconds: int = 30, load_now: bool = True) -> Path:
    repo_dir = Path(__file__).resolve().parent.parent
    python_bin = repo_dir / "venv" / "bin" / "python"
    if not python_bin.exists():
        python_bin = Path(sys.executable)

    launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
    log_dir = Path.home() / "Library" / "Logs"
    dk_profile_path = Path.home() / ".basementbets" / "dk_chrome_profile"
    launch_agents_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    dk_profile_path.mkdir(parents=True, exist_ok=True)

    plist_path = launch_agents_dir / f"{LAUNCHD_LABEL}.plist"
    log_path = log_dir / "basementbets-sync-worker.log"
    plist_obj = build_launchd_plist(
        repo_dir=repo_dir,
        python_bin=python_bin,
        log_path=log_path,
        dk_profile_path=dk_profile_path,
        sleep_seconds=sleep_seconds,
    )
    with plist_path.open("wb") as fh:
        plistlib.dump(plist_obj, fh)

    if load_now:
        subprocess.run(["launchctl", "unload", str(plist_path)], check=False, capture_output=True)
        subprocess.run(["launchctl", "load", "-w", str(plist_path)], check=False)

    return plist_path


def uninstall_agent() -> bool:
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
    if plist_path.exists():
        subprocess.run(["launchctl", "unload", "-w", str(plist_path)], check=False, capture_output=True)
        plist_path.unlink(missing_ok=True)
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Basement Bets Mac LaunchAgent for DK/FD sync worker.")
    parser.add_argument("action", choices=("install", "uninstall", "status"), default="install", nargs="?")
    parser.add_argument("--sleep", type=int, default=30, help="Worker poll interval in seconds.")
    parser.add_argument("--no-load", action="store_true", help="Write plist without running launchctl load.")
    args = parser.parse_args()

    if args.action == "install":
        plist_path = install_agent(sleep_seconds=args.sleep, load_now=not args.no_load)
        print(f"[MacSyncAgent] Installed LaunchAgent: {plist_path}")
        print("[MacSyncAgent] Log file: ~/Library/Logs/basementbets-sync-worker.log")
        return 0
    if args.action == "uninstall":
        removed = uninstall_agent()
        print("[MacSyncAgent] Uninstalled." if removed else "[MacSyncAgent] LaunchAgent was not installed.")
        return 0

    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
    print(f"[MacSyncAgent] Plist present: {plist_path.exists()} ({plist_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
