# 🌩 ORACLE CLOUD FREE — Guide déploiement 24/7 PERMANENT

**Objectif** : ton CYBORG tourne **24/7 sur un datacenter Oracle** gratuit à vie, même ton Mac éteint.

## 🎁 Pourquoi Oracle Cloud Free ?

- **Always Free** (pas un trial) : VM ARM 4 vCPU + 24GB RAM à vie
- Largement assez pour ton cyborg (il consomme ~500MB RAM)
- Datacenter Europe (faible latence vers FTMO broker)
- Zéro cost hors usage excessif

## 📋 Étape 1 — Créer le compte Oracle Cloud (5 min)

1. Ouvre [signup.oracle.com/cloud-free](https://signup.oracle.com/cloud-free)
2. Email + téléphone + **carte bancaire** (NON débitée — juste vérification anti-fraude)
3. Sélectionne **région Frankfurt** ou **Paris** (Europe = latence faible)
4. Confirme le compte via email

## 🖥 Étape 2 — Créer la VM ARM (5 min)

Une fois dans le portail Oracle :

1. Menu ≡ → **Compute → Instances**
2. **Create instance** :
   - Name : `ict-cyborg`
   - Image : **Ubuntu 22.04 Minimal — ARM64**
   - Shape : **VM.Standard.A1.Flex** (Always Free)
     - 4 OCPU, 24 GB RAM (max gratuit)
   - Networking : Create new VCN (réseau par défaut)
   - SSH keys :
     - **Generate SSH key pair for me**
     - **Download private key** (file `ssh-key-xxx.key`) — *SAUVEGARDE-LE*
3. **Create** → attends 2 min que l'instance soit "Running"
4. Note la **Public IP** (ex: `132.226.x.x`)

## 🔐 Étape 3 — Configure firewall (pour Telegram)

Par défaut, Oracle bloque tout sauf SSH. Pour autoriser outbound Telegram :

Dans le menu de la VM → **Networking → Subnet → Security List → Egress rules**
- Laisse l'egress par défaut (0.0.0.0/0 all) — déjà ouvert pour l'outbound

Ingress : tu n'as besoin que de SSH (port 22, déjà configuré).

## 💻 Étape 4 — SSH et installation (5 min)

Sur ton Mac terminal :

```bash
# 1. Rends la clé SSH correcte
chmod 600 ~/Downloads/ssh-key-xxx.key

# 2. Connecte-toi à la VM
ssh -i ~/Downloads/ssh-key-xxx.key ubuntu@132.226.x.x

# 3. Une fois sur la VM :
git clone https://github.com/davghali/ict-trading-framework.git
cd ict-trading-framework
bash deployment/vps/setup_vps.sh

# 4. Édite les credentials
nano user_data/.env
# Colle :
#   TELEGRAM_BOT_TOKEN=8634446704:AAFzH7aC4jRhhlRuw1OAvuDjxoLXLPx0FLg
#   TELEGRAM_CHAT_ID=1050705899
# Ctrl+X, Y, Enter pour sauvegarder

# 5. Restart les services pour prendre le .env
systemctl --user restart ict-cyborg ict-supervisor

# 6. Vérifie
systemctl --user status ict-cyborg
# Doit afficher "active (running)"
```

## ✅ Étape 5 — Vérification

Sur ton phone Telegram, tu devrais recevoir :
```
🔴 ICT CYBORG FULL MODE
✅ Cross-asset filter
✅ Multi-TF strict (W/D/H4/H1)
...
```

**Ton cyborg tourne MAINTENANT sur Oracle Cloud 24/7.**
Tu peux éteindre ton Mac — ça continue.

## 🔄 Étape 6 — Auto-updates

Quand tu push du code sur GitHub :
```bash
ssh ubuntu@132.226.x.x
cd ict-trading-framework
git pull
systemctl --user restart ict-cyborg ict-supervisor
```

Ou ajoute un cron auto-pull :
```bash
crontab -e
# Ajoute :
0 */6 * * * cd ~/ict-trading-framework && git pull && systemctl --user restart ict-cyborg ict-supervisor
```

## 🧹 Étape 7 — Shutdown Mac

Tu peux maintenant :
- Éteindre les LaunchAgents Mac : `launchctl unload ~/Library/LaunchAgents/com.ictframework.*.plist`
- Garder ton Mac pour le développement / dashboard
- Le CYBORG tourne sur Oracle sans interruption

## 📊 Monitoring depuis ton Mac

SSH rapide depuis ton Mac pour voir les logs :
```bash
# Logs cyborg
ssh -i ~/Downloads/ssh-key-xxx.key ubuntu@132.226.x.x \
    "tail -f ~/ict-trading-framework/reports/logs/cyborg.log"

# Status
ssh ... "systemctl --user status ict-cyborg"
```

## 💰 Coût final

- Oracle Cloud : **0 €/mois forever**
- Domain (optionnel) : 10 €/an
- **Total : 0 € pour 24/7 permanent**

## 🆘 Support

Si bloqué sur une étape → dis-moi quelle étape et l'erreur exacte.
