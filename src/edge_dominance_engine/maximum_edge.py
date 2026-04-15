"""
MAXIMUM EDGE ENGINE — ML-based scoring + Pareto frontier.

Objectif : maximiser simultanément WR ET volume via :
1. Gradient Boosted Classifier appris SUR IS
2. Calibration isotonique (P(win) prédit = WR réel)
3. Validation OOS stricte
4. Courbe Pareto : pour chaque threshold t, (WR, volume)
5. 3 tiers par asset : ELITE / BALANCED / VOLUME

PHILOSOPHIE :
Le ML ne "prédit" pas gagnant/perdant. Il classe les candidats par
P(win) CALIBRÉE. Tu choisis ensuite ton point (WR min, volume min) et le
système filtre aux candidats dépassant cette P(win).
"""
from __future__ import annotations

import warnings
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

warnings.filterwarnings("ignore", category=UserWarning)

from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class ParetoPoint:
    """Un point sur la courbe Pareto — un choix (threshold → WR, volume)."""
    threshold: float                    # P(win) minimum
    n_trades_oos: int
    winrate_oos: float
    expectancy_r_oos: float
    trades_per_month: float
    total_r_oos: float


@dataclass
class MLEdgeResult:
    asset: str
    ltf: str
    feature_cols: List[str]
    n_train: int
    n_test: int
    baseline_wr_test: float
    pareto: List[ParetoPoint]
    tiers: Dict[str, ParetoPoint]       # "elite" / "balanced" / "volume"
    calibration_test: dict               # diag calibration
    feature_importance: Dict[str, float]


