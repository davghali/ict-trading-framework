"""
Market Structure — Swings, BOS, CHoCH formalisés.

BOS (Break of Structure) : cassure de structure dans le SENS de la tendance
CHoCH (Change of Character) : cassure dans le sens CONTRAIRE = possible retournement

Protocole strict :
1. Identifier swings (pivots N-N)
2. Définir tendance actuelle (série de HH/HL ou LH/LL)
3. À chaque nouvelle bar : check if close crosses last swing high/low
4. Classifier la cassure : BOS (dans tendance) ou CHoCH (contre-tendance)
"""
from __future__ import annotations

import pandas as pd
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional

from src.utils.logging_conf import get_logger

log = get_logger(__name__)


class TrendState(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class StructureEvent:
    timestamp: datetime
    index: int
    event: str                          # "BOS_UP", "BOS_DOWN", "CHOCH_UP", "CHOCH_DOWN"
    price: float
    broken_level: float
    new_trend: str


@dataclass
class Swing:
    index: int
    timestamp: datetime
    price: float
    kind: str                           # "high" | "low"


class MarketStructure:

    def __init__(self, swing_lookback: int = 3):
        self.N = swing_lookback

    def analyze(self, df: pd.DataFrame) -> dict:
        swings = self._find_swings(df)
        events = self._find_structure_events(df, swings)
        trend = self._current_trend(swings)
        return {
            "swings": swings,
            "events": events,
            "current_trend": trend,
        }

    # ------------------------------------------------------------------
    def _find_swings(self, df: pd.DataFrame) -> List[Swing]:
        N = self.N
        h = df["high"].values
        l = df["low"].values
        idx = df.index
        out: List[Swing] = []
        for i in range(N, len(df) - N):
            if h[i] == max(h[i - N : i + N + 1]):
                out.append(Swing(i, idx[i].to_pydatetime(), float(h[i]), "high"))
            if l[i] == min(l[i - N : i + N + 1]):
                out.append(Swing(i, idx[i].to_pydatetime(), float(l[i]), "low"))
        out.sort(key=lambda s: s.index)
        return out

    # ------------------------------------------------------------------
    def _find_structure_events(
        self, df: pd.DataFrame, swings: List[Swing]
    ) -> List[StructureEvent]:
        events: List[StructureEvent] = []
        if len(swings) < 4:
            return events

        c = df["close"].values
        idx = df.index

        current_trend = TrendState.NEUTRAL
        last_high: Optional[Swing] = None
        last_low: Optional[Swing] = None

        for s in swings:
            if s.kind == "high":
                last_high = s
            else:
                last_low = s

        # Parcours bar-par-bar pour détecter BOS/CHoCH
        last_high_tracked = None
        last_low_tracked = None
        trend = TrendState.NEUTRAL

        for t in range(len(df)):
            # Update last swings visible as of t (causal)
            visible = [s for s in swings if s.index < t]
            if visible:
                highs = [s for s in visible if s.kind == "high"]
                lows = [s for s in visible if s.kind == "low"]
                if highs:
                    last_high_tracked = max(highs, key=lambda x: x.index)
                if lows:
                    last_low_tracked = max(lows, key=lambda x: x.index)

            close = c[t]

            # Cassure haussière ?
            if last_high_tracked and close > last_high_tracked.price:
                if trend in (TrendState.BEARISH, TrendState.NEUTRAL):
                    # CHoCH bullish
                    events.append(StructureEvent(
                        idx[t].to_pydatetime(), t, "CHOCH_UP",
                        float(close), last_high_tracked.price, "bullish"
                    ))
                    trend = TrendState.BULLISH
                elif trend == TrendState.BULLISH:
                    events.append(StructureEvent(
                        idx[t].to_pydatetime(), t, "BOS_UP",
                        float(close), last_high_tracked.price, "bullish"
                    ))
                last_high_tracked = None  # reset

            # Cassure baissière ?
            if last_low_tracked and close < last_low_tracked.price:
                if trend in (TrendState.BULLISH, TrendState.NEUTRAL):
                    events.append(StructureEvent(
                        idx[t].to_pydatetime(), t, "CHOCH_DOWN",
                        float(close), last_low_tracked.price, "bearish"
                    ))
                    trend = TrendState.BEARISH
                elif trend == TrendState.BEARISH:
                    events.append(StructureEvent(
                        idx[t].to_pydatetime(), t, "BOS_DOWN",
                        float(close), last_low_tracked.price, "bearish"
                    ))
                last_low_tracked = None

        return events

    # ------------------------------------------------------------------
    def _current_trend(self, swings: List[Swing]) -> TrendState:
        if len(swings) < 4:
            return TrendState.NEUTRAL
        highs = [s for s in swings[-8:] if s.kind == "high"]
        lows = [s for s in swings[-8:] if s.kind == "low"]
        if len(highs) >= 2 and len(lows) >= 2:
            hh = highs[-1].price > highs[-2].price
            hl = lows[-1].price > lows[-2].price
            lh = highs[-1].price < highs[-2].price
            ll = lows[-1].price < lows[-2].price
            if hh and hl:
                return TrendState.BULLISH
            if lh and ll:
                return TrendState.BEARISH
        return TrendState.NEUTRAL
