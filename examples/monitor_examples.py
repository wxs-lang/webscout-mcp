"""Web monitoring and alerting examples.

Demonstrates how to use the web monitor for:
- Content change detection
- Keyword monitoring
- Price monitoring
- Multi-channel alerting (Webhook, Email, DingTalk, WeCom)
- Change history tracking
"""

from webscout_mcp.monitor import (
    ChangeRecord,
    DingTalkAlert,
    EmailAlert,
    MonitorConfig,
    WebhookAlert,
    WebMonitor,
    WeComAlert,
)


def example_basic_monitoring():
    """Example: Basic web page change monitoring."""
    print("=" * 60)
    print("Example: Basic Web Page Monitoring")
    print("=" * 60)

    # Initialize monitor
    config = MonitorConfig(
        check_interval=300,  # Check every 5 minutes
        monitor_text=True,  # Monitor text content changes
        min_change_size=10,  # Minimum 10 character change to trigger alert
        history_path="/tmp/webscout_monitor_history.json",
    )
    monitor = WebMonitor(config=config)

    # Check a URL for changes
    print("\nChecking https://example.com for changes...")
    changes = monitor.check_url("https://example.com")

    if changes:
        print(f"  Detected {len(changes)} changes:")
        for change in changes:
            print(f"    - Type: {change.change_type}")
            print(f"      Time: {change.timestamp}")
            if change.old_value:
                print(f"      Old: {change.old_value[:100]}...")
            if change.new_value:
                print(f"      New: {change.new_value[:100]}...")
    else:
        print("  No changes detected (first check establishes baseline).")

    # Get statistics
    stats = monitor.get_stats()
    print(f"\nMonitor Statistics:")
    print(f"  Monitored URLs: {stats['monitored_urls']}")
    print(f"  Total changes: {stats['total_changes']}")
    print(f"  Alert channels: {stats['alert_channels']}")
    print(f"  Check interval: {stats['check_interval']}s")


def example_keyword_monitoring():
    """Example: Monitor for keyword appearance/disappearance."""
    print("\n" + "=" * 60)
    print("Example: Keyword Monitoring")
    print("=" * 60)

    # Configure keyword monitoring
    config = MonitorConfig(
        check_interval=60,
        keywords_appear=["sale", "discount", "new"],  # Alert when these appear
        keywords_disappear=["out of stock", "sold out"],  # Alert when these disappear
        history_path="/tmp/webscout_monitor_history.json",
    )
    monitor = WebMonitor(config=config)

    print("\nConfigured keyword monitoring:")
    print(f"  Watch for appearance: {', '.join(config.keywords_appear)}")
    print(f"  Watch for disappearance: {', '.join(config.keywords_disappear)}")

    # Check for changes
    print("\nChecking for keyword changes...")
    changes = monitor.check_url("https://example.com")

    keyword_changes = [c for c in changes if c.change_type in ("keyword_appear", "keyword_disappear")]
    if keyword_changes:
        print(f"  Detected {len(keyword_changes)} keyword changes:")
        for change in keyword_changes:
            print(f"    - {change.change_type}: '{change.new_value or change.old_value}'")
    else:
        print("  No keyword changes detected.")


def example_webhook_alert():
    """Example: Send alerts via Webhook."""
    print("\n" + "=" * 60)
    print("Example: Webhook Alert")
    print("=" * 60)

    # Initialize monitor
    config = MonitorConfig(history_path="/tmp/webscout_monitor_history.json")
    monitor = WebMonitor(config=config)

    # Add webhook alert channel
    webhook_url = "https://hooks.example.com/your-webhook-url"
    monitor.add_alert_channel(WebhookAlert(webhook_url))

    print(f"\nAdded webhook alert channel: {webhook_url}")
    print("Alerts will be sent as JSON POST requests with:")
    print("  - title: Alert title")
    print("  - content: Alert content")
    print("  - url: Monitored URL")
    print("  - change_type: Type of change")
    print("  - timestamp: Detection time")

    # Check URL (alerts will be sent if changes detected)
    print("\nChecking URL (alerts will be sent if changes detected)...")
    changes = monitor.check_url("https://example.com")
    print(f"  Detected {len(changes)} changes.")


def example_email_alert():
    """Example: Send alerts via Email (SMTP)."""
    print("\n" + "=" * 60)
    print("Example: Email Alert (SMTP)")
    print("=" * 60)

    # Initialize monitor
    config = MonitorConfig(history_path="/tmp/webscout_monitor_history.json")
    monitor = WebMonitor(config=config)

    # Add email alert channel (Gmail example)
    email_alert = EmailAlert(
        smtp_server="smtp.gmail.com",
        smtp_port=587,
        username="your-email@gmail.com",
        password="your-app-password",  # Use app password, not account password
        from_addr="your-email@gmail.com",
        to_addrs=["recipient@example.com"],
        use_tls=True,
    )
    monitor.add_alert_channel(email_alert)

    print("\nAdded email alert channel:")
    print(f"  SMTP Server: smtp.gmail.com:587")
    print(f"  From: your-email@gmail.com")
    print(f"  To: recipient@example.com")
    print(f"  TLS: Enabled")

    print("\nNote: For Gmail, use an App Password:")
    print("  1. Go to Google Account > Security")
    print("  2. Enable 2-Step Verification")
    print("  3. Create an App Password")
    print("  4. Use that password here")

    # Other SMTP servers:
    print("\nOther SMTP servers:")
    print("  QQ Mail: smtp.qq.com:587")
    print("  Outlook: smtp.office365.com:587")
    print("  Yahoo: smtp.mail.yahoo.com:587")


