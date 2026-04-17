# 🔴 ICT Institutional Framework

> **Infrastructure quantitative institutionnelle** — découverte d'edge ML + compliance FTMO/The 5ers + dashboard web — le tout open source.

[![Tests](https://img.shields.io/badge/tests-65%2F65-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)]()
[![License](https://img.shields.io/badge/license-Private-red)]()

---

## 🎯 Ce que fait ce framework

Un **laboratoire quant complet** pour le trading ICT/SMC :

- 🔴 **Live Scanner** — détecte signaux ICT sur 12 assets en temps réel
- 🧪 **Edge Discovery** — Gradient Boosting calibré + Pareto frontier
- 🛡️ **Risk Engine** — compliance FTMO/5ers hard-coded (impossible de blow-up)
- 📊 **Backtesting** — Walk-Forward + Monte Carlo
- 📉 **Charts** — bougies + FVG/OB overlays (Plotly)
- 📔 **Trade Journal** — log trades réels + calibration ML vs actual
- 📅 **News Calendar** — skip auto pendant NFP/CPI/FOMC
- 🌐 **Web dashboard** — 11 pages Streamlit

## 🏗️ Architecture — 16 engines

```
Data Engine • Validation • Features • ICT Engine (FVG/OB/BB/Liq/SMT)
  • Bias • Regime • Scoring • Execution • Risk • Backtest
  • Adaptation • Audit • Edge Dominance (ML) • Live Scanner
  • Trade Journal • News Calendar
```

## 🚀 Installation

### En local (5 min)

```bash
git clone <this-repo>
cd ict-institutional-framework
bash setup.sh          # installe deps + télécharge data
./ict dashboard        # lance l'interface web
```

Ouvre `http://localhost:8501`.

### Cloud (24/7 sans ton Mac)

**Streamlit Community Cloud** (gratuit) :
1. Fork ce repo sur GitHub
2. Va sur [share.streamlit.io](https://share.streamlit.io)
3. Deploy → Select repo → `dashboard.py`
4. URL : `https://<repo-name>.streamlit.app`

**Render.com** (gratuit 750h/mo) :
1. Fork repo
2. [render.com](https://render.com) → New Web Service → Connect GitHub
3. Détection auto de `render.yaml`
4. Deploy

**Docker** (ton VPS) :
```bash
docker-compose up -d
```

Voir [docs/DEPLOY.md](docs/DEPLOY.md) pour détails complets.

## 📱 Usage

### CLI
```bash
./ict dashboard        # UI web
./ict scan             # scan one-shot
./ict daemon           # scanner continu + alertes
./ict backtest XAUUSD  # backtest rapide
./ict status           # health check
```

### Dashboard web — 11 pages

| Page | Usage |
|---|---|
| 🏠 Overview | vue d'ensemble |
| 🔴 Live Scanner | signaux actifs maintenant |
| 📊 Edge Explorer | courbes Pareto par asset |
| 📈 Backtest Runner | test stratégie |
| 🧪 Edge Discovery | pattern mining |
| 📉 Charts | bougies + FVG overlays |
| 📔 Trade Journal | log trades + analytics |
| 📅 News Calendar | events macro |
| 🛡️ Risk Compliance | règles FTMO/5ers |
| ⚙️ Settings | configuration |
| 🔧 System Health | diagnostic |

## 🔔 Alertes

### Discord (le plus simple)
1. Serveur Discord → Intégrations → Webhook → copie URL
2. Dashboard → Settings → colle webhook → Save

### Telegram
1. @BotFather → `/newbot` → note le token
2. `/start` ton bot → note `chat_id`
3. Dashboard → Settings → colle les deux → Save

### Desktop
Automatique sur macOS/Linux/Windows (notifications natives).

## 📊 Performance validée OOS

Sur 12 assets (118k bars historiques) :

| Tier | Trades/mois | WR pondéré | Expected R/mois |
|---|---|---|---|
| 🎯 ELITE | 93 | 41.7% | +23R |
| ⚖ BALANCED | 138 | 41.4% | +28R |
| 🚀 VOLUME | 165 | 40.3% | +33R |

**Top edges découverts par ML** :
- **XAGUSD H1** : 35/mo @ WR 46.2% (+92R total OOS)
- **XAUUSD H1** : 27/mo @ WR 47.3% (+71R)
- **BTCUSD H1** : 72/mo @ WR 36.9% (+58R)
- **USDCAD D1** : WR 75% @ threshold 0.75 (8 trades OOS)

## 🛡️ Protection anti blow-up

Le Risk Engine bloque automatiquement :
- Soft cap daily à -2.5% (FTMO limit -5%)
- **Hard cap daily à -3.5%** (kill switch)
- Size auto-réduite en DD (-2% → x0.75, -3.5% → x0.50, -5% → x0.25)
- 3 pertes consécutives → pause 24h
- Zéro weekend holding FTMO enforced

## 🧪 Tests

```bash
python3 -m pytest tests/ -v
# 65 passed in ~2s
```

## 📂 Structure

```
├── src/                    # 16 engines
├── config/                 # YAML config (prop firms, instruments)
├── data/                   # OHLC parquets (git-ignored)
├── tests/                  # 65 unit tests
├── docs/                   # QUICKSTART, DEPLOY
├── user_data/              # Préférences user (git-ignored)
│   ├── settings.json
│   ├── .env (secrets)
│   ├── journal.jsonl
│   └── news_cache.json
├── ict                     # CLI principal
├── setup.sh                # installer
├── dashboard.py            # UI Streamlit
├── run_cyborg_full_auto.py # daemon 24/7 FULL AUTO (production)
├── run_cyborg_ultimate.py  # daemon signal-only (fallback)
├── Dockerfile
├── docker-compose.yml
├── render.yaml             # Render.com auto-deploy
├── railway.json            # Railway.app auto-deploy
└── requirements.txt
```

## ⚠️ Disclaimer

Ce framework est un **outil d'aide à la décision**, pas un conseiller financier.
Le trading comporte des risques. Les performances passées ne garantissent pas les performances futures.
Utilise à tes propres risques — respecte toujours les règles de ton prop firm.

## 📝 Licence

Privé — usage personnel uniquement.

---

**🔥 Built with discipline, calibrated with data, protected by compliance. 🔥**