class MaximumEdgeEngine:
    """
    Construit un scoreur ML par asset.

    Dépendances : scikit-learn.
    """

    def __init__(
        self,
        rr_target: float = 2.0,
        min_trades_elite: int = 5,
        min_trades_balanced: int = 15,
        min_trades_volume: int = 30,
    ):
        self.rr = rr_target
        self.min_elite = min_trades_elite
        self.min_balanced = min_trades_balanced
        self.min_volume = min_trades_volume

    # ------------------------------------------------------------------
    FEATURES_NUMERIC = [
        "fvg_size_atr", "fvg_impulsion", "atr_pct", "realized_vol_20",
        "adx_14", "bb_width_percentile", "hour_utc", "day_of_week",
        "dist_to_nearest_liquidity_atr", "dist_to_swing_h_atr",
        "dist_to_swing_l_atr",
    ]
    FEATURES_CATEGORICAL = [
        "side", "killzone", "session", "volatility_bucket",
        "trend_state", "htf_bias", "fvg_irl_erl",
    ]
    FEATURES_BOOL = [
        "has_ob", "has_bb_ifvg", "recent_sweep_low", "recent_sweep_high",
        "bos_up_recent", "bos_down_recent", "htf_align",
    ]

    def _prepare_features(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
        """One-hot encode categoricals + coerce numerics."""
        out = df.copy()

        # Numerics — fillna avec médiane (robuste aux outliers)
        for col in self.FEATURES_NUMERIC:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
                out[col] = out[col].fillna(out[col].median())
            else:
                out[col] = 0.0

        # Booleans
        for col in self.FEATURES_BOOL:
            if col in out.columns:
                out[col] = out[col].astype(int)
            else:
                out[col] = 0

        # One-hot for categoricals
        cat_cols_present = [c for c in self.FEATURES_CATEGORICAL if c in out.columns]
        if cat_cols_present:
            dummies = pd.get_dummies(out[cat_cols_present].fillna("NA"),
                                      prefix=cat_cols_present)
            out = pd.concat([out, dummies], axis=1)
            out = out.drop(columns=cat_cols_present)

        feat_cols = self.FEATURES_NUMERIC + self.FEATURES_BOOL + \
            [c for c in out.columns if any(c.startswith(cat + "_") for cat in cat_cols_present)]
        feat_cols = [c for c in feat_cols if c in out.columns]

        return out[feat_cols + (["outcome", "pnl_r", "timestamp"] if "outcome" in out.columns else [])], feat_cols

    # ------------------------------------------------------------------
    def analyze_asset(
        self,
        asset: str,
        ltf: str,
        df_candidates: pd.DataFrame,
        train_pct: float = 0.70,
    ) -> Optional[MLEdgeResult]:
        """
        Entraîne + valide OOS + calcule Pareto.
        """
        try:
            from sklearn.ensemble import GradientBoostingClassifier
            from sklearn.calibration import CalibratedClassifierCV
            from sklearn.metrics import roc_auc_score
        except ImportError:
            log.error("scikit-learn required")
            return None

        # Filter filled
        df = df_candidates[df_candidates["outcome"].isin([-1, 1])].copy()
        if len(df) < 100:
            log.warning(f"{asset}: only {len(df)} trades — skip ML")
            return None

        # Prepare features
        df_prep, feat_cols = self._prepare_features(df)
        df_prep = df_prep.sort_values("timestamp").reset_index(drop=True)

        # Split temporal
        cut = int(len(df_prep) * train_pct)
        train = df_prep.iloc[:cut]
        test = df_prep.iloc[cut:]
        if len(test) < 30:
            log.warning(f"{asset}: OOS only {len(test)} trades — skip ML")
            return None

        X_train = train[feat_cols].values
        y_train = (train["outcome"] == 1).astype(int).values
        X_test = test[feat_cols].values
        y_test = (test["outcome"] == 1).astype(int).values
        pnl_test = test["pnl_r"].values
        times_test = pd.to_datetime(test["timestamp"].values)

        # Model : GradientBoosting — robust to small data
        base = GradientBoostingClassifier(
            n_estimators=150, max_depth=3, learning_rate=0.05,
            subsample=0.8, min_samples_leaf=10,
            random_state=42,
        )
        # Calibration via isotonic sur IS avec CV
        try:
            model = CalibratedClassifierCV(base, method="isotonic", cv=3)
            model.fit(X_train, y_train)
        except Exception as e:
            log.warning(f"{asset}: calibration CV failed ({e}), using raw GBM")
            base.fit(X_train, y_train)
            model = base

        # OOS predictions
        probs = model.predict_proba(X_test)[:, 1]

        # AUC pour sanity check
        try:
            auc = roc_auc_score(y_test, probs)
        except Exception:
            auc = 0.5

        baseline_wr_test = y_test.mean()

        # Feature importance (on the base model)
        if hasattr(model, "calibrated_classifiers_"):
            importances = np.mean([c.estimator.feature_importances_
                                   for c in model.calibrated_classifiers_], axis=0)
        elif hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
        else:
            importances = np.zeros(len(feat_cols))
        importance_dict = {
            f: float(imp) for f, imp in sorted(
                zip(feat_cols, importances),
                key=lambda x: -x[1]
            )[:15]
        }

        # Pareto frontier — scan thresholds
        thresholds = np.linspace(0.30, 0.85, 12)
        pareto: List[ParetoPoint] = []
        span_days = (times_test.max() - times_test.min()).days
        months = max(1, span_days / 30)

        for t in thresholds:
            mask = probs >= t
            n = int(mask.sum())
            if n < 3:
                continue
            wr = float(y_test[mask].mean())
            ex = float(pnl_test[mask].mean())
            total = float(pnl_test[mask].sum())
            tpm = n / months
            pareto.append(ParetoPoint(
                threshold=float(t),
                n_trades_oos=n,
                winrate_oos=wr,
                expectancy_r_oos=ex,
                trades_per_month=float(tpm),
                total_r_oos=total,
            ))

        # Calibration diag : groupes de probs, vérifier que probs estimées ≈ WR réelles
        cal_diag = self._calibration_check(probs, y_test)

        # Pick 3 tiers :
        # ELITE  : highest WR avec au moins min_elite trades
        # BALANCED : best Sharpe × volume (prod WR × trades)
        # VOLUME : plus gros volume avec exp_R > 0
        tiers = {}
        if pareto:
            elite_cands = [p for p in pareto if p.n_trades_oos >= self.min_elite]
            if elite_cands:
                tiers["elite"] = max(elite_cands, key=lambda p: p.winrate_oos)

            balanced_cands = [p for p in pareto
                              if p.n_trades_oos >= self.min_balanced and p.expectancy_r_oos > 0.1]
            if balanced_cands:
                tiers["balanced"] = max(balanced_cands,
                                        key=lambda p: p.winrate_oos * np.log(p.n_trades_oos + 1))

            volume_cands = [p for p in pareto
                            if p.n_trades_oos >= self.min_volume and p.expectancy_r_oos > 0]
            if volume_cands:
                tiers["volume"] = max(volume_cands, key=lambda p: p.trades_per_month)

        log.info(f"{asset}: AUC={auc:.3f}, baseline WR={baseline_wr_test:.3f}, "
                 f"Pareto points={len(pareto)}, tiers={list(tiers.keys())}")

        return MLEdgeResult(
            asset=asset,
            ltf=ltf,
            feature_cols=feat_cols,
            n_train=len(train),
            n_test=len(test),
            baseline_wr_test=float(baseline_wr_test),
            pareto=pareto,
            tiers=tiers,
            calibration_test={"auc": float(auc), **cal_diag},
            feature_importance=importance_dict,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _calibration_check(probs: np.ndarray, y: np.ndarray) -> dict:
        """Vérifie que probs prédites ≈ taux de wins observé dans chaque bucket."""
        bins = [0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]
        out = {}
        for i in range(len(bins) - 1):
            lo, hi = bins[i], bins[i + 1]
            mask = (probs >= lo) & (probs < hi)
            n = mask.sum()
            if n < 5:
                continue
            predicted = probs[mask].mean()
            actual = y[mask].mean()
            out[f"p{int(lo*100):02d}-{int(hi*100):02d}"] = {
                "n": int(n),
                "predicted": round(float(predicted), 3),
                "actual": round(float(actual), 3),
            }
        return out
