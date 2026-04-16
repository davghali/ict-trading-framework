"""
TRADE MANAGER — gère les positions ouvertes automatiquement.

Pour chaque trade OPEN dans le journal :
1. Check current price (via yfinance refresh)
2. Si price >= TP1 et trade pas encore partial → alerte Telegram "Clos 50% + BE"
3. Si price >= 0.5R en profit → alerte "Move SL to BE"
4. Si price <= SL → alerte "Stop hit"
5. Si price >= TP2 → alerte "Target reached, close all"

Mode opérationnel :
- DRY MODE : envoie juste les ALERTES Telegram, l'user exécute
- LIVE MODE (avec MT5) : exécute automatiquement
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
import time

from src.trade_journal import TradeJournal, JournalEntry
from src.utils.user_settings import UserSettings, apply_env
from src.utils.logging_conf import get_logger
from src.data_engine import DataLoader
from src.utils.types import Timeframe

log = get_logger(__name__)


class TradeManager:

    def __init__(self, telegram_bot=None, mt5_executor=None):
        apply_env()
        self.settings = UserSettings.load()
        self.journal = TradeJournal()
        self.bot = telegram_bot
        self.mt5 = mt5_executor
        self.loader = DataLoader()
        # Track which alerts already sent (avoid spam)
        self._alerted = set()

    # ------------------------------------------------------------------
    def scan_open_positions(self) -> None:
        """Parcourt les trades ouverts et envoie les alertes de gestion."""
        open_trades = [e for e in self.journal.load_all() if not e.is_closed]
        if not open_trades:
            return

        for trade in open_trades:
            try:
                self._manage_one(trade)
            except Exception as e:
                log.warning(f"Manage trade {trade.trade_id} failed: {e}")

    # ------------------------------------------------------------------
    def _manage_one(self, trade: JournalEntry) -> None:
        """Gère un trade ouvert — alertes sur TP1, BE, trailing, SL."""
        # Get current price (try latest from data)
        try:
            df = self.loader.load(trade.symbol, Timeframe.H1)
            current_price = float(df["close"].iloc[-1])
        except Exception:
            try:
                df = self.loader.load(trade.symbol, Timeframe.D1)
                current_price = float(df["close"].iloc[-1])
            except Exception:
                return

        entry = trade.entry
        sl = trade.stop_loss
        tp1 = trade.take_profit_1
        tp2 = trade.take_profit_2
        risk_unit = abs(entry - sl)

        if risk_unit == 0:
            return

        # Compute current R
        if trade.side == "long":
            pct_to_tp = (current_price - entry) / risk_unit
        else:
            pct_to_tp = (entry - current_price) / risk_unit

        tid = trade.trade_id

        # Alert @ 0.5R → move SL to BE
        alert_key = f"{tid}_be"
        if pct_to_tp >= 0.5 and alert_key not in self._alerted:
            self._alerted.add(alert_key)
            self._send_alert(
                f"🟡 *MOVE SL TO BE*\n\n"
                f"{trade.symbol} {trade.side.upper()} #{tid}\n"
                f"Entry : {entry:.4f}\n"
                f"Current : {current_price:.4f}\n"
                f"R courant : +0.5R\n\n"
                f"👉 Déplace ton Stop Loss à `{entry:.4f}` (break-even)"
            )

        # Alert @ TP1 → partial close
        alert_key = f"{tid}_tp1"
        if ((trade.side == "long" and current_price >= tp1) or
            (trade.side == "short" and current_price <= tp1)) and alert_key not in self._alerted:
            self._alerted.add(alert_key)
            self._send_alert(
                f"🎯 *TP1 ATTEINT ({trade.symbol})*\n\n"
                f"Current : {current_price:.4f}\n"
                f"TP1 : {tp1:.4f}\n\n"
                f"👉 Action :\n"
                f"1. Ferme 50% de la position\n"
                f"2. Déplace SL à `{entry:.4f}` (BE)\n"
                f"3. Laisse courir vers TP2 {tp2:.4f}"
            )

        # Alert @ TP2 → full close
        alert_key = f"{tid}_tp2"
        if tp2 and ((trade.side == "long" and current_price >= tp2) or
                     (trade.side == "short" and current_price <= tp2)) and alert_key not in self._alerted:
            self._alerted.add(alert_key)
            self._send_alert(
                f"🏆 *TP2 ATTEINT !*\n\n"
                f"{trade.symbol} {trade.side.upper()} #{tid}\n"
                f"Target final atteint à {tp2:.4f}\n\n"
                f"👉 Ferme le reste de la position\n"
                f"Puis logge la fermeture dans le journal."
            )

        # SL hit
        alert_key = f"{tid}_sl"
        if ((trade.side == "long" and current_price <= sl) or
            (trade.side == "short" and current_price >= sl)) and alert_key not in self._alerted:
            self._alerted.add(alert_key)
            self._send_alert(
                f"🛑 *STOP LOSS TOUCHÉ*\n\n"
                f"{trade.symbol} {trade.side.upper()} #{tid}\n"
                f"SL : {sl:.4f}\n\n"
                f"👉 Ferme la position (probablement déjà fait par broker)\n"
                f"Puis logge la fermeture en 'sl'"
            )

    # ------------------------------------------------------------------
    def _send_alert(self, text: str) -> None:
        if self.bot is None:
            log.info(f"[DRY] {text[:80]}...")
            return
        self.bot.send_text(text)
