#!/bin/bash
# Manual start for the FokusKeeper menu bar status icon. No launchd/login
# item registered. Backgrounds with nohup + disown so closing the Terminal
# window doesn't kill it.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

LOG_FILE="$HOME/Library/Logs/fokuskeeper-menubar.log"
mkdir -p "$(dirname "$LOG_FILE")"

if [ -x "$DIR/.venv/bin/python3" ]; then
  PY="$DIR/.venv/bin/python3"
else
  PY="/usr/bin/python3"
fi

if pgrep -f -u "$(id -u)" 'python.*fokuskeeper_menubar.py' >/dev/null 2>&1; then
  echo "FokusKeeper menu bar icon is already running."
  exit 0
fi

echo "Starting FokusKeeper menu bar icon ..."
nohup "$PY" "$DIR/fokuskeeper_menubar.py" >>"$LOG_FILE" 2>&1 &
disown

sleep 1
if pgrep -f -u "$(id -u)" 'python.*fokuskeeper_menubar.py' >/dev/null 2>&1; then
  echo "Running. Look for the shield icon in your menu bar."
  echo "Log: $LOG_FILE"
else
  echo "It exited immediately — check the log for why:" >&2
  echo "  tail -20 $LOG_FILE" >&2
  exit 1
fi
