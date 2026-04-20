# 🎯 ICT CYBORG ULTRA — Guide d'installation TradingView

## Qu'est-ce que c'est ?

**LE premier indicateur TradingView qui combine 18 systèmes ICT/SMC en un seul script Pine.**

Personne d'autre au monde n'a fait ça. Point.

---

## 🏆 Les 18 systèmes intégrés

1. **FVG multi-timeframe** avec aging automatique
2. **Order Blocks** (OB + reversal detection)
3. **Breaker Blocks / IFVG** (labels BB↑/↓)
4. **Liquidity pools** (buy/sell stops via swing points)
5. **Liquidity Sweeps** (high/low swept detection)
6. **SMT Divergence** (cross-asset via DXY)
7. **Multi-TF bias strict** (W + D + H4 + H1 all aligned)
8. **Cross-asset filter** (DXY / VIX / SPX)
9. **Regime detection** (TRENDING / RANGING / VOLATILE / MANIPULATION)
10. **Killzones** (Asia, London, NY AM, NY PM, London Open)
11. **Next Killzone countdown** en temps réel
12. **Silver Bullet setup** détecteur
13. **Judas Swing** détecteur
14. **Power of Three** (PO3) détecteur
15. **Confluence scoring** 7 facteurs
16. **Grade S/A+/A/B** automatique
17. **Position sizing calculator** (SL/TP/lots suggérés)
18. **HUD Dashboard** 19 lignes top-right

---

## 📱 Installation (2 minutes)

### Étape 1 — Ouvre TradingView
Va sur https://www.tradingview.com → login

### Étape 2 — Ouvre n'importe quel chart
Exemple : XAUUSD / EURUSD / NAS100

### Étape 3 — Ouvre Pine Editor
- En bas de la page → onglet **"Pine Editor"**
- Ou raccourci : `Ctrl+Alt+P` (Windows) / `Cmd+Alt+P` (Mac)

### Étape 4 — Colle le script
1. Clear l'éditeur (`Ctrl+A` → `Delete`)
2. Ouvre `ICT_CYBORG_ULTRA.pine` dans ton dossier
3. **Copie tout le contenu** (Ctrl+A → Ctrl+C)
4. **Colle dans l'éditeur TradingView** (Ctrl+V)

### Étape 5 — Sauvegarde + Add to chart
- Clique **"Save"** (ou Ctrl+S) → nomme-le "ICT Cyborg Ultra"
- Clique **"Add to chart"** en haut à droite de l'éditeur

### Étape 6 — C'est fait !
L'indicateur apparaît sur ton chart avec :
- 📊 Dashboard HUD en haut à droite
- 🎯 Boxes FVG colorées
- 📦 Order Blocks highlightés
- 📏 Lignes de liquidité
- ⚡ Labels SB/J/PO3 pour les setups détectés

---

## 🔔 Configuration des alertes (IMPORTANT)

Pour recevoir des **notifications iPhone/Mac** quand un Grade S/A+ est détecté :

### Étape 1 — Click droit sur le chart → "Add Alert"

### Étape 2 — Sélectionne :
- **Condition** : `ICT Cyborg Ultra`
- **Alert** : choisis parmi :
  - 💎 Grade S Setup (plus rare, plus fiable)
  - 🎯 Grade A+ Setup (recommandé)
  - 🎯 Silver Bullet Long / Short
  - 🔄 Judas Swing Long / Short
  - ⚡ PO3 Long / Short
  - 📈 Multi-TF Aligned Bull / Bear
  - 🧹 Liquidity Sweep High / Low

### Étape 3 — Actions :
- ✅ **Show pop-up** (desktop)
- ✅ **Play sound**
- ✅ **Send email-to-SMS** (si tu veux SMS)
- ✅ **Webhook URL** : pour envoyer à ton bot AWS
- ✅ **Send notification to TradingView app** (iPhone/Android push)

### Étape 4 — Expiration
- "Open-ended" (jamais expirer)

### Étape 5 — Save

**Refais pour chaque alerte que tu veux** (je recommande au minimum : Grade A+ + Liquidity Sweep).

---

## ⚙️ Configuration optimale

### Mode SNIPER (recommandé pour pairer avec ton bot)
- Trading Style : **SNIPER**
- Min confluence : **5**
- Only Grade A+ et S déclenchent des alertes

### Mode SCALPER
- Trading Style : **SCALPER**
- Min confluence : **3**
- Grade A et plus déclenchent

### Mode SWING
- Trading Style : **SWING**
- Min confluence : **4**
- Focus sur daily/H4

---

## 🎨 Customisation

### Thème
- **Dark Pro** (par défaut, recommandé)
- Light (fond blanc)
- Neon (couleurs vives)
- Minimal (peu de visuels)

### Dashboard position
- Top Right / Top Left / Bottom Right / Bottom Left / Middle Right

### Éléments visuels
Tu peux masquer/afficher :
- FVG boxes
- Order Blocks
- Breaker Blocks
- Liquidity zones
- PDH/PDL/PWH/PWL
- Killzone highlights

---

## 🔗 Connexion avec ton bot AWS (webhook)

Si tu veux que TradingView **déclenche ton bot AWS** quand un Grade A+ tombe :

