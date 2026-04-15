#!/usr/bin/env bash
# deploy-cloud.sh — te guide pas à pas pour avoir ton site INDÉPENDANT public.
# Usage : bash deploy-cloud.sh

set -e
cd "$(dirname "$0")"

echo "╔═══════════════════════════════════════════════════════════════════════╗"
echo "║  🌐 ICT FRAMEWORK — DÉPLOIEMENT SITE STANDALONE CLOUD                ║"
echo "╚═══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Ce script te guide pour avoir TON site avec URL PUBLIQUE permanente"
echo "24/7, gratuit, indépendant de hiddennova-ict.fr."
echo ""
echo "Durée : 10 minutes."
echo ""
read -p "▶ Prêt à commencer ? (Enter) "

# ─────────────────────────────────────────────
# ÉTAPE 1 — Git
# ─────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  ÉTAPE 1/4 — Git repository local"
echo "══════════════════════════════════════════════════════════════════"
echo ""

if [ ! -d .git ]; then
    echo "Initialisation git..."
    git init -q
    git config user.email "trader@localhost"
    git config user.name "ICT Framework"
    git add .
    git commit -q -m "Initial commit: ICT Institutional Framework"
    git branch -M main
    echo "✓ Repo git initialisé"
else
    echo "✓ Repo git déjà initialisé"
    # Ensure we have a commit
    if [ -z "$(git log --oneline 2>/dev/null)" ]; then
        git add .
        git commit -q -m "Initial commit" || true
    fi
fi

# ─────────────────────────────────────────────
# ÉTAPE 2 — GitHub
# ─────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  ÉTAPE 2/4 — Créer ton repo GitHub (si pas fait)"
echo "══════════════════════════════════════════════════════════════════"
echo ""
echo "  1. Va sur : https://github.com/new"
echo "  2. Repository name : ict-quant  (ou ce que tu veux)"
echo "  3. Visibilité : Private (recommandé)"
echo "  4. NE COCHE PAS 'Initialize with README'"
echo "  5. Create repository"
echo ""
read -p "▶ Coller ci-dessous l'URL du repo (ex: https://github.com/davidghali/ict-quant.git) : " REPO_URL

if [ -z "$REPO_URL" ]; then
    echo "❌ URL vide. Abandon."
    exit 1
fi

# Configure remote
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO_URL"
echo "✓ Remote configuré : $REPO_URL"

# ─────────────────────────────────────────────
# ÉTAPE 3 — Push
# ─────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  ÉTAPE 3/4 — Push vers GitHub"
echo "══════════════════════════════════════════════════════════════════"
echo ""
echo "  ℹ Si Git te demande un password : utilise un Personal Access Token"
echo "    → https://github.com/settings/tokens"
echo "    → Generate new token (classic) → scope 'repo' → copy"
echo ""
read -p "▶ Prêt à push ? (Enter) "

if git push -u origin main; then
    echo "✓ Code poussé sur GitHub"
else
    echo ""
    echo "❌ Push échoué. Vérifications :"
    echo "   - URL correcte ?"
    echo "   - Personal Access Token valide ?"
    echo "   - Repo existe sur GitHub ?"
    exit 1
fi

# ─────────────────────────────────────────────
# ÉTAPE 4 — Deploy sur Streamlit Cloud
# ─────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "  ÉTAPE 4/4 — Deploy sur Streamlit Community Cloud"
echo "══════════════════════════════════════════════════════════════════"
echo ""
echo "  1. Ouvre : https://share.streamlit.io"
echo "  2. Sign in with GitHub (autorise Streamlit)"
echo "  3. Click 'New app'"
echo "  4. Repository : ton repo fraîchement poussé"
echo "  5. Branch : main"
echo "  6. Main file path : dashboard.py"
echo "  7. App URL : choisis un nom (ex: ict-quant-david)"
echo "  8. Click 'Deploy'"
echo ""
echo "  ⏳ Le premier build prend 3-5 min (télécharge les deps)."
echo ""
echo "  🎯 Ton URL finale : https://<TON-CHOIX>.streamlit.app"
echo ""

# Try to open Streamlit Cloud
if command -v open >/dev/null 2>&1; then
    read -p "▶ Ouvrir share.streamlit.io dans le browser ? (y/N) " OPEN
    if [ "$OPEN" = "y" ] || [ "$OPEN" = "Y" ]; then
        open "https://share.streamlit.io"
    fi
fi

# ─────────────────────────────────────────────
# Fin
# ─────────────────────────────────────────────
echo ""
echo "╔═══════════════════════════════════════════════════════════════════════╗"
echo "║  ✅ DÉPLOIEMENT TERMINÉ                                              ║"
echo "╚═══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "  📍 Ton site indépendant : https://<TON-CHOIX>.streamlit.app"
echo "     (l'URL apparaît sur share.streamlit.io une fois déployé)"
echo ""
echo "  🔄 Mises à jour : git push → auto-deploy"
echo "  🔒 Sécurité : ajoute un password dans dashboard.py (voir docs/SITE_STANDALONE.md)"
echo "  🌍 Custom domain : achète ict-quant.fr sur OVH, deploy sur Render + CNAME"
echo ""
echo "  📚 Doc : docs/SITE_STANDALONE.md"
echo ""
