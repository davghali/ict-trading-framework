"""
Bias Engine — produit un biais DIRECTIONNEL PROBABILISTE (jamais certain).

Approche multi-timeframe :
1. Weekly : structure + draw on liquidity (IRL → ERL ou inverse)
2. Daily : swing direction + liquidité cible
3. H4 : confluence finale

Logique ICT :
- Si weekly délivre vers PWH → biais = bullish
- Si weekly a déjà touché PWH → chercher draw vers PWL
- IRL → ERL : price s'étire vers liquidité externe
- ERL → IRL : price revient vers l'intérieur du range

Output : probabilité [0, 1] pour bullish, [0, 1] pour bearish, complement = neutral
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

from src.utils.types import BiasDirection, LiquidityPool, LiquidityType
from src.ict_engine.structure import MarketStructure, TrendState
from src.ict_engine.liquidity import LiquidityDetector
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class BiasAssessment:
    timestamp: datetime
    direction: BiasDirection
    probability: float                  # confidence en le biais choisi
    weekly_trend: str
    daily_trend: str
    next_target: float                  # niveau le plus probable à atteindre
    target_type: str                    # "PWH", "PDL", etc.
    reasons: List[str]


class BiasEngine:

    def __init__(self):
        self.structure = MarketStructure()
        self.liq = LiquidityDetector()

    def assess(
        self,
        df_weekly: pd.DataFrame,
        df_daily: pd.DataFrame,
        df_h4: pd.DataFrame,
        reference_ts: datetime,
    ) -> BiasAssessment:
        """
        Produit un assessment à la date reference_ts — uniquement sur données passées.
        """
        ref_ts = pd.Timestamp(reference_ts)
        if ref_ts.tz is None:
            ref_ts = ref_ts.tz_localize("UTC")
        else:
            ref_ts = ref_ts.tz_convert("UTC")
        w = df_weekly[df_weekly.index < ref_ts]
        d = df_daily[df_daily.index < ref_ts]
        h4 = df_h4[df_h4.index < ref_ts]

        if len(w) < 10 or len(d) < 20 or len(h4) < 50:
            return BiasAssessment(
                timestamp=reference_ts,
                direction=BiasDirection.NEUTRAL,
                probability=0.5,
                weekly_trend="insufficient_data",
                daily_trend="insufficient_data",
                next_target=float("nan"),
                target_type="none",
                reasons=["Insufficient history"],
            )

        # Analyse structurelle
        w_analysis = self.structure.analyze(w)
        d_analysis = self.structure.analyze(d)

        weekly_trend: TrendState = w_analysis["current_trend"]
        daily_trend: TrendState = d_analysis["current_trend"]

        reasons: List[str] = []
        bull_score = 0.0
        bear_score = 0.0

        # Weekly dominance (HTF plus lourd)
        if weekly_trend == TrendState.BULLISH:
            bull_score += 0.35
            reasons.append("Weekly trend bullish (HH/HL)")
        elif weekly_trend == TrendState.BEARISH:
            bear_score += 0.35
            reasons.append("Weekly trend bearish (LH/LL)")

        if daily_trend == TrendState.BULLISH:
            bull_score += 0.20
            reasons.append("Daily trend bullish")
        elif daily_trend == TrendState.BEARISH:
            bear_score += 0.20
            reasons.append("Daily trend bearish")

        # Dernier event structurel sur daily
        if d_analysis["events"]:
            last_ev = d_analysis["events"][-1]
            if "UP" in last_ev.event:
                bull_score += 0.15
                reasons.append(f"Last daily event: {last_ev.event}")
            elif "DOWN" in last_ev.event:
                bear_score += 0.15
                reasons.append(f"Last daily event: {last_ev.event}")

        # Liquidité : où va le "draw" ?
        pools = self.liq.detect_session_levels(d)
        target_price, target_type = self._pick_liquidity_target(pools, d, bull_score, bear_score)

        # Confluence H4 récente
        h4_analysis = self.structure.analyze(h4.tail(200))
        if h4_analysis["current_trend"] == TrendState.BULLISH:
            bull_score += 0.10
        elif h4_analysis["current_trend"] == TrendState.BEARISH:
            bear_score += 0.10

        # Normalisation
        total = bull_score + bear_score
        if total == 0:
            direction = BiasDirection.NEUTRAL
            prob = 0.5
        elif bull_score > bear_score:
            direction = BiasDirection.BULLISH
            prob = bull_score / total
        else:
            direction = BiasDirection.BEARISH
            prob = bear_score / total

        # Plafonnement : jamais > 0.85 (probabiliste, jamais certain)
        prob = min(0.85, max(0.15, prob))

        return BiasAssessment(
            timestamp=reference_ts,
            direction=direction,
            probability=prob,
            weekly_trend=weekly_trend.value,
            daily_trend=daily_trend.value,
            next_target=target_price,
            target_type=target_type,
            reasons=reasons,
        )

    # ------------------------------------------------------------------
    def _pick_liquidity_target(
        self,
        pools: List[LiquidityPool],
        df: pd.DataFrame,
        bull_score: float,
        bear_score: float,
    ):
        if df.empty or not pools:
            return float("nan"), "none"
        current = float(df["close"].iloc[-1])

        # Non-swept pools, trier par distance
        unswept = [p for p in pools if not p.swept]
        if not unswept:
            return float("nan"), "none"

        if bull_score >= bear_score:
            above = [p for p in unswept if p.price > current]
            if above:
                nearest = min(above, key=lambda p: p.price - current)
                return nearest.price, nearest.ltype.value
        else:
            below = [p for p in unswept if p.price < current]
            if below:
                nearest = min(below, key=lambda p: current - p.price)
                return nearest.price, nearest.ltype.value

        return float("nan"), "none"
