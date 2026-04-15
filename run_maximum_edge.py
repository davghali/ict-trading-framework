"""
MAXIMUM EDGE RUNNER — ML + Pareto frontier sur 12 assets.

Pour chaque asset :
1. Génère tous les candidats FVG + features
2. Entraîne un Gradient Boosting calibré sur IS
3. Prédit P(win) calibrée sur OOS
4. Calcule la courbe Pareto (threshold → WR, volume)
5. Extrait 3 tiers : ELITE, BALANCED, VOLUME

AGRÉGÉ : plan multi-asset avec max volume à WR visé.
"""
from __future__ import annotations

import sys
import json
import warnings
from pathlib import Path
from datetime import datetime
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
warnings.filterwarnings("ignore")

from src.data_engine import DataLoader
from src.feature_engine import FeatureEngine
from src.utils.types import Timeframe
from src.utils.config import REPORTS_DIR
from src.edge_dominance_engine import (
    EdgeCandidateGenerator, EdgeFeatureBuilder, MaximumEdgeEngine,
)


# 12 assets — tous ceux avec data suffisante
ASSETS_H1 = [
    ("NAS100", Timeframe.H1),
    ("XAUUSD", Timeframe.H1),
    ("BTCUSD", Timeframe.H1),
    ("SPX500", Timeframe.H1),
    ("DOW30",  Timeframe.H1),
    ("XAGUSD", Timeframe.H1),
]
ASSETS_D1 = [
    ("EURUSD", Timeframe.D1),
    ("GBPUSD", Timeframe.D1),
    ("USDJPY", Timeframe.D1),
    ("AUDUSD", Timeframe.D1),
    ("USDCAD", Timeframe.D1),
    ("ETHUSD", Timeframe.D1),
]
ALL_ASSETS = ASSETS_H1 + ASSETS_D1


def banner(t, ch="═"):
    print("\n" + ch * 82)
    print(f"  {t}")
    print(ch * 82)


def _prep(symbol, ltf, rr=2.0):
    loader = DataLoader()
    df_d = loader.load(symbol, Timeframe.D1)
    df_ltf = loader.load(symbol, ltf) if ltf != Timeframe.D1 else df_d
    df_w = df_d.resample("1W").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    df_h4 = (df_ltf.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna() if ltf.minutes < 240 else df_d)

    fe = FeatureEngine()
    df_ltf = fe.compute(df_ltf)

    gen = EdgeCandidateGenerator(rr_target=rr)
    fb = EdgeFeatureBuilder(use_htf_bias=True)

    cands = gen.generate(symbol, df_ltf)
    cands = gen.simulate(cands, df_ltf)
    cands = fb.enrich(cands, df_ltf, df_d, df_w, df_h4)
    return gen.to_dataframe(cands)


def _tier_line(tier_name, point):
    if point is None:
        return f"    {tier_name:10s} : (n/a — pas assez de trades à ce tier)"
    return (f"    {tier_name:10s} : WR {point.winrate_oos:.2%} | "
            f"exp_R {point.expectancy_r_oos:+.3f} | "
            f"{point.n_trades_oos} trades OOS | "
            f"{point.trades_per_month:.1f}/mo | "
            f"threshold {point.threshold:.2f}")


