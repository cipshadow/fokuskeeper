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
echo "[1/4] Making scripts executable..."
chmod +x "$INSTALL_DIR/fokuskeeper.py"
chmod +x "$INSTALL_DIR/fokuskeeper"
chmod +x "$INSTALL_DIR/start-menubar.sh"
echo "      Done."
echo ""

# Step 2: Create auto-start app
echo "[2/4] Creating login launcher app..."
APP_PATH="$HOME/Applications/FokusKeeper.app"
mkdir -p "$APP_PATH/Contents/MacOS"

cat > "$APP_PATH/Contents/MacOS/run" << EOF
#!/bin/bash
cd $Q_DIR
if [ -x $Q_DIR/.venv/bin/python3 ]; then
    PY=$Q_DIR/.venv/bin/python3
else
    PY="python3"
fi
exec "\$PY" fokuskeeper.py run >> "\$HOME/Library/Logs/fokuskeeper-stdout.log" 2>&1
EOF
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

# Step 3: Optional Desktop control panel
if [ "$1" = "--with-control-panel" ]; then
    echo "[3/4] Writing Desktop control panel..."
    cat > "$HOME/Desktop/FOKUSKEEPER.command" << EOF
#!/bin/bash
# FokusKeeper control panel — thin wrapper around the fokuskeeper CLI.
FK=$Q_DIR/fokuskeeper

if pgrep -f 'python.*fokuskeeper.py' > /dev/null; then
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
    echo "[3/4] Skipping Desktop control panel (pass --with-control-panel to add it)."
fi
echo ""

# Step 4: Start the daemon ("fokuskeeper start" verifies and exits 1 on
# failure, which aborts this script via set -e)
echo "[4/4] Starting the daemon..."
"$INSTALL_DIR/fokuskeeper" start
echo "      Daemon is running."

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
