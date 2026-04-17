# 🚀 ICT CYBORG ULTIMATE — Guide de Déploiement

**Date** : 2026-04-17
**Version** : Ultimate (3 phases activées)
**Statut** : Code prêt — nécessite déploiement AWS + tests

---

## 📋 Vue d'ensemble

3 phases d'optimisation déployées dans ce commit :

| Phase | Modules | Impact attendu |
|-------|---------|----------------|
| **1 (Gains faciles)** | Multi-instruments (19), exit_manager | x2-3 revenus |
| **2 (Gains moyens)** | confluence_filter, dynamic_risk, news_ride | +50-100% |
| **3 (Gains avancés)** | pyramid_manager, ML regime-aware, hot standby | +30-50% |

**Impact cumulé théorique** : **x4 à x7** sur les revenus.

---

## 🔧 Fichiers créés

### Nouveaux modules
- `src/exit_manager/` — Multi-partial exits (25%@1R, 25%@2R, 25%@3R, runner trailing)
- `src/confluence_filter/` — Filtre 7-facteurs (multi-TF, SMT, liquidity, cross-asset, KZ, volume, OB)
- `src/dynamic_risk/` — Anti-martingale adaptatif (0.25% min → 1.0% max)
- `src/news_ride/` — Ride post-news retracement 61.8% (désactivé par défaut)
- `src/pyramid_manager/` — Adds sur setups forts (+1R, max 2 ajouts)
- `src/ml_retrain/regime_aware_retrainer.py` — Modèles ML par régime

### Scripts
- `scripts/hot_standby_failover.sh` — Failover GCP si AWS down

### Config
- `user_data/settings.json` — Étendu avec 25+ nouveaux paramètres

### Nouveau daemon
- `run_cyborg_ultimate.py` — Version avec toutes les phases (ne casse PAS `run_cyborg.py`)

---

## 🎯 Déploiement sur AWS Windows (à faire par David)

### 1. Connecter en RDP
```
Host : <AWS_IP>
User : Administrator
Password : (voir WINDOWS_VPS_CREDENTIALS.txt sur Desktop)
```

### 2. Pull du nouveau code
Ouvrir PowerShell :
```powershell
cd C:\Users\Administrator\ict-trading-framework
git pull origin main
```

### 3. Vérifier settings.json à jour
```powershell
Get-Content user_data\settings.json | Select-String "use_multi_partial"
```
→ Doit afficher `"use_multi_partial_exits": true`.

### 4. Test dry-run (IMPORTANT — ne pas skipper)
```powershell
python run_cyborg_ultimate.py
```
Laisser tourner 5 minutes. Vérifier :
- Telegram affiche "🔴 ICT CYBORG ULTIMATE"
- Logs montrent "✅ ExitManager activé", "✅ ConfluenceFilter activé", etc.
- Au moins 1 scan réussi sans erreur

Ctrl+C pour arrêter.

### 5. Basculer la Scheduled Task
Option A (safer) — **garder ancien + nouveau en parallèle** :
- Task "ICTCyborg" → continue avec `run_cyborg.py`
- Créer task "ICTCyborgUltimate" → lance `run_cyborg_ultimate.py` sur un 2ème compte MT5

Option B (full switch) :
```powershell
# Éditer la Scheduled Task "ICTCyborg"
$task = Get-ScheduledTask -TaskName "ICTCyborg"
$action = New-ScheduledTaskAction `
  -Execute (Get-Command python.exe).Source `
  -Argument "C:\Users\Administrator\ict-trading-framework\run_cyborg_ultimate.py" `
  -WorkingDirectory "C:\Users\Administrator\ict-trading-framework"
