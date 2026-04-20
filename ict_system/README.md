# ICT System v1 — PROMPT_ULTIME Compliant

Built in strict adherence to [`PROMPT_ULTIME_ICT_TRADINGVIEW.md`](../PROMPT_ULTIME_ICT_TRADINGVIEW.md).

> **Status** : Phase A.1 (Skeleton + Inputs) ✅ — See [CHANGELOG.md](docs/CHANGELOG.md)

---

## Quick start

### 1. Install the strategy on TradingView

1. Open TradingView → Pine Editor
2. Paste contents of [`strategy/ict_strategy_v1.pine`](strategy/ict_strategy_v1.pine)
3. **Save** the script → name it "ICT Strategy v1"
4. **Add to chart** — it should compile and display a green "🟢 A.1 SKELETON OK" label on the last bar
5. Open the strategy's **⚙️ Settings** — you'll see 9 input groups with tooltips

### 2. What Phase A.1 does

- Declares all 9 input groups with proper group= / tooltip= per spec
- Uses FTMO-ready strategy() parameters (10k capital, 0.01% commission, 2 ticks slippage, no pyramiding)
- **NO trading logic yet** — this is the skeleton. Entries/exits come in A.4/A.5

### 3. Expected next phase (A.2)

Libraries `ict_core.pine`, `ict_structure.pine`, etc. will receive full implementations of:
- Power of Three (PO3) daily/weekly
- Midnight/Daily/Weekly/True Day Opens
- FVG, IFVG, BPR detection
- Order Block (strict mode per spec § 3.4)
- Breaker Block detection
- BOS, CHoCH, CISD, MSS
- Premium/Discount/Equilibrium zones

Each with visualization at chart level so you can visually validate each concept before moving to A.3.

---

## Architecture overview

```
ict_system/
├── libraries/              # 5 Pine v6 libraries (modular detections)
├── strategy/               # Phase A — backtest strategy
├── indicator/              # Phase B — live alerts (not yet built)
├── docs/                   # Architecture, changelog, limitations
└── backtests/              # Exported trade CSVs per iteration
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full design details.

---

## Philosophy

This system is built on 5 non-negotiable principles:

1. **Pure ICT methodology** — no classical indicators (MA/RSI/etc.)
2. **Modular** — each ICT concept in its own function inside a dedicated library
3. **Non-repainting** — strict `barstate.isconfirmed` + `lookahead_off` discipline
4. **Phase-by-phase** — no Phase B until Phase A meets exit criteria
5. **FTMO-compliant by default** — 0.5% risk, 2% daily cap, 5% total DD cap

---

## Phase roadmap

| Phase | Status |
|-------|--------|
| A.1 — Skeleton + Inputs | ✅ DONE |
| A.2 — Core ICT detections (libraries) | 🔜 NEXT |
| A.3 — Bias engine (Daily + Weekly) | — |
| A.4 — Continuation setup | — |
| A.5 — Reversal setup | — |
| A.6 — Filters (KZ, News, SMT, DXY) | — |
| A.7 — Risk management | — |
| A.8 — Performance report | — |
| A.9 — Walk-forward validation | — |
| **Exit criterion** | WR OOS ≥ 55%, PF ≥ 1.3, Max DD ≤ 10% |
| B.1 — Indicator conversion | Requires A.9 pass |
| B.2 — Webhook JSON alerts | — |
| B.3 — Chart UI polish | — |
| B.4 — USER_GUIDE.md | — |

---

## Known Pine v6 limitations

See [docs/PINE_V6_LIMITATIONS.md](docs/PINE_V6_LIMITATIONS.md) for the full list (10 documented limits + workarounds).

---

## License

Proprietary. Built for David Ghali's trading system.
