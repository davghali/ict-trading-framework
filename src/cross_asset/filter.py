"""
CROSS-ASSET FILTER — confirme un signal avec la corrélation inter-marchés.

Règles ICT/Wyckoff :
- XAUUSD LONG  → DXY doit baisser (inverse correlation)
- XAUUSD SHORT → DXY doit monter
- NAS100 LONG  → SPX aligné + VIX BAS (risk-on)
- NAS100 SHORT → SPX aligné + VIX HAUT (risk-off)
- EURUSD LONG  → DXY baisse
- GBPUSD LONG  → DXY baisse + EURUSD aligné
- USDJPY LONG  → DXY monte
- BTCUSD LONG  → NAS100 aligné (risk-on) + ETH aligné
- ETHUSD LONG  → BTC aligné + NAS aligné

Retourne un score de confirmation 0-1 qui filtre les signaux.
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional, Dict, List
from datetime import timedelta

from src.data_engine import DataLoader
from src.data_engine.downloader import download_asset
from src.utils.types import Timeframe, Side
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


# Tickers Yahoo pour les références macro
MACRO_TICKERS = {
    "DXY": "DX-Y.NYB",      # Dollar Index (correct Yahoo ticker)
    "SPX": "^GSPC",         # S&P 500
    "VIX": "^VIX",          # Volatility Index
    "US10Y": "^TNX",        # 10Y Treasury Yield
}

# Corrélations attendues par asset
# Format : {asset: {"long": [(ref_asset, direction_required), ...], "short": [...]}}
CORRELATION_RULES = {
    "XAUUSD": {
        "long":  [("DXY", "down"), ("US10Y", "down")],
        "short": [("DXY", "up"),   ("US10Y", "up")],
    },
    "XAGUSD": {
        "long":  [("DXY", "down"), ("XAUUSD", "up")],
        "short": [("DXY", "up"),   ("XAUUSD", "down")],
    },
    "EURUSD": {
        "long":  [("DXY", "down")],
        "short": [("DXY", "up")],
    },
    "GBPUSD": {
        "long":  [("DXY", "down"), ("EURUSD", "up")],
        "short": [("DXY", "up"),   ("EURUSD", "down")],
    },
    "USDJPY": {
        "long":  [("DXY", "up"),   ("US10Y", "up")],
        "short": [("DXY", "down"), ("US10Y", "down")],
    },
    "AUDUSD": {
        "long":  [("DXY", "down"), ("SPX", "up")],          # risk-on
        "short": [("DXY", "up"),   ("SPX", "down")],
    },
    "USDCAD": {
        "long":  [("DXY", "up")],
        "short": [("DXY", "down")],
    },
    "NAS100": {
        "long":  [("SPX", "up"),   ("VIX", "down")],
        "short": [("SPX", "down"), ("VIX", "up")],
    },
    "SPX500": {
        "long":  [("NAS100", "up"),  ("VIX", "down")],
        "short": [("NAS100", "down"), ("VIX", "up")],
    },
    "DOW30": {
        "long":  [("SPX", "up"),   ("VIX", "down")],
        "short": [("SPX", "down"), ("VIX", "up")],
    },
    "BTCUSD": {
        "long":  [("NAS100", "up"),  ("SPX", "up")],        # risk-on correlation
        "short": [("NAS100", "down"), ("SPX", "down")],
    },
    "ETHUSD": {
        "long":  [("BTCUSD", "up"),  ("NAS100", "up")],
        "short": [("BTCUSD", "down"), ("NAS100", "down")],
    },
}


@dataclass
class CorrelationCheck:
    """Résultat d'une vérification cross-asset."""
    asset: str
    side: str
    confirmations: List[str]       # ex: ["DXY down ✓", "US10Y down ✓"]
    failures: List[str]             # ex: ["SPX up required, got down"]
    score: float                    # 0-1 (fraction des confirmations)
    passed: bool                    # score >= threshold


class CrossAssetFilter:

    def __init__(self, min_score: float = 0.5, lookback_bars: int = 20):
        """
        min_score : % minimum de confirmations (0.5 = 50%)
        lookback_bars : combien de bars pour mesurer la direction
        """
        self.min_score = min_score
        self.lookback_bars = lookback_bars
        self.loader = DataLoader()

    # ------------------------------------------------------------------
    def _get_direction(self, ticker: str, timeframe: Timeframe = Timeframe.H1) -> Optional[str]:
        """Retourne 'up', 'down' ou None selon la direction récente."""
        try:
            # Essaye de load depuis DataLoader (si l'asset est dans le framework)
            df = None
            try:
                df = self.loader.load(ticker, timeframe)
            except FileNotFoundError:
                # Macro ticker — download on-demand
                yf_symbol = MACRO_TICKERS.get(ticker)
                if yf_symbol is None:
                    return None
                # Use yfinance direct (since not in config)
                import yfinance as yf
                df = yf.download(yf_symbol, period="7d", interval="1h",
                                  progress=False, auto_adjust=False, threads=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                df.columns = [str(c).lower() for c in df.columns]

            if df is None or len(df) < self.lookback_bars + 2:
                return None

            last_close = df["close"].iloc[-1]
            prior_close = df["close"].iloc[-self.lookback_bars - 1]
            pct = (last_close - prior_close) / prior_close
            if pct > 0.001:        # > 0.1% up
                return "up"
            elif pct < -0.001:
                return "down"
            else:
                return "flat"
        except Exception as e:
            log.debug(f"Direction check failed for {ticker}: {e}")
            return None

    # ------------------------------------------------------------------
    def check(self, asset: str, side: Side) -> CorrelationCheck:
        side_key = "long" if side == Side.LONG else "short"
        rules = CORRELATION_RULES.get(asset)
        if not rules:
            # Pas de règle → auto-pass
            return CorrelationCheck(
                asset=asset, side=side_key,
                confirmations=["no rules defined"],
                failures=[], score=1.0, passed=True,
            )

        required = rules.get(side_key, [])
        confirmations = []
        failures = []

        for ref_asset, req_direction in required:
            actual = self._get_direction(ref_asset)
            if actual is None:
                failures.append(f"{ref_asset} direction unavailable")
                continue
            if actual == req_direction:
                confirmations.append(f"{ref_asset} {req_direction} ✓")
            elif actual == "flat":
                # Neutral — partial credit
                confirmations.append(f"{ref_asset} flat (neutral)")
            else:
                failures.append(f"{ref_asset} should be {req_direction}, got {actual}")

        total = len(required)
        if total == 0:
            score = 1.0
        else:
            score = len(confirmations) / total

        return CorrelationCheck(
            asset=asset, side=side_key,
            confirmations=confirmations,
            failures=failures,
            score=score,
            passed=score >= self.min_score,
        )
