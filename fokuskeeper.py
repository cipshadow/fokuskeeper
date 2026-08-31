#!/usr/bin/env python3
"""
FokusKeeper - Prevents mindless distraction checking by requiring intentional purpose.
"""
import argparse
import os
import shutil
import time
import subprocess
import json
import fcntl
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

# Configuration
# pgrep/pkill pattern for the daemon process. Deliberately `python.*` + script
# name so an editor session with the file open never matches.
DAEMON_PROCESS_PATTERN = "python.*fokuskeeper.py"
# Timeouts so a hung osascript (e.g. a pending TCC prompt) can't freeze the
# single-threaded monitor loop forever. Dialogs legitimately wait on a human,
# so they get a much longer budget.
SUBPROCESS_TIMEOUT_SECONDS = 10
DIALOG_TIMEOUT_SECONDS = 600
COOLDOWN_MINUTES = 3
QUIET_PERIOD_MINUTES = 60  # skip the prompt if this app hasn't been used in this long
LOG_FILE = Path.home() / "Library/Logs/fokuskeeper.log"
STATE_FILE = Path.home() / ".fokuskeeper-state.json"
HISTORY_FILE = Path.home() / ".fokuskeeper-history.json"
CONFIG_FILE = Path.home() / ".fokuskeeper-config.json"  # {"enabled": [target keys]}

# Pre-rename paths. Kept so migrate_legacy_files() can copy an existing
# installation's data across; the legacy files stay in place as rollback.
LEGACY_STATE_FILE = Path.home() / ".slack-gatekeeper-state.json"
LEGACY_HISTORY_FILE = Path.home() / ".slack-gatekeeper-history.json"

# Intercept targets. A target can expose an app surface (macOS frontmost-process
# name), a web surface (Chrome tab hostnames), or both. Keys "slack" and "gmail"
# must keep these exact spellings: state-file counters/clocks are keyed on them.

@dataclass(frozen=True)
class Target:
    key: str
    label: str
    app_name: str = None      # macOS frontmost-process name; None = web-only
    url_domains: tuple = ()   # hostname suffix matches, Chrome only

TARGETS = (
    Target("slack", "Slack", "Slack", ("app.slack.com",)),
    Target("gmail", "Gmail", None, ("mail.google.com",)),
    Target("whatsapp", "WhatsApp", "WhatsApp", ("web.whatsapp.com",)),
    Target("instagram", "Instagram", None, ("instagram.com",)),
    Target("facebook", "Facebook", None, ("facebook.com",)),
    Target("reddit", "Reddit", None, ("reddit.com",)),
    Target("youtube", "YouTube", None, ("youtube.com",)),
    Target("x", "X", None, ("x.com", "twitter.com")),
    Target("tiktok", "TikTok", None, ("tiktok.com",)),
    Target("linkedin", "LinkedIn", None, ("linkedin.com",)),
)

TARGETS_BY_KEY = {t.key: t for t in TARGETS}
TARGET_KEYS = tuple(t.key for t in TARGETS)
TARGET_LABELS = {t.key: t.label for t in TARGETS}


@dataclass(frozen=True)
class Browser:
    key: str
    app_name: str
    current_tab_phrase: str  # AppleScript wording for "the tab you're looking at"
    # Chrome exposes a numeric id on both windows and tabs, so a restore can
    # target the exact tab even if others moved or closed meanwhile. Safari's
    # AppleScript dictionary has no tab id at all (verified live -- `id of
    # current tab` raises -1728) -- only `index`, which drifts the same way.
    # For a browser without one, we track only the window id and always
    # operate on "current tab of window W" (verified as a stable, working
    # handle). Narrower race than Chrome's: if the user switches tabs within
    # that same window during the ~1s the dialog takes to appear, the
    # restore lands on whatever tab is current then -- not necessarily the
    # one that was flagged. Accepted limitation, not present for Chrome.
    has_tab_ids: bool

BROWSERS = (
    Browser("chrome", "Google Chrome", "active tab", has_tab_ids=True),
    Browser("safari", "Safari", "current tab", has_tab_ids=False),
)
BROWSERS_BY_APP_NAME = {b.app_name: b for b in BROWSERS}


# Config cache for load_enabled_targets(). The daemon calls the seam every
# 0.5s tick, so we stat CONFIG_FILE (cheap) and only re-parse when the mtime
# changes — which also picks up `fokuskeeper setup` edits from another process
# without a restart. Keyed on (path, mtime_ns) so tests patching CONFIG_FILE
# never see a stale entry.
_config_cache = {"path": None, "mtime_ns": None, "targets": TARGETS}


def _parse_enabled_config(path):
    """Parse CONFIG_FILE into a tuple of enabled Targets, in TARGETS order.

    Expected shape: {"enabled": ["slack", "gmail", ...]}. Unknown keys are
    silently ignored. Any deviation — unreadable file, corrupt JSON, wrong
    shape, empty/missing "enabled" list, or nothing left after filtering —
    falls back to ALL targets (all-enabled is the default). Never raises.
    """
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, ValueError, OSError):
        return TARGETS
    if not isinstance(data, dict):
        return TARGETS
    enabled = data.get("enabled")
    if not isinstance(enabled, list) or not enabled:
        return TARGETS
    keys = {k for k in enabled if isinstance(k, str)}
    targets = tuple(t for t in TARGETS if t.key in keys)
    return targets or TARGETS


