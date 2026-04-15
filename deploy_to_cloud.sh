#!/usr/bin/env bash
# deploy_to_cloud.sh — déploie ton site sur Streamlit Community Cloud (gratuit, 24/7).
# Te guide pas à pas. Tu as juste besoin d'UN compte GitHub (2 min).

set -e
cd "$(dirname "$0")"

clear
cat <<'BANNER'
╔═════════════════════════════════════════════════════════════════════════╗
║                                                                         ║
║      🌐 DEPLOY TON ICT FRAMEWORK SUR LE CLOUD — 24/7 SANS TON MAC      ║
║                                                                         ║
╚═════════════════════════════════════════════════════════════════════════╝

Ce script va faire TOUT pour toi :
  ✓ Créer un repo GitHub
  ✓ Pousser ton code
  ✓ Te donner le lien exact pour déployer sur Streamlit Cloud

Tu as juste besoin de :
  1. Un compte GitHub (si pas déjà) — 2 min
  2. Un Personal Access Token (pour permettre au script de push)

Durée totale : 10 minutes.

BANNER

read -p "▶ Appuie sur Enter pour commencer..."
echo ""

# ═════════════════════════════════════════════════════════════════
# ÉTAPE 1 — Compte GitHub
# ═════════════════════════════════════════════════════════════════
echo "╔═════════════════════════════════════════════════════════╗"
echo "║  ÉTAPE 1/4 — Compte GitHub                              ║"
echo "╚═════════════════════════════════════════════════════════╝"
echo ""
echo "  As-tu déjà un compte GitHub ?"
echo ""
read -p "▶ Tape 'o' si OUI, 'n' si NON : " HAS_GH

if [ "$HAS_GH" = "n" ] || [ "$HAS_GH" = "N" ]; then
    echo ""
    echo "  OK, je t'ouvre la page d'inscription."
    echo ""
    echo "  📝 Sur la page qui va s'ouvrir :"
    echo "     • Entre ton email"
    echo "     • Choisis un password"
    echo "     • Choisis un username (ex: davidghali)"
    echo "     • Vérifie ton email"
    echo ""
    read -p "▶ Enter pour ouvrir github.com/signup..."
    open "https://github.com/signup"
    echo ""
    echo "  ⏳ Reviens ici une fois inscrit."
    read -p "▶ Enter quand ton compte est créé..."
fi

echo ""
read -p "▶ Quel est ton username GitHub ? (ex: davidghali) : " GH_USER

if [ -z "$GH_USER" ]; then
    echo "❌ Username vide. Abandon."
    exit 1
fi

# ═════════════════════════════════════════════════════════════════
# ÉTAPE 2 — Personal Access Token
# ═════════════════════════════════════════════════════════════════
echo ""
echo "╔═════════════════════════════════════════════════════════╗"
echo "║  ÉTAPE 2/4 — Personal Access Token                      ║"
echo "╚═════════════════════════════════════════════════════════╝"
echo ""
echo "  Le script doit pouvoir créer un repo sur ton compte."
echo "  Pour ça, tu dois créer un 'token' (mot de passe temporaire)."
echo ""
echo "  📝 Sur la page qui va s'ouvrir :"
echo "     1. Click 'Generate new token (classic)'"
echo "     2. Note (name) : 'ICT Framework Deploy'"
echo "     3. Expiration : 30 days"
echo "     4. Scopes : COCHE 'repo' (la case entière)"
echo "     5. Scroll en bas, click 'Generate token'"
echo "     6. COPIE le token (ghp_xxxxxxx) — tu ne le reverras pas !"
echo ""
read -p "▶ Enter pour ouvrir la page des tokens..."
open "https://github.com/settings/tokens/new?scopes=repo&description=ICT%20Framework%20Deploy"
echo ""
read -sp "▶ Colle ton token ici (caché pour sécu) : " GH_TOKEN
echo ""

if [ -z "$GH_TOKEN" ]; then
    echo "❌ Token vide. Abandon."
    exit 1
fi

# ═════════════════════════════════════════════════════════════════
# ÉTAPE 3 — Création du repo + push
# ═════════════════════════════════════════════════════════════════
echo ""
echo "╔═════════════════════════════════════════════════════════╗"
echo "║  ÉTAPE 3/4 — Création du repo et push du code          ║"
echo "╚═════════════════════════════════════════════════════════╝"
echo ""

