"""
DAEMON LIVE — scanner continu + alertes.

Lance un loop qui :
1. Scanne les 12 assets toutes les N minutes
2. Détecte les NOUVEAUX signaux (pas déjà vus)
3. Envoie alertes Discord / Telegram si configurés
4. Sauvegarde chaque scan en JSON

Usage :
    # Scan toutes les 15 min
    python3 run_daemon.py --interval 15 --tier balanced

    # Avec Discord
    export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
    python3 run_daemon.py --interval 15

    # Avec Telegram
    export TELEGRAM_BOT_TOKEN="..."
    export TELEGRAM_CHAT_ID="..."
    python3 run_daemon.py --interval 15
"""
from __future__ import annotations

import sys
import time
import argparse
import warnings
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
warnings.filterwarnings("ignore")

from src.live_scanner import LiveScanner
from src.live_scanner.alerter import Alerter
from src.live_scanner.scanner import save_signals_json, print_signals
from src.live_scanner.desktop_notify import notify_signal
from src.utils.user_settings import UserSettings, apply_env
from src.news_calendar import NewsCalendar, currencies_for


def main():
    # Load user preferences + push secrets to env
    apply_env()
    settings = UserSettings.load()

    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=settings.scan_interval_minutes,
                    help="Minutes entre scans")
    ap.add_argument("--tier", default=settings.default_tier,
                    choices=["elite", "balanced", "volume"])
    ap.add_argument("--min-alert-tier", default=settings.min_alert_tier,
                    choices=["ELITE", "BALANCED", "VOLUME"])
    ap.add_argument("--no-alerts", action="store_true")
    ap.add_argument("--no-news-filter", action="store_true")
    ap.add_argument("--discord-webhook", default=None)
    ap.add_argument("--telegram-token", default=None)
    ap.add_argument("--telegram-chat", default=None)
    args = ap.parse_args()

    scanner = LiveScanner(
        symbols_h1=settings.assets_h1, symbols_d1=settings.assets_d1,
        tier=args.tier, refresh_data=True,
    )
    # News calendar
    news_cal = None
    if not args.no_news_filter:
        try:
            news_cal = NewsCalendar(
                skip_minutes_before=settings.skip_news_minutes_before,
                skip_minutes_after=settings.skip_news_minutes_after,
                min_impact=settings.skip_news_impact.capitalize(),
            )
            news_cal.refresh()
            print(f"  News filter: ON ({settings.skip_news_impact} impact)")
        except Exception as e:
            print(f"  News filter: DISABLED ({e})")
            news_cal = None

    if args.no_alerts:
        alerter = None
    else:
        alerter = Alerter(
            discord_webhook=args.discord_webhook,
            telegram_bot_token=args.telegram_token,
            telegram_chat_id=args.telegram_chat,
            min_tier=args.min_alert_tier,
        )
        alert_status = "Discord" if alerter.discord else "none"
        alert_status2 = "Telegram" if alerter.tg_token else "none"
        print(f"  Alerts: Discord={alert_status} Telegram={alert_status2}")

    print(f"\n{'═' * 76}")
    print(f"  LIVE DAEMON — scanning every {args.interval} min")
    print(f"  Tier: {args.tier.upper()} | Min alert tier: {args.min_alert_tier}")
    print(f"{'═' * 76}")

    while True:
        start = time.time()
        try:
            print(f"\n─── {datetime.utcnow():%Y-%m-%d %H:%M:%S UTC} ───")
            signals = scanner.scan_once()

            # Filter news windows
            if news_cal is not None:
                before = len(signals)
                signals = [
                    s for s in signals
                    if not news_cal.is_in_news_window(
                        datetime.fromisoformat(s.timestamp_scan),
                        currencies_for(s.symbol),
                    )
                ]
                skipped = before - len(signals)
                if skipped > 0:
                    print(f"  ⏭ {skipped} signal(s) skipped (news window)")

            print_signals(signals)

            # Save
            out = save_signals_json(signals)
            print(f"  💾 {out.name}")

            # Alert new
            if alerter:
                n_new = alerter.alert_new(signals)
                if n_new > 0:
                    print(f"  🔔 {n_new} new alert(s) sent")
                else:
                    print(f"  (no new alerts)")

            # Desktop notifications
            if settings.desktop_notifications and signals:
                for s in signals[:3]:                  # max 3 desktop notif par scan
                    notify_signal(s)

        except Exception as e:
            print(f"  ✗ Scan error: {type(e).__name__}: {e}")

        elapsed = time.time() - start
        sleep_for = max(60, args.interval * 60 - elapsed)
        print(f"\n  ⏳ Next scan in {int(sleep_for)}s (Ctrl+C to quit)")
        try:
            time.sleep(sleep_for)
        except KeyboardInterrupt:
            print("\n  Stopped.")
            break


if __name__ == "__main__":
    main()
