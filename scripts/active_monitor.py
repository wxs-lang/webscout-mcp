#!/usr/bin/env python3
"""
Active Monitor - Proactively monitor all aspects of the project.

Monitors:
1. QQ Email - error notifications
2. GitHub CI - workflow status
3. Stability Test - 24h test results
4. Comprehensive Test - all MCP tools
5. System Resources - memory, CPU, disk

Checks every 60 seconds. Alerts on any failures.
"""

import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# ============================================================
# Configuration
# ============================================================

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO_OWNER = "wxs-lang"
REPO_NAME = "webscout-mcp"

CHECK_INTERVAL = 60  # seconds

PROJECT_DIR = Path(__file__).parent.parent
MONITOR_LOG = PROJECT_DIR / "active_monitor.log"
ALERT_LOG = PROJECT_DIR / "alerts.log"

WORKFLOWS = [
    "tests",
    "quality",
    "publish",
    "live-tests",
    "mcp-live-e2e",
    "docker-publish",
]

# ============================================================
# Logging
# ============================================================

def log(message, level="INFO"):
    """Log message with timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] [{level}] {message}"
    print(entry)
    with open(MONITOR_LOG, "a") as f:
        f.write(entry + "\n")


def alert(message, severity="WARNING"):
    """Log an alert."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] [{severity}] 🚨 ALERT: {message}"
    print(entry)
    with open(ALERT_LOG, "a") as f:
        f.write(entry + "\n")
    with open(MONITOR_LOG, "a") as f:
        f.write(entry + "\n")


# ============================================================
# GitHub CI Monitoring
# ============================================================

def github_api_get(endpoint):
    """Make a GET request to GitHub API."""
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/{endpoint}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def check_ci_status():
    """Check all CI workflow statuses."""
    log("Checking CI status...")
    failures = []
    results = {}

    for workflow in WORKFLOWS:
        try:
            data = github_api_get(f"actions/workflows/{workflow}.yml/runs?per_page=1")
            runs = data.get("workflow_runs", [])
            if runs:
                run = runs[0]
                status = run.get("status")
                conclusion = run.get("conclusion")
                results[workflow] = {"status": status, "conclusion": conclusion}

                if conclusion == "failure":
                    failures.append(workflow)
                    alert(f"CI workflow failed: {workflow} (run: {run.get('id')})", "CRITICAL")
                elif status == "in_progress":
                    log(f"  {workflow}: in progress")
                else:
                    log(f"  ✅ {workflow}: {conclusion}")
            else:
                log(f"  ⚠️  {workflow}: no runs found")
        except Exception as e:
            log(f"  ❌ {workflow}: error - {e}", "ERROR")
            failures.append(f"{workflow}(error)")

    return results, failures


# ============================================================
# Process Monitoring
# ============================================================

