"""
ALERTER — push notifications sur nouveau signal.

Supporte :
- Discord webhook (simple)
- Telegram bot (via bot token + chat_id)
- Fichier local JSON (historique)

Configuration via env vars :
  DISCORD_WEBHOOK_URL
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
"""
from __future__ import annotations

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import List

from src.live_scanner.scanner import LiveSignal
from src.utils.logging_conf import get_logger
from src.utils.config import REPORTS_DIR

log = get_logger(__name__)


class Alerter:

    def __init__(
        self,
        discord_webhook: str = None,
        telegram_bot_token: str = None,
        telegram_chat_id: str = None,
        min_tier: str = "BALANCED",
    ):
        self.discord = discord_webhook or os.getenv("DISCORD_WEBHOOK_URL")
        self.tg_token = telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.tg_chat = telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.min_tier = min_tier

        self._seen_file = REPORTS_DIR / "alerted_signals.json"
        self._seen = self._load_seen()

    def _load_seen(self) -> set:
        if self._seen_file.exists():
            try:
                return set(json.loads(self._seen_file.read_text()))
            except Exception:
                return set()
        return set()

    def _save_seen(self):
        # keep only last 1000 IDs
        ids = list(self._seen)[-1000:]
        self._seen_file.write_text(json.dumps(ids))

    def _signal_id(self, s: LiveSignal) -> str:
        """ID unique pour dédup."""
        return f"{s.symbol}_{s.ltf}_{s.side}_{s.fvg_age_bars}_{int(s.entry * 1000)}"

    # ------------------------------------------------------------------
    def alert_new(self, signals: List[LiveSignal]) -> int:
        """Alerte uniquement les signaux jamais vus ≥ tier minimum."""
        tier_rank = {"ELITE": 3, "BALANCED": 2, "VOLUME": 1, "SKIP": 0}
        min_rank = tier_rank.get(self.min_tier, 2)

        new_sigs = []
        for s in signals:
            if tier_rank.get(s.tier, 0) < min_rank:
                continue
            sig_id = self._signal_id(s)
            if sig_id in self._seen:
                continue
            self._seen.add(sig_id)
            new_sigs.append(s)

        for s in new_sigs:
            self._send(s)

        self._save_seen()
        return len(new_sigs)

    # ------------------------------------------------------------------
    def _send(self, s: LiveSignal):
        msg = self._format(s)
        sent = False
        if self.discord:
            if self._send_discord(msg, s):
                sent = True
        if self.tg_token and self.tg_chat:
            if self._send_telegram(msg):
                sent = True
        if not sent:
            # fallback : log only
            log.info(f"SIGNAL (local only): {s.symbol} {s.side} P(win)={s.ml_prob_win}")

    def _format(self, s: LiveSignal) -> str:
        emoji = "🎯" if s.tier == "ELITE" else ("⚖" if s.tier == "BALANCED" else "🚀")
        side_emoji = "🟢" if s.side == "long" else "🔴"
        prob_str = f"{s.ml_prob_win:.1%}" if s.ml_prob_win else "n/a"
        return (
            f"{emoji} **{s.tier}** — {s.symbol} {s.ltf}\n"
            f"{side_emoji} **{s.side.upper()}** @ {s.entry:.4f}\n"
            f"SL: {s.stop_loss:.4f}  |  TP1: {s.take_profit_1:.4f}  (RR {s.risk_reward:.2f})\n"
            f"P(win): **{prob_str}**  |  FVG age: {s.fvg_age_bars} bars  |  KZ: {s.killzone}\n"
            f"Current: {s.current_price:.4f}  (dist {s.distance_to_entry_pct:.2f}%)\n"
            f"⏰ {s.timestamp_scan}"
        )

    def _send_discord(self, msg: str, s: LiveSignal) -> bool:
        if not self.discord:
            return False
        try:
            color = 0x00FF00 if s.side == "long" else 0xFF0000
            embed = {
                "title": f"{s.tier} — {s.symbol} {s.ltf} — {s.side.upper()}",
                "description": msg,
                "color": color,
                "timestamp": datetime.utcnow().isoformat(),
            }
            payload = {"embeds": [embed]}
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.discord, data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if 200 <= resp.status < 300:
                    log.info(f"Discord alert sent: {s.symbol}")
                    return True
        except Exception as e:
            log.warning(f"Discord send failed: {e}")
        return False

    def _send_telegram(self, msg: str) -> bool:
        if not self.tg_token or not self.tg_chat:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
            payload = urllib.parse.urlencode({
                "chat_id": self.tg_chat,
                "text": msg,
                "parse_mode": "Markdown",
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload)
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    log.info("Telegram alert sent")
                    return True
        except Exception as e:
            log.warning(f"Telegram send failed: {e}")
        return False


if __name__ == "__main__":
    # Test mode — send a fake signal
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--discord", type=str, default=None)
    ap.add_argument("--telegram-token", type=str, default=None)
    ap.add_argument("--telegram-chat", type=str, default=None)
    args = ap.parse_args()

    from src.live_scanner.scanner import LiveSignal
    fake = LiveSignal(
        timestamp_scan=datetime.utcnow().isoformat(),
        symbol="XAUUSD", ltf="1h", side="long",
        entry=2400.50, stop_loss=2395.20, take_profit_1=2411.10,
        take_profit_2=2416.40, risk_reward=2.0,
        fvg_size_atr=1.2, fvg_age_bars=3, fvg_impulsion=1.5,
        killzone="ny_am_kz", current_price=2400.30,
        distance_to_entry_pct=0.01, ml_prob_win=0.47,
        tier="BALANCED", priority_score=75.0,
    )
    alerter = Alerter(
        discord_webhook=args.discord,
        telegram_bot_token=args.telegram_token,
        telegram_chat_id=args.telegram_chat,
    )
    n = alerter.alert_new([fake])
    print(f"Alerted: {n}")
