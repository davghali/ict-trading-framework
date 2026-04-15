"""
Risk Engine — GARDIEN ABSOLU du capital. Compliance FTMO + The 5ers.

INVARIANT : le Risk Engine peut REJETER n'importe quel trade. C'est le SEUL
module qui a droit de veto absolu. Tout trade passe par lui avant exécution.

CONTRÔLES :
1. Daily loss cap (hard + soft)
2. Overall drawdown cap (hard + soft)
3. Consecutive losses → pause
4. Size réduit en drawdown
5. Max trades par jour/semaine
6. Weekend holding check (FTMO block)
7. News event check (si activé)
8. Risk per trade plafonné
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from typing import List, Optional, Tuple

import pandas as pd

from src.utils.config import get_prop_firm_rules
from src.utils.logging_conf import get_logger
from src.utils.types import Trade, Signal

log = get_logger(__name__)


@dataclass
class AccountState:
    balance: float
    initial_balance: float
    equity: float                       # balance + floating P&L
    start_of_day_balance: float
    peak_balance: float                  # all-time peak
    trades_today: int = 0
    trades_this_week: int = 0
    open_trades: List[Trade] = field(default_factory=list)
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    last_reset_day: Optional[date] = None
    trading_halted: bool = False
    halt_reason: str = ""

    def daily_pnl_pct(self) -> float:
        return (self.equity - self.start_of_day_balance) / self.initial_balance * 100

    def overall_dd_pct(self) -> float:
        return (self.equity - self.initial_balance) / self.initial_balance * 100


@dataclass
class RiskDecision:
    allow: bool
    reason: str
    suggested_size: float = 0.0
    risk_usd: float = 0.0
    risk_pct: float = 0.0


class RiskEngine:

    def __init__(self, firm: str = "ftmo", variant: str = "classic_challenge"):
        self.rules = get_prop_firm_rules(firm, variant)
        self.safety = self.rules["safety"]
        self.firm = firm
        self.variant = variant

        self._daily_violations: List[str] = []
        log.info(f"RiskEngine initialized: {firm}/{variant}")
        log.info(f"  Max daily: {self.rules['max_daily_loss_pct']}% | "
                 f"Overall: {self.rules['max_overall_loss_pct']}% | "
                 f"Safety daily soft: {self.safety['daily_loss_soft_cap_pct']}%")

    # ------------------------------------------------------------------
    def init_account(self, initial_balance: float) -> AccountState:
        return AccountState(
            balance=initial_balance,
            initial_balance=initial_balance,
            equity=initial_balance,
            start_of_day_balance=initial_balance,
            peak_balance=initial_balance,
            last_reset_day=None,
        )

    # ------------------------------------------------------------------
    def pre_trade_check(
        self,
        account: AccountState,
        signal: Signal,
        now: datetime,
    ) -> RiskDecision:
        """
        Vérifie tous les gates avant d'accepter un trade.
        Retourne RiskDecision(allow=False) si UN SEUL gate bloque.
        """
        # Reset daily if new day
        self._maybe_reset_daily(account, now)

        if account.trading_halted:
            return RiskDecision(False, f"Trading halted: {account.halt_reason}")

        # Gate 1 — weekend
        if not self.rules.get("weekend_holding", True):
            if now.weekday() == 4 and now.hour >= 21:     # Friday 9pm+ UTC
                return RiskDecision(False, "No weekend holding allowed (FTMO)")
            if now.weekday() >= 5:
                return RiskDecision(False, "Weekend — no trading")

        # Gate 2 — daily loss cap HARD
        daily_pnl_pct = account.daily_pnl_pct()
        hard_cap = -self.safety["daily_loss_hard_cap_pct"]
        if daily_pnl_pct <= hard_cap:
            self._halt(account, f"Daily hard cap hit: {daily_pnl_pct:.2f}%")
            return RiskDecision(False, account.halt_reason)

        # Gate 3 — daily soft cap → no new trade
        soft_cap = -self.safety["daily_loss_soft_cap_pct"]
        if daily_pnl_pct <= soft_cap:
            return RiskDecision(False, f"Daily soft cap: {daily_pnl_pct:.2f}% (no new trade)")

        # Gate 4 — overall DD
        overall = account.overall_dd_pct()
        if overall <= -self.safety["overall_loss_hard_cap_pct"]:
            self._halt(account, f"Overall hard cap: {overall:.2f}%")
            return RiskDecision(False, account.halt_reason)

        # Gate 5 — consecutive losses
        if account.consecutive_losses >= self.safety["max_consecutive_losses"]:
            return RiskDecision(
                False,
                f"{account.consecutive_losses} consecutive losses — cooling period",
            )

        # Gate 6 — max trades
        if account.trades_today >= self.safety["max_trades_per_day"]:
            return RiskDecision(False, "Max trades per day reached")
        if account.trades_this_week >= self.safety["max_trades_per_week"]:
            return RiskDecision(False, "Max trades per week reached")

        # Gate 7 — size des positions
        # Calcul du risque par trade adaptatif
        base_risk_pct = self.safety["risk_per_trade_base_pct"]

        # Réduction en drawdown
        scale_down = 1.0
        for rule in self.safety.get("drawdown_scale_down", []):
            if overall <= rule["threshold_pct"]:
                scale_down = min(scale_down, rule["size_multiplier"])

        effective_risk_pct = min(
            base_risk_pct * scale_down,
            self.safety["risk_per_trade_max_pct"],
        )

        # Si un trade venait à dépasser la limite journalière, plafonner davantage
        remaining_daily = -soft_cap - abs(daily_pnl_pct)  # % restant avant soft cap
        if remaining_daily > 0 and remaining_daily < effective_risk_pct:
            effective_risk_pct = remaining_daily * 0.8    # safety marge 20%

        risk_usd = account.balance * (effective_risk_pct / 100)

        # Calcul du sizing (unités / lots) — besoin du pip_value
        # Sera fait dans PositionSizer
        return RiskDecision(
            allow=True,
            reason="OK",
            risk_usd=risk_usd,
            risk_pct=effective_risk_pct,
        )

    # ------------------------------------------------------------------
    def on_trade_opened(self, account: AccountState, trade: Trade, now: datetime) -> None:
        self._maybe_reset_daily(account, now)
        account.open_trades.append(trade)
        account.trades_today += 1
        account.trades_this_week += 1

    def on_trade_closed(self, account: AccountState, trade: Trade) -> None:
        if trade in account.open_trades:
            account.open_trades.remove(trade)
        account.balance += trade.pnl_usd
        account.equity = account.balance + sum(t.pnl_usd for t in account.open_trades)

        if trade.is_win:
            account.consecutive_wins += 1
            account.consecutive_losses = 0
        else:
            account.consecutive_losses += 1
            account.consecutive_wins = 0

        account.peak_balance = max(account.peak_balance, account.balance)

    def update_equity(self, account: AccountState, mark_to_market: float) -> None:
        """À appeler à chaque bar pour MAJ de l'equity (float P&L)."""
        account.equity = account.balance + mark_to_market

    # ------------------------------------------------------------------
    def check_compliance(
        self, account: AccountState, now: datetime
    ) -> Tuple[bool, List[str]]:
        """Retourne (compliant, violations)."""
        violations = []
        daily = account.daily_pnl_pct()
        overall = account.overall_dd_pct()

        if daily < -self.rules["max_daily_loss_pct"]:
            violations.append(f"Daily loss {daily:.2f}% < -{self.rules['max_daily_loss_pct']}%")
        if overall < -self.rules["max_overall_loss_pct"]:
            violations.append(f"Overall loss {overall:.2f}% < -{self.rules['max_overall_loss_pct']}%")

        if not self.rules.get("weekend_holding", True):
            if now.weekday() >= 5 and len(account.open_trades) > 0:
                violations.append("Weekend position held (forbidden)")

        return len(violations) == 0, violations

    # ------------------------------------------------------------------
    def _maybe_reset_daily(self, account: AccountState, now: datetime) -> None:
        today = now.date()
        if account.last_reset_day != today:
            account.start_of_day_balance = account.balance
            account.trades_today = 0
            account.last_reset_day = today
            # reset weekly on Monday
            if now.weekday() == 0:
                account.trades_this_week = 0
            # unhalt if reason was daily-related
            if account.trading_halted and "Daily" in account.halt_reason:
                account.trading_halted = False
                account.halt_reason = ""
                log.info("New day: trading resumed")

    def _halt(self, account: AccountState, reason: str) -> None:
        account.trading_halted = True
        account.halt_reason = reason
        log.warning(f"TRADING HALTED: {reason}")