def example_dingtalk_alert():
    """Example: Send alerts via DingTalk (钉钉) robot."""
    print("\n" + "=" * 60)
    print("Example: DingTalk (钉钉) Robot Alert")
    print("=" * 60)

    # Initialize monitor
    config = MonitorConfig(history_path="/tmp/webscout_monitor_history.json")
    monitor = WebMonitor(config=config)

    # Add DingTalk alert channel
    dingtalk_webhook = "https://oapi.dingtalk.com/robot/send?access_token=your-token"
    dingtalk_secret = "your-secret"  # Optional, for signed robots

    monitor.add_alert_channel(DingTalkAlert(dingtalk_webhook, secret=dingtalk_secret))

    print("\nAdded DingTalk robot alert channel:")
    print(f"  Webhook: {dingtalk_webhook}")
    print(f"  Secret: {'configured' if dingtalk_secret else 'not configured'}")

    print("\nHow to create a DingTalk robot:")
    print("  1. Open DingTalk group > Group Settings")
    print("  2. Click 'Smart Group Assistant'")
    print("  3. Click 'Add Robot' > 'Custom'")
    print("  4. Set robot name and security settings")
    print("  5. Copy the webhook URL and secret")


def example_wecom_alert():
    """Example: Send alerts via WeCom (企业微信) robot."""
    print("\n" + "=" * 60)
    print("Example: WeCom (企业微信) Robot Alert")
    print("=" * 60)

    # Initialize monitor
    config = MonitorConfig(history_path="/tmp/webscout_monitor_history.json")
    monitor = WebMonitor(config=config)

    # Add WeCom alert channel
    wecom_webhook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your-key"
    monitor.add_alert_channel(WeComAlert(wecom_webhook))

    print("\nAdded WeCom robot alert channel:")
    print(f"  Webhook: {wecom_webhook}")

    print("\nHow to create a WeCom robot:")
    print("  1. Open WeCom group > Group Settings")
    print("  2. Click 'Group Robot'")
    print("  3. Click 'Add Robot'")
    print("  4. Set robot name")
    print("  5. Copy the webhook URL")


def example_change_history():
    """Example: Track and view change history."""
    print("\n" + "=" * 60)
    print("Example: Change History Tracking")
    print("=" * 60)

    # Initialize monitor
    config = MonitorConfig(
        history_path="/tmp/webscout_monitor_history.json",
        max_history=100,  # Keep last 100 changes per URL
    )
    monitor = WebMonitor(config=config)

    # Check URL multiple times to build history
    url = "https://example.com"
    print(f"\nChecking {url} (3 times to build history)...")
    for i in range(3):
        changes = monitor.check_url(url)
        print(f"  Check {i+1}: {len(changes)} changes")

    # Get history
    history = monitor.get_history(url, limit=10)
    print(f"\nChange history for {url} (last {len(history)} changes):")
    for record in history:
        print(f"  [{record.timestamp}] {record.change_type}")
        if record.diff:
            print(f"    Diff: {record.diff[:100]}...")

    # Get all history
    all_history = monitor.get_all_history()
    print(f"\nTotal URLs with history: {len(all_history)}")
    for url, records in all_history.items():
        print(f"  {url}: {len(records)} changes")

    # Clear history for a specific URL
    print(f"\nClearing history for {url}...")
    monitor.clear_history(url)
    print("  History cleared!")


def example_multi_channel_alerting():
    """Example: Send alerts via multiple channels simultaneously."""
    print("\n" + "=" * 60)
    print("Example: Multi-Channel Alerting")
    print("=" * 60)

    # Initialize monitor
    config = MonitorConfig(history_path="/tmp/webscout_monitor_history.json")
    monitor = WebMonitor(config=config)

    # Add multiple alert channels
    monitor.add_alert_channel(WebhookAlert("https://hooks.example.com/webhook1"))
    monitor.add_alert_channel(WebhookAlert("https://hooks.example.com/webhook2"))
    # Email, DingTalk, WeCom can also be added

    print("\nAdded multiple alert channels:")
    print(f"  Total channels: {len(monitor._alert_channels)}")
    print("  Alerts will be sent to all channels simultaneously")
    print("  Failures in one channel won't affect others")

    # Check URL
    print("\nChecking URL (alerts sent to all channels if changes detected)...")
    changes = monitor.check_url("https://example.com")
    print(f"  Detected {len(changes)} changes.")


def run_all_examples():
    """Run all web monitoring examples."""
    print("\n" + "=" * 60)
    print("  Web Monitoring & Alerting Examples")
    print("=" * 60 + "\n")

    example_basic_monitoring()
    example_keyword_monitoring()
    example_webhook_alert()
    example_email_alert()
    example_dingtalk_alert()
    example_wecom_alert()
    example_change_history()
    example_multi_channel_alerting()

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_examples()
