"""
FVG Detector — Fair Value Gap ICT formalisé.

DÉFINITION STRICTE (ICT) :
- Bullish FVG : Low[t] > High[t-2]  ← gap "manqué" entre bougie 1 et 3
- Bearish FVG : High[t] < Low[t-2]
- REQUIS : la bougie du milieu (t-1) doit montrer du DISPLACEMENT
  (range > 1.2 × ATR, close près de l'extrême)
- CE (Consequent Encroachment) = midpoint

QUALITY SCORE :
- taille en ATR (plus grand = plus significatif)
- impulsion de la bougie du milieu
- volume spike (si dispo)
- alignement avec structure HTF

CLASSIFICATION IRL/ERL :
- IRL (Internal Range Liquidity) : FVG dans un range interne
- ERL (External Range Liquidity) : FVG aux extrêmes d'un swing
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import List

from src.utils.types import FVG, Side
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


class FVGDetector:
    """
    Détecteur de FVG causal : chaque FVG est identifié UNIQUEMENT à la clôture
    de la bougie t (la 3ème), jamais avant.
    """

    def __init__(
        self,
        min_size_atr: float = 0.25,         # FVG doit faire au moins 0.25 ATR
        displacement_min: float = 1.2,      # bougie du milieu > 1.2 ATR
        close_in_range_min: float = 0.70,   # close ≥ 70% du range dans sens impulsion
        require_body_alignment: bool = True,
    ):
        self.min_size_atr = min_size_atr
        self.displacement_min = displacement_min
        self.close_in_range_min = close_in_range_min
        self.require_body_alignment = require_body_alignment

    def detect(self, df: pd.DataFrame, atr_col: str = "atr_14") -> List[FVG]:
        """
        Détecte tous les FVG du DataFrame. Retourne une liste chronologique.
        Nécessite : open/high/low/close + atr_14 (ou équivalent).
        """
        if atr_col not in df.columns:
            raise ValueError(f"ATR column '{atr_col}' missing. Run FeatureEngine first.")

        out: List[FVG] = []
        h = df["high"].values
        l = df["low"].values
        o = df["open"].values
        c = df["close"].values
        atr = df[atr_col].values
        idx = df.index

        for t in range(2, len(df)):
            if np.isnan(atr[t]) or atr[t] == 0:
                continue

            # Bougie du milieu (t-1)
            mid_range = h[t - 1] - l[t - 1]
            mid_body = abs(c[t - 1] - o[t - 1])
            displacement = mid_range / atr[t - 1] if atr[t - 1] else 0

            if displacement < self.displacement_min:
                continue

            close_in_range = (c[t - 1] - l[t - 1]) / mid_range if mid_range else 0.5

            # --- Bullish FVG : Low[t] > High[t-2]
            if l[t] > h[t - 2]:
                if self.require_body_alignment:
                    if close_in_range < self.close_in_range_min:
                        continue
                    if c[t - 1] <= o[t - 1]:                # bougie milieu doit être bull
                        continue

                gap_top = l[t]
                gap_bottom = h[t - 2]
                size = gap_top - gap_bottom
                size_atr = size / atr[t]

                if size_atr < self.min_size_atr:
                    continue

                impulsion_score = displacement * close_in_range * (mid_body / mid_range if mid_range else 0)

                fvg = FVG(
                    index=t,
                    timestamp=idx[t].to_pydatetime(),
                    side=Side.LONG,
                    top=float(gap_top),
                    bottom=float(gap_bottom),
                    size=float(size),
                    size_in_atr=float(size_atr),
                    displacement=float(displacement),
                    impulsion_score=float(impulsion_score),
                    ce=float((gap_top + gap_bottom) / 2),
                    volume_at_formation=float(df["volume"].iloc[t - 1]) if "volume" in df.columns else 0.0,
                )
                out.append(fvg)

            # --- Bearish FVG : High[t] < Low[t-2]
            elif h[t] < l[t - 2]:
                if self.require_body_alignment:
                    if (1 - close_in_range) < self.close_in_range_min:
                        continue
                    if c[t - 1] >= o[t - 1]:                # bougie milieu doit être bear
                        continue

                gap_top = l[t - 2]
                gap_bottom = h[t]
                size = gap_top - gap_bottom
                size_atr = size / atr[t]

                if size_atr < self.min_size_atr:
                    continue

                impulsion_score = displacement * (1 - close_in_range) * (mid_body / mid_range if mid_range else 0)

                fvg = FVG(
                    index=t,
                    timestamp=idx[t].to_pydatetime(),
                    side=Side.SHORT,
                    top=float(gap_top),
                    bottom=float(gap_bottom),
                    size=float(size),
                    size_in_atr=float(size_atr),
                    displacement=float(displacement),
                    impulsion_score=float(impulsion_score),
                    ce=float((gap_top + gap_bottom) / 2),
                    volume_at_formation=float(df["volume"].iloc[t - 1]) if "volume" in df.columns else 0.0,
                )
                out.append(fvg)

        # Post-processing : mark filled FVGs + IRL/ERL
        self._mark_fills(out, df)
        self._classify_irl_erl(out, df)

        log.info(f"FVG detect: {len(out)} FVGs found in {len(df)} bars")
        return out

    def _mark_fills(self, fvgs: List[FVG], df: pd.DataFrame) -> None:
        """Pour chaque FVG, détecte quand/si il a été comblé (prix passe CE)."""
        for fvg in fvgs:
            future = df.iloc[fvg.index + 1 :]
            if future.empty:
                continue
            if fvg.side == Side.LONG:
                # rempli quand low ≤ CE
                hits = future[future["low"] <= fvg.ce]
            else:
                hits = future[future["high"] >= fvg.ce]
            if not hits.empty:
                fvg.filled = True
                fvg.filled_at_index = int(df.index.get_loc(hits.index[0]))

    def _classify_irl_erl(self, fvgs: List[FVG], df: pd.DataFrame,
                          lookback: int = 50) -> None:
        """
        IRL/ERL : FVG à l'intérieur du range [swing_low, swing_high] → IRL
                  FVG au-delà d'un swing → ERL
        """
        for fvg in fvgs:
            window_start = max(0, fvg.index - lookback)
            window = df.iloc[window_start : fvg.index]
            if window.empty:
                continue
            hi = window["high"].max()
            lo = window["low"].min()
            if fvg.top <= hi and fvg.bottom >= lo:
                fvg.irl_erl = "IRL"
            else:
                fvg.irl_erl = "ERL"

    def to_dataframe(self, fvgs: List[FVG]) -> pd.DataFrame:
        if not fvgs:
            return pd.DataFrame()
        return pd.DataFrame([vars(f) for f in fvgs])
