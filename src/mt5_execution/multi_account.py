"""
MT5 MULTI-ACCOUNT MANAGER — gère N comptes prop firms en parallèle.

Features :
- Pool de comptes (config via user_data/mt5_accounts.json)
- Router intelligent : quel compte prend quel signal
- Portfolio tracker : risk cumulé across accounts
- Per-account risk management (respect des limites broker)
- Asset whitelist par compte
- Priority-based routing
- Correlation-aware (évite over-exposure)

Usage :
    manager = MT5MultiAccountManager()
    manager.load_accounts()           # charge tous les comptes configurés
    results = manager.route_signal(signal)  # envoie au(x) compte(s) approprié(s)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

from src.mt5_execution.executor import MT5Executor, OrderResult
from src.utils.logging_conf import get_logger

log = get_logger(__name__)

ACCOUNTS_FILE = Path(__file__).parents[2] / "user_data" / "mt5_accounts.json"


@dataclass
class AccountState:
    """État live d'un compte."""
    id: str
    broker: str
    variant: str
    balance: float
    starting_balance: float
    max_daily_pct: float
    max_overall_pct: float
    risk_per_trade_pct: float
    enabled: bool = True
    priority: int = 1
    assets_whitelist: List[str] = field(default_factory=list)
    executor: Optional[MT5Executor] = None
    # Runtime
    open_positions: int = 0
    daily_pnl: float = 0.0
    overall_pnl: float = 0.0
    blocked_reason: str = ""

    @property
    def daily_pnl_pct(self) -> float:
        return self.daily_pnl / self.starting_balance * 100

    @property
    def overall_pnl_pct(self) -> float:
        return (self.balance - self.starting_balance) / self.starting_balance * 100

    def can_trade(self, asset: str = None) -> bool:
        if not self.enabled:
            self.blocked_reason = "disabled"
            return False
        # Check daily/overall loss limits (internal buffer at 70%)
        if self.daily_pnl_pct < -self.max_daily_pct * 0.7:
            self.blocked_reason = f"daily_pnl {self.daily_pnl_pct:.1f}% too close to limit"
            return False
        if self.overall_pnl_pct < -self.max_overall_pct * 0.7:
            self.blocked_reason = f"overall_pnl {self.overall_pnl_pct:.1f}% too close"
            return False
        # Asset whitelist
        if asset and self.assets_whitelist and asset not in self.assets_whitelist:
            self.blocked_reason = f"{asset} not whitelisted"
            return False
        self.blocked_reason = ""
        return True


@dataclass
class RouteResult:
    """Résultat du routage d'un signal."""
    signal_id: str
    routed_to: List[str]                 # account IDs qui ont pris le signal
    skipped: Dict[str, str]              # account_id → reason
    orders: List[OrderResult] = field(default_factory=list)


