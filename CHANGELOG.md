# Changelog

## 1.2.0 - 2026-08-31

- Renamed "targets" to "apps" throughout the UI, dialogs, and docs.
- **Choose targets...** and **Adjust timing...** are now one combined **Settings...** flow (`fokuskeeper settings`): app chooser, then cooldown, then quiet period, in one visit.
- Reworded the cooldown and quiet-period prompts with concrete examples of what each setting means in practice.

## 1.1.0 - 2026-08-31

- Cooldown and quiet-period minutes are now configurable: **Adjust timing...** in the menu bar, or `fokuskeeper timing` from a terminal. Both prompts pre-fill the current value; cancelling either one leaves both settings untouched.
- Fixed: relaunching the menu bar app (login, crash recovery, manual restart) no longer silently restarts the daemon after you'd deliberately stopped it. Your last explicit start/stop choice is now remembered.
- Fixed: `fokuskeeper setup` no longer wipes previously-saved timing settings when it saves the target selection.
- Gave the menu bar status item a stable autosave name, so third-party menu bar managers (Bartender, Ice, and similar) can persist its position instead of losing track of it across relaunches.

## 1.0.0 - 2026-08-30

First public release.

- Gates ten distraction targets on macOS: Slack and WhatsApp as native apps plus their web apps, and web-only Gmail, Instagram, Facebook, Reddit, YouTube, X, TikTok, LinkedIn -- web gating works in both Chrome and Safari. Firefox isn't supported (no AppleScript tab-URL access).
- One-click installer (`FokusKeeper-Install.command`, distributed via GitHub Releases): download, unzip, double-click, no git or terminal typing needed.
- Blocking dialog with today's stats, "Stay focused" as the safe default, and "I have a reason" to proceed.
- First-run welcome screen explaining how the dialog and cooldown work, then a native chooser to pick which targets to gate. Re-run anytime via the menu bar's **Choose targets...** item or `fokuskeeper setup`; config changes apply live.
- Per-target 3-minute cooldown shared between a target's app and web surfaces; first-open-of-the-day and 60-minute quiet-period auto-allows.
- Stats CLI: `stats`, `history`, `report`, `reset`, plus `start`/`stop`/`restart`/`status`/`logs` process commands.
- `install.sh` sets up a menu bar status icon by default (shield-with-K, dims when stopped) and builds a `~/Applications/FokusKeeper.app` login launcher that runs it; falls back to a headless daemon if the menu bar's one dependency (`rumps`) can't install. Optional Desktop control panel; `uninstall.sh` with `--purge`.
- Automatic migration of legacy `~/.slack-gatekeeper-*.json` state and history files (copied, originals kept).
- Everything stays on the machine: state, history, config, and logs in the home directory with `chmod 600`, no telemetry.
