"""
ICT CYBORG — daemon ULTIME avec toutes les phases branchées.

Enhancements actifs :
- Cross-asset filter (DXY, SPX, VIX)
- Multi-TF strict (W/D/H4/H1)
- Dynamic exit selon régime
- Ladder entries
- MT5 executor ready (dry-run par défaut)
- Telegram bot interactif
- News skip auto
- Auto-journal

Lance :  python3 run_cyborg.py
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

import pandas as pd

from src.utils.user_settings import UserSettings, apply_env
from src.utils.logging_conf import get_logger
from src.utils.types import Timeframe, Side, Regime
from src.telegram_bot import TelegramBot
from src.live_scanner import LiveScanner
from src.live_scanner.cyborg_enhancer import CyborgEnhancer
from src.news_calendar import NewsCalendar, currencies_for
from src.data_engine import DataLoader
from src.feature_engine import FeatureEngine
from src.regime_engine import RegimeDetector
from src.mt5_execution import MT5Executor

log = get_logger(__name__)


SCAN_INTERVAL_MIN = 15
MIN_GRADE = "A+"       # SNIPER MODE — uniquement A+ et S


def _get_htf_dfs(symbol: str, ltf: Timeframe):
    """Charge weekly/daily/h4/h1 dfs pour un symbol."""
    loader = DataLoader()
    try:
        df_d = loader.load(symbol, Timeframe.D1)
    except Exception:
        return None, None, None, None

    try:
        df_ltf = loader.load(symbol, ltf) if ltf != Timeframe.D1 else df_d
    except Exception:
        df_ltf = df_d

    df_w = df_d.resample("1W").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()

    if ltf.minutes < 240:
        df_h4 = df_ltf.resample("4h").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()
    else:
        df_h4 = df_d

    df_h1 = df_ltf if ltf == Timeframe.H1 else df_h4
    return df_w, df_d, df_h4, df_h1


def run():
    apply_env()
    settings = UserSettings.load()
    bot = TelegramBot()
    enhancer = CyborgEnhancer(cross_min_score=0.4, multi_tf_min_score=0.55)
    regime_detector = RegimeDetector()
    fe = FeatureEngine()
    mt5_exec = MT5Executor()         # dry-run par défaut

    if not bot.enabled:
        log.error("Telegram not configured. Check user_data/.env")
        return

    # Start bot polling
    Thread(target=bot.poll_updates, daemon=True).start()
    log.info("Telegram bot polling started")

    # Welcome
    bot.send_text(
        "🔴 *ICT CYBORG FULL MODE*\n\n"
        f"✅ Cross-asset filter\n"
        f"✅ Multi-TF strict (W/D/H4/H1)\n"
        f"✅ Dynamic exit selon régime\n"
        f"✅ Ladder entries (3 niveaux)\n"
        f"✅ MT5 executor (dry-run)\n"
        f"✅ News skip auto\n\n"
        f"Grade min alerte : *{MIN_GRADE}*\n"
        f"Scan : {SCAN_INTERVAL_MIN} min\n"
        f"Assets : {len(settings.assets_h1)} H1 + {len(settings.assets_d1)} D1"
    )

    # Scanner setup
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
    loader = DataLoader()
    GRADE_RANK = {"S": 5, "A+": 4, "A": 3, "B": 2, "Skip": 0}
    min_rank = GRADE_RANK.get(MIN_GRADE, 3)

    while True:
        start = time.time()
        try:
            log.info(f"────── Cyborg scan @ {datetime.utcnow():%H:%M:%S} ──────")
            raw_signals = scanner.scan_once()

            # Apply CYBORG enhancements
            enhanced_signals = []
            for sig in raw_signals:
                # Load HTF dataframes
                ltf = Timeframe(sig.ltf)
                df_w, df_d, df_h4, df_h1 = _get_htf_dfs(sig.symbol, ltf)
                if df_w is None or len(df_w) < 10:
                    continue

                # Load features + regime
                try:
                    df_ltf = fe.compute(loader.load(sig.symbol, ltf))
                except Exception:
                    continue
                regime_state = regime_detector.detect(df_ltf.tail(500))
                atr = float(df_ltf["atr_14"].iloc[-1]) if "atr_14" in df_ltf.columns else 0

                if regime_state.regime == Regime.MANIPULATION:
                    log.info(f"🚫 {sig.symbol}: régime MANIPULATION, skip")
                    continue

                # Enhance
                enh = enhancer.enhance(
                    sig, df_w, df_d, df_h4, df_h1,
                    regime=regime_state.regime, atr=atr,
                )
                if enh is None:
                    continue

                # Grade filter
                if GRADE_RANK.get(enh.cyborg_grade, 0) < min_rank:
                    continue

                # News skip
                ts = datetime.fromisoformat(sig.timestamp_scan)
                if news_cal.is_in_news_window(ts, currencies_for(sig.symbol)):
                    log.info(f"⏭ {sig.symbol}: news window skip")
                    continue

                enhanced_signals.append(enh)

            # Send NEW signals
            new_count = 0
            for enh in enhanced_signals:
                sig = enh.base
                sig_id = f"{sig.symbol}_{sig.ltf}_{sig.fvg_age_bars}_{int(sig.entry * 1000)}"
                if sig_id in alerted_ids:
                    continue
                alerted_ids.add(sig_id)
                if len(alerted_ids) > 500:
                    alerted_ids = set(list(alerted_ids)[-300:])

                bot.send_signal_with_buttons(sig, enhanced=enh)
                new_count += 1
                log.info(
                    f"📨 Sent {enh.cyborg_grade}: {sig.symbol} {sig.ltf} {sig.side} "
                    f"P={enh.final_probability:.0%} cross={enh.cross_asset.score if enh.cross_asset else 'n/a'}"
                )

            log.info(f"  Raw: {len(raw_signals)} → Enhanced: {len(enhanced_signals)} → New: {new_count}")

        except Exception as e:
            log.error(f"Cyborg scan error: {type(e).__name__}: {e}", exc_info=True)

        elapsed = time.time() - start
        sleep_for = max(60, SCAN_INTERVAL_MIN * 60 - elapsed)
        log.info(f"Next scan in {int(sleep_for)}s")
        time.sleep(sleep_for)


if __name__ == "__main__":
    run()
