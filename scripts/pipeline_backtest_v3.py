"""
PIPELINE BACKTEST v3 — SMART OPTIMIZATION
==========================================

LESSON from v1 and v2 :
  - v1 WR 35.87% PF 1.16 (baseline — too many bad trades)
  - v2 HTF filter was COUNTER-productive (WR 21%) — too strict
  - The real edge is ASSET + KZ + FVG QUALITY (but not HTF bias)

v3 optimizations (data-driven from v1 analysis) :

ASSET WHITELIST :
  - XAUUSD / XAGUSD / BTCUSD H1 (PF 1.20-1.41 in v1)
  - EURUSD / GBPUSD / AUDUSD / USDCAD D1 (PF 1.10-1.21 in v1)
  - DROPPED : NAS100/SPX500/DOW30/USDJPY (PF < 1.02)

KZ WHITELIST :
  - london_kz + london_open + asia_kz (WR 38-39% in v1)
  - none allowed (WR 36%, large volume) — keep this
  - DROPPED : ny_am_kz / ny_pm_kz / ny_lunch (WR 33-35%)

FVG QUALITY (mild filter — don't over-restrict) :
  - MIN_SIZE_ATR = 0.3 (vs 0.2 default)
  - MIN_IMPULSION = 1.2 (vs 1.1 default)

RISK MANAGEMENT :
  - Max 3 consec losses → cooldown 10 bars
  - Max 4 trades/day per asset

KEEP DEFAULT :
  - TP1 2R / TP2 3R (don't change what works)
  - SL buffer 0.3 ATR
  - No HTF bias filter (v2 showed it HURTS)
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Dict
from collections import defaultdict

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_engine import DataLoader
from src.feature_engine import FeatureEngine
from src.ict_engine import FVGDetector
from src.utils.types import Side, Timeframe
from src.utils.sessions import which_killzone

REPORTS_DIR = ROOT / "reports"

# V3 Config
RISK_PCT = 0.005
INITIAL_CAP = 10_000
ENTRY_WINDOW = 30
MAX_HOLD_BARS = 100
PARTIAL_TP1 = 0.5
TP1_R = 2.0
TP2_R = 3.0

MIN_FVG_SIZE_ATR = 0.3
MIN_FVG_IMPULSION = 1.2

KZ_WHITELIST = {"london_kz", "london_open", "asia_kz", "none"}

MAX_CONSEC_LOSS = 3
COOLDOWN_BARS = 10
MAX_TRADES_PER_DAY = 4

ASSETS_H1 = ["XAUUSD", "XAGUSD", "BTCUSD"]
ASSETS_D1 = ["EURUSD", "GBPUSD", "AUDUSD", "USDCAD"]


@dataclass
class Trade:
    ts_in: str
    ts_out: str
    symbol: str
    ltf: str
    side: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    exit_price: float
    exit_reason: str
    r: float
    bars: int
    kz: str
    fvg_size: float
    fvg_impulsion: float


def backtest(symbol: str, tf: Timeframe) -> List[Trade]:
    try:
        df = DataLoader().load(symbol, tf)
    except Exception:
        return []
    if len(df) < 100:
        return []
    df = FeatureEngine().compute(df)

    try:
        all_fvgs = FVGDetector(min_size_atr=0.2, displacement_min=1.1,
                                close_in_range_min=0.6).detect(df)
    except Exception:
        return []

    # Apply quality filters
    fvgs = [f for f in all_fvgs
            if float(f.size_in_atr) >= MIN_FVG_SIZE_ATR
            and float(f.impulsion_score) >= MIN_FVG_IMPULSION]

    trades: List[Trade] = []
    consec_loss = 0
    cooldown_until = -1
    trades_per_day: Dict[str, int] = defaultdict(int)

    for fvg in fvgs:
        fvg_bar = fvg.index
        if fvg_bar >= len(df) - ENTRY_WINDOW - 2:
            continue
        atr = float(df["atr_14"].iloc[fvg_bar]) if not pd.isna(df["atr_14"].iloc[fvg_bar]) else 0
        if atr <= 0:
            continue

        if fvg.side == Side.LONG:
            entry = fvg.ce
            sl = fvg.bottom - 0.3 * atr
            risk = entry - sl
            tp1 = entry + TP1_R * risk
            tp2 = entry + TP2_R * risk
        else:
            entry = fvg.ce
            sl = fvg.top + 0.3 * atr
            risk = sl - entry
            tp1 = entry - TP1_R * risk
            tp2 = entry - TP2_R * risk
        if risk <= 0:
            continue

        entry_bar = None
        for i in range(fvg_bar + 1, min(fvg_bar + ENTRY_WINDOW, len(df))):
            if i <= cooldown_until:
                continue
            ts = df.index[i].to_pydatetime()
            kz = which_killzone(ts) or "none"
            if kz not in KZ_WHITELIST:
                continue
            date_key = ts.strftime("%Y-%m-%d")
            if trades_per_day[date_key] >= MAX_TRADES_PER_DAY:
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
        date_key = entry_time.strftime("%Y-%m-%d")
        trades_per_day[date_key] += 1

        tp1_hit = False
        exit_reason = ""
        exit_price = None
        r_realized = 0.0
        exit_bar = None

        R_BE = PARTIAL_TP1 * TP1_R
        R_FULL = PARTIAL_TP1 * TP1_R + (1 - PARTIAL_TP1) * TP2_R

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
            ec = float(df["close"].iloc[exit_bar])
            if fvg.side == Side.LONG:
                raw = (ec - entry) / risk
            else:
                raw = (entry - ec) / risk
            raw = max(-2.0, min(3.0, raw))
            r_realized = R_BE + (1 - PARTIAL_TP1) * raw if tp1_hit else raw
            exit_reason = "time"
            exit_price = ec

        if r_realized < 0:
            consec_loss += 1
            if consec_loss >= MAX_CONSEC_LOSS:
                cooldown_until = exit_bar + COOLDOWN_BARS
                consec_loss = 0
        else:
            consec_loss = 0

        trades.append(Trade(
            ts_in=entry_time.isoformat(),
            ts_out=df.index[exit_bar].to_pydatetime().isoformat(),
            symbol=symbol,
            ltf=tf.value,
            side="long" if fvg.side == Side.LONG else "short",
            entry=round(entry, 5),
            sl=round(sl, 5),
            tp1=round(tp1, 5),
            tp2=round(tp2, 5),
            exit_price=round(exit_price, 5),
            exit_reason=exit_reason,
            r=round(r_realized, 3),
            bars=exit_bar - entry_bar,
            kz=kz,
            fvg_size=round(float(fvg.size_in_atr), 2),
            fvg_impulsion=round(float(fvg.impulsion_score), 2),
        ))

    return trades


def stats(trades: List[Trade], label: str) -> Dict:
    if not trades:
        return {"label": label, "n": 0}
    n = len(trades)
    rs = [t.r for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    wr = len(wins) / n * 100
    tr = sum(rs)
    exp = tr / n
    pf = sum(wins) / abs(sum(losses)) if losses else float("inf")

    first_t = min(datetime.fromisoformat(t.ts_in) for t in trades)
    last_t = max(datetime.fromisoformat(t.ts_in) for t in trades)
    days = max((last_t - first_t).days, 1)

    eq = [INITIAL_CAP]
    for r in rs:
        e = max(eq[-1], 1.0)
        eq.append(e + r * e * RISK_PCT)
    eq = np.array(eq)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak * 100
    max_dd = float(dd.min())
    final_ret = (eq[-1] / INITIAL_CAP - 1) * 100

    by_kz = defaultdict(list)
    for t in trades:
        by_kz[t.kz].append(t.r)

    kz_stats = {kz: {
        "n": len(xs),
        "wr": round(sum(1 for x in xs if x > 0) / len(xs) * 100, 2) if xs else 0,
        "avg_r": round(sum(xs) / len(xs), 3) if xs else 0,
    } for kz, xs in by_kz.items()}

    return {
        "label": label,
        "n": n,
        "days": days,
        "trades_per_week": round(n / (days / 7), 2),
        "win_rate_pct": round(wr, 2),
        "expectancy_R": round(exp, 3),
        "profit_factor": round(pf, 2) if pf != float("inf") else None,
        "total_R": round(tr, 2),
        "final_return_pct": round(final_ret, 2),
        "max_dd_pct": round(max_dd, 2),
        "by_kz": kz_stats,
    }


def run():
    print("=" * 80)
    print("ICT CYBORG PIPELINE BACKTEST v3 — SMART OPTIMIZATION")
    print("=" * 80)
    print(f"Min FVG size ATR  : {MIN_FVG_SIZE_ATR}")
    print(f"Min FVG impulsion : {MIN_FVG_IMPULSION}")
    print(f"KZ whitelist      : {KZ_WHITELIST}")
    print(f"TP1/TP2           : {TP1_R}R / {TP2_R}R")
    print(f"Max consec loss   : {MAX_CONSEC_LOSS} → cooldown {COOLDOWN_BARS} bars")
    print(f"Max trades/day    : {MAX_TRADES_PER_DAY}")
    print()

    all_trades: List[Trade] = []
    per_asset: Dict[str, Dict] = {}

    for sym in ASSETS_H1:
        ts = backtest(sym, Timeframe.H1)
        if ts:
            s = stats(ts, f"{sym} H1")
            per_asset[f"{sym}_1h"] = s
            all_trades.extend(ts)
            print(f"▶ {sym:7s} H1 : n={s['n']:4d} WR {s['win_rate_pct']:5.1f}% "
                  f"Exp {s['expectancy_R']:+.3f}R PF {s['profit_factor']} "
                  f"{s['trades_per_week']:.2f}/wk DD {s['max_dd_pct']:+.1f}% "
                  f"Ret {s['final_return_pct']:+.1f}%")

    for sym in ASSETS_D1:
        ts = backtest(sym, Timeframe.D1)
        if ts:
            s = stats(ts, f"{sym} D1")
            per_asset[f"{sym}_1d"] = s
            all_trades.extend(ts)
            print(f"▶ {sym:7s} D1 : n={s['n']:4d} WR {s['win_rate_pct']:5.1f}% "
                  f"Exp {s['expectancy_R']:+.3f}R PF {s['profit_factor']} "
                  f"{s['trades_per_week']:.2f}/wk DD {s['max_dd_pct']:+.1f}% "
                  f"Ret {s['final_return_pct']:+.1f}%")

    print("\n" + "=" * 80)
    print("GLOBAL v3")
    print("=" * 80)
    g = stats(all_trades, "GLOBAL v3")
    for k, v in g.items():
        if k == "by_kz":
            print(f"{k:18s} : {v}")
        else:
            print(f"{k:18s} : {v}")

    out = {
        "generated_at": datetime.utcnow().isoformat(),
        "config": {
            "min_fvg_size": MIN_FVG_SIZE_ATR,
            "min_fvg_impulsion": MIN_FVG_IMPULSION,
            "kz_whitelist": list(KZ_WHITELIST),
            "tp1_r": TP1_R, "tp2_r": TP2_R,
            "max_consec_loss": MAX_CONSEC_LOSS,
            "cooldown_bars": COOLDOWN_BARS,
            "max_trades_per_day": MAX_TRADES_PER_DAY,
        },
        "global": g,
        "per_asset": per_asset,
    }
    tsid = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    (REPORTS_DIR / f"pipeline_backtest_v3_{tsid}.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"\nReport: pipeline_backtest_v3_{tsid}.json")


if __name__ == "__main__":
    run()
