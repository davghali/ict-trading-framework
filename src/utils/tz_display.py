"""
Timezone display helper — all user-facing times in Europe/Paris.

Internal logic uses UTC (consistent across regions).
Display (Telegram, logs, dashboard) uses Europe/Paris for David.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
    HAS_ZONEINFO = True
except ImportError:
    # Fallback for Python < 3.9 or missing tzdata
    # Europe/Paris is UTC+1 (winter) / UTC+2 (summer)
    # Approximation : use fixed offset +2 (summer) which covers most trading hours
    PARIS = timezone(timedelta(hours=2), name="Europe/Paris")
    HAS_ZONEINFO = False


def now_paris() -> datetime:
    """Return current time in Europe/Paris."""
    return datetime.now(PARIS)


def utc_to_paris(dt: datetime) -> datetime:
    """Convert a UTC datetime to Europe/Paris."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PARIS)


def format_paris(dt: datetime = None, fmt: str = "%d/%m/%Y %H:%M:%S") -> str:
    """Format a datetime in Europe/Paris timezone."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PARIS).strftime(fmt)


def paris_time_short(dt: datetime = None) -> str:
    """Short format HH:MM for Paris time."""
    return format_paris(dt, fmt="%H:%M")


def paris_datetime(dt: datetime = None) -> str:
    """Full Paris datetime."""
    return format_paris(dt, fmt="%d/%m/%Y %H:%M:%S %Z")


def is_dst_paris() -> bool:
    """True if Paris is currently on DST (UTC+2), False if winter (UTC+1)."""
    now = datetime.now(PARIS)
    return bool(now.dst()) if HAS_ZONEINFO else True