Set-ScheduledTask -TaskName "ICTCyborg" -Action $action
```

### 6. Redémarrer
```powershell
Stop-ScheduledTask -TaskName "ICTCyborg"
Start-Sleep 3
Start-ScheduledTask -TaskName "ICTCyborg"
```

### 7. Vérification
- Ouvrir Telegram → attendre le message de démarrage (< 1 min)
- Dashboard Streamlit → vérifier "Last Scan" récent
- Laisser tourner 24h → évaluer :
  - 0 erreur critique dans logs
  - Filtrage correct (A+ only, confluence pass)
  - Telegram montre les infos enrichies (score confluence, risk dynamique)

---

## ⚠️ Désactivation d'un module en urgence

Si un module cause problème, **désactiver dans `settings.json`** (ne PAS toucher au code) :

```json
"use_multi_partial_exits": false,
"use_confluence_filter": false,
"use_dynamic_risk": false,
"use_news_ride": false,
"use_pyramid": false
```

Puis `Stop/Start ScheduledTask`.

---

## 🔄 Rollback complet

Si tout doit revenir à l'ancienne version :

```powershell
cd C:\Users\Administrator\ict-trading-framework
git log --oneline -5  # repérer le commit précédent
git checkout <COMMIT_HASH>  # rollback local
# OU reprendre Scheduled Task sur run_cyborg.py (ne pas toucher run_cyborg_ultimate.py)
```

---

## 📊 Monitoring à surveiller (1ère semaine)

| Métrique | Seuil alerte | Comment vérifier |
|----------|--------------|------------------|
| Uptime bot | < 95% | UptimeRobot |
| Erreurs /scan | > 3 par cycle | Logs AWS |
| Signaux A+/semaine | < 2 (trop filtré) | Telegram history |
| Drawdown | > 3% daily | Dashboard Streamlit |
| MT5 disconnect | tout disconnect | Telegram alerts |

---

## 🎓 Onboarding The5ers High Stakes 100K

Quand tu achètes The5ers :

1. Ajouter dans `user_data/mt5_accounts.json` :
```json
{
  "id": "the5ers_highstakes_100k",
  "broker": "The5ers",
  "variant": "high_stakes",
  "login": <TON_LOGIN>,
  "password": "<TON_MDP>",
  "server": "The5ers-Server01",
  "balance": 100000,
  "max_daily_pct": 4.0,
  "max_overall_pct": 5.0,
  "risk_per_trade_pct": 0.4,
  "enabled": true,
  "priority": 1,
  "assets_whitelist": ["XAUUSD", "NAS100", "SPX500", "EURUSD", "GBPUSD", "BTCUSD"],
  "notes": "The5ers High Stakes — 1-step challenge, 5% trailing DD strict"
}
```

2. Redémarrer la Scheduled Task.

3. Le bot prendra automatiquement les signaux A+/S sur ce compte avec le risque configuré.

---

## 🤖 Cron GCP (failover + ML daily)

Sur le VM GCP Linux, ajouter :

```bash
crontab -e
```

```cron
# ML daily retrain (à 02h00 UTC)
0 2 * * * cd /home/davidghali/ict-trading-framework && python3 -c "from src.ml_retrain.regime_aware_retrainer import *; retrainer = RegimeAwareRetrainer(RegimeAwareRetrainerConfig(model_dir=Path('models'), frequency='daily')); retrainer.load_existing_models(); print(retrainer.summary())" >> /var/log/ml_retrain.log 2>&1

# Hot standby failover (toutes les 2 min)
*/2 * * * * /home/davidghali/ict-trading-framework/scripts/hot_standby_failover.sh

# Heartbeat hebdo (dimanche 18h UTC)
0 18 * * 0 /home/davidghali/ict-trading-framework/scripts/heartbeat.sh
```

---

## ✅ Checklist finale

- [ ] RDP AWS ouvert
- [ ] `git pull` sur AWS fait
- [ ] `python run_cyborg_ultimate.py` test OK 5 min
- [ ] Scheduled Task basculée
- [ ] Telegram reçoit le msg "ULTIMATE"
- [ ] Dashboard montre "Last Scan" récent
- [ ] 24h de test → OK
- [ ] The5ers 100k ajouté quand acheté
