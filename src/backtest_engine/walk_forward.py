"""
Walk-Forward Analysis.

Principe : plutôt qu'un backtest unique sur tout l'historique, on simule
un processus réaliste :
- Fenêtre d'apprentissage glissante
- Fenêtre de test hors échantillon juste après
- Avancer et répéter

Ex : train 2 ans → test 6 mois → avance de 6 mois → répéter.

Métriques :
- Moyenne/écart-type des métriques par fold
- Robustness ratio : performance out-of-sample / in-sample
  (proche de 1 = pas d'overfit, <0.5 = overfit sévère)
- Consistency : % de folds profitables
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Callable, Dict, Any
import pandas as pd
import numpy as np

from src.utils.types import BacktestResult
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class WalkForwardFold:
    fold_id: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    in_sample: BacktestResult
    out_of_sample: BacktestResult


@dataclass
class WalkForwardReport:
    folds: List[WalkForwardFold] = field(default_factory=list)

    def summary(self) -> dict:
        if not self.folds:
            return {"n_folds": 0}

        is_returns = [f.in_sample.total_return_pct for f in self.folds]
        oos_returns = [f.out_of_sample.total_return_pct for f in self.folds]
        is_sharpe = [f.in_sample.sharpe_ratio for f in self.folds]
        oos_sharpe = [f.out_of_sample.sharpe_ratio for f in self.folds]

        profitable_oos = sum(1 for r in oos_returns if r > 0)

        robustness_return = (
            np.mean(oos_returns) / np.mean(is_returns)
            if np.mean(is_returns) > 0 else 0
        )
        robustness_sharpe = (
            np.mean(oos_sharpe) / np.mean(is_sharpe)
            if np.mean(is_sharpe) > 0 else 0
        )

        return {
            "n_folds": len(self.folds),
            "is_return_mean": round(float(np.mean(is_returns)), 2),
            "is_return_std": round(float(np.std(is_returns)), 2),
            "oos_return_mean": round(float(np.mean(oos_returns)), 2),
            "oos_return_std": round(float(np.std(oos_returns)), 2),
            "is_sharpe_mean": round(float(np.mean(is_sharpe)), 2),
            "oos_sharpe_mean": round(float(np.mean(oos_sharpe)), 2),
            "profitable_oos_pct": round(100 * profitable_oos / len(self.folds), 1),
            "robustness_ratio_return": round(float(robustness_return), 3),
            "robustness_ratio_sharpe": round(float(robustness_sharpe), 3),
            "verdict": self._verdict(robustness_return, profitable_oos / len(self.folds)),
        }

    @staticmethod
    def _verdict(robustness: float, profitable_pct: float) -> str:
        if robustness >= 0.70 and profitable_pct >= 0.65:
            return "ROBUST"
        if robustness >= 0.50 and profitable_pct >= 0.50:
            return "ACCEPTABLE"
        if robustness < 0.30 or profitable_pct < 0.40:
            return "OVERFIT_SUSPECT"
        return "MARGINAL"


class WalkForwardEngine:

    def __init__(
        self,
        train_years: float = 2.0,
        test_months: int = 6,
        step_months: int = 6,
        min_trades_per_fold: int = 20,
    ):
        self.train_years = train_years
        self.test_months = test_months
        self.step_months = step_months
        self.min_trades = min_trades_per_fold

    def run(
        self,
        df: pd.DataFrame,
        train_fn: Callable[[pd.DataFrame], Any],
        eval_fn: Callable[[pd.DataFrame, Any], BacktestResult],
    ) -> WalkForwardReport:
        """
        train_fn : reçoit le sous-dataframe train, retourne le modèle/params
        eval_fn : reçoit (df, model) et retourne un BacktestResult
        """
        report = WalkForwardReport()
        if df.empty:
            return report

        start = df.index[0]
        end = df.index[-1]
        train_span = pd.DateOffset(years=self.train_years)
        test_span = pd.DateOffset(months=self.test_months)
        step_span = pd.DateOffset(months=self.step_months)

        fold_id = 0
        cursor = start + train_span

        while cursor + test_span <= end:
            train_start = cursor - train_span
            train_end = cursor
            test_start = cursor
            test_end = cursor + test_span

            train_df = df[(df.index >= train_start) & (df.index < train_end)]
            test_df = df[(df.index >= test_start) & (df.index < test_end)]

            if len(train_df) < 200 or len(test_df) < 50:
                cursor += step_span
                continue

            try:
                model = train_fn(train_df)
                is_result = eval_fn(train_df, model)
                oos_result = eval_fn(test_df, model)
            except Exception as e:
                log.error(f"Fold {fold_id} failed: {e}")
                cursor += step_span
                continue

            # Skip folds with too few trades
            if is_result.total_trades < self.min_trades and oos_result.total_trades < 5:
                log.warning(f"Fold {fold_id} skipped: too few trades "
                            f"(is={is_result.total_trades}, oos={oos_result.total_trades})")
                cursor += step_span
                continue

            fold = WalkForwardFold(
                fold_id=fold_id,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                in_sample=is_result,
                out_of_sample=oos_result,
            )
            report.folds.append(fold)
            log.info(
                f"WF fold {fold_id}: IS ret {is_result.total_return_pct:.2f}% | "
                f"OOS ret {oos_result.total_return_pct:.2f}% | "
                f"OOS trades {oos_result.total_trades}"
            )
            fold_id += 1
            cursor += step_span

        log.info(f"Walk-Forward: {len(report.folds)} folds completed")
        return report
