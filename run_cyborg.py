"""
ICT CYBORG — daemon ultime.

Combine :
- Scanner multi-TF (W/D/H4/H1)
- Cross-asset filters (DXY, SPX, VIX implicites)
- Dynamic exit selon régime
- Telegram bot interactif avec boutons
- Auto-journal sur "Take"

Lance :
  python3 run_cyborg.py

Ou via LaunchAgent (auto-start macOS).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from datetime import datetime
from threading import Thread

sys.path.insert(0, str(Path(__file__).parent))
import warnings
warnings.filterwarnings("ignore")

from src.utils.user_settings import UserSettings, apply_env
from src.utils.logging_conf import get_logger
from src.telegram_bot import TelegramBot
from src.live_scanner import LiveScanner
from src.news_calendar import NewsCalendar, currencies_for

log = get_logger(__name__)


SCAN_INTERVAL_MIN = 15
MIN_ALERT_TIER = "BALANCED"           # ELITE / BALANCED / VOLUME
TIER_RANK = {"ELITE": 3, "BALANCED": 2, "VOLUME": 1, "SKIP": 0}


def run():
    apply_env()
    settings = UserSettings.load()
    bot = TelegramBot()

    if not bot.enabled:
        log.error("Telegram not configured. Check user_data/.env")
        return

    # 1) Start bot polling in background (listen for callbacks)
    Thread(target=bot.poll_updates, daemon=True).start()
    log.info("Telegram bot polling started in background")

    # 2) Startup message
    bot.send_text(
        "🔴 *ICT CYBORG DAEMON ACTIVE*\n\n"
        f"Scan toutes les {SCAN_INTERVAL_MIN} min\n"
        f"Alert tier min : *{MIN_ALERT_TIER}*\n"
        f"Assets : {', '.join(settings.assets_h1[:3])} + {', '.join(settings.assets_d1[:2])}\n\n"
        "Les signaux arrivent avec boutons ✅ / ❌ / 📊"
    )

    # 3) Main scan loop
    scanner = LiveScanner(
        symbols_h1=settings.assets_h1,
        symbols_d1=settings.assets_d1,
        tier="balanced",
        refresh_data=True,
    )
    news_cal = NewsCalendar(
        skip_minutes_before=settings.skip_news_minutes_before,
        skip_minutes_after=settings.skip_news_minutes_after,
        min_impact=settings.skip_news_impact.capitalize(),
    )
    try:
        news_cal.refresh()
    except Exception:
        pass

    alerted_ids = set()
    min_rank = TIER_RANK.get(MIN_ALERT_TIER, 2)

    while True:
        start = time.time()
        try:
            log.info(f"────── Scan @ {datetime.utcnow():%H:%M:%S} ──────")
            signals = scanner.scan_once()

            # Filter by news
            filtered = []
            for s in signals:
                ts = datetime.fromisoformat(s.timestamp_scan)
                if news_cal.is_in_news_window(ts, currencies_for(s.symbol)):
                    continue
                filtered.append(s)

            # Filter by tier
            filtered = [s for s in filtered if TIER_RANK.get(s.tier, 0) >= min_rank]

            # Send NEW signals (dedup via signature)
            new_count = 0
            for s in filtered:
                sig_id = f"{s.symbol}_{s.ltf}_{s.fvg_age_bars}_{int(s.entry * 1000)}"
                if sig_id in alerted_ids:
                    continue
                alerted_ids.add(sig_id)
                # Keep set bounded
                if len(alerted_ids) > 500:
                    alerted_ids = set(list(alerted_ids)[-300:])

                bot.send_signal_with_buttons(s)
                new_count += 1
                log.info(f"📨 Sent: {s.symbol} {s.ltf} {s.side} ({s.tier})")

            if new_count == 0:
                log.info(f"  {len(signals)} signals total, 0 new alerts")

        except Exception as e:
            log.error(f"Scan error: {e}")

        elapsed = time.time() - start
        sleep_for = max(60, SCAN_INTERVAL_MIN * 60 - elapsed)
        log.info(f"Next scan in {int(sleep_for)}s")
        time.sleep(sleep_for)


if __name__ == "__main__":
    run()
