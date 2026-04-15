# 🌍 DÉPLOIEMENT — TON SITE ACCESSIBLE

## 🎯 3 NIVEAUX D'ACCÈS

| Niveau | URL | Accessible depuis |
|---|---|---|
| 🟢 Local | `http://localhost:8501` | Ton Mac uniquement |
| 🟡 LAN | `http://192.168.1.40:8501` | Tout appareil sur ton Wi-Fi (phone, tablette) |
| 🔴 Public | `https://xxx.trycloudflare.com` | Internet entier (depuis n'importe où) |

---

## ⚡ OPTION 1 — LOCAL + LAN (instantané, 0 setup)

```bash
cd "/Users/davidghali/DAVID DAVID/ict-institutional-framework"
./ict dashboard
```

Tu vois :
```
💻 Mac        : http://localhost:8501
📱 Phone/LAN  : http://192.168.1.40:8501
```

**Sur ton phone** : connecte-toi au MÊME Wi-Fi que ton Mac, ouvre Safari, tape `http://192.168.1.40:8501` → dashboard full sur mobile.

**Avantages** : instantané, zéro coût, zéro dépendance
**Limites** : ton Mac doit être allumé, téléphone sur même Wi-Fi

---

## 🌍 OPTION 2 — URL PUBLIQUE INTERNET (Cloudflare Tunnel — GRATUIT)

**Tu l'as déjà** — `cloudflared` est dans `bin/` (téléchargé auto).

```bash
./ict serve-public
```

Tu vois :
```
https://genes-favorite-material-century.trycloudflare.com
```

**Donne cette URL à n'importe qui** (toi depuis phone 4G, un ami, etc.) — il accède au dashboard même si ton Wi-Fi est éteint, même sur réseau mobile.

**Avantages** : URL publique https, chiffrement, fonctionne depuis partout
**Limites** :
- L'URL change à chaque redémarrage (`trycloudflare.com` gratuit)
- Ton Mac doit être allumé (c'est toi le serveur)
- URL aléatoire (pas brandable)

---

## 🔒 OPTION 3 — URL PUBLIQUE PERMANENTE (ton domaine)

Pour une URL permanente type `ict.hiddennova-ict.fr` :

### 3a. Cloudflare Tunnel (gratuit, permanent)

1. Crée un compte Cloudflare gratuit
2. Ajoute ton domaine `hiddennova-ict.fr` à Cloudflare
3. Login : `./bin/cloudflared tunnel login`
4. Crée un tunnel nommé :
   ```bash
   ./bin/cloudflared tunnel create ict
   ./bin/cloudflared tunnel route dns ict ict.hiddennova-ict.fr
   ```
5. Config `~/.cloudflared/config.yml` :
   ```yaml
   tunnel: ict
   ingress:
     - hostname: ict.hiddennova-ict.fr
       service: http://localhost:8501
     - service: http_status:404
   ```
6. Lance : `./bin/cloudflared tunnel run ict`

**Résultat** : `https://ict.hiddennova-ict.fr` permanent + HTTPS auto.

---

## ☁️ OPTION 4 — DÉPLOIEMENT CLOUD (sans ton Mac)

Le site tourne sur un serveur cloud 24/7, même ton Mac éteint.

### 4a. Streamlit Community Cloud (GRATUIT — recommandé)

1. Push ton code sur **GitHub** (repo public ou privé)
2. Va sur [share.streamlit.io](https://share.streamlit.io)
3. Connecte GitHub → sélectionne ton repo → main → `dashboard.py`
4. Click **Deploy**
5. URL gratuite : `https://ton-repo.streamlit.app`

**Avantages** : gratuit, 24/7, zéro setup serveur
**Limites** : repo doit être accessible à Streamlit, données publiques

### 4b. Render.com (GRATUIT 750h/mois)

Fichier déjà prêt : `render.yaml`

1. Push sur GitHub
2. [render.com](https://render.com) → New Web Service → Connect GitHub
3. Sélectionne le repo → Render détecte `render.yaml` automatiquement
4. Deploy
5. URL : `https://ict-framework.onrender.com`

### 4c. Railway.app (USD 5/mois)

Fichier déjà prêt : `railway.json`

1. [railway.app](https://railway.app) → New Project → From GitHub Repo
2. Deploy automatique
3. URL custom possible

### 4d. Docker self-hosted (VPS à 5€/mois)

Fichier déjà prêt : `Dockerfile` + `docker-compose.yml`

Sur un VPS Ubuntu (OVH, Hetzner, DigitalOcean) :
```bash
git clone <ton-repo> ict-framework
cd ict-framework
docker-compose up -d
```

---

## 📊 COMPARATIF DES OPTIONS

| Option | Coût | Setup | URL | Uptime | Recommandé pour |
|---|---|---|---|---|---|
| **Local + LAN** | 0€ | 0 min | `192.168.1.40:8501` | Mac allumé | Usage quotidien solo |
| **Cloudflare Tunnel quick** | 0€ | 0 min | `xxx.trycloudflare.com` | Mac allumé | Partage ponctuel |
| **Cloudflare Tunnel permanent** | 0€ | 15 min | `ict.hiddennova-ict.fr` | Mac allumé | Intégration à ton domaine |
| **Streamlit Cloud** | 0€ | 5 min | `xxx.streamlit.app` | 24/7 | MVP / démo |
| **Render.com** | 0€ (750h) | 5 min | `xxx.onrender.com` | 24/7 | Production légère |
| **Railway.app** | 5$/mois | 3 min | `xxx.railway.app` | 24/7 | Production fiable |
| **VPS Docker** | 5€/mois | 30 min | ton domaine | 24/7 | Control total |

---

## 🎯 MA RECOMMANDATION POUR TOI

**Phase 1 — maintenant (5 secondes)** :
```bash
./ict serve-public
```
Tu as ta première URL publique live.

**Phase 2 — cette semaine** :
1. Crée un compte Cloudflare gratuit
2. Configure `ict.hiddennova-ict.fr` (option 3a ci-dessus)
3. Tu as une URL permanente branded

**Phase 3 — plus tard (si tu veux 24/7 sans ton Mac)** :
1. Push sur GitHub privé
2. Deploy Render.com (gratuit 750h/mois = ~24/7)
3. URL `ict-framework.onrender.com` permanente

---

## 🔐 SÉCURITÉ

**⚠️ Important** : le dashboard n'a PAS d'authentification par défaut.

Si tu rends l'URL publique, n'importe qui y accède. Avant production :

### Option A : Basic Auth via Streamlit-Auth
```python
# dans dashboard.py
import streamlit as st
password = st.text_input("Password", type="password")
if password != "TON_PASSWORD":
    st.stop()
```

### Option B : Cloudflare Zero Trust (gratuit)
Dans ton tunnel : ajoute Access Policy → Email Gate → seul ton email peut se connecter via magic link.

### Option C : Streamlit Authenticator
```bash
pip install streamlit-authenticator
```
Page login pro avec hashed passwords.

---

## 🆘 TROUBLESHOOTING

**"Address already in use"** — port 8501 occupé
```bash
lsof -i :8501
kill -9 <PID>
```

**"cloudflared: command not found"** — utilise le binary local
```bash
./bin/cloudflared tunnel --url http://localhost:8501
```

**Dashboard lent depuis le tunnel** — c'est normal (proxy), utilise LAN quand tu es chez toi.

---

## ✅ STATUS ACTUEL

Ton site est **EN LIGNE** à :
- 💻 Local : `http://localhost:8501` ✓
- 📱 LAN : `http://192.168.1.40:8501` ✓
- 🌍 Public : `https://genes-favorite-material-century.trycloudflare.com` ✓ (cette URL change à chaque redémarrage)

**Tu peux MAINTENANT ouvrir cette URL depuis ton téléphone en 4G, depuis n'importe où.** 🎯
