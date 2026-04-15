#!/usr/bin/env bash
# Double-clique — copie l'URL publique dans le clipboard (Cmd+V partout).

cd "$(dirname "$0")"

URL_FILE="user_data/public_url.txt"

# Ensure services running
SERVICES=$(launchctl list | grep ictframework | wc -l | tr -d ' ')
if [ "$SERVICES" -lt 3 ]; then
    bash scripts/install_autostart.sh > /dev/null 2>&1
    sleep 10
fi

# Wait for URL
for i in 1 2 3 4 5 6 7 8 9 10; do
    if [ -f "$URL_FILE" ] && [ -s "$URL_FILE" ]; then break; fi
    sleep 2
done

if [ ! -f "$URL_FILE" ] || [ ! -s "$URL_FILE" ]; then
    echo "❌ URL pas encore prête. Attends 30s et réessaie."
    read -p "Enter..."
    exit 1
fi

URL=$(cat "$URL_FILE" | tr -d '\n')

# Copy + notify
echo -n "$URL" | pbcopy
osascript -e "display notification \"$URL\" with title \"URL copiée ✓\" sound name \"Glass\"" 2>/dev/null

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🌍 TON SITE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "   $URL"
echo ""
echo "  ✓ Copiée (Cmd+V partout)"
echo "  ✓ Envoie-la sur ton téléphone, WhatsApp, SMS..."
echo ""
sleep 2
