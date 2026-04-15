"""
Regime Detection Engine.

Méthodes combinées :
1. Hurst exponent : trending (>0.55), random walk (~0.5), mean-reverting (<0.45)
2. ADX : tendance forte (>25), faible (<20)
3. Volatility percentile : high/low vs historique
4. Range/ATR ratio : mesure la compression

Output : Regime + score [0,1] de stabilité.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional

from src.utils.types import Regime
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class RegimeState:
    regime: Regime
    hurst: float
    adx: float
    vol_percentile: float               # 0-1, where current vol sits in history
    stability: float                    # 0-1, how stable this regime is
    description: str


class RegimeDetector:

    def __init__(
        self,
        hurst_window: int = 100,
        vol_window: int = 100,
        vol_history_window: int = 500,
    ):
        self.hurst_window = hurst_window
        self.vol_window = vol_window
        self.vol_history_window = vol_history_window

    # ------------------------------------------------------------------
    def detect(self, df: pd.DataFrame) -> RegimeState:
        """
        Calcule le régime CURRENT à partir du DataFrame donné (dernières N bars).
        Utilise uniquement des données passées (causal).
        """
        if len(df) < max(self.hurst_window, self.vol_history_window):
            return RegimeState(
                regime=Regime.UNKNOWN, hurst=0.5, adx=0.0,
                vol_percentile=0.5, stability=0.0,
                description="insufficient_history",
            )

        close = df["close"]
        hurst = self._hurst_exponent(close.tail(self.hurst_window).values)
        adx = self._adx(df.tail(50))

        returns = close.pct_change().dropna()
        vol_now = returns.tail(self.vol_window).std()
        vol_hist = returns.tail(self.vol_history_window).rolling(self.vol_window).std().dropna()
        if len(vol_hist) > 10 and vol_hist.std() > 0:
            vol_pct = (vol_hist < vol_now).mean()
        else:
            vol_pct = 0.5

        regime = self._classify(hurst, adx, vol_pct)
        stability = self._stability(hurst, adx, vol_pct)
        desc = (
            f"H={hurst:.2f} ADX={adx:.1f} volPct={vol_pct:.2f} → {regime.value}"
        )
        return RegimeState(
            regime=regime, hurst=hurst, adx=adx,
            vol_percentile=vol_pct, stability=stability,
            description=desc,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _hurst_exponent(prices: np.ndarray) -> float:
        """
        Estimation Hurst par R/S analysis.
        - ~0.5 : random walk
        - >0.5 : trending (persistent)
        - <0.5 : mean-reverting (anti-persistent)
        """
        if len(prices) < 50:
            return 0.5
        ts = np.log(prices[prices > 0])
        if len(ts) < 20:
            return 0.5
        lags = range(2, min(20, len(ts) // 2))
        try:
            tau = [np.sqrt(np.std(np.subtract(ts[lag:], ts[:-lag]))) for lag in lags]
            tau = [t for t in tau if t > 0]
            lags = lags[: len(tau)]
            if len(tau) < 5:
                return 0.5
            poly = np.polyfit(np.log(list(lags)), np.log(tau), 1)
            hurst = poly[0] * 2
            return float(max(0.0, min(1.0, hurst)))
        except Exception:
            return 0.5

    @staticmethod
    def _adx(df: pd.DataFrame, period: int = 14) -> float:
        if len(df) < period * 2:
            return 0.0
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values
        tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)),
                                           np.abs(l - np.roll(c, 1))))
        tr[0] = h[0] - l[0]
        plus_dm = np.where((h - np.roll(h, 1)) > (np.roll(l, 1) - l),
                           np.maximum(h - np.roll(h, 1), 0), 0)
        minus_dm = np.where((np.roll(l, 1) - l) > (h - np.roll(h, 1)),
                            np.maximum(np.roll(l, 1) - l, 0), 0)
        atr = pd.Series(tr).rolling(period).mean()
        pdi = 100 * pd.Series(plus_dm).rolling(period).mean() / atr
        ndi = 100 * pd.Series(minus_dm).rolling(period).mean() / atr
        dx = 100 * np.abs(pdi - ndi) / (pdi + ndi).replace(0, np.nan)
        adx = dx.rolling(period).mean()
        last = adx.dropna()
        return float(last.iloc[-1]) if not last.empty else 0.0

    @staticmethod
    def _classify(hurst: float, adx: float, vol_pct: float) -> Regime:
        trending = hurst > 0.55 and adx > 22
        ranging = hurst < 0.5 or adx < 18
        high_vol = vol_pct > 0.70
        low_vol = vol_pct < 0.30
        manipulation = adx > 30 and vol_pct > 0.85   # très forte vol + tendance extrême

        if manipulation:
            return Regime.MANIPULATION
        if trending:
            return Regime.TRENDING_HIGH_VOL if high_vol else Regime.TRENDING_LOW_VOL
        if ranging:
            return Regime.RANGING_HIGH_VOL if high_vol else Regime.RANGING_LOW_VOL
        # default
        return Regime.RANGING_LOW_VOL if low_vol else Regime.UNKNOWN

    @staticmethod
    def _stability(hurst: float, adx: float, vol_pct: float) -> float:
        """Plus les signaux sont cohérents, plus le régime est stable."""
        # extremes stables, zones grises instables
        hurst_conf = abs(hurst - 0.5) * 2               # [0,1]
        adx_conf = min(adx / 40, 1.0)                    # 40+ = strong
        vol_conf = abs(vol_pct - 0.5) * 2                # extremes plus stables
        return float((hurst_conf + adx_conf + vol_conf) / 3)

    # ------------------------------------------------------------------
    def detect_series(self, df: pd.DataFrame, window: int = 200) -> pd.DataFrame:
        """
        Produit une série temporelle de régimes (calcul causal glissant).
        Utile pour analyser la performance par régime.
        """
        results = []
        idx_out = []
        for i in range(window, len(df), 5):             # step de 5 pour perf
            sub = df.iloc[: i]
            state = self.detect(sub)
            results.append({
                "regime": state.regime.value,
                "hurst": state.hurst,
                "adx": state.adx,
                "vol_pct": state.vol_percentile,
                "stability": state.stability,
            })
            idx_out.append(df.index[i])
        return pd.DataFrame(results, index=pd.DatetimeIndex(idx_out))
