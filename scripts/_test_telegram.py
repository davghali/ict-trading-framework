"""Helper : test Telegram bot connection (called by DEPLOY_ONE_CLICK.ps1)"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from src.telegram_bot.bot import TelegramBot
except ImportError as e:
    print("FAIL: cannot import TelegramBot ({0})".format(e))
    sys.exit(1)

try:
    bot = TelegramBot()
    if not bot.enabled:
        print("FAIL: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in .env")
        sys.exit(1)

    if bot.test_connection():
        print("Telegram OK")
        sys.exit(0)
    else:
        print("FAIL: Telegram test_connection() returned False")
        sys.exit(1)
except Exception as e:
    print("FAIL: {0}".format(e))
    sys.exit(1)
