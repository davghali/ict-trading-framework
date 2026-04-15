"""
News Calendar — fetch des events macro, skip N min avant/après.

Source : nfs.faireconomy.media/ff_calendar_thisweek.json (gratuit)
Impact : low, medium, high

NB : fallback offline via un cache si la source ne répond pas.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

USER_DATA_DIR = Path(__file__).parents[2] / "user_data"
USER_DATA_DIR.mkdir(exist_ok=True)
CACHE_FILE = USER_DATA_DIR / "news_cache.json"
CACHE_TTL_HOURS = 6

CALENDAR_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
]


@dataclass
class NewsEvent:
    datetime_utc: datetime
    currency: str
    title: str
    impact: str                          # "Low", "Medium", "High"
    forecast: str = ""
    previous: str = ""


class NewsCalendar:

    def __init__(self, skip_minutes_before: int = 30, skip_minutes_after: int = 30,
                 min_impact: str = "High"):
        self.skip_before = skip_minutes_before
        self.skip_after = skip_minutes_after
        self.min_impact = min_impact
        self._events: List[NewsEvent] = []
        self._loaded = False

    def refresh(self, force: bool = False) -> bool:
        """Télécharge/met à jour le calendrier. Cache 6h."""
        if not force and CACHE_FILE.exists():
            age = datetime.utcnow().timestamp() - CACHE_FILE.stat().st_mtime
            if age < CACHE_TTL_HOURS * 3600:
                return self._load_from_cache()

        for url in CALENDAR_URLS:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())
                CACHE_FILE.write_text(json.dumps(data))
                return self._load_from_cache()
            except Exception:
                continue
        # fallback
        return self._load_from_cache()

    def _load_from_cache(self) -> bool:
        if not CACHE_FILE.exists():
            return False
        try:
            raw = json.loads(CACHE_FILE.read_text())
            self._events = []
            for item in raw:
                try:
                    # Format ForexFactory : date UTC-5 implicit (US Eastern)
                    # We parse as provided; assume UTC if "Z" or offset
                    dt_str = item.get("date", "")
                    if not dt_str:
                        continue
                    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        # ForexFactory gives Eastern time — approximate UTC+5
                        dt = dt.replace(tzinfo=timezone.utc) + timedelta(hours=5)
                    self._events.append(NewsEvent(
                        datetime_utc=dt,
                        currency=item.get("country", "USD"),
                        title=item.get("title", ""),
                        impact=item.get("impact", "Low").capitalize(),
                        forecast=str(item.get("forecast", "")),
                        previous=str(item.get("previous", "")),
                    ))
                except Exception:
                    continue
            self._loaded = True
            return True
        except Exception:
            return False

    def is_in_news_window(self, ts: datetime, currency_filter: Optional[List[str]] = None) -> bool:
        """Retourne True si ts est dans [event - skip_before, event + skip_after]."""
        if not self._loaded:
            self.refresh()
        if not self._events:
            return False
        # Convert ts to UTC aware
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        impacts_allowed = {"Low", "Medium", "High"}
        if self.min_impact == "High":
            impacts_allowed = {"High"}
        elif self.min_impact == "Medium":
            impacts_allowed = {"Medium", "High"}

        for ev in self._events:
            if ev.impact not in impacts_allowed:
                continue
            if currency_filter and ev.currency not in currency_filter:
                continue
            start = ev.datetime_utc - timedelta(minutes=self.skip_before)
            end = ev.datetime_utc + timedelta(minutes=self.skip_after)
            if start <= ts <= end:
                return True
        return False

    def upcoming(self, hours: int = 24) -> List[NewsEvent]:
        if not self._loaded:
            self.refresh()
        now = datetime.now(timezone.utc)
        out = []
        for ev in self._events:
            if now <= ev.datetime_utc <= now + timedelta(hours=hours):
                out.append(ev)
        return sorted(out, key=lambda e: e.datetime_utc)


# Symbol → currencies impacted
SYMBOL_CURRENCIES = {
    "EURUSD": ["USD", "EUR"], "GBPUSD": ["USD", "GBP"], "USDJPY": ["USD", "JPY"],
    "AUDUSD": ["USD", "AUD"], "USDCAD": ["USD", "CAD"],
    "XAUUSD": ["USD"], "XAGUSD": ["USD"],
    "NAS100": ["USD"], "SPX500": ["USD"], "DOW30": ["USD"],
    "BTCUSD": ["USD"], "ETHUSD": ["USD"],
}


def currencies_for(symbol: str) -> List[str]:
    return SYMBOL_CURRENCIES.get(symbol, ["USD"])
