"""
ICT CYBORG FULL AUTO — auto-execution MT5 live sur signaux A+.

Combine :
- Phase 1/2/3 Ultimate (confluence, dynamic risk, pyramid, ML regime)
- AutoExecutor : place les ordres MT5 automatiquement
- PositionManager : gère les exits multi-partials live (thread séparé)
- Telegram commands : /pause /resume /auto_status /positions /close_all

Safety :
- Guards multiples (max positions, daily loss cap, lockouts)
- Can pause via Telegram /pause sans arrêter le daemon
- Rollback : basculer la Scheduled Task vers run_cyborg_ultimate.py ou run_cyborg.py

Prérequis :
- MT5 installé + terminal tournant sur AWS
- Credentials MT5 dans .env (MT5_LOGIN, MT5_PASSWORD, MT5_SERVER)
  OU dans user_data/mt5_accounts.json (premier compte enabled=true utilisé)
- settings.json : "auto_execute": true

Lance :  python3 run_cyborg_full_auto.py
"""
from __future__ import annotations

import sys
import os
import time
import json
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

# Phase 1/2/3 modules
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
    from src.pyramid_manager import PyramidManager
except Exception:
    PyramidManager = None

# Auto-execution modules
try:
    from src.auto_execution import AutoExecutor, AutoExecutionConfig, PositionManager
except Exception as e:
    AutoExecutor = None
    AutoExecutionConfig = None
    PositionManager = None

try:
    from src.utils.tz_display import now_paris, paris_time_short, format_paris
except Exception:
    def paris_time_short(dt=None): return datetime.utcnow().strftime("%H:%M")
    def format_paris(dt=None, fmt="%d/%m/%Y %H:%M:%S"): return datetime.utcnow().strftime(fmt)

# Safety net modules (P1 enhancements)
try:
    from src.ftmo_guards import ConsistencyTracker
except Exception:
    ConsistencyTracker = None

try:
    from src.alerts_backup import EmailAlerter
    from src.alerts_backup.multi_channel_alerter import MultiChannelAlerter
except Exception:
    EmailAlerter = None
    MultiChannelAlerter = None


log = get_logger(__name__)


SCAN_INTERVAL_MIN = 15
MIN_GRADE = "B"  # Accept B/A/A+/S (all non-Skip). Was "A+" - too strict, caused 0 trades.
                  # ML classifier (threshold 0.45) remains primary quality gate upstream.


def _load_settings_dict() -> dict:
    try:
        path = Path(__file__).parent / "user_data" / "settings.json"
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_mt5_creds_from_accounts() -> dict:
    """Charge creds MT5 depuis mt5_accounts.json (premier account enabled)."""
    try:
        path = Path(__file__).parent / "user_data" / "mt5_accounts.json"
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for acc in data.get("accounts", []):
            if acc.get("enabled") and acc.get("login", 0) > 0:
                return {
                    "MT5_LOGIN": str(acc["login"]),
                    "MT5_PASSWORD": acc.get("password", ""),
                    "MT5_SERVER": acc.get("server", ""),
                    "initial_balance": float(acc.get("balance", 10000)),
                    "risk_per_trade_pct": float(acc.get("risk_per_trade_pct", 0.5)),
                }
    except Exception as e:
        log.warning(f"Failed to load MT5 creds from accounts: {e}")
    return {}


