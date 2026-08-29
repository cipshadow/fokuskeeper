#!/usr/bin/env python3
"""
Slack Gatekeeper - Prevents mindless Slack checking by requiring intentional purpose.
"""
import os
import time
import subprocess
import json
import fcntl
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
SLACK_APP_NAME = "Slack"
CHROME_APP_NAME = "Google Chrome"
GMAIL_PATTERN = "mail.google.com"
COOLDOWN_MINUTES = 3
QUIET_PERIOD_MINUTES = 60  # skip the prompt if this app hasn't been used in this long
LOG_FILE = Path.home() / "Library/Logs/slack-gatekeeper.log"
STATE_FILE = Path.home() / ".slack-gatekeeper-state.json"
HISTORY_FILE = Path.home() / ".slack-gatekeeper-history.json"



# ============================================================================
# Security Functions
# ============================================================================

def sanitize_for_applescript(text):
    """Escape special characters to prevent AppleScript injection."""
    if not isinstance(text, str):
        text = str(text)
    text = text.replace('\\', '\\\\')  # Escape backslashes first
    text = text.replace('"', '\\"')  # Escape double quotes
    text = text.replace('\x00', '')  # Remove null bytes
    return text

def validate_counter(value, max_value=1000):
    """Validate and clamp counter values."""
    try:
        value = int(value)
    except (ValueError, TypeError):
        return 0
    return max(0, min(value, max_value))

def log(message):
    """Append to log file with timestamp and secure permissions."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}\n"
    
    # Ensure directory exists
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Open with restricted permissions (user-only: 0o600)
    try:
        fd = os.open(LOG_FILE, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'a') as f:
            f.write(log_entry)
    except Exception as e:
        # Fallback to standard open if os.open fails
        with open(LOG_FILE, "a") as f:
            f.write(log_entry)

def load_state():
    """Load state (last allowed time, daily stats) from file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_state(state):
    """Save state to file with file locking."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    with open(STATE_FILE, "w") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # Exclusive lock
            json.dump(state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)  # Unlock
    
    # Set secure permissions (user-only)
    os.chmod(STATE_FILE, 0o600)

def get_today_date():
    """Get today's date as string (YYYY-MM-DD)."""
    return datetime.now().strftime("%Y-%m-%d")

def increment_daily_count(app_type="slack"):
    """Increment today's open count for specified app and return new count."""
    state = load_state()
    today = get_today_date()
    
    # Reset counts if it's a new day
    if state.get("stats_date") != today:
        state["stats_date"] = today
        state["slack_opens"] = 0
        state["gmail_opens"] = 0
        state["slack_prevented"] = 0
        state["gmail_prevented"] = 0
        state["distractions_prevented"] = 0
        # Keep old "daily_opens" for backwards compatibility
        state["daily_opens"] = 0
    
    # Increment specific app counter
    if app_type == "slack":
        state["slack_opens"] = state.get("slack_opens", 0) + 1
        count = state["slack_opens"]
    else:  # gmail
        state["gmail_opens"] = state.get("gmail_opens", 0) + 1
        count = state["gmail_opens"]
    
    # Update total for backwards compatibility
    state["daily_opens"] = state.get("slack_opens", 0) + state.get("gmail_opens", 0)
    
    save_state(state)
    
    # Save to history with specific type
    save_to_history(f"{app_type}_opened")
    
    return count

def increment_prevented_count(app_type="slack"):
    """Increment today's distractions prevented count for specified app and return new count."""
    state = load_state()
    today = get_today_date()

    # Reset counts if it's a new day
    if state.get("stats_date") != today:
        state["stats_date"] = today
        state["slack_opens"] = 0
        state["gmail_opens"] = 0
        state["slack_prevented"] = 0
        state["gmail_prevented"] = 0
        state["distractions_prevented"] = 0
        state["daily_opens"] = 0

    key = "slack_prevented" if app_type == "slack" else "gmail_prevented"
    state[key] = state.get(key, 0) + 1

    # Keep combined total for backwards compatibility
    state["distractions_prevented"] = state.get("slack_prevented", 0) + state.get("gmail_prevented", 0)
    save_state(state)

    # Save to history with specific type
    save_to_history(f"{app_type}_prevented")

    return state[key]