def load_enabled_targets():
    """Read the enabled-target set from CONFIG_FILE, mtime-cached."""
    global _config_cache
    path = CONFIG_FILE
    try:
        mtime_ns = os.stat(path).st_mtime_ns
    except OSError:
        # File absent (or unstatable): all-enabled default.
        return TARGETS
    cache = _config_cache
    if cache["path"] == path and cache["mtime_ns"] == mtime_ns:
        return cache["targets"]
    targets = _parse_enabled_config(path)
    _config_cache = {"path": path, "mtime_ns": mtime_ns, "targets": targets}
    return targets


def enabled_targets():
    """The targets the daemon currently intercepts.

    The seam all app/URL matching consults — never TARGETS directly. Backed
    by CONFIG_FILE via load_enabled_targets(); stats/history/report keep
    iterating ALL targets so disabled ones still show historical counts.
    """
    return load_enabled_targets()


def match_app_name(app_name, targets=None):
    """Return the enabled target whose app_name exactly equals app_name, or None."""
    if not app_name:
        return None
    for target in enabled_targets() if targets is None else targets:
        if target.app_name is not None and app_name == target.app_name:
            return target
    return None


def match_url(url, targets=None):
    """Return the enabled target whose url_domains match the URL's hostname.

    Hostname-suffix semantics: "reddit.com" matches reddit.com and
    old.reddit.com, but never notreddit.com — and slack.com does NOT match
    the app.slack.com target.
    """
    if not url:
        return None
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower()
    for target in enabled_targets() if targets is None else targets:
        for domain in target.url_domains:
            if host == domain or host.endswith("." + domain):
                return target
    return None


def _hostname_for_log(url):
    """Hostname only, for log lines — never the full URL (path/query can carry
    search terms or message content). Restoring the tab still uses the real
    original_url; this is a logging-only redaction.
    """
    try:
        return urlparse(url).hostname or url
    except ValueError:
        return url


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

def _run(cmd, timeout=SUBPROCESS_TIMEOUT_SECONDS):
    """subprocess.run with capture_output/text and a timeout.

    On timeout, logs and returns a CompletedProcess with returncode 1 and
    empty output, so every call site falls into its existing non-zero
    returncode failure path (None / "" / (None, None) / False / cancel).
    """
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log(f"Command timed out after {timeout}s: {' '.join(cmd[:2])}")
        return subprocess.CompletedProcess(
            cmd, returncode=1, stdout="", stderr=f"timed out after {timeout}s"
        )

