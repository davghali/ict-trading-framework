#!/usr/bin/env bash
# install_cyborg.sh — installe le CYBORG comme LaunchAgent macOS 24/7
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PYBIN="$(which python3)"
LAUNCH="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH"
mkdir -p "$ROOT/reports/logs"

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║  🔴 ICT CYBORG — INSTALLATION AUTO-START 24/7            ║"
echo "╚═══════════════════════════════════════════════════════════╝"

cat > "$LAUNCH/com.ictframework.cyborg.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ictframework.cyborg</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYBIN</string>
    <string>$ROOT/run_cyborg.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StandardOutPath</key><string>$ROOT/reports/logs/cyborg.log</string>
  <key>StandardErrorPath</key><string>$ROOT/reports/logs/cyborg.err</string>
  <key>ThrottleInterval</key><integer>30</integer>
</dict>
</plist>
EOF

echo "  ✓ Plist écrit"
launchctl unload "$LAUNCH/com.ictframework.cyborg.plist" 2>/dev/null || true
launchctl load "$LAUNCH/com.ictframework.cyborg.plist"
echo "  ✓ Cyborg daemon lancé + auto-start activé"

# Stop the old daemon (it's replaced by cyborg)
launchctl unload "$HOME/Library/LaunchAgents/com.ictframework.daemon.plist" 2>/dev/null || true

sleep 3
echo ""
echo "  Services actifs :"
launchctl list | grep ictframework | awk '{print "    • "$3}'
echo ""
echo "  Logs : reports/logs/cyborg.log"
echo ""
echo "  ✅ LE CYBORG TOURNE 24/7 — tu vas recevoir les signaux sur Telegram"
