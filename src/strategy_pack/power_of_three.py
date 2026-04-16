"""
POWER OF THREE (AMD) — Accumulation, Manipulation, Distribution.

Pattern ICT :
- Phase 1 (Accumulation) : price en range serré
- Phase 2 (Manipulation) : break d'un côté puis retour (sweep liquidité)
- Phase 3 (Distribution) : move propre dans la direction opposée

Setup : detect le sweep + confirmation structure break → entry.
"""
from __future__ import annotations

import pandas as pd
from dataclasses import dataclass
from datetime import datetime
from typing import List

from src.utils.types import Side
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class PO3Setup:
    timestamp: datetime
    symbol: str
    side: Side
    accumulation_high: float
    accumulation_low: float
    manipulation_sweep: float
    entry: float
    stop_loss: float
    take_profit: float
    rr: float


class PowerOfThreeStrategy:

    def __init__(self, accumulation_bars: int = 20, max_accumulation_atr: float = 1.5):
        self.acc_bars = accumulation_bars
        self.max_acc_atr = max_accumulation_atr

    def scan(self, df: pd.DataFrame, symbol: str,
              atr_col: str = "atr_14") -> List[PO3Setup]:
        setups = []

        for i in range(self.acc_bars + 2, len(df) - 2):
            acc_window = df.iloc[i - self.acc_bars : i]
            acc_high = acc_window["high"].max()
            acc_low = acc_window["low"].min()
            acc_range = acc_high - acc_low

            atr = df[atr_col].iloc[i]
            if pd.isna(atr) or atr <= 0:
                continue

            # Accumulation must be tight
            if acc_range > self.max_acc_atr * atr:
                continue

            # Next bar : manipulation (sweep + return)
            manip_bar = df.iloc[i]
            bar_high = manip_bar["high"]
            bar_low = manip_bar["low"]
            bar_close = manip_bar["close"]

            # Bearish PO3 : sweep high, then close below acc_high
            if bar_high > acc_high and bar_close < acc_high:
                side = Side.SHORT
                entry = acc_high
                sl = bar_high + 0.2 * atr
                tp = acc_low - acc_range
                risk = sl - entry
            # Bullish PO3 : sweep low, then close above acc_low
            elif bar_low < acc_low and bar_close > acc_low:
                side = Side.LONG
                entry = acc_low
                sl = bar_low - 0.2 * atr
                tp = acc_high + acc_range
                risk = entry - sl
            else:
                continue

            if risk <= 0:
                continue
            rr = abs(tp - entry) / risk
            if rr < 2.0:
                continue

            setups.append(PO3Setup(
                timestamp=df.index[i].to_pydatetime(),
                symbol=symbol, side=side,
                accumulation_high=acc_high, accumulation_low=acc_low,
                manipulation_sweep=bar_high if side == Side.SHORT else bar_low,
                entry=entry, stop_loss=sl, take_profit=tp, rr=rr,
            ))

        log.info(f"Power of Three {symbol}: {len(setups)} setups")
        return setups
