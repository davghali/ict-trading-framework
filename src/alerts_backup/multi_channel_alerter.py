"""
Multi-Channel Alerter — Telegram primary, Email fallback.

Usage :
    alerter = MultiChannelAlerter(telegram_bot=bot, email_alerter=EmailAlerter())
    alerter.send_critical("Title", "Body")  # tries telegram first, fallback email
"""
from __future__ import annotations

from typing import Optional

from src.utils.logging_conf import get_logger
from .email_alerter import EmailAlerter

log = get_logger(__name__)


class MultiChannelAlerter:
    """Route critical alerts through Telegram (primary) + Email (fallback)."""

    def __init__(
        self,
        telegram_bot=None,
        email_alerter: Optional[EmailAlerter] = None,
    ):
        self.telegram = telegram_bot
        self.email = email_alerter or EmailAlerter()

    def _try_telegram(self, subject: str, body: str) -> bool:
        if self.telegram is None or not getattr(self.telegram, "enabled", False):
            return False
        try:
            full = f"*{subject}*\n\n{body}"
            result = self.telegram.send_text(full)
            # send_text may return None, dict, or nothing. Assume success if no exception.
            return True
        except Exception as e:
            log.warning(f"Telegram send failed: {e}")
            return False

    def send_info(self, subject: str, body: str) -> None:
        """Info alerts : Telegram only, no email (avoid inbox spam)."""
        self._try_telegram(subject, body)

    def send_warn(self, subject: str, body: str) -> None:
        """Warning alerts : Telegram + email if Telegram fails."""
        ok = self._try_telegram(subject, body)
        if not ok:
            self.email.send_warn(subject, body)

    def send_critical(self, subject: str, body: str) -> None:
        """Critical : Telegram + email ALWAYS (redundancy)."""
        self._try_telegram(subject, body)
        self.email.send_critical(subject, body)
