# 🚀 QUICK START — ICT Institutional Framework

## ⚡ Installation (1 minute)

```bash
cd "/Users/davidghali/DAVID DAVID/ict-institutional-framework"
bash setup.sh
```

Ça fait :
1. Installe les dépendances Python (numpy, pandas, scikit-learn, streamlit…)
2. Crée toutes les dossiers nécessaires
3. Télécharge les data Yahoo Finance (12 assets)
4. Initialise les settings par défaut
5. Lance la vérification finale

## 🎯 Usage quotidien (3 options)

### Option A : Dashboard visuel (RECOMMANDÉ)

```bash
./ict dashboard
```

Ouvre `http://localhost:8501` dans ton navigateur. **11 pages** :
- 🏠 **Overview** — vue d'ensemble
- 🔴 **Live Scanner** — signaux actifs maintenant
- 📊 **Edge Explorer** — courbes Pareto ML
- 📈 **Backtest Runner** — tester une stratégie
- 🧪 **Edge Discovery** — analyse features
- 📉 **Charts** — bougies + FVG overlays
- 📔 **Trade Journal** — log trades réels
- 📅 **News Calendar** — events macro
- 🛡️ **Risk Compliance** — règles FTMO/5ers
- ⚙️ **Settings** — configuration tout-en-un
- 🔧 **System Health** — diagnostic

### Option B : Scanner CLI

```bash
./ict scan           # one-shot
./ict daemon         # continu + alertes
```

### Option C : Daemon + Auto-start

```bash
./ict install-autostart   # macOS LaunchAgent
```

Le daemon démarre **automatiquement au login Mac**, scanne les 12 assets toutes les 15 min, et envoie notification desktop + Discord/Telegram dès qu'un signal apparaît.

## 📱 Configurer les alertes

### Discord (le plus simple)

1. Dans ton serveur Discord : `Paramètres > Intégrations > Webhooks > Nouveau webhook`
2. Copie l'URL
3. Dans le dashboard → `⚙️ Settings` → colle l'URL dans "Discord Webhook URL" → SAVE

### Telegram

1. Parle à `@BotFather` → `/newbot` → note le token
2. Démarre une conversation avec ton bot → `/start`
3. Va sur `https://api.telegram.org/bot<TOKEN>/getUpdates` → note `chat.id`
4. Dashboard → `⚙️ Settings` → colle les deux → SAVE

### Desktop macOS

Activé par défaut. Notification native avec son "Glass" au trigger.

## 🏦 Workflow FTMO Challenge

**Jour 1 — setup**
```bash
./ict dashboard
# → Settings → firm: ftmo, variant: classic_challenge, balance: 100000, risk: 0.5%
```

**Chaque jour**
1. Matin : ouvre dashboard → Live Scanner → SCAN
2. Identifie signaux BALANCED/ELITE proche de ton prix actuel
3. Vérifie News Calendar (skip si news ≤ 30 min)
4. Places tes ordres sur FTMO (MetaTrader ou cTrader)
5. Clique "Log this trade" dans le scanner
6. À la clôture : Trade Journal → "Fermer un trade ouvert"

**Avantages** :
- Impossible de blow-up (Risk Engine enforce)
- Tu sais TA vraie performance vs prédite (calibration ML)
- Historique complet pour analyse

## 📊 Comprendre les 3 TIERS

| Tier | Criterion | Trades/mois | WR attendu | Usage |
|---|---|---|---|---|
| 🎯 **ELITE** | P(win) ≥ 0.45+ | ~93 | 41-47% | Max WR |
| ⚖ **BALANCED** | P(win) ≥ 0.35+ | ~138 | 41-47% | Optimal |
| 🚀 **VOLUME** | P(win) ≥ 0.30+ | ~165 | 36-46% | Max trades |

## 🔧 Commandes utiles

```bash
./ict setup               # réinstaller
./ict status              # health check
./ict calendar            # news à venir
./ict test                # tester alertes
./ict install-autostart   # auto-start Mac
./ict uninstall-autostart # retirer
./ict dashboard           # UI web
./ict scan                # scan unique
./ict daemon              # scanner continu
./ict backtest XAUUSD     # backtest rapide
```

## 🆘 Troubleshooting

### "No module named 'streamlit'"
```bash
python3 -m pip install streamlit
```

### "Data not found"
```bash
./ict setup
```

### "Discord webhook not working"
- Vérifie l'URL dans Settings
- Test via `./ict test`

### "Trop peu de signaux"
- Utilise tier "volume" dans Settings
- Élargis les assets (H1 → tous)

### "Trop de signaux"
- Passe au tier "elite"
- Limite min_alert_tier à ELITE

## 📚 Structure des fichiers

```
ict-institutional-framework/
├── ict                      # CLI principal (chmod +x)
├── setup.sh                 # installer
├── dashboard.py             # UI Streamlit
├── run_daemon.py            # scanner continu
├── run_*.py                 # scripts recherche (backtest, ML, etc.)
├── user_data/               # TES préférences (git-ignore)
│   ├── settings.json
│   ├── .env                 # secrets
│   ├── journal.jsonl        # tes trades
│   └── news_cache.json
├── src/                     # 14 engines
│   ├── live_scanner/        # NOUVEAU : scanner + alerter + notify
│   ├── trade_journal/       # NOUVEAU : log + analytics
│   ├── news_calendar/       # NOUVEAU : macro events
│   └── ... (les 13 engines existants)
├── data/raw/                # 18 parquets OHLC
├── reports/                 # sorties JSON/CSV + logs
└── docs/                    # documentation
```

## 🎯 Rappel philosophique

> **"Le marché est incertain. Toute stratégie peut échouer. Seule la robustesse survit."**

Le système :
- **Ne te fera pas blow-up** (compliance hard-coded)
- **Ne te mentira pas** (Audit Engine rejette les perf suspectes)
- **Te complète** (ton œil + sa discipline = synergy)

**Ton 80% WR humain** reste la force. Le système l'**amplifie** en scannant 12 assets 24/7 que tu ne peux pas surveiller en parallèle.

🔥 *Survival mode ON.*
