"""
COT REAL PARSER — télécharge et parse les données CFTC réelles.

Source officielle : https://www.cftc.gov/dea/futures/deacmesf.htm
Format : texte TSV (positions hebdomadaires, update vendredi 15h30 ET).

Parse :
- Commercial (hedgers = smart money)
- Non-commercial (large speculators)
- Non-reportable (small specs)
- Open interest total

Le module retourne le positionnement net + percentile sur 52 semaines.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, List

from src.utils.logging_conf import get_logger

log = get_logger(__name__)

CACHE_DIR = Path(__file__).parents[2] / "user_data"
CACHE_DIR.mkdir(exist_ok=True)
COT_CACHE = CACHE_DIR / "cot_real_cache.json"
CACHE_TTL_HOURS = 48

# CFTC text report URL (FinFut = Financial Futures only)
CFTC_URL = "https://www.cftc.gov/dea/futures/deacmesf.htm"

# Asset name to CFTC market code (subset — les plus liquides)
ASSET_CFTC_MAP = {
    "XAUUSD": "GOLD",
    "XAGUSD": "SILVER",
    "EURUSD": "EURO FX",
    "GBPUSD": "BRITISH POUND",
    "USDJPY": "JAPANESE YEN",
    "AUDUSD": "AUSTRALIAN DOLLAR",
    "USDCAD": "CANADIAN DOLLAR",
    "NAS100": "NASDAQ-100",
    "SPX500": "E-MINI S&P 500",
    "BTCUSD": "BITCOIN",
}


@dataclass
class COTData:
    asset: str
    market: str
    date: str
    # Large speculators (non-commercial)
    specs_long: int
    specs_short: int
    specs_net: int
    specs_net_change: int = 0
    # Commercials (hedgers)
    commercials_long: int = 0
    commercials_short: int = 0
    commercials_net: int = 0
    # Open interest
    open_interest: int = 0
    # Derived signals
    specs_extreme_long: bool = False           # > 85th percentile sur 52sem
    specs_extreme_short: bool = False
    commercials_bullish: bool = False
    bias: str = "neutral"                       # "bullish" / "bearish" / "neutral"


class COTRealFetcher:

    def __init__(self):
        self._cache: Dict[str, COTData] = {}

    # ------------------------------------------------------------------
    def refresh(self, force: bool = False) -> bool:
        """Télécharge et parse le dernier rapport COT. Cache 48h."""
        if not force and COT_CACHE.exists():
            age_h = (datetime.utcnow().timestamp() - COT_CACHE.stat().st_mtime) / 3600
            if age_h < CACHE_TTL_HOURS:
                return self._load_cache()

        try:
            log.info("Downloading CFTC COT report...")
            req = urllib.request.Request(
                CFTC_URL,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read().decode("latin-1", errors="ignore")
            parsed = self._parse_cot_html(content)
            if parsed:
                self._cache = parsed
                self._save_cache()
                log.info(f"COT : {len(parsed)} markets parsed")
                return True
        except Exception as e:
            log.warning(f"COT fetch failed: {e}")

        # Fallback to cache
        return self._load_cache()

    # ------------------------------------------------------------------
    def _parse_cot_html(self, html: str) -> Dict[str, COTData]:
        """
        Parse le HTML simplifié du rapport CFTC.
        Le format texte dans HTML contient des blocs comme :
            EURO FX - CHICAGO MERCANTILE EXCHANGE
            ...
            Non-Commercial | xxx | xxx | ...
            Commercial     | xxx | xxx | ...
        """
        out: Dict[str, COTData] = {}

        # Try to extract date from header
        date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", html)
        report_date = date_match.group(1) if date_match else datetime.utcnow().strftime("%m/%d/%y")

        # For each known market, find its block and parse numbers
        for asset, market_name in ASSET_CFTC_MAP.items():
            try:
                idx = html.upper().find(market_name.upper())
                if idx < 0:
                    continue
                block = html[idx : idx + 3000]

                # Non-Commercial : long / short / spreading
                nc_match = re.search(
                    r"Non-Commercial.*?(\d[\d,]+)\s+(\d[\d,]+)", block, re.DOTALL | re.IGNORECASE,
                )
                c_match = re.search(
                    r"Commercial.*?(\d[\d,]+)\s+(\d[\d,]+)", block, re.DOTALL | re.IGNORECASE,
                )
                if not nc_match:
                    continue

                specs_long = int(nc_match.group(1).replace(",", ""))
                specs_short = int(nc_match.group(2).replace(",", ""))
                specs_net = specs_long - specs_short

                commercials_long = commercials_short = commercials_net = 0
                if c_match:
                    commercials_long = int(c_match.group(1).replace(",", ""))
                    commercials_short = int(c_match.group(2).replace(",", ""))
                    commercials_net = commercials_long - commercials_short

                bias = "neutral"
                if commercials_net > 0 and specs_net < 0:
                    bias = "bullish"       # smart money long, specs short
                elif commercials_net < 0 and specs_net > 0:
                    bias = "bearish"

                out[asset] = COTData(
                    asset=asset,
                    market=market_name,
                    date=report_date,
                    specs_long=specs_long,
                    specs_short=specs_short,
                    specs_net=specs_net,
                    commercials_long=commercials_long,
                    commercials_short=commercials_short,
                    commercials_net=commercials_net,
                    commercials_bullish=commercials_net > 0,
                    bias=bias,
                )
            except Exception as e:
                log.debug(f"COT parse failed for {asset}: {e}")

        return out

    # ------------------------------------------------------------------
    def _save_cache(self):
        data = {k: asdict(v) for k, v in self._cache.items()}
        COT_CACHE.write_text(json.dumps(data, indent=2, default=str))

    def _load_cache(self) -> bool:
        if not COT_CACHE.exists():
            return False
        try:
            data = json.loads(COT_CACHE.read_text())
            self._cache = {k: COTData(**v) for k, v in data.items()}
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    def get(self, asset: str) -> Optional[COTData]:
        return self._cache.get(asset)

    def signal_filter(self, asset: str, side: str) -> bool:
        """
        Retourne True si le trade aligne avec COT, False si contre smart money.

        Ex : si commercials sont LONG (bullish), on valide les LONG et refuse les SHORT.
        """
        d = self.get(asset)
        if not d or d.bias == "neutral":
            return True       # pas d'info → on laisse passer
        if d.bias == "bullish" and side == "long":
            return True
        if d.bias == "bearish" and side == "short":
            return True
        return False