def _init_modules(settings_dict: dict) -> dict:
    modules = {}

    if settings_dict.get("use_multi_partial_exits", False) and ExitManager:
        try:
            modules["exit_manager"] = ExitManager(
                partial_levels=settings_dict.get("partial_exit_levels"),
                runner_trailing_atr_mult=settings_dict.get("runner_trailing_atr_mult", 2.0),
                runner_target_min_r=settings_dict.get("runner_target_min_r", 5.0),
            )
            log.info("[OK] ExitManager active")
        except Exception as e:
            log.error(f"ExitManager init failed: {e}")

    if settings_dict.get("use_confluence_filter", False) and ConfluenceFilter:
        try:
            modules["confluence_filter"] = ConfluenceFilter(
                min_score=settings_dict.get("confluence_min_score", 3),
                require_smt=settings_dict.get("confluence_require_smt", True),
                require_multi_tf=settings_dict.get("confluence_require_multi_tf", True),
            )
            log.info("[OK] ConfluenceFilter active")
        except Exception as e:
            log.error(f"ConfluenceFilter init failed: {e}")

    if settings_dict.get("use_dynamic_risk", False) and DynamicRiskManager:
        try:
            modules["dynamic_risk"] = DynamicRiskManager(
                base_risk=settings_dict.get("dynamic_risk_base", 0.5),
                max_risk=settings_dict.get("dynamic_risk_max", 1.0),
                min_risk=settings_dict.get("dynamic_risk_min", 0.25),
                hot_streak_boost=settings_dict.get("dynamic_risk_hot_streak_boost", 0.2),
                cold_streak_penalty=settings_dict.get("dynamic_risk_cold_streak_penalty", 0.25),
            )
            log.info("[OK] DynamicRiskManager active")
        except Exception as e:
            log.error(f"DynamicRiskManager init failed: {e}")

    if settings_dict.get("use_pyramid", False) and PyramidManager:
        try:
            modules["pyramid"] = PyramidManager(
                max_adds=settings_dict.get("pyramid_max_adds", 2),
                add_at_r=settings_dict.get("pyramid_add_at_r", 1.0),
                add_risk_pct=settings_dict.get("pyramid_add_risk_pct", 0.3),
            )
            log.info("[OK] PyramidManager active")
        except Exception as e:
            log.error(f"PyramidManager init failed: {e}")

    return modules


def _init_auto_executor(settings_dict: dict, telegram_bot) -> tuple:
    """Init AutoExecutor + PositionManager si activé."""
    if not settings_dict.get("auto_execute", False):
        log.warning("auto_execute=false — running in SIGNAL-ONLY mode (no MT5 orders)")
        return None, None

    if AutoExecutor is None:
        log.error("auto_execution module not available")
        return None, None

    # Charge credentials MT5
    creds = _load_mt5_creds_from_accounts()
    if creds:
        os.environ["MT5_LOGIN"] = creds.get("MT5_LOGIN", "")
        os.environ["MT5_PASSWORD"] = creds.get("MT5_PASSWORD", "")
        os.environ["MT5_SERVER"] = creds.get("MT5_SERVER", "")
        initial_balance = creds.get("initial_balance", 10000)
    else:
        initial_balance = settings_dict.get("account_balance", 10000)

    # Build AutoExecutor config
    auto_config = AutoExecutionConfig(
        enabled=settings_dict.get("auto_execute", True),
        max_concurrent_positions=settings_dict.get("auto_max_concurrent_positions", 5),
        max_positions_per_symbol=settings_dict.get("auto_max_positions_per_symbol", 1),
        daily_loss_cap_pct=settings_dict.get("auto_daily_loss_cap_pct", 3.5),
        min_account_balance_pct=settings_dict.get("auto_min_balance_pct", 90.0),
        allow_weekends=settings_dict.get("auto_allow_weekends", False),
        default_comment="ICT Cyborg AUTO",
        initial_balance=initial_balance,
    )

    # Init MT5Executor (will try to connect)
    mt5_exec = MT5Executor()

    try:
        auto_exec = AutoExecutor(config=auto_config, mt5_executor=mt5_exec)
    except Exception as e:
        log.error(f"AutoExecutor init failed: {e}")
        return None, None

    # Init PositionManager
    try:
        pos_mgr = PositionManager(
            mt5_executor=mt5_exec,
            exit_manager=ExitManager(
                partial_levels=settings_dict.get("partial_exit_levels"),
            ) if ExitManager else None,
            check_interval_seconds=settings_dict.get("position_check_interval", 60),
            telegram_bot=telegram_bot,
        )
        pos_mgr.start()
        log.info("[OK] PositionManager thread started")
    except Exception as e:
        log.error(f"PositionManager init failed: {e}")
        pos_mgr = None

    # Link telegram bot to auto_executor for /pause /resume commands
    if telegram_bot is not None:
        setattr(telegram_bot, "auto_executor", auto_exec)
        setattr(telegram_bot, "position_manager", pos_mgr)
        log.info("[OK] Telegram bot linked to AutoExecutor")

    status = "DRY-RUN" if mt5_exec.dry_run else "LIVE"
    log.warning(f"AutoExecutor initialized in {status} mode")
    return auto_exec, pos_mgr


