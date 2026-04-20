# PINE SCRIPT V6 — Known limitations & workarounds

> Transparency document per master prompt rule #6 : "Tu ne mens pas sur les limites de Pine Script."
> Every limitation here affects the ICT system. Workarounds documented where possible.

---

## L1 — `request.security()` hard cap ~40 calls

**Limit** : Pine v6 caps the number of `request.security` calls per script at ~40 (TV server load protection).

**Impact on ICT system** :
- Cannot simultaneously load DXY + SPX + VIX + US10Y + GBPUSD + XAGUSD + ETH for all assets at once.
- SMT divergence defined across 5 pair combos (EUR/DXY, XAU/XAG, NAS/SPX, BTC/ETH) — loading ALL would consume 5-10 calls alone.

**Workaround** :
- Auto-detect the ACTIVE instrument via `syminfo.ticker` and load ONLY the relevant correlated symbol.
- Example : if chart = XAUUSD, load XAGUSD only (not the other 4 pairs).
- Saves ~8 `request.security` calls, leaves budget for multi-TF HTF/LTF data.

**Location in code** : `ict_filters.pine` → `f_auto_smt_symbol()` (Phase A.6).

---

## L2 — `request.security()` cannot be inside conditional blocks

**Limit** : Pine v6 has PARTIAL dynamic request support (v6 improvement over v5), but placing `request.security` inside a conditional `if` block is still unreliable and can cause errors or unexpected behavior.

**Impact** : Cannot conditionally load different symbols based on runtime state.

**Workaround** :
- Load all needed symbols at script top level (unconditionally).
- Use the loaded values conditionally further down.
- Accept the upfront resource cost.

---

## L3 — `ta.pivothigh / ta.pivotlow` have inherent lookback delay

**Limit** : A pivot high/low cannot be known until `lookback_right` bars have passed after the candidate bar. This is mathematically necessary (the future must pass before we know it's a pivot).

**Impact** : Swing detection is ALWAYS `lookback_right` bars delayed (default 3 bars).

**Workaround** :
- ACCEPT this delay. It's not repainting — it's reality.
- Document clearly in code that signals appear `lookback_right` bars after the actual pivot.
- In Phase A backtest, this creates realistic results (no future peek).

---

## L4 — TradingView backtest bar limit

**Limit** :
- Free plan : ~5,000 bars
- Essential plan : ~10,000 bars
- Plus plan : ~20,000 bars
- Premium plan : ~40,000 bars

**Impact** : On M5, 10,000 bars = ~35 days of data. Impossible to backtest 3 years of M5 without Premium ($59.95/mo).

**Workaround** :
- Phase A backtest on H4 / H1 timeframes (more bars = more years covered).
- M15 / M5 testing only on Premium-tier TV, or externally via Python (the `scripts/backtest_apex_v3.py` pattern from V3 era).
- Document this in BACKTEST_REPORT.md so user knows the temporal scope of each backtest.

---

## L5 — Historical alerts require Premium tier

**Limit** : `alertcondition()` and `alert()` generate alerts only on LIVE bars by default. Historical replay of alerts requires Premium subscription.

**Impact** : In Phase B (indicator + alerts), testing alert firing on old setups requires user has Premium TV.

**Workaround** :
- In Phase A, we don't need alerts (we use `strategy.entry/exit`).
- In Phase B, we document that alerts work live only — user accepts this for webhook automation.

---

## L6 — Webhook payload size ≤ 4096 characters

**Limit** : TradingView webhook body is capped at 4096 UTF-8 chars.

**Impact** : Rich JSON payload with setup details, multi-TF bias, cross-asset, etc. could theoretically exceed this.

**Workaround** :
- Keep webhook JSON compact : abbreviated field names if needed.
- Omit optional fields when null.
- Tested payload size in Phase B before publishing.

---

## L7 — `barstate.isconfirmed` introduces 1-bar delay for live signals

**Limit** : Signals gated by `barstate.isconfirmed` fire only after a bar closes. On H1, that means up to 60 min delay between signal formation and trigger.

**Impact** : Live execution lags by 1 bar on the timeframe being traded.

**Workaround** :
- This is the price of not repainting. Cannot be fixed without sacrificing reliability.
- Document in USER_GUIDE : "Alerts fire on bar close. For M5, up to 5 min delay."
- Users wanting faster execution must drop to a lower TF (and accept more noise).

---

## L8 — No native news calendar access

**Limit** : Pine has no API to ForexFactory, Investing.com, or any economic calendar.

**Impact** : Cannot dynamically skip trades during NFP/FOMC/CPI.

**Workaround** :
- **Phase A** (backtest) : static CSV hard-coded in `ict_filters.pine` with known red events for the past N years.
- **Phase B** (live) : accept incoming webhook from a separate Python cron job that pulls FF calendar and posts to TV webhook. This sets a Pine variable that gates entries.

---

## L9 — No native Monte Carlo / walk-forward in Pine

**Limit** : Pine Strategy Tester gives raw trades, but no MC simulation, no walk-forward native tooling.

**Impact** : Cannot run the 1000-iteration MC robustness test (§ 9.2) inside Pine.

**Workaround** :
- Export trade list via Strategy Tester → Copy CSV.
- Python script `scripts/montecarlo_analysis.py` (Phase A.9) runs 1000-shuffle MC + computes 95th percentile drawdown.
- Documented in `BACKTEST_REPORT.md`.

---

## L10 — Pine library size limit (~100kb per library)

**Limit** : TradingView published libraries cannot exceed ~100kb compiled size.

**Impact** : Each of our 5 libs must stay under this.

**Workaround** :
- Pre-budgeted : 5 libs × 80kb max = under limit by design.
- No dead code, no decorative comments bloating size.
- Unit tests kept in strategy file, not in libs (so libs stay lean).

---

## Summary of impact on ICT system

| Limitation | Blocking? | Mitigation |
|-----------|-----------|------------|
| L1 request.security cap | No | Auto-detect correlated symbol |
| L2 conditional security | No | Top-level loading |
| L3 pivot lag | No | Accepted (not repaint) |
| L4 backtest bars | Partial | Use H1/H4, Python for M5 |
| L5 historical alerts | No | Accept live-only for Phase B |
| L6 webhook 4096 chars | No | Compact JSON |
| L7 bar-close delay | No | Documented, accepted |
| L8 no news API | No | Static CSV + external webhook |
| L9 no MC | No | External Python script |
| L10 library size | No | 5-lib budget under limit |

**None of these limitations prevent the ICT system from achieving its performance targets.** They do however mandate the architecture choices above.
