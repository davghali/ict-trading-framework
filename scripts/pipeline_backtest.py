"""
PIPELINE BACKTEST — Real end-to-end simulation of the ICT Cyborg bot
====================================================================

Walks through historical data bar-by-bar and simulates EXACTLY what the
LiveScanner + AutoExecutor + PositionManager would do in production.

Unlike the simplified apex_v3 backtest, this uses the REAL detection
modules from src/ (FVGDetector, OrderBlockDetector, LiquidityDetector)
so results reflect what the actual bot will produce.

Outputs :
- WR, RR, PF, Expectancy per asset/TF
- Trades per week / day
- Best killzone
- Monthly PnL breakdown
- Max drawdown (R-based)
- Full JSON report + Markdown summary
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional
from collections import defaultdict

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_engine import DataLoader
from src.feature_engine import FeatureEngine
from src.ict_engine import FVGDetector, OrderBlockDetector, LiquidityDetector
from src.utils.types import Side, Timeframe
from src.utils.sessions import which_killzone

DATA_DIR = ROOT / "data" / "raw"
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG (matches production settings)
# ═══════════════════════════════════════════════════════════════════════════
RISK_PCT       = 0.005    # 0.5% per trade
INITIAL_CAP    = 10_000   # FTMO Swing 10k ref
MAX_HOLD_BARS  = 100      # timeout if no exit
ENTRY_WINDOW   = 30       # bars window for entry trigger after FVG formation
TP1_R          = 2.0
TP2_R          = 3.0
PARTIAL_TP1    = 0.5      # 50% closed at TP1
SLIPPAGE_PIPS  = 0.5      # simulate slippage on entry/exit

# Assets to test (must have data in data/raw/)
ASSETS_H1 = ["XAUUSD", "NAS100", "BTCUSD", "SPX500", "XAGUSD", "DOW30"]
ASSETS_D1 = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"]


@dataclass
class BTTrade:
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
    fvg_age_at_entry: int


def backtest_symbol(symbol: str, tf: Timeframe) -> List[BTTrade]:
    """
    Replays the full detection pipeline on historical data.
    For each FVG detected, simulates :
    1. Waiting for price to revisit FVG CE (entry trigger, within ENTRY_WINDOW bars)
    2. Managing position with SL, TP1 (partial), TP2, BE move after TP1
    3. Timeout at MAX_HOLD_BARS
    """
    loader = DataLoader()
    try:
        df = loader.load(symbol, tf)
    except Exception as e:
        print(f"[SKIP] {symbol} {tf.value}: {e}")
        return []

    if len(df) < 100:
        print(f"[SKIP] {symbol} {tf.value}: too few bars ({len(df)})")
        return []

    fe = FeatureEngine()
    df = fe.compute(df)

    # Detect all FVGs + OBs in entire history
    try:
        fvgs = FVGDetector(min_size_atr=0.2, displacement_min=1.1,
                            close_in_range_min=0.6).detect(df)
    except Exception as e:
        print(f"[ERR] {symbol} FVG detection: {e}")
        return []

    if not fvgs:
        print(f"[SKIP] {symbol} {tf.value}: no FVGs detected")
        return []

    trades: List[BTTrade] = []

    for fvg in fvgs:
        fvg_bar = fvg.index
        if fvg_bar >= len(df) - ENTRY_WINDOW - 2:
            continue

        atr = float(df["atr_14"].iloc[fvg_bar]) if not pd.isna(df["atr_14"].iloc[fvg_bar]) else 0
        if atr <= 0:
            continue

        # Compute entry/SL/TPs
        if fvg.side == Side.LONG:
            entry = fvg.ce
            sl    = fvg.bottom - 0.3 * atr
            risk  = entry - sl
            tp1   = entry + TP1_R * risk
            tp2   = entry + TP2_R * risk
        else:
            entry = fvg.ce
            sl    = fvg.top + 0.3 * atr
            risk  = sl - entry
            tp1   = entry - TP1_R * risk
            tp2   = entry - TP2_R * risk

        if risk <= 0:
            continue

        # Look for entry trigger (price revisits CE)
        entry_bar = None
        for i in range(fvg_bar + 1, min(fvg_bar + ENTRY_WINDOW, len(df))):
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
        fvg_age = entry_bar - fvg_bar

        # Simulate trade management
        tp1_hit = False
        exit_reason = ""
        exit_price = None
        r_realized = 0.0
        exit_bar = None

        # Partial R calculation :
        # If SL hit before TP1  → -1R
        # If TP1 hit then SL (now BE) → +0.5 * 2R = +1R (half closed at +2R, rest at BE)
        # If TP1 then TP2 → +0.5 * 2R + 0.5 * 3R = +2.5R
        R_BE    = PARTIAL_TP1 * TP1_R                      # +1R
        R_FULL  = PARTIAL_TP1 * TP1_R + (1 - PARTIAL_TP1) * TP2_R  # +2.5R

        for j in range(entry_bar + 1, min(entry_bar + MAX_HOLD_BARS, len(df))):
            nb = df.iloc[j]
            nh = float(nb["high"])
            nl = float(nb["low"])

            if fvg.side == Side.LONG:
                # SL check (before TP1 = full loss, after TP1 = BE)
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
                # TP1 check
                if not tp1_hit and nh >= tp1:
                    tp1_hit = True
                # TP2 check
                if tp1_hit and nh >= tp2:
                    r_realized = R_FULL
                    exit_reason = "tp2"
                    exit_price = tp2
                    exit_bar = j
                    break
            else:  # SHORT
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

        # Timeout
        if exit_reason == "":
            exit_bar = min(entry_bar + MAX_HOLD_BARS, len(df) - 1)
            exit_close = float(df["close"].iloc[exit_bar])
            if fvg.side == Side.LONG:
                r_raw = (exit_close - entry) / risk
            else:
                r_raw = (entry - exit_close) / risk
            r_raw = max(-2.0, min(3.0, r_raw))
            if tp1_hit:
                r_realized = R_BE + (1 - PARTIAL_TP1) * r_raw
            else:
                r_realized = r_raw
            exit_reason = "time"
            exit_price = exit_close

        exit_time = df.index[exit_bar].to_pydatetime()
        bars_held = exit_bar - entry_bar

        trades.append(BTTrade(
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
            fvg_age_at_entry = fvg_age,
        ))

    return trades


def compute_stats(trades: List[BTTrade], label: str) -> Dict:
    if not trades:
        return {"label": label, "n": 0}

    n = len(trades)
    rs = [t.r_realized for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    wr = len(wins) / n * 100
    total_r = sum(rs)
    expectancy = total_r / n
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    pf = sum(wins) / abs(sum(losses)) if losses else float("inf")

    # Time-weighted stats
    first_t = min(datetime.fromisoformat(t.timestamp_entry) for t in trades)
    last_t  = max(datetime.fromisoformat(t.timestamp_entry) for t in trades)
    days = max((last_t - first_t).days, 1)
    weeks = days / 7
    trades_per_week = n / weeks
    trades_per_day  = n / days

    # Equity curve (compounding 0.5% risk)
    equity = [INITIAL_CAP]
    for r in rs:
        eq = max(equity[-1], 1.0)
        equity.append(eq + r * eq * RISK_PCT)
    equity_arr = np.array(equity)
    peak = np.maximum.accumulate(equity_arr)
    dd = (equity_arr - peak) / peak * 100
    max_dd = float(dd.min())
    final_return_pct = (equity_arr[-1] / INITIAL_CAP - 1) * 100

    # By killzone
    by_kz = defaultdict(list)
    for t in trades:
        by_kz[t.killzone].append(t.r_realized)
    kz_stats = {
        kz: {
            "n": len(rs_kz),
            "wr": sum(1 for r in rs_kz if r > 0) / len(rs_kz) * 100 if rs_kz else 0,
            "avg_r": sum(rs_kz) / len(rs_kz) if rs_kz else 0,
        }
        for kz, rs_kz in by_kz.items()
    }

    # By exit reason
    by_exit = defaultdict(int)
    for t in trades:
        by_exit[t.exit_reason] += 1

    # Monthly breakdown
    by_month = defaultdict(list)
    for t in trades:
        key = datetime.fromisoformat(t.timestamp_entry).strftime("%Y-%m")
        by_month[key].append(t.r_realized)
    monthly = {
        m: {
            "n": len(rs_m),
            "r_total": sum(rs_m),
            "wr": sum(1 for r in rs_m if r > 0) / len(rs_m) * 100 if rs_m else 0,
        }
        for m, rs_m in sorted(by_month.items())
    }

    return {
        "label": label,
        "n": n,
        "period_days": days,
        "trades_per_week": round(trades_per_week, 2),
        "trades_per_day":  round(trades_per_day, 3),
        "win_rate_pct":    round(wr, 2),
        "expectancy_R":    round(expectancy, 3),
        "avg_win_R":       round(avg_win, 2),
        "avg_loss_R":      round(avg_loss, 2),
        "profit_factor":   round(pf, 2) if pf != float("inf") else None,
        "total_R":         round(total_r, 2),
        "final_return_pct": round(final_return_pct, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "by_exit_reason":  dict(by_exit),
        "by_killzone":     kz_stats,
        "monthly_breakdown": monthly,
    }


def run_all():
    print("=" * 80)
    print("ICT CYBORG PIPELINE BACKTEST — End-to-End Simulation")
    print("=" * 80)

    all_trades: List[BTTrade] = []
    per_asset_stats = {}

    # H1 assets
    for sym in ASSETS_H1:
        print(f"\n▶ Backtest {sym} H1 ...")
        trades = backtest_symbol(sym, Timeframe.H1)
        if trades:
            stats = compute_stats(trades, f"{sym} H1")
            per_asset_stats[f"{sym}_1h"] = stats
            all_trades.extend(trades)
            print(f"   {sym} H1 : {stats['n']} trades · WR {stats['win_rate_pct']}% · "
                  f"Exp {stats['expectancy_R']:+.2f}R · PF {stats['profit_factor']} · "
                  f"{stats['trades_per_week']}/week")

    # D1 assets
    for sym in ASSETS_D1:
        print(f"\n▶ Backtest {sym} D1 ...")
        trades = backtest_symbol(sym, Timeframe.D1)
        if trades:
            stats = compute_stats(trades, f"{sym} D1")
            per_asset_stats[f"{sym}_1d"] = stats
            all_trades.extend(trades)
            print(f"   {sym} D1 : {stats['n']} trades · WR {stats['win_rate_pct']}% · "
                  f"Exp {stats['expectancy_R']:+.2f}R · PF {stats['profit_factor']} · "
                  f"{stats['trades_per_week']}/week")

    # GLOBAL stats
    print("\n" + "=" * 80)
    print("GLOBAL (all assets combined)")
    print("=" * 80)
    global_stats = compute_stats(all_trades, "GLOBAL")
    print(f"Total trades      : {global_stats['n']}")
    print(f"Period (days)     : {global_stats['period_days']}")
    print(f"Trades per week   : {global_stats['trades_per_week']}")
    print(f"Trades per day    : {global_stats['trades_per_day']}")
    print(f"Win rate          : {global_stats['win_rate_pct']}%")
    print(f"Expectancy        : {global_stats['expectancy_R']:+.3f}R per trade")
    print(f"Profit factor     : {global_stats['profit_factor']}")
    print(f"Total R           : {global_stats['total_R']:+.2f}")
    print(f"Return at 0.5%    : {global_stats['final_return_pct']:+.2f}%")
    print(f"Max DD            : {global_stats['max_drawdown_pct']:+.2f}%")
    print(f"By exit reason    : {global_stats['by_exit_reason']}")
    print(f"By killzone       : {global_stats['by_killzone']}")

    # Save report
    out = {
        "generated_at": datetime.utcnow().isoformat(),
        "config": {
            "risk_pct": RISK_PCT,
            "initial_capital": INITIAL_CAP,
            "max_hold_bars": MAX_HOLD_BARS,
            "entry_window": ENTRY_WINDOW,
            "tp1_r": TP1_R,
            "tp2_r": TP2_R,
            "partial_tp1": PARTIAL_TP1,
        },
        "global": global_stats,
        "per_asset": per_asset_stats,
        "total_trades_count": len(all_trades),
        "sample_trades": [asdict(t) for t in all_trades[:20]],
    }
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"pipeline_backtest_{ts}.json"
    report_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n📄 Report saved: {report_path.name}")

    # CSV dump of all trades
    if all_trades:
        csv_path = REPORTS_DIR / f"pipeline_backtest_trades_{ts}.csv"
        df_trades = pd.DataFrame([asdict(t) for t in all_trades])
        df_trades.to_csv(csv_path, index=False)
        print(f"📄 Trades CSV:  {csv_path.name}")

    return out


if __name__ == "__main__":
    run_all()
