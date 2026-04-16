#!/usr/bin/env bash
# install_supervisor.sh — installe le supervisor (recap/health/trade_manager) 24/7
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PYBIN="$(which python3)"
LAUNCH="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH"
mkdir -p "$ROOT/reports/logs"

cat > "$LAUNCH/com.ictframework.supervisor.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ictframework.supervisor</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYBIN</string>
    <string>$ROOT/run_supervisor.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StandardOutPath</key><string>$ROOT/reports/logs/supervisor.log</string>
  <key>StandardErrorPath</key><string>$ROOT/reports/logs/supervisor.err</string>
  <key>ThrottleInterval</key><integer>30</integer>
</dict>
</plist>
EOF

launchctl unload "$LAUNCH/com.ictframework.supervisor.plist" 2>/dev/null || true
launchctl load "$LAUNCH/com.ictframework.supervisor.plist"
echo "✓ Supervisor LaunchAgent installed and running"
launchctl list | grep ictframework | awk '{print "  • "$3}'