def check_process(process_name):
    """Check if a process is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", process_name],
            capture_output=True, text=True, timeout=5
        )
        pids = result.stdout.strip().split("\n") if result.stdout.strip() else []
        return len(pids) > 0, pids
    except Exception:
        return False, []


def check_all_processes():
    """Check all monitoring processes."""
    log("Checking processes...")
    processes = {
        "stability_test": "stability_test_24h.py",
        "comprehensive_test": "comprehensive_test.py",
        "email_monitor": "qq_email_monitor.py",
    }

    status = {}
    for name, pattern in processes.items():
        running, pids = check_process(pattern)
        status[name] = {"running": running, "pids": pids}
        if running:
            log(f"  ✅ {name}: running (PID: {', '.join(pids[:3])})")
        else:
            alert(f"Process not running: {name}", "WARNING")
            log(f"  ❌ {name}: NOT RUNNING")

    return status


# ============================================================
# Log File Monitoring
# ============================================================

def check_log_for_errors(log_file, error_patterns=None):
    """Check a log file for recent errors."""
    if error_patterns is None:
        error_patterns = ["ERROR", "FAILED", "Traceback", "Exception", "❌"]

    if not log_file.exists():
        return False, []

    try:
        # Read last 100 lines
        with open(log_file, "r") as f:
            lines = f.readlines()[-100:]

        errors = []
        for line in lines:
            for pattern in error_patterns:
                if pattern in line:
                    errors.append(line.strip())
                    break

        return len(errors) > 0, errors[-5:]  # Return last 5 errors
    except Exception as e:
        log(f"Error reading {log_file}: {e}", "ERROR")
        return False, []


def check_all_logs():
    """Check all log files for errors."""
    log("Checking log files...")
    logs = {
        "stability_test": PROJECT_DIR / "stability_test.log",
        "comprehensive_test": PROJECT_DIR / "comprehensive_test.log",
        "email_monitor": PROJECT_DIR / "qq_email_monitor.log",
        "email_errors": PROJECT_DIR / "email_errors.log",
        "alerts": PROJECT_DIR / "alerts.log",
    }

    results = {}
    for name, log_path in logs.items():
        has_errors, errors = check_log_for_errors(log_path)
        results[name] = {"has_errors": has_errors, "errors": errors}
        if has_errors:
            alert(f"Errors found in {name} log: {errors[0][:80]}", "WARNING")
        else:
            log(f"  ✅ {name}: no errors")

    return results


# ============================================================
# System Resource Monitoring
# ============================================================

def check_system_resources():
    """Check system resource usage."""
    log("Checking system resources...")
    try:
        # Memory
        with open("/proc/meminfo", "r") as f:
            meminfo = f.read()
        total_mem = int([l for l in meminfo.split("\n") if "MemTotal" in l][0].split()[1]) / 1024
        available_mem = int([l for l in meminfo.split("\n") if "MemAvailable" in l][0].split()[1]) / 1024
        used_mem = total_mem - available_mem
        mem_percent = (used_mem / total_mem) * 100

        # Disk
        disk = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
        disk_info = disk.stdout.strip().split("\n")[-1].split()

        log(f"  Memory: {used_mem:.0f}MB / {total_mem:.0f}MB ({mem_percent:.1f}%)")
        log(f"  Disk: {disk_info[2]} used / {disk_info[1]} total ({disk_info[4]})")

        if mem_percent > 80:
            alert(f"High memory usage: {mem_percent:.1f}%", "WARNING")

        return {
            "memory_used_mb": round(used_mem, 1),
            "memory_total_mb": round(total_mem, 1),
            "memory_percent": round(mem_percent, 1),
            "disk_used": disk_info[2],
            "disk_total": disk_info[1],
            "disk_percent": disk_info[4],
        }
    except Exception as e:
        log(f"Error checking system resources: {e}", "ERROR")
        return {}


# ============================================================
# Report Generation
# ============================================================

def generate_report(ci_status, process_status, log_status, system_status):
    """Generate a comprehensive monitoring report."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "ci_status": ci_status,
        "process_status": process_status,
        "log_status": {k: {"has_errors": v["has_errors"]} for k, v in log_status.items()},
        "system_status": system_status,
    }

    report_file = PROJECT_DIR / "monitoring_report.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return report


# ============================================================
# Main Monitor Loop
# ============================================================

def main():
    """Main monitoring loop."""
    print("=" * 80)
    print("🔍 ACTIVE MONITOR - Project Health Monitoring")
    print("=" * 80)
    print(f"Repository: {REPO_OWNER}/{REPO_NAME}")
    print(f"Check interval: {CHECK_INTERVAL}s")
    print(f"Log file: {MONITOR_LOG}")
    print(f"Alert file: {ALERT_LOG}")
    print("=" * 80 + "\n")

    iteration = 0
    while True:
        iteration += 1
        print(f"\n{'─' * 80}")
        print(f"📊 MONITOR ITERATION {iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'─' * 80}\n")

        try:
            # 1. Check CI status
            ci_status, ci_failures = check_ci_status()

            # 2. Check processes
            process_status = check_all_processes()

            # 3. Check logs
            log_status = check_all_logs()

            # 4. Check system resources
            system_status = check_system_resources()

            # 5. Generate report (logged internally)
            generate_report(ci_status, process_status, log_status, system_status)

            # Summary
            total_alerts = sum(1 for v in log_status.values() if v["has_errors"])
            total_process_down = sum(1 for v in process_status.values() if not v["running"])

            print(f"\n{'─' * 80}")
            print("📋 SUMMARY")
            print(f"{'─' * 80}")
            print(f"  CI Failures: {len(ci_failures)}")
            print(f"  Processes Down: {total_process_down}")
            print(f"  Log Alerts: {total_alerts}")
            print(f"  System: {system_status.get('memory_percent', 'N/A')}% memory")

            if len(ci_failures) == 0 and total_process_down == 0 and total_alerts == 0:
                print("\n  ✅ ALL SYSTEMS NOMINAL")
            else:
                print("\n  ⚠️  ISSUES DETECTED - See alerts.log for details")

        except Exception as e:
            alert(f"Monitor iteration failed: {e}", "ERROR")
            import traceback
            traceback.print_exc()

        print(f"\n💤 Sleeping {CHECK_INTERVAL}s...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
