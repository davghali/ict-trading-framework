"""
Order Block Detector — RÈGLE ICT STRICTE :
Un Order Block n'est VALIDE que si un FVG suit dans la même direction.

Définitions :
- Bullish OB : dernière bougie baissière AVANT un move haussier impulsif
  qui crée un FVG bullish
- Bearish OB : dernière bougie haussière AVANT un move baissier impulsif
  qui crée un FVG bearish

Ce module DÉPEND du FVGDetector.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import List

from src.utils.types import OrderBlock, FVG, Side
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


class OrderBlockDetector:

    def __init__(
        self,
        max_lookback: int = 10,     # max bars avant le FVG pour trouver l'OB
        atr_col: str = "atr_14",
    ):
        self.max_lookback = max_lookback
        self.atr_col = atr_col

    def detect(self, df: pd.DataFrame, fvgs: List[FVG]) -> List[OrderBlock]:
        out: List[OrderBlock] = []
        o = df["open"].values
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values
        atr = df[self.atr_col].values
        idx = df.index

        for fvg in fvgs:
            # Chercher la dernière bougie de sens OPPOSÉ avant la formation du FVG
            # Le FVG est formé à la bougie t (la 3ème), la bougie de displacement est t-1
            # On cherche avant t-1
            displacement_idx = fvg.index - 1

            found_ob_idx = None
            for k in range(1, self.max_lookback + 1):
                probe = displacement_idx - k
                if probe < 0:
                    break
                is_bull_candle = c[probe] > o[probe]
                is_bear_candle = c[probe] < o[probe]

                if fvg.side == Side.LONG and is_bear_candle:
                    found_ob_idx = probe
                    break
                if fvg.side == Side.SHORT and is_bull_candle:
                    found_ob_idx = probe
                    break

            if found_ob_idx is None:
                continue

            ob_side = fvg.side
            ob_high = float(h[found_ob_idx])
            ob_low = float(l[found_ob_idx])
            ob_open = float(o[found_ob_idx])
            ob_close = float(c[found_ob_idx])

            # Strength score : combo de taille OB / taille du move impulsif
            ob_range = ob_high - ob_low
            impulse = abs(c[fvg.index] - c[found_ob_idx])
            if atr[found_ob_idx] and ob_range > 0:
                strength = (impulse / atr[found_ob_idx]) * min(ob_range / atr[found_ob_idx], 2.0)
            else:
                strength = 0.0

            ob = OrderBlock(
                index=found_ob_idx,
                timestamp=idx[found_ob_idx].to_pydatetime(),
                side=ob_side,
                high=ob_high,
                low=ob_low,
                open=ob_open,
                close=ob_close,
                associated_fvg_index=fvg.index,
                is_valid=True,                      # ← validité garantie par FVG
                strength_score=float(strength),
            )
            out.append(ob)

        # Post-processing : mark tested/held
        self._check_tests(out, df)
        log.info(f"OB detect: {len(out)} valid OBs (FVG-backed)")
        return out

    def _check_tests(self, obs: List[OrderBlock], df: pd.DataFrame) -> None:
        for ob in obs:
            future = df.iloc[ob.index + 5 :]       # skip immediate action
            if future.empty:
                continue
            if ob.side == Side.LONG:
                # Test = price returns into OB zone
                tests = future[(future["low"] <= ob.high) & (future["low"] >= ob.low)]
                ob.tested = len(tests)
                if ob.tested > 0:
                    # held = après le 1er test, price reparte dans le sens de l'OB
                    first_test_idx = df.index.get_loc(tests.index[0])
                    post = df.iloc[first_test_idx : first_test_idx + 10]
                    ob.held = post["close"].max() > ob.high
            else:
                tests = future[(future["high"] >= ob.low) & (future["high"] <= ob.high)]
                ob.tested = len(tests)
                if ob.tested > 0:
                    first_test_idx = df.index.get_loc(tests.index[0])
                    post = df.iloc[first_test_idx : first_test_idx + 10]
                    ob.held = post["close"].min() < ob.low

    def to_dataframe(self, obs: List[OrderBlock]) -> pd.DataFrame:
        if not obs:
            return pd.DataFrame()
        return pd.DataFrame([vars(o) for o in obs])
