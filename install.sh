#!/bin/bash
# FokusKeeper - Installation Script
# Usage: ./install.sh [--with-control-panel]

set -e

echo "FokusKeeper - Installation"
echo "=========================="
echo ""

# Guard: python3 must exist
if ! command -v python3 > /dev/null 2>&1; then
    echo "python3 was not found on this machine."
    echo "Install the Xcode Command Line Tools (run: xcode-select --install)"
    echo "or install Python via Homebrew (brew install python)."
    exit 1
fi

# Detect installation directory
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "Installation directory: $INSTALL_DIR"
echo ""

# Shell-escaped form of INSTALL_DIR for safe interpolation into generated
# launcher scripts below. %q produces output that is already quoted for
# reuse as shell input, so it must be used UNQUOTED wherever it appears.
Q_DIR=$(printf '%q' "$INSTALL_DIR")

# Step 1: Make scripts executable
echo "[1/6] Making scripts executable..."
chmod +x "$INSTALL_DIR/fokuskeeper.py"
chmod +x "$INSTALL_DIR/fokuskeeper"
chmod +x "$INSTALL_DIR/start-menubar.sh"
echo "      Done."
echo ""

# Step 2: Set up the menu bar icon (rumps, in the repo's own venv). This is
# the default experience now, not an opt-in extra -- but it must never take
# down the actual gating feature if it fails (no network, no build tools for
# pyobjc's native extension on this Python), so failures here are warnings,
# not aborts: `set -e` is suspended for this block and MENUBAR_READY records
# the outcome for the steps below.
echo "[2/6] Setting up the menu bar icon..."
MENUBAR_READY=0
set +e
if [ ! -x "$INSTALL_DIR/.venv/bin/python3" ]; then
    python3 -m venv "$INSTALL_DIR/.venv" > /dev/null 2>&1
fi
if [ -x "$INSTALL_DIR/.venv/bin/python3" ] && \
   "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt" > /dev/null 2>&1; then
    MENUBAR_READY=1
    echo "      Done."
else
    echo "      Could not set up the menu bar icon (no network, or no build"
    echo "      tools for one of its dependencies) -- continuing without it."
    echo "      FokusKeeper will still run and gate normally; retry with:"
    echo "        python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
fi
set -e
echo ""

# Now that the venv (if any) exists, resolve $PY once for the rest of this
# script -- the chooser and the final start both prefer it for consistency
# with whatever the daemon/menu bar will actually run under.
if [ -x "$INSTALL_DIR/.venv/bin/python3" ]; then
    PY="$INSTALL_DIR/.venv/bin/python3"
else
    PY="python3"
fi

# Step 3: Create login launcher app. Runs the menu bar app when step 2
# succeeded (it starts the daemon itself on launch); falls back to the
# daemon directly, headless, when it didn't.
echo "[3/6] Creating login launcher app..."
APP_PATH="$HOME/Applications/FokusKeeper.app"
mkdir -p "$APP_PATH/Contents/MacOS"

if [ "$MENUBAR_READY" = "1" ]; then
    cat > "$APP_PATH/Contents/MacOS/run" << EOF
#!/bin/bash
cd $Q_DIR
mkdir -p "\$HOME/Library/Logs"
exec "$Q_DIR/.venv/bin/python3" fokuskeeper_menubar.py >> "\$HOME/Library/Logs/fokuskeeper-menubar.log" 2>&1
EOF
else
    cat > "$APP_PATH/Contents/MacOS/run" << EOF
#!/bin/bash
cd $Q_DIR
mkdir -p "\$HOME/Library/Logs"
if [ -x $Q_DIR/.venv/bin/python3 ]; then
    PY=$Q_DIR/.venv/bin/python3
else
    PY="python3"
fi
exec "\$PY" -u fokuskeeper.py run >> "\$HOME/Library/Logs/fokuskeeper-stdout.log" 2>&1
EOF
fi
chmod +x "$APP_PATH/Contents/MacOS/run"

cat > "$APP_PATH/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>run</string>
    <key>CFBundleName</key>
    <string>FokusKeeper</string>
    <key>CFBundleIdentifier</key>
    <string>local.fokuskeeper</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
EOF
echo "      Created: $APP_PATH"
echo ""

# Step 4: Optional Desktop control panel
if [ "$1" = "--with-control-panel" ]; then
    echo "[4/6] Writing Desktop control panel..."
    mkdir -p "$HOME/Desktop"
    cat > "$HOME/Desktop/FOKUSKEEPER.command" << EOF
#!/bin/bash
# FokusKeeper control panel — thin wrapper around the fokuskeeper CLI.
FK=$Q_DIR/fokuskeeper

if pgrep -f -u \$(id -u) 'python.*fokuskeeper.py' > /dev/null; then
    STATUS="ACTIVE"
    ACTION="Stop"
else
    STATUS="STOPPED"
    ACTION="Start"
fi

CHOICE=\$(osascript -e "button returned of (display dialog \"FokusKeeper is \$STATUS\" buttons {\"\$ACTION\", \"Stats\", \"Cancel\"} default button 1)")

case "\$CHOICE" in
    Start) "\$FK" start ;;
    Stop)  "\$FK" stop ;;
    Stats) "\$FK" stats ;;
esac
EOF
    chmod +x "$HOME/Desktop/FOKUSKEEPER.command"
    echo "      Created: ~/Desktop/FOKUSKEEPER.command"
else
    echo "[4/6] Skipping Desktop control panel (pass --with-control-panel to add it)."
fi
echo ""

# Step 5: First-run target chooser (foreground, interactive). The resident
# daemon never shows UI — see cmd_run()'s docstring in fokuskeeper.py — so
# first-run selection happens here instead, while install.sh still has your
# terminal's attention. Skipped if a config already exists (e.g. re-running
# install.sh, or a migrated legacy setup).
CONFIG_FILE="$HOME/.fokuskeeper-config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "[5/6] Choose which distractions to gate..."
    "$PY" "$INSTALL_DIR/fokuskeeper.py" setup
    echo ""
else
    echo "[5/6] Existing target selection found, skipping chooser."
    echo ""
fi

# Step 6: Start it. Prefer the menu bar app (it starts the daemon itself on
# launch, per fokuskeeper_menubar.py) so the default experience has a visible
# icon; fall back to the headless daemon directly when step 2 didn't have a
# working rumps install, or if the menu bar app fails to come up for any
# other reason -- gating must not depend on the menu bar working.
echo "[6/6] Starting FokusKeeper..."
STARTED_MENUBAR=0
if [ "$MENUBAR_READY" = "1" ]; then
    set +e
    "$INSTALL_DIR/start-menubar.sh"
    if [ $? -eq 0 ]; then
        STARTED_MENUBAR=1
    fi
    set -e
fi
if [ "$STARTED_MENUBAR" = "0" ]; then
    "$INSTALL_DIR/fokuskeeper" start
    echo "      Daemon is running (headless)."
fi

echo ""
echo "=================================="
echo "Installation complete"
echo "=================================="
echo ""
echo "NEXT STEPS:"
echo ""
echo "1. Auto-start at login:"
echo "   System Settings -> General -> Login Items -> '+' -> select"
echo "   ~/Applications/FokusKeeper.app"
echo ""
echo "2. Permissions:"
echo "   macOS will ask for Automation permission the first time"
echo "   FokusKeeper interacts with other apps. Click Allow."
echo ""
echo "3. Everyday control:"
echo "   $INSTALL_DIR/fokuskeeper {start|stop|status|stats}"
echo ""
