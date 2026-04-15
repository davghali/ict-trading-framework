# 🌐 SITE STANDALONE — 5 MINUTES pour URL publique gratuite 24/7

**Objectif** : avoir TON site à URL publique permanente, **complètement indépendant** de hiddennova-ict.fr, **gratuit**, **24/7 sans ton Mac**.

---

## 🥇 OPTION A — Streamlit Community Cloud (RECOMMANDÉ)

**Résultat final** : URL type `https://ict-framework.streamlit.app`
**Coût** : 0€ forever
**Uptime** : 24/7 (hébergement par Streamlit)
**Ton Mac** : pas besoin qu'il soit allumé

### Étape 1 — Compte GitHub (si pas déjà)

1. [github.com/signup](https://github.com/signup) — gratuit, 2 min
2. Vérifie ton email

### Étape 2 — Crée le repo

1. [github.com/new](https://github.com/new)
2. Nom (au choix) : `ict-framework` / `ict-quant` / `apex-quant` / ce que tu veux
3. **Private** (conserve la confidentialité de tes trades)
4. **Create repository**

### Étape 3 — Push le code depuis ton Mac

Ouvre Terminal :
```bash
cd "/Users/davidghali/DAVID DAVID/ict-institutional-framework"

# Git init (une seule fois)
git init
git add .
git commit -m "Initial commit: ICT Institutional Framework"
git branch -M main

# Remplace <USERNAME> par ton pseudo GitHub et <REPO> par le nom que tu as choisi
git remote add origin https://github.com/<USERNAME>/<REPO>.git
git push -u origin main
```

Il va te demander tes credentials GitHub (utilise un **Personal Access Token** :
[github.com/settings/tokens](https://github.com/settings/tokens) → Generate new token → `repo` scope).

### Étape 4 — Déploie sur Streamlit Cloud

1. Va sur [share.streamlit.io](https://share.streamlit.io)
2. **Sign in with GitHub** (autorise)
3. **New app** → Select repo → `main` branch → `dashboard.py`
4. **Custom subdomain** : choisis ton URL (ex. `ict-quant-david`)
5. **Deploy**

⏳ Premier build = 3-5 min. Streamlit télécharge les deps, tout se fait tout seul.

### Étape 5 — ✅ TON SITE EST LIVE

URL : `https://ict-quant-david.streamlit.app` (ton choix)

**Accessible de partout**, même ton Mac éteint. Gratuit.

---

## 🥈 OPTION B — Hugging Face Spaces (alternative gratuite)

**Résultat** : `https://huggingface.co/spaces/<username>/ict-framework`

1. [huggingface.co/join](https://huggingface.co/join) — gratuit
2. [New Space](https://huggingface.co/new-space) → Streamlit SDK → Free CPU
3. Push code (Git-like workflow, instructions fournies)

**Avantages** : pas de limite de compute, ML-friendly.

---

## 🥉 OPTION C — Render.com (gratuit 750h/mois ≈ 24/7)

**Résultat** : `https://ict-framework.onrender.com`

1. Push sur GitHub (Option A, étapes 1-3)
2. [render.com](https://render.com) → Sign up GitHub
3. **New + Web Service** → Select repo
4. Render détecte `render.yaml` automatiquement
5. **Create Web Service**

⚠ Le free tier de Render **dort** après 15 min d'inactivité (wake up = 30s).
Streamlit Cloud n'a pas ce problème → **préfère Streamlit Cloud**.

---

## 💎 OPTION D — Domaine pro à 10€/an

Si tu veux une URL **branded** type `https://ict-quant.fr` :

1. Achète le domaine sur :
   - [OVH](https://www.ovh.com) (~10€/an `.fr`, `.com`)
   - [Namecheap](https://www.namecheap.com) (~10€/an)
   - [Google Domains](https://domains.google) (~12€/an)

2. Noms suggérés (à vérifier dispo) :
   - `ict-quant.fr` / `ict-quant.com`
   - `apex-quant.fr` / `apex-quant.com`
   - `edge-lab.fr`
   - `smc-quant.fr`
   - `ict-pro.app`
   - `quant-ict.io`

3. Pointe le domaine vers Streamlit Cloud (CNAME) ou Render :
   - Streamlit Cloud supporte custom domain sur plan payant (20$/mo)
   - Render supporte custom domain **gratuitement** même sur free tier
   - → **Recommandation** : deploy Render + custom domain = 10€/an tout compris

---

## 📊 COMPARATIF FINAL

| Solution | URL | Coût | Uptime | Recommandé |
|---|---|---|---|---|
| Streamlit Cloud | `xxx.streamlit.app` | 0€ | 24/7 | ⭐ **PRIMARY** |
| Hugging Face | `xxx.hf.space` | 0€ | 24/7 | Alternative |
| Render free | `xxx.onrender.com` | 0€ | ~24/7 (dormir 15min) | Backup |
| Render + domaine | `ton-domaine.fr` | 10€/an | 24/7 | Pro |
| VPS Docker | `ton-domaine.fr` | 60€/an | 24/7 | Enterprise |

---

## ⚠️ IMPORTANT — SÉCURITÉ AVANT DE DÉPLOYER

Ton site public **n'a pas d'authentification par défaut**. N'importe qui avec l'URL peut voir tes settings et trades.

**AVANT DE DEPLOY** :

### Solution 1 — Ajouter un password simple

Dans `dashboard.py`, tout en haut après les imports :

```python
import streamlit as st

# Password gate
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.title("🔒 ICT Framework — Access")
    pwd = st.text_input("Password", type="password")
    if st.button("Unlock"):
        # CHANGE CE PASSWORD !
        if pwd == "TonPasswordSecret123":
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Wrong password")
    st.stop()
```

### Solution 2 — Streamlit Authenticator (pro)

```bash
pip install streamlit-authenticator
```

Documentation : [github.com/mkhorasani/Streamlit-Authenticator](https://github.com/mkhorasani/Streamlit-Authenticator)

### Solution 3 — Cloudflare Access (Zero Trust)

Si tu mets un custom domain Cloudflare, active Zero Trust Access :
- Gratuit jusqu'à 50 users
- Magic link par email
- Seul ton email a accès

---

## 🎯 MON CONSEIL POUR TOI

**Path 1 — MAINTENANT (5 min)** :
```bash
# 1. Crée un GitHub privé (2 min)
# 2. Push ton code
git init && git add . && git commit -m "initial"
git remote add origin https://github.com/<TOI>/ict-quant.git
git push -u origin main

# 3. Deploy sur Streamlit Cloud
# share.streamlit.io → New app → main → dashboard.py → Deploy
```

Tu as `https://ict-quant-<toi>.streamlit.app` en live en 5 min.

**Path 2 — Dans une semaine (pro)** :
1. Achète `ict-quant.fr` sur OVH (~10€/an)
2. Deploy sur Render.com (free tier)
3. Lie ton domaine à Render (CNAME)
4. Tu as `https://ict-quant.fr` branded

---

## 🆘 HELP

**"git push" demande un mot de passe** :
- Use un Personal Access Token (pas ton password GitHub)
- [github.com/settings/tokens](https://github.com/settings/tokens) → Generate → `repo` scope

**"Streamlit Cloud deploy failed"** :
- Check que `requirements.txt` liste bien les deps
- Check logs dans l'UI Streamlit Cloud

**"Cloud site ne voit pas mes données"** :
- Les parquets dans `data/raw/` ne sont PAS pushés (.gitignore)
- Au premier run cloud, le dashboard télécharge automatiquement via yfinance
- Ou push les parquets (retire `data/` du .gitignore) — +200MB

**"Je veux MES trades persistés sur le cloud"** :
- `user_data/journal.jsonl` n'est PAS pushé
- Options :
  - Pousse-le (retire de .gitignore) — simple, mais visible sur GitHub
  - Utilise un Volume Render (5$/mo) pour persistance
  - Base de données (Supabase free) — plus pro

---

## ✅ ACTION IMMÉDIATE

**Je te recommande de faire ça MAINTENANT, ça prend 10 min** :

1. Va sur [github.com/new](https://github.com/new) → create repo (privé)
2. Reviens ici et fais :
   ```bash
   cd "/Users/davidghali/DAVID DAVID/ict-institutional-framework"
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<TON-USERNAME>/<TON-REPO>.git
   git push -u origin main
   ```
3. Va sur [share.streamlit.io](https://share.streamlit.io) → Deploy → choose repo
4. **Ton site est live** avec URL indépendante 24/7.

Si tu bloque sur une étape, dis-moi laquelle — je t'aide à la débloquer. 🔥