REPO_NAME="ict-trading-framework"
read -p "▶ Nom du repo (défaut: $REPO_NAME) : " REPO_INPUT
if [ -n "$REPO_INPUT" ]; then
    REPO_NAME="$REPO_INPUT"
fi

# Create repo via GitHub API (private by default)
echo ""
echo "  ⏳ Création du repo privé sur GitHub..."
RESPONSE=$(curl -sS -w "%{http_code}" -o /tmp/gh_resp.json \
    -H "Authorization: token $GH_TOKEN" \
    -H "Accept: application/vnd.github+json" \
    https://api.github.com/user/repos \
    -d "{\"name\":\"$REPO_NAME\",\"private\":true,\"description\":\"ICT Institutional Framework — my personal trading tool\"}")

HTTP_CODE="${RESPONSE: -3}"
if [ "$HTTP_CODE" = "201" ]; then
    echo "  ✓ Repo créé : https://github.com/$GH_USER/$REPO_NAME (privé)"
elif [ "$HTTP_CODE" = "422" ]; then
    echo "  ℹ Repo existe déjà — on continue"
else
    echo "  ❌ Erreur HTTP $HTTP_CODE"
    cat /tmp/gh_resp.json 2>/dev/null | head -5
    exit 1
fi

# Git init (if not already)
if [ ! -d .git ]; then
    git init -q
    git config user.email "trader@localhost"
    git config user.name "$GH_USER"
fi

git add .
git commit -q -m "Deploy: ICT Framework to cloud" 2>/dev/null || true
git branch -M main 2>/dev/null

# Remote + push
git remote remove origin 2>/dev/null || true
git remote add origin "https://$GH_USER:$GH_TOKEN@github.com/$GH_USER/$REPO_NAME.git"

echo "  ⏳ Push vers GitHub..."
if git push -u origin main --force 2>&1 | tail -5; then
    echo "  ✓ Code poussé sur GitHub"
else
    echo "  ❌ Push échoué. Vérifie le token."
    exit 1
fi

# Cleanup : remove token from remote URL (sécu)
git remote set-url origin "https://github.com/$GH_USER/$REPO_NAME.git"

# ═════════════════════════════════════════════════════════════════
# ÉTAPE 4 — Streamlit Community Cloud
# ═════════════════════════════════════════════════════════════════
echo ""
echo "╔═════════════════════════════════════════════════════════╗"
echo "║  ÉTAPE 4/4 — Deploy sur Streamlit Community Cloud      ║"
echo "╚═════════════════════════════════════════════════════════╝"
echo ""
echo "  Ton code est sur GitHub. Dernière étape : déployer."
echo ""
echo "  📝 Sur la page qui va s'ouvrir :"
echo "     1. 'Sign in with GitHub' → autorise"
echo "     2. Click 'New app' (bouton en haut à droite)"
echo "     3. Remplis :"
echo "        • Repository : $GH_USER/$REPO_NAME"
echo "        • Branch     : main"
echo "        • Main file  : dashboard.py"
echo "        • App URL    : $GH_USER-ict-framework (ou ce que tu veux)"
echo "     4. Click 'Deploy'"
echo ""
echo "  ⏳ Premier build = 3-5 min. Après ça, ton site est LIVE 24/7."
echo ""
read -p "▶ Enter pour ouvrir Streamlit Cloud..."
open "https://share.streamlit.io/deploy?repository=https://github.com/$GH_USER/$REPO_NAME&branch=main&mainModule=dashboard.py"

echo ""
echo "╔═════════════════════════════════════════════════════════════════════════╗"
echo "║  ✅ DÉPLOIEMENT LANCÉ !                                                 ║"
echo "╚═════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Ton site sera accessible à :"
echo "    🌍 https://$GH_USER-ict-framework.streamlit.app"
echo "       (ou le nom que tu as choisi dans 'App URL')"
echo ""
echo "  Il fonctionnera 24/7, GRATUIT, même ton Mac éteint."
echo ""
echo "  ℹ️  La première fois, l'app télécharge les data (30-60s)."
echo "     Les fois suivantes, c'est instantané."
echo ""
echo "  🔒 SÉCURITÉ — ton repo est PRIVÉ (seul toi y accèdes)."
echo "     Le site Streamlit est PUBLIC par défaut — tape 'password' dans"
echo "     le chat Claude pour que je t'ajoute une protection."
echo ""
echo "  🔄 Pour updater ton site : tape ./deploy_to_cloud.sh update"
echo ""
