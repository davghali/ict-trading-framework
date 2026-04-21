"""
BOT MAX VOLUME — Maximize trades/week × % return
=================================================

INSIGHT : ML threshold 0.55 is too strict (only 5% of setups pass)
STRATEGY : Expand universe + test multiple thresholds to find sweet spot

EXPANSIONS :
  - Assets : XAU/XAG/BTC H1 + ETH/NAS100/SPX500/DOW30/XAG D1
  - Thresholds tested : 0.40, 0.45, 0.50, 0.55, 0.60
  - Each threshold = WR/volume trade-off

GOAL : Find the (threshold × volume) that maximizes :
  Total R accumulated × (1 / DD_risk)
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from datetime import datetime
from dataclasses import asdict
from typing import List, Dict, Optional

import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.data_engine import DataLoader
from src.feature_engine import FeatureEngine
from src.ict_engine import FVGDetector
from src.utils.types import Side, Timeframe
from bot_level1_complete import build_ml_features, simulate_trade_outcome, build_dataset, monte_carlo, is_news_blackout

REPORTS_DIR = ROOT / "reports"

INITIAL_CAP = 10_000
RISK_PCT = 0.005

ASSETS_CONFIG = {
    "XAUUSD": Timeframe.H1,
    "XAGUSD": Timeframe.H1,
    "BTCUSD": Timeframe.H1,
    "ETHUSD": Timeframe.D1,
    "NAS100": Timeframe.H1,
    "SPX500": Timeframe.H1,
    "DOW30":  Timeframe.H1,
    "XAGUSD_D": Timeframe.D1,  # duplicate for D1 perspective
}

# ─── MAP dupes ───
ASSET_MAP = {
    "XAUUSD_H1": ("XAUUSD", Timeframe.H1),
    "XAGUSD_H1": ("XAGUSD", Timeframe.H1),
    "BTCUSD_H1": ("BTCUSD", Timeframe.H1),
    "ETHUSD_D1": ("ETHUSD", Timeframe.D1),
    "NAS100_H1": ("NAS100", Timeframe.H1),
    "SPX500_H1": ("SPX500", Timeframe.H1),
    "DOW30_H1":  ("DOW30",  Timeframe.H1),
    "XAGUSD_D1": ("XAGUSD", Timeframe.D1),
    "XAUUSD_D1": ("XAUUSD", Timeframe.D1),
    "AUDUSD_D1": ("AUDUSD", Timeframe.D1),
    "GBPUSD_D1": ("GBPUSD", Timeframe.D1),
    "EURUSD_D1": ("EURUSD", Timeframe.D1),
    "USDCAD_D1": ("USDCAD", Timeframe.D1),
    "USDJPY_D1": ("USDJPY", Timeframe.D1),
}


def build_combined_dataset():
    """Load all assets and build combined ML dataset."""
    all_ds = []
    try:
        dxy_df = pd.read_parquet(ROOT / "data/raw/DXY_1h.parquet")
    except Exception:
        dxy_df = None

    for key, (sym, tf) in ASSET_MAP.items():
        try:
            df = DataLoader().load(sym, tf)
            df = FeatureEngine().compute(df)
            ds = build_dataset(df, dxy_df)
            ds["symbol"] = sym
            ds["tf"] = tf.value
            ds["asset_key"] = key
            all_ds.append(ds)
            print(f"  ✓ {key}: {len(ds)} samples")
        except Exception as e:
            print(f"  ⚠ {key}: {e}")
    return pd.concat(all_ds, ignore_index=True) if all_ds else pd.DataFrame()


def train_and_evaluate(combined: pd.DataFrame, threshold: float) -> Dict:
    """Train ML, apply threshold, compute stats."""
    # Filter news blackouts
    df = combined[combined["news_blackout"] == 0].reset_index(drop=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    feature_cols = [c for c in df.columns
                    if c not in ["r_realized", "exit_reason", "label", "timestamp", "symbol", "tf", "asset_key"]]

    split_idx = int(len(df) * 0.7)
    X_train = df[feature_cols].iloc[:split_idx].values
    y_train = df["label"].iloc[:split_idx].values
    X_test  = df[feature_cols].iloc[split_idx:].values
    y_test  = df["label"].iloc[split_idx:].values
    test_df = df.iloc[split_idx:].reset_index(drop=True)

    # Handle NaN by filling with 0 (safer than drop for ML)
    X_train = np.nan_to_num(X_train, nan=0.0, posinf=0.0, neginf=0.0)
    X_test  = np.nan_to_num(X_test,  nan=0.0, posinf=0.0, neginf=0.0)

    scaler = StandardScaler()
    X_tr = scaler.fit_transform(X_train)
    X_te = scaler.transform(X_test)

    clf = GradientBoostingClassifier(
        n_estimators=100, max_depth=4, learning_rate=0.05,
        min_samples_leaf=10, random_state=42
    )
    clf.fit(X_tr, y_train)

    proba = clf.predict_proba(X_te)[:, 1]
    mask = proba >= threshold

    n_filtered = int(mask.sum())
    if n_filtered == 0:
        return {"threshold": threshold, "n": 0}

    rs = test_df["r_realized"].iloc[np.where(mask)[0]].values
    wins = rs[rs > 0]
    losses = rs[rs <= 0]
    wr = len(wins) / len(rs) * 100
    exp = float(rs.mean())
    pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 else float("inf")

    # Time window of test
    test_filtered = test_df.iloc[np.where(mask)[0]]
    if len(test_filtered) > 1:
        first_ts = pd.to_datetime(test_filtered["timestamp"]).min()
        last_ts  = pd.to_datetime(test_filtered["timestamp"]).max()
        days = max((last_ts - first_ts).days, 1)
    else:
        days = 30

    trades_per_week = n_filtered / (days / 7)
    trades_per_month = n_filtered / (days / 30)

    # Compound return
    eq = INITIAL_CAP
    for r in rs:
        eq = max(eq + r * eq * RISK_PCT, 100)
    final_ret = (eq / INITIAL_CAP - 1) * 100
    annualized = ((eq / INITIAL_CAP) ** (365.25 / days) - 1) * 100 if days > 0 else 0

    # Equity curve for DD
    equity = [INITIAL_CAP]
    for r in rs:
        e = max(equity[-1], 1.0)
        equity.append(e + r * e * RISK_PCT)
    eq_arr = np.array(equity)
    peak = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peak) / peak * 100
    max_dd = float(dd.min())

    # By asset breakdown
    by_asset = test_filtered["asset_key"].value_counts().to_dict() if len(test_filtered) > 0 else {}

    return {
        "threshold": threshold,
        "n": n_filtered,
        "days": days,
        "trades_per_week": round(float(trades_per_week), 2),
        "trades_per_month": round(float(trades_per_month), 2),
        "win_rate": round(wr, 2),
        "expectancy_R": round(exp, 3),
        "profit_factor": round(float(pf), 2) if pf != float("inf") else None,
        "total_R": round(float(rs.sum()), 2),
        "return_pct": round(final_ret, 2),
        "annualized_pct": round(annualized, 2),
        "max_dd_pct": round(max_dd, 2),
        "by_asset": by_asset,
        # Composite : trades/week × WR / |DD|
        "score": round(trades_per_week * wr / max(abs(max_dd), 0.5), 2),
    }


def run():
    print("=" * 100)
    print("🚀 BOT MAX VOLUME — Pareto optimization")
    print("=" * 100)

    print("\n▶ Building dataset from 14 asset/TF combos...")
    combined = build_combined_dataset()
    print(f"\n  Total samples: {len(combined)}")

    # Test multiple thresholds
    thresholds = [0.40, 0.45, 0.48, 0.50, 0.52, 0.55, 0.60]
    print("\n" + "=" * 100)
    print(f"{'Threshold':<11} {'n':>5} {'WR%':>6} {'Exp':>7} {'PF':>5} {'/wk':>7} {'/mo':>7} {'Ret%':>8} {'Ann%':>6} {'DD%':>7} {'Score':>7}")
    print("-" * 110)

    results = []
    for thr in thresholds:
        r = train_and_evaluate(combined, thr)
        results.append(r)
        if r["n"] > 0:
            pf = r.get("profit_factor", 0) or 0
            pf_s = f"{pf:.2f}" if pf else "inf"
            print(f"{thr:<11.2f} {r['n']:>5} {r['win_rate']:>5.1f}% {r['expectancy_R']:>+6.3f} {pf_s:>5} "
                  f"{r['trades_per_week']:>6.2f} {r['trades_per_month']:>6.2f} "
                  f"{r['return_pct']:>+7.1f}% {r['annualized_pct']:>+5.1f}% {r['max_dd_pct']:>+6.1f}% {r['score']:>6.2f}")

    # Find Pareto-optimal
    valid = [r for r in results if r["n"] > 5]
    if valid:
        # Best by composite score
        by_score = sorted(valid, key=lambda x: x.get("score", 0), reverse=True)
        best = by_score[0]
        print("\n" + "=" * 100)
        print(f"🏆 BEST THRESHOLD : {best['threshold']}")
        print("=" * 100)
        print(f"  n trades          : {best['n']}")
        print(f"  Win rate          : {best['win_rate']}%")
        print(f"  Expectancy        : {best['expectancy_R']:+.3f}R")
        print(f"  Profit factor     : {best['profit_factor']}")
        print(f"  Trades/week       : {best['trades_per_week']}")
        print(f"  Trades/month      : {best['trades_per_month']}")
        print(f"  Return (test)     : {best['return_pct']:+.2f}%")
        print(f"  Annualized        : {best['annualized_pct']:+.2f}%")
        print(f"  Max DD            : {best['max_dd_pct']:+.2f}%")
        print(f"  Composite score   : {best['score']}")
        print(f"  By asset          : {best['by_asset']}")

    # Max trades (volume) analysis
    by_volume = sorted(valid, key=lambda x: x["trades_per_week"], reverse=True)
    if by_volume:
        max_vol = by_volume[0]
        print(f"\n🔥 MAX VOLUME : threshold {max_vol['threshold']}")
        print(f"  {max_vol['trades_per_week']} trades/week · {max_vol['trades_per_month']} trades/month")
        print(f"  WR {max_vol['win_rate']}% · Exp {max_vol['expectancy_R']:+.3f}R · Ann {max_vol['annualized_pct']:+.1f}%")

    # Max % (quality)
    by_return = sorted(valid, key=lambda x: x.get("annualized_pct", 0), reverse=True)
    if by_return:
        max_ret = by_return[0]
        print(f"\n💎 MAX RETURN : threshold {max_ret['threshold']}")
        print(f"  {max_ret['trades_per_week']} trades/week · {max_ret['trades_per_month']} trades/month")
        print(f"  WR {max_ret['win_rate']}% · Exp {max_ret['expectancy_R']:+.3f}R · Ann {max_ret['annualized_pct']:+.1f}%")

    # Save
    out = {
        "generated_at": datetime.utcnow().isoformat(),
        "results_per_threshold": results,
        "best_by_score": best if valid else None,
        "best_by_volume": max_vol if valid else None,
        "best_by_return": max_ret if valid else None,
        "dataset_size": len(combined),
    }
    tsid = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    (REPORTS_DIR / f"bot_max_volume_{tsid}.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"\n📄 Report: bot_max_volume_{tsid}.json")


if __name__ == "__main__":
    run()
