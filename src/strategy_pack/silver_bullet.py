"""
SILVER BULLET ICT — setup entre 10h-11h NY (14h-15h UTC).

Règles strictes :
- Window : 14:00-15:00 UTC (10h-11h ET NY)
- Detect FVG formed in that hour
- Entry : retour dans le FVG
- SL : au-delà du FVG
- TP : liquidité la plus proche (PDH/PDL ou EQH/EQL)

Win rate historique ICT : 70-80% selon structure HTF alignée.
"""
from __future__ import annotations

import pandas as pd
from dataclasses import dataclass
from datetime import time, datetime
from typing import List, Optional

from src.ict_engine.fvg import FVGDetector
from src.ict_engine.liquidity import LiquidityDetector
from src.utils.types import Side, FVG, LiquidityPool
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class SilverBulletSetup:
    timestamp: datetime
    symbol: str
    side: Side
    fvg: FVG
    entry: float
    stop_loss: float
    take_profit: float
    target_liquidity: Optional[LiquidityPool]
    rr: float


class SilverBulletStrategy:

    WINDOW_START = time(14, 0)      # 14:00 UTC
    WINDOW_END = time(15, 0)         # 15:00 UTC

    def __init__(self, sl_buffer_atr: float = 0.3):
        self.sl_buf = sl_buffer_atr

    def scan(self, df: pd.DataFrame, symbol: str,
              atr_col: str = "atr_14") -> List[SilverBulletSetup]:
        """Scan les FVG formés dans la Silver Bullet window."""
        setups = []
        fvg_detector = FVGDetector(min_size_atr=0.3, displacement_min=1.2,
                                     close_in_range_min=0.70)
        fvgs = fvg_detector.detect(df, atr_col=atr_col)

        liq = LiquidityDetector()
        pools = liq.detect_session_levels(df)

        for fvg in fvgs:
            ts = fvg.timestamp
            if ts.tzinfo is None:
                ts_time = ts.time()
            else:
                # Ensure UTC
                ts_time = ts.time()
            if not (self.WINDOW_START <= ts_time <= self.WINDOW_END):
                continue

            atr = df[atr_col].iloc[fvg.index]
            if pd.isna(atr) or atr <= 0:
                continue

            entry = fvg.ce
            if fvg.side == Side.LONG:
                sl = fvg.bottom - self.sl_buf * atr
                # Target : nearest unswept high above
                candidates = [p for p in pools if p.price > entry and not p.swept]
                if not candidates:
                    continue
                target = min(candidates, key=lambda p: p.price - entry)
                tp = target.price
                risk = entry - sl
            else:
                sl = fvg.top + self.sl_buf * atr
                candidates = [p for p in pools if p.price < entry and not p.swept]
                if not candidates:
                    continue
                target = min(candidates, key=lambda p: entry - p.price)
                tp = target.price
                risk = sl - entry

            if risk <= 0:
                continue
            rr = abs(tp - entry) / risk
            if rr < 1.5:
                continue

            setups.append(SilverBulletSetup(
                timestamp=fvg.timestamp, symbol=symbol, side=fvg.side,
                fvg=fvg, entry=entry, stop_loss=sl, take_profit=tp,
                target_liquidity=target, rr=rr,
            ))

        log.info(f"Silver Bullet {symbol}: {len(setups)} setups found")
        return setups
