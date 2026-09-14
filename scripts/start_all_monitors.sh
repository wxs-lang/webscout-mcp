#!/usr/bin/env bash
# Auto-start all WebScout monitors after environment reboot.
# Registered via crontab @reboot. Safe to re-run - skips already-running processes.

PROJECT_DIR="/home/user/.super_doubao/super-doubao-runtime/workspace/webscout-mcp"
cd "$PROJECT_DIR" || exit 1

# Secrets are injected from the environment, never hardcoded in the repo.
# To run manually: GITHUB_TOKEN=... QQ_EMAIL_USER=... QQ_EMAIL_AUTH_CODE=... ./scripts/start_all_monitors.sh
export GITHUB_TOKEN="${GITHUB_TOKEN:-}"
export QQ_EMAIL_USER="${QQ_EMAIL_USER:-393456156@qq.com}"
export QQ_EMAIL_AUTH_CODE="${QQ_EMAIL_AUTH_CODE:-}"

ensure_running() {
    local pattern="$1"
    local command="$2"
    local logfile="$3"

    if pgrep -f "$pattern" > /dev/null 2>&1; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] already running: $pattern"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] starting: $command"
        nohup python3 $command >> "$logfile" 2>&1 &
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] started (PID $!): $command"
    fi
}

mkdir -p "$PROJECT_DIR/stability-7day-results" "$PROJECT_DIR/logs"

# 7-day stability test (highest priority)
ensure_running "stability_test_7day.py" "scripts/stability_test_7day.py --duration 7 --interval 1800" "stability-7day-results/stability_test.log"

# Watchdog (self-healing for all monitors)
ensure_running "watchdog.py" "scripts/watchdog.py" "watchdog.log"

# Email monitor
ensure_running "qq_email_monitor.py" "scripts/qq_email_monitor.py" "qq_email_monitor.log"

# Active monitor (CI + process + resource checks)
ensure_running "active_monitor.py" "scripts/active_monitor.py" "active_monitor.log"

# Comprehensive functional test
ensure_running "comprehensive_test.py" "scripts/comprehensive_test.py" "comprehensive_test.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] auto-start complete."
