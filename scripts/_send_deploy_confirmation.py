"""Helper : send Telegram deploy confirmation (called by DEPLOY_ONE_CLICK.ps1 at the end)."""
from __future__ import annotations
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from src.telegram_bot.bot import TelegramBot
except ImportError as e:
    print("WARN: cannot import TelegramBot ({0}) - skipping confirmation".format(e))
    sys.exit(0)

MESSAGE = (
    "🚀 *BOT ML v2 DEPLOYED*\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "✅ ML threshold 0.45 (Pareto optimal)\n"
    "✅ 11 assets (6 H1 + 5 D1)\n"
    "✅ Auto-exec ON (FTMO Swing 10k)\n"
    "✅ Auto-restart ON (Scheduled Task)\n"
    "✅ Streamlit OFF\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🎯 Expected : WR 51.8% · PF 2.35\n"
    "📈 Annualized : +82% · DD -3.9%\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "Deployed at : {0} UTC\n"
    "Envoie /status pour vérifier le bot."
).format(datetime.utcnow().strftime("%Y-%m-%d %H:%M"))

try:
    bot = TelegramBot()
    if not bot.enabled:
        print("WARN: Telegram not configured - skipping confirmation")
        sys.exit(0)

    msg_id = bot.send_text(MESSAGE)
    if msg_id:
        print("Telegram confirmation sent (msg_id={0})".format(msg_id))
        sys.exit(0)
    else:
        print("WARN: Telegram send_text() returned None")
        sys.exit(0)
except Exception as e:
    print("WARN: confirmation failed ({0}) - bot is still live".format(e))
    sys.exit(0)
