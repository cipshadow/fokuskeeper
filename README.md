# FokusKeeper

A macOS distraction gate. Opening Slack, YouTube, or eight other time sinks costs you one deliberate click first.

![FokusKeeper dialog](docs/dialog.png)

## What it does

FokusKeeper watches your frontmost app. When you open a gated app or switch a Chrome tab to a gated site, it blocks the surface (quits the app, or parks the tab at `about:blank`) and shows a dialog with today's numbers: opens, blocks, time rescued, and a motivation line.

Two buttons:

- **Stay focused** (default): the app stays quit or the tab closes, and your prevented-distraction count goes up.
- **I have a reason**: the app relaunches or the tab restores to its exact URL, and you get a 3-minute cooldown with no further prompts.

That is the whole product. It is a speed bump, not a wall. Most distraction checks are reflexes; making the reflex cost one conscious decision is enough to kill a large share of them, and the dialog shows you the running score.

## Download

[**Download FokusKeeper**](https://github.com/cipshadow/fokuskeeper/releases/latest/download/FokusKeeper-Install.zip)

Unzip it, then double-click `FokusKeeper-Install.command`. A Terminal window opens itself, downloads the app, and installs it -- no typing required. macOS may show a one-time security prompt since this isn't a signed app; if double-clicking doesn't open it, right-click the file and choose Open instead.

Prefer git? See [Manual install](#install) below.

## Targets

| Target | App | Web (Chrome) |
|---|---|---|
| Slack | Slack | app.slack.com |
| Gmail | - | mail.google.com |
| WhatsApp | WhatsApp | web.whatsapp.com |
| Instagram | - | instagram.com |
| Facebook | - | facebook.com |
| Reddit | - | reddit.com |
| YouTube | - | youtube.com |
| X | - | x.com, twitter.com |
| TikTok | - | tiktok.com |
| LinkedIn | - | linkedin.com |

You pick which of these to gate at first run; all ten are pre-selected.

## How it works

A Python daemon (`fokuskeeper.py`, stdlib only) polls the frontmost application every 0.5 seconds via `osascript`. When Chrome is frontmost it also reads the active tab's URL. Detection is edge-triggered: a target prompts when you switch to it, not continuously while you stay on it.

On each detected open, the gate decides in strict precedence order:

1. **Cooldown**: within 3 minutes of a grant, allow silently.
2. **First open of the day**: auto-allow (you get one free check).
3. **Quiet period**: no use of that target in 60+ minutes, auto-allow.
4. **Prompt**: block the surface and show the dialog.

Cooldowns are shared per target across surfaces: allowing the Slack app also covers app.slack.com in Chrome for the same 3 minutes. The cooldown clock is fixed at the moment of the grant; continued use does not extend it.

## Prerequisites

- macOS 12 or later
- Python 3.9+ (stdlib only for the daemon itself; the system `python3` works). A fresh Mac without developer tools will offer to install the Xcode Command Line Tools the first time you run `python3`; accept that, or `brew install python`.
- Google Chrome, if you want web gating (the app surfaces work without it)
- Internet access during install, to fetch `rumps` for the menu bar icon (see below — the daemon still works fine without it)

## Install

```bash
git clone https://github.com/cipshadow/fokuskeeper.git
cd fokuskeeper
./install.sh
```

The installer checks for `python3`, sets up a menu bar icon (a small `.venv` with `rumps`), builds `~/Applications/FokusKeeper.app` as the login launcher, and starts everything. Add the app to System Settings -> General -> Login Items to start it at login. Pass `--with-control-panel` to also get a `FOKUSKEEPER.command` start/stop/stats panel on your Desktop.

If the menu bar setup can't complete (no network, or no build tools for one of its dependencies), install continues anyway with a plain headless daemon — no menu bar icon, but gating still works fully. Retry the menu bar setup any time with `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && ./start-menubar.sh`, then re-run `./install.sh` to regenerate the login launcher so it picks it up automatically.

On first run a native chooser lists all ten targets, pre-selected; deselect any you want ungated. Your choice is saved to `~/.fokuskeeper-config.json`.

### Permissions

macOS asks for **Automation** permission the first time FokusKeeper talks to System Events (frontmost-app polling) and to Google Chrome (tab reading). Click Allow on both.

Grants are **per launching app**: the daemon started from your terminal and the daemon started by FokusKeeper.app each need their own grant. If web gating stops silently after you switch how the daemon starts, run `./fokuskeeper logs` and look for the `WARNING: cannot read Chrome tabs` line, then re-grant Automation for Google Chrome to the launching app in System Settings -> Privacy & Security -> Automation.

## Usage

```bash
./fokuskeeper start      # start the daemon
./fokuskeeper stop       # stop it
./fokuskeeper restart    # stop + start
./fokuskeeper status     # daemon liveness plus today's stats
./fokuskeeper logs       # last 20 log lines
./fokuskeeper stats      # today's per-target numbers
./fokuskeeper history    # last 7 days, grouped by date
./fokuskeeper report     # all-time totals
./fokuskeeper reset      # zero today's counters (cooldowns survive)
./fokuskeeper setup      # re-run the target chooser
```

Sample `stats` output:

```
FokusKeeper - Today's stats (2026-08-30)
  Slack: opens 3, blocked 2, cooldown none
  Gmail: opens 1, blocked 0, cooldown 2m left
  ...
  Total opens: 4
  Total blocked: 2
```

## Customization

- **Targets**: `./fokuskeeper setup` reopens the chooser. Changes apply live; the daemon watches the config file's mtime, no restart needed.
- **Timing**: edit `COOLDOWN_MINUTES` (default 3) and `QUIET_PERIOD_MINUTES` (default 60) at the top of `fokuskeeper.py`, then restart the daemon. Deliberate v1 choice: these live in code, not a config file.
- **Menu bar icon**: installed by default (see Install above). A shield-with-K icon shows daemon state; click it to start/stop. To start it manually without logging out and back in, run `./start-menubar.sh` — it prefers the repo's `.venv` automatically and starts the daemon itself if it isn't already running.

## Uninstall

```bash
./uninstall.sh           # stop everything, remove the launcher app and Desktop panel
./uninstall.sh --purge   # also delete state, history, config, and logs
```

`--purge` also removes leftover files from the legacy naming (`~/.slack-gatekeeper-state.json` and friends). Removing the Login Items entry is a manual step; the script tells you where.

## FAQ

**Which browsers are gated?**
Google Chrome only. Safari, Arc, and Firefox are not supported yet. Native app gating (Slack, WhatsApp) works regardless of browser.

**Why only app.slack.com and not all of slack.com?**
Matching all of slack.com would also gate sign-in and marketing pages, and the sign-in flow would get you prompted twice on the way into the app. The hostname match is deliberate.

**I opened two distractions at once and only got one dialog.**
While a dialog is up the poll loop is paused, so a second target opened meanwhile is missed. It gets caught on its next focus change.

**Where does my data go?**
Nowhere. State, history, and config live in your home directory (`~/.fokuskeeper-state.json`, `~/.fokuskeeper-history.json`, `~/.fokuskeeper-config.json`), the log in `~/Library/Logs/fokuskeeper.log`, all with `chmod 600`. No telemetry, no network calls.

**Can I bypass it?**
Yes, trivially: stop the daemon, or click the allow button. FokusKeeper is a mindfulness speed bump for yourself, not parental controls. If you can bypass it without noticing you did, that is the moment it was built for.

**What does 0.5-second polling cost?**
One short `osascript` call per tick (two while Chrome is frontmost). CPU use is negligible on any modern Mac.

**What happens if I press Return while the dialog is focused?**
"Stay focused" is the default button, so Return blocks. Reflex-smashing the keyboard lands on the safe side; allowing requires clicking the other button.

**I upgraded from the old version. Where are my stats?**
Legacy `~/.slack-gatekeeper-*.json` files are copied to the new names automatically on first run; the originals stay in place as rollback.

## License

MIT. See [LICENSE](LICENSE).
