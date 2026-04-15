"""
Monte Carlo Simulation — stress-test du système.

Trois méthodes :
1. RESHUFFLE : shuffle l'ordre des trades → teste si la performance
   dépend d'une séquence chanceuse
2. BOOTSTRAP : tire avec remise N trades → estime la distribution des
   résultats possibles
3. PARAMETRIC : génère N trades à partir de (win_rate, avg_win_r, avg_loss_r)

Output :
- Distribution des final balance
- Distribution des max drawdown (risk of ruin)
- Probabilité de violation FTMO/5ers
- VaR 95% / 99%
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List

from src.utils.types import Trade
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class MonteCarloResult:
    n_simulations: int
    mean_final_balance: float
    median_final_balance: float
    pct_5_final: float                  # worst 5%
    pct_95_final: float                 # best 5%
    mean_max_dd_pct: float
    worst_max_dd_pct: float             # 99th percentile DD
    p_violation_ftmo: float             # P(DD > 10%)
    p_violation_5ers: float             # P(daily_DD > 4% ou DD > 6%)
    p_profitable: float
    all_final_balances: np.ndarray = field(default_factory=lambda: np.array([]))
    all_max_dd: np.ndarray = field(default_factory=lambda: np.array([]))

    def summary(self) -> str:
        return (
            f"MC ({self.n_simulations} sims) — "
            f"Final mean: {self.mean_final_balance:,.0f} | "
            f"5% worst: {self.pct_5_final:,.0f} | "
            f"95% best: {self.pct_95_final:,.0f} | "
            f"Mean DD: {self.mean_max_dd_pct:.2f}% | "
            f"Worst DD (99th): {self.worst_max_dd_pct:.2f}% | "
            f"P(FTMO violated): {self.p_violation_ftmo * 100:.1f}% | "
            f"P(5ers violated): {self.p_violation_5ers * 100:.1f}% | "
            f"P(profitable): {self.p_profitable * 100:.1f}%"
        )


class MonteCarlo:

    def __init__(self, n_simulations: int = 1000, seed: int = 42):
        self.n_sims = n_simulations
        self.rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------
    def reshuffle(
        self,
        trades: List[Trade],
        initial_balance: float,
        ftmo_dd_limit: float = 10.0,
        the5ers_dd_limit: float = 6.0,
    ) -> MonteCarloResult:
        """Shuffle l'ordre des trades existants."""
        if not trades:
            return self._empty_result()
        pnls = np.array([t.pnl_usd for t in trades])
        return self._simulate(pnls, initial_balance, ftmo_dd_limit, the5ers_dd_limit)

    def bootstrap(
        self,
        trades: List[Trade],
        initial_balance: float,
        n_trades: int | None = None,
        ftmo_dd_limit: float = 10.0,
        the5ers_dd_limit: float = 6.0,
    ) -> MonteCarloResult:
        """Bootstrap with replacement."""
        if not trades:
            return self._empty_result()
        pnls = np.array([t.pnl_usd for t in trades])
        n = n_trades or len(pnls)
        # sample avec remise
        def draw():
            return self.rng.choice(pnls, size=n, replace=True)
        return self._simulate(None, initial_balance, ftmo_dd_limit, the5ers_dd_limit,
                              custom_draw=draw)

    def parametric(
        self,
        win_rate: float,
        avg_win: float,              # en $
        avg_loss: float,              # en $ (négatif)
        n_trades: int,
        initial_balance: float,
        ftmo_dd_limit: float = 10.0,
        the5ers_dd_limit: float = 6.0,
    ) -> MonteCarloResult:
        """Génère trades synthétiques à partir de stats."""
        def draw():
            wins = self.rng.random(n_trades) < win_rate
            pnls = np.where(wins, avg_win, avg_loss)
            # Ajout de noise gaussien (±30% de amplitude)
            noise = self.rng.normal(1.0, 0.15, n_trades)
            return pnls * noise
        return self._simulate(None, initial_balance, ftmo_dd_limit, the5ers_dd_limit,
                              custom_draw=draw)

    # ------------------------------------------------------------------
    def _simulate(
        self,
        base_pnls,
        initial_balance: float,
        ftmo_dd: float,
        the5ers_dd: float,
        custom_draw=None,
    ) -> MonteCarloResult:
        finals = np.zeros(self.n_sims)
        dds = np.zeros(self.n_sims)
        ftmo_viol = np.zeros(self.n_sims)
        the5ers_viol = np.zeros(self.n_sims)

        for i in range(self.n_sims):
            if custom_draw is not None:
                pnls = custom_draw()
            else:
                pnls = self.rng.permutation(base_pnls)
            equity = initial_balance + np.cumsum(pnls)
            peak = np.maximum.accumulate(equity)
            dd_pct = (equity - peak) / peak * 100
            dd_min = dd_pct.min() if len(dd_pct) else 0
            finals[i] = equity[-1]
            dds[i] = abs(dd_min)
            if abs(dd_min) >= ftmo_dd:
                ftmo_viol[i] = 1
            if abs(dd_min) >= the5ers_dd:
                the5ers_viol[i] = 1

        return MonteCarloResult(
            n_simulations=self.n_sims,
            mean_final_balance=float(np.mean(finals)),
            median_final_balance=float(np.median(finals)),
            pct_5_final=float(np.percentile(finals, 5)),
            pct_95_final=float(np.percentile(finals, 95)),
            mean_max_dd_pct=float(np.mean(dds)),
            worst_max_dd_pct=float(np.percentile(dds, 99)),
            p_violation_ftmo=float(ftmo_viol.mean()),
            p_violation_5ers=float(the5ers_viol.mean()),
            p_profitable=float((finals > initial_balance).mean()),
            all_final_balances=finals,
            all_max_dd=dds,
        )

    def _empty_result(self) -> MonteCarloResult:
        return MonteCarloResult(
            n_simulations=0,
            mean_final_balance=0, median_final_balance=0,
            pct_5_final=0, pct_95_final=0,
            mean_max_dd_pct=0, worst_max_dd_pct=0,
            p_violation_ftmo=0, p_violation_5ers=0, p_profitable=0,
        )
