# ARCHITECTURE — ICT System v1

> Version 1.0 — Phase A.1 — 2026-04-21
> Spec: [PROMPT_ULTIME_ICT_TRADINGVIEW.md](../../PROMPT_ULTIME_ICT_TRADINGVIEW.md)

---

## 1. Design principles

The ICT system is built on 5 non-negotiable principles:

1. **Pure ICT methodology** — no classical indicators (no MA, RSI, MACD, Bollinger, etc.).
2. **Modular** — each ICT concept in its own function inside a dedicated library.
3. **Non-repainting** — strict use of `barstate.isconfirmed` + `lookahead_off`.
4. **Phase-by-phase** — no Phase B until Phase A meets exit criteria (§ 10 of master prompt).
5. **FTMO-compliant by default** — risk 0.5%, max daily loss 2%, max total DD 5%.

---

## 2. Folder structure

```
ict_system/
├── libraries/                       # Pine v6 libraries (published to TV for reuse)
│   ├── ict_core.pine               # PO3, Opens, FVG, IFVG, BPR, OB, BB
│   ├── ict_structure.pine          # BOS, CHoCH, CISD, MSS, Premium/Discount
│   ├── ict_liquidity.pine          # PDH/PDL/PWH/PWL/PMH/PML, KZ H/L, EQH/EQL
│   ├── ict_filters.pine            # News, KZ, SMT, DXY correlation
│   └── ict_risk.pine               # Sizing, SL clamps, TP, DD tracking
├── strategy/
│   └── ict_strategy_v1.pine        # Phase A — strategy() for backtest
├── indicator/
│   └── ict_indicator_v1.pine       # Phase B — indicator() + webhook alerts
├── docs/
│   ├── ARCHITECTURE.md             # This file
│   ├── CHANGELOG.md                # Iteration log
│   ├── PINE_V6_LIMITATIONS.md      # Known Pine v6 constraints + workarounds
│   ├── USER_GUIDE.md               # (Phase B.4) End-user documentation
│   ├── BACKTEST_REPORT.md          # (Phase A.8) Performance metrics
│   └── WEBHOOK_SPEC.md             # (Phase B) Alert JSON format spec
└── backtests/
    └── results_YYYYMMDD.csv        # Exported trade logs per iteration
```

---

## 3. Library separation rationale

Each library has a single responsibility (§ 7.1 of master prompt):

| Library | Responsibility | Lines (est.) |
|---------|----------------|--------------|
| `ict_core` | Detection primitives (PO3, Opens, FVG, OB, BB) | 400-600 |
| `ict_structure` | Structure logic (BOS, CHoCH, CISD, Premium/Discount) | 300-500 |
| `ict_liquidity` | Liquidity pools (time-based + EQH/EQL) | 250-400 |
| `ict_filters` | Entry filters (KZ, news, SMT, DXY) | 300-500 |
| `ict_risk` | Position sizing + DD halts + trade management | 250-400 |

**Why 5 libs instead of 1 monolith?**
- Each lib stays well under the 100kb Pine lib size limit.
- Parallel editing (future) without merge conflicts.
- Clear responsibility boundaries — easier to audit for overfit/repaint.
- Reusable across strategy AND indicator (Phase A + Phase B share libs).

**Why not more libs (e.g., separate `ict_po3`, `ict_fvg`, `ict_ob`)?**
- Over-granularity hurts readability. PO3 + Opens + FVG are all detection primitives used together.
- Pine v6 import overhead (each library import = 1 declaration).

---

## 4. Phase-by-phase delivery

| Phase | Scope | Exit criterion |
|-------|-------|----------------|
| **A.1** | Skeleton + 9 input groups | ✅ Compiles clean on TV |
| A.2 | Implement all `f_*` detection functions in the 5 libraries | Each concept visualizable at chart |
| A.3 | Daily + Weekly bias engine | Bias label matches manual chart reading |
| A.4 | Continuation setup logic | Entries visible, CSV log exportable |
| A.5 | Reversal setup logic | Entries visible, CSV log exportable |
| A.6 | All 4 filters (KZ, news, SMT, DXY) | Filter stats visible in report |
| A.7 | Risk management (sizing, SL/TP, DD halts) | Position sizes verified manually |
| A.8 | Full performance report | BACKTEST_REPORT.md produced |
| A.9 | Walk-forward + out-of-sample | In/OOS delta ≤ 15% WR |
| **B.1** | Convert to indicator | 100% signal parity w/ strategy |
| B.2 | JSON webhook alerts | Payload tested on 5 historical setups |
| B.3 | Chart UI (zones, labels) | No clutter, readable for trader |
| B.4 | USER_GUIDE.md | Complete end-user docs |

