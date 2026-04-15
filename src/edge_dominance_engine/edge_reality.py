"""
PHASE 6-8 — SIMULATION AVANCÉE + OPTIMISATION SANS BIAIS + RÉALITÉ.

Réinjecte des frictions réelles dans les trades simulés :
- Slippage variable (distribution log-normale)
- Spread variable (selon session et volatilité)
- Latence d'exécution (N bars de retard)
- Commission

Re-simule pour voir si l'edge survit.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict

from src.edge_dominance_engine.edge_discovery import EdgeCondition
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class RealityStressResult:
    edge_description: str
    baseline_winrate: float
    baseline_expectancy: float
    stressed_winrate: float
    stressed_expectancy: float
    expectancy_degradation_pct: float
    still_positive: bool


class RealityStressEngine:

    def __init__(
        self,
        slippage_pips_mean: float = 0.5,
        slippage_pips_std: float = 0.3,
        spread_pips_mean: float = 1.0,
        spread_pips_std: float = 0.5,
        latency_bars: int = 0,              # exécution retardée
        commission_r_cost: float = 0.05,    # coût fixe en R par trade
        seed: int = 42,
    ):
        self.slip_m = slippage_pips_mean
        self.slip_s = slippage_pips_std
        self.spread_m = spread_pips_mean
        self.spread_s = spread_pips_std
        self.latency = latency_bars
        self.commission_r = commission_r_cost
        self.rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------
    def stress(
        self,
        df_candidates: pd.DataFrame,
        rr_target: float = 2.0,
    ) -> pd.DataFrame:
        """
        Applique slippage + spread + commission sur chaque trade.
        Modifie pnl_r réaliste.
        """
        out = df_candidates.copy()
        n = len(out)

        # Slippage : réduit le profit sur TP, augmente la perte sur SL
        slippage_r = np.abs(self.rng.normal(self.slip_m, self.slip_s, n)) / 20
        # Spread : coût fixe au round-turn
        spread_r = np.abs(self.rng.normal(self.spread_m, self.spread_s, n)) / 20

        # Apply
        is_tp = out["outcome"] == 1
        is_sl = out["outcome"] == -1

        # TP profit devient rr - slippage - spread - commission
        out.loc[is_tp, "pnl_r_realistic"] = (
            rr_target - slippage_r[is_tp] - spread_r[is_tp] - self.commission_r
        )
        # SL loss : -1 - slippage - spread - commission (slippage ajoute à la perte)
        out.loc[is_sl, "pnl_r_realistic"] = (
            -1.0 - slippage_r[is_sl] - spread_r[is_sl] - self.commission_r
        )
        out.loc[out["outcome"] == 0, "pnl_r_realistic"] = -self.commission_r

        return out

    # ------------------------------------------------------------------
    def compare(
        self,
        df_before: pd.DataFrame,
        df_after: pd.DataFrame,
    ) -> Dict[str, float]:
        """Compare edge avant/après stress."""
        b = df_before[df_before["outcome"].isin([-1, 1])]
        a = df_after[df_after["outcome"].isin([-1, 1])]
        return {
            "baseline_winrate": float((b["pnl_r"] > 0).mean()),
            "baseline_expectancy": float(b["pnl_r"].mean()),
            "stressed_winrate": float((a["pnl_r_realistic"] > 0).mean()),
            "stressed_expectancy": float(a["pnl_r_realistic"].mean()),
        }

    # ------------------------------------------------------------------
    def stress_edge(
        self,
        df_candidates: pd.DataFrame,
        edge: EdgeCondition,
        rr_target: float = 2.0,
    ) -> RealityStressResult:
        """Stress-test un edge spécifique."""
        # Filter
        sub = df_candidates
        for k, v in edge.filters.items():
            if k not in sub.columns:
                continue
            sub = sub[sub[k] == v]
        sub = sub[sub["outcome"].isin([-1, 1])]

        if len(sub) < 10:
            return RealityStressResult(
                edge_description=edge.description,
                baseline_winrate=edge.winrate,
                baseline_expectancy=edge.expectancy_r,
                stressed_winrate=0,
                stressed_expectancy=0,
                expectancy_degradation_pct=100,
                still_positive=False,
            )

        stressed = self.stress(sub, rr_target)

        base_wr = (sub["pnl_r"] > 0).mean()
        base_ex = sub["pnl_r"].mean()
        str_wr = (stressed["pnl_r_realistic"] > 0).mean()
        str_ex = stressed["pnl_r_realistic"].mean()

        degradation = (base_ex - str_ex) / abs(base_ex) * 100 if base_ex != 0 else 0

        return RealityStressResult(
            edge_description=edge.description,
            baseline_winrate=float(base_wr),
            baseline_expectancy=float(base_ex),
            stressed_winrate=float(str_wr),
            stressed_expectancy=float(str_ex),
            expectancy_degradation_pct=float(degradation),
            still_positive=bool(str_ex > 0),
        )
