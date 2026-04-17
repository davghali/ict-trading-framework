"""
Dynamic Risk Manager — anti-martingale adaptatif.

Règles :
- Base : 0.5% (FTMO/The5ers) ou selon config
- Après 2 wins consécutifs : +0.2% (max 1.0%)
- Après 2 losses consécutives : -0.25% (min 0.25%)
- Après 3 losses d'affilée : reset base + lockout 24h
- Drawdown daily > 2% : forced min risk

Objectif : capitaliser les hot streaks, protéger sur cold streaks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Literal
from datetime import datetime, timedelta
from collections import deque


@dataclass
class RiskState:
    """État courant de gestion de risque."""
    base_risk: float = 0.5
    current_risk: float = 0.5
    max_risk: float = 1.0
    min_risk: float = 0.25
    hot_streak_boost: float = 0.2
    cold_streak_penalty: float = 0.25
    last_results: deque = field(default_factory=lambda: deque(maxlen=20))
    lockout_until: Optional[datetime] = None
    daily_pnl_pct: float = 0.0

    def get_consecutive_wins(self) -> int:
        count = 0
        for r in reversed(self.last_results):
            if r == "win":
                count += 1
            else:
                break
        return count

    def get_consecutive_losses(self) -> int:
        count = 0
        for r in reversed(self.last_results):
            if r == "loss":
                count += 1
            else:
                break
        return count

    def is_locked_out(self) -> bool:
        if self.lockout_until is None:
            return False
        return datetime.utcnow() < self.lockout_until


@dataclass
class RiskDecision:
    """Décision de risk pour un nouveau trade."""
    risk_pct: float
    allowed: bool
    reason: str
    consecutive_wins: int = 0
    consecutive_losses: int = 0


class DynamicRiskManager:
    """Gère le risque dynamique anti-martingale."""

    def __init__(
        self,
        base_risk: float = 0.5,
        max_risk: float = 1.0,
        min_risk: float = 0.25,
        hot_streak_boost: float = 0.2,
        cold_streak_penalty: float = 0.25,
        lockout_after_losses: int = 3,
        lockout_duration_hours: int = 24,
        daily_dd_lock_pct: float = 2.0,
    ):
        self.state = RiskState(
            base_risk=base_risk,
            current_risk=base_risk,
            max_risk=max_risk,
            min_risk=min_risk,
            hot_streak_boost=hot_streak_boost,
            cold_streak_penalty=cold_streak_penalty,
        )
        self.lockout_after_losses = lockout_after_losses
        self.lockout_duration_hours = lockout_duration_hours
        self.daily_dd_lock_pct = daily_dd_lock_pct

    def record_result(self, result: Literal["win", "loss", "breakeven"], pnl_pct: float = 0.0):
        """Enregistre un résultat de trade."""
        self.state.last_results.append(result)
        self.state.daily_pnl_pct += pnl_pct
        self._recompute_risk()
        self._check_lockout()

    def _recompute_risk(self):
        """Recalcule le risque courant selon les streaks."""
        wins = self.state.get_consecutive_wins()
        losses = self.state.get_consecutive_losses()

        if wins >= 2:
            # Hot streak : +boost par win au-dessus de 1
            boost = self.state.hot_streak_boost * (wins - 1)
            new_risk = min(self.state.base_risk + boost, self.state.max_risk)
            self.state.current_risk = new_risk
        elif losses >= 2:
            # Cold streak : -penalty par loss au-dessus de 1
            penalty = self.state.cold_streak_penalty * (losses - 1)
            new_risk = max(self.state.base_risk - penalty, self.state.min_risk)
            self.state.current_risk = new_risk
        else:
            # Mixed : retour à la base
            self.state.current_risk = self.state.base_risk

    def _check_lockout(self):
        """Active lockout si série de pertes ou DD daily trop gros."""
        losses = self.state.get_consecutive_losses()
        if losses >= self.lockout_after_losses:
            self.state.lockout_until = datetime.utcnow() + timedelta(
                hours=self.lockout_duration_hours
            )
            self.state.current_risk = self.state.min_risk

        if self.state.daily_pnl_pct <= -abs(self.daily_dd_lock_pct):
            self.state.lockout_until = datetime.utcnow() + timedelta(hours=12)
            self.state.current_risk = self.state.min_risk

    def reset_daily(self):
        """Reset daily PnL (à appeler en début de journée)."""
        self.state.daily_pnl_pct = 0.0

    def unlock(self):
        """Force unlock (manuel, ex: via Telegram)."""
        self.state.lockout_until = None
        self.state.current_risk = self.state.base_risk

    def decide(self) -> RiskDecision:
        """Décide du risque pour le prochain trade."""
        wins = self.state.get_consecutive_wins()
        losses = self.state.get_consecutive_losses()

        if self.state.is_locked_out():
            return RiskDecision(
                risk_pct=0.0,
                allowed=False,
                reason=f"LOCKOUT jusqu'à {self.state.lockout_until:%H:%M UTC}",
                consecutive_wins=wins,
                consecutive_losses=losses,
            )

        reason_parts = [f"Base {self.state.base_risk}%"]
        if wins >= 2:
            reason_parts.append(f"+{wins-1} hot streak boost")
        if losses >= 2:
            reason_parts.append(f"-{losses-1} cold streak penalty")

        return RiskDecision(
            risk_pct=self.state.current_risk,
            allowed=True,
            reason=" | ".join(reason_parts),
            consecutive_wins=wins,
            consecutive_losses=losses,
        )

    def summary(self) -> str:
        """Résumé lisible de l'état."""
        d = self.decide()
        wins = d.consecutive_wins
        losses = d.consecutive_losses
        locked = "🔒 LOCKED" if self.state.is_locked_out() else "🔓 OPEN"
        return (
            f"{locked} | Risk: {self.state.current_risk:.2f}% | "
            f"Wins: {wins} | Losses: {losses} | "
            f"Daily PnL: {self.state.daily_pnl_pct:+.2f}%"
        )
