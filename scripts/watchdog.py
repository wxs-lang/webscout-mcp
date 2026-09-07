#!/usr/bin/env python3
"""
Watchdog - Monitor and auto-recover all monitoring processes.

Runs in background, checks every 60 seconds if all monitors are running.
If any monitor stops, automatically restarts it.
"""

import subprocess
import time
import os
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).parent.parent
WATCHDOG_LOG = PROJECT_DIR / "watchdog.log"

# Monitors to watch
MONITORS = [
    {
        "name": "stability_test",
        "pattern": "stability_test_24h.py",
        "command": ["python3", "scripts/stability_test_24h.py"],
        "logfile": "stability_test.log",
        "env": {},
    },
    {
        "name": "comprehensive_test",
        "pattern": "comprehensive_test.py",
        "command": ["python3", "scripts/comprehensive_test.py"],
        "logfile": "comprehensive_test.log",
        "env": {},
    },
    {
        "name": "qq_email_monitor",
        "pattern": "qq_email_monitor.py",
        "command": ["python3", "scripts/qq_email_monitor.py"],
        "logfile": "qq_email_monitor.log",
        "env": {
            "QQ_EMAIL_USER": os.environ.get("QQ_EMAIL_USER", ""),
            "QQ_EMAIL_AUTH_CODE": os.environ.get("QQ_EMAIL_AUTH_CODE", ""),
        },
    },
    {
        "name": "active_monitor",
        "pattern": "active_monitor.py",
        "command": ["python3", "scripts/active_monitor.py"],
        "logfile": "active_monitor.log",
        "env": {
            "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
        },
    },
]

CHECK_INTERVAL = 60  # seconds


def log(message):
    """Log message with timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] {message}"
    print(entry)
    with open(WATCHDOG_LOG, "a") as f:
        f.write(entry + "\n")


def is_process_running(pattern):
    """Check if a process matching the pattern is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True, text=True, timeout=5
        )
        pids = result.stdout.strip().split("\n") if result.stdout.strip() else []
        # Filter out the watchdog itself
        pids = [p for p in pids if p]
        return len(pids) > 0
    except Exception:
        return False


def start_monitor(monitor):
    """Start a monitor process."""
    name = monitor["name"]
    command = monitor["command"]
    logfile = PROJECT_DIR / monitor["logfile"]
    env = os.environ.copy()
    env.update(monitor["env"])

    try:
        with open(logfile, "a") as log_f:
            process = subprocess.Popen(
                command,
                cwd=str(PROJECT_DIR),
                stdout=log_f,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
        log(f"✅ Started {name} (PID: {process.pid})")
        return True
    except Exception as e:
        log(f"❌ Failed to start {name}: {e}")
        return False


def main():
    """Main watchdog loop."""
    print("=" * 80)
    print("🐕 WATCHDOG - Monitor Auto-Recovery Service")
    print("=" * 80)
    print(f"Project: {PROJECT_DIR}")
    print(f"Check interval: {CHECK_INTERVAL}s")
    print(f"Monitors to watch: {len(MONITORS)}")
    print("=" * 80 + "\n")

    log("Watchdog started")

    while True:
        try:
            log("--- Checking monitor status ---")
            all_running = True

            for monitor in MONITORS:
                name = monitor["name"]
                pattern = monitor["pattern"]

                if is_process_running(pattern):
                    log(f"  ✅ {name}: running")
                else:
                    log(f"  ❌ {name}: NOT RUNNING - restarting...")
                    all_running = False
                    start_monitor(monitor)

            if all_running:
                log("✅ All monitors running normally")

        except Exception as e:
            log(f"⚠️  Error in watchdog loop: {e}")

        log(f"💤 Sleeping {CHECK_INTERVAL}s...\n")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
