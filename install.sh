#!/bin/bash
# Slack Gatekeeper - Installation Script
# Run this after syncing to a new machine

set -e  # Exit on error

echo "🚪 Distraction Gatekeeper - Installation"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Detect installation directory
INSTALL_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo "📁 Installation directory: $INSTALL_DIR"
echo ""

# Step 1: Make scripts executable
echo "1️⃣  Making scripts executable..."
chmod +x "$INSTALL_DIR/slack_gatekeeper.py"
chmod +x "$INSTALL_DIR/gatekeeper"
echo "   ✅ Scripts are executable"
echo ""

# Step 2: Create auto-start app
echo "2️⃣  Creating auto-start app..."
APP_PATH="$HOME/Applications/StartGatekeeper.app"
mkdir -p "$APP_PATH/Contents/MacOS"

# Create startup script
cat > "$APP_PATH/Contents/MacOS/run" << EOF
#!/bin/bash
cd "$INSTALL_DIR"
python3 slack_gatekeeper.py > ~/Library/Logs/gatekeeper.log 2>&1 &

EOF

chmod +x "$APP_PATH/Contents/MacOS/run"

# Create Info.plist
cat > "$APP_PATH/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>run</string>
    <key>CFBundleName</key>
    <string>StartGatekeeper</string>
    <key>CFBundleIdentifier</key>
    <string>local.startgatekeeper</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
EOF

echo "   ✅ Created: $APP_PATH"
echo ""

# Step 3: Copy control panel to Desktop
echo "3️⃣  Setting up Desktop control panel..."
cat > "$HOME/Desktop/GATEKEEPER.command" << EOF
#!/bin/bash
# Distraction Gatekeeper Control Panel (Slack + Gmail)

cd "$INSTALL_DIR"

# Check if running
is_running() {
    pgrep -f slack_gatekeeper.py > /dev/null
}

# Get counts
get_counts() {
    python3 << 'PYEOF'
import json
import os
from datetime import datetime
try:
    with open(os.path.expanduser('~/.slack-gatekeeper-state.json'), 'r') as f:
        state = json.load(f)
    today = datetime.now().strftime('%Y-%m-%d')
    if state.get('stats_date') == today:
        slack_opens = state.get('slack_opens', 0)
        gmail_opens = state.get('gmail_opens', 0)
        prevented = state.get('distractions_prevented', 0)
        print(f"{slack_opens}|{gmail_opens}|{prevented}")
    else:
        print("0|0|0")
except:
    print("0|0|0")
PYEOF
}

# Show control panel
if is_running; then
    STATUS="🟢 ACTIVE"
    ACTION="⏸ Pause"
else
    STATUS="🔴 STOPPED"
    ACTION="▶ Start"
fi

COUNTS=\$(get_counts)
SLACK_OPENS=\$(echo \$COUNTS | cut -d'|' -f1)
GMAIL_OPENS=\$(echo \$COUNTS | cut -d'|' -f2)
PREVENTED=\$(echo \$COUNTS | cut -d'|' -f3)

CHOICE=\$(osascript << OSASCRIPT
display dialog "━━━━━━━━━━━━━━━━━━━━━━
🚪 DISTRACTION GATEKEEPER
━━━━━━━━━━━━━━━━━━━━━━

\$STATUS

📊 Slack Opens: \$SLACK_OPENS
📧 Gmail Opens: \$GMAIL_OPENS
💪 Distractions Prevented: \$PREVENTED

━━━━━━━━━━━━━━━━━━━━━━" buttons {"\$ACTION", "🔄 Reset"} default button 1
button returned of result
OSASCRIPT
)

case "\$CHOICE" in
    "▶ Start")
        cd "$INSTALL_DIR"
        python3 slack_gatekeeper.py > ~/Library/Logs/gatekeeper.log 2>&1 &
        ;;
    "⏸ Pause")
        pkill -f slack_gatekeeper.py
        ;;
    "🔄 Reset")
        python3 << 'PYEOF'
import json
import os
from datetime import datetime
with open(os.path.expanduser('~/.slack-gatekeeper-state.json'), 'w') as f:
    json.dump({'slack_opens': 0, 'gmail_opens': 0, 'distractions_prevented': 0, 'daily_opens': 0, 'stats_date': datetime.now().strftime('%Y-%m-%d')}, f)
PYEOF
        ;;
esac
EOF

chmod +x "$HOME/Desktop/GATEKEEPER.command"
echo "   ✅ Created: ~/Desktop/GATEKEEPER.command"
echo ""

# Step 4: Test the gatekeeper
echo "4️⃣  Testing the gatekeeper..."
cd "$INSTALL_DIR"
python3 slack_gatekeeper.py > ~/Library/Logs/gatekeeper.log 2>&1 &
sleep 2

if pgrep -f slack_gatekeeper.py > /dev/null; then
    echo "   ✅ Gatekeeper started successfully!"
    ./gatekeeper status
else
    echo "   ❌ Failed to start. Check logs: tail ~/Library/Logs/gatekeeper.log"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Installation Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 NEXT STEPS:"
echo ""
echo "1. Add to Login Items for auto-start:"
echo "   • Open System Settings → General → Login Items"
echo "   • Click '+' button"
echo "   • Select: ~/Applications/StartGatekeeper.app"
echo "   • Click Add"
echo ""
echo "2. Test it:"
echo "   • Try opening Slack"
echo "   • You should see the gatekeeper dialog!"
echo ""
echo "3. Control Panel:"
echo "   • Double-click GATEKEEPER.command on Desktop"
echo "   • Or run: ./gatekeeper status"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

