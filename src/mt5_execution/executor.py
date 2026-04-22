"""
MT5 EXECUTOR — auto-exécution sur FTMO / The 5ers via MetaTrader 5 Python API.

Prérequis :
- pip install MetaTrader5 (sur Windows ou Mac via Crossover/Wine)
- Credentials FTMO MT5 : login, password, server (dispo sur dashboard FTMO)

Workflow :
1. Connect via mt5.initialize(login=..., password=..., server=...)
2. Place ordre market/limit avec SL/TP
3. Return order_id + status
4. Monitor positions ouvertes
5. Close partial au TP1, move SL à BE, etc.

NB : si MetaTrader5 pas installé (Mac ARM), mode DRY-RUN actif :
le code simule l'envoi sans vraiment connecter.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, List

from src.utils.logging_conf import get_logger
from src.utils.user_settings import UserSettings

log = get_logger(__name__)

# Try import MT5 — fallback to dry-run mode
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False
    log.info("MetaTrader5 not installed — MT5 executor in DRY-RUN mode")


# Mapping symbol → MT5 ticker (peut varier selon broker)
FTMO_SYMBOL_MAP = {
    "XAUUSD": "XAUUSD",
    "XAGUSD": "XAGUSD",
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
    "AUDUSD": "AUDUSD",
    "USDCAD": "USDCAD",
    "NAS100": "US100",
    "SPX500": "US500",
    "DOW30":  "US30",
    "BTCUSD": "BTCUSD",
    "ETHUSD": "ETHUSD",
}


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[int] = None
    message: str = ""
    executed_price: Optional[float] = None
    dry_run: bool = False


class MT5Executor:

    def __init__(self, login: int = None, password: str = None,
                 server: str = None, dry_run: bool = None):
        """
        Si credentials pas fournis, cherche dans os.environ :
          MT5_LOGIN, MT5_PASSWORD, MT5_SERVER
        """
        self.login = login or int(os.getenv("MT5_LOGIN", "0"))
        self.password = password or os.getenv("MT5_PASSWORD", "")
        self.server = server or os.getenv("MT5_SERVER", "")
        # Dry run si pas de MT5 installé OU pas de credentials
        if dry_run is None:
            self.dry_run = not MT5_AVAILABLE or not self.login
        else:
            self.dry_run = dry_run
        self._connected = False

    # ------------------------------------------------------------------
    def connect(self) -> bool:
        if self.dry_run:
            log.info("MT5Executor: DRY-RUN mode (no real connection)")
            self._connected = True
            return True
        if not MT5_AVAILABLE:
            log.error("MetaTrader5 package not available")
            return False
        ok = mt5.initialize(login=self.login, password=self.password,
                             server=self.server)
        if not ok:
            err = mt5.last_error()
            log.error(f"MT5 connect failed: {err}")
            return False
        acc = mt5.account_info()
        if acc is None:
            return False
        log.info(f"MT5 connected: {acc.login} balance=${acc.balance:.0f}")
        self._connected = True
        return True

    # ------------------------------------------------------------------
    def place_order(
        self,
        symbol: str,
        side: str,                        # "long" / "short"
        lots: float,
        stop_loss: float,
        take_profit: float,
        entry_type: str = "market",      # "market" | "limit"
        entry_price: Optional[float] = None,
        comment: str = "ICT Cyborg",
    ) -> OrderResult:
        if not self._connected:
            if not self.connect():
                return OrderResult(False, message="Not connected")

        mt5_symbol = FTMO_SYMBOL_MAP.get(symbol, symbol)

        if self.dry_run:
            # Simulate
            order_id = int(datetime.utcnow().timestamp())
            log.info(
                f"[DRY-RUN] {side.upper()} {mt5_symbol} {lots} lots @ "
                f"SL {stop_loss:.4f} TP {take_profit:.4f}"
            )
            return OrderResult(
                success=True, order_id=order_id,
                message=f"DRY-RUN order simulated",
                executed_price=entry_price,
                dry_run=True,
            )

        # REAL execution
        if side == "long":
            order_type = mt5.ORDER_TYPE_BUY if entry_type == "market" else mt5.ORDER_TYPE_BUY_LIMIT
        else:
            order_type = mt5.ORDER_TYPE_SELL if entry_type == "market" else mt5.ORDER_TYPE_SELL_LIMIT

        # Activer le symbole dans Market Watch si pas déjà fait (FTMO ETHUSD etc.)
        # Sans ça, symbol_info_tick() retourne None même si le symbole existe chez le broker.
        sym_info = mt5.symbol_info(mt5_symbol)
        if sym_info is None:
            # Essayer variantes communes FTMO (sufixes cashCFD, .x, etc.)
            for variant in [mt5_symbol + ".", mt5_symbol + "cash", mt5_symbol + ".x"]:
                sym_info = mt5.symbol_info(variant)
                if sym_info is not None:
                    mt5_symbol = variant
                    log.info(f"Symbol found as variant : {mt5_symbol}")
                    break
        if sym_info is None:
            return OrderResult(False, message=f"Symbol {mt5_symbol} not found in MT5 (check broker contract name)")

        if not sym_info.visible:
            log.info(f"Activating {mt5_symbol} in Market Watch...")
            if not mt5.symbol_select(mt5_symbol, True):
                return OrderResult(False, message=f"Cannot select {mt5_symbol} in Market Watch")
            # Laisser 200ms pour que MT5 peuple les ticks
            import time
            time.sleep(0.2)

        tick = mt5.symbol_info_tick(mt5_symbol)
        if tick is None:
            return OrderResult(False, message=f"No tick for {mt5_symbol} (symbol activated but no live data)")

        price = entry_price or (tick.ask if side == "long" else tick.bid)

        request = {
            "action": mt5.TRADE_ACTION_DEAL if entry_type == "market" else mt5.TRADE_ACTION_PENDING,
            "symbol": mt5_symbol,
            "volume": lots,
            "type": order_type,
            "price": price,
            "sl": stop_loss,
            "tp": take_profit,
            "deviation": 10,
            "magic": 20260416,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err_code = result.retcode if result else "unknown"
            err_msg = result.comment if result else mt5.last_error()
            log.error(f"MT5 order failed: {err_code} {err_msg}")
            return OrderResult(False, message=f"Failed: {err_msg}")

        log.info(f"MT5 order placed: {result.order} @ {result.price}")
        return OrderResult(
            success=True,
            order_id=result.order,
            executed_price=result.price,
            message="Order filled",
        )

    # ------------------------------------------------------------------
    def list_positions(self) -> List[Dict]:
        if self.dry_run or not self._connected:
            return []
        positions = mt5.positions_get()
        if not positions:
            return []
        return [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": "long" if p.type == mt5.POSITION_TYPE_BUY else "short",
                "volume": p.volume,
                "entry": p.price_open,
                "current": p.price_current,
                "sl": p.sl, "tp": p.tp,
                "profit": p.profit,
            }
            for p in positions
        ]

    def close_position(self, ticket: int, partial_pct: float = 1.0) -> OrderResult:
        """Ferme une position (ou partiellement)."""
        if self.dry_run:
            return OrderResult(True, order_id=ticket,
                                message=f"[DRY] closed {partial_pct*100:.0f}%", dry_run=True)
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return OrderResult(False, message=f"Position {ticket} not found")
        p = pos[0]
        close_lots = p.volume * partial_pct
        tick = mt5.symbol_info_tick(p.symbol)
        price = tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask
        opp_type = mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": p.symbol, "volume": close_lots,
            "type": opp_type, "price": price,
            "deviation": 10, "magic": 20260416,
            "comment": "ICT Cyborg close",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(req)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return OrderResult(True, order_id=result.order)
        return OrderResult(False, message=str(result))

    def modify_position(self, ticket: int, new_sl: float = None,
                         new_tp: float = None) -> OrderResult:
        """Modifie SL/TP (pour break-even, trailing)."""
        if self.dry_run:
            return OrderResult(True, order_id=ticket, dry_run=True,
                                message=f"[DRY] modified SL={new_sl} TP={new_tp}")
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return OrderResult(False)
        p = pos[0]
        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": p.symbol,
            "sl": new_sl if new_sl is not None else p.sl,
            "tp": new_tp if new_tp is not None else p.tp,
        }
        result = mt5.order_send(req)
        ok = result and result.retcode == mt5.TRADE_RETCODE_DONE
        return OrderResult(ok, order_id=ticket)

    # ------------------------------------------------------------------
    def shutdown(self):
        if MT5_AVAILABLE and self._connected and not self.dry_run:
            mt5.shutdown()
