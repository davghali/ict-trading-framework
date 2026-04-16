"""
SUPERVISOR DAEMON — orchestre les tâches périodiques au-delà du scan.

- 07:00 UTC : Morning brief
- 22:00 UTC : Evening recap
- Dimanche 20:00 UTC : Weekly recap
- 1er du mois 20:00 UTC : Monthly recap
- Toutes les 10 min : gestion des trades ouverts (TP1, BE, TP2, SL alerts)
- Toutes les 60 min : heartbeat health check
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
import warnings
warnings.filterwarnings("ignore")

from src.utils.logging_conf import get_logger
from src.utils.user_settings import apply_env
from src.telegram_bot import TelegramBot
from src.recap import RecapGenerator
from src.health import HealthMonitor
from src.trade_manager import TradeManager

log = get_logger(__name__)


# Schedule (UTC)
MORNING_HOUR = 7        # 07:00 UTC
EVENING_HOUR = 22       # 22:00 UTC
WEEKLY_DAY = 6          # Sunday (Monday=0)
WEEKLY_HOUR = 20
MONTHLY_DAY = 1         # 1st of month
MONTHLY_HOUR = 20

TRADE_MANAGE_INTERVAL_SEC = 10 * 60    # 10 min
HEALTH_INTERVAL_SEC = 60 * 60          # 60 min


def run():
    apply_env()
    bot = TelegramBot()
    recap = RecapGenerator()
    health = HealthMonitor()
    tm = TradeManager(telegram_bot=bot)

    if not bot.enabled:
        log.error("Bot not configured")
        return

    bot.send_text(
        "🛡️ *SUPERVISOR ACTIVE*\n\n"
        "Tâches périodiques :\n"
        "🌅 Morning brief à 07h UTC\n"
        "🌙 Evening recap à 22h UTC\n"
        "📅 Weekly recap dimanche 20h\n"
        "📆 Monthly recap le 1er du mois\n"
        "💓 Health check chaque heure\n"
        "🎯 Trade management toutes les 10 min"
    )

    # Track last-run timestamps
    last_morning = None
    last_evening = None
    last_weekly = None
    last_monthly = None
    last_trade_manage = 0
    last_health = 0

    while True:
        try:
            now = datetime.utcnow()
            today_key = now.date()

            # Morning brief
            if (now.hour == MORNING_HOUR and last_morning != today_key):
                try:
                    msg = recap.morning_brief()
                    bot.send_text(msg)
                    last_morning = today_key
                    log.info("Morning brief sent")
                except Exception as e:
                    log.error(f"Morning brief failed: {e}")

            # Evening recap
            if (now.hour == EVENING_HOUR and last_evening != today_key):
                try:
                    msg = recap.evening_recap()
                    bot.send_text(msg)
                    last_evening = today_key
                    log.info("Evening recap sent")
                except Exception as e:
                    log.error(f"Evening recap failed: {e}")

            # Weekly recap (Sunday 20h)
            if (now.weekday() == WEEKLY_DAY and now.hour == WEEKLY_HOUR
                and last_weekly != today_key):
                try:
                    msg = recap.weekly_recap()
                    bot.send_text(msg)
                    last_weekly = today_key
                    log.info("Weekly recap sent")
                except Exception as e:
                    log.error(f"Weekly recap failed: {e}")

            # Monthly recap (1st 20h)
            if (now.day == MONTHLY_DAY and now.hour == MONTHLY_HOUR
                and last_monthly != today_key):
                try:
                    msg = recap.monthly_recap()
                    bot.send_text(msg)
                    last_monthly = today_key
                    log.info("Monthly recap sent")
                except Exception as e:
                    log.error(f"Monthly recap failed: {e}")

            # Trade management (every 10 min)
            if time.time() - last_trade_manage > TRADE_MANAGE_INTERVAL_SEC:
                try:
                    tm.scan_open_positions()
                    last_trade_manage = time.time()
                except Exception as e:
                    log.error(f"Trade manager failed: {e}")

            # Health check (hourly)
            if time.time() - last_health > HEALTH_INTERVAL_SEC:
                try:
                    report = health.check_all()
                    if not report.all_ok:
                        bot.send_text(f"⚠️ *HEALTH ISSUE*\n\n{report.summary()}")
                        health.auto_recover(report)
                    last_health = time.time()
                except Exception as e:
                    log.error(f"Health check failed: {e}")

        except Exception as e:
            log.error(f"Supervisor error: {e}")

        # Sleep until next minute tick
        time.sleep(60)


if __name__ == "__main__":
    run()
