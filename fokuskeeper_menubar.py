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
DESIRED_STATE_FILE = Path.home() / ".fokuskeeper-desired-state"
POLL_SECONDS = 5

ICON_BASE_SYMBOLS = ("shield.fill", "shield.lefthalf.filled", "shield")
ICON_POINT_SIZE = 18
ICON_OFF_FRACTION = 0.4  # dims the shield when stopped; the K cutout stays crisp

FALLBACK_TITLE_ON = "🛡️"
FALLBACK_TITLE_OFF = "🛡️⏸"

_lock_handle = None
_shield_k_cache = {}


def _shield_k_image(on):
    """A shield with a 'K' cut out of it, cached per on/off state.

    No SF Symbol combines a shield with an arbitrary letter, so this
    composites one: draw the shield glyph solid, then punch the K through it
    with a destination-out blend — the same cutout technique Apple's own
    compound shield symbols use (e.g. shield.lefthalf.filled's two-tone
    split). Returns None if no shield symbol resolves at all, so the caller
    can fall back to the plain-text title.
    """
    if on in _shield_k_cache:
        return _shield_k_cache[on]

    base = None
    for name in ICON_BASE_SYMBOLS:
        base = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            name, "FokusKeeper"
        )
        if base is not None:
            break
    if base is None:
        _shield_k_cache[on] = None
        return None

    size = ICON_POINT_SIZE
    image = AppKit.NSImage.alloc().initWithSize_((size, size))
    image.lockFocus()

    rect = AppKit.NSMakeRect(0, 0, size, size)
    base.drawInRect_fromRect_operation_fraction_(
        rect, AppKit.NSZeroRect, AppKit.NSCompositingOperationSourceOver,
        1.0 if on else ICON_OFF_FRACTION,
    )

    font = AppKit.NSFont.boldSystemFontOfSize_(size * 0.62)
    attrs = {
        AppKit.NSFontAttributeName: font,
        AppKit.NSForegroundColorAttributeName: AppKit.NSColor.blackColor(),
    }
    text = AppKit.NSAttributedString.alloc().initWithString_attributes_("K", attrs)
    text_size = text.size()
    x = (size - text_size.width) / 2.0 - 2  # nudge left: the K's diagonal strokes read visually off-center otherwise
    y = (size - text_size.height) / 2.0 + size * 0.02  # nudge up: the shield's pointed tip reads as dead weight below center

    ctx = AppKit.NSGraphicsContext.currentContext()
    ctx.saveGraphicsState()
    ctx.setCompositingOperation_(AppKit.NSCompositingOperationDestinationOut)
    text.drawAtPoint_((x, y))
    ctx.restoreGraphicsState()

    image.unlockFocus()
    image.setTemplate_(True)
    _shield_k_cache[on] = image
    return image


def is_running():
    # -u str(os.getuid()): on a shared Mac (Fast User Switching or multiple
    # real accounts), pgrep -f alone matches ANY user's daemon -- another
    # account's FokusKeeper would make this one falsely report running.
    result = subprocess.run(
        ["pgrep", "-f", "-u", str(os.getuid()), PROCESS_PATTERN],
        capture_output=True, text=True,
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


def _resident_python():
    """The python that should run fokuskeeper.py -- the repo's own venv if
    the menu bar setup created one, else the system python3."""
    venv_python = HERE / ".venv" / "bin" / "python3"
    return str(venv_python) if venv_python.exists() else "/usr/bin/python3"


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
    subprocess.Popen(
        [_resident_python(), "-u", str(DAEMON_SCRIPT), "run"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def open_settings(_sender=None):
    """Re-run the target chooser (the same one install.sh and `fokuskeeper
    setup` use — no separate settings UI to keep in sync). Runs in the
    foreground and blocks the menu bar app's own event loop while the
    chooser dialog is up; that's fine, since a modal system dialog already
    blocks everything else the user could do in the meantime.
    """
    subprocess.run([_resident_python(), str(DAEMON_SCRIPT), "setup"])


def open_timing(_sender=None):
    """Re-run the cooldown/quiet-period prompts (same as `fokuskeeper
    timing`) — see open_settings() for why this shells out rather than
    reimplementing the dialogs here.
    """
    subprocess.run([_resident_python(), str(DAEMON_SCRIPT), "timing"])


def stop_daemon():
    """pkill regardless of how it was started (launchd vs. direct spawn); no
    KeepAlive means it stays down. Scoped to this user, not other accounts'
    processes -- see is_running().
    """
    subprocess.run(
        ["pkill", "-f", "-u", str(os.getuid()), PROCESS_PATTERN],
        capture_output=True, text=True,
    )


def desired_running():
    """Whether the daemon should be on, per the user's last explicit choice.

    Defaults to True when the file is absent (first-ever launch, per
    FokusKeeperStatusApp.__init__'s docstring) or unreadable -- everything
    else preserves a deliberate `stop` across menu bar app relaunches,
    instead of __init__ silently overriding it every time the app restarts
    (a real bug: a menu bar app relaunch used to force the daemon back on
    even right after the user stopped it).
    """
    try:
        return DESIRED_STATE_FILE.read_text().strip() != "off"
    except OSError:
        return True


def set_desired_running(value):
    try:
        DESIRED_STATE_FILE.write_text("on" if value else "off")
    except OSError:
        pass


class FokusKeeperStatusApp(rumps.App):
    def __init__(self):
        super().__init__("FokusKeeper", title=FALLBACK_TITLE_OFF, quit_button="Quit")
        self.on = False

        self.toggle_item = rumps.MenuItem("Start FokusKeeper", callback=self.toggle)
        self.settings_item = rumps.MenuItem("Choose targets...", callback=open_settings)
        self.timing_item = rumps.MenuItem("Adjust timing...", callback=open_timing)
        self.menu = [self.toggle_item, None, self.settings_item, self.timing_item]

        # The menu bar icon is now the default entry point (install.sh's
        # login launcher runs this, not the daemon directly), so launching
        # it must actually turn gating on for a fresh install -- not just
        # show a stopped icon waiting for a manual click nobody asked for.
        # But once the user has explicitly stopped it, a later relaunch of
        # this app (login, crash recovery, manual restart) must respect
        # that choice rather than silently turning gating back on.
        if not is_running() and desired_running():
            start_daemon()

        self.tick(None)
        self.timer = rumps.Timer(self.tick, POLL_SECONDS)
        self.timer.start()

    @rumps.events.before_start
    def configure_status_item(self):
        item = self.status_item()
        if item is not None:
            # rumps never gives its NSStatusItem an autosave name, so AppKit
            # (and third-party menu bar managers like Ice, which track items
            # by their persisted position) have no stable identity to anchor
            # it to across relaunches -- a plausible reason the icon can
            # exist but never render somewhere visible.
            try:
                item.setAutosaveName_("FokusKeeperStatusItem")
            except AttributeError:
                pass
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

        try:
            image = _shield_k_image(self.on)
        except AttributeError:
            image = None

        if image is None:
            item.setImage_(None)
            item.setTitle_(FALLBACK_TITLE_ON if self.on else FALLBACK_TITLE_OFF)
            return

        item.setTitle_("")
        item.setImage_(image)

    def toggle(self, _sender):
        if self.on:
            stop_daemon()
            set_desired_running(False)
        else:
            start_daemon()
            set_desired_running(True)
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
