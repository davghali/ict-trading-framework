# 🚀 DEPLOY AWS GUIDE — Bot ML Production v2

**Date** : 2026-04-21
**Version** : v2-ml-production (threshold 0.45)
**Expected** : WR 51.8% · PF 2.35 · +82%/an · DD -3.9%

---

## 📋 CHECKLIST PRÉ-DÉPLOIEMENT

- ✅ ML Model entraîné (4120 samples, AUC 0.883)
- ✅ Settings.json v2 configuré (11 assets, threshold 0.45)
- ✅ Audit complet passé (tous checks verts)
- ✅ Code repository à jour sur GitHub

---

## 🎯 ÉTAPE 1 — CONNEXION AWS WINDOWS (2 min)

### Via Remote Desktop (RDP)

```
Hostname     : 13.60.28.97 (ton AWS public IPv4)
User         : Administrator
Password     : [ton mot de passe AWS]
```

Mac → Microsoft Remote Desktop → New → IP + credentials

---

## 🎯 ÉTAPE 2 — PULL DERNIÈRE VERSION (1 min)

Ouvrir **PowerShell** en mode Administrator :

```powershell
cd C:\Users\Administrator\ict-trading-framework
git pull origin main
```

Tu dois voir des lignes comme :
```
Fetching origin
Updating xxx..yyy
Fast-forward
...
models/production_model.pkl | bin 0 -> xxxxx bytes
scripts/train_production_model.py | xxx +++
user_data/settings.json | xxx ++++----
```

---

## 🎯 ÉTAPE 3 — VÉRIFIER LE MODEL ML (30 sec)

```powershell
python -c "import pickle; m = pickle.load(open('models/production_model.pkl','rb')); print('Model OK'); print('Threshold:', m['threshold']); print('Samples:', m['training_samples']); print('AUC:', m['in_sample_auc'])"
```

Tu dois voir :
```
Model OK
Threshold: 0.45
Samples: 4120
AUC: 0.883
```

---

## 🎯 ÉTAPE 4 — CONFIGURER MT5 CREDENTIALS (5 min)

### Créer `user_data/mt5_accounts.json`

Dans PowerShell :
```powershell
notepad user_data\mt5_accounts.json
```

Coller (remplacer avec tes vraies credentials FTMO) :
```json
{
  "accounts": [
    {
      "name": "FTMO Swing 10k",
      "enabled": true,
      "login": 511206077,
      "password": "TON_MOT_DE_PASSE_TRADING",
      "server": "FTMO-Server",
      "balance": 10000,
      "risk_per_trade_pct": 0.5
    }
  ]
}
```

**IMPORTANT** : le `password` c'est le TRADING password (pas le login FTMO dashboard).

### Vérifier la connexion MT5

```powershell
python -c "import MetaTrader5 as mt5; ok = mt5.initialize(login=511206077, password='TON_MDP', server='FTMO-Server'); print('Connected:', ok); print(mt5.account_info() if ok else mt5.last_error()); mt5.shutdown()"
```

Tu dois voir balance + login affichés.

---

## 🎯 ÉTAPE 5 — DISABLE STREAMLIT (30 sec)

### Tuer tous les process Streamlit actifs

```powershell
Get-Process | Where-Object {$_.ProcessName -match "streamlit|python"} | Where-Object {$_.MainWindowTitle -match "streamlit"} | Stop-Process -Force -ErrorAction SilentlyContinue
```

### Désactiver la Scheduled Task Streamlit (si existe)

```powershell
Get-ScheduledTask | Where-Object {$_.TaskName -match "Streamlit|Dashboard"} | Disable-ScheduledTask
```

---

## 🎯 ÉTAPE 6 — TESTER LE BOT EN DRY-RUN (2 min)

**Test manuel avant de lancer en auto-exec :**

```powershell
python run_cyborg_full_auto.py --dry-run 2>&1 | Select-Object -First 30
```

Tu dois voir :
```
[OK] ML Model loaded (threshold 0.45)
[OK] MT5 connected (balance $10000)
[OK] Telegram bot connected
[OK] 11 assets loaded
Scanning...
```

---

## 🎯 ÉTAPE 7 — LANCER EN AUTO-EXEC (activation live)

### Option A : Via Scheduled Task (recommandé)

```powershell
# Stop existing
Stop-ScheduledTask -TaskName "ICTCyborg" -ErrorAction SilentlyContinue

# Start fresh
Start-ScheduledTask -TaskName "ICTCyborg"

# Verify
Get-ScheduledTask -TaskName "ICTCyborg" | Get-ScheduledTaskInfo
```

### Option B : Manuel direct (pour tester)

