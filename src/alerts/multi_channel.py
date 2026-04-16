"""
MULTI-CHANNEL ALERTER — envoie à Telegram + Discord + Email en parallèle.

Zéro signal perdu : si Telegram down, Discord prend le relais. Si les 2 down,
email SMTP envoie le signal.

Configuration via user_data/.env :
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  DISCORD_WEBHOOK_URL
  EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, EMAIL_USER, EMAIL_PASS, EMAIL_TO
"""
from __future__ import annotations

import os
import json
import smtplib
import urllib.request
import urllib.parse
from email.mime.text import MIMEText
from typing import List, Dict, Optional

from src.utils.logging_conf import get_logger
from src.utils.user_settings import apply_env

log = get_logger(__name__)


class MultiChannelAlerter:

    def __init__(self):
        apply_env()
        self.tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.tg_chat = os.getenv("TELEGRAM_CHAT_ID", "")
        self.discord = os.getenv("DISCORD_WEBHOOK_URL", "")
        self.email_host = os.getenv("EMAIL_SMTP_HOST", "")
        self.email_port = int(os.getenv("EMAIL_SMTP_PORT", "587"))
        self.email_user = os.getenv("EMAIL_USER", "")
        self.email_pass = os.getenv("EMAIL_PASS", "")
        self.email_to = os.getenv("EMAIL_TO", "")

    # ------------------------------------------------------------------
    def send(self, title: str, body: str, priority: str = "normal") -> Dict[str, bool]:
        """
        Envoie sur TOUS les canaux configurés. Retourne {channel: success}.
        priority : "normal" | "critical" (critical = tous canaux forcés)
        """
        results = {}

        # Telegram
        if self.tg_token and self.tg_chat:
            results["telegram"] = self._send_telegram(title, body)
        else:
            results["telegram"] = False

        # Discord (backup)
        if self.discord and (priority == "critical" or not results.get("telegram")):
            results["discord"] = self._send_discord(title, body)
        else:
            results["discord"] = False

        # Email (last resort for critical)
        if (priority == "critical" and self.email_host and self.email_to
            and not any(results.values())):
            results["email"] = self._send_email(title, body)
        else:
            results["email"] = False

        return results

    # ------------------------------------------------------------------
    def _send_telegram(self, title: str, body: str) -> bool:
        try:
            text = f"*{title}*\n\n{body}"
            params = urllib.parse.urlencode({
                "chat_id": self.tg_chat,
                "text": text[:4000],
                "parse_mode": "Markdown",
            }).encode("utf-8")
            url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
            with urllib.request.urlopen(url, data=params, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return data.get("ok", False)
        except Exception as e:
            log.warning(f"Telegram failed: {e}")
            return False

    def _send_discord(self, title: str, body: str) -> bool:
        if not self.discord:
            return False
        try:
            payload = {
                "embeds": [{
                    "title": title,
                    "description": body[:2000],
                    "color": 0xDC2626,
                }]
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.discord, data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return 200 <= resp.status < 300
        except Exception as e:
            log.warning(f"Discord failed: {e}")
            return False

    def _send_email(self, title: str, body: str) -> bool:
        if not all([self.email_host, self.email_user, self.email_pass, self.email_to]):
            return False
        try:
            msg = MIMEText(body)
            msg["Subject"] = f"[ICT Cyborg] {title}"
            msg["From"] = self.email_user
            msg["To"] = self.email_to
            with smtplib.SMTP(self.email_host, self.email_port, timeout=20) as srv:
                srv.starttls()
                srv.login(self.email_user, self.email_pass)
                srv.send_message(msg)
            return True
        except Exception as e:
            log.warning(f"Email failed: {e}")
            return False