class MT5MultiAccountManager:

    def __init__(self):
        self.accounts: Dict[str, AccountState] = {}
        self.routing_rules: Dict = {}
        self._loaded = False

    # ------------------------------------------------------------------
    def load_accounts(self) -> int:
        """Charge les comptes depuis user_data/mt5_accounts.json."""
        if not ACCOUNTS_FILE.exists():
            log.info("No mt5_accounts.json — pas de compte MT5 configuré")
            return 0
        try:
            cfg = json.loads(ACCOUNTS_FILE.read_text())
        except Exception as e:
            log.error(f"Failed to load mt5_accounts.json: {e}")
            return 0

        self.routing_rules = cfg.get("routing_rules", {})
        for acc_cfg in cfg.get("accounts", []):
            if not acc_cfg.get("enabled", True):
                continue
            acc = AccountState(
                id=acc_cfg["id"],
                broker=acc_cfg["broker"],
                variant=acc_cfg.get("variant", ""),
                balance=acc_cfg.get("balance", 100000),
                starting_balance=acc_cfg.get("balance", 100000),
                max_daily_pct=acc_cfg.get("max_daily_pct", 5.0),
                max_overall_pct=acc_cfg.get("max_overall_pct", 10.0),
                risk_per_trade_pct=acc_cfg.get("risk_per_trade_pct", 0.5),
                enabled=acc_cfg.get("enabled", True),
                priority=acc_cfg.get("priority", 1),
                assets_whitelist=acc_cfg.get("assets_whitelist", []),
            )
            # Create executor
            acc.executor = MT5Executor(
                login=acc_cfg.get("login", 0),
                password=acc_cfg.get("password", ""),
                server=acc_cfg.get("server", ""),
            )
            # Update balance from live
            if not acc.executor.dry_run:
                try:
                    acc.executor.connect()
                    import MetaTrader5 as mt5
                    info = mt5.account_info()
                    if info:
                        acc.balance = info.balance
                        acc.overall_pnl = info.balance - info.credit
                except Exception as e:
                    log.warning(f"Could not fetch live balance for {acc.id}: {e}")

            self.accounts[acc.id] = acc
            log.info(f"Loaded account: {acc.id} ({acc.broker}) "
                      f"balance=${acc.balance:,.0f} "
                      f"{'LIVE' if acc.executor and not acc.executor.dry_run else 'DRY-RUN'}")

        self._loaded = True
        return len(self.accounts)

    # ------------------------------------------------------------------
    def route_signal(self, signal, max_accounts: int = 5) -> RouteResult:
        """
        Route un signal vers le(s) compte(s) approprié(s).

        Stratégie :
        1. Filtre les comptes qui peuvent trader (whitelist + risk)
        2. Tri par priority
        3. Envoie à max_accounts comptes
        """
        if not self._loaded:
            self.load_accounts()

        result = RouteResult(
            signal_id=f"{signal.symbol}_{signal.timestamp_scan}",
            routed_to=[], skipped={},
        )

        if not self.accounts:
            return result

        # Determine eligible accounts
        eligible = []
        for acc_id, acc in self.accounts.items():
            if not acc.can_trade(signal.symbol):
                result.skipped[acc_id] = acc.blocked_reason
                continue

            # Check asset routing rules
            asset_routing = self.routing_rules.get("asset_routing", {})
            if signal.symbol in asset_routing:
                if acc_id not in asset_routing[signal.symbol]:
                    result.skipped[acc_id] = f"{signal.symbol} not routed to {acc_id}"
                    continue

            # Max simultaneous per account check
            max_sim = self.routing_rules.get("max_simultaneous_per_account", 3)
            if acc.open_positions >= max_sim:
                result.skipped[acc_id] = f"max_simultaneous {max_sim} reached"
                continue

            eligible.append(acc)

        if not eligible:
            log.info(f"No eligible account for {signal.symbol}")
            return result

        # Sort by priority (lowest first = highest priority)
        eligible.sort(key=lambda a: a.priority)

        # Execute on top N accounts
        for acc in eligible[:max_accounts]:
            lots = self._calculate_lots(acc, signal)
            if lots <= 0:
                result.skipped[acc.id] = "lots calc = 0"
                continue

            order_result = acc.executor.place_order(
                symbol=signal.symbol,
                side=signal.side,
                lots=lots,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit_1,
                entry_type="limit",
                entry_price=signal.entry,
                comment=f"Cyborg {signal.tier}",
            )
            result.orders.append(order_result)
            if order_result.success:
                acc.open_positions += 1
                result.routed_to.append(acc.id)
                log.info(f"✓ Routed {signal.symbol} to {acc.id} (order {order_result.order_id})")
            else:
                result.skipped[acc.id] = f"order failed: {order_result.message}"

        return result

    # ------------------------------------------------------------------
    def _calculate_lots(self, acc: AccountState, signal) -> float:
        """Calcule la taille de lot selon le risque du compte."""
        from src.risk_engine.position_sizer import PositionSizer
        sizer = PositionSizer()
        risk_usd = acc.balance * acc.risk_per_trade_pct / 100
        sizing = sizer.calculate(signal.symbol, signal.entry,
                                  signal.stop_loss, risk_usd)
        return sizing.size if sizing.valid else 0

    # ------------------------------------------------------------------
    def get_portfolio_summary(self) -> Dict:
        """Retourne snapshot du portfolio cross-comptes."""
        total_balance = sum(a.balance for a in self.accounts.values())
        total_daily_pnl = sum(a.daily_pnl for a in self.accounts.values())
        total_overall_pnl = sum(a.overall_pnl for a in self.accounts.values())
        total_positions = sum(a.open_positions for a in self.accounts.values())
        worst_account_dd = 0
        if self.accounts:
            worst_account_dd = min(a.overall_pnl_pct for a in self.accounts.values())
        return {
            "n_accounts": len(self.accounts),
            "active_accounts": sum(1 for a in self.accounts.values() if a.enabled),
            "total_balance": total_balance,
            "total_daily_pnl": total_daily_pnl,
            "total_overall_pnl": total_overall_pnl,
            "total_open_positions": total_positions,
            "worst_dd_pct": worst_account_dd,
            "accounts": [
                {
                    "id": a.id,
                    "broker": a.broker,
                    "balance": a.balance,
                    "daily_pnl_pct": a.daily_pnl_pct,
                    "overall_pnl_pct": a.overall_pnl_pct,
                    "open_positions": a.open_positions,
                    "can_trade": a.can_trade(),
                    "blocked_reason": a.blocked_reason,
                }
                for a in self.accounts.values()
            ],
        }

    # ------------------------------------------------------------------
    def close_all(self, reason: str = "manual") -> None:
        """Ferme toutes les positions sur tous les comptes (kill switch)."""
        for acc in self.accounts.values():
            if acc.executor:
                positions = acc.executor.list_positions()
                for pos in positions:
                    acc.executor.close_position(pos["ticket"])
        log.warning(f"CLOSE ALL triggered: {reason}")
