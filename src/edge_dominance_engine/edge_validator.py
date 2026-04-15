"""
PHASE 4-5 — ISOLATION + VALIDATION BRUTALE.

Une fois un edge identifié sur données d'entraînement :
1. L'appliquer TELQUEL sur une période OOS
2. L'appliquer sur un autre actif (cross-asset)
3. Rejeter immédiatement si performance s'écroule

SEUIL DE SURVIE :
- OOS winrate doit rester ≥ 80% de l'IS winrate
- OOS expectancy doit rester positive
- OOS n_samples ≥ 10 (sinon non significatif)
"""
from __future__ import annotations

import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Any

from src.edge_dominance_engine.edge_discovery import EdgeCondition
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class EdgeValidationResult:
    edge: EdgeCondition
    is_winrate: float
    oos_winrate: float
    oos_n: int
    oos_expectancy: float
    robustness_ratio: float           # oos_wr / is_wr
    passes_oos: bool
    cross_asset_results: Dict[str, Dict[str, float]] = field(default_factory=dict)
    verdict: str = "UNKNOWN"          # "ROBUST" | "MARGINAL" | "REJECTED"


class EdgeValidator:

    def __init__(self,
                 min_oos_samples: int = 10,
                 min_robustness_ratio: float = 0.80):
        self.min_n = min_oos_samples
        self.min_ratio = min_robustness_ratio

    # ------------------------------------------------------------------
    def apply_filters(self, df: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
        """Applique les filtres d'un edge sur un DataFrame de candidats."""
        out = df
        for k, v in filters.items():
            if k not in out.columns:
                return pd.DataFrame()
            # special handling for binned features stored as string
            if isinstance(v, str) and "(" in v and "]" in v:
                # bin matching — reconstituer
                binned_col = f"{k}_bin"
                if binned_col in out.columns:
                    out = out[out[binned_col].astype(str) == v]
                else:
                    out = out[out[k].astype(str) == v]
            else:
                out = out[out[k] == v]
        return out

    # ------------------------------------------------------------------
    def validate_oos(
        self,
        edge: EdgeCondition,
        df_test: pd.DataFrame,
    ) -> EdgeValidationResult:
        """Applique l'edge sur données test (OOS)."""
        sub = self.apply_filters(df_test, edge.filters)
        sub = sub[sub["outcome"].isin([-1, 1])]
        n = len(sub)

        if n < self.min_n:
            return EdgeValidationResult(
                edge=edge,
                is_winrate=edge.winrate,
                oos_winrate=0.0,
                oos_n=n,
                oos_expectancy=0.0,
                robustness_ratio=0.0,
                passes_oos=False,
                verdict="REJECTED_INSUFFICIENT_OOS",
            )

        oos_wr = (sub["pnl_r"] > 0).mean()
        oos_ex = sub["pnl_r"].mean()
        ratio = oos_wr / edge.winrate if edge.winrate > 0 else 0

        passes = (
            oos_ex > 0 and
            ratio >= self.min_ratio and
            n >= self.min_n
        )

        verdict = (
            "ROBUST" if passes and ratio >= 0.90 else
            "MARGINAL" if passes else
            "REJECTED"
        )

        return EdgeValidationResult(
            edge=edge,
            is_winrate=edge.winrate,
            oos_winrate=float(oos_wr),
            oos_n=n,
            oos_expectancy=float(oos_ex),
            robustness_ratio=float(ratio),
            passes_oos=bool(passes),
            verdict=verdict,
        )

    # ------------------------------------------------------------------
    def validate_cross_asset(
        self,
        edge: EdgeCondition,
        dfs_by_asset: Dict[str, pd.DataFrame],
    ) -> Dict[str, Dict[str, float]]:
        """Teste l'edge sur d'autres actifs."""
        out = {}
        for asset, df in dfs_by_asset.items():
            sub = self.apply_filters(df, edge.filters)
            sub = sub[sub["outcome"].isin([-1, 1])]
            if len(sub) < self.min_n:
                out[asset] = {"n": len(sub), "winrate": 0.0, "expectancy": 0.0, "valid": False}
                continue
            wr = (sub["pnl_r"] > 0).mean()
            ex = sub["pnl_r"].mean()
            out[asset] = {
                "n": len(sub),
                "winrate": round(float(wr), 3),
                "expectancy": round(float(ex), 3),
                "valid": bool(ex > 0 and wr >= edge.winrate * self.min_ratio),
            }
        return out

    # ------------------------------------------------------------------
    def summarize(self, results: List[EdgeValidationResult]) -> pd.DataFrame:
        rows = []
        for r in results:
            rows.append({
                "description": r.edge.description,
                "IS WR": round(r.is_winrate, 3),
                "OOS WR": round(r.oos_winrate, 3),
                "OOS n": r.oos_n,
                "OOS exp_R": round(r.oos_expectancy, 3),
                "robustness": round(r.robustness_ratio, 3),
                "verdict": r.verdict,
            })
        return pd.DataFrame(rows).sort_values("robustness", ascending=False)
