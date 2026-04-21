# WEEKLY_REPORT.ps1 - Weekly performance report Sunday 20:00
$FRAMEWORK_DIR = "C:\Users\Administrator\ict-trading-framework"
Set-Location $FRAMEWORK_DIR
$env:PYTHONIOENCODING = "utf-8"

python -c @"
import sys, json
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, '.')
try:
    from src.trade_journal import TradeJournal
    from src.telegram_bot import TelegramBot
    from src.utils.user_settings import apply_env
    apply_env()
    bot = TelegramBot()
    j = TradeJournal()
    stats = j.analytics()
    txt = (
        '📊 WEEKLY REPORT\n\n'
        f'Trades cloturés : {stats[\"n_closed\"]}\n'
        f'Winrate : {stats[\"win_rate\"]:.1%}\n'
        f'PnL total : {stats[\"total_pnl_usd\"]:+,.0f} USD\n'
    )
    if bot.enabled:
        bot.send_text(txt)
    print(txt)
except Exception as e:
    print(f'Report failed: {e}')
"@ 2>&1
