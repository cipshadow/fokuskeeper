#!/usr/bin/python3
"""Menu bar status icon for the FokusKeeper daemon.

Does not run any FokusKeeper logic itself — fokuskeeper.py keeps doing that
as its own process. This polls for that process on a timer, shows an on/off
icon, and can start or stop it.

Deliberately self-contained: it references only its own sibling daemon script
and the launchd label, never anything outside this repo. A launchd-started
process cannot read paths that need per-app TCC grants, so keeping every
runtime path inside this repo is what makes the app portable and reliable.

Start prefers `launchctl kickstart` so the daemon comes up under the same
agent, PATH and logging as it does at login. If the agent isn't installed on
this machine it spawns the daemon directly instead, so the icon still works on
a fresh clone. Stop uses pkill, which works whoever started the process; the
agent intentionally has no KeepAlive, so nothing resurrects it.
"""

import fcntl
import os
import subprocess
import sys
from pathlib import Path

import AppKit
import rumps
import rumps.events  # not re-exported by rumps/__init__, so import it directly

HERE = Path(__file__).resolve().parent
DAEMON_SCRIPT = HERE / "fokuskeeper.py"
AGENT_LABEL = "com.fokuskeeper.daemon"
PROCESS_PATTERN = "python.*fokuskeeper.py"
LOCK_FILE = Path.home() / ".fokuskeeper-menubar.lock"
POLL_SECONDS = 5

ICON_SYMBOLS_ON = ("shield.lefthalf.filled", "lock.shield")
ICON_SYMBOLS_OFF = ("shield.slash", "shield")
ICON_POINT_SIZE = 18

FALLBACK_TITLE_ON = "🛡️"
FALLBACK_TITLE_OFF = "🛡️⏸"

_lock_handle = None


def is_running():
    result = subprocess.run(
        ["pgrep", "-f", PROCESS_PATTERN], capture_output=True, text=True
    )
    return result.returncode == 0


def agent_target():
    return f"gui/{os.getuid()}/{AGENT_LABEL}"


def agent_installed():
    """True if the LaunchAgent is bootstrapped, so kickstart will work."""
    result = subprocess.run(
        ["launchctl", "print", agent_target()], capture_output=True, text=True
    )
    return result.returncode == 0


def start_daemon():
    """Start via launchd when available, else spawn directly."""
    if agent_installed():
        result = subprocess.run(
            ["launchctl", "kickstart", agent_target()], capture_output=True, text=True
        )
        if result.returncode == 0:
            return

    # No agent on this machine (or kickstart refused) — run it ourselves.
    # start_new_session detaches it so it outlives this menu bar app.
    venv_python = HERE / ".venv" / "bin" / "python3"
    python = str(venv_python) if venv_python.exists() else "/usr/bin/python3"
    subprocess.Popen(
        [python, "-u", str(DAEMON_SCRIPT), "run"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def stop_daemon():
    """pkill regardless of who started it; no KeepAlive means it stays down."""
    subprocess.run(["pkill", "-f", PROCESS_PATTERN], capture_output=True, text=True)


class FokusKeeperStatusApp(rumps.App):
    def __init__(self):
        super().__init__("FokusKeeper", title=FALLBACK_TITLE_OFF, quit_button="Quit")
        self.on = False

        self.toggle_item = rumps.MenuItem("Start FokusKeeper", callback=self.toggle)
        self.menu = [self.toggle_item]

        self.tick(None)
        self.timer = rumps.Timer(self.tick, POLL_SECONDS)
        self.timer.start()

    @rumps.events.before_start
    def configure_status_item(self):
        item = self.status_item()
        if item is not None:
            try:
                item.setVisible_(True)
            except AttributeError:
                pass
        self.apply_icon()

    def status_item(self):
        nsapp = getattr(self, "_nsapp", None)
        if nsapp is None:
            return None
        return getattr(nsapp, "nsstatusitem", None)

    def apply_icon(self):
        item = self.status_item()
        if item is None:
            return

        names = ICON_SYMBOLS_ON if self.on else ICON_SYMBOLS_OFF
        image = None
        try:
            for name in names:
                image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                    name, "FokusKeeper"
                )
                if image is not None:
                    break
        except AttributeError:
            image = None

        if image is None:
            item.setImage_(None)
            item.setTitle_(FALLBACK_TITLE_ON if self.on else FALLBACK_TITLE_OFF)
            return

        image.setTemplate_(True)
        image.setSize_((ICON_POINT_SIZE, ICON_POINT_SIZE))
        item.setTitle_("")
        item.setImage_(image)

    def toggle(self, _sender):
        if self.on:
            stop_daemon()
        else:
            start_daemon()
        self.tick(None)

    def tick(self, _sender):
        self.on = is_running()
        self.toggle_item.title = "Stop FokusKeeper" if self.on else "Start FokusKeeper"
        self.apply_icon()


def claim_single_instance():
    global _lock_handle
    _lock_handle = open(LOCK_FILE, "w")
    try:
        fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)


if __name__ == "__main__":
    claim_single_instance()
    AppKit.NSApplication.sharedApplication().setActivationPolicy_(
        AppKit.NSApplicationActivationPolicyAccessory
    )
    FokusKeeperStatusApp().run()