def save_to_history(event_type):
    """Save event to historical log file with file locking."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Use file locking to prevent race conditions
    with open(HISTORY_FILE, "a+") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # Exclusive lock
            
            # Read existing history
            f.seek(0)
            try:
                content = f.read()
                history = json.loads(content) if content else []
            except (json.JSONDecodeError, ValueError):
                history = []
            
            # Append new event
            history.append({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "time": datetime.now().strftime("%H:%M:%S"),
                "type": event_type  # "opened" or "prevented"
            })
            
            # Write back to file
            f.seek(0)
            f.truncate()
            json.dump(history, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)  # Unlock
    
    # Set secure permissions (user-only)
    os.chmod(HISTORY_FILE, 0o600)

def get_daily_count(app_type="slack"):
    """Get today's open count for specified app."""
    state = load_state()
    today = get_today_date()
    
    if state.get("stats_date") == today:
        if app_type == "slack":
            return state.get("slack_opens", 0)
        elif app_type == "gmail":
            return state.get("gmail_opens", 0)
        else:  # total
            return state.get("daily_opens", 0)
    return 0

def get_prevented_count(app_type="slack"):
    """Get today's distractions prevented count for specified app."""
    state = load_state()
    today = get_today_date()

    if state.get("stats_date") == today:
        key = "slack_prevented" if app_type == "slack" else "gmail_prevented"
        return state.get(key, 0)
    return 0

# Cooldown and quiet period are two different clocks and must not share a key.
#
#   {app}_granted_at  — when access was last *granted*. Fixed at the moment of the
#                       grant and never touched again, so the cooldown expires a
#                       set time after the prompt.
#   {app}_last_seen   — when the app was last focused. Refreshed on every glance,
#                       so the quiet period measures genuine idleness.
#
# Until 2026-08-20 both were the single key `{app}_last_active_time`, and the
# monitor loop refreshed it on every allowed focus. That made the cooldown a
# *sliding* window: touching Slack once every COOLDOWN_MINUTES kept it alive
# forever and it never re-prompted. Diagnosed 2026-08-11, see SESSION_LOG.
#
# Legacy state is migrated on read, so an existing ~/.slack-gatekeeper-state.json
# keeps working.
LEGACY_ACTIVE_KEY = "_last_active_time"

def _read_clock(state, app_type, name):
    """Read a clock, falling back to the legacy shared key."""
    value = state.get(f"{app_type}_{name}")
    if value is None:
        value = state.get(f"{app_type}{LEGACY_ACTIVE_KEY}")
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        # Corrupt timestamp — treat as absent rather than crashing the daemon.
        return None

def update_last_seen(app_type="slack"):
    """Record that the app was just focused. Does NOT extend the cooldown."""
    state = load_state()
    state[f"{app_type}_last_seen"] = datetime.now().isoformat()
    save_state(state)

def is_in_cooldown(app_type="slack"):
    """True while we're still inside the grant window from the last prompt."""
    granted_at = _read_clock(load_state(), app_type, "granted_at")
    if granted_at is None:
        return False
    return datetime.now() - granted_at < timedelta(minutes=COOLDOWN_MINUTES)

def is_quiet_period(app_type="slack"):
    """True if this app hasn't been touched in over QUIET_PERIOD_MINUTES."""
    last_seen = _read_clock(load_state(), app_type, "last_seen")
    if last_seen is None:
        return True
    return datetime.now() - last_seen >= timedelta(minutes=QUIET_PERIOD_MINUTES)

def is_slack_running():
    """Check if Slack is currently running."""
    result = subprocess.run(
        ["pgrep", "-x", "Slack"],
        capture_output=True,
        text=True
    )
    return result.returncode == 0

def get_frontmost_app():
    """Get the name of the currently active/frontmost application."""
    script = 'tell application "System Events" to return name of first application process whose frontmost is true'
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None

def quit_slack():
    """Quit Slack application."""
    subprocess.run(
        ["osascript", "-e", f'quit app "{SLACK_APP_NAME}"'],
        capture_output=True
    )
    log("Quit Slack")

def get_chrome_active_tab_url():
    """Get the URL of the active tab in Chrome."""
    script = '''
    tell application "Google Chrome"
        if it is running then
            try
                get URL of active tab of front window
            on error
                return ""
            end try
        else
            return ""
        end if
    end tell
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return ""

def is_gmail_url(url):
    """Check if URL is Gmail."""
    return GMAIL_PATTERN in url

def get_chrome_front_tab_ref():
    """Identify the front Chrome window and its active tab by ID.

    Targeting the exact (window, tab) pair is what keeps a restored Gmail tab in
    the Chrome profile it came from — "active tab of front window" can drift to
    another profile's window between detection and restore.
    """
    script = '''
    tell application "Google Chrome"
        if it is running then
            try
                set w to front window
                return (id of w as string) & "|" & (id of active tab of w as string)
            on error
                return ""
            end try
        else
            return ""
        end if
    end tell
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return (None, None)
    parts = result.stdout.strip().split("|")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return (None, None)
    return (int(parts[0]), int(parts[1]))