```powershell
# Run detached in background
Start-Process -FilePath "python" -ArgumentList "run_cyborg_full_auto.py" -WindowStyle Hidden
```

---

## 🎯 ÉTAPE 8 — VÉRIFIER TELEGRAM (30 sec)

Ouvre Telegram `@Davghalibot` et envoie :

```
/status
```

Tu dois recevoir :
```
🤖 ICT CYBORG FULL AUTO
✅ System : RUNNING
✅ ML Model : loaded (threshold 0.45)
✅ MT5 : connected (FTMO 10k)
📊 Daily P&L : +0.00%
📈 Positions : 0 open
⏰ Last scan : 22:35:42 Paris
```

---

## 🎯 ÉTAPE 9 — PREMIERS TRADES (attente)

**Fréquence attendue** : 3-4 trades/semaine
**Première activité** : lors de la prochaine killzone London (07h UTC) ou NY AM (13h30 UTC)

Quand un signal fire, tu reçois sur Telegram :
```
💎 A+ GRADE — XAUUSD H1

🟢 ACHETER
━━━━━━━━━━━━━
📍 Entry : 4820.50
🛑 SL    : 4815.20
🎯 TP1   : 4831.10 (2R)
🏁 TP2   : 4836.40 (3R)
━━━━━━━━━━━━━
🤖 ML P(win): 67%
⏰ KZ    : London KZ

[✅ PRENDRE]  [❌ SKIP]  [📊 DÉTAILS]
```

Si `auto_execute: true` → le bot exécute tout seul sans attendre ton clic.

---

## 📊 MONITORING QUOTIDIEN

### Recap du soir (22:00 UTC / 23:00 Paris)

Tu recevras automatiquement sur Telegram :
```
🏙️ RECAP DU SOIR
Tuesday 22/04/2026 · 23:00 Paris

🎯 SIGNAUX DU JOUR
Total: 3
🏆 A+/S: 2  ⭐ A: 1  ⚡ B: 0

🏛️ PROPFIRM
P&L jour:   +1.20%
Drawdown:   0.00%
Objectif:   12.0% accompli (target +10%)

🕐 DEMAIN
🇬🇧 London:  09:00 Paris  (07:00 UTC)
🇺🇸 NY AM:   14:30 Paris  (12:30 UTC)

💤 Bonne nuit David — discipline ✓
```

### Commandes Telegram disponibles

```
/status       — État du système + positions
/pause        — Suspend auto-execution
/resume       — Reprend auto-execution
/positions    — Liste positions MT5 ouvertes
/close_all    — 🚨 URGENCE : ferme tout
/auto_status  — Détails AutoExecutor
```

---

## 🛡️ SAFETY NET (déjà actif)

- Max daily loss : **-3.5%** → bot se met en pause auto
- Max total DD : **-8%** → bot stop + alerte
- Max positions concurrentes : **4**
- Max trades/jour : **8**
- Friday cutoff : **16h UTC** → pas de nouveaux trades vendredi soir

---

## 🔧 TROUBLESHOOTING

### Bot ne tourne pas
```powershell
# Check processes
Get-Process python

# Check Scheduled Tasks
Get-ScheduledTask | Where-Object {$_.TaskName -match "ICTCyborg"}

# Manually start
python run_cyborg_full_auto.py
```

### Telegram pas de réponse
```powershell
# Test telegram
python -c "from src.telegram_bot import TelegramBot; b = TelegramBot(); b.send_text('Test OK')"
```

### MT5 déconnecté
```powershell
# Re-init MT5
python -c "import MetaTrader5 as mt5; mt5.initialize()"
```

### Rollback d'urgence
```powershell
cd C:\Users\Administrator\ict-trading-framework
git log --oneline -5
git checkout <previous_commit_hash>
```

---

## 📈 OBJECTIFS FTMO (avec cette config)

### Phase 1 (10k challenge - target +10%)
- Durée attendue : **2-3 semaines**
- Daily loss : -5% max → on est à -3.5% safety
- Total DD : -10% max → on est à -8%

### Phase 2 (verification - target +5%)
- Durée attendue : **1-2 semaines**
- Mêmes règles

### Funded 10k → 100k scaling
- Performance attendue : **+5-8%/mois**
- 80/20 profit split : **$4-6k/mois** à toi sur 100k funded
- Scaling +25% tous les 4 mois

---

## 🎯 NEXT STEPS APRÈS DEPLOY

1. **Semaine 1-2** : monitoring quotidien, vérifier que trades = backtest
2. **Semaine 3-4** : ajuster threshold si besoin (0.45 → 0.48 si DD élevé)
3. **Mois 2** : re-train ML avec nouvelles data
4. **Mois 3** : demander scaling FTMO

---

**Tout est prêt. Bonne chance David. 🏆**
