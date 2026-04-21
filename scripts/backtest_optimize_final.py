"""
FINAL OPTIMIZATION ANALYSIS
============================

Takes v1 trades CSV (4157 trades) and filters them to find THE OPTIMAL
combination without changing the trade execution logic.

Tests 8 configs to find the Pareto-optimal WR × PF × trades/month.
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import json

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

# Load v1 trades
csv_file = list((ROOT / "reports").glob("pipeline_backtest_trades_*.csv"))[-1]
df = pd.read_csv(csv_file)
print(f"Loaded {len(df)} trades from {csv_file.name}\n")

ELITE_ASSETS = ["XAUUSD", "XAGUSD", "GBPUSD", "AUDUSD", "XAUUSD", "EURUSD", "USDCAD"]
H1_ASSETS = ["XAUUSD", "XAGUSD"]
D1_ASSETS = ["GBPUSD", "AUDUSD", "EURUSD", "USDCAD"]

ELITE_KZ = {"london_kz", "london_open", "asia_kz"}
LONDON_ONLY = {"london_kz", "london_open"}


def compute_stats(trades_df, label):
    if len(trades_df) == 0:
        return {"label": label, "n": 0}
    n = len(trades_df)
    rs = trades_df["r_realized"].values
    wins = rs[rs > 0]
    losses = rs[rs <= 0]
    wr = len(wins) / n * 100
    tr = rs.sum()
    exp = tr / n
    pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else float("inf")

    trades_df["ts"] = pd.to_datetime(trades_df["timestamp_entry"])
    first = trades_df["ts"].min()
    last = trades_df["ts"].max()
    days = max((last - first).days, 1)

    # Compound equity at 0.5% risk
    eq = [10000.0]
    for r in rs:
        e = max(eq[-1], 1.0)
        eq.append(e + r * e * 0.005)
    eq = np.array(eq)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak * 100
    max_dd = float(dd.min())
    final_ret = (eq[-1] / 10000 - 1) * 100

    years = days / 365.25
    annualized = ((eq[-1] / 10000) ** (1 / max(years, 0.1)) - 1) * 100 if years > 0 else 0

    return {
        "label": label,
        "n": n,
        "days": days,
        "years": round(years, 2),
        "trades_per_week": round(n / (days / 7), 2),
        "trades_per_month": round(n / (days / 30), 2),
        "win_rate": round(wr, 2),
        "expectancy_R": round(exp, 3),
        "profit_factor": round(float(pf), 2) if pf != float("inf") else None,
        "total_R": round(float(tr), 2),
        "return_pct": round(float(final_ret), 2),
        "annualized_pct": round(annualized, 2),
        "max_dd_pct": round(max_dd, 2),
    }


configs = [
    # (label, filter_fn)
    ("V1 baseline (all 4157)",
        lambda d: d),
    ("Elite assets only (7)",
        lambda d: d[d["symbol"].isin(ELITE_ASSETS)]),
    ("H1 metals only (XAU+XAG)",
        lambda d: d[(d["symbol"].isin(["XAUUSD", "XAGUSD"])) & (d["ltf"] == "1h")]),
    ("Elite KZ only (Asia + London)",
        lambda d: d[d["killzone"].isin(ELITE_KZ)]),
    ("London KZ only",
        lambda d: d[d["killzone"].isin(LONDON_ONLY)]),
    ("H1 metals + London only",
        lambda d: d[(d["symbol"].isin(["XAUUSD", "XAGUSD"])) & (d["ltf"] == "1h") & (d["killzone"].isin(LONDON_ONLY))]),
    ("D1 forex + metals H1",
        lambda d: d[((d["symbol"].isin(H1_ASSETS)) & (d["ltf"] == "1h")) |
                     ((d["symbol"].isin(D1_ASSETS)) & (d["ltf"] == "1d"))]),
    ("D1 forex + metals H1 + London H1",
        lambda d: d[(((d["symbol"].isin(H1_ASSETS)) & (d["ltf"] == "1h") & (d["killzone"].isin(LONDON_ONLY))) |
                      ((d["symbol"].isin(D1_ASSETS)) & (d["ltf"] == "1d")))]),
    ("XAGUSD H1 only (best edge)",
        lambda d: d[(d["symbol"] == "XAGUSD") & (d["ltf"] == "1h")]),
    ("GBPUSD D1 + AUDUSD D1 only",
        lambda d: d[(d["symbol"].isin(["GBPUSD", "AUDUSD"])) & (d["ltf"] == "1d")]),
    ("XAGUSD H1 + London only",
        lambda d: d[(d["symbol"] == "XAGUSD") & (d["ltf"] == "1h") & (d["killzone"].isin(LONDON_ONLY))]),
]

print("=" * 100)
print(f"{'CONFIG':<45} {'n':>5} {'WR%':>6} {'Exp':>7} {'PF':>5} {'Ret%':>8} {'Ann%':>6} {'DD%':>7} {'/week':>6}")
print("=" * 100)

results = []
for label, filt in configs:
    sub = filt(df.copy())
    s = compute_stats(sub, label)
    results.append(s)
    if s["n"] > 0:
        pf_str = f"{s['profit_factor']:.2f}" if s['profit_factor'] else "inf"
        print(f"{label:<45} {s['n']:>5} {s['win_rate']:>5.1f}% {s['expectancy_R']:>+6.3f} {pf_str:>5} "
              f"{s['return_pct']:>+7.1f}% {s['annualized_pct']:>+5.1f}% {s['max_dd_pct']:>+6.1f}% {s['trades_per_week']:>5.2f}")
    else:
        print(f"{label:<45} {0:>5}")

print("=" * 100)

# Save
out = {
    "source": str(csv_file),
    "configs_tested": [r for r in results],
    "generated_at": datetime.utcnow().isoformat(),
}
(ROOT / "reports" / "backtest_optimization_summary.json").write_text(json.dumps(out, indent=2))
print("\nSaved: reports/backtest_optimization_summary.json")
