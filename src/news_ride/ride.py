"""
News Ride Module — trade les retracements post-news au lieu d'éviter.

Flow :
1. News high impact détecté → attendre `wait_minutes` (5 min default)
2. Capture le spike (high/low depuis news release)
3. Attendre retracement à 61.8% du spike
4. Vérifier structure ICT (FVG/OB dans le sens du retournement)
5. Entrée SNIPER avec risque x0.5 (prudent vu volatilité élevée)
6. TP rapide (1.5R) car volatilité va se normaliser

Instruments ciblés : XAUUSD, EURUSD, GBPUSD, NAS100
(instruments très liquides avec retracements propres)

Désactivé par défaut (use_news_ride=false). À activer quand le reste est rodé.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Literal
from datetime import datetime, timedelta
from enum import Enum


class NewsRideState(str, Enum):
    IDLE = "idle"
    WAITING_SPIKE = "waiting_spike"
    SPIKE_CAPTURED = "spike_captured"
    WAITING_RETRACE = "waiting_retrace"
    ENTRY_VALID = "entry_valid"
    EXPIRED = "expired"


@dataclass
class NewsEvent:
    """Événement news en cours."""
    symbol: str
    currency: str
    timestamp: datetime
    impact: str                      # "high" | "medium"
    name: str
    pre_release_price: float


@dataclass
class NewsRideSignal:
    """Signal généré par news ride."""
    symbol: str
    side: Literal["long", "short"]
    entry: float
    sl: float
    tp: float
    risk_multiplier: float           # ex: 0.5 = risque réduit
    reason: str
    valid_until: datetime
    spike_high: float
    spike_low: float
    retracement_level: float


@dataclass
class NewsTracker:
    """Tracker d'un événement news actif."""
    event: NewsEvent
    state: NewsRideState = NewsRideState.WAITING_SPIKE
    spike_high: float = 0.0
    spike_low: float = float("inf")
    spike_captured_at: Optional[datetime] = None
    retracement_target: float = 0.0
    direction: Literal["long", "short", "unknown"] = "unknown"


class NewsRideModule:
    """Gère le ride post-news."""

    def __init__(
        self,
        wait_minutes: int = 5,
        retracement_pct: float = 0.618,
        risk_multiplier: float = 0.5,
        valid_window_minutes: int = 30,
        min_spike_size_pips: float = 20.0,
        target_rr: float = 1.5,
    ):
        self.wait_minutes = wait_minutes
        self.retracement_pct = retracement_pct
        self.risk_multiplier = risk_multiplier
        self.valid_window_minutes = valid_window_minutes
        self.min_spike_size_pips = min_spike_size_pips
        self.target_rr = target_rr
        self.active_trackers: Dict[str, NewsTracker] = {}

    def register_news(self, event: NewsEvent) -> None:
        """Enregistre une news qui vient de sortir."""
        key = f"{event.symbol}_{event.timestamp.isoformat()}"
        self.active_trackers[key] = NewsTracker(
            event=event,
            state=NewsRideState.WAITING_SPIKE,
        )

    def update_price(self, symbol: str, current_price: float, current_ts: datetime) -> List[NewsRideSignal]:
        """Mise à jour de prix — retourne signaux si conditions remplies."""
        signals: List[NewsRideSignal] = []
        to_remove: List[str] = []

        for key, tracker in self.active_trackers.items():
            if tracker.event.symbol != symbol:
                continue

            elapsed = (current_ts - tracker.event.timestamp).total_seconds() / 60.0

            # Expiration
            if elapsed > self.valid_window_minutes:
                tracker.state = NewsRideState.EXPIRED
                to_remove.append(key)
                continue

            # Phase 1: waiting spike
            if tracker.state == NewsRideState.WAITING_SPIKE:
                tracker.spike_high = max(tracker.spike_high, current_price)
                tracker.spike_low = min(tracker.spike_low, current_price)

                if elapsed >= self.wait_minutes:
                    pre_release = tracker.event.pre_release_price
                    # Direction : vers où a spike le plus (référence = pre_release)
                    up_move = max(0.0, tracker.spike_high - pre_release)
                    down_move = max(0.0, pre_release - tracker.spike_low)
                    if up_move + down_move <= 0:
                        to_remove.append(key)
                        continue
                    if up_move > down_move:
                        tracker.direction = "short"  # fade the up spike
                        tracker.retracement_target = (
                            tracker.spike_high - self.retracement_pct * up_move
                        )
                    else:
                        tracker.direction = "long"  # fade the down spike
                        tracker.retracement_target = (
                            tracker.spike_low + self.retracement_pct * down_move
                        )
                    tracker.state = NewsRideState.WAITING_RETRACE
                    tracker.spike_captured_at = current_ts

            # Phase 2: waiting retracement
            elif tracker.state == NewsRideState.WAITING_RETRACE:
                hit_target = False
                if tracker.direction == "long":
                    # wait price to come back up to retracement level
                    hit_target = current_price >= tracker.retracement_target
                elif tracker.direction == "short":
                    hit_target = current_price <= tracker.retracement_target

                if hit_target:
                    # Generate signal
                    if tracker.direction == "long":
                        entry = current_price
                        sl = tracker.spike_low - (tracker.spike_high - tracker.spike_low) * 0.1
                        r_unit = abs(entry - sl)
                        tp = entry + self.target_rr * r_unit
                    else:
                        entry = current_price
                        sl = tracker.spike_high + (tracker.spike_high - tracker.spike_low) * 0.1
                        r_unit = abs(sl - entry)
                        tp = entry - self.target_rr * r_unit

                    signals.append(NewsRideSignal(
                        symbol=symbol,
                        side=tracker.direction,
                        entry=entry,
                        sl=sl,
                        tp=tp,
                        risk_multiplier=self.risk_multiplier,
                        reason=f"News ride {tracker.event.name} ({self.retracement_pct*100:.1f}% retrace)",
                        valid_until=current_ts + timedelta(minutes=10),
                        spike_high=tracker.spike_high,
                        spike_low=tracker.spike_low,
                        retracement_level=tracker.retracement_target,
                    ))
                    tracker.state = NewsRideState.ENTRY_VALID
                    to_remove.append(key)

        for key in to_remove:
            self.active_trackers.pop(key, None)

        return signals

    def active_count(self) -> int:
        return len(self.active_trackers)

    def clear_expired(self, current_ts: datetime):
        """Nettoie les trackers expirés."""
        to_remove = []
        for key, tracker in self.active_trackers.items():
            elapsed = (current_ts - tracker.event.timestamp).total_seconds() / 60.0
            if elapsed > self.valid_window_minutes:
                to_remove.append(key)
        for key in to_remove:
            self.active_trackers.pop(key, None)
