#!/usr/bin/env bash
# Double-clique pour arrêter tous les services (libère CPU/réseau).

cd "$(dirname "$0")"
bash scripts/uninstall_autostart.sh
echo ""
echo "Tous les services ont été arrêtés."
echo "Pour redémarrer : double-clique '🚀 Install Everything.command'"
echo ""
read -p "Enter pour fermer..."
