# PROMPT ULTIME — STRATÉGIE ICT AUTOMATISÉE POUR TRADINGVIEW

> **Comment utiliser ce prompt :** Copie l'intégralité de ce document dans Claude Code (de préférence via un fichier `.md` posé à la racine du projet). Demande à Claude Code de lire ce document en entier avant d'écrire une seule ligne de code, puis de suivre strictement la **roadmap par phases**. Ne saute aucune phase. À chaque fin de phase, valide les livrables avant de continuer.

---

## 🎯 0. MISSION

Tu es un expert en développement **Pine Script v5** spécialisé dans la méthodologie **ICT (Inner Circle Trader)**. Ta mission est de construire un système de trading complet, en deux livrables successifs :

1. **Phase A — Strategy Pine Script v5** : pour backtester, mesurer, optimiser, poncer les chiffres.
2. **Phase B — Indicator Pine Script v5** : une fois la stratégie validée, convertir en indicateur avec alertes webhook pour automatiser l'exécution sur propfirm (FTMO, The5ers, etc.).

**Critères de succès mesurables :**
- Code modulaire, lisible, chaque concept ICT dans sa propre fonction/library.
- Pas de repainting. Pas de look-ahead bias. Utilisation rigoureuse de `barstate.isconfirmed` et des séries historiques.
- Backtest reproductible (seed fixe, paramètres documentés).
- Rapport de performance détaillé (voir section 10).
- Walk-forward obligatoire avant de passer en Phase B.

---

## 👤 1. CONTEXTE DU TRADER (ne pas inventer, respecter à la lettre)

