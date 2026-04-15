"""
SMT (Smart Money Technique) Divergence Detector.

PRINCIPE :
Deux actifs corrélés divergent à une extremité de swing.
Ex : SP500 fait un HH mais NAS100 fait un LH → divergence bearish SMT.

Cas d'usage ICT :
- EURUSD vs DXY (doit toujours diverger — sont inversement corrélés)
  → si EURUSD fait HH et DXY fait aussi LL, tout est OK
  → si EURUSD fait HH et DXY fait HH, divergence manipulation
- NAS100 vs SPX500 (positivement corrélé)
  → NAS100 HH mais SPX500 LH = faiblesse, possible retournement

Le détecteur travaille sur DEUX séries alignées temporellement.
"""
from __future__ import annotations

import pandas as pd
from dataclasses import dataclass
from datetime import datetime
from typing import List

from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class SMTDivergence:
    timestamp: datetime
    asset_a: str
    asset_b: str
    type: str                           # "bullish_smt" | "bearish_smt"
    price_a: float
    price_b: float
    description: str


class SMTDetector:
    """
    Compare deux DataFrames alignés (même index) et détecte les divergences
    aux swings. Supporte corrélation positive et négative.
    """

    def __init__(self, swing_lookback: int = 5):
        self.N = swing_lookback

    def detect(
        self,
        df_a: pd.DataFrame,
        df_b: pd.DataFrame,
        name_a: str,
        name_b: str,
        correlation: str = "positive",   # "positive" | "negative"
    ) -> List[SMTDivergence]:
        """
        Aligne les deux séries (intersection d'index) puis compare les swings.
        """
        common = df_a.index.intersection(df_b.index)
        a = df_a.loc[common]
        b = df_b.loc[common]

        swings_a = self._swings(a)
        swings_b = self._swings(b)

        divergences: List[SMTDivergence] = []

        # Parcours des swings highs de A, cherche un swing high de B dans une fenêtre
        window = pd.Timedelta(hours=12)

        for t_a, (h_a, type_a) in swings_a.items():
            if type_a != "high":
                continue
            # Chercher un swing high de B proche temporellement
            close_b = {t: (p, tp) for t, (p, tp) in swings_b.items()
                       if tp == "high" and abs(t - t_a) <= window}
            if not close_b:
                continue
            # Par rapport au swing précédent
            prev_high_a = self._prev_swing(swings_a, t_a, "high")
            if prev_high_a is None:
                continue
            prev_high_b_val, _ = close_b.get(
                max(close_b.keys()),
                (None, None),
            )
            t_b = max(close_b.keys())
            prev_high_b = self._prev_swing(swings_b, t_b, "high")
            if prev_high_b is None:
                continue

            a_made_hh = h_a > prev_high_a[0]
            b_made_hh = close_b[t_b][0] > prev_high_b[0]

            is_divergent = False
            if correlation == "positive":
                is_divergent = a_made_hh != b_made_hh
            else:  # negative correlation
                is_divergent = a_made_hh == b_made_hh

            if is_divergent:
                divergences.append(SMTDivergence(
                    timestamp=t_a.to_pydatetime(),
                    asset_a=name_a,
                    asset_b=name_b,
                    type="bearish_smt",
                    price_a=float(h_a),
                    price_b=float(close_b[t_b][0]),
                    description=(
                        f"{name_a} {'HH' if a_made_hh else 'LH'} vs "
                        f"{name_b} {'HH' if b_made_hh else 'LH'} "
                        f"({correlation} correlation expected)"
                    ),
                ))

        # Même logique pour les lows (bullish SMT)
        for t_a, (l_a, type_a) in swings_a.items():
            if type_a != "low":
                continue
            close_b = {t: (p, tp) for t, (p, tp) in swings_b.items()
                       if tp == "low" and abs(t - t_a) <= window}
            if not close_b:
                continue
            prev_low_a = self._prev_swing(swings_a, t_a, "low")
            if prev_low_a is None:
                continue
            t_b = max(close_b.keys())
            prev_low_b = self._prev_swing(swings_b, t_b, "low")
            if prev_low_b is None:
                continue

            a_made_ll = l_a < prev_low_a[0]
            b_made_ll = close_b[t_b][0] < prev_low_b[0]

            is_divergent = False
            if correlation == "positive":
                is_divergent = a_made_ll != b_made_ll
            else:
                is_divergent = a_made_ll == b_made_ll

            if is_divergent:
                divergences.append(SMTDivergence(
                    timestamp=t_a.to_pydatetime(),
                    asset_a=name_a,
                    asset_b=name_b,
                    type="bullish_smt",
                    price_a=float(l_a),
                    price_b=float(close_b[t_b][0]),
                    description=(
                        f"{name_a} {'LL' if a_made_ll else 'HL'} vs "
                        f"{name_b} {'LL' if b_made_ll else 'HL'}"
                    ),
                ))

        log.info(f"SMT: {len(divergences)} divergences {name_a}/{name_b}")
        return divergences

    # ------------------------------------------------------------------
    def _swings(self, df: pd.DataFrame) -> dict:
        """Retourne {timestamp: (price, 'high'|'low')}."""
        N = self.N
        swings = {}
        h = df["high"].values
        l = df["low"].values
        idx = df.index
        for i in range(N, len(df) - N):
            if h[i] == max(h[i - N : i + N + 1]):
                swings[idx[i]] = (float(h[i]), "high")
            if l[i] == min(l[i - N : i + N + 1]):
                swings[idx[i]] = (float(l[i]), "low")
        return swings

    @staticmethod
    def _prev_swing(swings: dict, ts, kind: str):
        prev = [(t, v) for t, (v, k) in swings.items() if k == kind and t < ts]
        if not prev:
            return None
        t_prev = max(p[0] for p in prev)
        return (swings[t_prev][0], t_prev)
