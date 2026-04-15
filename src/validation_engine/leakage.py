"""
Leakage Detector — traque les fuites de données subtiles.

Types de fuite détectés :
1. FEATURE LEAKAGE : feature utilise future data (shift négatif caché)
2. TARGET LEAKAGE : target dérive d'info présente au moment T
3. TRAIN-TEST CONTAMINATION : overlap d'index
4. WALK-FORWARD FAIL : modèle ré-entraîné utilise données futures

Ces fuites sont la cause #1 des "stratégies magiques" qui échouent en réel.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Tuple

from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class LeakageReport:
    passed: bool
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class LeakageDetector:

    def check_dataset_overlap(
        self,
        train: pd.DataFrame,
        val: pd.DataFrame,
        test: pd.DataFrame,
    ) -> LeakageReport:
        """Aucun index ne doit être partagé entre train/val/test."""
        r = LeakageReport(passed=True)

        tr_idx = set(train.index)
        va_idx = set(val.index)
        te_idx = set(test.index)

        ov_tv = tr_idx & va_idx
        ov_tt = tr_idx & te_idx
        ov_vt = va_idx & te_idx

        if ov_tv:
            r.issues.append(f"{len(ov_tv)} indices overlap train/val")
            r.passed = False
        if ov_tt:
            r.issues.append(f"{len(ov_tt)} indices overlap train/test")
            r.passed = False
        if ov_vt:
            r.issues.append(f"{len(ov_vt)} indices overlap val/test")
            r.passed = False

        # Ordre temporel
        if len(train) and len(val) and train.index.max() >= val.index.min():
            r.issues.append("Train extends INTO validation period (time leak)")
            r.passed = False
        if len(val) and len(test) and val.index.max() >= test.index.min():
            r.issues.append("Validation extends INTO test period (time leak)")
            r.passed = False

        return r

    def check_features_no_lookahead(
        self,
        df: pd.DataFrame,
        feature_cols: List[str],
        close_col: str = "close",
    ) -> LeakageReport:
        """
        Heuristique : une feature qui corrèle anormalement avec un futur return
        AU MÊME timestamp est suspecte. Un feature correct utilise uniquement
        de l'info passée, donc sa corrélation avec close[t+1] doit être modérée.

        LIMITE : c'est une heuristique, pas une preuve formelle. Idéalement
        on audit manuellement chaque feature.
        """
        r = LeakageReport(passed=True)
        if close_col not in df.columns:
            r.warnings.append(f"{close_col} missing — skip lookahead check")
            return r

        future_return = df[close_col].pct_change().shift(-1)
        for col in feature_cols:
            if col not in df.columns:
                continue
            series = df[col]
            if series.dtype == "O" or series.nunique() < 5:
                continue
            # Corrélation contemporaine feature[t] ↔ return[t+1]
            mask = series.notna() & future_return.notna()
            if mask.sum() < 100:
                continue
            corr = series[mask].corr(future_return[mask])
            if corr is not None and abs(corr) > 0.5:
                r.warnings.append(
                    f"Feature '{col}' has suspiciously high corr with future "
                    f"return: {corr:.3f} — AUDIT MANUALLY"
                )
        return r

    def check_walk_forward_respect(
        self,
        train_end: pd.Timestamp,
        eval_start: pd.Timestamp,
        min_gap_days: int = 1,
    ) -> LeakageReport:
        r = LeakageReport(passed=True)
        gap = (eval_start - train_end).total_seconds() / 86400
        if gap < 0:
            r.issues.append(f"Walk-forward violation: eval ({eval_start}) starts "
                            f"BEFORE train ends ({train_end})")
            r.passed = False
        elif gap < min_gap_days:
            r.warnings.append(f"Walk-forward gap only {gap:.1f} days "
                              f"(recommend ≥ {min_gap_days})")
        return r

    def check_feature_stationarity_shift(
        self,
        train_features: pd.DataFrame,
        test_features: pd.DataFrame,
        threshold_std: float = 3.0,
    ) -> LeakageReport:
        """
        Si distributions de features sont TRÈS différentes train vs test,
        c'est un signal de régime-shift potentiel — le modèle risque de
        généraliser mal (pas une fuite directe, mais un risque majeur).
        """
        r = LeakageReport(passed=True)
        common = [c for c in train_features.columns if c in test_features.columns]
        for col in common:
            if train_features[col].dtype == "O":
                continue
            tr_mean = train_features[col].mean()
            tr_std = train_features[col].std() or 1.0
            te_mean = test_features[col].mean()
            if abs(te_mean - tr_mean) > threshold_std * tr_std:
                r.warnings.append(
                    f"Feature '{col}' distribution shifted "
                    f"(train μ={tr_mean:.4f}, test μ={te_mean:.4f}, "
                    f"train σ={tr_std:.4f}) — regime shift risk"
                )
        return r
