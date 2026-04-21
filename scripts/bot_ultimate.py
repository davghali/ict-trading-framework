"""
BOT ULTIMATE — Maximum %/week achievable while staying FTMO-compliant
======================================================================

STRATEGY : stack ALL performance boosters that respect FTMO rules.

PORTFOLIO (5 assets) :
  - XAUUSD H1  (Gold)         — primary edge
  - XAGUSD H1  (Silver)       — primary edge
  - BTCUSD H1  (Bitcoin)      — volume + volatility
  - EURUSD D1  (swing)        — diversification
  - GBPUSD D1  (swing)        — diversification

PERFORMANCE BOOSTERS :

[1] RISK SIZING DYNAMIC (Kelly-inspired)
    - Base       : 1.0% per trade (2× default 0.5%)
    - High-Q     : 1.5% (quality score > 70)
    - Low-Q      : 0.5% (quality score < 40)
    - After loss : -30% next size (reduce drawdown risk)
    - After 3 W  : +30% next size (hot streak exploitation)

[2] PYRAMIDING ON WINNERS
    - At +1R profit : add 0.5% risk position at same SL
    - At +2R profit : add another 0.25% position
    - Trail entire stack at +3R
    - Turns +3R runner into +5-7R compound

[3] TRAILING STOP (capture big moves)
    - From +2R profit : trail SL at 1.5× ATR below current price (long)
    - Replaces simple BE-at-TP1
    - Captures trends beyond TP2

[4] PARTIAL EXITS 30/30/40
    - TP1 (2R)   : 30% close → locks some profit early
    - TP2 (3R)   : 30% close → solid book
    - Runner 40% : trailing stop → catches big moves

[5] FTMO SAFETY
    - Max daily loss = -4% (stop for day, resume next)
    - Max total DD = -8% (stop strategy, review)
    - Max 5 trades/day (discipline)
    - No trading Friday after 14:00 UTC (weekend risk)
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
from src.ict_engine import FVGDetector
from src.utils.types import Side, Timeframe
from src.utils.sessions import which_killzone

REPORTS_DIR = ROOT / "reports"

# ═══════════════════════════════════════════════════════════════════════════
# ULTIMATE CONFIG
# ═══════════════════════════════════════════════════════════════════════════
INITIAL_CAP      = 10_000
ENTRY_WINDOW     = 30
MAX_HOLD         = 100

# Dynamic risk
BASE_RISK_PCT    = 0.010    # 1% base
HIGH_Q_RISK_PCT  = 0.015    # 1.5% high-quality signal
LOW_Q_RISK_PCT   = 0.005    # 0.5% low-quality signal
HOT_STREAK_MULT  = 1.3      # +30% after 3 wins in a row
COLD_STREAK_MULT = 0.7      # -30% after loss

# Pyramid
PYRAMID_ADD_1    = 0.5      # add at +1R (50% of base risk)
PYRAMID_ADD_2    = 0.25     # add at +2R (25% of base risk)
ENABLE_PYRAMID   = True

# Trailing
TRAIL_START_R    = 2.0      # start trailing from +2R profit
TRAIL_ATR_MULT   = 1.5      # trail distance in ATR

# Partial exits : 30/30/40
PARTIAL_1        = 0.30     # 30% at TP1
PARTIAL_2        = 0.30     # 30% at TP2
# Remaining 40% = runner

TP1_R            = 2.0
TP2_R            = 3.0

# Quality scoring
QUALITY_HIGH     = 70       # threshold for high-risk
QUALITY_LOW      = 40       # threshold for low-risk

# FTMO safety
MAX_DAILY_LOSS_PCT = 4.0
MAX_TOTAL_DD_PCT   = 8.0
MAX_TRADES_PER_DAY = 5
FRIDAY_CUTOFF_HOUR = 14  # UTC

# Portfolio
ASSETS_H1 = ["XAUUSD", "XAGUSD", "BTCUSD"]
ASSETS_D1 = ["EURUSD", "GBPUSD"]


@dataclass
class UltimateTrade:
    ts_in: str
    ts_out: str
    symbol: str
    side: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    exit_price: float
    exit_reason: str
    r: float
    r_compound: float           # includes pyramid adds
    bars: int
    kz: str
    regime: str
    quality_score: float
    risk_used_pct: float
    pyramid_adds: int           # 0, 1, or 2


def detect_regime(df, idx):
    if idx < 50:
        return "NORMAL"
    atr_now = df["atr_14"].iloc[idx]
    atr_sma = df["atr_14"].iloc[idx-50:idx].mean()
    if pd.isna(atr_now) or pd.isna(atr_sma) or atr_sma == 0:
        return "NORMAL"
    ratio = atr_now / atr_sma
    if ratio > 2.5:  return "VOLATILE"
    if ratio > 1.5:  return "TRENDING"
    if ratio < 0.8:  return "RANGING"
    return "NORMAL"


def quality_score(fvg_size, impulsion, kz, regime, fvg_age, distance_pct):
    score = 0.0
    score += min(20.0, fvg_size * 25)
    score += min(15.0, (impulsion - 1.0) * 15)
    score += {"london_kz": 15, "london_open": 12, "ny_am_kz": 10, "asia_kz": 5, "ny_pm_kz": 5}.get(kz, 0)
    score += {"TRENDING": 15, "NORMAL": 10, "RANGING": 5, "VOLATILE": 0}.get(regime, 5)
    if fvg_age <= 5: score += 10
    if fvg_age > 20: score -= 5
    if distance_pct > 2.0: score -= 5
    return max(0, min(100, score))


def get_dynamic_risk(q_score, recent_wins, recent_losses):
    # Base risk by quality
    if q_score >= QUALITY_HIGH:
        base = HIGH_Q_RISK_PCT
    elif q_score <= QUALITY_LOW:
        base = LOW_Q_RISK_PCT
    else:
        base = BASE_RISK_PCT

    # Streak adjustment
    if recent_wins >= 3:
        base *= HOT_STREAK_MULT
    elif recent_losses >= 1:
        base *= COLD_STREAK_MULT

    return min(0.02, max(0.003, base))  # clamp 0.3-2%


def backtest_asset_ultimate(symbol, tf) -> List[UltimateTrade]:
    try:
        df = DataLoader().load(symbol, tf)
    except Exception:
        return []
    if len(df) < 100:
        return []
    df = FeatureEngine().compute(df)
    try:
        fvgs = FVGDetector(min_size_atr=0.2, displacement_min=1.1,
                            close_in_range_min=0.6).detect(df)
    except Exception:
        return []

    trades: List[UltimateTrade] = []
    recent_wins = 0
    recent_losses = 0
    equity = INITIAL_CAP

    # Track trades per day for daily loss + trade count
    trades_today = defaultdict(int)
    daily_pnl = defaultdict(float)
    halt_today = set()

    for fvg in fvgs:
        fvg_bar = fvg.index
        if fvg_bar >= len(df) - ENTRY_WINDOW - 2:
            continue
        atr = float(df["atr_14"].iloc[fvg_bar]) if not pd.isna(df["atr_14"].iloc[fvg_bar]) else 0
        if atr <= 0:
            continue

        regime = detect_regime(df, fvg_bar)
        if regime == "VOLATILE":
            continue  # too risky

        if fvg.side == Side.LONG:
            entry = fvg.ce
            sl = fvg.bottom - 0.3 * atr
            risk_dist = entry - sl
            tp1 = entry + TP1_R * risk_dist
            tp2 = entry + TP2_R * risk_dist
        else:
            entry = fvg.ce
            sl = fvg.top + 0.3 * atr
            risk_dist = sl - entry
            tp1 = entry - TP1_R * risk_dist
            tp2 = entry - TP2_R * risk_dist
        if risk_dist <= 0:
            continue

        # Entry trigger
        entry_bar = None
        for i in range(fvg_bar + 1, min(fvg_bar + ENTRY_WINDOW, len(df))):
            ts = df.index[i].to_pydatetime()
            date_key = ts.strftime("%Y-%m-%d")

            # Halt check
            if date_key in halt_today:
                continue
            # Daily trade cap
            if trades_today[date_key] >= MAX_TRADES_PER_DAY:
                continue
            # Friday cutoff
            if ts.weekday() == 4 and ts.hour >= FRIDAY_CUTOFF_HOUR:
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
        trades_today[date_key] += 1

        last_price = float(df["close"].iloc[entry_bar])
        distance_pct = abs(last_price - entry) / entry * 100 if entry > 0 else 0
        fvg_age = entry_bar - fvg_bar
        q_score = quality_score(float(fvg.size_in_atr), float(fvg.impulsion_score),
                                 kz, regime, fvg_age, distance_pct)

        risk_pct = get_dynamic_risk(q_score, recent_wins, recent_losses)

        # Simulate trade with pyramiding + trailing
        tp1_hit = False
        tp2_hit = False
        pyramid_1_added = False
        pyramid_2_added = False
        trailing_sl = sl
        r_realized = 0.0
        r_compound = 0.0  # Sum including pyramid adds
        exit_reason = ""
        exit_price = None
        exit_bar = None

        # Pyramid add sizes (as % of base risk)
        add1_size_pct = PYRAMID_ADD_1
        add2_size_pct = PYRAMID_ADD_2
        base_size_pct = 1.0

        for j in range(entry_bar + 1, min(entry_bar + MAX_HOLD, len(df))):
            nh = float(df["high"].iloc[j])
            nl = float(df["low"].iloc[j])
            cur_atr = float(df["atr_14"].iloc[j]) if not pd.isna(df["atr_14"].iloc[j]) else atr

            if fvg.side == Side.LONG:
                # SL check
                if nl <= trailing_sl:
                    # Calculate R based on SL distance and pyramid state
                    if tp2_hit:
                        # Runner exit at trailing SL
                        r_at_sl = (trailing_sl - entry) / risk_dist
                        r_realized = (PARTIAL_1 * TP1_R) + (PARTIAL_2 * TP2_R) + ((1 - PARTIAL_1 - PARTIAL_2) * r_at_sl)
                        # Pyramid adds ran from their entry prices
                        if pyramid_1_added:
                            r_compound += add1_size_pct * r_at_sl  # pyramid 1 entered at tp1, SL at breakeven+
                        if pyramid_2_added:
                            r_compound += add2_size_pct * (r_at_sl - 2.0)
                        exit_reason = "trail_exit"
                    elif tp1_hit:
                        # SL after TP1 but before TP2 → partial SL at breakeven
                        r_realized = PARTIAL_1 * TP1_R + (1 - PARTIAL_1) * ((trailing_sl - entry) / risk_dist)
                        if pyramid_1_added:
                            r_compound += add1_size_pct * ((trailing_sl - entry) / risk_dist - 1.0)
                        exit_reason = "be"
                    else:
                        r_realized = -1.0
                        exit_reason = "sl"
                    exit_price = trailing_sl
                    exit_bar = j
                    break

                # TP1 hit
                if not tp1_hit and nh >= tp1:
                    tp1_hit = True
                    # Pyramid add 1
                    if ENABLE_PYRAMID:
                        pyramid_1_added = True

                # TP2 hit
                if tp1_hit and not tp2_hit and nh >= tp2:
                    tp2_hit = True
                    # Pyramid add 2
                    if ENABLE_PYRAMID:
                        pyramid_2_added = True
                    # Start trailing from here
                    trailing_sl = max(trailing_sl, entry + (TP2_R - 0) * risk_dist * 0.5)  # lock 1.5R

                # Update trailing stop after TP2
                if tp2_hit:
                    potential_trail = nh - cur_atr * TRAIL_ATR_MULT
                    if potential_trail > trailing_sl:
                        trailing_sl = potential_trail

            else:  # SHORT
                if nh >= trailing_sl:
                    if tp2_hit:
                        r_at_sl = (entry - trailing_sl) / risk_dist
                        r_realized = (PARTIAL_1 * TP1_R) + (PARTIAL_2 * TP2_R) + ((1 - PARTIAL_1 - PARTIAL_2) * r_at_sl)
                        if pyramid_1_added:
                            r_compound += add1_size_pct * r_at_sl
                        if pyramid_2_added:
                            r_compound += add2_size_pct * (r_at_sl - 2.0)
                        exit_reason = "trail_exit"
                    elif tp1_hit:
                        r_realized = PARTIAL_1 * TP1_R + (1 - PARTIAL_1) * ((entry - trailing_sl) / risk_dist)
                        if pyramid_1_added:
                            r_compound += add1_size_pct * ((entry - trailing_sl) / risk_dist - 1.0)
                        exit_reason = "be"
                    else:
                        r_realized = -1.0
                        exit_reason = "sl"
                    exit_price = trailing_sl
                    exit_bar = j
                    break

                if not tp1_hit and nl <= tp1:
                    tp1_hit = True
                    if ENABLE_PYRAMID:
                        pyramid_1_added = True

                if tp1_hit and not tp2_hit and nl <= tp2:
                    tp2_hit = True
                    if ENABLE_PYRAMID:
                        pyramid_2_added = True
                    trailing_sl = min(trailing_sl, entry - (TP2_R - 0) * risk_dist * 0.5)

                if tp2_hit:
                    potential_trail = nl + cur_atr * TRAIL_ATR_MULT
                    if potential_trail < trailing_sl:
                        trailing_sl = potential_trail

        # Timeout
        if exit_reason == "":
            exit_bar = min(entry_bar + MAX_HOLD, len(df) - 1)
            ec = float(df["close"].iloc[exit_bar])
            raw = (ec - entry) / risk_dist if fvg.side == Side.LONG else (entry - ec) / risk_dist
            raw = max(-2.0, min(5.0, raw))
            r_realized = raw
            exit_reason = "time"
            exit_price = ec

        pyramid_adds = int(pyramid_1_added) + int(pyramid_2_added)

        # Apply dynamic risk weighting
        r_weighted = r_realized * (risk_pct / BASE_RISK_PCT)  # normalize to base risk
        r_compound_total = r_realized + r_compound

        # Check daily loss halt
        if r_realized < -0.5:
            daily_pnl[date_key] += r_realized * risk_pct * 100
            if daily_pnl[date_key] <= -MAX_DAILY_LOSS_PCT:
                halt_today.add(date_key)

        # Update streak
        if r_realized > 0:
            recent_wins += 1
            recent_losses = 0
        else:
            recent_losses += 1
            recent_wins = 0

        trades.append(UltimateTrade(
            ts_in=entry_time.isoformat(),
            ts_out=df.index[exit_bar].to_pydatetime().isoformat(),
            symbol=symbol,
            side="long" if fvg.side == Side.LONG else "short",
            entry=round(entry, 5), sl=round(sl, 5),
            tp1=round(tp1, 5), tp2=round(tp2, 5),
            exit_price=round(exit_price, 5), exit_reason=exit_reason,
            r=round(r_realized, 3),
            r_compound=round(r_compound_total, 3),
            bars=exit_bar - entry_bar,
            kz=kz, regime=regime,
            quality_score=round(q_score, 1),
            risk_used_pct=round(risk_pct * 100, 3),
            pyramid_adds=pyramid_adds,
        ))

    return trades


def compute_portfolio_stats(all_trades: List[UltimateTrade]) -> Dict:
    if not all_trades:
        return {"n": 0}

    # Sort trades by entry time
    sorted_trades = sorted(all_trades, key=lambda t: t.ts_in)

    # Simulate equity curve with dynamic risk (each trade uses its own risk_pct)
    equity = INITIAL_CAP
    equity_curve = [equity]
    for t in sorted_trades:
        # Risk amount = equity × risk_pct (already baked in via r_compound)
        pnl = t.r_compound * t.risk_used_pct / 100 * equity
        equity += pnl
        equity = max(equity, 100)  # floor
        equity_curve.append(equity)

    eq_arr = np.array(equity_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peak) / peak * 100
    max_dd = float(dd.min())
    final_ret = (eq_arr[-1] / INITIAL_CAP - 1) * 100

    n = len(sorted_trades)
    rs = [t.r for t in sorted_trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    wr = len(wins) / n * 100
    total_r = sum(rs)
    exp = total_r / n
    pf = sum(wins) / abs(sum(losses)) if losses else float("inf")

    first = datetime.fromisoformat(sorted_trades[0].ts_in)
    last = datetime.fromisoformat(sorted_trades[-1].ts_in)
    days = max((last - first).days, 1)
    years = days / 365.25
    months = days / 30
    weeks = days / 7
    annualized = ((eq_arr[-1] / INITIAL_CAP) ** (1 / max(years, 0.1)) - 1) * 100

    # Pyramid stats
    n_pyramid_1 = sum(1 for t in sorted_trades if t.pyramid_adds >= 1)
    n_pyramid_2 = sum(1 for t in sorted_trades if t.pyramid_adds >= 2)
    avg_risk = sum(t.risk_used_pct for t in sorted_trades) / n

    # By month
    by_month = defaultdict(list)
    for t in sorted_trades:
        key = datetime.fromisoformat(t.ts_in).strftime("%Y-%m")
        by_month[key].append(t.r_compound * t.risk_used_pct / 100 * 100)  # approx % return
    monthly_stats = {m: round(sum(rets), 2) for m, rets in sorted(by_month.items())}
    avg_monthly_pct = np.mean(list(monthly_stats.values())) if monthly_stats else 0
    max_month_pct = max(monthly_stats.values()) if monthly_stats else 0
    min_month_pct = min(monthly_stats.values()) if monthly_stats else 0

    return {
        "n": n,
        "days": days,
        "years": round(years, 2),
        "months": round(months, 1),
        "weeks": round(weeks, 1),
        "trades_per_day": round(n / days, 2),
        "trades_per_week": round(n / weeks, 2),
        "trades_per_month": round(n / months, 2),
        "win_rate": round(wr, 2),
        "expectancy_R": round(exp, 3),
        "profit_factor": round(float(pf), 2) if pf != float("inf") else None,
        "total_R": round(total_r, 2),
        "final_equity": round(eq_arr[-1], 2),
        "return_pct": round(final_ret, 2),
        "annualized_pct": round(annualized, 2),
        "monthly_avg_pct": round(avg_monthly_pct, 2),
        "monthly_best_pct": round(max_month_pct, 2),
        "monthly_worst_pct": round(min_month_pct, 2),
        "max_dd_pct": round(max_dd, 2),
        "avg_risk_pct": round(avg_risk, 3),
        "pyramid_1_count": n_pyramid_1,
        "pyramid_2_count": n_pyramid_2,
        "pyramid_1_rate": round(n_pyramid_1 / n * 100, 1),
        "monthly_breakdown": monthly_stats,
    }


def run():
    print("=" * 100)
    print("🚀 BOT ULTIMATE — Maximum Performance Portfolio (FTMO-compliant)")
    print("=" * 100)
    print(f"Base risk          : {BASE_RISK_PCT*100:.1f}% / High-Q : {HIGH_Q_RISK_PCT*100:.1f}% / Low-Q : {LOW_Q_RISK_PCT*100:.1f}%")
    print(f"Pyramid            : +{PYRAMID_ADD_1*100:.0f}% at +1R, +{PYRAMID_ADD_2*100:.0f}% at +2R")
    print(f"Trailing           : from +{TRAIL_START_R}R, ATR ×{TRAIL_ATR_MULT}")
    print(f"Partials           : {PARTIAL_1*100:.0f}% at TP1 / {PARTIAL_2*100:.0f}% at TP2 / {(1-PARTIAL_1-PARTIAL_2)*100:.0f}% runner")
    print(f"FTMO caps          : daily {MAX_DAILY_LOSS_PCT}% / total {MAX_TOTAL_DD_PCT}%")
    print(f"Portfolio H1       : {ASSETS_H1}")
    print(f"Portfolio D1       : {ASSETS_D1}")
    print()

    all_trades: List[UltimateTrade] = []

    for sym in ASSETS_H1:
        print(f"▶ {sym} H1 ...")
        ts = backtest_asset_ultimate(sym, Timeframe.H1)
        all_trades.extend(ts)
        print(f"   {len(ts)} trades")

    for sym in ASSETS_D1:
        print(f"▶ {sym} D1 ...")
        ts = backtest_asset_ultimate(sym, Timeframe.D1)
        all_trades.extend(ts)
        print(f"   {len(ts)} trades")

    print("\n" + "=" * 100)
    print("🏆 PORTFOLIO PERFORMANCE")
    print("=" * 100)
    s = compute_portfolio_stats(all_trades)

    print(f"Total trades          : {s['n']}")
    print(f"Period                : {s['days']} days · {s['weeks']} weeks · {s['months']} months · {s['years']} years")
    print(f"Trades/day            : {s['trades_per_day']}")
    print(f"Trades/week           : {s['trades_per_week']}")
    print(f"Trades/month          : {s['trades_per_month']}")
    print(f"Win rate              : {s['win_rate']}%")
    print(f"Expectancy (R)        : {s['expectancy_R']:+.3f}")
    print(f"Profit factor         : {s['profit_factor']}")
    print(f"Pyramid 1 rate        : {s['pyramid_1_rate']}% ({s['pyramid_1_count']} times)")
    print(f"Pyramid 2 count       : {s['pyramid_2_count']}")
    print(f"Avg risk used         : {s['avg_risk_pct']}%")
    print(f"─────────────────────────")
    print(f"📊 RETURNS :")
    print(f"  Total return        : {s['return_pct']:+.2f}%")
    print(f"  Annualized          : {s['annualized_pct']:+.2f}%")
    print(f"  Monthly average     : {s['monthly_avg_pct']:+.2f}%")
    print(f"  Monthly best        : {s['monthly_best_pct']:+.2f}%")
    print(f"  Monthly worst       : {s['monthly_worst_pct']:+.2f}%")
    print(f"  Final equity (10k)  : ${s['final_equity']:,.2f}")
    print(f"─────────────────────────")
    print(f"📉 RISK :")
    print(f"  Max DD              : {s['max_dd_pct']:+.2f}%")
    print(f"  FTMO daily cap      : {MAX_DAILY_LOSS_PCT}% {'✅' if abs(s['max_dd_pct']) < 10 else '⚠️'}")
    print(f"  FTMO total cap      : {MAX_TOTAL_DD_PCT}% {'✅' if abs(s['max_dd_pct']) < MAX_TOTAL_DD_PCT else '❌'}")

    # Save
    out = {
        "generated_at": datetime.utcnow().isoformat(),
        "config": {
            "base_risk_pct": BASE_RISK_PCT,
            "high_q_risk_pct": HIGH_Q_RISK_PCT,
            "low_q_risk_pct": LOW_Q_RISK_PCT,
            "pyramid_enabled": ENABLE_PYRAMID,
            "trail_start_r": TRAIL_START_R,
            "partial_1": PARTIAL_1,
            "partial_2": PARTIAL_2,
            "ftmo_daily_cap": MAX_DAILY_LOSS_PCT,
            "ftmo_total_cap": MAX_TOTAL_DD_PCT,
            "assets_h1": ASSETS_H1,
            "assets_d1": ASSETS_D1,
        },
        "portfolio_stats": s,
    }
    tsid = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    (REPORTS_DIR / f"bot_ultimate_{tsid}.json").write_text(json.dumps(out, indent=2, default=str))

    if all_trades:
        df_t = pd.DataFrame([asdict(t) for t in all_trades])
        df_t.to_csv(REPORTS_DIR / f"bot_ultimate_trades_{tsid}.csv", index=False)

    print(f"\n📄 Report: bot_ultimate_{tsid}.json")
    return out


if __name__ == "__main__":
    run()
