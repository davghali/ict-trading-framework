"""
Scoring Engine — évalue la qualité d'un setup POTENTIEL.

Approche :
1. Phase 1 — poids a priori (heuristiques ICT) pour démarrer
2. Phase 2 — AFTER backtest, les poids sont APPRIS via régression logistique
   sur les features vs. issue réelle (win/loss normalisé en R)

CRITÈRES DE SCORING :
Chaque setup est scoré sur une batterie de critères. Le score agrégé
détermine le grade (A+/A/B/Reject).

CRITÈRES :
- HTF bias align  (poids a priori 0.20)
- Killzone active (0.15)
- Prise de liquidité préalable (0.15)
- FVG impulsion_score (0.10)
- OB valide avec FVG (0.10)
- BB + IFVG confluence (0.08)
- Régime compatible (0.08)
- Distance au target (RR ≥ 2) (0.08)
- SMT divergence (bonus +0.06)

Score 0-100. Mapping :
- 85+ : A+
- 70-84 : A
- 55-69 : B
- <55 : reject
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, List

from src.utils.types import (
    Signal, SetupGrade, BiasDirection, Regime, Side,
    FVG, OrderBlock, LiquidityPool, BreakerBlock,
)
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


DEFAULT_WEIGHTS = {
    "htf_bias_align": 0.20,
    "killzone_active": 0.15,
    "liquidity_swept": 0.15,
    "fvg_impulsion": 0.10,
    "ob_valid": 0.10,
    "bb_ifvg_confluence": 0.08,
    "regime_compatible": 0.08,
    "rr_min_2": 0.08,
    "smt_confluence": 0.06,
}


@dataclass
class SetupFeatures:
    """Features extraites d'un setup candidat."""
    htf_bias_align: int = 0              # 0 or 1
    killzone_active: int = 0
    liquidity_swept: int = 0
    fvg_impulsion: float = 0.0           # [0, 1] normalized
    ob_valid: int = 0
    bb_ifvg_confluence: int = 0
    regime_compatible: int = 0
    rr_min_2: int = 0
    smt_confluence: int = 0

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in DEFAULT_WEIGHTS.keys()}


class ScoringEngine:

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or dict(DEFAULT_WEIGHTS)
        self._validate_weights()
        self._model_path = Path(__file__).parent / "learned_weights.pkl"

    def _validate_weights(self) -> None:
        s = sum(self.weights.values())
        if abs(s - 1.0) > 0.02:
            log.warning(f"Weights sum to {s:.3f}, not 1.0. Normalizing.")
            self.weights = {k: v / s for k, v in self.weights.items()}

    # ------------------------------------------------------------------
    def score(self, features: SetupFeatures) -> float:
        """Score 0-100."""
        feats = features.to_dict()
        # Normalize continuous features
        feats["fvg_impulsion"] = min(1.0, max(0.0, feats["fvg_impulsion"]))
        total = sum(self.weights[k] * feats[k] for k in self.weights)
        return float(total * 100)

    def grade(self, score: float) -> SetupGrade:
        if score >= 85:
            return SetupGrade.A_PLUS
        if score >= 70:
            return SetupGrade.A
        if score >= 55:
            return SetupGrade.B
        return SetupGrade.REJECT

    # ------------------------------------------------------------------
    def evaluate_setup(
        self,
        *,
        htf_bias: BiasDirection,
        proposed_side: Side,
        current_killzone: Optional[str],
        recent_swept_liquidity: Optional[LiquidityPool],
        fvg: Optional[FVG],
        ob: Optional[OrderBlock],
        bb: Optional[BreakerBlock],
        regime: Regime,
        rr: float,
        smt_present: bool,
    ) -> tuple[SetupFeatures, float, SetupGrade]:
        """Évalue un setup candidat → (features, score, grade)."""
        f = SetupFeatures()

        # HTF bias align
        if htf_bias == BiasDirection.BULLISH and proposed_side == Side.LONG:
            f.htf_bias_align = 1
        elif htf_bias == BiasDirection.BEARISH and proposed_side == Side.SHORT:
            f.htf_bias_align = 1

        # Killzone
        f.killzone_active = int(current_killzone in {
            "london_kz", "london_open", "ny_am_kz", "ny_open", "ny_pm_kz",
        })

        # Liquidity swept
        f.liquidity_swept = int(recent_swept_liquidity is not None
                                 and recent_swept_liquidity.swept)

        # FVG impulsion normalisée (0-1)
        if fvg is not None:
            f.fvg_impulsion = min(1.0, fvg.impulsion_score / 2.0)

        # OB valid
        f.ob_valid = int(ob is not None and ob.is_valid)

        # BB+IFVG
        f.bb_ifvg_confluence = int(bb is not None and bb.is_valid)

        # Régime compatible
        trending_regimes = {Regime.TRENDING_HIGH_VOL, Regime.TRENDING_LOW_VOL}
        f.regime_compatible = int(regime in trending_regimes
                                    or regime == Regime.RANGING_LOW_VOL)

        # RR
        f.rr_min_2 = int(rr >= 2.0)

        # SMT
        f.smt_confluence = int(smt_present)

        score = self.score(f)
        grade = self.grade(score)
        return f, score, grade

    # ------------------------------------------------------------------
    def save_learned_weights(self, weights: Dict[str, float]) -> None:
        self._model_path.write_bytes(pickle.dumps(weights))
        log.info(f"Saved learned weights: {weights}")

    def load_learned_weights(self) -> Optional[Dict[str, float]]:
        if not self._model_path.exists():
            return None
        return pickle.loads(self._model_path.read_bytes())
