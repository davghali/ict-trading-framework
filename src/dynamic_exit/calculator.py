"""
DYNAMIC EXIT — ajuste TP/SL/trailing selon le régime de marché détecté.

Régimes :
- TRENDING_HIGH_VOL  : TP jusqu'à 5R, trailing agressif après 2R
- TRENDING_LOW_VOL   : TP 3R, trailing après 1.5R
- RANGING_HIGH_VOL   : TP1 1.5R (partial 50%), TP2 2.5R
- RANGING_LOW_VOL    : TP 1.5R simple (ranges courts)
- MANIPULATION       : NO TRADE
- UNKNOWN            : TP 2R conservateur

Output : ExitPlan avec TP1, TP2, SL, trailing_start, BE_move, partial %.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.utils.types import Side, Regime
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class ExitPlan:
    # Entry level (for reference)
    entry: float
    stop_loss: float
    # Exit levels
    tp1: float
    tp2: float
    tp3: Optional[float] = None        # only for strong trending
    # Dynamic management
    partial_tp1_pct: float = 0.50      # % de position à fermer au TP1
    move_be_at_r: float = 0.5           # R à partir duquel déplacer SL à BE
    trailing_start_r: float = 2.0       # R à partir duquel enclencher trailing
    trailing_distance_atr: float = 1.0  # distance ATR pour le trailing
    # Risk metrics
    risk_per_unit: float = 0.0
    rr_to_tp1: float = 0.0
    rr_to_tp2: float = 0.0
    max_rr: float = 0.0
    # Context
    regime: str = "unknown"
    rationale: str = ""


class DynamicExit:

    def compute(
        self,
        side: Side,
        entry: float,
        initial_sl: float,
        atr: float,
        regime: Regime,
    ) -> ExitPlan:
        """
        Calcule le plan d'exit complet selon le régime.
        """
        risk = abs(entry - initial_sl)
        if risk <= 0 or atr <= 0:
            return ExitPlan(
                entry=entry, stop_loss=initial_sl,
                tp1=entry, tp2=entry,
                regime=regime.value,
                rationale="Invalid risk/atr",
            )

        # Multiplicateur de risque selon side
        mult = 1 if side == Side.LONG else -1

        if regime == Regime.TRENDING_HIGH_VOL:
            tp1_r = 1.5
            tp2_r = 3.0
            tp3_r = 5.0
            partial = 0.33              # 1/3 partial à chaque TP
            be_at = 0.5
            trail_start = 2.0
            trail_atr = 1.5
            rat = "Trending + high vol → laisser courir jusqu'à 5R"
        elif regime == Regime.TRENDING_LOW_VOL:
            tp1_r = 1.5
            tp2_r = 3.0
            tp3_r = None
            partial = 0.50
            be_at = 0.7
            trail_start = 1.5
            trail_atr = 1.0
            rat = "Trending calme → TP à 3R avec trailing 1.5R"
        elif regime == Regime.RANGING_HIGH_VOL:
            tp1_r = 1.2
            tp2_r = 2.0
            tp3_r = None
            partial = 0.60              # prends vite car range instable
            be_at = 0.5
            trail_start = 1.5
            trail_atr = 0.8
            rat = "Range volatile → prendre TP vite (1.2R / 2R)"
        elif regime == Regime.RANGING_LOW_VOL:
            tp1_r = 1.5
            tp2_r = 2.5
            tp3_r = None
            partial = 0.50
            be_at = 1.0
            trail_start = 2.0
            trail_atr = 0.8
            rat = "Range calme → TP 1.5R / 2.5R standards"
        elif regime == Regime.MANIPULATION:
            # Ne devrait pas arriver (filtré upstream) mais fallback conservateur
            tp1_r = 1.0
            tp2_r = 1.5
            tp3_r = None
            partial = 0.80
            be_at = 0.5
            trail_start = 1.0
            trail_atr = 0.5
            rat = "Manipulation détectée — exit rapide"
        else:  # UNKNOWN
            tp1_r = 2.0
            tp2_r = 3.0
            tp3_r = None
            partial = 0.50
            be_at = 1.0
            trail_start = 2.0
            trail_atr = 1.0
            rat = "Régime incertain — TP standard 2R/3R"

        tp1 = entry + mult * tp1_r * risk
        tp2 = entry + mult * tp2_r * risk
        tp3 = entry + mult * tp3_r * risk if tp3_r else None

        return ExitPlan(
            entry=entry,
            stop_loss=initial_sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            partial_tp1_pct=partial,
            move_be_at_r=be_at,
            trailing_start_r=trail_start,
            trailing_distance_atr=trail_atr,
            risk_per_unit=risk,
            rr_to_tp1=tp1_r,
            rr_to_tp2=tp2_r,
            max_rr=tp3_r or tp2_r,
            regime=regime.value,
            rationale=rat,
        )
