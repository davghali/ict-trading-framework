"""
Email Alerter — fallback alerts via SMTP quand Telegram fail.

Configuration via .env :
- SMTP_HOST (default: smtp.gmail.com)
- SMTP_PORT (default: 587)
- SMTP_USER (ex: ghalidavid5@gmail.com)
- SMTP_PASSWORD (App password Gmail 16 char)
- ALERT_EMAIL_TO (default: ghalidavid5@gmail.com)

Pour Gmail : créer un App Password sur
https://myaccount.google.com/apppasswords (2FA requis).
"""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional

from src.utils.logging_conf import get_logger

log = get_logger(__name__)


class EmailAlerter:
    """Send alert emails via SMTP."""

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        email_to: Optional[str] = None,
    ):
        self.smtp_host = smtp_host or os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = smtp_user or os.getenv("SMTP_USER", "")
        self.smtp_password = smtp_password or os.getenv("SMTP_PASSWORD", "")
        self.email_to = email_to or os.getenv(
            "ALERT_EMAIL_TO", "ghalidavid5@gmail.com"
        )
        self.enabled = bool(self.smtp_user and self.smtp_password)

    def send(self, subject: str, body: str, level: str = "INFO") -> bool:
        """
        Send an email alert.
        level : INFO | WARN | CRITICAL (just for formatting)
        Returns True if sent, False if failed.
        """
        if not self.enabled:
            log.debug("EmailAlerter disabled (no SMTP credentials)")
            return False

        prefix = {"INFO": "🔵", "WARN": "⚠️", "CRITICAL": "🚨"}.get(level, "")
        full_subject = f"{prefix} ICT Cyborg — {subject}"

        msg = MIMEMultipart()
        msg["From"] = self.smtp_user
        msg["To"] = self.email_to
        msg["Subject"] = full_subject

        html_body = f"""
        <html>
        <body style="font-family: monospace; background: #f0f0f0; padding: 20px;">
          <div style="background: white; padding: 20px; border-radius: 8px;">
            <h2 style="color: {'red' if level=='CRITICAL' else 'orange' if level=='WARN' else 'blue'};">
              {prefix} {subject}
            </h2>
            <pre style="white-space: pre-wrap;">{body}</pre>
            <hr>
            <small>Envoyé automatiquement par ICT Cyborg — {datetime.utcnow().isoformat()} UTC</small>
          </div>
        </body>
        </html>
        """
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            log.info(f"Email alert sent: {subject}")
            return True
        except Exception as e:
            log.error(f"Email send failed: {e}")
            return False

    def send_critical(self, subject: str, body: str) -> bool:
        return self.send(subject, body, level="CRITICAL")

    def send_warn(self, subject: str, body: str) -> bool:
        return self.send(subject, body, level="WARN")

    def test(self) -> bool:
        """Test l'envoi d'un email."""
        return self.send(
            "Test connexion SMTP",
            "Ceci est un email de test du système ICT Cyborg.\n"
            "Si tu reçois cet email, le fallback email est opérationnel.\n\n"
            f"Date : {datetime.utcnow().isoformat()} UTC\n"
            f"From : {self.smtp_user}\n"
            f"To   : {self.email_to}",
            level="INFO",
        )