def _get_htf_dfs(symbol: str, ltf: Timeframe):
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
    # Seuils assouplis pour permettre aux signaux de passer en prod.
    # Cross-asset filter retourne souvent score=0.00 (bug ou marché sans
    # confirmation) -> mettre à 0.0 désactive effectivement ce filtre.
    # Multi-TF min 0.3 (au lieu de 0.55) = plus permissif sur alignement HTF.
    # L'ML classifier (threshold 0.45) reste la couche de filtrage principale.
    enhancer = CyborgEnhancer(cross_min_score=0.0, multi_tf_min_score=0.3)
    regime_detector = RegimeDetector()
    fe = FeatureEngine()

    if not bot.enabled:
        log.error("Telegram not configured. Check user_data/.env")
        return

    # Init Phase 1/2/3 modules
    modules = _init_modules(settings_dict)

    # Init safety nets (P1 enhancements)
    consistency = None
    if ConsistencyTracker is not None and settings_dict.get("use_consistency_tracker", True):
        try:
            consistency = ConsistencyTracker(
                threshold_pct=settings_dict.get("consistency_threshold_pct", 45.0)
            )
            log.info("[OK] ConsistencyTracker active")
        except Exception as e:
            log.error(f"ConsistencyTracker init failed: {e}")

    email_alerter = None
    multi_alerter = None
    if EmailAlerter is not None:
        try:
            email_alerter = EmailAlerter()
            multi_alerter = MultiChannelAlerter(telegram_bot=bot, email_alerter=email_alerter)
            if email_alerter.enabled:
                log.info("[OK] EmailAlerter active (fallback SMTP)")
            else:
                log.info("[INFO] EmailAlerter disabled (no SMTP creds in .env)")
        except Exception as e:
            log.error(f"EmailAlerter init failed: {e}")

    # Init auto-executor + position manager
    auto_exec, pos_mgr = _init_auto_executor(settings_dict, bot)

    # Start bot polling (after auto_executor linked)
    Thread(target=bot.poll_updates, daemon=True).start()
    log.info("Telegram bot polling started")

    # Welcome message
    auto_status = "OFF (signal-only)"
    if auto_exec is not None:
        auto_status = "LIVE" if not auto_exec.mt5.dry_run else "DRY-RUN (no MT5)"
    active_modules = ", ".join(modules.keys()) if modules else "base only"
    bot.send_text(
        "🔴 *ICT CYBORG FULL AUTO*\n\n"
        f"*AUTO-EXECUTION* : {auto_status}\n"
        f"*Phases* : {active_modules}\n"
        f"*Instruments* : {len(settings.assets_h1) + len(settings.assets_d1)} "
        f"(H1+D1)\n"
        f"*Grade min* : {MIN_GRADE}\n"
        f"*Scan* : {SCAN_INTERVAL_MIN} min\n"
        f"*Demarrage* : {format_paris()} Paris\n"
        f"*Trading days* : Lundi-Vendredi (fuseau Paris)\n\n"
        "*Commandes* :\n"
        "• /auto\\_status - etat auto-exec\n"
        "• /pause - pause ordres auto\n"
        "• /resume - reprise\n"
        "• /positions - positions ouvertes\n"
        "• /close\\_all - URGENCE fermer tout"
    )

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
            # Weekend guard : ferme les positions vendredi 16h UTC
            if auto_exec is not None and settings_dict.get("auto_close_before_weekend", True):
                cutoff = settings_dict.get("auto_friday_close_hour_utc", 16)
                try:
                    closed = auto_exec.close_all_before_weekend(cutoff_hour_utc=cutoff)
                    if closed > 0:
                        bot.send_text(f"🗓 *Weekend guard*\n{closed} positions fermees avant weekend")
                        if multi_alerter:
                            multi_alerter.send_warn("Weekend close",
                                f"{closed} positions closed before weekend cutoff ({cutoff}h UTC)")
                except Exception as wg_e:
                    log.error(f"Weekend guard error: {wg_e}")

            # Consistency check FTMO
            if consistency:
                status = consistency.get_status()
                if not status.allowed:
                    log.warning(f"[FTMO CONSISTENCY] {status.reason}")

            log.info(f"====== Full Auto scan @ {format_paris()} Paris (= {datetime.utcnow():%H:%M:%S} UTC) ======")
            raw_signals = scanner.scan_once()

            enhanced_signals = []
            for sig in raw_signals:
                try:
                    ltf = Timeframe(sig.ltf)
                    df_w, df_d, df_h4, df_h1 = _get_htf_dfs(sig.symbol, ltf)
                    if df_w is None or len(df_w) < 10:
                        log.info(f"[FILTER-HTF] {sig.symbol}: weekly data missing (rows={len(df_w) if df_w is not None else 0})")
                        continue

                    try:
                        df_ltf = fe.compute(loader.load(sig.symbol, ltf))
                    except Exception as fe_e:
                        log.info(f"[FILTER-FEATURES] {sig.symbol}: feature compute failed ({fe_e})")
                        continue
                    regime_state = regime_detector.detect(df_ltf.tail(500))
                    atr = float(df_ltf["atr_14"].iloc[-1]) if "atr_14" in df_ltf.columns else 0

                    if regime_state.regime == Regime.MANIPULATION:
                        log.info(f"[SKIP] {sig.symbol}: MANIPULATION regime")
                        continue

                    enh = enhancer.enhance(
                        sig, df_w, df_d, df_h4, df_h1,
                        regime=regime_state.regime, atr=atr,
                    )
                    if enh is None:
                        log.info(f"[FILTER-ENHANCE] {sig.symbol} {sig.side}: enhance() returned None (cross/multi_tf/grade filter)")
                        continue

                    if GRADE_RANK.get(enh.cyborg_grade, 0) < min_rank:
                        log.info(f"[FILTER-GRADE] {sig.symbol} {sig.side}: grade={enh.cyborg_grade} below min={MIN_GRADE}")
                        continue

                    if confluence_filter:
                        conf_result = confluence_filter.evaluate_from_signal(enh)
                        if not conf_result.pass_filter:
                            log.info(f"[SKIP] {sig.symbol}: confluence — {conf_result.reason}")
                            continue
                        setattr(enh, "confluence_score", conf_result.total_score)

                    ts = datetime.fromisoformat(sig.timestamp_scan)
                    if news_cal.is_in_news_window(ts, currencies_for(sig.symbol)):
                        log.info(f"[SKIP] {sig.symbol}: news window")
                        continue

                    setattr(enh, "_atr", atr)
                    enhanced_signals.append(enh)
                except Exception as inner_e:
                    log.error(f"Signal process error {sig.symbol}: {inner_e}")

            new_count = 0
            auto_count = 0
            for enh in enhanced_signals:
                try:
                    sig = enh.base
                    sig_id = f"{sig.symbol}_{sig.ltf}_{sig.fvg_age_bars}_{int(sig.entry * 1000)}"
                    if sig_id in alerted_ids:
                        continue
                    alerted_ids.add(sig_id)
                    if len(alerted_ids) > 500:
                        alerted_ids = set(list(alerted_ids)[-300:])

                    # Dynamic risk
                    risk_pct = settings.risk_per_trade_pct
                    risk_reason = "base"
                    if dynamic_risk:
                        decision = dynamic_risk.decide()
                        if decision.allowed:
                            risk_pct = decision.risk_pct
                            risk_reason = decision.reason
                        else:
                            log.info(f"[LOCKOUT] {sig.symbol}: {decision.reason}")
                            continue
                    setattr(enh, "dynamic_risk_pct", risk_pct)

                    new_count += 1

                    # Consistency guard (FTMO)
                    if consistency:
                        c_status = consistency.get_status()
                        if not c_status.allowed:
                            log.warning(f"[CONSISTENCY BLOCK] {sig.symbol}: {c_status.reason}")
                            # Info only (no button since full auto blocked)
                            bot.send_text(
                                f"🚫 *SIGNAL {enh.cyborg_grade} BLOQUE*\n"
                                f"{sig.symbol} {sig.side.upper()}\n"
                                f"Raison: {c_status.reason}"
                            )
                            continue

                    # AUTO-EXECUTION (FULL AUTO - pas de boutons, exec direct)
                    if auto_exec is not None:
                        signal_dict = {
                            "symbol": sig.symbol,
                            "side": sig.side,
                            "entry": sig.entry,
                            "stop_loss": sig.stop_loss,
                            "take_profit": getattr(sig, "take_profit_1", sig.entry),
                        }
                        exec_result = auto_exec.execute_signal(
                            signal=signal_dict,
                            risk_pct=risk_pct,
                        )
                        if exec_result.success:
                            auto_count += 1
                            log.info(
                                f"[AUTO-EXEC] {sig.symbol} {sig.side} "
                                f"ticket={exec_result.ticket} @ {exec_result.entry}"
                            )
                            # Register in PositionManager
                            if pos_mgr and exec_result.ticket:
                                pos_mgr.register(
                                    ticket=exec_result.ticket,
                                    symbol=sig.symbol,
                                    side=sig.side,
                                    entry=exec_result.entry,
                                    sl=exec_result.sl,
                                    tp=exec_result.tp,
                                    lots=exec_result.lots,
                                    atr=getattr(enh, "_atr", 0),
                                )
                            # Telegram confirmation complete with grade + confluence
                            # -> Broadcast au canal (membres) ET chat admin via send_broadcast
                            # (fallback send_text si pas de channel configuré).
                            conf = getattr(enh, "confluence_score", "-")
                            filled_msg = (
                                f"✅ *AUTO-EXEC FILLED* - Grade {enh.cyborg_grade}\n"
                                f"{sig.symbol} {sig.side.upper()} "
                                f"{exec_result.lots}lot\n\n"
                                f"Entry : {exec_result.entry:.5f}\n"
                                f"SL : {exec_result.sl:.5f}\n"
                                f"TP : {exec_result.tp:.5f}\n"
                                f"Risk : {risk_pct:.2f}%\n"
                                f"Confluence : {conf}/7\n"
                                f"Killzone : {getattr(sig, 'killzone', '-')}\n\n"
                                f"Ticket MT5 : {exec_result.ticket}\n"
                                f"Le PositionManager gere les exits auto."
                            )
                            broadcast_fn = getattr(bot, "send_broadcast", bot.send_text)
                            broadcast_fn(filled_msg)
                        else:
                            # Exec skipped or failed - info (admin only, pas membres)
                            reason = exec_result.skipped_reason or exec_result.message
                            bot.send_text(
                                f"⏭ *SIGNAL {enh.cyborg_grade} SKIP*\n"
                                f"{sig.symbol} {sig.side.upper()}\n"
                                f"Raison: {reason}"
                            )
                    else:
                        # Fallback si auto_exec indispo (signal-only) -> canal
                        signal_only_msg = (
                            f"🔔 *SIGNAL {enh.cyborg_grade}* (signal-only)\n"
                            f"{sig.symbol} {sig.side.upper()}\n"
                            f"Entry: {sig.entry:.5f} | SL: {sig.stop_loss:.5f}"
                        )
                        broadcast_fn = getattr(bot, "send_broadcast", bot.send_text)
                        broadcast_fn(signal_only_msg)

                    log.info(
                        f"[SENT] {enh.cyborg_grade}: {sig.symbol} {sig.ltf} "
                        f"{sig.side} P={enh.final_probability:.0%} risk={risk_pct:.2f}%"
                    )
                except Exception as send_e:
                    log.error(f"Signal handling error: {send_e}")

            log.info(
                f"  Raw:{len(raw_signals)} Enh:{len(enhanced_signals)} "
                f"Sent:{new_count} AutoExec:{auto_count}"
            )

            if dynamic_risk:
                log.info(f"  {dynamic_risk.summary()}")
            if auto_exec:
                log.info(f"  {auto_exec.summary()}")

        except Exception as e:
            log.error(f"Scan error: {type(e).__name__}: {e}", exc_info=True)
            if multi_alerter:
                try:
                    multi_alerter.send_critical(
                        "Scan loop error",
                        f"{type(e).__name__}: {e}\n\nLe bot continue, mais verifier les logs AWS."
                    )
                except Exception:
                    pass

        elapsed = time.time() - start
        sleep_for = max(60, SCAN_INTERVAL_MIN * 60 - elapsed)
        log.info(f"Next scan in {int(sleep_for)}s")
        time.sleep(sleep_for)


if __name__ == "__main__":
    run()