def migrate_legacy_files():
    """Copy pre-rename state/history files to the new paths, once.

    Copies (never moves) so the legacy files remain as rollback. No-op when the
    new file already exists or the legacy file is absent.
    """
    pairs = (
        (STATE_FILE, LEGACY_STATE_FILE),
        (HISTORY_FILE, LEGACY_HISTORY_FILE),
    )
    for new_file, legacy_file in pairs:
        if new_file.exists() or not legacy_file.exists():
            continue
        new_file.parent.mkdir(parents=True, exist_ok=True)
        # Create the destination 0o600 BEFORE writing content, so the data
        # is never world-readable even briefly (copyfile+chmod would be).
        fd = os.open(new_file, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as dst, open(legacy_file, "rb") as src:
            shutil.copyfileobj(src, dst)
        log(f"Migrated legacy file {legacy_file} -> {new_file}")

def load_state():
    """Load state (last allowed time, daily stats) from file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError):
            try:
                log(f"State file unreadable/corrupt - treating as empty: {STATE_FILE}")
            except Exception:
                pass  # a logging failure must not crash state loading
            return {}
    return {}

def _write_json_file(path, data, lock=False):
    """Atomically write JSON with user-only permissions from creation.

    Writes to a same-directory temp file created 0o600, fsyncs, then
    os.replace()s it over path — readers never see a partial or
    world-readable file. The lock parameter is kept for signature
    stability; the atomic replace makes an flock unnecessary.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

def save_state(state):
    """Save state to file with file locking."""
    _write_json_file(STATE_FILE, state, lock=True)

def get_today_date():
    """Get today's date as string (YYYY-MM-DD)."""
    return datetime.now().strftime("%Y-%m-%d")

def _reset_daily_counters(state):
    """Zero every target's counters (and the legacy totals) for a fresh day."""
    state["stats_date"] = get_today_date()
    for key in TARGET_KEYS:
        state[f"{key}_opens"] = 0
        state[f"{key}_prevented"] = 0
    # Legacy combined totals, kept for backwards compatibility
    state["daily_opens"] = 0
    state["distractions_prevented"] = 0

def increment_daily_count(app_type="slack"):
    """Increment today's open count for specified app and return new count."""
    state = load_state()

    # Reset counts if it's a new day
    if state.get("stats_date") != get_today_date():
        _reset_daily_counters(state)

    state[f"{app_type}_opens"] = state.get(f"{app_type}_opens", 0) + 1
    count = state[f"{app_type}_opens"]

    # Update total for backwards compatibility
    state["daily_opens"] = sum(state.get(f"{key}_opens", 0) for key in TARGET_KEYS)

    save_state(state)

    # Save to history with specific type
    save_to_history(f"{app_type}_opened")

    return count

def increment_prevented_count(app_type="slack"):
    """Increment today's distractions prevented count for specified app and return new count."""
    state = load_state()

    # Reset counts if it's a new day
    if state.get("stats_date") != get_today_date():
        _reset_daily_counters(state)

    state[f"{app_type}_prevented"] = state.get(f"{app_type}_prevented", 0) + 1

    # Keep combined total for backwards compatibility
    state["distractions_prevented"] = sum(
        state.get(f"{key}_prevented", 0) for key in TARGET_KEYS
    )
    save_state(state)

    # Save to history with specific type
    save_to_history(f"{app_type}_prevented")

    return state[f"{app_type}_prevented"]

def save_to_history(event_type):
    """Save event to historical log file with file locking."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Create 0o600 from the start so the file is never world-readable, then
    # use file locking to prevent race conditions ("a+" semantics as before).
    fd = os.open(HISTORY_FILE, os.O_CREAT | os.O_RDWR | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a+") as f:
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
        if app_type in TARGETS_BY_KEY:
            return state.get(f"{app_type}_opens", 0)
        return state.get("daily_opens", 0)  # total
    return 0

def get_prevented_count(app_type="slack"):
    """Get today's distractions prevented count for specified app.

    Delegates to _today_counters (defined later; resolved at call time) so
    the legacy slack-only distractions_prevented fallback applies here too.
    """
    counters = _today_counters(load_state())
    return counters.get(app_type, (0, 0))[1]

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

# The quiet-period threshold is minutes-scale, so last_seen only needs coarse
# freshness — refreshing at most every LAST_SEEN_REFRESH_SECONDS avoids an
# fsync'd state write on every 0.5s poll tick during continued use.
LAST_SEEN_REFRESH_SECONDS = 15

def refresh_last_seen(app_type):
    """Refresh last_seen during continued use, but only when it has gone stale.

    Runs regardless of cooldown state: continuous use past the cooldown must
    still count as activity, or a long session would read as a quiet period
    and the next open would auto-allow.
    """
    state = load_state()
    now = datetime.now()
    last_seen = _read_clock(state, app_type, "last_seen")
    if last_seen is not None and (now - last_seen).total_seconds() < LAST_SEEN_REFRESH_SECONDS:
        return
    state[f"{app_type}_last_seen"] = now.isoformat()
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

def is_app_running(app_name):
    """Check if an app's process is currently running (exact process name)."""
    result = _run(["pgrep", "-x", app_name])
    return result.returncode == 0

def get_frontmost_app():
    """Get the name of the currently active/frontmost application."""
    script = 'tell application "System Events" to return name of first application process whose frontmost is true'
    result = _run(["osascript", "-e", script])
    if result.returncode == 0:
        return result.stdout.strip()
    _warn_access_once(
        "frontmost",
        "Cannot read the frontmost app - app-surface gating (Slack, WhatsApp) is "
        "inactive. Grant Automation permission for System Events to the app that "
        f"starts FokusKeeper ({result.stderr.strip() or 'unknown osascript error'}).",
    )
    return None

def quit_app(app_name):
    """Quit a macOS application by name. Only logs success when it actually happened."""
    result = _run(["osascript", "-e", f'quit app "{sanitize_for_applescript(app_name)}"'])
    if result.returncode == 0:
        log(f"Quit {app_name}")
        return True
    _warn_access_once(
        f"quit:{app_name}",
        f"Cannot quit {app_name} - it will keep running after a denied distraction. "
        f"Grant Automation permission for {app_name} to the app that starts FokusKeeper "
        f"({result.stderr.strip() or 'unknown osascript error'}).",
    )
    return False

def get_browser_active_tab_url(browser):
    """Get the URL of the active tab in the given browser."""
    script = f'''
    tell application "{browser.app_name}"
        if it is running then
            try
                get URL of {browser.current_tab_phrase} of front window
            on error
                return ""
            end try
        else
            return ""
        end if
    end tell
    '''
    result = _run(["osascript", "-e", script])
    if result.returncode == 0:
        return result.stdout.strip()
    _warn_access_once(
        f"{browser.key}_tabs",
        f"Cannot read {browser.app_name} tabs - web gating for it is inactive. "
        f"Grant Automation permission for {browser.app_name} to the app that "
        f"starts FokusKeeper ({result.stderr.strip() or 'unknown osascript error'}).",
    )
    return ""

_access_warned = set()

def _warn_access_once(key, message):
    """Log the first automation failure for a given key, once per process lifetime.

    The classic cause is a missing per-app Automation grant (TCC error -1743)
    for whatever process launched the daemon. Without this, an affected
    surface (frontmost-app detection, Chrome tab reading, quitting an app)
    just silently stops working — this is what makes that diagnosable.
    Keyed so independent grants (e.g. System Events vs. a specific app) each
    get their own one-time warning instead of one hiding the rest.
    """
    if key in _access_warned:
        return
    _access_warned.add(key)
    log(f"WARNING: {message} Check the Permissions section of the README.")

def get_browser_front_tab_ref(browser):
    """Identify the front window (and, for browsers that support it, the
    exact tab within it) so a restore lands back in the same place.

    Returns (window_id, tab_id). tab_id is None for a browser without a
    stable per-tab id (Safari — see Browser.has_tab_ids); callers then
    always target "current tab of window W" instead of a specific tab.

    This is the ONLY place tab/window ids may come from: it validates every
    id as digits, which is what makes interpolating them into _tell_tab safe.
    """
    if browser.has_tab_ids:
        script = f'''
        tell application "{browser.app_name}"
            if it is running then
                try
                    set w to front window
                    return (id of w as string) & "|" & (id of {browser.current_tab_phrase} of w as string)
                on error
                    return ""
                end try
            else
                return ""
            end if
        end tell
        '''
        result = _run(["osascript", "-e", script])
        if result.returncode != 0:
            return (None, None)
        parts = result.stdout.strip().split("|")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            return (None, None)
        return (int(parts[0]), int(parts[1]))

    script = f'''
    tell application "{browser.app_name}"
        if it is running then
            try
                return id of front window as string
            on error
                return ""
            end try
        else
            return ""
        end if
    end tell
    '''
    result = _run(["osascript", "-e", script])
    if result.returncode != 0 or not result.stdout.strip().isdigit():
        return (None, None)
    return (int(result.stdout.strip()), None)


def _tell_tab(browser, window_id, tab_id, body):
    """Run an AppleScript body against a specific tab, returning True on success.

    When tab_id is set, ids are matched as strings: AppleScript coerces
    9-digit ids to single-precision reals in `whose id is N` comparisons,
    which can match a neighbouring tab. When tab_id is None (a browser
    without tab ids), targets "current tab of window W" instead — see
    Browser.has_tab_ids for the narrower race this accepts.
    """
    if tab_id is not None:
        script = f'''
        tell application "{browser.app_name}"
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
    else:
        script = f'''
        tell application "{browser.app_name}"
            try
                if not (exists window id {window_id}) then error "window {window_id} not found"
                tell window id {window_id}
                    set targetTab to current tab
                end tell

                {body}
                return "ok"
            on error errMsg
                return "err: " & errMsg
            end try
        end tell
        '''
    result = _run(["osascript", "-e", script])
    output = result.stdout.strip()
    if output == "ok":
        return True
    log(f"{browser.app_name} tab operation failed (window {window_id}, tab {tab_id}): {output}")
    return False


def park_tab(browser, window_id, tab_id, label):
    """Blank out the tab without closing it, so its window/profile survives."""
    if window_id is None:
        log(f"Could not identify the {label} tab - leaving it alone")
        return False
    if _tell_tab(browser, window_id, tab_id, 'set URL of targetTab to "about:blank"'):
        log(f"Parked {label} tab at about:blank")
        return True
    return False


def restore_tab(browser, window_id, tab_id, original_url, label):
    """Restore the parked tab to the exact URL it was on (same window/profile)."""
    safe_url = sanitize_for_applescript(original_url)
    if _tell_tab(browser, window_id, tab_id, f'set URL of targetTab to "{safe_url}"'):
        log(f"Restored {label} tab in original window/profile: {_hostname_for_log(original_url)}")
        return True
    log(f"Could not restore the original {label} tab - not opening {label} elsewhere")
    return False


def discard_parked_tab(browser, window_id, tab_id, label):
    """Close the parked tab after access is denied."""
    if _tell_tab(browser, window_id, tab_id, "close targetTab"):
        log(f"Closed parked {label} tab")


# ============================================================================
# Gate evaluation
# ============================================================================

class Gate(Enum):
    """Outcome of the pre-prompt checks, in precedence order."""
    COOLDOWN = "cooldown"      # inside the grant window: silent allow
    FIRST_OPEN = "first_open"  # first open of the day: auto-allow
    QUIET = "quiet"            # idle for QUIET_PERIOD_MINUTES+: auto-allow
    PROMPT = "prompt"          # none of the above: intercept and ask


def evaluate_gate(target):
    """Pure gate decision for a target. Precedence: COOLDOWN > FIRST_OPEN > QUIET > PROMPT."""
    key = target.key
    if is_in_cooldown(key):
        return Gate.COOLDOWN
    if get_daily_count(key) == 0:
        return Gate.FIRST_OPEN
    if is_quiet_period(key):
        return Gate.QUIET
    return Gate.PROMPT


# ============================================================================
# Surfaces — how a target is blocked/restored/discarded on interception
# ============================================================================

class AppSurface:
    """A target intercepted as a macOS app (quit on block, relaunch on restore)."""

    def __init__(self, target):
        self.target = target

    def block(self):
        return quit_app(self.target.app_name)

    def restore(self):
        _run(["open", "-a", self.target.app_name])

    def discard(self):
        pass  # the app is already quit; nothing to clean up


class WebSurface:
    """A target intercepted as a browser tab (park on block, restore URL, close on discard).

    window_id/tab_id must come from get_browser_front_tab_ref() — the only
    producer that validates them as digits.
    """

    def __init__(self, target, browser, window_id, tab_id, url):
        self.target = target
        self.browser = browser
        self.window_id = window_id
        self.tab_id = tab_id
        self.url = url

    def block(self):
        return park_tab(self.browser, self.window_id, self.tab_id, self.target.label)

    def restore(self):
        restore_tab(self.browser, self.window_id, self.tab_id, self.url, self.target.label)

    def discard(self):
        discard_parked_tab(self.browser, self.window_id, self.tab_id, self.target.label)


def handle_intercept(target, surface):
    """Shared intercept flow for both surfaces. Returns True when access is allowed."""
    key = target.key
    gate = evaluate_gate(target)

    if gate is Gate.COOLDOWN:
        log(f"Within {target.label} cooldown period - allowing")
        update_last_seen(key)  # glance only — must not extend the cooldown
        return True

    if gate is Gate.FIRST_OPEN:
        new_count = increment_daily_count(key)
        allow_access(key)
        log(f"First {target.label} open of the day - auto-allowed (#{new_count})")
        print(f"First {target.label} open today - allowed automatically")
        return True

    if gate is Gate.QUIET:
        new_count = increment_daily_count(key)
        allow_access(key)
        log(f"No {target.label} use in {QUIET_PERIOD_MINUTES}+ min - auto-allowed (#{new_count})")
        print(f"Quiet period - {target.label} allowed automatically")
        return True

    # Gate.PROMPT — intercept!
    blocked = surface.block()
    time.sleep(0.3)

    allowed = show_confirmation_dialog(target)

    if allowed:
        new_count = increment_daily_count(key)
        allow_access(key)
        surface.restore()
        log(f"Re-opened {target.label} (#{new_count} today)")
        print(f"{target.label} opened - Total today: {new_count}")
        return True

    surface.discard()
    prevented_count = increment_prevented_count(key)
    if blocked:
        log(f"{target.label} access denied - distraction prevented (#{prevented_count} today)")
        print(f"Access denied - good job staying focused! ({prevented_count} distractions prevented)")
    else:
        # The block itself failed (e.g. a missing Automation grant — see the
        # WARNING logged by quit_app/park_tab above), so the target may
        # still be sitting open. Still honors the user's "no" for counting
        # purposes, but says so plainly instead of implying it worked.
        log(f"{target.label} access denied, but it may not be fully blocked "
            f"- see the WARNING above (#{prevented_count} today)")
        print(f"Access denied, but FokusKeeper couldn't confirm {target.label} "
              f"is closed - check logs. ({prevented_count} distractions prevented)")
    return False


# ============================================================================
# Confirmation dialog
# ============================================================================

def format_time_rescued(prevented):
    """Human time saved: 10 minutes per blocked distraction."""
    minutes_rescued = prevented * 10
    hours_rescued, remaining_minutes = divmod(minutes_rescued, 60)
    if hours_rescued > 0:
        return f"{hours_rescued}h {remaining_minutes}m"
    return f"{remaining_minutes}m"


def compute_success_rate(total_opens, prevented):
    """Percentage of today's attempts that were blocked."""
    total_attempts = total_opens + prevented
    return (prevented / total_attempts * 100) if total_attempts > 0 else 0


def motivation_for(rate):
    """Motivational line for a success rate percentage."""
    if rate >= 70:
        return "Your focus is outstanding today! 🎯"
    elif rate >= 50:
        return "You're building great focus habits! 💪"
    elif rate >= 30:
        return "Keep pushing - you're making progress! ✨"
    else:
        return "This is your chance to strengthen focus! 🌟"


def parse_dialog_button(returncode, stdout):
    """True when the dialog result means \"I have a reason\".

    Non-zero returncode (X button, ESC, cancel) blocks, same as "Stay focused".
    """
    if returncode != 0:
        return False
    return "reason" in stdout.strip().lower()


def collect_stats():
    """Today's per-target counters as a list of dicts (key, label, opens, prevented)."""
    counters = _today_counters(load_state())
    return [
        {
            "key": key,
            "label": TARGET_LABELS[key],
            "opens": counters[key][0],
            "prevented": counters[key][1],
        }
        for key in TARGET_KEYS
    ]


def build_dialog_message(stats, target):
    """Dialog body: the intercepted target's numbers plus today's totals.

    Deliberately NOT one line per target — ten targets don't fit a dialog.
    Every interpolated value passes through sanitize_for_applescript.
    """
    by_key = {s["key"]: s for s in stats}
    mine = by_key.get(target.key, {"opens": 0, "prevented": 0})
    target_opens = validate_counter(mine["opens"])
    target_prevented = validate_counter(mine["prevented"])
    total_opens = sum(validate_counter(s["opens"]) for s in stats)
    total_prevented = sum(validate_counter(s["prevented"]) for s in stats)

    success_rate = compute_success_rate(total_opens, total_prevented)
    time_rescued = format_time_rescued(total_prevented)
    motivation = motivation_for(success_rate)
    label = sanitize_for_applescript(target.label)

    return (
        f"Taking a distraction break?\\n\\n"
        f"━━━━━━━━━━━━━━━━━━━━\\n\\n"
        f"Today's Focus Metrics\\n\\n"
        f"  📊  {label} Opens        {sanitize_for_applescript(target_opens)}\\n"
        f"  🚫  {label} Blocked      {sanitize_for_applescript(target_prevented)}\\n"
        f"  📈  All Opens        {sanitize_for_applescript(total_opens)}\\n"
        f"  🛑  All Blocked      {sanitize_for_applescript(total_prevented)}\\n"
        f"  ⏰  Time Rescued       {sanitize_for_applescript(time_rescued)}\\n\\n"
        f"━━━━━━━━━━━━━━━━━━━━\\n\\n"
        f"{motivation}\\n\\n"
        f"Are you sure you need to check {label} right now?"
    )


def show_confirmation_dialog(target):
    """Show the confirmation dialog for a target. True if the user has a reason."""
    message = build_dialog_message(collect_stats(), target)

    # Simple two-button dialog
    script = f'''
    set dialogResult to display dialog "{message}" buttons {{"Stay focused", "🔴 I have a reason"}} default button "Stay focused" with icon caution with title "🚪 FokusKeeper"
    set clickedButton to button returned of dialogResult
    return clickedButton
    '''

    # A timeout returns returncode 1 (logged by _run), which lands in the
    # same dialog-closed/ESC branch below — treated as "Stay focused".
    result = _run(["osascript", "-e", script], timeout=DIALOG_TIMEOUT_SECONDS)

    allowed = parse_dialog_button(result.returncode, result.stdout)
    if allowed:
        log(f"User has a reason - allowing {target.label} access")
    elif result.returncode == 0:
        log("User chose to stay focused")
    else:
        # X button (close), ESC, or cancelled dialog — same as "Stay focused"
        log("User closed dialog (X button/ESC) - staying focused")
    return allowed

def allow_access(app_type="slack"):
    """Grant access: start the cooldown clock. This is the ONLY thing that does."""
    state = load_state()
    now = datetime.now().isoformat()
    state[f"{app_type}_granted_at"] = now
    state[f"{app_type}_last_seen"] = now
    save_state(state)
    log(f"Access allowed - {app_type} cooldown started ({COOLDOWN_MINUTES} min)")

def monitor():
    """Main monitoring loop across all enabled targets (app + web surfaces)."""
    targets = enabled_targets()
    log(f"FokusKeeper started ({', '.join(t.label for t in targets)})")

    # Display helpful startup information
    print("=" * 70)
    print("🚪 FOKUSKEEPER - Distraction Blocker")
    print("=" * 70)
    print()
    print("🎯 WATCHED TARGETS:")
    for target in targets:
        surfaces = []
        if target.app_name:
            surfaces.append(f"app: {target.app_name}")
        if target.url_domains:
            surfaces.append(f"web: {', '.join(target.url_domains)}")
        print(f"  • {target.label} ({'; '.join(surfaces)})")
    print()
    print("📋 HOW IT WORKS:")
    print("  • Detects when you try to open a watched app or site")
    print("  • Shows a dialog making you consciously decide if you need it")
    print("  • Tracks your daily stats and distractions blocked")
    print()
    print(f"⏰ COOLDOWN PERIOD: {COOLDOWN_MINUTES} minutes")
    print(f"  After clicking 'I have a reason', you get {COOLDOWN_MINUTES} minutes of")
    print("  uninterrupted access. The timer starts at the grant and is not")
    print("  extended by continued use.")
    print()
    print(f"🤫 QUIET PERIOD: {QUIET_PERIOD_MINUTES} minutes")
    print(f"  If a target hasn't been used in {QUIET_PERIOD_MINUTES}+ minutes, the next")
    print("  open is let through without a prompt (checked per target).")
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
    stats_line = ", ".join(
        f"{t.label} {get_daily_count(t.key)}/{get_prevented_count(t.key)} (opens/blocked)"
        for t in targets if get_daily_count(t.key) or get_prevented_count(t.key)
    ) or "no activity yet"
    print(f"📊 Today's Stats: {stats_line}")
    print("=" * 70)
    print()
    print("Running... (Press Ctrl+C to stop)")
    print()

    last_app_key = None   # key of the app target that was frontmost last tick
    last_web_key = None   # key of the web target the Chrome tab showed last tick

    try:
        while True:
            try:
                current_frontmost = get_frontmost_app()
                targets = enabled_targets()  # one config stat per tick

                # Check 1: app-surface targets (edge-triggered on focus change)
                app_target = match_app_name(current_frontmost, targets)
                if app_target is not None and app_target.key != last_app_key:
                    log(f"{app_target.label} activated/focused")
                    allowed = handle_intercept(app_target, AppSurface(app_target))
                    if not allowed:
                        # Reset edge keys so a missed target re-triggers on the
                        # next focus change (the dialog stole focus meanwhile).
                        last_app_key = None
                        last_web_key = None
                        continue
                    time.sleep(0.5)

                # Track continued usage (refresh last_seen on continued use)
                if app_target is not None:
                    refresh_last_seen(app_target.key)
                last_app_key = app_target.key if app_target is not None else None

                # Check 2: web-surface targets in a supported browser (edge-triggered on tab URL)
                browser = BROWSERS_BY_APP_NAME.get(current_frontmost)
                if browser is not None:
                    tab_url = get_browser_active_tab_url(browser)
                    web_target = match_url(tab_url, targets)

                    if web_target is not None and web_target.key != last_web_key:
                        log(f"{web_target.label} tab activated: {_hostname_for_log(tab_url)}")
                        # Pin the exact tab (or window, for a browser without
                        # tab ids) so it can be restored into its own place.
                        # Ids come ONLY from get_browser_front_tab_ref.
                        window_id, tab_id = get_browser_front_tab_ref(browser)
                        surface = WebSurface(web_target, browser, window_id, tab_id, tab_url)
                        allowed = handle_intercept(web_target, surface)
                        if not allowed:
                            # Reset edge keys so a missed target re-triggers on the
                            # next focus change.
                            last_web_key = None
                            last_app_key = None
                            continue
                        time.sleep(0.5)

                    # Track continued usage (refresh last_seen on continued use)
                    if web_target is not None:
                        refresh_last_seen(web_target.key)
                    last_web_key = web_target.key if web_target is not None else None
                else:
                    last_web_key = None

                time.sleep(0.5)  # Check twice per second
            except Exception as e:
                # Never let a transient failure kill the daemon silently.
                # KeyboardInterrupt is not an Exception, so Ctrl+C still
                # reaches the handler below.
                log(f"Monitor loop error: {e}\n{traceback.format_exc()}")
                time.sleep(2)
                continue

    except KeyboardInterrupt:
        log("FokusKeeper stopped")
        summary = ", ".join(
            f"{t.label}: {get_daily_count(t.key)}" for t in enabled_targets()
            if get_daily_count(t.key)
        ) or "no opens today"
        print(f"\nStopped. {summary}")

# ============================================================================
# CLI commands
# ============================================================================

def load_history():
    """Load the history event list, degrading to [] on a missing/corrupt file."""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError, OSError):
            return []
    return []

def cooldown_remaining_minutes(state, key):
    """Minutes of cooldown left for a target, from {key}_granted_at.

    The old bash CLI read {key}_last_active_time, which the daemon no longer
    writes, so it always showed no cooldown. The grant clock is authoritative.
    """
    granted_at = _read_clock(state, key, "granted_at")
    if granted_at is None:
        return 0.0
    remaining = timedelta(minutes=COOLDOWN_MINUTES) - (datetime.now() - granted_at)
    return max(0.0, remaining.total_seconds() / 60)

def _today_counters(state):
    """Per-target (opens, prevented) for today, honouring legacy shared keys."""
    if state.get("stats_date") != get_today_date():
        return {key: (0, 0) for key in TARGET_KEYS}
    counters = {}
    for key in TARGET_KEYS:
        opens = validate_counter(state.get(f"{key}_opens", 0))
        prevented = state.get(f"{key}_prevented")
        if prevented is None:
            # Legacy state files only carried the shared total, and legacy
            # events were Slack-only (see _bucket_event_type) — falling back
            # for every target would multiply the shared total per target.
            prevented = state.get("distractions_prevented", 0) if key == "slack" else 0
        counters[key] = (opens, validate_counter(prevented))
    return counters

def cmd_stats():
    """Print today's per-target stats and cooldowns."""
    state = load_state()
    counters = _today_counters(state)
    print(f"FokusKeeper - Today's stats ({get_today_date()})")
    for key in TARGET_KEYS:
        opens, prevented = counters[key]
        remaining = cooldown_remaining_minutes(state, key)
        cooldown = f"{remaining:.0f}m left" if remaining > 0 else "none"
        print(f"  {TARGET_LABELS[key]}: opens {opens}, blocked {prevented}, cooldown {cooldown}")
    total_opens = sum(opens for opens, _ in counters.values())
    total_blocked = sum(prevented for _, prevented in counters.values())
    print(f"  Total opens: {total_opens}")
    print(f"  Total blocked: {total_blocked}")

def cmd_status():
    """Print whether the daemon is running, plus today's stats."""
    result = _run(["pgrep", "-f", "-u", str(os.getuid()), DAEMON_PROCESS_PATTERN])
    pids = {p.strip() for p in result.stdout.split() if p.strip()}
    pids.discard(str(os.getpid()))  # this status invocation matches the pattern too
    if pids:
        print(f"FokusKeeper daemon: running (pid {', '.join(sorted(pids))})")
    else:
        print("FokusKeeper daemon: not running")
    cmd_stats()

def _bucket_event_type(event_type):
    """Map a history event type to (target_key, kind) or None.

    Legacy events ("opened"/"prevented") predate the Gmail split and were
    Slack-only, so they count against slack.
    """
    if event_type == "opened":
        return ("slack", "opened")
    if event_type == "prevented":
        return ("slack", "prevented")
    for key in TARGET_KEYS:
        for kind in ("opened", "prevented"):
            if event_type == f"{key}_{kind}":
                return (key, kind)
    return None

def cmd_history():
    """Print the last 7 days of activity grouped by date."""
    history = load_history()
    cutoff = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
    days = {}
    for event in history:
        date = event.get("date", "")
        if date < cutoff:
            continue
        bucket = _bucket_event_type(event.get("type"))
        if bucket is None:
            continue
        key, kind = bucket
        day = days.setdefault(date, {k: {"opened": 0, "prevented": 0} for k in TARGET_KEYS})
        day[key][kind] += 1

    print("FokusKeeper - Last 7 days")
    if not days:
        print("  No activity recorded.")
        return
    for date in sorted(days):
        parts = [
            f"{TARGET_LABELS[key]} opens {days[date][key]['opened']}, blocked {days[date][key]['prevented']}"
            for key in TARGET_KEYS
        ]
        print(f"  {date}: " + " | ".join(parts))

def cmd_report():
    """Print totals across all recorded history."""
    history = load_history()
    totals = {key: {"opened": 0, "prevented": 0} for key in TARGET_KEYS}
    dates = []
    for event in history:
        bucket = _bucket_event_type(event.get("type"))
        if bucket is None:
            continue
        key, kind = bucket
        totals[key][kind] += 1
        if event.get("date"):
            dates.append(event["date"])

    print("FokusKeeper - All-time report")
    if not dates:
        print("  No history recorded.")
        return
    print(f"  From {min(dates)} to {max(dates)}")
    for key in TARGET_KEYS:
        print(f"  {TARGET_LABELS[key]}: opens {totals[key]['opened']}, blocked {totals[key]['prevented']}")
    total_opened = sum(t["opened"] for t in totals.values())
    total_prevented = sum(t["prevented"] for t in totals.values())
    print(f"  Total opens: {total_opened}")
    print(f"  Total blocked: {total_prevented}")

def save_config(config):
    """Write CONFIG_FILE with user-only permissions."""
    _write_json_file(CONFIG_FILE, config)


def run_setup():
    """Show the native multi-select target chooser and write CONFIG_FILE.

    Returns the list of enabled keys written, or None when nothing was
    written (user cancelled, or osascript failed e.g. headless). On cancel
    the existing config is left untouched; if none exists, none is written,
    so the all-enabled default applies.
    """
    # Labels are trusted module constants, but the invariant is that
    # EVERYTHING interpolated into osascript passes through
    # sanitize_for_applescript.
    items = ", ".join(
        f'"{sanitize_for_applescript(t.label)}"' for t in TARGETS
    )
    # Pre-select the currently enabled set so re-running setup edits the
    # existing selection. With no config, load_enabled_targets() returns all
    # targets, so first-run behaviour is unchanged (everything selected).
    default_items = ", ".join(
        f'"{sanitize_for_applescript(t.label)}"' for t in load_enabled_targets()
    )
    script = (
        f"choose from list {{{items}}} "
        f'with title "FokusKeeper" '
        f'with prompt "Which distractions should FokusKeeper gate? '
        f"Currently gated targets are selected. "
        f'(Cmd-click to toggle)" '
        f"default items {{{default_items}}} "
        f"with multiple selections allowed"
    )
    # A timeout returns returncode 1 (logged by _run) — treated as cancel.
    result = _run(["osascript", "-e", script], timeout=DIALOG_TIMEOUT_SECONDS)

    if result.returncode != 0:
        # osascript unavailable/failed (e.g. headless) — treat as cancel.
        log("Setup chooser failed (osascript error) - config left untouched")
        return None

    output = result.stdout.strip()
    if output == "false":
        # The literal "false" is what `choose from list` prints on Cancel.
        log("Setup cancelled - config left untouched")
        return None

    # osascript prints the chosen labels comma-separated. None of our labels
    # contain a comma, so a plain split is unambiguous.
    chosen = {label.strip() for label in output.split(",")}
    enabled = [t.key for t in TARGETS if t.label in chosen]  # TARGETS order
    save_config({"enabled": enabled})
    log(f"Setup saved: enabled targets = {', '.join(enabled) or 'none'}")
    return enabled


def cmd_setup():
    """`fokuskeeper setup`: run the chooser, then print the enabled set."""
    run_setup()
    labels = ", ".join(t.label for t in enabled_targets())
    print(f"Enabled targets: {labels}")


def cmd_run():
    """`fokuskeeper run`: the resident monitor loop. Never shows UI.

    This command is launched backgrounded (nohup ... &) by the CLI and the
    login-item launcher app, so it must not block on an interactive dialog —
    a modal AppleScript prompt from a backgrounded, non-foreground process is
    unreliable on macOS (TCC/window-server attribution is flaky outside a
    normal foreground context) and was the actual cause of a real "daemon
    never starts, log stays empty" report on a fresh account. First-run
    target selection is a separate, explicit, foreground step: `install.sh`
    runs `fokuskeeper setup` before ever starting the daemon, and it's
    re-runnable any time via `fokuskeeper setup`. With no config at all,
    enabled_targets() already defaults to all targets, so skipping the
    chooser here is a safe fallback, not a degraded one.
    """
    # Double-start guard: refuse to run a second daemon.
    result = _run(["pgrep", "-f", "-u", str(os.getuid()), DAEMON_PROCESS_PATTERN])
    pids = {p.strip() for p in result.stdout.split() if p.strip()}
    pids.discard(str(os.getpid()))  # this invocation matches the pattern too
    pids.discard(str(os.getppid()))  # so can a wrapper script's interpreter
    if pids:
        print(f"FokusKeeper daemon already running (pid {', '.join(sorted(pids))})")
        return
    monitor()


def cmd_reset():
    """Zero today's counters, preserving the cooldown/quiet-period clocks."""
    state = load_state()
    _reset_daily_counters(state)
    save_state(state)
    log("Counters reset via CLI")
    print("Today's counters reset (cooldown clocks preserved).")

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="fokuskeeper",
        description="FokusKeeper - distraction gate for distracting apps and sites.",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "stats", "status", "history", "report", "reset",
                 "setup"],
        help="run: start the monitor daemon (default); stats: today's numbers; "
             "status: daemon liveness + stats; history: last 7 days; "
             "report: all-time totals; reset: zero today's counters; "
             "setup: choose which targets to gate",
    )
    args = parser.parse_args(argv)

    # Ensure log directory exists
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    migrate_legacy_files()

    dispatch = {
        "run": cmd_run,
        "stats": cmd_stats,
        "status": cmd_status,
        "history": cmd_history,
        "report": cmd_report,
        "reset": cmd_reset,
        "setup": cmd_setup,
    }
    dispatch[args.command]()

if __name__ == "__main__":
    main()

