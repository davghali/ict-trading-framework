"""
EDGE INSIGHTS — analyse approfondie des 'presque-edges'.

Objectif : dépasser le binaire "edge trouvé / non trouvé" et exposer
le PAYSAGE STATISTIQUE réel de chaque asset.

Fournit :
- Baselines par asset
- Les 10 MEILLEURES conditions par asset (même si elles ne passent pas le cross-asset)
- Les conditions SYSTÉMATIQUEMENT PERDANTES (à éviter absolument)
- Heatmap winrate par (killzone × asset × side)
- Recommandations concrètes de trading
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
import json

sys.path.insert(0, str(Path(__file__).parent))
warnings.filterwarnings("ignore")

from src.data_engine import DataLoader
from src.feature_engine import FeatureEngine
from src.utils.types import Timeframe
from src.utils.config import REPORTS_DIR
from src.edge_dominance_engine import (
    EdgeCandidateGenerator, EdgeFeatureBuilder,
)


ASSETS = {
    "EURUSD":  Timeframe.D1,
    "NAS100":  Timeframe.H1,
    "XAUUSD":  Timeframe.H1,
    "BTCUSD":  Timeframe.H1,
}


def banner(t, ch="═"):
    print("\n" + ch * 76)
    print(f"  {t}")
    print(ch * 76)


def _prep(symbol, ltf, rr=2.0):
    loader = DataLoader()
    df_d = loader.load(symbol, Timeframe.D1)
    df_ltf = loader.load(symbol, ltf) if ltf != Timeframe.D1 else df_d
    df_w = df_d.resample("1W").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    df_h4 = (df_ltf.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
             if ltf.minutes < 240 else df_d)
    fe = FeatureEngine()
    df_ltf = fe.compute(df_ltf)

    gen = EdgeCandidateGenerator(rr_target=rr)
    fb = EdgeFeatureBuilder(use_htf_bias=True)
    cands = gen.generate(symbol, df_ltf)
    cands = gen.simulate(cands, df_ltf)
    cands = fb.enrich(cands, df_ltf, df_d, df_w, df_h4)
    return gen.to_dataframe(cands)


def analyze_conditional_performance(df: pd.DataFrame, feature: str, min_n=15):
    """Pour chaque valeur de feature, retourne (n, WR, exp_R)."""
    df = df[df["outcome"].isin([-1, 1])]
    if feature not in df.columns:
        return pd.DataFrame()
    rows = []
    for val in df[feature].dropna().unique():
        sub = df[df[feature] == val]
        if len(sub) < min_n:
            continue
        rows.append({
            "feature": feature,
            "value": val,
            "n": len(sub),
            "winrate": round((sub["pnl_r"] > 0).mean(), 3),
            "expectancy_r": round(sub["pnl_r"].mean(), 3),
        })
    return pd.DataFrame(rows).sort_values("expectancy_r", ascending=False)


def analyze_two_way(df: pd.DataFrame, f1: str, f2: str, min_n=10):
    df = df[df["outcome"].isin([-1, 1])]
    if f1 not in df.columns or f2 not in df.columns:
        return pd.DataFrame()
    rows = []
    for v1 in df[f1].dropna().unique():
        for v2 in df[f2].dropna().unique():
            sub = df[(df[f1] == v1) & (df[f2] == v2)]
            if len(sub) < min_n:
                continue
            rows.append({
                f1: v1,
                f2: v2,
                "n": len(sub),
                "winrate": round((sub["pnl_r"] > 0).mean(), 3),
                "expectancy_r": round(sub["pnl_r"].mean(), 3),
            })
    return pd.DataFrame(rows).sort_values("expectancy_r", ascending=False)


def run():
    banner("EDGE INSIGHTS — ANALYSE MULTI-ASSET APPROFONDIE", "═")
    print(f"  Date : {datetime.utcnow().isoformat()}")
    print(f"  Assets: {list(ASSETS.keys())}")

    # Load all
    dfs = {}
    for a, tf in ASSETS.items():
        try:
            dfs[a] = _prep(a, tf)
            filled = dfs[a][dfs[a]["outcome"].isin([-1, 1])]
            print(f"  {a:8s}: {len(filled)} trades simulés")
        except Exception as e:
            print(f"  {a}: SKIP ({e})")

    # Baselines
    banner("BASELINES (sans filtre)")
    print(f"  {'Asset':<10} {'n':>6} {'WR':>7} {'exp_R':>8}")
    for a, df in dfs.items():
        filled = df[df["outcome"].isin([-1, 1])]
        wr = (filled["pnl_r"] > 0).mean()
        ex = filled["pnl_r"].mean()
        print(f"  {a:<10} {len(filled):>6} {wr:>7.3f} {ex:>+8.3f}")

    # Analyse par feature × asset
    features_of_interest = [
        "killzone", "session", "hour_utc", "day_of_week",
        "volatility_bucket", "htf_align", "htf_bias", "side",
        "trend_state", "fvg_irl_erl", "has_ob",
        "recent_sweep_low", "recent_sweep_high",
    ]

    for feat in ["killzone", "hour_utc", "day_of_week", "volatility_bucket",
                 "htf_align", "side", "trend_state", "fvg_irl_erl"]:
        banner(f"  Performance par {feat}")
        for a, df in dfs.items():
            res = analyze_conditional_performance(df, feat, min_n=15)
            if len(res):
                print(f"\n  [{a}]")
                print(res.head(8).to_string(index=False))

    # Bivariate : killzone × side (par asset)
    banner("KILLZONE × SIDE (conditions directionnelles)")
    for a, df in dfs.items():
        res = analyze_two_way(df, "killzone", "side", min_n=10)
        if len(res):
            print(f"\n  [{a}] top 10 conditions (killzone × side) :")
            print(res.head(10).to_string(index=False))

    # Killzone × htf_align
    banner("KILLZONE × HTF_ALIGN (impact du biais HTF)")
    for a, df in dfs.items():
        res = analyze_two_way(df, "killzone", "htf_align", min_n=10)
        if len(res):
            print(f"\n  [{a}] top 10 (killzone × htf_align) :")
            print(res.head(10).to_string(index=False))

    # Zones À ÉVITER (exp_R franchement négatif)
    banner("⚠ ZONES SYSTÉMATIQUEMENT PERDANTES (à ÉVITER)")
    for a, df in dfs.items():
        filled = df[df["outcome"].isin([-1, 1])]
        rows = []
        for feat in ["killzone", "volatility_bucket", "trend_state", "side"]:
            if feat not in filled.columns:
                continue
            for v in filled[feat].dropna().unique():
                sub = filled[filled[feat] == v]
                if len(sub) < 20:
                    continue
                ex = sub["pnl_r"].mean()
                if ex < -0.20:
                    rows.append({
                        "asset": a, "feature": feat, "value": v,
                        "n": len(sub), "wr": round((sub["pnl_r"] > 0).mean(), 3),
                        "exp_R": round(ex, 3),
                    })
        if rows:
            print(f"\n  [{a}] Zones à éviter :")
            print(pd.DataFrame(rows).to_string(index=False))

    # Export global CSV
    all_rows = []
    for a, df in dfs.items():
        for feat in features_of_interest:
            res = analyze_conditional_performance(df, feat, min_n=10)
            for _, row in res.iterrows():
                all_rows.append({"asset": a, **row.to_dict()})
    export_df = pd.DataFrame(all_rows).sort_values("expectancy_r", ascending=False)
    out_csv = REPORTS_DIR / f"edge_insights_global_{datetime.utcnow():%Y%m%d_%H%M%S}.csv"
    export_df.to_csv(out_csv, index=False)

    banner("CONCLUSIONS ACTIONNABLES", "═")
    print("\n  Top 25 combinaisons (toutes conditions, tous actifs, min n=10) :\n")
    # Top global : filter avec WR > 0.55 et exp_R > 0.15
    top_global = export_df[(export_df["winrate"] >= 0.55) & (export_df["expectancy_r"] >= 0.15) & (export_df["n"] >= 15)]
    if len(top_global):
        print(top_global.head(25).to_string(index=False))
    else:
        print("  Aucune combinaison univariée ne dépasse WR 55% + exp_R 0.15 + n≥15")
        print("  Cela ne veut PAS dire 'pas de trading' : ça veut dire que\n"
              "  l'edge doit venir de la COMBINAISON de ≥3 conditions ET d'un\n"
              "  money management actif (partial TP, trailing).")

    print(f"\n  💾 Export CSV global : {out_csv}")
    print("═" * 76)


if __name__ == "__main__":
    run()
