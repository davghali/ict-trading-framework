"""
Sessions & Killzones — UTC-based, précis à la minute.

Sessions de référence (UTC) :
- Asia    : 00:00-08:00
- London  : 07:00-16:00
- NY      : 12:00-21:00

Killzones ICT (UTC) :
- London KZ       : 07:00-10:00
- NY AM KZ        : 12:30-15:00  (8:30-11:00 ET)
- NY PM KZ        : 18:30-20:30  (14:30-16:30 ET)
- Asia KZ         : 20:00-00:00  (session ouverture)
- London Open     : 07:00-08:00  (ouverture stricte)
- NY Open         : 13:30-14:30  (ouverture NYSE)
"""
from __future__ import annotations

from datetime import time, datetime, timedelta
from typing import Tuple, Optional
import pandas as pd


KILLZONES_UTC = {
    "asia_kz":     (time(20, 0), time(23, 59)),   # open asia
    "london_open": (time(7, 0),  time(8, 0)),
    "london_kz":   (time(7, 0),  time(10, 0)),
    "ny_am_kz":    (time(12, 30), time(15, 0)),
    "ny_open":     (time(13, 30), time(14, 30)),
    "ny_lunch":    (time(16, 0), time(17, 0)),
    "ny_pm_kz":    (time(18, 30), time(20, 30)),
}

SESSIONS_UTC = {
    "asia":   (time(0, 0),  time(8, 0)),
    "london": (time(7, 0),  time(16, 0)),
    "ny":     (time(12, 0), time(21, 0)),
}


def which_session(ts: datetime) -> Optional[str]:
    """Retourne 'asia' | 'london' | 'ny' | None."""
    t = ts.time()
    for name, (start, end) in SESSIONS_UTC.items():
        if start <= t < end:
            return name
    return None


def which_killzone(ts: datetime) -> Optional[str]:
    """Retourne le nom de la killzone en cours (ou None)."""
    t = ts.time()
    for name, (start, end) in KILLZONES_UTC.items():
        if start <= t <= end:
            return name
    return None


def is_in_killzone(ts: datetime, allowed: list[str] | None = None) -> bool:
    kz = which_killzone(ts)
    if kz is None:
        return False
    if allowed is None:
        return True
    return kz in allowed


def add_session_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute colonnes session + killzone à un DataFrame indexé par datetime UTC."""
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        raise TypeError("DataFrame index must be DatetimeIndex (UTC).")
    out["session"] = out.index.map(lambda ts: which_session(ts) or "off")
    out["killzone"] = out.index.map(lambda ts: which_killzone(ts) or "none")
    out["hour_utc"] = out.index.hour
    out["day_of_week"] = out.index.dayofweek   # Mon=0, Sun=6
    out["is_weekend"] = out["day_of_week"].isin([5, 6])
    return out


def previous_session_range(df: pd.DataFrame, session: str, reference_ts: datetime) -> Tuple[float, float]:
    """
    Retourne (high, low) de la session précédente spécifiée AVANT reference_ts.
    Ex : previous_session_range(df, 'ny', now) → PDH/PDL typique.
    """
    if session not in SESSIONS_UTC:
        raise ValueError(f"Unknown session: {session}")
    start_t, end_t = SESSIONS_UTC[session]

    ref_date = reference_ts.date()
    # scan back up to 7 days
    for days_back in range(1, 8):
        probe_date = ref_date - timedelta(days=days_back)
        mask = (df.index.date == probe_date) & \
               (df.index.time >= start_t) & (df.index.time < end_t)
        sub = df.loc[mask]
        if len(sub) > 0:
            return float(sub["high"].max()), float(sub["low"].min())
    return float("nan"), float("nan")
