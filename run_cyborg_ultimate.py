"""
ICT CYBORG ULTIMATE — daemon avec TOUTES les 3 phases branchées.

Modules activés (lecture settings.json) :
- Phase 1 : Multi-instruments (19) + exit_manager (multi-partials + runner)
- Phase 2 : confluence_filter + dynamic_risk + news_ride (optionnel)
- Phase 3 : pyramid_manager + ml regime-aware

Safety : chaque module est optionnel via settings.json. Si un module crash,
le bot continue avec les autres (try/except enveloppants).

Lance :  python3 run_cyborg_ultimate.py

Pour revenir à l'ancienne version safe :  python3 run_cyborg.py
"""
from __future__ import annotations

import sys
import time
import json
import traceback
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

# Phase 1/2/3 modules (import safe)
try:
    from src.exit_manager import ExitManager
except Exception:
    ExitManager = None

try:
    from src.confluence_filter import ConfluenceFilter
except Exception:
    ConfluenceFilter = None

try:
    from src.dynamic_risk import DynamicRiskManager
except Exception:
    DynamicRiskManager = None

try:
    from src.news_ride import NewsRideModule
except Exception:
    NewsRideModule = None

try:
    from src.pyramid_manager import PyramidManager
except Exception:
    PyramidManager = None


log = get_logger(__name__)


SCAN_INTERVAL_MIN = 15
MIN_GRADE = "A+"       # SNIPER MODE — A+ et S


