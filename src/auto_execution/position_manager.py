"""
Position Manager — surveille les positions MT5 ouvertes et applique
les exits multi-partials + trailing runner automatiquement.

Tourne en thread séparé, check toutes les N secondes (60s par défaut).
Pour chaque position gérée :
- Calcule R actuel
- Applique les exits (25%@1R, 25%@2R, 25%@3R, runner trail)
- Update SL via mt5.modify_position
- Close partial via mt5.close_position
- Marque les triggers pour ne pas re-fermer
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from threading import Thread, Lock, Event
from typing import Dict, List, Optional, Literal

from src.utils.logging_conf import get_logger
from src.exit_manager import ExitManager
from src.exit_manager.manager import (
    TradeState, ExitPlan, ExitAction, ExitOrder,
)

log = get_logger(__name__)


@dataclass
class ManagedPosition:
    """Position suivie par le PositionManager."""
    ticket: int
    symbol: str
    side: Literal["long", "short"]
    entry: float
    sl_original: float
    sl_current: float
    tp: float
    lots_original: float
    lots_current: float
    r_unit: float                        # Valeur d'1R en prix
    exit_plan: ExitPlan
    created_at: datetime
    last_atr: float = 0.0
    closed: bool = False
    telegram_notified: List[str] = field(default_factory=list)


class PositionManager:
    """Surveille et gère les positions MT5 en temps réel."""

    def __init__(
        self,
        mt5_executor,
        exit_manager: Optional[ExitManager] = None,
        check_interval_seconds: int = 60,
        telegram_bot=None,
    ):
        self.mt5 = mt5_executor
        self.exit_manager = exit_manager or ExitManager()
        self.check_interval = check_interval_seconds
        self.telegram = telegram_bot
        self.managed: Dict[int, ManagedPosition] = {}
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Optional[Thread] = None

    def register(
        self,
        ticket: int,
        symbol: str,
        side: str,
        entry: float,
        sl: float,
        tp: float,
        lots: float,
        atr: float = 0.0,
    ) -> ManagedPosition:
        """Enregistre une nouvelle position à gérer."""
        r_unit = abs(entry - sl)
        if r_unit <= 0:
            log.warning(f"Invalid r_unit for ticket {ticket}, not managed")
            r_unit = 0.0001  # Placeholder pour éviter div by zero
        plan = self.exit_manager.create_plan()
        mp = ManagedPosition(
            ticket=ticket,
            symbol=symbol,
            side=side,
            entry=entry,
            sl_original=sl,
            sl_current=sl,
            tp=tp,
            lots_original=lots,
            lots_current=lots,
            r_unit=r_unit,
            exit_plan=plan,
            created_at=datetime.utcnow(),
            last_atr=atr,
        )
        with self._lock:
            self.managed[ticket] = mp
        log.info(f"Position {ticket} registered: {symbol} {side} @ {entry} (r={r_unit:.5f})")
        return mp

    def unregister(self, ticket: int) -> None:
        with self._lock:
            self.managed.pop(ticket, None)

    def _sync_with_mt5(self) -> None:
        """
        Synchronise l'état local avec MT5 :
        - Supprime les positions fermées
        - Met à jour le prix courant pour chaque position
        """
        try:
            live = self.mt5.list_positions()
        except Exception as e:
            log.error(f"list_positions failed: {e}")
            return

        live_tickets = {p["ticket"] for p in live}
        with self._lock:
            local_tickets = set(self.managed.keys())
            # Remove closed
            for t in local_tickets - live_tickets:
                closed_pos = self.managed.pop(t, None)
                if closed_pos:
                    log.info(f"Position {t} closed (removed from manager)")
                    if self.telegram:
                        try:
                            self.telegram.send_text(
                                f"🔒 Position fermée : {closed_pos.symbol} "
                                f"(ticket {t})"
                            )
                        except Exception:
                            pass

    def _process_position(self, live_pos: Dict) -> None:
        """Process une position live et applique les exits."""
        ticket = live_pos["ticket"]
        with self._lock:
            mp = self.managed.get(ticket)
        if mp is None or mp.closed:
            return

        current_price = live_pos["current"]

        # Build TradeState pour evaluate
        state = TradeState(
            symbol=mp.symbol,
            side=mp.side,
            entry=mp.entry,
            sl_original=mp.sl_original,
            sl_current=mp.sl_current,
            position_size_original=mp.lots_original,
            position_size_current=mp.lots_current,
            tp=mp.tp,
            r_unit=mp.r_unit,
            exit_plan=mp.exit_plan,
            current_price=current_price,
            current_atr=mp.last_atr,
        )

        orders = self.exit_manager.evaluate(state)
        if not orders:
            return

        for order in orders:
            self._execute_exit_order(mp, order)

    def _execute_exit_order(self, mp: ManagedPosition, order: ExitOrder) -> None:
        """Exécute un ordre d'exit sur MT5."""
        try:
            if order.action == ExitAction.PARTIAL_CLOSE:
                pct = order.close_size / mp.lots_current if mp.lots_current > 0 else 0
                pct = min(max(pct, 0.0), 1.0)
                result = self.mt5.close_position(mp.ticket, partial_pct=pct)
                if result.success:
                    mp.lots_current -= order.close_size
                    log.info(
                        f"Ticket {mp.ticket}: PARTIAL {pct*100:.0f}% closed — {order.reason}"
                    )
                    self._notify(mp, order)
                else:
                    log.error(f"Partial close failed: {result.message}")

            elif order.action in (ExitAction.MOVE_SL, ExitAction.TRAIL_SL):
                result = self.mt5.modify_position(mp.ticket, new_sl=order.new_sl)
                if result.success:
                    mp.sl_current = order.new_sl
                    log.info(
                        f"Ticket {mp.ticket}: SL moved to {order.new_sl:.5f} — {order.reason}"
                    )
                else:
                    log.warning(f"Modify SL failed: {result.message}")

            elif order.action == ExitAction.FULL_CLOSE:
                result = self.mt5.close_position(mp.ticket, partial_pct=1.0)
                if result.success:
                    mp.closed = True
                    log.info(f"Ticket {mp.ticket}: FULL CLOSE — {order.reason}")
                    self._notify(mp, order)
                else:
                    log.error(f"Full close failed: {result.message}")
        except Exception as e:
            log.error(f"Exit order exec error: {e}")

    def _notify(self, mp: ManagedPosition, order: ExitOrder) -> None:
        """Envoie notification Telegram pour partial/close."""
        key = f"{order.action.value}_{order.reason}"
        if key in mp.telegram_notified:
            return
        mp.telegram_notified.append(key)
        if self.telegram is None:
            return
        try:
            msg = (
                f"💎 *EXIT {order.action.value.upper()}*\n"
                f"{mp.symbol} {mp.side.upper()} ticket {mp.ticket}\n"
                f"Reason: {order.reason}"
            )
            self.telegram.send_text(msg)
        except Exception as e:
            log.debug(f"Telegram notify failed: {e}")

    # ---------- Thread loop ----------
    def _loop(self) -> None:
        log.info(f"PositionManager loop started (interval={self.check_interval}s)")
        while not self._stop_event.is_set():
            try:
                self._sync_with_mt5()
                try:
                    live = self.mt5.list_positions()
                except Exception:
                    live = []
                for lp in live:
                    self._process_position(lp)
            except Exception as e:
                log.error(f"PositionManager loop error: {e}", exc_info=True)
            self._stop_event.wait(self.check_interval)
        log.info("PositionManager loop stopped")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._loop, daemon=True, name="PositionManager")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def summary(self) -> str:
        with self._lock:
            lines = [f"PositionManager: {len(self.managed)} managed positions"]
            for t, mp in self.managed.items():
                r_reached = self.exit_manager.current_r_reached(TradeState(
                    symbol=mp.symbol, side=mp.side, entry=mp.entry,
                    sl_original=mp.sl_original, sl_current=mp.sl_current,
                    position_size_original=mp.lots_original,
                    position_size_current=mp.lots_current, tp=mp.tp,
                    r_unit=mp.r_unit, exit_plan=mp.exit_plan,
                    current_price=mp.entry,
                ))
                lines.append(
                    f"  {t}: {mp.symbol} {mp.side} "
                    f"{mp.lots_current}/{mp.lots_original}lot "
                    f"partials={sum(1 for l in mp.exit_plan.levels if l.triggered)}/3"
                )
        return "\n".join(lines)
