"""
BOT 4-ASSETS OPTIMIZER — XAUUSD, XAGUSD, EURUSD × DXY, NAS100
==============================================================

GOAL : Find the OPTIMAL bot config for user's preferred 4 assets
       Maximize : Win Rate × Trades/Week × Avg RR

STRATEGY PER ASSET :
  XAUUSD : H1 + H4 tested, London/NY KZ filter
  XAGUSD : H1 + H4 tested, London/NY KZ filter
  EURUSD : D1 + H4 tested, + DXY correlation filter (SMT)
  NAS100 : H1 + H4 tested, DXY/SPX correlation

TESTS PER ASSET : 4-6 param combos
OUTPUT : Best config per asset + combined portfolio projection
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple
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

INITIAL_CAP = 10_000
RISK_PCT    = 0.005
ENTRY_WINDOW = 30
MAX_HOLD    = 100
PARTIAL_TP1 = 0.5


@dataclass
class Trade:
    ts_in: str
    ts_out: str
    symbol: str
    tf: str
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


def load_dxy_h1() -> Optional[pd.DataFrame]:
    try:
        df = pd.read_parquet(ROOT / "data/raw/DXY_1h.parquet")
        return df
    except Exception:
        return None


def load_dxy_d1() -> Optional[pd.DataFrame]:
    try:
        df = pd.read_parquet(ROOT / "data/raw/DXY_1d.parquet")
        return df
    except Exception:
        return None


def get_dxy_bias_at(ts: datetime, dxy_df: pd.DataFrame, lookback_bars: int = 10) -> str:
    """
    Determines DXY bias at a specific timestamp.
    BULL = DXY strengthening (close > close N bars ago)
    BEAR = DXY weakening
    """
    if dxy_df is None or dxy_df.empty:
        return "UNKNOWN"
    # Find closest bar
    try:
        # Normalize timezone
        if dxy_df.index.tz is None:
            dxy_df.index = dxy_df.index.tz_localize("UTC")
        ts_utc = pd.Timestamp(ts).tz_localize("UTC") if pd.Timestamp(ts).tz is None else pd.Timestamp(ts).tz_convert("UTC")
        subset = dxy_df[dxy_df.index <= ts_utc]
        if len(subset) < lookback_bars + 1:
            return "UNKNOWN"
        cur = float(subset["close"].iloc[-1])
        ref = float(subset["close"].iloc[-lookback_bars - 1])
        if cur > ref * 1.002:
            return "BULL"
        if cur < ref * 0.998:
            return "BEAR"
        return "NEUTRAL"
    except Exception:
        return "UNKNOWN"


def backtest_asset(
    symbol: str,
    tf: Timeframe,
    *,
    kz_whitelist: Optional[set] = None,
    min_fvg_size: float = 0.2,
    min_impulsion: float = 1.1,
    tp1_r: float = 2.0,
    tp2_r: float = 3.0,
    use_dxy_correlation: bool = False,
    dxy_df: Optional[pd.DataFrame] = None,
) -> List[Trade]:
    """Backtest one asset on one TF with optional filters."""
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
    fvgs = [f for f in all_fvgs
            if float(f.size_in_atr) >= min_fvg_size
            and float(f.impulsion_score) >= min_impulsion]

    trades: List[Trade] = []

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
            tp1 = entry + tp1_r * risk
            tp2 = entry + tp2_r * risk
        else:
            entry = fvg.ce
            sl = fvg.top + 0.3 * atr
            risk = sl - entry
            tp1 = entry - tp1_r * risk
            tp2 = entry - tp2_r * risk
        if risk <= 0:
            continue

        entry_bar = None
        for i in range(fvg_bar + 1, min(fvg_bar + ENTRY_WINDOW, len(df))):
            ts = df.index[i].to_pydatetime()
            kz = which_killzone(ts) or "none"
            if kz_whitelist and kz not in kz_whitelist:
                continue

            # DXY correlation filter (for EURUSD)
            if use_dxy_correlation and dxy_df is not None:
                dxy_bias = get_dxy_bias_at(ts, dxy_df, lookback_bars=10)
                # EURUSD inversely correlated to DXY
                # LONG EURUSD only if DXY BEAR
                # SHORT EURUSD only if DXY BULL
                if fvg.side == Side.LONG and dxy_bias == "BULL":
                    continue
                if fvg.side == Side.SHORT and dxy_bias == "BEAR":
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

        tp1_hit = False
        exit_reason = ""
        exit_price = None
        r_realized = 0.0
        exit_bar = None
        R_BE = PARTIAL_TP1 * tp1_r
        R_FULL = PARTIAL_TP1 * tp1_r + (1 - PARTIAL_TP1) * tp2_r

        for j in range(entry_bar + 1, min(entry_bar + MAX_HOLD, len(df))):
            nh = float(df["high"].iloc[j])
            nl = float(df["low"].iloc[j])
            if fvg.side == Side.LONG:
                if not tp1_hit and nl <= sl:
                    r_realized, exit_reason, exit_price, exit_bar = -1.0, "sl", sl, j
                    break
                if tp1_hit and nl <= entry:
                    r_realized, exit_reason, exit_price, exit_bar = R_BE, "be", entry, j
                    break
                if not tp1_hit and nh >= tp1:
                    tp1_hit = True
                if tp1_hit and nh >= tp2:
                    r_realized, exit_reason, exit_price, exit_bar = R_FULL, "tp2", tp2, j
                    break
            else:
                if not tp1_hit and nh >= sl:
                    r_realized, exit_reason, exit_price, exit_bar = -1.0, "sl", sl, j
                    break
                if tp1_hit and nh >= entry:
                    r_realized, exit_reason, exit_price, exit_bar = R_BE, "be", entry, j
                    break
                if not tp1_hit and nl <= tp1:
                    tp1_hit = True
                if tp1_hit and nl <= tp2:
                    r_realized, exit_reason, exit_price, exit_bar = R_FULL, "tp2", tp2, j
                    break

        if exit_reason == "":
            exit_bar = min(entry_bar + MAX_HOLD, len(df) - 1)
            ec = float(df["close"].iloc[exit_bar])
            raw = (ec - entry) / risk if fvg.side == Side.LONG else (entry - ec) / risk
            raw = max(-2.0, min(3.0, raw))
            r_realized = R_BE + (1 - PARTIAL_TP1) * raw if tp1_hit else raw
            exit_reason = "time"
            exit_price = ec

        trades.append(Trade(
            ts_in=entry_time.isoformat(),
            ts_out=df.index[exit_bar].to_pydatetime().isoformat(),
            symbol=symbol, tf=tf.value,
            side="long" if fvg.side == Side.LONG else "short",
            entry=round(entry, 5), sl=round(sl, 5),
            tp1=round(tp1, 5), tp2=round(tp2, 5),
            exit_price=round(exit_price, 5), exit_reason=exit_reason,
            r=round(r_realized, 3), bars=exit_bar - entry_bar, kz=kz,
        ))
    return trades


def compute_stats(trades: List[Trade], label: str) -> Dict:
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
    first = min(datetime.fromisoformat(t.ts_in) for t in trades)
    last = max(datetime.fromisoformat(t.ts_in) for t in trades)
    days = max((last - first).days, 1)
    eq = [INITIAL_CAP]
    for r in rs:
        e = max(eq[-1], 1.0)
        eq.append(e + r * e * RISK_PCT)
    eq = np.array(eq)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak * 100
    max_dd = float(dd.min())
    final_ret = (eq[-1] / INITIAL_CAP - 1) * 100
    years = days / 365.25
    annualized = ((eq[-1] / INITIAL_CAP) ** (1 / max(years, 0.1)) - 1) * 100 if years > 0 else 0

    avg_win_r = sum(wins) / len(wins) if wins else 0
    avg_loss_r = sum(losses) / len(losses) if losses else 0
    avg_rr = avg_win_r / abs(avg_loss_r) if avg_loss_r != 0 else 0

    return {
        "label": label,
        "n": n,
        "days": days,
        "trades_per_week": round(n / (days / 7), 2),
        "trades_per_month": round(n / (days / 30), 2),
        "win_rate": round(wr, 2),
        "expectancy_R": round(exp, 3),
        "avg_win_R": round(avg_win_r, 2),
        "avg_loss_R": round(avg_loss_r, 2),
        "avg_RR": round(avg_rr, 2),
        "profit_factor": round(pf, 2) if pf != float("inf") else None,
        "total_R": round(tr, 2),
        "return_pct": round(final_ret, 2),
        "annualized_pct": round(annualized, 2),
        "max_dd_pct": round(max_dd, 2),
        # Composite score : WR × trades/week × avg_RR / 100
        "composite_score": round(wr * (n / (days / 7)) * avg_rr / 100, 3),
    }


def run():
    print("=" * 100)
    print("BOT 4-ASSETS OPTIMIZER — XAUUSD · XAGUSD · EURUSD × DXY · NAS100")
    print("=" * 100)

    dxy_h1 = load_dxy_h1()
    dxy_d1 = load_dxy_d1()
    print(f"DXY 1h : {len(dxy_h1) if dxy_h1 is not None else 'N/A'}")
    print(f"DXY 1d : {len(dxy_d1) if dxy_d1 is not None else 'N/A'}\n")

    LONDON_ONLY = {"london_kz", "london_open"}
    LONDON_NY   = {"london_kz", "london_open", "ny_am_kz"}
    ALL_KZ      = None  # no filter

    # Test configs per asset
    configs_to_test = [
        # XAUUSD tests
        ("XAUUSD H1 · all KZ · default", "XAUUSD", Timeframe.H1, {"kz_whitelist": None, "min_fvg_size": 0.2, "min_impulsion": 1.1, "tp1_r": 2, "tp2_r": 3}),
        ("XAUUSD H1 · London + NY", "XAUUSD", Timeframe.H1, {"kz_whitelist": LONDON_NY, "min_fvg_size": 0.2, "min_impulsion": 1.1, "tp1_r": 2, "tp2_r": 3}),
        ("XAUUSD H1 · London only", "XAUUSD", Timeframe.H1, {"kz_whitelist": LONDON_ONLY, "min_fvg_size": 0.2, "min_impulsion": 1.1, "tp1_r": 2, "tp2_r": 3}),
        ("XAUUSD H1 · London + quality", "XAUUSD", Timeframe.H1, {"kz_whitelist": LONDON_ONLY, "min_fvg_size": 0.3, "min_impulsion": 1.3, "tp1_r": 2, "tp2_r": 3}),
        ("XAUUSD H1 · London + high RR (2.5/4)", "XAUUSD", Timeframe.H1, {"kz_whitelist": LONDON_ONLY, "min_fvg_size": 0.2, "min_impulsion": 1.1, "tp1_r": 2.5, "tp2_r": 4}),

        # XAGUSD tests
        ("XAGUSD H1 · all KZ · default", "XAGUSD", Timeframe.H1, {"kz_whitelist": None, "min_fvg_size": 0.2, "min_impulsion": 1.1, "tp1_r": 2, "tp2_r": 3}),
        ("XAGUSD H1 · London + NY", "XAGUSD", Timeframe.H1, {"kz_whitelist": LONDON_NY, "min_fvg_size": 0.2, "min_impulsion": 1.1, "tp1_r": 2, "tp2_r": 3}),
        ("XAGUSD H1 · London only", "XAGUSD", Timeframe.H1, {"kz_whitelist": LONDON_ONLY, "min_fvg_size": 0.2, "min_impulsion": 1.1, "tp1_r": 2, "tp2_r": 3}),
        ("XAGUSD H1 · high RR (2.5/4)", "XAGUSD", Timeframe.H1, {"kz_whitelist": None, "min_fvg_size": 0.2, "min_impulsion": 1.1, "tp1_r": 2.5, "tp2_r": 4}),

        # EURUSD tests (with DXY correlation)
        ("EURUSD D1 · no DXY filter", "EURUSD", Timeframe.D1, {"kz_whitelist": None, "min_fvg_size": 0.2, "min_impulsion": 1.1, "tp1_r": 2, "tp2_r": 3}),
        ("EURUSD D1 · DXY correlation", "EURUSD", Timeframe.D1, {"kz_whitelist": None, "min_fvg_size": 0.2, "min_impulsion": 1.1, "tp1_r": 2, "tp2_r": 3, "use_dxy_correlation": True, "dxy_df": dxy_d1}),
        ("EURUSD D1 · DXY + quality", "EURUSD", Timeframe.D1, {"kz_whitelist": None, "min_fvg_size": 0.3, "min_impulsion": 1.3, "tp1_r": 2, "tp2_r": 3, "use_dxy_correlation": True, "dxy_df": dxy_d1}),
        ("EURUSD D1 · DXY + high RR", "EURUSD", Timeframe.D1, {"kz_whitelist": None, "min_fvg_size": 0.2, "min_impulsion": 1.1, "tp1_r": 2.5, "tp2_r": 4, "use_dxy_correlation": True, "dxy_df": dxy_d1}),

        # NAS100 tests
        ("NAS100 H1 · all KZ · default", "NAS100", Timeframe.H1, {"kz_whitelist": None, "min_fvg_size": 0.2, "min_impulsion": 1.1, "tp1_r": 2, "tp2_r": 3}),
        ("NAS100 H1 · NY AM only", "NAS100", Timeframe.H1, {"kz_whitelist": {"ny_am_kz"}, "min_fvg_size": 0.2, "min_impulsion": 1.1, "tp1_r": 2, "tp2_r": 3}),
        ("NAS100 H1 · London + NY", "NAS100", Timeframe.H1, {"kz_whitelist": LONDON_NY, "min_fvg_size": 0.2, "min_impulsion": 1.1, "tp1_r": 2, "tp2_r": 3}),
        ("NAS100 H1 · Quality filters", "NAS100", Timeframe.H1, {"kz_whitelist": LONDON_NY, "min_fvg_size": 0.3, "min_impulsion": 1.5, "tp1_r": 2, "tp2_r": 3}),
        ("NAS100 H1 · High RR", "NAS100", Timeframe.H1, {"kz_whitelist": None, "min_fvg_size": 0.2, "min_impulsion": 1.1, "tp1_r": 2.5, "tp2_r": 4}),
    ]

    all_results: List[Dict] = []
    print(f"{'CONFIG':<44} {'n':>5} {'WR%':>6} {'Exp':>7} {'PF':>5} {'RR':>5} {'/wk':>6} {'Ret%':>8} {'Ann%':>6} {'DD%':>7} {'Score':>7}")
    print("-" * 130)

    for label, sym, tf, params in configs_to_test:
        trades = backtest_asset(sym, tf, **params)
        s = compute_stats(trades, label)
        all_results.append({**s, "symbol": sym, "tf": tf.value, "params": {k: str(v) for k, v in params.items() if k != "dxy_df"}})
        if s["n"] > 0:
            pf_s = f"{s['profit_factor']:.2f}" if s.get("profit_factor") else "inf"
            print(f"{label:<44} {s['n']:>5} {s['win_rate']:>5.1f}% {s['expectancy_R']:>+6.3f} {pf_s:>5} "
                  f"{s['avg_RR']:>5.2f} {s['trades_per_week']:>5.2f} "
                  f"{s['return_pct']:>+7.1f}% {s['annualized_pct']:>+5.1f}% {s['max_dd_pct']:>+6.1f}% {s.get('composite_score', 0):>6.2f}")

    print("-" * 130)

    # Pick best config per asset (by composite score)
    print("\n" + "=" * 100)
    print("BEST CONFIG PER ASSET (composite score = WR × trades/week × avg_RR / 100)")
    print("=" * 100)

    by_asset = defaultdict(list)
    for r in all_results:
        if r["n"] > 0:
            by_asset[r["symbol"]].append(r)

    best_per_asset = {}
    for sym, configs in by_asset.items():
        # Sort by composite score
        configs.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
        best = configs[0]
        best_per_asset[sym] = best
        print(f"\n{sym}:")
        print(f"  🏆 BEST: {best['label']}")
        print(f"     n={best['n']} · WR {best['win_rate']}% · Exp {best['expectancy_R']:+.3f}R · PF {best['profit_factor']}")
        print(f"     RR {best['avg_RR']}:1 · {best['trades_per_week']}/wk · Ret {best['return_pct']:+.1f}% · Ann {best['annualized_pct']:+.1f}% · DD {best['max_dd_pct']:+.1f}%")
        print(f"     Score: {best.get('composite_score', 0):.2f}")

    # Combined portfolio projection (best config per asset combined)
    print("\n" + "=" * 100)
    print("COMBINED PORTFOLIO (best config per asset combined)")
    print("=" * 100)
    combined_weekly = sum(b["trades_per_week"] for b in best_per_asset.values())
    weighted_wr = sum(b["win_rate"] * b["trades_per_week"] for b in best_per_asset.values()) / combined_weekly if combined_weekly > 0 else 0
    weighted_rr = sum(b["avg_RR"] * b["trades_per_week"] for b in best_per_asset.values()) / combined_weekly if combined_weekly > 0 else 0
    total_ret = sum(b["return_pct"] for b in best_per_asset.values())

    print(f"Total trades/week  : {combined_weekly:.1f}")
    print(f"Weighted WR        : {weighted_wr:.1f}%")
    print(f"Weighted avg RR    : {weighted_rr:.2f}:1")
    print(f"Sum of returns     : {total_ret:+.1f}%")

    # Save full report
    out = {
        "generated_at": datetime.utcnow().isoformat(),
        "all_results": all_results,
        "best_per_asset": best_per_asset,
        "portfolio": {
            "trades_per_week": round(combined_weekly, 2),
            "weighted_wr": round(weighted_wr, 2),
            "weighted_rr": round(weighted_rr, 2),
            "sum_return_pct": round(total_ret, 2),
        }
    }
    tsid = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    (REPORTS_DIR / f"bot_4assets_optimized_{tsid}.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"\n📄 Report: bot_4assets_optimized_{tsid}.json")


if __name__ == "__main__":
    run()
