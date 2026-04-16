"""
RETAIL SENTIMENT REAL — scrape Myfxbook community outlook.

URL : https://www.myfxbook.com/community/outlook

Myfxbook affiche pour chaque paire les % long/short du retail (community).
Principe contrarian : si 80% du retail est long un asset, souvent price baisse.

Le scraper parse la page HTML et cache les données 4h.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from src.utils.logging_conf import get_logger

log = get_logger(__name__)

CACHE_DIR = Path(__file__).parents[2] / "user_data"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_FILE = CACHE_DIR / "retail_sentiment_real.json"
CACHE_TTL_HOURS = 4

MYFXBOOK_URL = "https://www.myfxbook.com/community/outlook"

# Asset aliasing (Myfxbook format ≠ framework format)
ASSET_ALIASES = {
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
    "AUDUSD": "AUDUSD",
    "USDCAD": "USDCAD",
    "XAUUSD": "XAUUSD",
    "XAGUSD": "XAGUSD",
}


@dataclass
class RetailSentiment:
    asset: str
    timestamp: str
    long_pct: float              # 0-100
    short_pct: float             # 0-100
    long_lots: float = 0
    short_lots: float = 0
    total_traders: int = 0
    is_extreme_long: bool = False
    is_extreme_short: bool = False


class RetailRealFetcher:

    def __init__(self, extreme_threshold: float = 70.0):
        self._cache: Dict[str, RetailSentiment] = {}
        self.extreme_threshold = extreme_threshold

    # ------------------------------------------------------------------
    def refresh(self, force: bool = False) -> bool:
        if not force and CACHE_FILE.exists():
            age_h = (datetime.utcnow().timestamp() - CACHE_FILE.stat().st_mtime) / 3600
            if age_h < CACHE_TTL_HOURS:
                return self._load_cache()

        try:
            log.info("Fetching Myfxbook sentiment...")
            req = urllib.request.Request(
                MYFXBOOK_URL,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ICTBot/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            parsed = self._parse_html(html)
            if parsed:
                self._cache = parsed
                self._save_cache()
                log.info(f"Retail sentiment: {len(parsed)} assets parsed")
                return True
        except Exception as e:
            log.warning(f"Myfxbook fetch failed: {e}")

        return self._load_cache()

    # ------------------------------------------------------------------
    def _parse_html(self, html: str) -> Dict[str, RetailSentiment]:
        """
        Myfxbook affiche des blocs du type :
          EURUSD
          Short: 65%  Long: 35%

        Ou via une table HTML. Extraction par regex robuste.
        """
        out: Dict[str, RetailSentiment] = {}
        ts = datetime.utcnow().isoformat()

        for asset, alias in ASSET_ALIASES.items():
            # Find bloc near asset name
            patterns = [
                # Pattern 1 : explicit Short:X% Long:Y%
                rf"{alias}.{{0,500}}?Short:\s*(\d+(?:\.\d+)?)\s*%.{{0,200}}?Long:\s*(\d+(?:\.\d+)?)\s*%",
                rf"{alias}.{{0,500}}?Long:\s*(\d+(?:\.\d+)?)\s*%.{{0,200}}?Short:\s*(\d+(?:\.\d+)?)\s*%",
            ]
            matched = False
            for p_idx, pattern in enumerate(patterns):
                m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
                if m:
                    if p_idx == 0:
                        short_pct = float(m.group(1))
                        long_pct = float(m.group(2))
                    else:
                        long_pct = float(m.group(1))
                        short_pct = float(m.group(2))
                    out[asset] = RetailSentiment(
                        asset=asset,
                        timestamp=ts,
                        long_pct=long_pct,
                        short_pct=short_pct,
                        is_extreme_long=long_pct >= self.extreme_threshold,
                        is_extreme_short=short_pct >= self.extreme_threshold,
                    )
                    matched = True
                    break
            if not matched:
                log.debug(f"Could not parse sentiment for {asset}")

        return out

    # ------------------------------------------------------------------
    def _save_cache(self):
        data = {k: asdict(v) for k, v in self._cache.items()}
        CACHE_FILE.write_text(json.dumps(data, indent=2, default=str))

    def _load_cache(self) -> bool:
        if not CACHE_FILE.exists():
            return False
        try:
            data = json.loads(CACHE_FILE.read_text())
            self._cache = {k: RetailSentiment(**v) for k, v in data.items()}
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    def get(self, asset: str) -> Optional[RetailSentiment]:
        return self._cache.get(asset)

    def contrarian_filter(self, asset: str, side: str) -> bool:
        """
        Retourne True si le signal n'est PAS contre le contrarian signal.
        - Si retail est 70%+ long → pas de LONG (contrarian short)
        - Si retail est 70%+ short → pas de SHORT (contrarian long)
        """
        s = self.get(asset)
        if not s:
            return True
        if s.is_extreme_long and side == "long":
            return False       # retail trop long, évite le long
        if s.is_extreme_short and side == "short":
            return False
        return True
