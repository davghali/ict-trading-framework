"""
PHASE 9 — REPORTING + DESTRUCTION DES ILLUSIONS.

Produit le rapport FINAL avec uniquement :
1. Les conditions exactes où un edge existe (ou "NONE — no edge found")
2. Le winrate réel validé (IS & OOS)
3. Le RR réel
4. La fréquence réelle (trades par an attendus)
5. Le drawdown réel (Monte Carlo)
6. Les conditions d'échec

+ AVERTISSEMENTS sur les biais détectés.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import pandas as pd

from src.edge_dominance_engine.edge_discovery import EdgeCondition
from src.edge_dominance_engine.edge_validator import EdgeValidationResult
from src.edge_dominance_engine.edge_reality import RealityStressResult
from src.utils.logging_conf import get_logger
from src.utils.config import REPORTS_DIR

log = get_logger(__name__)


@dataclass
class EdgeReport:
    timestamp: str
    asset_primary: str
    n_candidates_generated: int
    n_candidates_simulated: int
    baseline_winrate: float
    baseline_expectancy_r: float
    edges_discovered: int
    edges_validated_oos: int
    edges_passing_cross_asset: int
    edges_surviving_reality_stress: int
    final_edges: List[Dict] = field(default_factory=list)
    illusions_detected: List[str] = field(default_factory=list)
    verdict: str = "UNKNOWN"                        # "EDGE_FOUND" | "NO_EDGE" | "UNCERTAIN"
    warnings: List[str] = field(default_factory=list)


class EdgeReporter:

    def build(
        self,
        asset_primary: str,
        n_generated: int,
        n_simulated: int,
        baseline: Dict[str, float],
        discovered: List[EdgeCondition],
        validated: List[EdgeValidationResult],
        cross_asset: Dict[str, Dict[str, Dict]],
        reality: List[RealityStressResult],
    ) -> EdgeReport:
        rep = EdgeReport(
            timestamp=datetime.utcnow().isoformat(),
            asset_primary=asset_primary,
            n_candidates_generated=n_generated,
            n_candidates_simulated=n_simulated,
            baseline_winrate=baseline.get("winrate", 0),
            baseline_expectancy_r=baseline.get("expectancy", 0),
            edges_discovered=len(discovered),
            edges_validated_oos=sum(1 for r in validated if r.passes_oos),
            edges_passing_cross_asset=0,
            edges_surviving_reality_stress=sum(1 for r in reality if r.still_positive),
        )

        # Map des edges qui survivent à TOUT
        surviving: List[Dict] = []

        for val_res in validated:
            if not val_res.passes_oos:
                continue
            edge_desc = val_res.edge.description
            # Cross-asset
            x_asset = cross_asset.get(edge_desc, {})
            x_pass_count = sum(1 for v in x_asset.values() if v.get("valid"))
            if x_pass_count > 0:
                rep.edges_passing_cross_asset += 1
            # Reality stress
            real_res = next((r for r in reality if r.edge_description == edge_desc), None)
            survives_reality = real_res is not None and real_res.still_positive

            if val_res.passes_oos and survives_reality:
                surviving.append({
                    "description": edge_desc,
                    "filters": val_res.edge.filters,
                    "is_winrate": round(val_res.is_winrate, 3),
                    "oos_winrate": round(val_res.oos_winrate, 3),
                    "oos_n_samples": val_res.oos_n,
                    "oos_expectancy_r": round(val_res.oos_expectancy, 3),
                    "robustness_ratio": round(val_res.robustness_ratio, 3),
                    "rr": round(val_res.edge.rr, 2),
                    "stressed_expectancy_r": round(real_res.stressed_expectancy, 3),
                    "expectancy_degradation_pct": round(real_res.expectancy_degradation_pct, 1),
                    "cross_asset_validation": x_asset,
                    "verdict": val_res.verdict,
                })

        rep.final_edges = surviving

        # Verdict global
        if surviving and any(e["oos_winrate"] >= 0.70 for e in surviving):
            rep.verdict = "EDGE_FOUND"
        elif surviving:
            rep.verdict = "EDGE_MARGINAL"
        else:
            rep.verdict = "NO_EDGE"

        # Warnings
        if rep.baseline_winrate > 0.55 and rep.baseline_expectancy_r > 0.15:
            rep.warnings.append(
                f"Baseline WR ({rep.baseline_winrate:.2%}) & exp_R ({rep.baseline_expectancy_r:.2f}) "
                "are suspiciously high — verify simulator assumptions (TP first vs SL first)"
            )
        if rep.edges_discovered > 100:
            rep.warnings.append(
                f"{rep.edges_discovered} edges 'discovered' is high — multiple-testing "
                "inflation likely. Only trust edges surviving OOS + cross-asset + stress."
            )
        if rep.edges_validated_oos == 0 and rep.edges_discovered > 0:
            rep.illusions_detected.append(
                "All discovered edges failed OOS validation — in-sample edges were ILLUSIONS"
            )
        if rep.edges_surviving_reality_stress == 0 and rep.edges_validated_oos > 0:
            rep.illusions_detected.append(
                "Edges validated OOS but crushed by slippage/spread — EDGE PURE THEORY, "
                "impractical in real execution"
            )

        return rep

    # ------------------------------------------------------------------
    def save(self, report: EdgeReport) -> Path:
        out = REPORTS_DIR / f"edge_dominance_{report.asset_primary}_{datetime.utcnow():%Y%m%d_%H%M%S}.json"
        payload = {
            "timestamp": report.timestamp,
            "asset_primary": report.asset_primary,
            "n_candidates_generated": report.n_candidates_generated,
            "n_candidates_simulated": report.n_candidates_simulated,
            "baseline_winrate": report.baseline_winrate,
            "baseline_expectancy_r": report.baseline_expectancy_r,
            "edges_discovered": report.edges_discovered,
            "edges_validated_oos": report.edges_validated_oos,
            "edges_passing_cross_asset": report.edges_passing_cross_asset,
            "edges_surviving_reality_stress": report.edges_surviving_reality_stress,
            "final_edges": report.final_edges,
            "illusions_detected": report.illusions_detected,
            "warnings": report.warnings,
            "verdict": report.verdict,
        }
        out.write_text(json.dumps(payload, indent=2, default=str))
        log.info(f"Edge report saved: {out}")
        return out

    # ------------------------------------------------------------------
    def print_report(self, report: EdgeReport) -> None:
        print("\n" + "=" * 74)
        print(f"  EDGE DOMINANCE ENGINE — RAPPORT FINAL ({report.asset_primary})")
        print("=" * 74)
        print(f"  Candidates generated      : {report.n_candidates_generated}")
        print(f"  Candidates simulated      : {report.n_candidates_simulated}")
        print(f"  Baseline WR (no filter)   : {report.baseline_winrate:.3f}")
        print(f"  Baseline exp_R            : {report.baseline_expectancy_r:+.3f}")
        print(f"  Edges discovered          : {report.edges_discovered}")
        print(f"  Edges validated OOS       : {report.edges_validated_oos}")
        print(f"  Edges cross-asset OK      : {report.edges_passing_cross_asset}")
        print(f"  Edges surviving reality   : {report.edges_surviving_reality_stress}")
        print(f"\n  VERDICT : {report.verdict}")
        print("=" * 74)

        if report.final_edges:
            print("\n  EDGES SURVIVANTS (conditions → edge réel) :\n")
            for i, e in enumerate(report.final_edges[:10], 1):
                print(f"  #{i}  {e['description']}")
                print(f"       WR (IS)   : {e['is_winrate']:.2%}")
                print(f"       WR (OOS)  : {e['oos_winrate']:.2%}  (n={e['oos_n_samples']})")
                print(f"       OOS exp_R : {e['oos_expectancy_r']:+.3f}")
                print(f"       stressed  : {e['stressed_expectancy_r']:+.3f} "
                      f"(dégradation {e['expectancy_degradation_pct']:.1f}%)")
                print(f"       RR        : {e['rr']:.2f}")
                print(f"       robustness: {e['robustness_ratio']:.2f}")
                print(f"       verdict   : {e['verdict']}")
                print()
        else:
            print("\n  ❌ AUCUN EDGE N'A SURVÉCU AUX TESTS.")
            print("  C'est un résultat HONNÊTE. La plupart des 'edges' ICT ne passent")
            print("  pas la validation OOS stricte sur les données testées.")

        if report.illusions_detected:
            print("\n  ⚠ ILLUSIONS DÉTECTÉES :")
            for i in report.illusions_detected:
                print(f"     • {i}")

        if report.warnings:
            print("\n  ⚠ AVERTISSEMENTS :")
            for w in report.warnings:
                print(f"     • {w}")

        print("\n" + "=" * 74)