- **Méthodologie** : ICT pure (pas de moyennes mobiles, pas de RSI, pas d'indicateurs classiques).
- **Style** : scalping & intraday, jamais de swing multi-jours.
- **Instruments** : EURUSD, GBPUSD, US30, NAS100, SP500, BTCUSD, ETHUSD, XAUUSD, XAGUSD. DXY utilisé uniquement en **corrélation / SMT**.
- **Broker** : OANDA sur TradingView.
- **Propfirm** : FTMO, The5ers — donc drawdown quotidien et total à respecter.
- **Risk management** :
  - 0.5% de risque par trade.
  - RR cible : 2R ou 3R.
  - SL max sur EURUSD : ~20 pips. Adapté par instrument (ATR-based fallback).
- **Fréquence** : 2 trades/jour en moyenne, uniquement en Killzones, hors news rouges.
- **News à filtrer obligatoirement** : NFP, FOMC, CPI, PPI, toute news rouge ForexFactory / prop firm.

---

## 🧭 2. ROADMAP PAR PHASES

### PHASE A — STRATEGY (à valider AVANT la Phase B)

| Étape | Livrable | Critère de sortie |
|-------|----------|-------------------|
| A.1 | Squelette Pine v5 `strategy()` + inputs | Compile sans erreur |
| A.2 | Bibliothèque de détection des concepts ICT (PO3, opens, liquidités, PD arrays, structure) | Chaque concept visualisable au chart |
| A.3 | Moteur de biais daily & weekly | Biais imprimé en label, cohérent à la main |
| A.4 | Logique Setup Continuation | Entries visibles, log CSV |
| A.5 | Logique Setup Reversal | Entries visibles, log CSV |
| A.6 | Filtres (KZ, news, SMT, corrélation DXY) | Entries filtrées correctement |
| A.7 | Risk management (0.5%, RR, SL adaptatif) | Taille de position correcte |
| A.8 | Rapport de performance complet | Métriques section 10 |
| A.9 | Walk-forward & out-of-sample | Rapport comparatif in-sample vs OOS |

### PHASE B — INDICATOR + ALERTES

| Étape | Livrable | Critère de sortie |
|-------|----------|-------------------|
| B.1 | Conversion `strategy()` → `indicator()` | Même signaux que Phase A |
| B.2 | Système d'alertes JSON webhook-ready | Payload testé |
| B.3 | Affichage graphique des zones et setups | UX propre, pas de surcharge |
| B.4 | Documentation utilisateur | Markdown `USER_GUIDE.md` |

> **RÈGLE ABSOLUE** : ne démarre jamais la Phase B tant que la Phase A ne produit pas des résultats statistiquement robustes (voir section 10).

---

## 🧱 3. CONCEPTS ICT À IMPLÉMENTER (SPÉCIFICATIONS DÉTAILLÉES)

Chaque concept doit être une **fonction séparée** dans une `library` Pine v5 nommée `ict_core`, pour réutilisation en strategy ET en indicator.

### 3.1 Power of Three (PO3)

**Définition** : une bougie Daily/Weekly se décompose en 3 phases — Accumulation → Manipulation → Distribution.

**Implémentation attendue** :
```
f_po3_daily() :
  - Accumulation = range entre Daily Open (00:00 NY) et début Asia KZ
  - Manipulation = wick qui dépasse Accumulation range (souvent en Asia ou début London)
  - Distribution = corps de la bougie qui expanse dans la direction inverse de la manipulation
  - Retourne {phase: "accum"|"manip"|"distrib", direction: "bull"|"bear"|"neutral"}
```

Idem pour `f_po3_weekly()` basé sur Weekly Open (dimanche 17:00 NY ou lundi 00:00 NY — **paramétrable**).

### 3.2 Opens de référence (à tracer en lignes)

- **Midnight Open** : 00:00 New York time, timeframe chart.
- **Daily Open** : identique Midnight Open (équivalent ICT).
- **Weekly Open** : lundi 00:00 NY (ou dimanche 17:00 NY si futures session).
- **True Day Open** : 00:00 NY (variante utilisée par certains ICT traders comme pivot d'équilibre).

Chaque open doit être une ligne horizontale qui s'étend jusqu'à la fin de sa période, paramétrable en couleur/style.

### 3.3 Liquidités externes (Time-Based)

À détecter et tracer :
- **PDH / PDL** (Previous Day High/Low)
- **PWH / PWL** (Previous Week High/Low)
- **PMH / PML** (Previous Month High/Low)
- **Previous KZ High/Low** pour chaque Killzone (Asia, London, NY AM, NY Lunch, NY PM)
- **EQH / EQL** : Equal Highs/Lows (2+ wicks dans une tolérance de `eq_tolerance_pips`, paramétrable, défaut 2 pips sur EURUSD, adapté par instrument)
- **Relative EQH/EQL** : tolérance plus large (défaut 5 pips)

**Chaque niveau doit avoir un état : `active` / `swept` / `expired`** — trace-le différemment (ligne pleine → pointillée après sweep).

### 3.4 Liquidités internes (PD Arrays)

- **FVG (Fair Value Gap)** : 3 bougies, gap entre high[2] et low[0] (bullish) ou low[2] et high[0] (bearish). Tag `mitigated` quand le prix revient dans la zone.
- **IFVG (Inverted FVG)** : un FVG qui a été traversé en clôture par le corps d'une bougie → devient support/résistance inversé.
- **BPR (Balanced Price Range)** : chevauchement d'un FVG bullish et d'un FVG bearish. Zone de haute réactivité.
- **OB (Order Block)** : dernière bougie de direction opposée avant un mouvement impulsif qui (a) prend de la liquidité, (b) délivre un FVG, (c) crée un BOS. **Les 3 conditions doivent être vérifiées, sinon ce n'est pas un OB valide.**
- **BB (Breaker Block)** : OB qui a été invalidé (cassé) puis qui agit comme support/résistance inversé après un CHoCH.

### 3.5 Structure de marché

- **BOS (Break of Structure)** : clôture **du corps** au-delà du dernier swing dans le sens du trend. Paramètre : `bos_body_close = true`.
- **CHoCH (Change of Character)** : prise de liquidité time-based + formation d'un BB + IFVG sur l'UT d'analyse.
- **CISD (Change in State of Delivery)** : séquence prise de liquidité + OB + FVG qui confirme le renversement sur l'UT de confirmation.
- **MSS (Market Structure Shift)** : synonyme de CHoCH utilisé par certains ICT. À implémenter comme alias.

### 3.6 Premium / Discount / Equilibrium

Calculé sur le dernier swing range (high swing le plus récent — low swing le plus récent) :
- **Premium** : > 50% du range
- **Discount** : < 50% du range
- **Equilibrium** : zone 45%-55% (paramétrable)

**Règle** : en continuation bullish, on veut entrer en **Discount**. En bearish, en **Premium**. Exception : si un **BB** est présent dans la zone opposée, le prix peut l'atteindre (override possible, **paramétrable** `bb_overrides_pd = true`).

### 3.7 Killzones (heure New York)

| KZ | Début | Fin |
|----|-------|-----|
| Asia | 20:00 | 00:00 |
| London | 02:00 | 05:00 |
| NY AM | 09:30 | 11:00 |
| NY Lunch (no trade) | 12:00 | 13:00 |
| NY PM | 13:30 | 16:00 |

Paramétrables via inputs. Affichage en fond coloré semi-transparent.

### 3.8 SMT Divergences (CRITIQUE — attention aux limites Pine)

Paires à surveiller :
- EURUSD ↔ DXY (inversée)
- EURUSD ↔ GBPUSD (normale, via DXY implicite)
- XAUUSD ↔ XAGUSD
- NAS100 ↔ SP500
- BTCUSD ↔ ETHUSD

**Définition SMT** : si l'asset A fait un nouveau high/low mais l'asset B corrélé ne le fait pas → divergence → signal de retournement potentiel.

**Implémentation Pine v5** :
```
request.security(symbol_corr, timeframe.period, close, lookahead=barmerge.lookahead_off)
```
Toujours `lookahead=barmerge.lookahead_off` pour éviter le repainting.

> ⚠️ Pine Script v5 limite `request.security` à ~40 appels. Optimise pour ne charger que la paire corrélée pertinente à l'instrument actif (via `syminfo.ticker`).

### 3.9 Timeframe Alignement

| UT Analyse (HTF) | UT Confirmation (LTF) |
|------------------|-----------------------|
| Daily | H1 |
| H4 | M15 |
| H1 | M5 |
| M15 | M1 |

**Implémentation** : l'indicateur tourne sur l'UT de confirmation, mais récupère via `request.security` les PD arrays de l'UT d'analyse correspondante. Un input `htf_mapping` permet de choisir le mapping ou de laisser auto-détection.

---

## 🎯 4. LOGIQUE DE TRADING (LE CŒUR)

### 4.1 Détermination du biais

**Biais Weekly** (rafraîchi chaque début de semaine) :
- PO3 weekly (phase + direction)
- Weekly Open vs prix actuel (au-dessus = biais bull, en-dessous = bear)
- Nature de la bougie weekly précédente (expansion / retournement / hésitation)

**Biais Daily** (rafraîchi chaque 00:00 NY) :
- PO3 daily
- Midnight Open vs prix
- Cohérence avec biais weekly
- Asia range balayé dans quel sens au début de London → indicateur de direction

Output : `bias_daily = "bull" | "bear" | "neutral"` et `bias_weekly = idem`.

**Règle** : ne prendre que les setups dans le sens du biais daily ET weekly alignés. Si conflit weekly/daily, `require_alignment = true` bloque les entries (paramétrable).

### 4.2 Setup CONTINUATION

**Conditions sur UT d'analyse (HTF)** :
1. Biais daily clair et aligné weekly.
2. Prix dans un PD array valide : **OB + FVG** dans la zone correcte (Discount si bull, Premium si bear).
3. Prix au-dessus (bull) ou en-dessous (bear) du Daily Open / Midnight Open selon le biais.

**Conditions sur UT de confirmation (LTF)** dans la KZ active :
1. Sweep d'une liquidité interne ou mineure (ex: low Asian en London pour un long).
2. Formation d'un **CISD** = Breaker Block + IFVG dans le sens du biais.
3. Entrée sur le retest du BB ou du FVG nouvellement formé.

**Entry** : limit order au 50% du FVG de confirmation OU au retest du BB.
**SL** : juste au-delà du sweep qui a déclenché le CISD (+ 2-3 pips de buffer).
**TP** : prochaine liquidité externe dans le sens du biais (PDH/PDL, PWH/PWL, EQH/EQL). Si RR < 2 → pas de trade.

### 4.3 Setup REVERSAL

**Conditions sur UT d'analyse (HTF)** :
1. Prise de liquidité externe time-based (PDH, PWH, EQH, etc.) contre le biais précédent.
2. Formation d'un **BB + IFVG** qui invalide la structure précédente.
3. (Optionnel mais recommandé) SMT divergence avec paire corrélée.

**Conditions sur UT de confirmation (LTF)** :
1. Sweep interne.
2. **CISD** = OB + FVG dans le nouveau sens.
3. Entrée sur retest.

**Entry / SL / TP** : même logique que Continuation, SL au-delà du high/low qui a pris la liquidité externe.

### 4.4 Gestion des killzones

- **London** : peut être continuation ou reversal selon Asian range (asian sweep = reversal potentiel).
- **NY AM** : souvent continuation de London, ou reversal si London a été extrême.
- **NY PM** : souvent reversal du NY AM, ou continuation si tendance forte.

Un input `kz_mode = {auto, continuation, reversal, both}` paramètre le comportement attendu.

---

## 🛡️ 5. RISK MANAGEMENT

```
risk_pct = input.float(0.5, "Risque % par trade", step=0.1)
rr_target_1 = input.float(2.0, "RR Target 1")
rr_target_2 = input.float(3.0, "RR Target 2")
partial_tp1_pct = input.float(50, "% fermé au TP1")
breakeven_on_tp1 = input.bool(true, "Breakeven après TP1")
max_sl_pips = input.float(20, "SL max en pips (EURUSD ref)")
max_daily_trades = input.int(4, "Max trades par jour")
max_daily_loss_pct = input.float(2.0, "Perte max quotidienne %")
max_total_dd_pct = input.float(5.0, "Drawdown total max %")
```

**Taille de position** : calcul automatique basé sur `risk_pct`, distance SL en pips, et valeur du pip (via `syminfo.pointvalue`).

**Scaling SL par instrument** (table paramétrable) :
- EURUSD/GBPUSD : 20 pips max
- XAUUSD : 300 pips max (3$)
- NAS100/SP500 : 30 points max
- US30 : 50 points max
- BTCUSD : 0.8% du prix
- ETHUSD : 1.0% du prix

---

## 🚫 6. FILTRES OBLIGATOIRES

### 6.1 Filtre News

Deux approches à coder :
1. **Statique** : table CSV paramétrable avec dates/heures des news rouges connues.
2. **Dynamique** : via alerts externes webhook ForexFactory (Phase B uniquement — en Phase A, la table statique suffit pour le backtest).

Bloque toute entrée dans la fenêtre `news_buffer_before = 30 min` avant à `news_buffer_after = 30 min` après.

### 6.2 Filtre Killzones

Aucune entrée hors KZ configurées. Aucune entrée en NY Lunch (12:00-13:00 NY).

### 6.3 Filtre SMT / Corrélation DXY

Pour EURUSD/GBPUSD : si DXY ne confirme pas (pas de mouvement inverse cohérent), le trade est bloqué (paramétrable `require_dxy_confirmation = true`).

### 6.4 Filtre Max Trades / Max Drawdown

Hard stop : si `daily_loss >= max_daily_loss_pct` OU `total_dd >= max_total_dd_pct`, plus aucune entrée jusqu'au reset (quotidien ou manuel).

---

## 🏗️ 7. ARCHITECTURE TECHNIQUE

### 7.1 Structure des fichiers

```
/ict_system
  /libraries
    ict_core.pine              # Détections ICT (PO3, OB, FVG, etc.)
    ict_structure.pine         # BOS, CHoCH, CISD, MSS
    ict_liquidity.pine         # Liquidités externes et internes
    ict_filters.pine           # News, KZ, SMT, corrélation
    ict_risk.pine              # Sizing, SL/TP, DD tracking
  /strategy
    ict_strategy_v1.pine       # Phase A - strategy() principal
  /indicator
    ict_indicator_v1.pine      # Phase B - indicator() + alertes
  /docs
    USER_GUIDE.md
    BACKTEST_REPORT.md
    WEBHOOK_SPEC.md
  /backtests
    results_YYYYMMDD.csv
```

### 7.2 Conventions de code

- Nommage : `snake_case` pour les variables, `f_` préfixe pour les fonctions, `SC_` pour les constantes.
- Commentaires structurés `// ═══ SECTION ═══`.
- Chaque input a un `group=` et un `tooltip=` explicite.
- Pas de magic numbers : tout paramétrable.
- `// @version=5` obligatoire.

### 7.3 Gestion du repainting

- Toutes les détections utilisent `barstate.isconfirmed` pour les signaux d'entrée.
- `request.security()` toujours avec `lookahead=barmerge.lookahead_off`.
- Les swing points utilisent `ta.pivothigh/pivotlow` avec `lookback_right` explicite (défaut 3) — accepter le décalage naturel plutôt que tricher.

### 7.4 Format des alertes (Phase B)

JSON webhook compatible avec un bridge type `TradingView → FTMO/OANDA` :

```json
{
  "action": "{{strategy.order.action}}",
  "symbol": "{{ticker}}",
  "price": {{close}},
  "sl": {{strategy.order.contracts}},
  "tp": "...",
  "setup_type": "continuation|reversal",
  "kz": "london|ny_am|ny_pm",
  "bias_daily": "bull|bear",
  "confidence_score": 0.0,
  "rr_target": 2.0,
  "risk_pct": 0.5,
  "timestamp": "{{time}}"
}
```

---

## 📊 8. INPUTS ATTENDUS (à exposer à l'utilisateur)

**Groupes obligatoires :**
1. `🎯 Biais & Structure` — toggles PO3, BOS body-close, etc.
2. `💧 Liquidités` — lookbacks, tolérances EQH/EQL
3. `📦 PD Arrays` — détection OB/FVG/IFVG/BB/BPR
4. `⏰ Killzones` — heures début/fin par KZ, timezone
5. `🔁 Corrélation / SMT` — symboles corrélés, seuils
6. `🛡️ Risk Management` — risk%, RR, SL max, limites journalières
7. `🚫 Filtres` — news, KZ, SMT, max trades
8. `🎨 Affichage` — couleurs, transparence, labels on/off
9. `🔔 Alertes` — mode, format JSON

---

## 📈 9. BACKTEST & OPTIMISATION

### 9.1 Données requises

- Minimum **3 ans** d'historique par instrument.
- Séparation **in-sample (70%)** / **out-of-sample (30%)**.
- Walk-forward sur fenêtres glissantes de 6 mois.

### 9.2 Méthodologie

1. Optimisation des inputs sur in-sample uniquement.
2. Validation sur out-of-sample sans retouche.
3. Test Monte Carlo sur l'ordre des trades (1000 itérations) pour mesurer la robustesse.
4. Test de sensibilité : ±10% sur chaque paramètre clé. Si la perf s'effondre → overfit.

### 9.3 Pièges à éviter (à documenter dans le code)

- ❌ Optimiser les heures de KZ par instrument (overfit classique).
- ❌ Élargir `eq_tolerance_pips` jusqu'à ce que ça marche.
- ❌ Ajouter des conditions ad-hoc qui éliminent les pertes connues.
- ❌ Ignorer le slippage et les spreads (intégrer au minimum le spread moyen OANDA par instrument).

---

## ✅ 10. RAPPORT DE PERFORMANCE (livrable obligatoire Phase A.8)

Claude Code doit produire un fichier `BACKTEST_REPORT.md` avec :

**Métriques par instrument et globales :**
- Total trades, wins, losses
- Win rate (honnête — pas de filtrage post-hoc)
- Profit factor
- Expectancy (R multiple)
- Max drawdown (% et absolu)
- Max drawdown duration (jours)
- Sharpe ratio, Sortino ratio
- Distribution des R (histogramme)
- Moyenne RR réalisé vs cible
- Trades par KZ (London/NY AM/NY PM)
- Trades par setup (continuation vs reversal)
- Performance par jour de la semaine
- Performance par mois / saisonnalité

**Tests de robustesse :**
- In-sample vs out-of-sample (écart max accepté : 15% sur win rate).
- Monte Carlo : 95e percentile du drawdown.
- Sensibilité aux paramètres clés.

**⚠️ Critère d'arrêt / de passage en Phase B :**
- Si win rate OOS < 55% OU profit factor < 1.3 OU max DD > 10% → **retour itératif**, pas de Phase B.

---

## 🔁 11. GUIDE D'ITÉRATION

Quand les résultats sont décevants, privilégier dans l'ordre :
1. **Revoir la définition d'un concept** (ex: OB trop strict ou trop laxiste).
2. **Affiner les filtres** (KZ plus étroites, news plus larges).
3. **Revoir le mapping HTF/LTF** (peut-être H1 → M1 au lieu de M5).
4. **Jamais** ajouter un filtre qui élimine spécifiquement les pertes vues en backtest.

À chaque itération, logguer dans `CHANGELOG.md` :
- Date, hypothèse testée, métrique avant/après, décision (garder/rollback).

---

## 🎁 12. LIVRABLES FINAUX ATTENDUS

### Fin de Phase A
- [ ] `ict_strategy_v1.pine` fonctionnel, sans erreur, modulaire.
- [ ] Libraries `ict_*.pine` exportées et documentées.
- [ ] `BACKTEST_REPORT.md` complet sur les 9 instruments.
- [ ] `CHANGELOG.md` des itérations.
- [ ] Validation walk-forward documentée.

### Fin de Phase B
- [ ] `ict_indicator_v1.pine` qui reproduit à 100% les signaux Phase A.
- [ ] Alertes JSON webhook testées sur au moins 5 setups historiques.
- [ ] `USER_GUIDE.md` : installation, inputs, lecture des signaux, setup webhook.
- [ ] `WEBHOOK_SPEC.md` : format exact, exemples, mapping vers broker.

---

## 📜 13. RÈGLES ABSOLUES POUR CLAUDE CODE

1. **Tu ne codes jamais sans avoir lu ce document en entier.**
2. **Tu travailles phase par phase.** Pas de saut.
3. **Tu n'inventes pas** de règles ICT qui ne sont pas dans ce document. Si un point est ambigu, tu demandes confirmation avant de coder.
4. **Tu documentes chaque fonction** avec un header expliquant : but, inputs, outputs, hypothèses, limites connues.
5. **Tu refuses d'overfit.** Si un résultat de backtest semble "trop beau" (WR > 80% sur OOS), tu alertes et demandes une revue.
6. **Tu ne mens pas sur les limites de Pine Script.** Si une feature demande un workaround (ex: SMT limité par le nombre de `request.security`), tu l'explicites dans le code et la doc.
7. **Tu n'ajoutes pas de code "pour faire joli".** Chaque ligne doit servir une des règles de ce document.
8. **Tu proposes des tests unitaires simples** (au minimum : bar replay sur 5 setups historiques manuellement validés par le trader).

---

## 🚀 14. DÉMARRAGE

**Premier message à envoyer à Claude Code après lui avoir transmis ce document** :

> Lis intégralement `PROMPT_ULTIME_ICT_TRADINGVIEW.md`.
> Puis :
> 1. Produis un résumé en 10 points de ce que tu vas construire, en indiquant explicitement les points où tu anticipes des limitations Pine Script.
> 2. Propose un plan détaillé pour la Phase A.1 (squelette + inputs) avec la liste exacte des fichiers que tu vas créer.
> 3. Attends ma validation avant d'écrire du code.

---

**Fin du prompt ultime.**
*Version 1.0 — ajuste ce document avant chaque nouvelle itération majeure.*
