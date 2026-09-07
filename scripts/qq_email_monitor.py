#!/usr/bin/env python3
"""
QQ Email Monitor - Monitor QQ mailbox for error notifications.

Connects to QQ Mail via IMAP and checks for new emails related to
project errors (CI failures, PyPI issues, GitHub notifications, etc.).

Setup:
1. Enable IMAP/SMTP service in QQ Mail settings
2. Get an authorization code (not your login password)
3. Set environment variables or edit config below:
   - QQ_EMAIL_USER: your QQ email address (e.g., 393456156@qq.com)
   - QQ_EMAIL_AUTH_CODE: your QQ email authorization code

Usage:
    python3 scripts/qq_email_monitor.py
"""

import imaplib
import email
from email.header import decode_header
import time
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path


# ============================================================
# Configuration
# ============================================================

QQ_EMAIL_USER = os.environ.get("QQ_EMAIL_USER", "393456156@qq.com")
QQ_EMAIL_AUTH_CODE = os.environ.get("QQ_EMAIL_AUTH_CODE", "")

IMAP_SERVER = "imap.qq.com"
IMAP_PORT = 993

# Check interval in seconds
CHECK_INTERVAL = 300  # 5 minutes

# Keywords that indicate error emails
ERROR_KEYWORDS = [
    "error", "failed", "failure", "build failed", "ci failed",
    "pypi", "publish failed", "github", "action", "workflow",
    "exception", "traceback", "bug", "issue", "alert",
    "失败", "错误", "报错", "异常",
]

# Project-related keywords
PROJECT_KEYWORDS = [
    "webscout", "webscout-mcp", "wxs-lang",
    "github.com/wxs-lang", "pypi.org/project/webscout",
]

# Output file for detected errors
OUTPUT_FILE = Path(__file__).parent.parent / "email_errors.log"

# State file to track processed emails
STATE_FILE = Path(__file__).parent.parent / ".email_monitor_state.json"


# ============================================================
# Email Decoding Helpers
# ============================================================

def decode_email_header(header_value):
    """Decode email header that may contain encoded words."""
    if not header_value:
        return ""
    decoded_parts = decode_header(header_value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                result.append(part.decode("utf-8", errors="replace"))
        else:
            result.append(str(part))
    return "".join(result)


def get_email_body(msg):
    """Extract plain text body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    body += payload.decode(charset, errors="replace")
                except Exception:
                    pass
            elif content_type == "text/html" and not body:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    html = payload.decode(charset, errors="replace")
                    # Simple HTML tag removal
                    body += re.sub(r"<[^>]+>", " ", html)
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
        except Exception:
            body = str(msg.get_payload())
    return body[:2000]  # Limit body length


# ============================================================
# State Management
# ============================================================

def load_state():
    """Load processed email IDs from state file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"processed_ids": [], "last_check": None}


def save_state(state):
    """Save processed email IDs to state file."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"⚠️  Failed to save state: {e}")


# ============================================================
# Error Detection
# ============================================================

def is_error_email(subject, body, sender):
    """Check if email is related to project errors."""
    text = f"{subject} {body} {sender}".lower()

    # Check if email is project-related
    is_project = any(kw.lower() in text for kw in PROJECT_KEYWORDS)

    # Check if email contains error keywords
    has_error = any(kw.lower() in text for kw in ERROR_KEYWORDS)

    # Also check for GitHub action failure patterns
    github_patterns = [
        r"workflow.*fail", r"build.*fail", r"action.*fail",
        r"run.*fail", r"ci.*fail",
    ]
    is_github_error = any(re.search(p, text) for p in github_patterns)

    return is_project and (has_error or is_github_error)


def log_error_email(email_id, subject, sender, date, body):
    """Log detected error email to output file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"""
{'='*80}
⚠️  ERROR EMAIL DETECTED
{'='*80}
Time:     {timestamp}
Email ID: {email_id}
Date:     {date}
From:     {sender}
Subject:  {subject}

Body (first 500 chars):
{body[:500]}
{'='*80}
"""
    try:
        with open(OUTPUT_FILE, "a") as f:
            f.write(log_entry)
        print(f"📝 Error logged to {OUTPUT_FILE}")
    except Exception as e:
        print(f"⚠️  Failed to log error: {e}")

    # Also print to console
    print(log_entry)


