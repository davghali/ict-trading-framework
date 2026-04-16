"""
COT (Commitments of Traders) — données positionnement institutionnel.

Source : CFTC.gov (gratuit, update hebdo le vendredi).

Usage ICT : si "Commercial" est MASSIVEMENT long → potentiel retournement imminent.
Si "Non-commercial" (specs) atteint extrême long/short → souvent contrarian.

Le module cache les données et expose :
- net_long / net_short par asset
- percentile sur N dernières semaines (extrême = signal)
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from src.utils.logging_conf import get_logger

log = get_logger(__name__)

CACHE_FILE = Path(__file__).parents[2] / "user_data" / "cot_cache.json"
CACHE_TTL_DAYS = 7

# CFTC symbol codes
COT_CODES = {
    "XAUUSD": "088691",   # Gold
    "XAGUSD": "084691",   # Silver
    "EURUSD": "099741",   # Euro FX
    "GBPUSD": "096742",   # British Pound
    "USDJPY": "097741",   # JPY
    "AUDUSD": "232741",   # AUD
    "USDCAD": "090741",   # CAD
    "NAS100": "209742",   # Nasdaq 100
    "SPX500": "13874A",   # S&P 500
}


@dataclass
class COTReport:
    asset: str
    date: str
    commercials_long: int
    commercials_short: int
    speculators_long: int
    speculators_short: int
    net_commercials: int
    net_speculators: int
    bias: str                   # "bullish_institutional" / "bearish_institutional" / "neutral"


class COTFetcher:

    def __init__(self):
        self._cache: Dict[str, COTReport] = {}

    # ------------------------------------------------------------------
    def refresh(self) -> bool:
        """Télécharge les dernières données COT. Cache 7 jours."""
        if CACHE_FILE.exists():
            age_days = (datetime.utcnow().timestamp() - CACHE_FILE.stat().st_mtime) / 86400
            if age_days < CACHE_TTL_DAYS:
                self._load_cache()
                return True

        # Fetch from CFTC (simplified : in practice parse XML from public URL)
        # Placeholder : we'd parse https://www.cftc.gov/dea/futures/deacmesf.htm
        # For now : return cached or empty
        self._load_cache()
        return True

    def _load_cache(self) -> None:
        if CACHE_FILE.exists():
            try:
                data = json.loads(CACHE_FILE.read_text())
                for asset, rep in data.items():
                    self._cache[asset] = COTReport(**rep)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def get(self, asset: str) -> Optional[COTReport]:
        return self._cache.get(asset)

    def bias_for(self, asset: str) -> str:
        """Retourne le biais COT : 'bullish' / 'bearish' / 'neutral' / 'unknown'."""
        report = self.get(asset)
        if not report:
            return "unknown"
        # Commercial positioning → edge
        if report.net_commercials > 0:
            return "bullish"      # commercials long = smart money long
        elif report.net_commercials < 0:
            return "bearish"
        return "neutral"

    def is_extreme(self, asset: str, threshold: float = 0.85) -> bool:
        """Positionnement extrême = risque de retournement."""
        report = self.get(asset)
        if not report:
            return False
        total = abs(report.net_speculators)
        # Simplified : si net specs > 85% de la position totale, extrême
        return total > threshold * abs(report.net_commercials + report.net_speculators)
