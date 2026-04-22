"""
CYBORG ENHANCER — upgrade les signaux existants avec :
- Cross-asset filter (DXY, SPX, VIX)
- Multi-TF strict alignment
- Dynamic exit selon régime
- Ladder entries (3 entries au lieu de 1)

Usage :
    enhancer = CyborgEnhancer()
    for signal in raw_signals:
        enhanced = enhancer.enhance(signal, df_weekly, df_daily, df_h4, df_h1, regime)
        if enhanced is None:
            continue  # filtered out by cross-asset ou multi-TF
        # enhanced has improved TP/SL + ladder entries
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List
import pandas as pd

from src.live_scanner.scanner import LiveSignal
from src.cross_asset import CrossAssetFilter, CorrelationCheck
from src.multi_tf import MultiTFAlignment
from src.dynamic_exit import DynamicExit, ExitPlan
from src.utils.types import Side, Regime
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class LadderEntry:
    """Un niveau d'entrée (ladder de 3 entrées)."""
    price: float
    lot_pct: float           # pourcentage de la size totale


@dataclass
class EnhancedSignal:
    """Signal avec toutes les features cyborg."""
    base: LiveSignal
    cross_asset: Optional[CorrelationCheck] = None
    multi_tf_score: float = 0.0
    multi_tf_details: List[str] = field(default_factory=list)
    exit_plan: Optional[ExitPlan] = None
    ladder_entries: List[LadderEntry] = field(default_factory=list)
    final_probability: float = 0.0          # proba × multi-tf × cross-asset
    cyborg_grade: str = ""                   # S / A+ / A / B / Skip


class CyborgEnhancer:

    def __init__(
        self,
        cross_min_score: float = 0.5,
        multi_tf_min_score: float = 0.60,
    ):
        self.cross_filter = CrossAssetFilter(min_score=cross_min_score)
        self.multi_tf = MultiTFAlignment(min_score=multi_tf_min_score)
        self.exit_calc = DynamicExit()

    # ------------------------------------------------------------------
    def enhance(
        self,
        signal: LiveSignal,
        df_weekly: pd.DataFrame,
        df_daily: pd.DataFrame,
        df_h4: pd.DataFrame,
        df_h1: pd.DataFrame,
        regime: Regime,
        atr: float,
    ) -> Optional[EnhancedSignal]:
        """
        Enrichit un signal. Retourne None si filtré.
        """
        side = Side.LONG if signal.side == "long" else Side.SHORT

        # 1. Cross-asset check
        try:
            ca = self.cross_filter.check(signal.symbol, side)
        except Exception as e:
            log.debug(f"Cross-asset check failed: {e}")
            ca = None

        if ca is not None and not ca.passed:
            log.info(f"🚫 {signal.symbol} {signal.side}: cross-asset failed (score {ca.score:.2f})")
            return None

        # 2. Multi-TF strict
        try:
            tf_result = self.multi_tf.check(side, df_weekly, df_daily, df_h4, df_h1)
        except Exception as e:
            log.debug(f"Multi-TF check failed: {e}")
            tf_result = None

        if tf_result is not None and not tf_result.passed:
            log.info(f"🚫 {signal.symbol} {signal.side}: multi-TF failed (score {tf_result.score:.2f})")
            return None

        # 3. Dynamic exit selon régime
        try:
            exit_plan = self.exit_calc.compute(
                side=side, entry=signal.entry,
                initial_sl=signal.stop_loss, atr=atr,
                regime=regime,
            )
        except Exception as e:
            log.warning(f"Dynamic exit calc failed: {e}")
            exit_plan = None

        # 4. Ladder entries
        ladder = self._build_ladder(signal, side, atr)

        # 5. Final probability (pondérée)
        # FIX : les scores cross/multi-TF à 0 étaient PÉNALISANTS (final_prob = base*0.5).
        # Un score de 0 signifie "pas d'info" (filter échoué/absent), pas "mauvais signal".
        # → traiter les scores < 0.1 comme NEUTRES (0.5) pour ne pas pénaliser le signal.
        base_prob = signal.ml_prob_win or 0.4

        _mt = tf_result.score if tf_result else 0.75
        if _mt < 0.1:
            _mt = 0.5  # neutre : pas d'info
        multi_tf_boost = _mt

        _ca = ca.score if ca else 0.75
        if _ca < 0.1:
            _ca = 0.5  # neutre : pas d'info
        cross_boost = _ca

        final_prob = base_prob * (0.5 + 0.25 * multi_tf_boost + 0.25 * cross_boost)
        final_prob = min(0.95, final_prob)   # cap à 95%

        # 6. Cyborg grade (thresholds abaissés pour production avec seuils relaxés)
        if final_prob >= 0.55:
            grade = "S"
        elif final_prob >= 0.45:
            grade = "A+"
        elif final_prob >= 0.35:
            grade = "A"
        elif final_prob >= 0.25:
            grade = "B"
        else:
            grade = "Skip"

        if grade == "Skip":
            return None

        return EnhancedSignal(
            base=signal,
            cross_asset=ca,
            multi_tf_score=tf_result.score if tf_result else 0.0,
            multi_tf_details=tf_result.confirmations if tf_result else [],
            exit_plan=exit_plan,
            ladder_entries=ladder,
            final_probability=final_prob,
            cyborg_grade=grade,
        )

    # ------------------------------------------------------------------
    def _build_ladder(self, signal: LiveSignal, side: Side, atr: float) -> List[LadderEntry]:
        """
        3 entries :
        - 40% au CE (entry de base)
        - 30% à 66% du FVG (plus profond)
        - 30% à l'extrême FVG
        """
        if atr <= 0:
            return [LadderEntry(signal.entry, 1.0)]

        # FVG size from SL distance proxy
        risk = abs(signal.entry - signal.stop_loss)
        # 66% deeper = 0.33 * risk from entry toward SL
        if side == Side.LONG:
            entry_2 = signal.entry - 0.33 * risk
            entry_3 = signal.entry - 0.66 * risk
        else:
            entry_2 = signal.entry + 0.33 * risk
            entry_3 = signal.entry + 0.66 * risk

        return [
            LadderEntry(signal.entry, 0.40),
            LadderEntry(entry_2, 0.30),
            LadderEntry(entry_3, 0.30),
        ]
