"""
BACKTEST APEX V3 — Python replica of ICT_CYBORG_APEX_V3.pine core logic
=======================================================================

Replique les filtres principaux du Pine Script APEX V3 :
- Bias multi-TF (simplifié : trend 50 EMA + bias de la TF supérieure)
- FVG detection (3-bar imbalance, fresh unmitigated)
- Liquidity sweep (bar qui prend le high/low des 10 dernieres bars puis ferme dedans)
- Order Block (derniere bougie opposée avant mouvement impulsif)
- Premium/Discount (50% range last N bars)
- Killzone filter (intraday UT seulement — pour daily, skip)
- Confluence score 0-15 (comme Pine)
- Grade : S >= 9, A+ >= 7, A >= 5, B >= 3

Entry/SL/TP :
- Entry : open bar suivante
- SL    : 1.5 * ATR
- TP1   : 2.0 * ATR (2R)
- TP2   : 4.0 * ATR (4R)
- 50% sortie TP1, 50% sortie TP2 (ou SL breakeven si TP1 hit)

Risk : 0.5% par trade, compte 10k
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import List, Dict, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "raw"
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# =============================================================================
# CONFIG
# =============================================================================
INITIAL_BALANCE = 10_000.0
RISK_PCT        = 0.005      # 0.5% per trade
ATR_LEN         = 14
SL_MULT         = 1.5
TP1_MULT        = 2.0
TP2_MULT        = 4.0
PARTIAL_PCT     = 0.5        # sort 50% a TP1
TREND_LEN       = 50         # EMA 50 pour bias
SWING_LEN       = 10         # swing pour structure
PD_LOOKBACK     = 30         # range pour premium/discount
FVG_AGE_MAX     = 30         # FVG fresh
SWEEP_LOOKBACK  = 10
SLIPPAGE_PIPS   = 0.5


# =============================================================================
# HELPERS
# =============================================================================
def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def detect_fvg_bull(df: pd.DataFrame) -> pd.Series:
    """FVG bull : low[bar] > high[bar-2]"""
    return df["low"] > df["high"].shift(2)


def detect_fvg_bear(df: pd.DataFrame) -> pd.Series:
    """FVG bear : high[bar] < low[bar-2]"""
    return df["high"] < df["low"].shift(2)


def detect_sweep_bull(df: pd.DataFrame, lookback: int = 10) -> pd.Series:
    """Sweep low = prend le plus bas des N dernieres bars puis referme au-dessus"""
    prior_low = df["low"].shift(1).rolling(lookback).min()
    sweep_low = (df["low"] < prior_low) & (df["close"] > prior_low)
    return sweep_low


def detect_sweep_bear(df: pd.DataFrame, lookback: int = 10) -> pd.Series:
    """Sweep high = prend le plus haut des N dernieres bars puis referme au-dessous"""
    prior_high = df["high"].shift(1).rolling(lookback).max()
    sweep_high = (df["high"] > prior_high) & (df["close"] < prior_high)
    return sweep_high


def pd_zone(df: pd.DataFrame, lookback: int = 30) -> pd.Series:
    """Retourne 1 = discount (bas 50% range), -1 = premium (haut 50%), 0 = equilibrium ±5%"""
    rng_high = df["high"].rolling(lookback).max()
    rng_low  = df["low"].rolling(lookback).min()
    mid = (rng_high + rng_low) / 2
    close = df["close"]
    out = pd.Series(0, index=df.index, dtype=int)
    out[close < rng_low + (rng_high - rng_low) * 0.45] = 1   # discount
    out[close > rng_high - (rng_high - rng_low) * 0.45] = -1  # premium
    return out


def bos_bull(df: pd.DataFrame, swing_len: int = 10) -> pd.Series:
    """BOS bull = close casse le swing high des N dernieres bars"""
    prior_sh = df["high"].shift(1).rolling(swing_len).max()
    return df["close"] > prior_sh


def bos_bear(df: pd.DataFrame, swing_len: int = 10) -> pd.Series:
    prior_sl = df["low"].shift(1).rolling(swing_len).min()
    return df["close"] < prior_sl


def compute_bias_higher_tf(df: pd.DataFrame, factor: int) -> pd.Series:
    """Bias HTF approximation : EMA(close, TREND_LEN * factor) vs close"""
    ema_htf = ema(df["close"], TREND_LEN * factor)
    bias = pd.Series(0, index=df.index, dtype=int)
    bias[df["close"] > ema_htf] = 1
    bias[df["close"] < ema_htf] = -1
    return bias


# =============================================================================
# CONFLUENCE SCORE (replica Pine APEX V3)
# =============================================================================
def compute_signals(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """
    Calcule bar-par-bar :
      - fvg_bull/bear
      - sweep_bull/bear
      - bos_bull/bear
      - pd_zone (1=disc, -1=prem)
      - bias_htf1 (multi-TF 1 cran plus haut)
      - bias_htf2 (2 crans plus haut)
      - atr
      - conf_score (0-15)
      - grade (S/A+/A/B)
      - direction (long/short)
    """
    d = df.copy()
    d["atr"]         = atr(d, ATR_LEN)
    d["ema50"]       = ema(d["close"], TREND_LEN)
    d["bias_ltf"]    = (d["close"] > d["ema50"]).astype(int) - (d["close"] < d["ema50"]).astype(int)
    d["bias_htf1"]   = compute_bias_higher_tf(d, 4)       # ~H4 si on est H1, ~W si D
    d["bias_htf2"]   = compute_bias_higher_tf(d, 12)      # ~D si H1, ~M si D

    d["fvg_bull"]    = detect_fvg_bull(d)
    d["fvg_bear"]    = detect_fvg_bear(d)
    d["sweep_bull"]  = detect_sweep_bull(d, SWEEP_LOOKBACK)
    d["sweep_bear"]  = detect_sweep_bear(d, SWEEP_LOOKBACK)
    d["bos_bull"]    = bos_bull(d, SWING_LEN)
    d["bos_bear"]    = bos_bear(d, SWING_LEN)
    d["pd_zone"]     = pd_zone(d, PD_LOOKBACK)

    # Setup bull = sweep_bull OU fvg_bull recent OU bos_bull
    d["fvg_bull_r"]  = d["fvg_bull"].rolling(FVG_AGE_MAX).sum() > 0
    d["fvg_bear_r"]  = d["fvg_bear"].rolling(FVG_AGE_MAX).sum() > 0

    # SETUP DETECTION
    setup_bull = (
        d["sweep_bull"]
        | (d["fvg_bull"] & d["bias_ltf"].eq(1))
        | (d["bos_bull"] & d["pd_zone"].eq(1))
    )
    setup_bear = (
        d["sweep_bear"]
        | (d["fvg_bear"] & d["bias_ltf"].eq(-1))
        | (d["bos_bear"] & d["pd_zone"].eq(-1))
    )

    # CONFLUENCE SCORE — replica APEX V3 (scale 0-15)
    score = pd.Series(0, index=d.index, dtype=int)

    # Multi-TF alignment (max 4pt)
    triple_align_bull = (d["bias_ltf"] == 1) & (d["bias_htf1"] == 1) & (d["bias_htf2"] == 1)
    triple_align_bear = (d["bias_ltf"] == -1) & (d["bias_htf1"] == -1) & (d["bias_htf2"] == -1)
    score = score + triple_align_bull.astype(int) * 3 + triple_align_bear.astype(int) * 3
    duo_align = ((d["bias_ltf"] == d["bias_htf1"]) & (d["bias_ltf"] != 0)).astype(int)
    score = score + duo_align  # +1 si LTF = HTF1

    # Setup actif (max 2pt)
    score = score + (setup_bull | setup_bear).astype(int) * 2

    # FVG nearby (max 2pt)
    fvg_near = (d["fvg_bull_r"] | d["fvg_bear_r"]).astype(int)
    score = score + fvg_near * 2

    # Sweep + BOS combined (max 2pt = elite confluence)
    elite_combo_bull = (d["sweep_bull"] & d["bos_bull"]).astype(int)
    elite_combo_bear = (d["sweep_bear"] & d["bos_bear"]).astype(int)
    score = score + (elite_combo_bull + elite_combo_bear) * 2

    # Premium/Discount aligned with direction (max 2pt)
    pd_bull = ((d["pd_zone"] == 1) & setup_bull).astype(int) * 2
    pd_bear = ((d["pd_zone"] == -1) & setup_bear).astype(int) * 2
    score = score + pd_bull + pd_bear

    # BOS confirmation alone (max 1pt)
    score = score + ((d["bos_bull"] & ~elite_combo_bull.astype(bool)) | (d["bos_bear"] & ~elite_combo_bear.astype(bool))).astype(int)

    # Sweep alone (max 1pt)
    score = score + ((d["sweep_bull"] & ~d["bos_bull"]) | (d["sweep_bear"] & ~d["bos_bear"])).astype(int)

    # Penalty : sweep dans mauvaise direction vs HTF bias
    score = score - (
        (d["sweep_bull"] & (d["bias_htf1"] == -1))
        | (d["sweep_bear"] & (d["bias_htf1"] == 1))
    ).astype(int) * 2
    score = score.clip(lower=0, upper=15)

    d["conf_score"] = score

    # GRADE : S >= 9, A+ >= 7, A >= 5, B >= 3 (replica Pine)
    def grade_fn(s):
        if s >= 9: return "S"
        if s >= 7: return "A+"
        if s >= 5: return "A"
        if s >= 3: return "B"
        return "-"
    d["grade"] = d["conf_score"].apply(grade_fn)

    # DIRECTION
    d["direction"] = 0
    d.loc[setup_bull & d["bias_htf1"].ge(0), "direction"] = 1
    d.loc[setup_bear & d["bias_htf1"].le(0), "direction"] = -1

    return d


# =============================================================================
# BACKTEST ENGINE
# =============================================================================
@dataclass
class Trade:
    entry_time: datetime
    exit_time: Optional[datetime]
    symbol: str
    tf: str
    grade: str
    direction: int           # 1=long, -1=short
    entry: float
    sl: float
    tp1: float
    tp2: float
    conf_score: int
    exit_reason: str = ""    # tp1, tp2, sl, be, time
    exit_price: Optional[float] = None
    r_realized: float = 0.0  # total R captured (partial TP1 + partial TP2 or SL)
    pnl_usd: float = 0.0
    duration_bars: int = 0


def backtest_df(d: pd.DataFrame, symbol: str, tf: str,
                grades_allowed: Tuple[str, ...] = ("S", "A+"),
                max_hold_bars: int = 50) -> List[Trade]:
    """
    Backtest event-driven.
    Pour chaque bar où grade in grades_allowed et direction != 0 et pas deja en position :
      - Entry = open bar suivante
      - SL/TP basés ATR
      - Manage bar-par-bar : SL hit ? TP1 ? TP2 ? ou max_hold
    """
    trades: List[Trade] = []
    bars = d.reset_index()
    time_col = bars.columns[0]

    i = 1
    while i < len(bars) - 1:
        row = bars.iloc[i]
        if (row["grade"] in grades_allowed and
            row["direction"] != 0 and
            not pd.isna(row["atr"]) and row["atr"] > 0):

            nxt = bars.iloc[i + 1]
            entry = float(nxt["open"])
            direction = int(row["direction"])
            atr_v = float(row["atr"])

            if direction == 1:
                sl  = entry - SL_MULT * atr_v
                tp1 = entry + TP1_MULT * atr_v
                tp2 = entry + TP2_MULT * atr_v
            else:
                sl  = entry + SL_MULT * atr_v
                tp1 = entry - TP1_MULT * atr_v
                tp2 = entry - TP2_MULT * atr_v

            trade = Trade(
                entry_time=row[time_col].to_pydatetime() if hasattr(row[time_col], "to_pydatetime") else row[time_col],
                exit_time=None,
                symbol=symbol,
                tf=tf,
                grade=row["grade"],
                direction=direction,
                entry=entry,
                sl=sl,
                tp1=tp1,
                tp2=tp2,
                conf_score=int(row["conf_score"]),
            )

            # Manage (clean version)
            tp1_hit = False
            R_PARTIAL = PARTIAL_PCT * (TP1_MULT / SL_MULT)  # ex: 0.5 * (2/1.5) = 0.667R
            R_FULL_TP2 = R_PARTIAL + (1 - PARTIAL_PCT) * (TP2_MULT / SL_MULT)  # 0.667 + 0.5*2.67 = 2.0R
            exited = False
            j = i + 1

            while j < min(i + 1 + max_hold_bars, len(bars)):
                b = bars.iloc[j]
                bh, bl = float(b["high"]), float(b["low"])
                trade.duration_bars = j - i

                if direction == 1:  # LONG
                    # 1) SL hit (priorité si pas TP1)
                    if not tp1_hit and bl <= sl:
                        trade.exit_reason = "sl"
                        trade.exit_price = sl
                        trade.r_realized = -1.0
                        exited = True
                        break
                    # 2) TP1 hit
                    if not tp1_hit and bh >= tp1:
                        tp1_hit = True
                    # 3) Après TP1, check TP2 ou BE
                    if tp1_hit:
                        if bh >= tp2:
                            trade.exit_reason = "tp2"
                            trade.exit_price = tp2
                            trade.r_realized = R_FULL_TP2
                            exited = True
                            break
                        if bl <= entry:  # BE hit
                            trade.exit_reason = "be"
                            trade.exit_price = entry
                            trade.r_realized = R_PARTIAL
                            exited = True
                            break
                else:  # SHORT
                    if not tp1_hit and bh >= sl:
                        trade.exit_reason = "sl"
                        trade.exit_price = sl
                        trade.r_realized = -1.0
                        exited = True
                        break
                    if not tp1_hit and bl <= tp1:
                        tp1_hit = True
                    if tp1_hit:
                        if bl <= tp2:
                            trade.exit_reason = "tp2"
                            trade.exit_price = tp2
                            trade.r_realized = R_FULL_TP2
                            exited = True
                            break
                        if bh >= entry:
                            trade.exit_reason = "be"
                            trade.exit_price = entry
                            trade.r_realized = R_PARTIAL
                            exited = True
                            break
                j += 1

            if exited:
                b = bars.iloc[j]
                trade.exit_time = b[time_col].to_pydatetime() if hasattr(b[time_col], "to_pydatetime") else b[time_col]
            else:
                # Time out : close current
                j = min(i + max_hold_bars, len(bars) - 1)
                last = bars.iloc[j]
                close = float(last["close"])
                if direction == 1:
                    r_raw = (close - entry) / (entry - sl)
                else:
                    r_raw = (entry - close) / (sl - entry)
                r_raw = float(np.clip(r_raw, -2.0, TP2_MULT / SL_MULT))
                trade.r_realized = R_PARTIAL + (1 - PARTIAL_PCT) * r_raw if tp1_hit else r_raw
                trade.exit_reason = "time"
                trade.exit_price = close
                trade.exit_time = last[time_col].to_pydatetime() if hasattr(last[time_col], "to_pydatetime") else last[time_col]

            # PnL USD
            trade.pnl_usd = trade.r_realized * INITIAL_BALANCE * RISK_PCT
            trades.append(trade)

            # Skip in-position bars
            i = max(j, i + 1)
        else:
            i += 1

    return trades


# =============================================================================
# STATS
# =============================================================================
def compute_stats(trades: List[Trade], label: str) -> Dict:
    if not trades:
        return {"label": label, "n": 0}
    df_t = pd.DataFrame([asdict(t) for t in trades])
    wins = df_t[df_t["r_realized"] > 0]
    losses = df_t[df_t["r_realized"] <= 0]
    n = len(df_t)
    wr = len(wins) / n if n > 0 else 0
    avg_win_r = wins["r_realized"].mean() if len(wins) > 0 else 0
    avg_loss_r = losses["r_realized"].mean() if len(losses) > 0 else 0
    avg_rr = (avg_win_r / abs(avg_loss_r)) if avg_loss_r < 0 else 0
    total_r = df_t["r_realized"].sum()
    expectancy_r = df_t["r_realized"].mean()
    total_pnl = df_t["pnl_usd"].sum()

    # Equity curve simple — compounding fixed-fractional sur equity courante
    equity = [INITIAL_BALANCE]
    for r in df_t["r_realized"]:
        eq = max(equity[-1], 1.0)  # floor pour eviter negatifs
        equity.append(eq + r * eq * RISK_PCT)
    equity = np.array(equity)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    max_dd = float(dd.min() * 100) if len(dd) > 0 else 0
    total_return_pct = (equity[-1] / INITIAL_BALANCE - 1) * 100

    # Duree
    first_trade = df_t["entry_time"].min()
    last_trade = df_t["entry_time"].max()
    years = max((last_trade - first_trade).days / 365.25, 0.1)
    trades_per_year = n / years
    ratio = max(equity[-1] / INITIAL_BALANCE, 1e-9)
    annualized_return = (ratio ** (1/years) - 1) * 100 if years > 0 else 0

    # Sharpe
    r_returns = df_t["r_realized"].values * RISK_PCT
    sharpe = (np.mean(r_returns) / np.std(r_returns) * np.sqrt(trades_per_year)) if np.std(r_returns) > 0 else 0

    # Profit factor
    gross_win = wins["r_realized"].sum() if len(wins) > 0 else 0
    gross_loss = abs(losses["r_realized"].sum()) if len(losses) > 0 else 1e-9
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    return {
        "label": label,
        "n": int(n),
        "period_years": round(years, 2),
        "trades_per_year": round(trades_per_year, 1),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate_pct": round(wr * 100, 2),
        "avg_win_R": round(float(avg_win_r), 2),
        "avg_loss_R": round(float(avg_loss_r), 2),
        "avg_RR": round(float(avg_rr), 2),
        "expectancy_R": round(float(expectancy_r), 3),
        "profit_factor": round(float(pf), 2),
        "total_R": round(float(total_r), 2),
        "total_return_pct": round(float(total_return_pct), 2),
        "annualized_return_pct": round(float(annualized_return), 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_annualized": round(float(sharpe), 2),
        "final_equity_usd": round(float(equity[-1]), 2),
        "total_pnl_usd": round(float(total_pnl), 2),
    }


# =============================================================================
# MAIN
# =============================================================================
def load_and_prepare(file: str) -> pd.DataFrame:
    df = pd.read_parquet(DATA_DIR / file)
    df.columns = [c.lower() for c in df.columns]
    if "date" in df.columns:
        df = df.set_index("date")
    df = df.sort_index()
    need = ["open", "high", "low", "close"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError(f"{file} missing columns: {missing}")
    df = df.dropna(subset=need)
    return df


def resample_h4(df_h1: pd.DataFrame) -> pd.DataFrame:
    """Resample H1 -> H4"""
    o = df_h1["open"].resample("4h").first()
    h = df_h1["high"].resample("4h").max()
    l = df_h1["low"].resample("4h").min()
    c = df_h1["close"].resample("4h").last()
    v = df_h1.get("volume", pd.Series(0, index=df_h1.index)).resample("4h").sum()
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}).dropna()


def run_all() -> Dict:
    """Run backtests pour les 3 assets sur D + H1 + H4 (si data dispo)."""
    results = {"generated_at": datetime.utcnow().isoformat(), "runs": []}

    matrix = [
        # (symbol, file, tf_label, max_hold_bars)
        ("EURUSD", "EURUSD_1d.parquet", "1D", 30),
        ("NAS100", "NAS100_1d.parquet", "1D", 30),
        ("XAUUSD", "XAUUSD_1d.parquet", "1D", 30),
        ("NAS100", "NAS100_1h.parquet", "1H", 48),
        ("XAUUSD", "XAUUSD_1h.parquet", "1H", 48),
    ]

    for symbol, file, tf, max_hold in matrix:
        try:
            df = load_and_prepare(file)
        except FileNotFoundError:
            print(f"[SKIP] {symbol} {tf}: file not found")
            continue

        print(f"\n{'='*60}")
        print(f"[{symbol} {tf}] {len(df)} bars | {df.index[0]} → {df.index[-1]}")
        print(f"{'='*60}")

        d = compute_signals(df, symbol)

        for grades, label_suffix in [
            (("S",), "S only"),
            (("A+",), "A+ only"),
            (("S", "A+"), "S + A+"),
        ]:
            trades = backtest_df(d, symbol, tf, grades_allowed=grades, max_hold_bars=max_hold)
            stats = compute_stats(trades, f"{symbol} {tf} [{label_suffix}]")
            results["runs"].append(stats)
            print(f"  [{label_suffix:10s}] n={stats.get('n',0):4d}  WR={stats.get('win_rate_pct',0):5.1f}%  "
                  f"avgRR={stats.get('avg_RR',0):.2f}  PF={stats.get('profit_factor',0):.2f}  "
                  f"total_R={stats.get('total_R',0):+.1f}  ret={stats.get('total_return_pct',0):+.1f}%  "
                  f"DD={stats.get('max_drawdown_pct',0):+.1f}%")

        # H4 si H1 dispo
        if tf == "1H":
            df_h4 = resample_h4(df)
            print(f"[{symbol} 4H resampled] {len(df_h4)} bars")
            d4 = compute_signals(df_h4, symbol)
            for grades, label_suffix in [
                (("S",), "S only"),
                (("A+",), "A+ only"),
                (("S", "A+"), "S + A+"),
            ]:
                trades = backtest_df(d4, symbol, "4H", grades_allowed=grades, max_hold_bars=30)
                stats = compute_stats(trades, f"{symbol} 4H [{label_suffix}]")
                results["runs"].append(stats)
                print(f"  [{label_suffix:10s}] n={stats.get('n',0):4d}  WR={stats.get('win_rate_pct',0):5.1f}%  "
                      f"avgRR={stats.get('avg_RR',0):.2f}  PF={stats.get('profit_factor',0):.2f}  "
                      f"total_R={stats.get('total_R',0):+.1f}  ret={stats.get('total_return_pct',0):+.1f}%  "
                      f"DD={stats.get('max_drawdown_pct',0):+.1f}%")

    # Save
    out_file = REPORTS_DIR / f"apex_v3_backtest_{datetime.utcnow():%Y%m%d_%H%M%S}.json"
    out_file.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n\n{'='*60}")
    print(f"Saved: {out_file.name}")
    print(f"{'='*60}")
    return results


if __name__ == "__main__":
    run_all()
