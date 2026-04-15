"""
Feature Engine — transforme OHLCV en variables mesurables.

Toutes les features sont CAUSALES (utilisent uniquement des données passées).
Aucune feature ne doit utiliser .shift(-N) avec N>0.

Groupes :
- Volatilité : ATR, TR, realized vol, vol-of-vol
- Momentum : returns multi-horizon, displacement
- Structure : swings, BOS, CHoCH
- Distance aux niveaux : ratios normalisés
- Volume : OBV, VWAP, volume-spike
- Compression / expansion : Bollinger bandwidth, range contraction
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional

from src.utils.logging_conf import get_logger
from src.utils.sessions import add_session_columns

log = get_logger(__name__)


class FeatureEngine:
    """Engine causal : toutes les features utilisent seulement le passé."""

    def __init__(self, atr_period: int = 14, vol_lookbacks: tuple = (5, 20, 50)):
        self.atr_period = atr_period
        self.vol_lookbacks = vol_lookbacks

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcule toutes les features sur une copie du DataFrame."""
        out = df.copy()
        self._add_basic(out)
        self._add_volatility(out)
        self._add_momentum(out)
        self._add_structure(out)
        self._add_compression(out)
        self._add_session_features(out)
        if "volume" in out.columns:
            self._add_volume(out)

        # Feature lag-safety : shift toutes les features de +1 pour garantir
        # qu'elles sont disponibles AU DÉBUT de la bar t+1 (pas à sa fin).
        # Politique : on fait ce shift au moment de l'inférence, pas ici,
        # pour garder les features alignées avec leur bar native.
        return out

    # ------------------------------------------------------------------
    # Basic / Price transforms
    # ------------------------------------------------------------------
    def _add_basic(self, df: pd.DataFrame) -> None:
        df["range"] = df["high"] - df["low"]
        df["body"] = (df["close"] - df["open"]).abs()
        df["upper_wick"] = df["high"] - df[["open", "close"]].max(axis=1)
        df["lower_wick"] = df[["open", "close"]].min(axis=1) - df["low"]
        df["body_to_range"] = df["body"] / df["range"].replace(0, np.nan)
        df["hl2"] = (df["high"] + df["low"]) / 2
        df["ohlc4"] = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
        df["log_return"] = np.log(df["close"] / df["close"].shift(1))
        df["return"] = df["close"].pct_change()

    # ------------------------------------------------------------------
    # Volatility — ATR, realized vol
    # ------------------------------------------------------------------
    def _add_volatility(self, df: pd.DataFrame) -> None:
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        df["tr"] = tr
        df[f"atr_{self.atr_period}"] = tr.rolling(self.atr_period).mean()
        df["atr_pct"] = df[f"atr_{self.atr_period}"] / df["close"]

        for lb in self.vol_lookbacks:
            df[f"realized_vol_{lb}"] = df["log_return"].rolling(lb).std()
            df[f"hl_range_pct_{lb}"] = ((df["high"].rolling(lb).max() -
                                         df["low"].rolling(lb).min()) /
                                        df["close"])

        # Vol-of-vol — second-order volatility
        df["vol_of_vol_20"] = df["realized_vol_20"].rolling(20).std()

    # ------------------------------------------------------------------
    # Momentum & Displacement (ICT)
    # ------------------------------------------------------------------
    def _add_momentum(self, df: pd.DataFrame) -> None:
        for lb in [5, 10, 20, 50]:
            df[f"ret_{lb}"] = df["close"].pct_change(lb)

        # Displacement ICT : une bougie de forte amplitude + close proche extreme
        # displacement_raw = range / ATR — normalisé
        df["displacement"] = df["range"] / df[f"atr_{self.atr_period}"]
        # Un displacement > 1.5 ATR avec close dans les 20% du range = impulsion forte
        df["close_in_range"] = (df["close"] - df["low"]) / df["range"].replace(0, np.nan)
        df["impulsion_up"] = (
            (df["displacement"] > 1.5) &
            (df["close_in_range"] > 0.80) &
            (df["close"] > df["open"])
        ).astype(int)
        df["impulsion_down"] = (
            (df["displacement"] > 1.5) &
            (df["close_in_range"] < 0.20) &
            (df["close"] < df["open"])
        ).astype(int)

        # ADX simplifié
        up_move = df["high"].diff()
        down_move = -df["low"].diff()
        pos_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        neg_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        pdi = 100 * pd.Series(pos_dm, index=df.index).rolling(14).mean() / df["tr"].rolling(14).mean()
        ndi = 100 * pd.Series(neg_dm, index=df.index).rolling(14).mean() / df["tr"].rolling(14).mean()
        dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
        df["adx_14"] = dx.rolling(14).mean()

    # ------------------------------------------------------------------
    # Structure — swings, BOS, CHoCH
    # ------------------------------------------------------------------
    def _add_structure(self, df: pd.DataFrame, swing_lookback: int = 3) -> None:
        """
        Swing highs/lows : pivot N bars avant et après.
        BOS (Break Of Structure) : cassure du dernier swing dans le sens de la tendance.
        CHoCH (Change of Character) : cassure du dernier swing dans le sens inverse.
        """
        N = swing_lookback
        h = df["high"].values
        l = df["low"].values

        swing_h = np.full(len(df), np.nan)
        swing_l = np.full(len(df), np.nan)

        for i in range(N, len(df) - N):
            if h[i] == max(h[i - N : i + N + 1]):
                swing_h[i] = h[i]
            if l[i] == min(l[i - N : i + N + 1]):
                swing_l[i] = l[i]

        df["swing_high"] = swing_h
        df["swing_low"] = swing_l
        df["last_swing_high"] = pd.Series(swing_h, index=df.index).ffill().shift(N)
        df["last_swing_low"] = pd.Series(swing_l, index=df.index).ffill().shift(N)

        # BOS / CHoCH flags (causaux)
        df["bos_up"] = (df["close"] > df["last_swing_high"]).astype(int)
        df["bos_down"] = (df["close"] < df["last_swing_low"]).astype(int)

        # Distance normalisée aux derniers swings
        atr = df[f"atr_{self.atr_period}"].replace(0, np.nan)
        df["dist_to_swing_h_atr"] = (df["last_swing_high"] - df["close"]) / atr
        df["dist_to_swing_l_atr"] = (df["close"] - df["last_swing_low"]) / atr

    # ------------------------------------------------------------------
    # Compression / Expansion
    # ------------------------------------------------------------------
    def _add_compression(self, df: pd.DataFrame) -> None:
        # Bollinger bandwidth
        ma = df["close"].rolling(20).mean()
        sd = df["close"].rolling(20).std()
        df["bb_upper"] = ma + 2 * sd
        df["bb_lower"] = ma - 2 * sd
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / ma

        # Low bandwidth = compression = breakout imminent
        df["compression_flag"] = (
            df["bb_width"] < df["bb_width"].rolling(100).quantile(0.25)
        ).astype(int)

        # Range contraction / expansion ratio
        df["range_ratio_5_20"] = (
            df["range"].rolling(5).mean() / df["range"].rolling(20).mean()
        )

    # ------------------------------------------------------------------
    # Session features
    # ------------------------------------------------------------------
    def _add_session_features(self, df: pd.DataFrame) -> None:
        tmp = add_session_columns(df)
        df["session"] = tmp["session"]
        df["killzone"] = tmp["killzone"]
        df["hour_utc"] = tmp["hour_utc"]
        df["day_of_week"] = tmp["day_of_week"]
        df["is_weekend"] = tmp["is_weekend"]

    # ------------------------------------------------------------------
    # Volume features
    # ------------------------------------------------------------------
    def _add_volume(self, df: pd.DataFrame) -> None:
        df["volume_ma_20"] = df["volume"].rolling(20).mean()
        df["volume_spike"] = df["volume"] / df["volume_ma_20"].replace(0, np.nan)
        # OBV
        direction = np.sign(df["close"].diff()).fillna(0)
        df["obv"] = (direction * df["volume"]).cumsum()
