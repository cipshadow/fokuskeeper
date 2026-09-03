"""One native window for everything `fokuskeeper settings` configures:
which apps to watch, plus the cooldown and quiet-period minutes.

Deliberately separate from fokuskeeper.py (stdlib only) -- this needs AppKit,
which isn't guaranteed installed (see install.sh's headless fallback). Import
this module lazily and fall back to the older sequential dialogs if it's
unavailable; see fokuskeeper.py's cmd_settings().

Runs as its own short-lived process either way (invoked via `fokuskeeper.py
settings`), so it always bootstraps its own NSApplication rather than
assuming one is already running.
"""

import AppKit
import objc

WINDOW_WIDTH = 440
CHECKBOX_ROW_HEIGHT = 22
MARGIN = 20


class _SettingsDelegate(AppKit.NSObject):
    """Holds the Save/Cancel targets. PyObjC action methods must live on an
    NSObject subclass -- plain Python callables can't be wired as targets.
    """

    def initWithPanel_(self, panel):
        self = objc.super(_SettingsDelegate, self).init()
        if self is None:
            return None
        self.panel = panel
        return self

    def save_(self, _sender):
        self.panel.result = "save"
        AppKit.NSApp.stopModal()

    def cancel_(self, _sender):
        self.panel.result = "cancel"
        AppKit.NSApp.stopModal()


