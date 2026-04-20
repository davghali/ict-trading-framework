# CHANGELOG — ICT System v1

Following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.
Versions follow `v{phase}.{step}-{iteration}` scheme (e.g., `vA.1-1` = Phase A, Step 1, Iteration 1).

---

## [vA.1-1] — 2026-04-21

### Added
- Initial project structure under `/ict_system/`
- `strategy/ict_strategy_v1.pine` — Pine v6 strategy skeleton
  - `strategy()` header with FTMO-ready parameters (10k capital, 0.5% risk target, 0.01% commission, 2 ticks slippage, no pyramiding)
  - All 9 input groups implemented per master prompt § 8
    - `🎯 Biais & Structure` (5 inputs)
    - `💧 Liquidités` (7 inputs)
    - `📦 PD Arrays` (7 inputs)
    - `⏰ Killzones` (11 inputs)
    - `🔁 Corrélation / SMT` (4 inputs)
    - `🛡️ Risk Management` (17 inputs)
    - `🚫 Filtres` (6 inputs)
    - `🎨 Affichage` (12 inputs)
    - `🔔 Alertes` (2 inputs)
  - Every input has `group=` and `tooltip=` per spec § 7.2
  - Skeleton compile-check block ensuring all inputs are referenced
- `libraries/ict_core.pine` — skeleton with documented stubs for PO3, Opens, FVG, IFVG, BPR, OB, BB detection
- `libraries/ict_structure.pine` — skeleton with stubs for BOS, CHoCH, CISD, MSS, Premium/Discount
- `libraries/ict_liquidity.pine` — skeleton with stubs for PDH/PDL, PWH/PWL, PMH/PML, KZ H/L, EQH/EQL
- `libraries/ict_filters.pine` — skeleton with stubs for KZ, news, SMT, DXY correlation filters
- `libraries/ict_risk.pine` — skeleton with stubs for position sizing, SL clamps, DD tracking
- `docs/ARCHITECTURE.md` — design principles, folder structure, naming conventions, phase roadmap
- `docs/PINE_V6_LIMITATIONS.md` — 10 known Pine v6 limits + workarounds documented
- `docs/CHANGELOG.md` — this file
- `README.md` — project overview + quick start

### Exit criterion A.1
- ✅ Strategy file compiles without error on TradingView Pine Editor
- ✅ All 9 input groups visible in Properties dialog
- ✅ No trading logic yet (by design)
- ✅ No magic numbers (100% via inputs)

### Decisions
- **Folder separation** : new `/ict_system/` root kept apart from legacy `/tradingview/` (V1-V4) to avoid confusion
- **5 libraries** (core / structure / liquidity / filters / risk) over monolith — rationale in ARCHITECTURE.md § 3
- **Pine v6** confirmed (user updated from v5 spec)
- **Weekly Open default** : "Sunday 17:00 NY" (futures convention) — user can switch to Monday 00:00 NY
- **KZ defaults** : 20-00 Asia, 02-05 London, 09:30-11 NY AM, 13:30-16 NY PM per master prompt § 3.7
- **OB strict mode** : default TRUE — requires all 3 conditions (sweep + FVG + BOS) per § 3.4
- **BOS body close** : default TRUE per § 3.5

### Next
- `[vA.2-1]` — implement ICT core detections in `ict_core.pine` + `ict_structure.pine`
- Each function must have a pinned test case (manual validation setup from bar replay)

---

## Template for future entries

```markdown
## [vA.X-Y] — YYYY-MM-DD

### Hypothesis tested
- What you thought would improve metric X

### Metric before → after
- WR : 48% → 55%
- PF : 1.2 → 1.6
- Max DD : 8% → 6%

### Decision
- ✅ KEEP / ❌ ROLLBACK

### Reason
- Explanation
```
