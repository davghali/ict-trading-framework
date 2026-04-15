"""
Breaker Block Detector + IFVG.

DÉFINITIONS ICT :
- Breaker Block : un ancien OB qui a été VIOLÉ (price a cassé l'autre côté),
  puis prix revient tester la zone dans le SENS INVERSE.
  Ex: OB bullish à 1.2000-1.2020. Price casse en dessous de 1.2000.
  Price revient à 1.2000-1.2020 → devient un BB bearish.

- IFVG (Inversed Fair Value Gap) : un FVG qui a été complètement traversé,
  puis prix revient tester. C'est un "anti-FVG" : la zone agit maintenant
  en résistance/support inversé.

Règle : un BB valide doit s'accompagner d'un IFVG dans le sens du retest.
"""
from __future__ import annotations

import pandas as pd
from typing import List

from src.utils.types import OrderBlock, BreakerBlock, FVG, Side
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


class BreakerBlockDetector:

    def __init__(self, max_forward_bars: int = 200):
        self.max_forward_bars = max_forward_bars

    def detect(self, df: pd.DataFrame, obs: List[OrderBlock], fvgs: List[FVG]) -> List[BreakerBlock]:
        out: List[BreakerBlock] = []
        h = df["high"].values
        l = df["low"].values
        idx = df.index

        for ob in obs:
            end = min(ob.index + self.max_forward_bars, len(df) - 1)

            if ob.side == Side.LONG:
                # Chercher un close SOUS ob.low après formation → OB violé
                for j in range(ob.index + 1, end + 1):
                    if l[j] < ob.low:
                        # OB violé. Maintenant cherche un retest vers le haut.
                        for k in range(j + 1, end + 1):
                            if h[k] >= ob.low and h[k] <= ob.high:
                                # retest dans la zone ex-OB → BB bearish
                                ifvg = self._find_matching_ifvg(fvgs, k, Side.SHORT)
                                bb = BreakerBlock(
                                    origin_ob_index=ob.index,
                                    index=k,
                                    timestamp=idx[k].to_pydatetime(),
                                    side=Side.SHORT,
                                    high=ob.high,
                                    low=ob.low,
                                    associated_ifvg_index=ifvg.index if ifvg else None,
                                    is_valid=ifvg is not None,
                                )
                                out.append(bb)
                                break
                        break
            else:  # SHORT OB
                for j in range(ob.index + 1, end + 1):
                    if h[j] > ob.high:
                        for k in range(j + 1, end + 1):
                            if l[k] <= ob.high and l[k] >= ob.low:
                                ifvg = self._find_matching_ifvg(fvgs, k, Side.LONG)
                                bb = BreakerBlock(
                                    origin_ob_index=ob.index,
                                    index=k,
                                    timestamp=idx[k].to_pydatetime(),
                                    side=Side.LONG,
                                    high=ob.high,
                                    low=ob.low,
                                    associated_ifvg_index=ifvg.index if ifvg else None,
                                    is_valid=ifvg is not None,
                                )
                                out.append(bb)
                                break
                        break

        valid = [b for b in out if b.is_valid]
        log.info(f"BB detect: {len(valid)} valid BBs (with IFVG) / {len(out)} total")
        return valid

    def _find_matching_ifvg(self, fvgs: List[FVG], around_index: int,
                            side: Side, window: int = 5) -> FVG | None:
        """Trouve un FVG formé autour du retest, dans le sens attendu."""
        for f in fvgs:
            if f.side != side:
                continue
            if abs(f.index - around_index) <= window:
                return f
        return None

    def to_dataframe(self, bbs: List[BreakerBlock]) -> pd.DataFrame:
        if not bbs:
            return pd.DataFrame()
        return pd.DataFrame([vars(b) for b in bbs])