class SettingsPanel:
    """Builds and runs the settings window modally. Construct and call
    .run() -- returns "save" or "cancel"; on "save", read back
    .enabled_keys(), .cooldown_text(), .quiet_text().
    """

    def __init__(self, targets, enabled_keys, cooldown_minutes, quiet_period_minutes):
        self.targets = targets
        self.result = "cancel"
        self._checkboxes = []
        self._build(enabled_keys, cooldown_minutes, quiet_period_minutes)

    def _label(self, text, x, y, width, height, bold=False, wraps=False):
        field = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(x, y, width, height)
        )
        field.setStringValue_(text)
        field.setBezeled_(False)
        field.setDrawsBackground_(False)
        field.setEditable_(False)
        field.setSelectable_(False)
        if bold:
            field.setFont_(AppKit.NSFont.boldSystemFontOfSize_(13))
        else:
            field.setFont_(AppKit.NSFont.systemFontOfSize_(11))
            field.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        if wraps:
            field.cell().setWraps_(True)
            field.cell().setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        return field

    def _timer_field(self, label_text, example_text, value, y, content_width):
        """One timer row: a number field with a wrapped label beside it, then
        a wrapped example line below spanning the full width. Returns the
        NSTextField (for later reading back) and the list of views to add,
        plus the total height consumed.
        """
        field_height = 24
        label_height = 36  # two lines' worth, wrapped
        example_height = 28
        gap = 4

        field = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(MARGIN, y + example_height + gap, 60, field_height)
        )
        field.setStringValue_(str(value))

        label = self._label(
            label_text, MARGIN + 72, y + example_height + gap - 6,
            content_width - 72, label_height, wraps=True,
        )

        example = self._label(
            example_text, MARGIN, y, content_width, example_height, wraps=True,
        )

        total_height = example_height + gap + field_height
        return field, [label, example], total_height

    def _build(self, enabled_keys, cooldown_minutes, quiet_period_minutes):
        content_width = WINDOW_WIDTH - 2 * MARGIN
        extra_views = []

        # Layout bottom-up: every element is placed at the current `y`
        # (bottom of its own box), then `y` advances by that element's
        # height plus a gap before the next one is placed above it.
        y = MARGIN

        # Buttons
        button_row_height = 32
        save_button = AppKit.NSButton.alloc().initWithFrame_(
            AppKit.NSMakeRect(WINDOW_WIDTH - MARGIN - 90, y, 90, button_row_height)
        )
        save_button.setTitle_("Save")
        save_button.setBezelStyle_(AppKit.NSBezelStyleRounded)
        save_button.setKeyEquivalent_("\r")  # Return triggers Save

        cancel_button = AppKit.NSButton.alloc().initWithFrame_(
            AppKit.NSMakeRect(WINDOW_WIDTH - MARGIN - 90 - 90 - 8, y, 90, button_row_height)
        )
        cancel_button.setTitle_("Cancel")
        cancel_button.setBezelStyle_(AppKit.NSBezelStyleRounded)
        cancel_button.setKeyEquivalent_("\x1b")  # Escape triggers Cancel

        y += button_row_height + MARGIN

        # Quiet period section
        self.quiet_field, views, height = self._timer_field(
            "Quiet period (minutes): how often you can check an app without "
            "it counting as a distraction.",
            "Example: 60 minutes means checking Slack once an hour is fine "
            "and won't be gated -- but coming back sooner will be.",
            quiet_period_minutes, y, content_width,
        )
        extra_views.extend(views)
        y += height + MARGIN

        # Cooldown section
        self.cooldown_field, views, height = self._timer_field(
            "Cooldown (minutes): how long after you're let through before "
            "FokusKeeper asks again.",
            "Example: 5 minutes means a quick detour to Google and back to "
            "Slack still counts as the same work session -- no second prompt.",
            cooldown_minutes, y, content_width,
        )
        extra_views.extend(views)
        y += height + MARGIN

        # Apps checklist (built bottom-up, so the first target ends up on top)
        apps_title = self._label("Apps to watch", MARGIN, y, content_width, 18, bold=True)
        extra_views.append(apps_title)
        y += 22

        for target in self.targets:
            checkbox = AppKit.NSButton.alloc().initWithFrame_(
                AppKit.NSMakeRect(MARGIN, y, content_width, CHECKBOX_ROW_HEIGHT)
            )
            checkbox.setButtonType_(AppKit.NSButtonTypeSwitch)
            checkbox.setTitle_(target.label)
            checkbox.setState_(
                AppKit.NSControlStateValueOn if target.key in enabled_keys
                else AppKit.NSControlStateValueOff
            )
            self._checkboxes.append((target.key, checkbox))
            y += CHECKBOX_ROW_HEIGHT

        y += MARGIN  # top margin above the checklist

        window_height = y
        window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(0, 0, WINDOW_WIDTH, window_height),
            AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        window.setTitle_("FokusKeeper Settings")
        window.center()

        content = window.contentView()
        for _, checkbox in self._checkboxes:
            content.addSubview_(checkbox)
        for view in extra_views:
            content.addSubview_(view)
        content.addSubview_(self.cooldown_field)
        content.addSubview_(self.quiet_field)
        content.addSubview_(save_button)
        content.addSubview_(cancel_button)

        self._delegate = _SettingsDelegate.alloc().initWithPanel_(self)
        save_button.setTarget_(self._delegate)
        save_button.setAction_("save:")
        cancel_button.setTarget_(self._delegate)
        cancel_button.setAction_("cancel:")

        self.window = window

    def run(self):
        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
        app.activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)
        app.runModalForWindow_(self.window)
        self.window.close()
        return self.result

    def enabled_keys(self):
        return [key for key, checkbox in self._checkboxes if checkbox.state() == AppKit.NSControlStateValueOn]

    def cooldown_text(self):
        return self.cooldown_field.stringValue()

    def quiet_text(self):
        return self.quiet_field.stringValue()


def show_settings_panel(targets, enabled_keys, cooldown_minutes, quiet_period_minutes):
    """Show the panel; returns (result, enabled_keys, cooldown_text, quiet_text).

    result is "save" or "cancel". On "cancel" the other values are the
    inputs unchanged -- the caller should not write anything.
    """
    panel = SettingsPanel(targets, enabled_keys, cooldown_minutes, quiet_period_minutes)
    result = panel.run()
    return result, panel.enabled_keys(), panel.cooldown_text(), panel.quiet_text()
