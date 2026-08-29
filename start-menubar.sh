#!/bin/bash
# Manual start for the Gatekeeper menu bar status icon. No launchd/login
# item registered. Backgrounds with nohup + disown so closing the Terminal
# window doesn't kill it.
set -euo pipefail
cd "$(dirname "$0")"

LOG_FILE="$HOME/Library/Logs/gatekeeper-menubar.log"

if pgrep -f gatekeeper_menubar.py >/dev/null 2>&1; then
  echo "Gatekeeper menu bar icon is already running."
  exit 0
fi

echo "Starting Gatekeeper menu bar icon ..."
nohup /usr/bin/python3 "$(pwd)/gatekeeper_menubar.py" >>"$LOG_FILE" 2>&1 &
disown

sleep 1
if pgrep -f gatekeeper_menubar.py >/dev/null 2>&1; then
  echo "Running. Look for the shield icon in your menu bar."
  echo "Log: $LOG_FILE"
else
  echo "It exited immediately — check the log for why:" >&2
  echo "  tail -20 $LOG_FILE" >&2
  exit 1
fi
