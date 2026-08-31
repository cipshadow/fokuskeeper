# Changelog

## 1.0.0 - 2026-08-30

First public release.

- Gates ten distraction targets on macOS: Slack and WhatsApp as native apps plus their web apps, and web-only Gmail, Instagram, Facebook, Reddit, YouTube, X, TikTok, LinkedIn -- web gating works in both Chrome and Safari. Firefox isn't supported (no AppleScript tab-URL access).
- One-click installer (`FokusKeeper-Install.command`, distributed via GitHub Releases): download, unzip, double-click, no git or terminal typing needed.
- Blocking dialog with today's stats, "Stay focused" as the safe default, and "I have a reason" to proceed.
- First-run native chooser to pick which targets to gate; re-run anytime with `fokuskeeper setup`; config changes apply live.
- Per-target 3-minute cooldown shared between a target's app and web surfaces; first-open-of-the-day and 60-minute quiet-period auto-allows.
- Stats CLI: `stats`, `history`, `report`, `reset`, plus `start`/`stop`/`restart`/`status`/`logs` process commands.
- `install.sh` sets up a menu bar status icon by default (shield-with-K, dims when stopped) and builds a `~/Applications/FokusKeeper.app` login launcher that runs it; falls back to a headless daemon if the menu bar's one dependency (`rumps`) can't install. Optional Desktop control panel; `uninstall.sh` with `--purge`.
- Automatic migration of legacy `~/.slack-gatekeeper-*.json` state and history files (copied, originals kept).
- Everything stays on the machine: state, history, config, and logs in the home directory with `chmod 600`, no telemetry.
