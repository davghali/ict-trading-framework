# CHANGELOG — ICT System v1

Following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.
Versions follow `v{phase}.{step}-{iteration}` scheme (e.g., `vA.1-1` = Phase A, Step 1, Iteration 1).

---

## [vA.2-a-1] — 2026-04-21

### Added
- **[A.2.a.1] Time helpers** : `hr_ny`, `mn_ny`, `dow_ny`, `is_midnight_ny`, `is_sunday_17_ny`, `is_monday_00_ny`
- **[A.2.a.2] Opens** (§ 3.2) :
  - `midnight_open` / `tdo` via `request.security("D")` — Daily Open in ICT parlance
  - `weekly_open` via `request.security("W")` — broker-default weekly session
  - Horizontal lines drawn with `extend.right`, repainted only when new period starts
  - Works on ANY timeframe (M1 to W) — broker-independent
- **[A.2.a.3] Killzones backgrounds** (§ 3.7) :
  - `in_asia`, `in_london`, `in_ny_am`, `in_ny_lunch`, `in_ny_pm` booleans
  - `current_kz` text for HUD
  - `bgcolor()` painting for each KZ (user-controllable via `show_kz_bg`)
- **[A.2.a.4] Swing points** :
  - `ta.pivothigh` / `ta.pivotlow` with `swing_lookback = 10` (per spec § 7.3)
  - Accept natural pivot delay (no tricks, no repaint)
  - Labels "H" / "L" drawn at each confirmed swing
  - `last_sh`, `last_sl`, `last_sh_bar`, `last_sl_bar` tracked
- **[A.2.a.5] Power of Three (PO3)** (§ 3.1) :
  - Previous DAILY candle retrospective analysis : `po3_daily_prev_dir` in {bull, bear, neutral}
  - Previous WEEKLY candle retrospective analysis : `po3_weekly_prev_dir`
  - Current phase based on NY hour : `po3_current_phase` in {accum, manip, distrib, close}
  - Classification rule : lower wick 1.5x upper wick + body > 40% range = bullish PO3

### Updated
- **HUD Dashboard** : now shows Midnight Open, Weekly Open, PO3 Prev Day/Week, Current Phase, KZ Active, Last Swing H/L
- **Header comment** : roadmap reflects A.2.a completion

### Decisions
- **Inline implementation** (not in libraries) : rationale = faster iteration. Libraries to be populated in Phase B.1 when we need indicator + strategy parity
- **Open detection via `request.security`** : more robust than hour/minute checks (works on Daily/Weekly charts where hour is always 0)
- **Weekly session** : uses broker default (Sunday 17:00 NY on OANDA). `weekly_open_mode` input is currently documentation-only
- **PO3 classification thresholds** : 1.5x wick ratio + 40% body ratio — standard ICT interpretation, tune-able if backtest shows issue
- **Swing lookback** : 10 bars fixed for now — will become input if needed in A.3 bias engine

### Next (A.2.b)
- FVG detection (bull + bear), with zone rendering + mitigation tracking
- IFVG (Inverted FVG) — FVG closed through by body
- BPR (Balanced Price Range) — overlap of bull + bear FVG
- Order Block (STRICT : sweep + FVG + BOS all required)
- Breaker Block (invalidated OB post-CHoCH)

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
