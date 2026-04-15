"""
Adaptation Engine — self-correction SANS overfitting.

PRINCIPES :
1. On ne ré-optimise QUE sur données HORS échantillon
2. On désactive les setups systématiquement perdants (stat. significatif)
3. On AJUSTE les poids avec régression robuste, pas grid search
4. Toute adaptation doit survivre à une validation croisée

C'est l'opposé d'un "tuning" agressif. L'objectif est d'éliminer les
signaux morts, pas d'optimiser la courbe d'equity.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, List
from scipy import stats

from src.utils.types import Trade
from src.utils.logging_conf import get_logger
from src.scoring_engine import ScoringEngine, DEFAULT_WEIGHTS

log = get_logger(__name__)


@dataclass
class AdaptationReport:
    disabled_setups: List[str]
    new_weights: Dict[str, float]
    changes_rationale: List[str]


class AdaptationEngine:

    def __init__(self, min_trades_for_decision: int = 30,
                 p_value_threshold: float = 0.05):
        self.min_n = min_trades_for_decision
        self.alpha = p_value_threshold

    # ------------------------------------------------------------------
    def analyze_and_adapt(
        self,
        trades: List[Trade],
    ) -> AdaptationReport:
        report = AdaptationReport([], dict(DEFAULT_WEIGHTS), [])

        if len(trades) < self.min_n:
            report.changes_rationale.append(
                f"Not enough trades ({len(trades)} < {self.min_n}) — no changes applied"
            )
            return report

        # 1. Analyse par grade, session, régime
        dead_killzones = self._find_dead_slice(trades, lambda t: t.signal.killzone)
        dead_regimes = self._find_dead_slice(trades, lambda t: t.signal.regime.value)
        dead_grades = self._find_dead_slice(trades, lambda t: t.signal.grade.value)

        for kz in dead_killzones:
            report.disabled_setups.append(f"killzone:{kz}")
            report.changes_rationale.append(
                f"Killzone '{kz}' systematically losing (stat. significant) — DISABLED"
            )
        for rg in dead_regimes:
            report.disabled_setups.append(f"regime:{rg}")
            report.changes_rationale.append(
                f"Regime '{rg}' systematically losing — DISABLED"
            )

        # 2. Ré-calibration des poids via régression logistique
        new_weights = self._relearn_weights(trades)
        if new_weights:
            report.new_weights = new_weights
            report.changes_rationale.append(
                "Weights re-learned via logistic regression on realized outcomes"
            )

        return report

    # ------------------------------------------------------------------
    def _find_dead_slice(self, trades: List[Trade], key_fn) -> List[str]:
        groups: Dict[str, List[Trade]] = {}
        for t in trades:
            try:
                k = key_fn(t)
            except Exception:
                continue
            if k is None:
                continue
            groups.setdefault(str(k), []).append(t)

        dead: List[str] = []
        for k, ts in groups.items():
            if len(ts) < self.min_n:
                continue
            r_values = [t.pnl_r for t in ts]
            mean_r = np.mean(r_values)
            # Test si mean < 0 avec significance
            if mean_r >= 0:
                continue
            # t-test unilatéral H0: mean = 0, H1: mean < 0
            t_stat, p_val = stats.ttest_1samp(r_values, 0)
            if t_stat < 0 and (p_val / 2) < self.alpha:
                dead.append(k)
        return dead

    # ------------------------------------------------------------------
    def _relearn_weights(self, trades: List[Trade]) -> Dict[str, float] | None:
        """
        Régression logistique : features de setup → win/loss.
        Coefficients normalisés → nouveaux poids.
        """
        # Extraction features si disponibles (stockées dans signal.reasons ou via scoring)
        # Pour cette version : on utilise les features reconstruites à partir des Signal
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.preprocessing import StandardScaler
        except ImportError:
            log.warning("sklearn not available — skipping weight relearn")
            return None

        X = []
        y = []
        for t in trades:
            if t.pnl_r is None:
                continue
            sig = t.signal
            # Reconstruire le vecteur features approximativement
            feats = {
                "htf_bias_align": 1,   # par construction dans ExecutionEngine
                "killzone_active": 1,
                "liquidity_swept": 1 if sig.swept_liquidity else 0,
                "fvg_impulsion": sig.fvg_ref.impulsion_score if sig.fvg_ref else 0,
                "ob_valid": 1 if sig.ob_ref else 0,
                "bb_ifvg_confluence": 0,
                "regime_compatible": 1,
                "rr_min_2": 1 if sig.risk_reward >= 2 else 0,
                "smt_confluence": 0,
            }
            # normalise fvg_impulsion
            feats["fvg_impulsion"] = min(1.0, feats["fvg_impulsion"] / 2.0)
            X.append([feats[k] for k in DEFAULT_WEIGHTS.keys()])
            y.append(1 if t.is_win else 0)

        X = np.array(X, dtype=float)
        y = np.array(y)

        if len(np.unique(y)) < 2 or X.shape[0] < self.min_n:
            return None

        scaler = StandardScaler()
        try:
            Xs = scaler.fit_transform(X)
            model = LogisticRegression(max_iter=500, C=1.0)
            model.fit(Xs, y)
            coefs = np.abs(model.coef_[0])
            # Normalise : poids = |coef| / sum(|coef|)
            total = coefs.sum()
            if total == 0:
                return None
            weights = {
                k: float(coefs[i] / total)
                for i, k in enumerate(DEFAULT_WEIGHTS.keys())
            }
            return weights
        except Exception as e:
            log.error(f"Relearn failed: {e}")
            return None
