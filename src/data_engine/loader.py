"""
Data Loader — lecture parquet avec cache mémoire + vérifications auto.
"""
from __future__ import annotations

import pandas as pd
from functools import lru_cache
from typing import Optional

from src.utils.config import RAW_DIR, PROCESSED_DIR
from src.utils.logging_conf import get_logger
from src.utils.types import Timeframe

log = get_logger(__name__)


class DataLoader:
    """Accès unifié aux données — load once, use many."""

    def __init__(self, use_processed: bool = False):
        self._dir = PROCESSED_DIR if use_processed else RAW_DIR

    @lru_cache(maxsize=64)
    def load(self, symbol: str, timeframe: Timeframe) -> pd.DataFrame:
        path = self._dir / f"{symbol}_{timeframe.value}.parquet"
        if not path.exists():
            raise FileNotFoundError(
                f"Data not found: {path}. Run downloader first."
            )
        df = pd.read_parquet(path)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df = self._auto_repair(df, symbol, timeframe)
        log.debug(f"Loaded {symbol} {timeframe.value}: {len(df)} bars")
        return df

    @staticmethod
    def _auto_repair(df: pd.DataFrame, symbol: str, tf: Timeframe) -> pd.DataFrame:
        """
        Corrige les anomalies OHLC courantes de yfinance :
        - high < max(open, close) → force high = max(open, close)
        - low > min(open, close) → force low = min(open, close)
        - NaN → drop ligne
        Garantit que les data sortantes sont cohérentes pour tout downstream.
        """
        before = len(df)
        cols = [c for c in ["open", "high", "low", "close"] if c in df.columns]
        if set(cols) != {"open", "high", "low", "close"}:
            return df
        # Drop NaN
        df = df.dropna(subset=cols)
        # Repair high
        df["high"] = df[["high", "open", "close"]].max(axis=1)
        # Repair low
        df["low"] = df[["low", "open", "close"]].min(axis=1)
        # Drop non-positive prices
        df = df[(df[cols] > 0).all(axis=1)]
        after = len(df)
        if before != after:
            log.warning(f"{symbol} {tf.value}: auto-repaired {before - after} bar(s)")
        return df

    def load_range(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: Optional[pd.Timestamp] = None,
        end: Optional[pd.Timestamp] = None,
    ) -> pd.DataFrame:
        df = self.load(symbol, timeframe)
        def _utc(x):
            ts = pd.Timestamp(x)
            return ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")
        if start is not None:
            df = df[df.index >= _utc(start)]
        if end is not None:
            df = df[df.index < _utc(end)]
        return df.copy()

    def load_multi_tf(
        self, symbol: str, tfs: list[Timeframe]
    ) -> dict[str, pd.DataFrame]:
        return {tf.value: self.load(symbol, tf) for tf in tfs}

    def available_symbols(self) -> list[str]:
        return sorted({p.stem.split("_")[0] for p in self._dir.glob("*.parquet")})

    def available_tfs(self, symbol: str) -> list[str]:
        prefix = f"{symbol}_"
        return sorted(
            p.stem.replace(prefix, "")
            for p in self._dir.glob(f"{prefix}*.parquet")
        )
