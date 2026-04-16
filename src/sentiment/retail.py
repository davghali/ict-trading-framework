"""
RETAIL SENTIMENT — contrarian indicator.

Principe : quand retail est MASSIVEMENT long un asset (ex: 80% long EURUSD),
les institutionnels vendent à ce retail → price chute souvent.

Source : Myfxbook sentiment page (scrape simple) ou Oanda/IG données publiques.

Usage ICT : si retail ≥ 75% long un asset, considérer SHORT (contrarian).
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from src.utils.logging_conf import get_logger

log = get_logger(__name__)

CACHE_FILE = Path(__file__).parents[2] / "user_data" / "retail_sentiment_cache.json"
CACHE_TTL_HOURS = 4


@dataclass
class SentimentReading:
    asset: str
    timestamp: str
    long_pct: float
    short_pct: float
    total_positions: int = 0
    long_lots: float = 0.0
    short_lots: float = 0.0


class RetailSentimentFetcher:

    def __init__(self):
        self._cache: Dict[str, SentimentReading] = {}

    def refresh(self) -> bool:
        """Refresh sentiment cache (scrape Myfxbook if possible)."""
        if CACHE_FILE.exists():
            age_h = (datetime.utcnow().timestamp() - CACHE_FILE.stat().st_mtime) / 3600
            if age_h < CACHE_TTL_HOURS:
                self._load_cache()
                return True

        # Placeholder : load cached data
        # In production : scrape https://www.myfxbook.com/community/outlook
        self._load_cache()
        return True

    def _load_cache(self) -> None:
        if CACHE_FILE.exists():
            try:
                data = json.loads(CACHE_FILE.read_text())
                for asset, rep in data.items():
                    self._cache[asset] = SentimentReading(**rep)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def get(self, asset: str) -> Optional[SentimentReading]:
        return self._cache.get(asset)

    def is_retail_extreme(self, asset: str, threshold: float = 0.70) -> str:
        """
        Retourne 'contrarian_short', 'contrarian_long', ou 'neutral'.
        - Si retail ≥ 70% long → contrarian SHORT
        - Si retail ≥ 70% short → contrarian LONG
        """
        s = self.get(asset)
        if not s:
            return "neutral"
        if s.long_pct >= threshold:
            return "contrarian_short"
        if s.short_pct >= threshold:
            return "contrarian_long"
        return "neutral"

    def filter_signal(self, asset: str, side: str) -> bool:
        """
        Retourne True si le signal est OK vs retail sentiment.
        Retourne False si le signal aligne avec retail extrême (contrarian alert).
        """
        status = self.is_retail_extreme(asset)
        if status == "contrarian_short" and side == "long":
            return False     # retail long → évite long
        if status == "contrarian_long" and side == "short":
            return False
        return True