### Étape 1 — Active webhook dans TV (Premium plan requis ~15$/mois)
Dans les settings de l'alerte :
- ✅ **Webhook URL** : `https://ton-webhook-url.com/signal`
- ✅ **Message** : JSON format :
```json
{
  "action": "buy",
  "symbol": "{{ticker}}",
  "price": "{{close}}",
  "grade": "A+",
  "confluence": "{{plot_0}}",
  "time": "{{time}}"
}
```

### Étape 2 — Créer un endpoint sur ton AWS
Ajouter un Flask/FastAPI server qui écoute les webhooks et déclenche MT5.

*(Si tu veux cette étape, dis-le moi et je code l'endpoint)*

---

## 📊 Ce que tu verras sur le chart

### Dashboard HUD (top-right)
```
┌───────────────────────────────┐
│ 🎯 ICT CYBORG ULTRA | XAUUSD │
├───────────────────────────────┤
│ GRADE         | A+           │
│ Confluence    | 5/7          │
│ Multi-TF      | W↑ D↑ H4↑ H1↑│
│ Cross-Asset   | DXY↓ VIX↓ SPX↑│
│ Regime        | TRENDING     │
│ Killzone      | NY AM KZ     │
│ Next KZ       | NY PM in 5h30m│
│ Setup         | 🎯 SilverBullet↑│
├───────────────────────────────┤
│ FVG active    | ↑3 ↓1        │
│ Sweep         | Low swept    │
│ SMT           | Bullish div  │
├───────────────────────────────┤
│ Balance       | $10,000      │
│ Risk/trade    | 0.5% = $50   │
│ Suggest SL    | 2395.50      │
│ Suggest TP    | 2410.00      │
│ Lots (est)    | 0.05         │
└───────────────────────────────┘
```

### Sur le chart
- 🟢 **Boxes vertes** = FVG bullish (opportunités longs)
- 🔴 **Boxes rouges** = FVG bearish (opportunités shorts)
- 📦 **Rectangles** = Order Blocks
- 📏 **Lignes pointillées rouges** = Buy stops (liquidité au-dessus)
- 📏 **Lignes pointillées vertes** = Sell stops (liquidité en-dessous)
- 🔵 **Lignes cyan** = PDH / PDL (previous day)
- 🟡 **Lignes jaunes** = PWH / PWL (previous week)
- 🎯 Label **"SB"** = Silver Bullet détecté
- 🔄 Label **"J"** = Judas Swing détecté
- ⚡ Triangle **"PO3"** = Power of Three détecté

### Background color (quand setup actif)
- 💜 Violet = Grade S
- 💚 Vert = Grade A+
- 💛 Jaune = Grade A
- (transparent) = Pas de setup

### Killzones highlighting
- 🔵 Bleu clair = London KZ
- 🟠 Orange = NY AM KZ
- 🔴 Rouge = NY PM KZ
- 🟣 Violet = Asia KZ

---

## 💡 Tips pro

1. **Utilise sur timeframe H1 minimum** (pas trop de noise)
2. **Attends le Grade A+** pour trader (ne pas tout prendre)
3. **Vérifie Multi-TF** avant d'entrer (W↑ D↑ H4↑ H1↑)
4. **Respecte le regime** : évite MANIPULATION
5. **Utilise les killzones** : les A+ en killzone sont les meilleurs
6. **Combine avec ton bot AWS** : le bot exécute, TV t'alerte

---

## 🎓 Workflow idéal

### Ton setup complet maintenant
1. **AWS Bot** : exécute automatiquement les A+ sur MT5 ✅
2. **TradingView Indicator** : t'affiche visuellement + alerte push iPhone ✅
3. **Telegram Bot** : confirmations + commandes d'urgence ✅
4. **Dashboard Streamlit** : analyse web + app iPhone ✅

**Redondance parfaite** → si un canal tombe, les 3 autres t'alertent.

---

## 🐛 Troubleshooting

### "No plot displayed"
→ Vérifie que le script est bien "Added to chart" (bouton en haut de l'éditeur)

### "Error on calculation"
→ Recharge la page TradingView (F5)

### Dashboard ne s'affiche pas
→ Vérifie `show_dash` = true dans les settings

### Pas d'alerte qui arrive
→ Vérifie l'alerte est créée (Alert list en haut à droite)
→ Vérifie "Send notification to TradingView app" est coché
→ Ouvre TradingView app iPhone → Settings → Notifications = ON

### "Max 4 securities" error
→ C'est une limitation Pine Script Free
→ Désactive `use_cross` (cross-asset) ou prends TV Premium

---

## 🚀 Prochaines étapes (si tu veux aller + loin)

### v2 possible
- 🤖 **AI signal filter** : ML sur les 100 derniers setups pour score probabiliste
- 📊 **Real-time backtest stats** overlay
- 🔄 **Auto-adjust** confluence threshold selon winrate récent
- 🎯 **Institutional footprint** via volume profile
- 🌊 **Order flow imbalance** detection
- 📉 **Mean reversion opportunities**

### Publish sur TV
- **Mode "Invite-only"** : payant pour abonnés
- **Mode "Public"** : gratuit, build ta réputation ICT
- **Script Premium** : vente sur Gumroad

---

## 🎯 Crédits

**Développé par** : David Ghali (@Davghali)
**Design & code** : Claude + David
**Version** : 1.0 (2026-04-20)
**Licence** : Privé, usage personnel

---

**Bon trading, et que les A+ soient avec toi !** 💎🚀
