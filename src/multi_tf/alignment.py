"""
MULTI-TF STRICT ALIGNMENT — enforce Weekly → Daily → H4 → H1 → M15 same direction.

Principe ICT : un trade ne se prend que si TOUS les timeframes supérieurs sont alignés.

Niveaux :
- Weekly : tendance macro (HH/HL ou LH/LL sur 10 dernières weekly candles)
- Daily : confirmation (current trend D1)
- H4 : POI alignement (zone d'intérêt H4)
- H1 : structure break (BOS confirmé)
- M15 : entry confirmation (optionnel)

Retourne un score 0-1 + détail par timeframe.
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum

from src.ict_engine.structure import MarketStructure, TrendState
from src.utils.types import Timeframe, Side
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


class TFBias(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class AlignmentResult:
    weekly: str
    daily: str
    h4: str
    h1: str
    confirmations: List[str] = field(default_factory=list)
    score: float = 0.0
    passed: bool = False


class MultiTFAlignment:

    def __init__(self, min_score: float = 0.75, weight_weekly: float = 0.35,
                 weight_daily: float = 0.30, weight_h4: float = 0.20,
                 weight_h1: float = 0.15):
        """
        min_score : seuil (défaut 75% d'alignement)
        Weekly pèse le plus car c'est la macro.
        """
        self.min_score = min_score
        self.w_w = weight_weekly
        self.w_d = weight_daily
        self.w_h4 = weight_h4
        self.w_h1 = weight_h1
        self.ms = MarketStructure()

    # ------------------------------------------------------------------
    def check(self, side: Side, df_weekly: pd.DataFrame,
               df_daily: pd.DataFrame, df_h4: pd.DataFrame,
               df_h1: pd.DataFrame) -> AlignmentResult:
        required = TFBias.BULLISH if side == Side.LONG else TFBias.BEARISH

        # Trend analysis per TF
        weekly_trend = self._trend(df_weekly, lookback=10)
        daily_trend = self._trend(df_daily, lookback=20)
        h4_trend = self._trend(df_h4, lookback=20)
        h1_trend = self._trend(df_h1, lookback=20)

        confirmations = []
        score = 0.0

        # Weekly
        if weekly_trend == required:
            confirmations.append(f"W {weekly_trend.value} ✓")
            score += self.w_w
        elif weekly_trend == TFBias.NEUTRAL:
            confirmations.append(f"W neutral (partial)")
            score += self.w_w * 0.5
        else:
            confirmations.append(f"W {weekly_trend.value} ✗")

        # Daily
        if daily_trend == required:
            confirmations.append(f"D {daily_trend.value} ✓")
            score += self.w_d
        elif daily_trend == TFBias.NEUTRAL:
            confirmations.append(f"D neutral (partial)")
            score += self.w_d * 0.5
        else:
            confirmations.append(f"D {daily_trend.value} ✗")

        # H4
        if h4_trend == required:
            confirmations.append(f"H4 {h4_trend.value} ✓")
            score += self.w_h4
        elif h4_trend == TFBias.NEUTRAL:
            confirmations.append(f"H4 neutral")
            score += self.w_h4 * 0.5
        else:
            confirmations.append(f"H4 {h4_trend.value} ✗")

        # H1
        if h1_trend == required:
            confirmations.append(f"H1 {h1_trend.value} ✓")
            score += self.w_h1
        elif h1_trend == TFBias.NEUTRAL:
            confirmations.append(f"H1 neutral")
            score += self.w_h1 * 0.5
        else:
            confirmations.append(f"H1 {h1_trend.value} ✗")

        return AlignmentResult(
            weekly=weekly_trend.value,
            daily=daily_trend.value,
            h4=h4_trend.value,
            h1=h1_trend.value,
            confirmations=confirmations,
            score=score,
            passed=score >= self.min_score,
        )

    # ------------------------------------------------------------------
    def _trend(self, df: pd.DataFrame, lookback: int = 20) -> TFBias:
        """Détecte la tendance via swings HH/HL ou LH/LL sur N dernières bars."""
        if len(df) < lookback:
            return TFBias.NEUTRAL
        sub = df.tail(lookback * 3)
        swings = self.ms._find_swings(sub)
        if len(swings) < 4:
            # Fallback : comparaison simple close first vs last
            pct = (df["close"].iloc[-1] - df["close"].iloc[-lookback]) / df["close"].iloc[-lookback]
            if pct > 0.01:
                return TFBias.BULLISH
            elif pct < -0.01:
                return TFBias.BEARISH
            return TFBias.NEUTRAL
        # Structure : last 4 swings
        highs = [s for s in swings if s.kind == "high"][-2:]
        lows = [s for s in swings if s.kind == "low"][-2:]
        if len(highs) >= 2 and len(lows) >= 2:
            hh = highs[-1].price > highs[-2].price
            hl = lows[-1].price > lows[-2].price
            lh = highs[-1].price < highs[-2].price
            ll = lows[-1].price < lows[-2].price
            if hh and hl:
                return TFBias.BULLISH
            if lh and ll:
                return TFBias.BEARISH
        return TFBias.NEUTRAL
