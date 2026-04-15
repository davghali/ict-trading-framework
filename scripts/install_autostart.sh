#!/usr/bin/env bash
# install_autostart.sh — installe les LaunchAgents macOS pour tout faire tourner 24/7.
# Auto-start au login de ton Mac. Auto-restart si crash. Logs dans reports/logs/.

set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PYBIN="$(which python3)"
LAUNCH="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH"
mkdir -p "$ROOT/reports/logs"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  📡 INSTALL AUTOSTART — Dashboard + Tunnel + Daemon           ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Root   : $ROOT"
echo "  Python : $PYBIN"
echo ""

# ───────────────────────────────────────────────
# LaunchAgent 1 : Dashboard Streamlit
# ───────────────────────────────────────────────
cat > "$LAUNCH/com.ictframework.dashboard.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ictframework.dashboard</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYBIN</string>
    <string>-m</string>
    <string>streamlit</string>
    <string>run</string>
    <string>$ROOT/dashboard.py</string>
    <string>--server.address=0.0.0.0</string>
    <string>--server.port=8501</string>
    <string>--server.headless=true</string>
    <string>--browser.gatherUsageStats=false</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StandardOutPath</key><string>$ROOT/reports/logs/dashboard.log</string>
  <key>StandardErrorPath</key><string>$ROOT/reports/logs/dashboard.err</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
  </dict>
</dict>
</plist>
EOF
echo "  ✓ Dashboard plist écrit"

# ───────────────────────────────────────────────
# LaunchAgent 2 : Tunnel Cloudflare (URL publique)
# ───────────────────────────────────────────────
cat > "$LAUNCH/com.ictframework.tunnel.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ictframework.tunnel</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ROOT/scripts/tunnel_wrapper.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StandardOutPath</key><string>$ROOT/reports/logs/tunnel_out.log</string>
  <key>StandardErrorPath</key><string>$ROOT/reports/logs/tunnel_err.log</string>
  <key>ThrottleInterval</key><integer>15</integer>
</dict>
</plist>
EOF
echo "  ✓ Tunnel plist écrit"

# ───────────────────────────────────────────────
# LaunchAgent 3 : Daemon scanner (alertes 24/7)
# ───────────────────────────────────────────────
cat > "$LAUNCH/com.ictframework.daemon.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ictframework.daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYBIN</string>
    <string>$ROOT/run_daemon.py</string>
    <string>--interval</string><string>15</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StandardOutPath</key><string>$ROOT/reports/logs/daemon.log</string>
  <key>StandardErrorPath</key><string>$ROOT/reports/logs/daemon.err</string>
</dict>
</plist>
EOF
echo "  ✓ Daemon plist écrit"

# ───────────────────────────────────────────────
# Load (unload + load pour idempotence)
# ───────────────────────────────────────────────
echo ""
echo "  ⏳ Chargement des services..."
launchctl unload "$LAUNCH/com.ictframework.dashboard.plist" 2>/dev/null || true
launchctl unload "$LAUNCH/com.ictframework.tunnel.plist" 2>/dev/null || true
launchctl unload "$LAUNCH/com.ictframework.daemon.plist" 2>/dev/null || true

launchctl load  "$LAUNCH/com.ictframework.dashboard.plist"
launchctl load  "$LAUNCH/com.ictframework.tunnel.plist"
launchctl load  "$LAUNCH/com.ictframework.daemon.plist"

echo ""
echo "  ✅ 3 services lancés et auto-start activé"
echo ""
echo "  Services actifs :"
launchctl list | grep ictframework | awk '{print "    • "$3}'

echo ""
echo "  📍 Dashboard      : http://localhost:8501"
echo "  📍 LAN (phone)    : http://$(ipconfig getifaddr en0 2>/dev/null || echo 192.168.1.40):8501"
echo "  📍 URL publique   : apparaît dans 10-20s (./ict url pour voir)"
echo ""
echo "  💡 Prochaines étapes :"
echo "     • Tape : ./ict url           # Voir l'URL publique"
echo "     • Double-clique : 'Open Dashboard.command'"
echo "     • Logs : reports/logs/"
echo ""