def _tell_tab(window_id, tab_id, body):
    """Run an AppleScript body against a specific tab, returning True on success.

    IDs are matched as strings: AppleScript coerces 9-digit ids to single-precision
    reals in `whose id is N` comparisons, which can match a neighbouring tab.
    """
    script = f'''
    tell application "Google Chrome"
        try
            set targetWindow to missing value
            repeat with w in windows
                if (id of w as string) is "{window_id}" then
                    set targetWindow to w
                    exit repeat
                end if
            end repeat
            if targetWindow is missing value then error "window {window_id} not found"

            set targetTab to missing value
            repeat with t in tabs of targetWindow
                if (id of t as string) is "{tab_id}" then
                    set targetTab to t
                    exit repeat
                end if
            end repeat
            if targetTab is missing value then error "tab {tab_id} not found"

            {body}
            return "ok"
        on error errMsg
            return "err: " & errMsg
        end try
    end tell
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True
    )
    output = result.stdout.strip()
    if output == "ok":
        return True
    log(f"Chrome tab operation failed (window {window_id}, tab {tab_id}): {output}")
    return False


def park_gmail_tab(window_id, tab_id):
    """Blank out the Gmail tab without closing it, so its window/profile survives."""
    if window_id is None or tab_id is None:
        log("Could not identify the Gmail tab - leaving it alone")
        return False
    if _tell_tab(window_id, tab_id, 'set URL of targetTab to "about:blank"'):
        log("Parked Gmail tab at about:blank")
        return True
    return False


def restore_gmail_tab(window_id, tab_id, original_url):
    """Restore the parked tab to the exact URL it was on, preserving the u/N account."""
    safe_url = sanitize_for_applescript(original_url)
    if _tell_tab(window_id, tab_id, f'set URL of targetTab to "{safe_url}"'):
        log(f"Restored Gmail tab in original window/profile: {original_url}")
        return True
    log("Could not restore the original Gmail tab - not opening Gmail elsewhere")
    return False


def discard_parked_tab(window_id, tab_id):
    """Close the parked tab after access is denied."""
    if _tell_tab(window_id, tab_id, "close targetTab"):
        log("Closed parked Gmail tab")

def show_confirmation_dialog(slack_count, gmail_count, slack_prevented, gmail_prevented, app_name="Slack"):
    """Show enhanced confirmation dialog with stats. Returns True if user has a reason to open app."""

    # Validate counters to prevent overflow/display issues
    slack_count = validate_counter(slack_count)
    gmail_count = validate_counter(gmail_count)
    slack_prevented = validate_counter(slack_prevented)
    gmail_prevented = validate_counter(gmail_prevented)
    prevented_count = slack_prevented + gmail_prevented

    # Calculate success rate
    total_opens = slack_count + gmail_count
    total_attempts = total_opens + prevented_count
    success_rate = (prevented_count / total_attempts * 100) if total_attempts > 0 else 0

    # Calculate time rescued (10 minutes per blocked distraction)
    minutes_rescued = prevented_count * 10
    hours_rescued = minutes_rescued // 60
    remaining_minutes = minutes_rescued % 60
    
    if hours_rescued > 0:
        time_rescued = f"{hours_rescued}h {remaining_minutes}m"
    else:
        time_rescued = f"{remaining_minutes}m"
    
    # Create motivational message based on success rate
    if success_rate >= 70:
        motivation = "Your focus is outstanding today! 🎯"
    elif success_rate >= 50:
        motivation = "You're building great focus habits! 💪"
    elif success_rate >= 30:
        motivation = "Keep pushing - you're making progress! ✨"
    else:
        motivation = "This is your chance to strengthen focus! 🌟"
    
    # Build the enhanced dialog with better visual hierarchy
    message = (
        f"Taking a distraction break?\\n\\n"
        f"━━━━━━━━━━━━━━━━━━━━\\n\\n"
        f"Today's Focus Metrics\\n\\n"
        f"  📊  Slack Opens        {slack_count}\\n"
        f"  📧  Gmail Opens        {gmail_count}\\n"
        f"  🚫  Slack Blocked      {slack_prevented}\\n"
        f"  🚫  Gmail Blocked      {gmail_prevented}\\n"
        f"  ⏰  Time Rescued       {time_rescued}\\n\\n"
        f"━━━━━━━━━━━━━━━━━━━━\\n\\n"
        f"{motivation}\\n\\n"
        f"Are you sure you need to check {sanitize_for_applescript(app_name)} right now?"
    )
    
    # Simple two-button dialog
    script = f'''
    set dialogResult to display dialog "{message}" buttons {{"Stay focused", "🔴 I have a reason"}} default button "Stay focused" with icon caution with title "🚪 Focus Gatekeeper"
    set clickedButton to button returned of dialogResult
    return clickedButton
    '''
    
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        button_clicked = result.stdout.strip()
        
        # Check which button was clicked
        if "reason" in button_clicked.lower():
            log(f"User has a reason - allowing {app_name} access")
            return True
        else:
            log("User chose to stay focused")
            return False
    else:
        # User clicked X button (close), pressed ESC, or cancelled dialog
        # Treat this the same as "Stay focused" - block the distraction
        log("User closed dialog (X button/ESC) - staying focused")
        return False

def allow_access(app_type="slack"):
    """Grant access: start the cooldown clock. This is the ONLY thing that does."""
    state = load_state()
    now = datetime.now().isoformat()
    state[f"{app_type}_granted_at"] = now
    state[f"{app_type}_last_seen"] = now
    save_state(state)
    log(f"Access allowed - {app_type} cooldown started ({COOLDOWN_MINUTES} min)")

def monitor_slack():
    """Main monitoring loop for Slack and Gmail."""
    log("Distraction Gatekeeper started (Slack + Gmail)")
    
    # Display helpful startup information
    print("=" * 70)
    print("🚪 FOCUS GATEKEEPER - Distraction Blocker")
    print("=" * 70)
    print()
    print("📋 HOW IT WORKS:")
    print("  • Detects when you try to open Slack or Gmail")
    print("  • Shows a dialog making you consciously decide if you need it")
    print("  • Tracks your daily stats and distractions blocked")
    print()
    print(f"⏰ COOLDOWN PERIOD: {COOLDOWN_MINUTES} minutes")
    print(f"  After clicking 'I have a reason', you get {COOLDOWN_MINUTES} minutes of")
    print("  uninterrupted access. Timer starts when you STOP using the app.")
    print()
    print(f"🤫 QUIET PERIOD: {QUIET_PERIOD_MINUTES} minutes")
    print(f"  If an app hasn't been used in {QUIET_PERIOD_MINUTES}+ minutes, the next")
    print("  open is let through without a prompt (checked per app).")
    print()
    print("💾 TIME RESCUED CALCULATION:")
    print("  Each blocked distraction saves ~10 minutes of focus time")
    print("  (average time spent checking + context switching cost)")
    print()
    print("⚙️  CUSTOMIZE COOLDOWN:")
    print(f"  Edit COOLDOWN_MINUTES in: {__file__}")
    print(f"  Current value: {COOLDOWN_MINUTES} minutes")
    print()
    print("=" * 70)
    print(f"📊 Today's Stats: Slack opens: {get_daily_count('slack')}, Gmail opens: {get_daily_count('gmail')}, Slack blocked: {get_prevented_count('slack')}, Gmail blocked: {get_prevented_count('gmail')}")
    print("=" * 70)
    print()
    print("Running... (Press Ctrl+C to stop)")
    print()
    
    last_frontmost_app = None
    last_gmail_check = False
    
    try:
        while True:
            current_frontmost = get_frontmost_app()
            
            # Check 1: Slack app focus
            if current_frontmost == SLACK_APP_NAME and last_frontmost_app != SLACK_APP_NAME:
                log("Slack activated/focused")
                
                if is_in_cooldown("slack"):
                    log("Within Slack cooldown period - allowing")
                    update_last_seen("slack")  # glance only — must not extend the cooldown
                elif get_daily_count("slack") == 0:
                    # First Slack open of the day - let it through without prompting
                    new_count = increment_daily_count("slack")
                    allow_access("slack")
                    log(f"First Slack open of the day - auto-allowed (#{new_count})")
                    print(f"First Slack open today - allowed automatically")
                    time.sleep(0.5)
                    last_frontmost_app = SLACK_APP_NAME
                    continue
                elif is_quiet_period("slack"):
                    # No Slack activity in QUIET_PERIOD_MINUTES - let it through without prompting
                    new_count = increment_daily_count("slack")
                    allow_access("slack")
                    log(f"No Slack use in {QUIET_PERIOD_MINUTES}+ min - auto-allowed (#{new_count})")
                    print(f"Quiet period - Slack allowed automatically")
                    time.sleep(0.5)
                    last_frontmost_app = SLACK_APP_NAME
                    continue
                else:
                    # Not in cooldown - intercept!
                    quit_slack()
                    time.sleep(0.3)

                    # Show current counts
                    slack_count = get_daily_count("slack")
                    gmail_count = get_daily_count("gmail")
                    slack_prevented = get_prevented_count("slack")
                    gmail_prevented = get_prevented_count("gmail")

                    allowed = show_confirmation_dialog(slack_count, gmail_count, slack_prevented, gmail_prevented, "Slack")

                    if allowed:
                        new_count = increment_daily_count("slack")
                        allow_access("slack")

                        subprocess.run(["open", "-a", SLACK_APP_NAME])
                        log(f"Re-launched Slack (#{new_count} today)")
                        print(f"Slack opened - Total today: {new_count}")

                        time.sleep(0.5)
                        last_frontmost_app = SLACK_APP_NAME
                    else:
                        prevented_count = increment_prevented_count("slack")
                        log(f"Slack access denied - distraction prevented (#{prevented_count} today)")
                        print(f"Access denied - good job staying focused! ({prevented_count} distractions prevented)")
                        last_frontmost_app = None
                        continue
            
            # Track continued Slack usage (update activity time while using)
            if current_frontmost == SLACK_APP_NAME and is_in_cooldown("slack"):
                update_last_seen("slack")
            
            # Check 2: Gmail in Chrome
            if current_frontmost == CHROME_APP_NAME:
                chrome_url = get_chrome_active_tab_url()
                is_gmail_now = is_gmail_url(chrome_url)
                
                # Detect transition to Gmail tab
                if is_gmail_now and not last_gmail_check:
                    log(f"Gmail tab activated: {chrome_url}")
                    
                    if is_in_cooldown("gmail"):
                        log("Within Gmail cooldown period - allowing Gmail")
                        update_last_seen("gmail")  # glance only — must not extend the cooldown
                    elif get_daily_count("gmail") == 0:
                        # First Gmail open of the day - let it through without prompting
                        new_count = increment_daily_count("gmail")
                        allow_access("gmail")
                        log(f"First Gmail open of the day - auto-allowed (#{new_count})")
                        print(f"First Gmail open today - allowed automatically")
                    elif is_quiet_period("gmail"):
                        # No Gmail activity in QUIET_PERIOD_MINUTES - let it through without prompting
                        new_count = increment_daily_count("gmail")
                        allow_access("gmail")
                        log(f"No Gmail use in {QUIET_PERIOD_MINUTES}+ min - auto-allowed (#{new_count})")
                        print(f"Quiet period - Gmail allowed automatically")
                    else:
                        # Pin the exact tab so it can be restored into its own profile
                        original_window_id, original_tab_id = get_chrome_front_tab_ref()
                        original_url = chrome_url

                        # Not in cooldown - intercept!
                        park_gmail_tab(original_window_id, original_tab_id)
                        time.sleep(0.3)

                        # Show current counts
                        slack_count = get_daily_count("slack")
                        gmail_count = get_daily_count("gmail")
                        slack_prevented = get_prevented_count("slack")
                        gmail_prevented = get_prevented_count("gmail")

                        allowed = show_confirmation_dialog(slack_count, gmail_count, slack_prevented, gmail_prevented, "Gmail")

                        if allowed:
                            new_count = increment_daily_count("gmail")
                            allow_access("gmail")  # Separate Gmail cooldown

                            # Restore the original tab in the SAME window/profile/account
                            restore_gmail_tab(original_window_id, original_tab_id, original_url)
                            log(f"Re-opened Gmail (#{new_count} today)")
                            print(f"Gmail opened - Total today: {new_count}")

                            time.sleep(0.5)
                        else:
                            discard_parked_tab(original_window_id, original_tab_id)
                            prevented_count = increment_prevented_count("gmail")
                            log(f"Gmail access denied - distraction prevented (#{prevented_count} today)")
                            print(f"Access denied - good job staying focused! ({prevented_count} distractions prevented)")
                
                # Track continued Gmail usage (update activity time while using)
                if is_gmail_now and is_in_cooldown("gmail"):
                    update_last_seen("gmail")
                
                last_gmail_check = is_gmail_now
            else:
                last_gmail_check = False
            
            last_frontmost_app = current_frontmost
            time.sleep(0.5)  # Check twice per second
            
    except KeyboardInterrupt:
        log("Distraction Gatekeeper stopped")
        print(f"\nStopped. Slack: {get_daily_count('slack')}, Gmail: {get_daily_count('gmail')}")

if __name__ == "__main__":
    # Ensure log directory exists
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    monitor_slack()

