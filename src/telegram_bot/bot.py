"""
Telegram Bot INTERACTIF — envoie les signaux avec boutons [✅ PRENDRE] [❌ SKIP] [📊 DÉTAILS]

Workflow :
1. Scanner daemon détecte un signal élite
2. Bot envoie message Telegram avec inline buttons
3. User clic "✅ PRENDRE" → signal ajouté au journal + (futur) envoyé à MT5
4. User clic "❌ SKIP" → signal marqué skippé dans journal
5. User clic "📊 DÉTAILS" → envoi rationale complète

Le bot utilise long-polling (pas besoin de webhook public).
"""
from __future__ import annotations

import os
import json
import time
import urllib.request
import urllib.parse
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from threading import Thread
import uuid

from src.utils.user_settings import UserSettings, apply_env
from src.utils.logging_conf import get_logger
from src.trade_journal import TradeJournal, JournalEntry

log = get_logger(__name__)


PENDING_SIGNALS_FILE = Path(__file__).parents[2] / "user_data" / "pending_signals.json"
PENDING_SIGNALS_FILE.parent.mkdir(exist_ok=True)


def _tg_api(token: str, method: str, **params) -> Dict:
    """Appel Telegram API direct (pas de dépendance externe)."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.warning(f"TG API error ({method}): {e}")
        return {"ok": False, "error": str(e)}


class TelegramBot:

    def __init__(self, token: str = None, chat_id: str = None):
        apply_env()
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self._offset = 0

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    # ------------------------------------------------------------------
    def test_connection(self) -> bool:
        """Test que le bot peut envoyer un message."""
        if not self.enabled:
            return False
        r = _tg_api(self.token, "getMe")
        if not r.get("ok"):
            return False
        return self.send_text("✅ ICT Cyborg connected") is not None

    # ------------------------------------------------------------------
    def send_text(self, text: str, parse_mode: str = "Markdown",
                   reply_markup: Optional[Dict] = None) -> Optional[int]:
        """Envoie un message. Retourne message_id."""
        if not self.enabled:
            return None
        params = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            params["reply_markup"] = json.dumps(reply_markup)
        r = _tg_api(self.token, "sendMessage", **params)
        if r.get("ok"):
            return r["result"]["message_id"]
        return None

    # ------------------------------------------------------------------
    def send_signal_with_buttons(self, signal, extra_info: str = "",
                                  enhanced=None) -> Optional[int]:
        """Envoie un signal avec boutons inline ACCEPT / SKIP / DETAILS.

        Si enhanced (EnhancedSignal) fourni → affiche le full cyborg package.
        """
        if not self.enabled:
            return None

        side_emoji = "🟢 ACHETER" if signal.side == "long" else "🔴 VENDRE"
        # Grade system : S/A+/A/B (legacy ELITE/BALANCED/VOLUME retires)
        tier_emoji = {"S": "💎", "A+": "🎯", "A": "⭐", "B": "✓"}.get(
            enhanced.cyborg_grade if enhanced else signal.tier, "•")
        p = f"{signal.ml_prob_win * 100:.0f}%" if signal.ml_prob_win else "—"

        # Build unique signal id for callback
        sig_id = f"{signal.symbol}_{signal.ltf}_{signal.fvg_age_bars}_{int(signal.entry * 1000)}"
        self._persist_pending(sig_id, signal)

        # Grade label
        if enhanced:
            label = f"{enhanced.cyborg_grade} GRADE"
            prob_display = f"{enhanced.final_probability * 100:.0f}%"
        else:
            label = signal.tier
            prob_display = p

        text = (
            f"*{tier_emoji} {label} — {signal.symbol} {signal.ltf.upper()}*\n\n"
            f"*{side_emoji}*\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📍 Entry : `{signal.entry:.4f}`\n"
            f"🛑 SL    : `{signal.stop_loss:.4f}`\n"
        )

        # Dynamic exit from enhancer
        if enhanced and enhanced.exit_plan:
            ep = enhanced.exit_plan
            text += f"🎯 TP1   : `{ep.tp1:.4f}`  ({ep.rr_to_tp1:.1f}R)\n"
            text += f"🏁 TP2   : `{ep.tp2:.4f}`  ({ep.rr_to_tp2:.1f}R)\n"
            if ep.tp3:
                text += f"🚀 TP3   : `{ep.tp3:.4f}`  ({ep.max_rr:.1f}R)\n"
        else:
            text += f"🎯 TP1   : `{signal.take_profit_1:.4f}`  (2R)\n"
            text += f"🏁 TP2   : `{signal.take_profit_2:.4f}`  (3R)\n"

        text += (
            f"━━━━━━━━━━━━━━━━━\n"
            f"📊 RR    : {signal.risk_reward:.1f}\n"
            f"🎲 P(win): *{prob_display}*\n"
            f"⏰ KZ    : {signal.killzone.replace('_', ' ').upper()}\n"
        )

        # Cross-asset confirmation
        if enhanced and enhanced.cross_asset:
            ca = enhanced.cross_asset
            text += f"\n🔗 *Cross-asset* ({ca.score:.0%}) :\n"
            for c in ca.confirmations[:3]:
                text += f"  • {c}\n"

        # Multi-TF alignment
        if enhanced and enhanced.multi_tf_score > 0:
            text += f"\n📐 *Multi-TF* ({enhanced.multi_tf_score:.0%}) :\n"
            for c in enhanced.multi_tf_details[:4]:
                text += f"  • {c}\n"

        # Ladder entries
        if enhanced and len(enhanced.ladder_entries) > 1:
            text += f"\n🪜 *Ladder entries* :\n"
            for i, le in enumerate(enhanced.ladder_entries, 1):
                text += f"  {i}. `{le.price:.4f}` × {le.lot_pct*100:.0f}%\n"

        # Regime / exit strategy
        if enhanced and enhanced.exit_plan:
            text += f"\n📊 *Régime* : {enhanced.exit_plan.regime}\n"
            text += f"💡 {enhanced.exit_plan.rationale}\n"

        if extra_info:
            text += f"\n{extra_info}"

        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ PRENDRE", "callback_data": f"take:{sig_id}"},
                    {"text": "❌ SKIP", "callback_data": f"skip:{sig_id}"},
                ],
                [
                    {"text": "📊 DÉTAILS", "callback_data": f"details:{sig_id}"},
                ],
            ],
        }
        return self.send_text(text, reply_markup=reply_markup)

    # ------------------------------------------------------------------
    def _persist_pending(self, sig_id: str, signal) -> None:
        """Sauvegarde le signal pour qu'on puisse le récupérer au callback."""
        all_pending = {}
        if PENDING_SIGNALS_FILE.exists():
            try:
                all_pending = json.loads(PENDING_SIGNALS_FILE.read_text())
            except Exception:
                all_pending = {}
        # Keep only last 100
        if len(all_pending) > 100:
            all_pending = dict(list(all_pending.items())[-80:])

        all_pending[sig_id] = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": signal.symbol,
            "ltf": signal.ltf,
            "side": signal.side,
            "entry": float(signal.entry),
            "stop_loss": float(signal.stop_loss),
            "take_profit_1": float(signal.take_profit_1),
            "take_profit_2": float(signal.take_profit_2),
            "risk_reward": float(signal.risk_reward),
            "ml_prob_win": float(signal.ml_prob_win) if signal.ml_prob_win else None,
            "tier": signal.tier,
            "killzone": signal.killzone,
            "fvg_age_bars": int(signal.fvg_age_bars),
        }
        PENDING_SIGNALS_FILE.write_text(json.dumps(all_pending, indent=2))

    def _get_pending(self, sig_id: str) -> Optional[Dict]:
        if not PENDING_SIGNALS_FILE.exists():
            return None
        try:
            all_pending = json.loads(PENDING_SIGNALS_FILE.read_text())
            return all_pending.get(sig_id)
        except Exception:
            return None

    # ------------------------------------------------------------------
    def answer_callback(self, callback_query_id: str, text: str = "") -> None:
        """Acknowledge un callback pour retirer le loading du bouton."""
        if not self.enabled:
            return
        _tg_api(self.token, "answerCallbackQuery",
                callback_query_id=callback_query_id, text=text)

    def edit_message_buttons(self, message_id: int, new_text: str = None,
                              new_markup: Optional[Dict] = None) -> None:
        """Remplace le message (retire les boutons après action)."""
        if not self.enabled:
            return
        params = {"chat_id": self.chat_id, "message_id": message_id}
        if new_text:
            params["text"] = new_text
            params["parse_mode"] = "Markdown"
            _tg_api(self.token, "editMessageText", **params)
        if new_markup:
            params2 = {"chat_id": self.chat_id, "message_id": message_id,
                        "reply_markup": json.dumps(new_markup)}
            _tg_api(self.token, "editMessageReplyMarkup", **params2)

    # ------------------------------------------------------------------
    def poll_updates(self, poll_interval: int = 2) -> None:
        """
        Long-polling loop : reçoit les callback_query et les traite.
        Cette fonction tourne dans le daemon Telegram bot.

        Robust against HTTP 409 Conflict (stale polling sessions) :
        - Startup : force deleteWebhook + drop pending updates
        - Fast-forward offset to skip any backlog
        - If 409 persists in the loop, force-cleanup every 3 consecutive errors
        """
        log.info("Telegram bot polling started")

        # --- Startup cleanup : libère toute session Telegram fantôme ---
        _tg_api(self.token, "deleteWebhook", drop_pending_updates="true")
        time.sleep(2)

        # Fast-forward offset past any pending updates
        peek = _tg_api(self.token, "getUpdates", offset=-1, timeout=1)
        if peek.get("ok") and peek.get("result"):
            self._offset = peek["result"][-1]["update_id"] + 1
            log.info(f"Telegram offset fast-forwarded to {self._offset}")

        consecutive_409 = 0
        while True:
            try:
                r = _tg_api(self.token, "getUpdates",
                              offset=self._offset,
                              timeout=25)
                if not r.get("ok"):
                    err = str(r.get("error", ""))
                    if "409" in err or "Conflict" in err:
                        consecutive_409 += 1
                        if consecutive_409 >= 3:
                            log.warning(
                                f"Repeated 409 Conflict ({consecutive_409}x) - "
                                "force deleteWebhook + 30s cooldown"
                            )
                            _tg_api(self.token, "deleteWebhook",
                                     drop_pending_updates="true")
                            time.sleep(30)
                            consecutive_409 = 0
                        else:
                            time.sleep(poll_interval * 3)
                    else:
                        time.sleep(poll_interval)
                    continue
                # Success : reset counter
                consecutive_409 = 0
                for update in r.get("result", []):
                    self._offset = update["update_id"] + 1
                    self._handle_update(update)
            except Exception as e:
                log.warning(f"Polling error: {e}")
                time.sleep(poll_interval)

    # ------------------------------------------------------------------
    def _handle_update(self, update: Dict) -> None:
        # Callback query (button click)
        cbq = update.get("callback_query")
        if cbq:
            data = cbq.get("data", "")
            callback_id = cbq.get("id")
            message = cbq.get("message", {})
            message_id = message.get("message_id")
            if ":" not in data:
                self.answer_callback(callback_id, "Invalid data")
                return

            action, sig_id = data.split(":", 1)
            signal_dict = self._get_pending(sig_id)
            if not signal_dict:
                self.answer_callback(callback_id, "Signal expiré")
                return

            if action == "take":
                self._on_take(callback_id, message_id, sig_id, signal_dict)
            elif action == "skip":
                self._on_skip(callback_id, message_id, sig_id, signal_dict)
            elif action == "details":
                self._on_details(callback_id, signal_dict)
            else:
                self.answer_callback(callback_id, "Action inconnue")
            return

        # Normal message (/start, etc.)
        msg = update.get("message")
        if msg:
            text = msg.get("text", "")
            if text.startswith("/start"):
                self.send_text(
                    "👋 *ICT Cyborg connected*\n\n"
                    "Tu recevras ici les signaux avec boutons pour accepter ou skip.\n\n"
                    "Commandes :\n"
                    "• /status - état du système\n"
                    "• /scan - scan manuel\n"
                    "• /stats - stats journal",
                )
            elif text.startswith("/status"):
                # Rich status : System + MT5 + positions + ML. Wrapped in try/except
                # so a single failing subquery doesn't silence the whole response.
                lines = ["ICT CYBORG FULL AUTO", "", "System: RUNNING"]
                auto = getattr(self, "auto_executor", None)
                if auto is not None:
                    try:
                        info = auto.mt5.account_info()
                        if info:
                            lines.append(
                                "MT5: connected (login {0}, balance ${1:.2f})".format(
                                    info.get("login", "?"),
                                    float(info.get("balance", 0)),
                                )
                            )
                        else:
                            lines.append("MT5: disconnected")
                    except Exception as e:
                        lines.append("MT5: error ({0})".format(e))
                    try:
                        positions = auto.mt5.list_positions()
                        lines.append("Positions open: {0}".format(len(positions)))
                    except Exception:
                        lines.append("Positions open: ?")
                    try:
                        paused = getattr(auto, "is_paused", False)
                        lines.append("Auto-exec: {0}".format("PAUSED" if paused else "LIVE"))
                    except Exception:
                        pass
                else:
                    lines.append("Auto-executor: not configured")
                lines.append("Chat ID: {0}".format(self.chat_id))
                # Send plain text (no parse_mode) to avoid Markdown/em-dash pitfalls
                try:
                    self.send_text("\n".join(lines), parse_mode="")
                except Exception as e:
                    log.warning("/status send failed: {0}".format(e))
                    try:
                        self.send_text("Bot actif (chat_id {0})".format(self.chat_id),
                                         parse_mode="")
                    except Exception:
                        pass
            elif text.startswith("/stats"):
                j = TradeJournal()
                stats = j.analytics()
                if stats["n_closed"] == 0:
                    self.send_text("📔 Aucun trade journalisé")
                else:
                    self.send_text(
                        f"📔 *Journal*\n"
                        f"Trades : {stats['n_closed']}\n"
                        f"WR : {stats['win_rate']:.1%}\n"
                        f"PnL : {stats['total_pnl_usd']:+,.0f} USD",
                    )
            elif text.startswith("/scan"):
                self.send_text("🔍 Lancement du scan...")
                Thread(target=self._run_scan, daemon=True).start()
            # ========== AUTO-EXECUTION COMMANDS ==========
            elif text.startswith("/pause"):
                auto = getattr(self, "auto_executor", None)
                if auto is None:
                    self.send_text("⚠️ Auto-executor non configuré")
                else:
                    auto.pause(reason="Telegram /pause")
                    self.send_text(
                        "⏸ *AUTO-EXECUTION PAUSÉE*\n"
                        "Le bot continuera à envoyer les alertes mais "
                        "ne placera plus d'ordre.\n\n"
                        "Utilise /resume pour reprendre."
                    )
            elif text.startswith("/resume"):
                auto = getattr(self, "auto_executor", None)
                if auto is None:
                    self.send_text("⚠️ Auto-executor non configuré")
                else:
                    auto.resume()
                    self.send_text(
                        "▶️ *AUTO-EXECUTION REPRISE*\n"
                        "Les signaux A+ seront à nouveau exécutés automatiquement."
                    )
            elif text.startswith("/auto_status"):
                auto = getattr(self, "auto_executor", None)
                if auto is None:
                    self.send_text("⚠️ Auto-executor non configuré")
                else:
                    self.send_text(f"```\n{auto.summary()}\n```")
            elif text.startswith("/positions"):
                auto = getattr(self, "auto_executor", None)
                if auto is None:
                    self.send_text("⚠️ Auto-executor non configuré")
                else:
                    try:
                        positions = auto.mt5.list_positions()
                        if not positions:
                            self.send_text("📊 Aucune position ouverte")
                        else:
                            lines = ["📊 *Positions ouvertes*"]
                            for p in positions:
                                lines.append(
                                    f"• {p['symbol']} {p['type']} "
                                    f"{p['volume']}lot "
                                    f"PnL {p['profit']:+.2f} USD"
                                )
                            self.send_text("\n".join(lines))
                    except Exception as e:
                        self.send_text(f"Erreur : {e}")
            elif text.startswith("/close_all"):
                auto = getattr(self, "auto_executor", None)
                if auto is None:
                    self.send_text("⚠️ Auto-executor non configuré")
                else:
                    closed = auto.close_all(reason="Telegram /close_all")
                    auto.pause(reason="After /close_all")
                    self.send_text(
                        f"🚨 *URGENCE — {closed} positions fermées*\n"
                        f"Auto-executor PAUSÉ.\n"
                        f"Utilise /resume pour relancer."
                    )

    # ------------------------------------------------------------------
    def _on_take(self, callback_id: str, message_id: int, sig_id: str,
                  sd: Dict) -> None:
        """User accepté le trade → log au journal."""
        s = UserSettings.load()
        j = TradeJournal()
        entry = JournalEntry(
            trade_id=str(uuid.uuid4())[:8],
            created_at=datetime.utcnow().isoformat(),
            symbol=sd["symbol"], ltf=sd["ltf"], side=sd["side"],
            entry=sd["entry"], stop_loss=sd["stop_loss"],
            take_profit_1=sd["take_profit_1"],
            take_profit_2=sd["take_profit_2"],
            source_signal_id=sig_id,
            ml_prob_win_at_signal=sd.get("ml_prob_win"),
            tier_at_signal=sd["tier"],
            entry_time=datetime.utcnow().isoformat(),
            entry_fill=sd["entry"],
            lots=0,                                   # à remplir manuellement
            risk_usd=s.account_balance * s.risk_per_trade_pct / 100,
            killzone=sd.get("killzone", ""),
            notes="Via Telegram cyborg",
        )
        j.log(entry)
        self.answer_callback(callback_id, "✅ Trade accepté et loggé !")
        new_text = (
            f"✅ *TRADE PRIS*\n"
            f"{sd['symbol']} {sd['ltf'].upper()} — {sd['side'].upper()}\n"
            f"Entry : {sd['entry']:.4f}\n"
            f"Trade ID : `{entry.trade_id}`\n\n"
            f"👉 Place l'ordre sur FTMO MetaTrader"
        )
        self.edit_message_buttons(message_id, new_text=new_text)

    def _on_skip(self, callback_id: str, message_id: int, sig_id: str,
                  sd: Dict) -> None:
        self.answer_callback(callback_id, "❌ Signal skippé")
        new_text = (
            f"❌ *SIGNAL SKIPPÉ*\n"
            f"{sd['symbol']} {sd['ltf'].upper()} — {sd['side'].upper()}\n"
            f"Prix : {sd['entry']:.4f}"
        )
        self.edit_message_buttons(message_id, new_text=new_text)

    def _on_details(self, callback_id: str, sd: Dict) -> None:
        self.answer_callback(callback_id, "Voir détails")
        details = (
            f"*📊 DÉTAILS — {sd['symbol']} {sd['ltf'].upper()}*\n\n"
            f"Side : {sd['side'].upper()}\n"
            f"Tier : {sd['tier']}\n"
            f"Probability : {sd.get('ml_prob_win', 0) * 100:.0f}%\n"
            f"RR : {sd['risk_reward']:.1f}\n\n"
            f"Entry : `{sd['entry']:.4f}`\n"
            f"Stop  : `{sd['stop_loss']:.4f}`\n"
            f"TP1   : `{sd['take_profit_1']:.4f}`\n"
            f"TP2   : `{sd['take_profit_2']:.4f}`\n\n"
            f"Session : {sd['killzone']}\n"
            f"FVG age : {sd.get('fvg_age_bars', '?')} bars\n\n"
            f"💡 *Plan d'exécution* :\n"
            f"1. Place ordre limit entry @ {sd['entry']:.4f}\n"
            f"2. SL @ {sd['stop_loss']:.4f} | TP @ {sd['take_profit_2']:.4f}\n"
            f"3. Quand @ TP1 ({sd['take_profit_1']:.4f}) → close 50% + SL à BE\n"
            f"4. Laisse courir jusqu'à TP2"
        )
        self.send_text(details)

    def _run_scan(self) -> None:
        """Helper pour /scan command."""
        try:
            from src.live_scanner import LiveScanner
            s = UserSettings.load()
            scanner = LiveScanner(
                symbols_h1=s.assets_h1[:3],
                symbols_d1=s.assets_d1[:2],
                tier="balanced",
                refresh_data=True,
            )
            signals = scanner.scan_once()
            if not signals:
                self.send_text("😴 Aucun signal actif")
                return
            for sig in signals[:3]:
                self.send_signal_with_buttons(sig)
        except Exception as e:
            self.send_text(f"❌ Erreur scan : {e}")


def run_bot():
    """Entry point pour LaunchAgent."""
    apply_env()
    bot = TelegramBot()
    if not bot.enabled:
        log.error("Bot not configured. Check user_data/.env")
        return
    bot.test_connection()
    bot.poll_updates()


if __name__ == "__main__":
    run_bot()
