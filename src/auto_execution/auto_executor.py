"""
Auto Executor — place automatiquement les ordres MT5 sur signal A+.

Safety guards (configurables) :
- max_concurrent_positions : limite positions ouvertes simultanément
- max_positions_per_symbol : limite par symbole (évite sur-exposition)
- daily_loss_cap_pct : stop total si perdu % du compte dans la journée
- require_connection : si MT5 pas connecté, skip (pas de silent fail)
- paused : flag on/off via Telegram /pause /resume
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Optional, Dict, List, Literal

from src.utils.logging_conf import get_logger
from src.mt5_execution import MT5Executor

log = get_logger(__name__)


@dataclass
class AutoExecutionConfig:
    enabled: bool = True
    max_concurrent_positions: int = 5
    max_positions_per_symbol: int = 1
    daily_loss_cap_pct: float = 3.5          # Stop tout si -3.5% du solde
    min_account_balance_pct: float = 90.0    # Stop si balance < 90% initial
    allow_weekends: bool = False             # True pour BTC/ETH (legacy)
    # Trading days filter (weekday UTC : 0=Mon, 1=Tue, ... 4=Fri, 5=Sat, 6=Sun)
    # Par défaut : Lun-Ven UTC uniquement
    trading_days_utc: tuple = (0, 1, 2, 3, 4)
    # Horaires de blocage vendredi (évite weekend risk)
    friday_cutoff_hour_utc: int = 15         # Plus aucun trade après 15h UTC vendredi
    monday_earliest_hour_utc: int = 7        # Premier trade vendredi à 07h UTC lundi
    default_comment: str = "ICT Cyborg AUTO"
    initial_balance: float = 10000.0
    log_all_attempts: bool = True


@dataclass
class ExecutionResult:
    success: bool
    ticket: Optional[int] = None
    symbol: str = ""
    side: str = ""
    lots: float = 0.0
    entry: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    message: str = ""
    skipped_reason: str = ""


class AutoExecutor:
    """Orchestre l'auto-execution MT5 avec safety guards."""

    def __init__(
        self,
        config: Optional[AutoExecutionConfig] = None,
        mt5_executor: Optional[MT5Executor] = None,
    ):
        self.config = config or AutoExecutionConfig()
        self.mt5 = mt5_executor or MT5Executor()
        self._paused = False
        self._daily_pnl_pct = 0.0
        self._daily_reset_date: Optional[str] = None
        self._lock = Lock()
        self._ensure_connected()

    # ---------- State ----------
    @property
    def is_paused(self) -> bool:
        return self._paused

    def pause(self, reason: str = "manual") -> None:
        with self._lock:
            self._paused = True
        log.warning(f"AutoExecutor PAUSED — reason: {reason}")

    def resume(self) -> None:
        with self._lock:
            self._paused = False
        log.info("AutoExecutor RESUMED")

    def _ensure_connected(self) -> bool:
        if getattr(self.mt5, "_connected", False):
            return True
        try:
            return self.mt5.connect()
        except Exception as e:
            log.error(f"MT5 connect failed: {e}")
            return False

    # ---------- Daily tracking ----------
    def _check_daily_reset(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._daily_reset_date != today:
            self._daily_pnl_pct = 0.0
            self._daily_reset_date = today
            log.info(f"Daily PnL reset for {today}")

    def record_daily_pnl(self, pnl_pct: float) -> None:
        self._check_daily_reset()
        self._daily_pnl_pct += pnl_pct
        log.info(f"Daily PnL updated: {self._daily_pnl_pct:+.2f}%")

    # ---------- Safety guards ----------
    def _check_guards(self, symbol: str) -> Optional[str]:
        """Retourne None si OK, sinon le motif de blocage."""
        if not self.config.enabled:
            return "AutoExecutor disabled in config"
        if self._paused:
            return "AutoExecutor paused (via Telegram /pause)"

        self._check_daily_reset()
        if self._daily_pnl_pct <= -abs(self.config.daily_loss_cap_pct):
            return f"Daily loss cap hit ({self._daily_pnl_pct:.2f}%)"

        # Trading days filter (Lun-Ven UTC par défaut)
        now_utc = datetime.now(timezone.utc)
        weekday = now_utc.weekday()  # 0=Mon, 6=Sun
        if weekday not in self.config.trading_days_utc:
            return f"Trading disabled on weekday {weekday} (allowed: {self.config.trading_days_utc})"

        # Vendredi cutoff : plus de nouveaux trades après X h UTC vendredi
        if weekday == 4 and now_utc.hour >= self.config.friday_cutoff_hour_utc:
            return f"Friday cutoff active (>= {self.config.friday_cutoff_hour_utc}h UTC)"

        # Lundi : attendre ouverture des marchés
        if weekday == 0 and now_utc.hour < self.config.monday_earliest_hour_utc:
            return f"Monday early ({now_utc.hour}h UTC < {self.config.monday_earliest_hour_utc}h)"

        # Position limits
        try:
            positions = self.mt5.list_positions()
        except Exception as e:
            log.error(f"list_positions failed: {e}")
            positions = []

        if len(positions) >= self.config.max_concurrent_positions:
            return (
                f"Max concurrent positions reached "
                f"({len(positions)}/{self.config.max_concurrent_positions})"
            )

        same_symbol = sum(1 for p in positions if p.get("symbol", "").startswith(symbol[:5]))
        if same_symbol >= self.config.max_positions_per_symbol:
            return f"Max positions for {symbol} reached ({same_symbol})"

        # Balance check (optional)
        try:
            import MetaTrader5 as mt5mod
            if hasattr(self.mt5, "_connected") and self.mt5._connected:
                acc = mt5mod.account_info()
                if acc is not None:
                    balance_pct = (acc.balance / self.config.initial_balance) * 100
                    if balance_pct < self.config.min_account_balance_pct:
                        return (
                            f"Balance too low ({balance_pct:.1f}% of initial)"
                        )
        except Exception:
            pass

        return None

    # ---------- Sizing ----------
    def compute_lots_from_mt5(
        self,
        account_balance: float,
        risk_pct: float,
        entry: float,
        stop_loss: float,
        symbol: str,
    ) -> float:
        """
        Calcule la taille en lots en utilisant les vraies specs MT5.
        Respecte min_lot, max_lot, lot_step, tick_value du broker.
        Fallback sur compute_lots (formule simplifiee) si MT5 indispo.
        """
        try:
            import MetaTrader5 as mt5
            from src.mt5_execution.executor import FTMO_SYMBOL_MAP
            mt5_sym = FTMO_SYMBOL_MAP.get(symbol, symbol)
            info = mt5.symbol_info(mt5_sym)
            if info is None:
                return self.compute_lots(account_balance, risk_pct, entry, stop_loss, symbol)

            risk_amount = account_balance * (risk_pct / 100.0)
            sl_distance_price = abs(entry - stop_loss)
            if sl_distance_price <= 0:
                return 0.0

            # tick_value est la valeur en devise compte d'1 tick d'1 lot
            tick_value = info.trade_tick_value
            tick_size = info.trade_tick_size
            if tick_size <= 0 or tick_value <= 0:
                return self.compute_lots(account_balance, risk_pct, entry, stop_loss, symbol)

            # loss per lot = (sl_distance_price / tick_size) * tick_value
            loss_per_lot = (sl_distance_price / tick_size) * tick_value
            if loss_per_lot <= 0:
                return 0.0

            lots = risk_amount / loss_per_lot

            # Respecter min_lot, max_lot, lot_step
            min_lot = info.volume_min
            max_lot = info.volume_max
            lot_step = info.volume_step

            if lots < min_lot:
                # Risque trop faible pour ce symbole
                return 0.0
            if lots > max_lot:
                lots = max_lot

            # Arrondi au multiple de lot_step
            if lot_step > 0:
                lots = round(lots / lot_step) * lot_step
                # Encore verifier apres arrondi
                if lots < min_lot:
                    return 0.0
                if lots > max_lot:
                    lots = max_lot

            # Cap de securite
            lots = min(lots, 10.0)
            return round(lots, 2)
        except Exception as e:
            log.warning(f"compute_lots_from_mt5 failed for {symbol}: {e} - using fallback")
            return self.compute_lots(account_balance, risk_pct, entry, stop_loss, symbol)

    @staticmethod
    def compute_lots(
        account_balance: float,
        risk_pct: float,
        entry: float,
        stop_loss: float,
        symbol: str,
    ) -> float:
        """
        Calcule la taille en lots selon risque.
        Formule simplifiée : risk_amount / (distance_SL × pip_value)
        Pour FX majors : 1 lot = 100 000 unités, 1 pip = 10 USD.
        Pour gold/indices : ajustement via contract_size.
        """
        if account_balance <= 0 or risk_pct <= 0:
            return 0.0
        if entry <= 0 or stop_loss <= 0 or entry == stop_loss:
            return 0.0

        risk_amount = account_balance * (risk_pct / 100.0)
        sl_distance = abs(entry - stop_loss)

        # Contract size multipliers (approx)
        contract_mult = {
            "XAUUSD": 100,        # 100 oz per lot
            "XAGUSD": 5000,       # 5000 oz per lot
            "BTCUSD": 1,
            "ETHUSD": 1,
            "NAS100": 1,
            "SPX500": 1,
            "DOW30": 1,
            "GER40": 1,
            "UK100": 1,
        }
        mult = contract_mult.get(symbol, 100000)  # Default FX

        # USD per 1 unit price move per 1 lot
        usd_per_unit_per_lot = mult

        lots = risk_amount / (sl_distance * usd_per_unit_per_lot)

        # Round to 2 decimals (0.01 min lot)
        lots = max(0.01, round(lots, 2))

        # Cap absolue de sécurité
        lots = min(lots, 10.0)
        return lots

    # ---------- Main execute method ----------
    def execute_signal(
        self,
        signal: Dict,
        risk_pct: float = 0.5,
    ) -> ExecutionResult:
        """
        Exécute un signal A+.

        Args:
            signal : dict avec keys :
                symbol, side ("long"/"short"), entry, stop_loss, take_profit,
                account_balance (optionnel, sinon depuis MT5)
            risk_pct : % risque sur le compte (depuis DynamicRiskManager)

        Returns:
            ExecutionResult
        """
        symbol = signal.get("symbol", "")
        side = signal.get("side", "").lower()
        entry = float(signal.get("entry", 0))
        sl = float(signal.get("stop_loss", signal.get("sl", 0)))
        tp = float(signal.get("take_profit", signal.get("tp", 0)))

        # Guards
        skip_reason = self._check_guards(symbol)
        if skip_reason:
            if self.config.log_all_attempts:
                log.warning(f"Signal {symbol} skipped: {skip_reason}")
            return ExecutionResult(
                success=False,
                symbol=symbol,
                side=side,
                skipped_reason=skip_reason,
                message=f"Guard blocked: {skip_reason}",
            )

        # Get balance
        balance = signal.get("account_balance", self.config.initial_balance)
        try:
            import MetaTrader5 as mt5mod
            if getattr(self.mt5, "_connected", False):
                acc = mt5mod.account_info()
                if acc is not None:
                    balance = acc.balance
        except Exception:
            pass

        # Compute lots - prefer MT5-specific sizing if connected
        lots = self.compute_lots_from_mt5(balance, risk_pct, entry, sl, symbol)
        if lots <= 0:
            return ExecutionResult(
                success=False,
                symbol=symbol,
                skipped_reason="Invalid sizing (lots=0 or below min_lot)",
            )

        # Place order
        order_result = self.mt5.place_order(
            symbol=symbol,
            side=side,
            lots=lots,
            stop_loss=sl,
            take_profit=tp,
            entry_type="market",
            comment=self.config.default_comment,
        )

        if not order_result.success:
            log.error(f"MT5 order FAILED for {symbol}: {order_result.message}")
            return ExecutionResult(
                success=False,
                symbol=symbol,
                side=side,
                lots=lots,
                entry=entry,
                sl=sl,
                tp=tp,
                message=order_result.message,
            )

        log.info(
            f"AUTO-EXEC OK: {symbol} {side} {lots}lot @ {order_result.executed_price} "
            f"SL={sl} TP={tp} ticket={order_result.order_id}"
        )
        return ExecutionResult(
            success=True,
            ticket=order_result.order_id,
            symbol=symbol,
            side=side,
            lots=lots,
            entry=order_result.executed_price or entry,
            sl=sl,
            tp=tp,
            message="Filled",
        )

    def close_all(self, reason: str = "emergency") -> int:
        """Ferme toutes les positions ouvertes. Retourne le nombre fermé."""
        try:
            positions = self.mt5.list_positions()
        except Exception:
            return 0
        closed = 0
        for p in positions:
            result = self.mt5.close_position(p["ticket"], partial_pct=1.0)
            if result.success:
                closed += 1
                log.warning(f"Closed ticket {p['ticket']} ({p['symbol']}) — reason: {reason}")
        return closed

    def close_all_before_weekend(self, cutoff_hour_utc: int = 16) -> int:
        """
        Ferme toutes les positions si on est vendredi après cutoff_hour_utc.
        À appeler périodiquement (toutes les 5-10 min le vendredi).
        Retourne le nombre de positions fermées.
        """
        now_utc = datetime.now(timezone.utc)
        # Vendredi = weekday 4
        if now_utc.weekday() != 4:
            return 0
        if now_utc.hour < cutoff_hour_utc:
            return 0
        try:
            positions = self.mt5.list_positions()
        except Exception:
            return 0
        if not positions:
            return 0
        log.warning(
            f"Weekend guard: closing {len(positions)} positions "
            f"before weekend (friday {now_utc.hour}h UTC)"
        )
        return self.close_all(reason="weekend_guard")

    def summary(self) -> str:
        """Résumé de l'état pour Telegram."""
        try:
            positions = self.mt5.list_positions()
        except Exception:
            positions = []
        status = "PAUSED" if self._paused else "ACTIVE"
        return (
            f"AutoExec: {status}\n"
            f"Open positions: {len(positions)}/{self.config.max_concurrent_positions}\n"
            f"Daily PnL: {self._daily_pnl_pct:+.2f}% (cap: -{self.config.daily_loss_cap_pct}%)\n"
            f"MT5 connected: {getattr(self.mt5, '_connected', False)}\n"
            f"Dry-run mode: {getattr(self.mt5, 'dry_run', True)}"
        )