# ============================================================
# IMAP Connection
# ============================================================

def connect_imap():
    """Connect to QQ Mail IMAP server."""
    if not QQ_EMAIL_AUTH_CODE:
        print("❌ QQ_EMAIL_AUTH_CODE not set. Please set your QQ email authorization code.")
        print("   How to get authorization code:")
        print("   1. Open QQ Mail (mail.qq.com)")
        print("   2. Go to Settings → Accounts → IMAP/SMTP service")
        print("   3. Enable IMAP/SMTP service")
        print("   4. Click 'Generate authorization code' and follow instructions")
        print("   5. Set environment variable: export QQ_EMAIL_AUTH_CODE='your_code'")
        return None

    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(QQ_EMAIL_USER, QQ_EMAIL_AUTH_CODE)
        print(f"✅ Connected to QQ Mail: {QQ_EMAIL_USER}")
        return mail
    except imaplib.IMAP4.error as e:
        print(f"❌ IMAP login failed: {e}")
        print("   Please check your email address and authorization code.")
        return None
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return None


def check_new_emails(mail, state):
    """Check for new error emails in inbox."""
    try:
        mail.select("INBOX")

        # Search for recent emails (last 1 hour to avoid processing too many historical emails)
        since_date = (datetime.now() - timedelta(hours=1)).strftime("%d-%b-%Y")
        status, messages = mail.search(None, f'(SINCE "{since_date}")')

        if status != "OK":
            print("⚠️  Failed to search emails")
            return

        email_ids = messages[0].split()
        # Only check the latest 20 emails to avoid processing too many
        email_ids = email_ids[-20:]
        print(f"📧 Found {len(email_ids)} new emails to check (latest 20)")

        new_errors = 0
        for eid in email_ids:
            eid_str = eid.decode()

            # Skip already processed emails
            if eid_str in state["processed_ids"]:
                continue

            try:
                status, msg_data = mail.fetch(eid, "(RFC822)")
                if status != "OK":
                    continue

                msg = email.message_from_bytes(msg_data[0][1])

                subject = decode_email_header(msg.get("Subject", ""))
                sender = decode_email_header(msg.get("From", ""))
                date = msg.get("Date", "")
                body = get_email_body(msg)

                if is_error_email(subject, body, sender):
                    log_error_email(eid_str, subject, sender, date, body)
                    new_errors += 1

                # Mark as processed
                state["processed_ids"].append(eid_str)

            except Exception as e:
                print(f"⚠️  Error processing email {eid_str}: {e}")

        # Keep only last 500 processed IDs to avoid state file bloat
        if len(state["processed_ids"]) > 500:
            state["processed_ids"] = state["processed_ids"][-500:]

        state["last_check"] = datetime.now().isoformat()
        save_state(state)

        if new_errors > 0:
            print(f"🔴 Found {new_errors} new error email(s)!")
        else:
            print(f"✅ No new error emails found")

    except Exception as e:
        print(f"⚠️  Error checking emails: {e}")


# ============================================================
# Main Loop
# ============================================================

def main():
    """Main monitoring loop."""
    print("=" * 80)
    print("📧 QQ Email Monitor - Project Error Notification Monitor")
    print("=" * 80)
    print(f"Email: {QQ_EMAIL_USER}")
    print(f"Check interval: {CHECK_INTERVAL}s ({CHECK_INTERVAL//60} minutes)")
    print(f"Output log: {OUTPUT_FILE}")
    print("=" * 80)
    print()

    state = load_state()
    print(f"📊 Loaded state: {len(state.get('processed_ids', []))} processed emails")
    if state.get("last_check"):
        print(f"🕐 Last check: {state['last_check']}")
    print()

    while True:
        print(f"\n{'─'*80}")
        print(f"🔍 Checking emails at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")
        print(f"{'─'*80}")

        mail = connect_imap()
        if mail:
            try:
                check_new_emails(mail, state)
            finally:
                try:
                    mail.logout()
                except Exception:
                    pass
        else:
            print("⚠️  Will retry in next interval...")

        print(f"\n💤 Sleeping for {CHECK_INTERVAL}s...")
        try:
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            print("\n\n👋 Monitor stopped by user.")
            break


if __name__ == "__main__":
    main()
