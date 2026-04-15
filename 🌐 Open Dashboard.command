#!/usr/bin/env bash
# Double-clique — ouvre ton site ICT Framework (URL publique).

cd "$(dirname "$0")"

URL_FILE="user_data/public_url.txt"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🔴 ICT FRAMEWORK"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. Make sure services are running
SERVICES=$(launchctl list | grep ictframework | wc -l | tr -d ' ')
if [ "$SERVICES" -lt 3 ]; then
    echo "⚙️  Démarrage des services..."
    bash scripts/install_autostart.sh > /dev/null 2>&1
    sleep 10
fi

# 2. Wait for URL file
echo "⏳  Récupération de l'URL publique..."
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    if [ -f "$URL_FILE" ] && [ -s "$URL_FILE" ]; then
        break
    fi
    sleep 2
done

if [ ! -f "$URL_FILE" ] || [ ! -s "$URL_FILE" ]; then
    echo "❌ URL pas encore disponible."
    echo "   Relance ce fichier dans 30 secondes."
    read -p "Enter pour fermer..."
    exit 1
fi

URL=$(cat "$URL_FILE" | tr -d '\n')

# 3. Copy + notify + open
echo -n "$URL" | pbcopy
osascript -e "display notification \"URL copiée\" with title \"ICT Framework\" sound name \"Glass\"" 2>/dev/null

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🌍  $URL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  ✓ URL copiée dans ton clipboard"
echo "  ✓ Ouverture dans le navigateur..."
echo ""

open "$URL"

echo "  ℹ️  Cette URL fonctionne DEPUIS PARTOUT :"
echo "     • Ton téléphone 4G"
echo "     • N'importe quel ordi"
echo "     • Partage à qui tu veux"
echo ""

sleep 3