def main(rr: float = 2.0):
    banner("MAXIMUM EDGE ENGINE — ML + PARETO — 12 ASSETS", "═")
    print(f"  Date  : {datetime.utcnow().isoformat()}")
    print(f"  Assets: {[a for a, _ in ALL_ASSETS]}")
    print(f"  RR    : {rr}")
    print(f"  ML    : Gradient Boosting + isotonic calibration")

    engine = MaximumEdgeEngine(rr_target=rr)
    results = {}
    plan = {"timestamp": datetime.utcnow().isoformat(), "assets": {}}

    for asset, ltf in ALL_ASSETS:
        banner(f"{asset} ({ltf.value})")
        try:
            df = _prep(asset, ltf, rr=rr)
            filled = df[df["outcome"].isin([-1, 1])]
            if len(filled) < 100:
                print(f"  SKIP: only {len(filled)} trades simulés (< 100)")
                continue

            res = engine.analyze_asset(asset, ltf.value, df, train_pct=0.70)
            if res is None:
                continue
            results[asset] = res

            print(f"  Train n         : {res.n_train}")
            print(f"  Test  n         : {res.n_test}")
            print(f"  Baseline WR test: {res.baseline_wr_test:.3f}")
            print(f"  AUC OOS         : {res.calibration_test['auc']:.3f}")
            print()
            print("  Courbe Pareto (OOS) :")
            print(f"    {'thresh':>7} {'n':>5} {'WR':>6} {'exp_R':>7} {'/mo':>5} {'ΣR':>6}")
            for p in res.pareto:
                print(f"    {p.threshold:>7.2f} {p.n_trades_oos:>5d} "
                      f"{p.winrate_oos:>6.3f} {p.expectancy_r_oos:>+7.3f} "
                      f"{p.trades_per_month:>5.1f} {p.total_r_oos:>+6.2f}")
            print()
            print("  3 TIERS :")
            print(_tier_line("ELITE",    res.tiers.get("elite")))
            print(_tier_line("BALANCED", res.tiers.get("balanced")))
            print(_tier_line("VOLUME",   res.tiers.get("volume")))
            print()
            print("  Top features (importance) :")
            for f, imp in list(res.feature_importance.items())[:7]:
                print(f"    {f:40s} {imp:.4f}")

            plan["assets"][asset] = {
                "ltf": ltf.value,
                "n_test": res.n_test,
                "baseline_wr_test": res.baseline_wr_test,
                "auc": res.calibration_test["auc"],
                "calibration": res.calibration_test,
                "pareto": [vars(p) for p in res.pareto],
                "tiers": {k: vars(v) for k, v in res.tiers.items()},
                "top_features": dict(list(res.feature_importance.items())[:10]),
            }

        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")

    # ===========================================================
    banner("SYNTHÈSE GLOBALE — TOP ASSETS PAR TIER", "═")

    def agg(tier_name: str):
        elite_by_asset = []
        for asset, res in results.items():
            if tier_name in res.tiers:
                p = res.tiers[tier_name]
                elite_by_asset.append({
                    "asset": asset,
                    "tf": res.ltf,
                    "WR": round(p.winrate_oos, 3),
                    "exp_R": round(p.expectancy_r_oos, 3),
                    "n_test": p.n_trades_oos,
                    "per_mo": round(p.trades_per_month, 2),
                    "total_R": round(p.total_r_oos, 2),
                    "threshold": round(p.threshold, 3),
                })
        return sorted(elite_by_asset, key=lambda x: -x["WR"])

    for tier_name in ["elite", "balanced", "volume"]:
        agg_list = agg(tier_name)
        banner(f"TIER : {tier_name.upper()}")
        if not agg_list:
            print("  (aucun asset ne qualifie à ce tier)")
            continue
        total_mo = sum(a["per_mo"] for a in agg_list)
        weighted_wr = sum(a["WR"] * a["per_mo"] for a in agg_list) / max(total_mo, 1e-9)
        print(f"\n  {'Asset':<10} {'TF':<4} {'WR':>6} {'exp_R':>7} {'n':>5} {'/mo':>6} {'thres':>6}")
        for a in agg_list:
            print(f"  {a['asset']:<10} {a['tf']:<4} {a['WR']:>6.3f} "
                  f"{a['exp_R']:>+7.3f} {a['n_test']:>5d} "
                  f"{a['per_mo']:>6.2f} {a['threshold']:>6.2f}")
        print(f"\n  Σ : {total_mo:.1f} trades/mois | WR pondéré : {weighted_wr:.2%}")

    # ===========================================================
    banner("OPTIMAL PLAN — MAX VOLUME × QUALITY", "═")
    print("""
Le PLAN OPTIMAL pour maximiser trades/mois × WR sur tous assets :

  1. Activer TOUS les assets dans le tier BALANCED ou ELITE
  2. Utiliser le threshold P(win) recommandé par tier
  3. Pour chaque signal généré :
     a) Feature vector calculé
     b) ML model → P(win)
     c) Si P(win) ≥ threshold du tier choisi → trade autorisé
     d) Risk Engine valide ensuite (FTMO/5ers compliance)
     e) Money management actif (partial TP + BE 0.5R)

  Tu peux choisir TON point Pareto :

  🎯 WR MAX   → tier ELITE  : peu de trades, WR le plus haut
  ⚖  BALANCED → tier BALANCED : compromis optimal
  🚀 VOLUME   → tier VOLUME : max trades, WR break-even positif

  NB : les thresholds sont calibrés isotoniquement — un threshold 0.60
  veut DIRE P(win) estimée ≥ 60% avec validation OOS.
""")

    out = REPORTS_DIR / f"max_edge_pareto_{datetime.utcnow():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(plan, indent=2, default=str))
    print(f"  💾 Full report JSON : {out}")
    print("═" * 82)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rr", type=float, default=2.0)
    args = ap.parse_args()
    main(rr=args.rr)
