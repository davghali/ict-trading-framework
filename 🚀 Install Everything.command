#!/usr/bin/env bash
# Double-clique ce fichier pour tout installer.

cd "$(dirname "$0")"

# Install + autostart
bash setup.sh
echo ""
echo "Installing autostart services..."
bash scripts/install_autostart.sh

echo ""
echo "╔═══════════════════════════════════════════════════════════════════╗"
echo "║  ✅ TON OUTIL EST PRÊT                                           ║"
echo "╚═══════════════════════════════════════════════════════════════════╝"
echo ""
echo "Services actifs 24/7 :"
echo "  ✓ Dashboard web"
echo "  ✓ Tunnel public (URL internet)"
echo "  ✓ Daemon scanner + alertes"
echo ""
echo "Tes raccourcis :"
echo "  📌 Double-clique '🌐 Open Dashboard.command' pour ouvrir ton site"
echo "  📌 Double-clique '📋 Copy Public URL.command' pour copier l'URL"
echo ""
echo "L'URL publique apparaîtra dans 15-30 secondes."
echo ""
read -p "Appuie sur Enter pour fermer cette fenêtre..."
