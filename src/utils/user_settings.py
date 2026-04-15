"""
User Settings — préférences persistantes (hors du code).

Stockage : user_data/settings.json + user_data/.env

Tout ce que l'user peut configurer DANS le dashboard :
- Prop firm active + variant
- Risk per trade
- Assets à scanner
- Killzones à trader
- Scan interval
- Min tier pour alertes
- Webhooks Discord / Telegram
- Notification desktop on/off
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List


USER_DATA_DIR = Path(__file__).parents[2] / "user_data"
USER_DATA_DIR.mkdir(exist_ok=True)
SETTINGS_FILE = USER_DATA_DIR / "settings.json"
ENV_FILE = USER_DATA_DIR / ".env"


@dataclass
class UserSettings:
    # Prop firm
    firm: str = "ftmo"
    variant: str = "classic_challenge"
    account_balance: float = 100_000.0

    # Risk
    risk_per_trade_pct: float = 0.5
    daily_soft_cap_pct: float = 2.5
    daily_hard_cap_pct: float = 3.5

    # Assets to scan (par TF)
    assets_h1: List[str] = field(default_factory=lambda: [
        "XAUUSD", "XAGUSD", "BTCUSD", "NAS100", "DOW30", "SPX500",
    ])
    assets_d1: List[str] = field(default_factory=lambda: [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "ETHUSD",
    ])

    # Scan config
    scan_interval_minutes: int = 15
    default_tier: str = "balanced"       # elite / balanced / volume
    min_alert_tier: str = "BALANCED"

    # Alertes
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    desktop_notifications: bool = True
    sound_alerts: bool = True

    # News events
    skip_news_minutes_before: int = 30
    skip_news_minutes_after: int = 30
    skip_news_impact: str = "high"       # "all" | "high" | "none"

    # Money Management
    use_partial_tp: bool = True
    partial_tp_at_r: float = 1.0
    partial_tp_pct: float = 0.50
    move_be_at_r: float = 0.5

    def save(self) -> None:
        """Sauvegarde dans JSON (secrets vont dans .env)."""
        d = asdict(self)
        # Secrets dans .env (exclu du JSON)
        secret_keys = ["discord_webhook_url", "telegram_bot_token", "telegram_chat_id"]
        secrets = {k: d.pop(k) for k in secret_keys if k in d}
        SETTINGS_FILE.write_text(json.dumps(d, indent=2))
        # Write .env (key=value format)
        lines = [
            "# ICT Framework secrets — DO NOT COMMIT",
            "# Edit via dashboard Settings page",
        ]
        for k, v in secrets.items():
            lines.append(f"{k.upper()}={v}")
        ENV_FILE.write_text("\n".join(lines) + "\n")

    @classmethod
    def load(cls) -> "UserSettings":
        """Charge depuis settings.json + .env."""
        data = {}
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text())
            except Exception:
                pass
        # Read secrets from .env
        if ENV_FILE.exists():
            for line in ENV_FILE.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k_lower = k.strip().lower()
                if k_lower in ("discord_webhook_url", "telegram_bot_token", "telegram_chat_id"):
                    data[k_lower] = v.strip()
        # Fill defaults
        defaults = cls()
        merged = asdict(defaults)
        merged.update(data)
        return cls(**merged)

    def export_env(self) -> dict:
        """Retourne les secrets pour os.environ."""
        return {
            "DISCORD_WEBHOOK_URL": self.discord_webhook_url,
            "TELEGRAM_BOT_TOKEN": self.telegram_bot_token,
            "TELEGRAM_CHAT_ID": self.telegram_chat_id,
        }


def load_settings() -> UserSettings:
    return UserSettings.load()


def apply_env() -> None:
    """Exporte les secrets de settings → env vars."""
    s = UserSettings.load()
    for k, v in s.export_env().items():
        if v:
            os.environ[k] = v
