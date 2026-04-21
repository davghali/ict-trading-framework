"""
PIPELINE BACKTEST v2 — ULTRA-OPTIMIZED
=======================================

OPTIMIZATIONS vs v1 (based on v1 insights) :

ASSETS :
  - WHITELIST : XAUUSD / XAGUSD / BTCUSD H1 + EURUSD / GBPUSD / AUDUSD / USDCAD D1
  - BLACKLIST : NAS100 / SPX500 / DOW30 / USDJPY (PF ≤ 1.02 in v1)

QUALITY FILTERS (reduce 64% SL hit rate from v1) :
  - Min FVG size_atr      = 0.5  (v1 = 0.2) — only solid gaps
  - Min FVG impulsion     = 1.5  (v1 = 1.1) — impulsive move required
  - Min FVG age at entry  = 2    bars (avoid entering too early)
  - Max FVG age at entry  = 15   bars (avoid entering too late)

KILLZONE FILTER :
  - ALLOWED : london_kz / london_open / asia_kz (WR 38-39%, Exp +0.17-0.19R in v1)
  - BLOCKED : ny_am_kz / ny_pm_kz / ny_lunch / none (WR 33-36%, Exp +0.03-0.11)

HTF BIAS FILTER :
  - LONG : only if HTF (D1) close > D1 open of previous day (bullish prev daily)
  - SHORT : only if HTF (D1) close < D1 open of previous day (bearish prev daily)

RISK MANAGEMENT :
  - Max 3 consecutive losses → cooldown 5 bars
  - Max 4 trades per day per asset (daily cap)

DYNAMIC R TARGETS :
  - In trending regime (price > D sma20) : TP1 2.5R / TP2 4R
  - In ranging : TP1 1.5R / TP2 2.5R
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from collections import defaultdict

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_engine import DataLoader
from src.feature_engine import FeatureEngine
from src.ict_engine import FVGDetector, OrderBlockDetector
from src.utils.types import Side, Timeframe
from src.utils.sessions import which_killzone

DATA_DIR    = ROOT / "data" / "raw"
REPORTS_DIR = ROOT / "reports"

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════
RISK_PCT          = 0.005
INITIAL_CAP       = 10_000
ENTRY_WINDOW      = 30
MAX_HOLD_BARS     = 100
PARTIAL_TP1       = 0.5

# V2 Quality filters
MIN_FVG_SIZE_ATR  = 0.5
MIN_FVG_IMPULSION = 1.5
MIN_FVG_AGE       = 2
MAX_FVG_AGE       = 15

# V2 Killzone whitelist
KZ_WHITELIST      = {"london_kz", "london_open", "asia_kz"}

# V2 Risk mgmt
MAX_CONSEC_LOSS   = 3
COOLDOWN_BARS     = 5
MAX_TRADES_PER_DAY = 4

# V2 Dynamic R
TP1_R_TRENDING   = 2.5
TP2_R_TRENDING   = 4.0
TP1_R_RANGING    = 1.5
TP2_R_RANGING    = 2.5

# V2 Asset whitelist
ASSETS_H1 = ["XAUUSD", "XAGUSD", "BTCUSD"]
ASSETS_D1 = ["EURUSD", "GBPUSD", "AUDUSD", "USDCAD"]


@dataclass
class BTTradeV2:
    timestamp_entry: str
    timestamp_exit: str
    symbol: str
    ltf: str
    side: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    exit_price: float
    exit_reason: str
    r_realized: float
    bars_held: int
    killzone: str
    fvg_size_atr: float
    fvg_impulsion: float
    htf_bias: str
    regime: str


def backtest_symbol_v2(symbol: str, tf: Timeframe) -> List[BTTradeV2]:
    loader = DataLoader()
    try:
        df = loader.load(symbol, tf)
    except Exception:
        return []
    if len(df) < 100:
        return []

    fe = FeatureEngine()
    df = fe.compute(df)

    # Compute SMA20 for regime detection
    df["sma20"] = df["close"].rolling(20).mean()

    # Compute HTF bias (D1 previous close direction)
    # For H1 data : we need daily bias → resample to D1
    if tf == Timeframe.H1:
        df_d = df["close"].resample("1D").last().to_frame("d_close")
        df_d["d_open"] = df["open"].resample("1D").first()
        df_d["d_bias"] = np.where(df_d["d_close"] > df_d["d_open"], "BULL", "BEAR")
        # Merge bias back to H1 — bias is the PREVIOUS day's bias
        df_d["d_bias_prev"] = df_d["d_bias"].shift(1)
        df = df.join(df_d[["d_bias_prev"]], how="left")
        df["d_bias_prev"] = df["d_bias_prev"].ffill()
    else:
        # For D1 : bias = previous close vs prev open
        df["d_bias_prev"] = np.where(df["close"].shift(1) > df["open"].shift(1), "BULL", "BEAR")

    # Detect FVGs
    try:
        fvgs = FVGDetector(min_size_atr=0.2, displacement_min=1.1,
                            close_in_range_min=0.6).detect(df)
    except Exception:
        return []

    if not fvgs:
        return []

    # Apply V2 quality filters on FVG list
    quality_fvgs = [
        f for f in fvgs
        if float(f.size_in_atr) >= MIN_FVG_SIZE_ATR
        and float(f.impulsion_score) >= MIN_FVG_IMPULSION
    ]

    trades: List[BTTradeV2] = []

    # Risk state
    consec_losses = 0
    cooldown_until_bar = -1
    trades_today: Dict[str, int] = defaultdict(int)
    last_date = None

    for fvg in quality_fvgs:
        fvg_bar = fvg.index
        if fvg_bar >= len(df) - ENTRY_WINDOW - 2:
            continue

        atr = float(df["atr_14"].iloc[fvg_bar]) if not pd.isna(df["atr_14"].iloc[fvg_bar]) else 0
        if atr <= 0:
            continue

        # Regime detection (trending if price >5% away from sma20 on 20 bars)
        sma20 = float(df["sma20"].iloc[fvg_bar]) if not pd.isna(df["sma20"].iloc[fvg_bar]) else float(df["close"].iloc[fvg_bar])
        price = float(df["close"].iloc[fvg_bar])
        trend_dist = abs(price - sma20) / sma20 if sma20 > 0 else 0
        regime = "TRENDING" if trend_dist > 0.01 else "RANGING"

        # Dynamic R targets
        tp1_r = TP1_R_TRENDING if regime == "TRENDING" else TP1_R_RANGING
        tp2_r = TP2_R_TRENDING if regime == "TRENDING" else TP2_R_RANGING

        # Compute entry/SL/TPs
        if fvg.side == Side.LONG:
            entry = fvg.ce
            sl    = fvg.bottom - 0.3 * atr
            risk  = entry - sl
            tp1   = entry + tp1_r * risk
            tp2   = entry + tp2_r * risk
        else:
            entry = fvg.ce
            sl    = fvg.top + 0.3 * atr
            risk  = sl - entry
            tp1   = entry - tp1_r * risk
            tp2   = entry - tp2_r * risk
        if risk <= 0:
            continue

        # HTF bias filter
        htf_bias = df["d_bias_prev"].iloc[fvg_bar] if "d_bias_prev" in df.columns else "NEUT"
        if fvg.side == Side.LONG and htf_bias != "BULL":
            continue
        if fvg.side == Side.SHORT and htf_bias != "BEAR":
            continue

        # Look for entry trigger
        entry_bar = None
        for i in range(fvg_bar + MIN_FVG_AGE, min(fvg_bar + MAX_FVG_AGE, len(df))):
            # Cooldown check
            if i <= cooldown_until_bar:
                continue

            # Killzone filter
            ts = df.index[i].to_pydatetime()
            kz = which_killzone(ts) or "none"
            if kz not in KZ_WHITELIST:
                continue

            # Daily trades cap
            date_key = ts.strftime("%Y-%m-%d")
            if date_key != last_date:
                trades_today = defaultdict(int)
                last_date = date_key
            if trades_today[symbol] >= MAX_TRADES_PER_DAY:
                continue

            bh = float(df["high"].iloc[i])
            bl = float(df["low"].iloc[i])
            if fvg.side == Side.LONG and bl <= entry:
                entry_bar = i
                break
            if fvg.side == Side.SHORT and bh >= entry:
                entry_bar = i
                break

        if entry_bar is None:
            continue

        entry_time = df.index[entry_bar].to_pydatetime()
        kz = which_killzone(entry_time) or "none"
        trades_today[symbol] += 1

        # Simulate trade management
        tp1_hit = False
        exit_reason = ""
        exit_price = None
        r_realized = 0.0
        exit_bar = None

        R_BE    = PARTIAL_TP1 * tp1_r
        R_FULL  = PARTIAL_TP1 * tp1_r + (1 - PARTIAL_TP1) * tp2_r

        for j in range(entry_bar + 1, min(entry_bar + MAX_HOLD_BARS, len(df))):
            nh = float(df["high"].iloc[j])
            nl = float(df["low"].iloc[j])

            if fvg.side == Side.LONG:
                if not tp1_hit and nl <= sl:
                    r_realized = -1.0
                    exit_reason = "sl"
                    exit_price = sl
                    exit_bar = j
                    break
                if tp1_hit and nl <= entry:
                    r_realized = R_BE
                    exit_reason = "be"
                    exit_price = entry
                    exit_bar = j
                    break
                if not tp1_hit and nh >= tp1:
                    tp1_hit = True
                if tp1_hit and nh >= tp2:
                    r_realized = R_FULL
                    exit_reason = "tp2"
                    exit_price = tp2
                    exit_bar = j
                    break
            else:
                if not tp1_hit and nh >= sl:
                    r_realized = -1.0
                    exit_reason = "sl"
                    exit_price = sl
                    exit_bar = j
                    break
                if tp1_hit and nh >= entry:
                    r_realized = R_BE
                    exit_reason = "be"
                    exit_price = entry
                    exit_bar = j
                    break
                if not tp1_hit and nl <= tp1:
                    tp1_hit = True
                if tp1_hit and nl <= tp2:
                    r_realized = R_FULL
                    exit_reason = "tp2"
                    exit_price = tp2
                    exit_bar = j
                    break

        if exit_reason == "":
            exit_bar = min(entry_bar + MAX_HOLD_BARS, len(df) - 1)
            exit_close = float(df["close"].iloc[exit_bar])
            if fvg.side == Side.LONG:
                r_raw = (exit_close - entry) / risk
            else:
                r_raw = (entry - exit_close) / risk
            r_raw = max(-2.0, min(4.0, r_raw))
            if tp1_hit:
                r_realized = R_BE + (1 - PARTIAL_TP1) * r_raw
            else:
                r_realized = r_raw
            exit_reason = "time"
            exit_price = exit_close

        # Update consec loss tracking
        if r_realized < 0:
            consec_losses += 1
            if consec_losses >= MAX_CONSEC_LOSS:
                cooldown_until_bar = exit_bar + COOLDOWN_BARS
                consec_losses = 0
        else:
            consec_losses = 0

        exit_time = df.index[exit_bar].to_pydatetime()
        bars_held = exit_bar - entry_bar

        trades.append(BTTradeV2(
            timestamp_entry = entry_time.isoformat(),
            timestamp_exit  = exit_time.isoformat(),
            symbol          = symbol,
            ltf             = tf.value,
            side            = "long" if fvg.side == Side.LONG else "short",
            entry           = round(entry, 5),
            sl              = round(sl, 5),
            tp1             = round(tp1, 5),
            tp2             = round(tp2, 5),
            exit_price      = round(exit_price, 5),
            exit_reason     = exit_reason,
            r_realized      = round(r_realized, 3),
            bars_held       = bars_held,
            killzone        = kz,
            fvg_size_atr    = round(float(fvg.size_in_atr), 2),
            fvg_impulsion   = round(float(fvg.impulsion_score), 2),
            htf_bias        = str(htf_bias),
            regime          = regime,
        ))

    return trades


def compute_stats_v2(trades: List[BTTradeV2], label: str) -> Dict:
    if not trades:
        return {"label": label, "n": 0}

    n = len(trades)
    rs = [t.r_realized for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    wr = len(wins) / n * 100
    total_r = sum(rs)
    exp = total_r / n
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    pf = sum(wins) / abs(sum(losses)) if losses else float("inf")

    first_t = min(datetime.fromisoformat(t.timestamp_entry) for t in trades)
    last_t  = max(datetime.fromisoformat(t.timestamp_entry) for t in trades)
    days = max((last_t - first_t).days, 1)
    trades_per_week = n / (days / 7)

    equity = [INITIAL_CAP]
    for r in rs:
        eq = max(equity[-1], 1.0)
        equity.append(eq + r * eq * RISK_PCT)
    equity_arr = np.array(equity)
    peak = np.maximum.accumulate(equity_arr)
    dd = (equity_arr - peak) / peak * 100
    max_dd = float(dd.min())
    final_return = (equity_arr[-1] / INITIAL_CAP - 1) * 100

    by_kz = defaultdict(list)
    for t in trades:
        by_kz[t.killzone].append(t.r_realized)
    kz_stats = {
        kz: {
            "n": len(rs_kz),
            "wr": round(sum(1 for r in rs_kz if r > 0) / len(rs_kz) * 100, 2) if rs_kz else 0,
            "avg_r": round(sum(rs_kz) / len(rs_kz), 3) if rs_kz else 0,
        }
        for kz, rs_kz in by_kz.items()
    }

    by_exit = defaultdict(int)
    for t in trades:
        by_exit[t.exit_reason] += 1

    return {
        "label": label,
        "n": n,
        "period_days": days,
        "trades_per_week": round(trades_per_week, 2),
        "win_rate_pct":    round(wr, 2),
        "expectancy_R":    round(exp, 3),
        "avg_win_R":       round(avg_win, 2),
        "avg_loss_R":      round(avg_loss, 2),
        "profit_factor":   round(pf, 2) if pf != float("inf") else None,
        "total_R":         round(total_r, 2),
        "final_return_pct": round(final_return, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "by_exit_reason":  dict(by_exit),
        "by_killzone":     kz_stats,
    }


def run_v2():
    print("=" * 80)
    print("ICT CYBORG PIPELINE BACKTEST v2 — ULTRA-OPTIMIZED")
    print("=" * 80)
    print(f"Config : MIN_FVG_SIZE={MIN_FVG_SIZE_ATR}  MIN_IMPULSION={MIN_FVG_IMPULSION}")
    print(f"KZ whitelist : {KZ_WHITELIST}")
    print(f"Max consec loss : {MAX_CONSEC_LOSS}  Max trades/day : {MAX_TRADES_PER_DAY}")
    print()

    all_trades: List[BTTradeV2] = []
    per_asset = {}

    for sym in ASSETS_H1:
        print(f"▶ {sym} H1 ...")
        ts = backtest_symbol_v2(sym, Timeframe.H1)
        if ts:
            stats = compute_stats_v2(ts, f"{sym} H1")
            per_asset[f"{sym}_1h"] = stats
            all_trades.extend(ts)
            print(f"   n={stats['n']:4d} · WR {stats['win_rate_pct']:5.1f}% · "
                  f"Exp {stats['expectancy_R']:+.3f}R · PF {stats['profit_factor']} · "
                  f"{stats['trades_per_week']:.2f}/wk · DD {stats['max_drawdown_pct']:+.1f}%")

    for sym in ASSETS_D1:
        print(f"▶ {sym} D1 ...")
        ts = backtest_symbol_v2(sym, Timeframe.D1)
        if ts:
            stats = compute_stats_v2(ts, f"{sym} D1")
            per_asset[f"{sym}_1d"] = stats
            all_trades.extend(ts)
            print(f"   n={stats['n']:4d} · WR {stats['win_rate_pct']:5.1f}% · "
                  f"Exp {stats['expectancy_R']:+.3f}R · PF {stats['profit_factor']} · "
                  f"{stats['trades_per_week']:.2f}/wk · DD {stats['max_drawdown_pct']:+.1f}%")

    print("\n" + "=" * 80)
    print("GLOBAL v2")
    print("=" * 80)
    global_stats = compute_stats_v2(all_trades, "GLOBAL v2")
    for k, v in global_stats.items():
        if k in ("by_killzone", "by_exit_reason"):
            print(f"{k:20s} : {v}")
        else:
            print(f"{k:20s} : {v}")

    out = {
        "generated_at": datetime.utcnow().isoformat(),
        "config": {
            "min_fvg_size_atr": MIN_FVG_SIZE_ATR,
            "min_fvg_impulsion": MIN_FVG_IMPULSION,
            "kz_whitelist": list(KZ_WHITELIST),
            "max_consec_loss": MAX_CONSEC_LOSS,
            "cooldown_bars": COOLDOWN_BARS,
            "max_trades_per_day": MAX_TRADES_PER_DAY,
            "tp1_r_trending": TP1_R_TRENDING,
            "tp2_r_trending": TP2_R_TRENDING,
            "tp1_r_ranging": TP1_R_RANGING,
            "tp2_r_ranging": TP2_R_RANGING,
        },
        "global": global_stats,
        "per_asset": per_asset,
        "total_trades": len(all_trades),
    }
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    (REPORTS_DIR / f"pipeline_backtest_v2_{ts}.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"\n📄 Report saved: pipeline_backtest_v2_{ts}.json")

    if all_trades:
        df_t = pd.DataFrame([asdict(t) for t in all_trades])
        df_t.to_csv(REPORTS_DIR / f"pipeline_backtest_v2_trades_{ts}.csv", index=False)

    return out


if __name__ == "__main__":
    run_v2()