**Exit criterion from Phase A → B** (§ 10 master prompt):
- WR OOS ≥ 55%
- Profit Factor ≥ 1.3
- Max DD ≤ 10%
- If ANY not met → iterate, don't advance.

---

## 5. Naming conventions

| Element | Convention | Example |
|---------|------------|---------|
| Variable | `snake_case` | `swept_low`, `bias_daily` |
| Function | `f_` prefix + snake_case | `f_po3_daily()`, `f_detect_fvg_bull()` |
| Constant | `SC_` prefix | `SC_BULL`, `SC_PO3_ACCUM` |
| Input variable | `g{N}_` group prefix | `g1_bias`, `g6_risk` |
| Section header | `// ═══ SECTION ═══` | Uses heavy double-line box drawing |
| Phase marker | `// [A.X] Description` | `// [A.2] Implement PO3 here` |

---

## 6. Non-repainting discipline

Every detection MUST respect these rules:

1. **`barstate.isconfirmed`** guard on all entry signals — never signal mid-bar.
2. **`request.security()`** always with `lookahead = barmerge.lookahead_off`.
3. **`ta.pivothigh` / `ta.pivotlow`** with explicit `lookback_right` (default 3) — accept the natural delay, don't try to avoid it.
4. **No `[0]` references** in conditions that cause future-knowledge bias.
5. **Historical alerts** : documented that they work on bar-close only (1-bar delay).

---

## 7. Input organization

9 input groups per § 8 of master prompt. Group order in UI:

1. `🎯 Biais & Structure` (most critical — determines all setups)
2. `💧 Liquidités` (external targets)
3. `📦 PD Arrays` (internal entries)
4. `⏰ Killzones` (timing filter)
5. `🔁 Corrélation / SMT` (confirmation layer)
6. `🛡️ Risk Management` (position sizing)
7. `🚫 Filtres` (hard blocks)
8. `🎨 Affichage` (cosmetics)
9. `🔔 Alertes` (webhook config)

Variable prefix `g{N}_` denotes group number so that input groups remain visually clustered in the code.

---

## 8. Strategy execution parameters

`strategy()` header values (all spec-compliant):

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `initial_capital` | 10000 | FTMO Swing 10k reference |
| `default_qty_type` | `strategy.percent_of_equity` | Equity-based sizing |
| `default_qty_value` | 100 | Will be overridden by computed risk % |
| `commission_type` | `strategy.commission.percent` | Realistic broker model |
| `commission_value` | 0.01 | 0.01% per side (OANDA realistic) |
| `slippage` | 2 | 2 ticks (conservative) |
| `pyramiding` | 0 | 1 trade at a time — no scaling |
| `process_orders_on_close` | true | Prevents look-ahead |
| `max_boxes_count` | 500 | Max objects for chart UI |
| `max_lines_count` | 500 | Max lines for liquidity + TP levels |
| `max_labels_count` | 500 | Max text labels |
| `max_bars_back` | 1000 | Sufficient for swing lookbacks |

---

## 9. Webhook payload format (Phase B preview)

```json
{
  "action": "buy|sell",
  "symbol": "{{ticker}}",
  "price": {{close}},
  "sl": <price>,
  "tp1": <price>,
  "tp2": <price>,
  "setup_type": "continuation|reversal",
  "kz": "london|ny_am|ny_pm|asia",
  "bias_daily": "bull|bear",
  "bias_weekly": "bull|bear",
  "confidence_score": 0.0,
  "rr_target": 2.0,
  "risk_pct": 0.5,
  "timestamp": "{{time}}"
}
```

Constraint: total payload < 4096 chars (TV webhook limit).

---

## 10. What's NOT in scope (pas de dérive)

Explicitly excluded to avoid scope creep:

- ❌ No ML models (no xgboost, no neural nets) — ICT is rule-based
- ❌ No alternative data (no COT, no sentiment) — spec is pure price action
- ❌ No multi-asset portfolio allocation — 1 strategy per chart
- ❌ No auto-optimization — user-driven via Strategy Tester Properties
- ❌ No custom broker integration in Phase A — TV backtest only

These may become separate systems later, but are out of scope for the ICT system per master prompt.