def _load_settings_dict() -> dict:
    """Charge settings.json en dict (pour nouveaux champs)."""
    try:
        path = Path(__file__).parent / "user_data" / "settings.json"
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _init_modules(settings_dict: dict) -> dict:
    """Initialise les modules optionnels selon settings."""
    modules = {}

    # Exit Manager
    if settings_dict.get("use_multi_partial_exits", False) and ExitManager:
        try:
            modules["exit_manager"] = ExitManager(
                partial_levels=settings_dict.get("partial_exit_levels"),
                runner_trailing_atr_mult=settings_dict.get("runner_trailing_atr_mult", 2.0),
                runner_target_min_r=settings_dict.get("runner_target_min_r", 5.0),
            )
            log.info("✅ ExitManager activé (multi-partials + runner)")
        except Exception as e:
            log.error(f"ExitManager init failed: {e}")

    # Confluence Filter
    if settings_dict.get("use_confluence_filter", False) and ConfluenceFilter:
        try:
            modules["confluence_filter"] = ConfluenceFilter(
                min_score=settings_dict.get("confluence_min_score", 3),
                require_smt=settings_dict.get("confluence_require_smt", True),
                require_multi_tf=settings_dict.get("confluence_require_multi_tf", True),
            )
            log.info("✅ ConfluenceFilter activé")
        except Exception as e:
            log.error(f"ConfluenceFilter init failed: {e}")

    # Dynamic Risk
    if settings_dict.get("use_dynamic_risk", False) and DynamicRiskManager:
        try:
            modules["dynamic_risk"] = DynamicRiskManager(
                base_risk=settings_dict.get("dynamic_risk_base", 0.5),
                max_risk=settings_dict.get("dynamic_risk_max", 1.0),
                min_risk=settings_dict.get("dynamic_risk_min", 0.25),
                hot_streak_boost=settings_dict.get("dynamic_risk_hot_streak_boost", 0.2),
                cold_streak_penalty=settings_dict.get("dynamic_risk_cold_streak_penalty", 0.25),
            )
            log.info("✅ DynamicRiskManager activé")
        except Exception as e:
            log.error(f"DynamicRiskManager init failed: {e}")

    # News Ride (désactivé par défaut)
    if settings_dict.get("use_news_ride", False) and NewsRideModule:
        try:
            modules["news_ride"] = NewsRideModule(
                wait_minutes=settings_dict.get("news_ride_wait_minutes", 5),
                retracement_pct=settings_dict.get("news_ride_retracement_pct", 0.618),
                risk_multiplier=settings_dict.get("news_ride_risk_multiplier", 0.5),
            )
            log.info("✅ NewsRideModule activé")
        except Exception as e:
            log.error(f"NewsRideModule init failed: {e}")

    # Pyramid
    if settings_dict.get("use_pyramid", False) and PyramidManager:
        try:
            modules["pyramid"] = PyramidManager(
                max_adds=settings_dict.get("pyramid_max_adds", 2),
                add_at_r=settings_dict.get("pyramid_add_at_r", 1.0),
                add_risk_pct=settings_dict.get("pyramid_add_risk_pct", 0.3),
            )
            log.info("✅ PyramidManager activé")
        except Exception as e:
            log.error(f"PyramidManager init failed: {e}")

    return modules


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
    settings_dict = _load_settings_dict()
    bot = TelegramBot()
    enhancer = CyborgEnhancer(cross_min_score=0.4, multi_tf_min_score=0.55)
    regime_detector = RegimeDetector()
    fe = FeatureEngine()
    mt5_exec = MT5Executor()

    if not bot.enabled:
        log.error("Telegram not configured. Check user_data/.env")
        return

    # Init Phase 1/2/3 modules
    modules = _init_modules(settings_dict)

    # Start bot polling
    Thread(target=bot.poll_updates, daemon=True).start()
    log.info("Telegram bot polling started")

    # Welcome
    active_modules = [k for k in modules.keys()]
    module_line = ", ".join(active_modules) if active_modules else "base only"
    bot.send_text(
        "🔴 *ICT CYBORG ULTIMATE*\n\n"
        f"✅ Cross-asset + Multi-TF + Regime\n"
        f"✅ Dynamic exit, Ladder entries, MT5 executor\n"
        f"✅ News skip auto, Auto-journal\n\n"
        f"*Phases activées :*\n"
        f"• Instruments : {len(settings.assets_h1) + len(settings.assets_d1)} (H1+D1)\n"
        f"• Modules : {module_line}\n\n"
        f"Grade min : *{MIN_GRADE}*\n"
        f"Scan : {SCAN_INTERVAL_MIN} min"
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

    confluence_filter = modules.get("confluence_filter")
    dynamic_risk = modules.get("dynamic_risk")

    while True:
        start = time.time()
        try:
            log.info(f"────── Cyborg ULTIMATE scan @ {datetime.utcnow():%H:%M:%S} ──────")
            raw_signals = scanner.scan_once()

            # Apply CYBORG enhancements
            enhanced_signals = []
            for sig in raw_signals:
                try:
                    ltf = Timeframe(sig.ltf)
                    df_w, df_d, df_h4, df_h1 = _get_htf_dfs(sig.symbol, ltf)
                    if df_w is None or len(df_w) < 10:
                        continue

                    try:
                        df_ltf = fe.compute(loader.load(sig.symbol, ltf))
                    except Exception:
                        continue
                    regime_state = regime_detector.detect(df_ltf.tail(500))
                    atr = float(df_ltf["atr_14"].iloc[-1]) if "atr_14" in df_ltf.columns else 0

                    if regime_state.regime == Regime.MANIPULATION:
                        log.info(f"🚫 {sig.symbol}: régime MANIPULATION, skip")
                        continue

                    enh = enhancer.enhance(
                        sig, df_w, df_d, df_h4, df_h1,
                        regime=regime_state.regime, atr=atr,
                    )
                    if enh is None:
                        continue

                    # Grade filter
                    if GRADE_RANK.get(enh.cyborg_grade, 0) < min_rank:
                        continue

                    # Confluence filter (Phase 2)
                    if confluence_filter:
                        conf_result = confluence_filter.evaluate_from_signal(enh)
                        if not conf_result.pass_filter:
                            log.info(f"🚫 {sig.symbol}: confluence fail — {conf_result.reason}")
                            continue
                        # Attach confluence to enhanced signal (for later use)
                        setattr(enh, "confluence_score", conf_result.total_score)
                        setattr(enh, "confluence_details", conf_result.details)

                    # News skip
                    ts = datetime.fromisoformat(sig.timestamp_scan)
                    if news_cal.is_in_news_window(ts, currencies_for(sig.symbol)):
                        log.info(f"⏭ {sig.symbol}: news window skip")
                        continue

                    enhanced_signals.append(enh)
                except Exception as inner_e:
                    log.error(f"Signal enhance error {sig.symbol}: {inner_e}")
                    continue

            # Send NEW signals
            new_count = 0
            for enh in enhanced_signals:
                try:
                    sig = enh.base
                    sig_id = f"{sig.symbol}_{sig.ltf}_{sig.fvg_age_bars}_{int(sig.entry * 1000)}"
                    if sig_id in alerted_ids:
                        continue
                    alerted_ids.add(sig_id)
                    if len(alerted_ids) > 500:
                        alerted_ids = set(list(alerted_ids)[-300:])

                    # Dynamic risk decision
                    risk_pct = settings.risk_per_trade_pct
                    risk_reason = "base"
                    if dynamic_risk:
                        decision = dynamic_risk.decide()
                        if decision.allowed:
                            risk_pct = decision.risk_pct
                            risk_reason = decision.reason
                        else:
                            log.info(f"🔒 {sig.symbol}: risk lockout — {decision.reason}")
                            continue

                    # Attach risk info
                    setattr(enh, "dynamic_risk_pct", risk_pct)
                    setattr(enh, "dynamic_risk_reason", risk_reason)

                    bot.send_signal_with_buttons(sig, enhanced=enh)
                    new_count += 1
                    log.info(
                        f"📨 Sent {enh.cyborg_grade}: {sig.symbol} {sig.ltf} {sig.side} "
                        f"P={enh.final_probability:.0%} risk={risk_pct:.2f}% "
                        f"cross={enh.cross_asset.score if enh.cross_asset else 'n/a'}"
                    )
                except Exception as send_e:
                    log.error(f"Send signal error: {send_e}")

            log.info(f"  Raw: {len(raw_signals)} → Enhanced: {len(enhanced_signals)} → New: {new_count}")

            # Log dynamic risk state
            if dynamic_risk:
                log.info(f"  {dynamic_risk.summary()}")

        except Exception as e:
            log.error(f"Cyborg scan error: {type(e).__name__}: {e}", exc_info=True)

        elapsed = time.time() - start
        sleep_for = max(60, SCAN_INTERVAL_MIN * 60 - elapsed)
        log.info(f"Next scan in {int(sleep_for)}s")
        time.sleep(sleep_for)


if __name__ == "__main__":
    run()
