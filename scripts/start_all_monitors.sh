#!/bin/bash
# Start all monitoring processes
# This script can be called by cron or systemd to auto-recover after restart

cd /home/user/.super_doubao/super-doubao-runtime/workspace/webscout-mcp

# Kill existing processes
pkill -f "stability_test_24h.py" 2>/dev/null
pkill -f "comprehensive_test.py" 2>/dev/null
pkill -f "qq_email_monitor.py" 2>/dev/null
pkill -f "active_monitor.py" 2>/dev/null
sleep 2

# Start 24h stability test
nohup python3 scripts/stability_test_24h.py > stability_test.log 2>&1 &
echo "Stability test started: PID $!"

# Start comprehensive function test
nohup python3 scripts/comprehensive_test.py > comprehensive_test.log 2>&1 &
echo "Comprehensive test started: PID $!"

# Start QQ email monitor (requires QQ_EMAIL_USER and QQ_EMAIL_AUTH_CODE env vars)
QQ_EMAIL_USER="${QQ_EMAIL_USER:-}" QQ_EMAIL_AUTH_CODE="${QQ_EMAIL_AUTH_CODE:-}" nohup python3 scripts/qq_email_monitor.py > qq_email_monitor.log 2>&1 &
echo "Email monitor started: PID $!"

# Start active monitor (requires GITHUB_TOKEN env var)
GITHUB_TOKEN="${GITHUB_TOKEN:-}" nohup python3 scripts/active_monitor.py > active_monitor.log 2>&1 &
echo "Active monitor started: PID $!"

echo ""
echo "✅ All monitors started!"
sleep 3
ps aux | grep -E "stability_test|comprehensive_test|qq_email_monitor|active_monitor" | grep -v grep | awk '{print "  -", $12, $13, "PID:", $2}'
