"""
EDGE DOMINANCE ENGINE — runner complet.

Exécute les 9 phases :
1. Génération massive (NE FILTRE RIEN)
2. Feature explosion
3. Edge discovery (pattern mining)
4. Isolation (filtres exacts)
5. Validation brutale (OOS + cross-asset)
6. Simulation avancée (Monte Carlo)
7. Optimisation sans biais (stabilité only)
8. Test de réalité (slippage/spread/commission)
9. Destruction des illusions + rapport final

USAGE :
    python run_edge_discovery.py
    python run_edge_discovery.py --primary NAS100 --ltf 1h
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path
import argparse
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
warnings.filterwarnings("ignore")

from src.data_engine import DataLoader
from src.feature_engine import FeatureEngine
from src.validation_engine import DataSplitter
from src.utils.types import Timeframe
from src.edge_dominance_engine import (
    EdgeCandidateGenerator, EdgeFeatureBuilder, EdgeDiscovery,
    EdgeValidator, RealityStressEngine, EdgeReporter,
)


def banner(t):
    print("\n" + "─" * 72)
    print(f"  {t}")
    print("─" * 72)


def _prep_dfs(symbol: str, ltf: Timeframe):
    loader = DataLoader()
    df_d = loader.load(symbol, Timeframe.D1)
    df_ltf = loader.load(symbol, ltf)
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
    return df_ltf, df_d, df_w, df_h4


def run(primary_symbol: str = "NAS100", ltf: Timeframe = Timeframe.H1,
        cross_assets: list = None, rr: float = 2.0):
    cross_assets = cross_assets or []

    # ===========================================================
    banner(f"PHASE 1 — GÉNÉRATION MASSIVE ({primary_symbol} {ltf.value})")
    df_ltf, df_d, df_w, df_h4 = _prep_dfs(primary_symbol, ltf)
    print(f"  Data: {len(df_ltf)} bars {df_ltf.index[0].date()} → {df_ltf.index[-1].date()}")

    gen = EdgeCandidateGenerator(rr_target=rr)
    candidates = gen.generate(primary_symbol, df_ltf)
    candidates = gen.simulate(candidates, df_ltf)
    print(f"  Trades simulés (filled): {len(candidates)}")

    # ===========================================================
    banner("PHASE 2 — FEATURE EXPLOSION")
    fb = EdgeFeatureBuilder(use_htf_bias=True)
    candidates = fb.enrich(candidates, df_ltf, df_d, df_w, df_h4)
    df_cand = gen.to_dataframe(candidates)
    print(f"  Feature vector width: {df_cand.shape[1]}")

    # Split in-sample / out-of-sample (temporal)
    # 70% IS, 30% OOS
    n = len(df_cand)
    cut = int(n * 0.70)
    df_cand_sorted = df_cand.sort_values("timestamp").reset_index(drop=True)
    df_is = df_cand_sorted.iloc[:cut]
    df_oos = df_cand_sorted.iloc[cut:]
    print(f"  IS  : {len(df_is)} trades ({df_is['timestamp'].iloc[0]} → {df_is['timestamp'].iloc[-1]})")
    print(f"  OOS : {len(df_oos)} trades ({df_oos['timestamp'].iloc[0]} → {df_oos['timestamp'].iloc[-1]})")

    # Baseline
    filled_is = df_is[df_is["outcome"].isin([-1, 1])]
    base_wr = (filled_is["pnl_r"] > 0).mean() if len(filled_is) else 0
    base_ex = filled_is["pnl_r"].mean() if len(filled_is) else 0
    print(f"  Baseline IS : WR={base_wr:.3f}, exp_R={base_ex:+.3f}")

    # ===========================================================
    banner("PHASE 3 — EDGE DISCOVERY (pattern mining multi-dim)")
    discovery = EdgeDiscovery(
        rr_target=rr, min_samples=20,
        min_winrate=0.55, min_expectancy=0.10,
    )
    edges = discovery.discover(df_is)
    print(f"  Edges candidats passant les seuils : {len(edges)}")
    if edges:
        summary = discovery.summarize(edges, top_n=15)
        print("\n  Top 15 :")
        print(summary.to_string(index=False))

    # ===========================================================
    banner("PHASE 4-5 — ISOLATION + VALIDATION OOS BRUTALE")
    validator = EdgeValidator(min_oos_samples=10, min_robustness_ratio=0.80)
    validated = [validator.validate_oos(e, df_oos) for e in edges]
    passing = [v for v in validated if v.passes_oos]
    print(f"  Edges survivant OOS : {len(passing)} / {len(validated)}")
    if validated:
        sum_df = validator.summarize(validated)
        print("\n  Validation OOS (top 15) :")
        print(sum_df.head(15).to_string(index=False))

    # ===========================================================
    banner("PHASE 5 bis — VALIDATION CROSS-ASSET")
    cross_data = {}
    if cross_assets:
        for a in cross_assets:
            try:
                df_a_ltf, df_a_d, df_a_w, df_a_h4 = _prep_dfs(a, ltf)
                cand_a = gen.generate(a, df_a_ltf)
                cand_a = gen.simulate(cand_a, df_a_ltf)
                cand_a = fb.enrich(cand_a, df_a_ltf, df_a_d, df_a_w, df_a_h4)
                df_a = gen.to_dataframe(cand_a)
                cross_data[a] = df_a
                print(f"  {a}: {len(df_a)} trades simulés")
            except Exception as e:
                print(f"  {a}: SKIPPED ({e})")
    cross_results: dict = {}
    for v in validated:
        if v.passes_oos and cross_data:
            cross_results[v.edge.description] = validator.validate_cross_asset(v.edge, cross_data)

    # ===========================================================
    banner("PHASE 8 — TEST DE RÉALITÉ (slippage/spread/commission)")
    stress = RealityStressEngine(
        slippage_pips_mean=0.5, slippage_pips_std=0.3,
        spread_pips_mean=1.0, spread_pips_std=0.5,
        commission_r_cost=0.05,
    )
    reality_results = [stress.stress_edge(df_cand, v.edge, rr_target=rr) for v in validated if v.passes_oos]
    if reality_results:
        print("  Edges passant après frictions réelles :")
        for r in reality_results:
            status = "✓" if r.still_positive else "✗"
            print(f"    {status} {r.edge_description[:60]:60s} | "
                  f"base_exp {r.baseline_expectancy:+.3f} → "
                  f"stressed {r.stressed_expectancy:+.3f} "
                  f"(dégradation {r.expectancy_degradation_pct:.1f}%)")

    # ===========================================================
    banner("PHASE 9 — RAPPORT FINAL (destruction des illusions)")
    reporter = EdgeReporter()
    report = reporter.build(
        asset_primary=primary_symbol,
        n_generated=len(candidates),
        n_simulated=len(candidates),
        baseline={"winrate": base_wr, "expectancy": base_ex},
        discovered=edges,
        validated=validated,
        cross_asset=cross_results,
        reality=reality_results,
    )
    path = reporter.save(report)
    reporter.print_report(report)
    print(f"\n  💾 Full report saved : {path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary", default="NAS100")
    ap.add_argument("--ltf", default="1h")
    ap.add_argument("--cross", nargs="+", default=[])
    ap.add_argument("--rr", type=float, default=2.0)
    args = ap.parse_args()

    run(primary_symbol=args.primary, ltf=Timeframe(args.ltf),
        cross_assets=args.cross, rr=args.rr)
