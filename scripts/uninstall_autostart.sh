#!/usr/bin/env bash
# uninstall_autostart.sh — retire les 3 LaunchAgents.

set -e
LAUNCH="$HOME/Library/LaunchAgents"

for svc in dashboard tunnel daemon; do
    plist="$LAUNCH/com.ictframework.$svc.plist"
    if [ -f "$plist" ]; then
        launchctl unload "$plist" 2>/dev/null || true
        rm "$plist"
        echo "  ✓ $svc retiré"
    fi
done
echo ""
echo "  ✅ Tous les services autostart ont été désinstallés"
