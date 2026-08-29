#!/bin/bash
# FokusKeeper - Uninstall Script
# Usage: ./uninstall.sh [--purge]
#   --purge also removes state, history, config, and log files
#   (including files from the legacy "slack-gatekeeper" naming).

echo "FokusKeeper - Uninstall"
echo "======================="
echo ""

# Stop daemon and menubar (fine if they aren't running)
pkill -f 'python.*fokuskeeper.py' 2>/dev/null || true
pkill -f 'python.*fokuskeeper_menubar.py' 2>/dev/null || true
echo "Stopped daemon and menu bar (if they were running)."

remove_path() {
    if [ -e "$1" ]; then
        rm -rf "$1"
        echo "Removed: $1"
    fi
}

remove_path "$HOME/Applications/FokusKeeper.app"
remove_path "$HOME/Desktop/FOKUSKEEPER.command"

if [ "$1" = "--purge" ]; then
    echo ""
    echo "Purging data and logs..."
    remove_path "$HOME/.fokuskeeper-state.json"
    remove_path "$HOME/.fokuskeeper-history.json"
    remove_path "$HOME/.fokuskeeper-config.json"
    remove_path "$HOME/Library/Logs/fokuskeeper.log"
    remove_path "$HOME/Library/Logs/fokuskeeper-stdout.log"
    # Legacy files from the old "slack-gatekeeper" naming
    remove_path "$HOME/.slack-gatekeeper-state.json"
    remove_path "$HOME/.slack-gatekeeper-history.json"
    remove_path "$HOME/Library/Logs/slack-gatekeeper.log"
    remove_path "$HOME/Library/Logs/slack-gatekeeper-stdout.log"
    remove_path "$HOME/Library/Logs/gatekeeper.log"
fi

echo ""
echo "Done. One manual step remains:"
echo "Remove FokusKeeper from Login Items yourself:"
echo "  System Settings -> General -> Login Items"
echo "(Scripting Login Items needs extra permissions, so it is not automated.)"
