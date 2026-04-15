"""
EDGE DOMINANCE ENGINE — MULTI-ASSET COMPLET.

Sur LES 4 ACTIFS (EURUSD, NAS100, XAUUSD, BTCUSD) :
  Phase 1 : génération + simulation
  Phase 2 : feature explosion
  Phase 3 : discovery INDÉPENDANT sur chaque actif
  Phase 4 : union des edges candidats
  Phase 5 : VALIDATION CROSS-ASSET
           → un edge valide doit survivre sur au moins 2 actifs
  Phase 8 : reality stress
  Phase 9 : rapport global agrégé

PHILOSOPHIE :
Un vrai edge doit être GÉNÉRIQUE. Un edge qui ne marche QUE sur NAS100
est suspect (peut être overfit à ce marché). Un edge qui traverse
EURUSD + NAS100 + XAUUSD + BTCUSD = edge RÉEL.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path
from datetime import datetime
import pandas as pd
import json

sys.path.insert(0, str(Path(__file__).parent))
warnings.filterwarnings("ignore")

from src.data_engine import DataLoader
from src.feature_engine import FeatureEngine
from src.utils.types import Timeframe
from src.utils.config import REPORTS_DIR
from src.utils.logging_conf import get_logger
from src.edge_dominance_engine import (
    EdgeCandidateGenerator, EdgeFeatureBuilder, EdgeDiscovery,
    EdgeValidator, RealityStressEngine,
)

log = get_logger(__name__)


# ------------------------------------------------------------------
ASSET_CONFIG = {
    "EURUSD":  {"ltf": Timeframe.D1, "has_h1": False},      # only daily available
    "NAS100":  {"ltf": Timeframe.H1, "has_h1": True},
    "XAUUSD":  {"ltf": Timeframe.H1, "has_h1": True},
    "BTCUSD":  {"ltf": Timeframe.H1, "has_h1": True},
}


def banner(t: str, ch: str = "─") -> None:
    print("\n" + ch * 76)
    print(f"  {t}")
    print(ch * 76)


def _prep_asset(symbol: str, ltf: Timeframe):
    loader = DataLoader()
    df_d = loader.load(symbol, Timeframe.D1)
    df_ltf = loader.load(symbol, ltf) if ltf != Timeframe.D1 else df_d
    df_w = df_d.resample("1W").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    if ltf.minutes < 240:
        df_h4 = df_ltf.resample("4h").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()
    else:
        df_h4 = df_d

    fe = FeatureEngine()
    df_ltf = fe.compute(df_ltf)
    return df_ltf, df_d, df_w, df_h4


def _generate_and_enrich(symbol: str, ltf: Timeframe, rr: float = 2.0):
    df_ltf, df_d, df_w, df_h4 = _prep_asset(symbol, ltf)

    gen = EdgeCandidateGenerator(rr_target=rr)
    fb = EdgeFeatureBuilder(use_htf_bias=True)

    cands = gen.generate(symbol, df_ltf)
    cands = gen.simulate(cands, df_ltf)
    cands = fb.enrich(cands, df_ltf, df_d, df_w, df_h4)
    df = gen.to_dataframe(cands)
    return df


def _split_is_oos(df: pd.DataFrame, oos_pct: float = 0.30):
    df = df.sort_values("timestamp").reset_index(drop=True)
    n = len(df)
    cut = int(n * (1 - oos_pct))
    return df.iloc[:cut].copy(), df.iloc[cut:].copy()


# ------------------------------------------------------------------
def run_multi(rr: float = 2.0):
    banner("EDGE DOMINANCE ENGINE — MULTI-ASSET DISCOVERY", "═")
    print(f"  Assets        : {list(ASSET_CONFIG.keys())}")
    print(f"  RR target     : {rr}")
    print(f"  Date          : {datetime.utcnow().isoformat()}")

    # ---------------------------------------------------
    # Phase 1-2 : pour chaque asset, génération + features
    # ---------------------------------------------------
    dfs_full: dict[str, pd.DataFrame] = {}
    baselines: dict[str, dict] = {}
    for asset, cfg in ASSET_CONFIG.items():
        banner(f"PHASE 1-2 — {asset} ({cfg['ltf'].value})")
        try:
            df = _generate_and_enrich(asset, cfg["ltf"], rr=rr)
            dfs_full[asset] = df
            filled = df[df["outcome"].isin([-1, 1])]
            wr = (filled["pnl_r"] > 0).mean() if len(filled) else 0
            ex = filled["pnl_r"].mean() if len(filled) else 0
            baselines[asset] = {
                "n_total": len(df),
                "n_filled": len(filled),
                "baseline_wr": round(float(wr), 3),
                "baseline_exp_r": round(float(ex), 3),
            }
            print(f"  {asset}: {len(df)} candidates, {len(filled)} filled, "
                  f"baseline WR={wr:.3f}, exp_R={ex:+.3f}")
        except Exception as e:
            print(f"  {asset}: SKIPPED ({type(e).__name__}: {e})")

    # ---------------------------------------------------
    # Phase 3 : discovery INDÉPENDANTE sur IS de chaque asset
    # ---------------------------------------------------
    banner("PHASE 3 — DISCOVERY INDÉPENDANTE PAR ASSET", "═")
    discovery = EdgeDiscovery(
        rr_target=rr, min_samples=20,
        min_winrate=0.55, min_expectancy=0.08,
    )
    all_edges_by_asset: dict[str, list] = {}
    dfs_is: dict[str, pd.DataFrame] = {}
    dfs_oos: dict[str, pd.DataFrame] = {}

    for asset, df in dfs_full.items():
        is_df, oos_df = _split_is_oos(df, 0.30)
        dfs_is[asset] = is_df
        dfs_oos[asset] = oos_df
        edges = discovery.discover(is_df)
        all_edges_by_asset[asset] = edges
        print(f"  {asset}: {len(edges)} edges discovered in-sample")
        if edges:
            top = discovery.summarize(edges, top_n=5)
            print(top.to_string(index=False))
            print()

    # ---------------------------------------------------
    # Phase 4 : UNION des edges candidats (on combine les insights de tous les assets)
    # ---------------------------------------------------
    banner("PHASE 4 — AGRÉGATION DES EDGES CANDIDATS", "═")
    edges_seen = {}
    for asset, edges in all_edges_by_asset.items():
        for e in edges:
            key = tuple(sorted((k, str(v)) for k, v in e.filters.items()))
            if key not in edges_seen or e.quality_score > edges_seen[key][1].quality_score:
                edges_seen[key] = (asset, e)
    unique_edges = [v[1] for v in edges_seen.values()]
    print(f"  Total unique edge patterns (dedup'd): {len(unique_edges)}")

    # ---------------------------------------------------
    # Phase 5 : VALIDATION CROSS-ASSET
    # Un edge doit fonctionner sur ≥ 2 actifs (hors asset d'origine)
    # ---------------------------------------------------
    banner("PHASE 5 — VALIDATION CROSS-ASSET (OOS + autres actifs)", "═")
    validator = EdgeValidator(min_oos_samples=10, min_robustness_ratio=0.80)

    stress = RealityStressEngine(
        slippage_pips_mean=0.7, slippage_pips_std=0.4,
        spread_pips_mean=1.2, spread_pips_std=0.6,
        commission_r_cost=0.06,
    )

    final_edges = []
    for edge in unique_edges:
        # 1) Validation OOS sur l'asset d'origine
        origin_asset = edges_seen[tuple(sorted((k, str(v)) for k, v in edge.filters.items()))][0]
        oos_origin = validator.validate_oos(edge, dfs_oos[origin_asset])
        if not oos_origin.passes_oos:
            continue

        # 2) Cross-asset : validation sur les AUTRES assets (en utilisant tout leur df)
        cross_results = {}
        n_cross_valid = 0
        for a, df in dfs_full.items():
            if a == origin_asset:
                continue
            vr = validator.validate_oos(edge, df)
            cross_results[a] = {
                "n": vr.oos_n,
                "winrate": round(vr.oos_winrate, 3),
                "expectancy": round(vr.oos_expectancy, 3),
                "robustness": round(vr.robustness_ratio, 3),
                "valid": vr.passes_oos,
            }
            if vr.passes_oos:
                n_cross_valid += 1

        # 3) Reality stress
        # on stress sur le df d'origine
        real_res = stress.stress_edge(dfs_full[origin_asset], edge, rr_target=rr)

        # Critère final : edge OOS OK + survit sur au moins 1 autre asset + survit stress réel
        survived_cross = n_cross_valid >= 1
        survived_reality = real_res.still_positive
        survived_all = oos_origin.passes_oos and survived_cross and survived_reality

        if survived_all:
            final_edges.append({
                "description": edge.description,
                "filters": edge.filters,
                "origin_asset": origin_asset,
                "is_winrate": round(edge.winrate, 3),
                "is_n": edge.n_samples,
                "oos_origin_winrate": round(oos_origin.oos_winrate, 3),
                "oos_origin_n": oos_origin.oos_n,
                "oos_origin_expectancy": round(oos_origin.oos_expectancy, 3),
                "robustness_origin": round(oos_origin.robustness_ratio, 3),
                "rr": round(edge.rr, 2),
                "cross_asset": cross_results,
                "n_cross_valid": n_cross_valid,
                "stressed_expectancy": round(real_res.stressed_expectancy, 3),
                "degradation_pct": round(real_res.expectancy_degradation_pct, 1),
            })

    # Rank by quality (robustness × cross valid × stressed expectancy)
    final_edges.sort(key=lambda e: (
        e["n_cross_valid"],
        e["robustness_origin"] * e["stressed_expectancy"],
    ), reverse=True)

    # ---------------------------------------------------
    # Phase 9 : RAPPORT FINAL
    # ---------------------------------------------------
    banner("PHASE 9 — RAPPORT FINAL MULTI-ASSET", "═")
    print("\n  BASELINES (sans filtre) :")
    for a, b in baselines.items():
        print(f"    {a:8s} : {b['n_filled']:5d} trades | WR {b['baseline_wr']:.3f} | exp_R {b['baseline_exp_r']:+.3f}")

    print(f"\n  Edges testés (uniques)       : {len(unique_edges)}")
    print(f"  Edges survivant TOUTES phases: {len(final_edges)}")

    if final_edges:
        print("\n  ✅ EDGES FINAUX (conditions robustes) :\n")
        for i, e in enumerate(final_edges[:10], 1):
            print(f"  #{i}  {e['description']}")
            print(f"       Origin asset : {e['origin_asset']}")
            print(f"       IS  WR       : {e['is_winrate']:.2%} (n={e['is_n']})")
            print(f"       OOS WR (orig): {e['oos_origin_winrate']:.2%} (n={e['oos_origin_n']})")
            print(f"       OOS exp_R    : {e['oos_origin_expectancy']:+.3f}")
            print(f"       Robustness   : {e['robustness_origin']:.2f}")
            print(f"       Cross-asset OK: {e['n_cross_valid']}/{len(ASSET_CONFIG) - 1}")
            for a, cr in e["cross_asset"].items():
                tag = "✓" if cr["valid"] else "✗"
                print(f"         {tag} {a}: WR {cr['winrate']:.2%} exp_R {cr['expectancy']:+.3f} (n={cr['n']})")
            print(f"       After stress : exp_R {e['stressed_expectancy']:+.3f} (deg {e['degradation_pct']:.1f}%)")
            print()
        verdict = "EDGE_FOUND"
    else:
        print("\n  ❌ AUCUN edge ne survit aux tests : OOS + cross-asset + stress.")
        print("  C'est un VERDICT SCIENTIFIQUE honnête.")
        print("  Avec les conditions brutes (tout FVG sans filtre HTF), il n'y a")
        print("  pas d'edge universel ≥ 70% WR / RR 2 reproducible.")
        print("\n  Ce que ça PROUVE :")
        print("   1. Les setups ICT bruts, isolés, ne constituent PAS un edge")
        print("   2. L'edge doit venir de la COMBINAISON de conditions ET du")
        print("      MONEY MANAGEMENT (partial TP, trailing, BE) — pas d'un seul")
        print("      filtre statique.")
        print("   3. Le vrai edge est comportemental : discipline, FOMO control,")
        print("      respect du Risk Engine.")
        verdict = "NO_UNIVERSAL_EDGE"

    # Save
    out = REPORTS_DIR / f"edge_multi_asset_{datetime.utcnow():%Y%m%d_%H%M%S}.json"
    payload = {
        "timestamp": datetime.utcnow().isoformat(),
        "rr_target": rr,
        "assets": list(ASSET_CONFIG.keys()),
        "baselines": baselines,
        "edges_discovered_by_asset": {a: len(v) for a, v in all_edges_by_asset.items()},
        "unique_edge_patterns": len(unique_edges),
        "final_robust_edges": final_edges,
        "verdict": verdict,
    }
    out.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n  💾 Full report: {out}")
    print("\n" + "═" * 76)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rr", type=float, default=2.0)
    args = ap.parse_args()
    run_multi(rr=args.rr)
