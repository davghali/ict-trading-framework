"""Tests unitaires — Safety Net P0/P1 enhancements."""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


# ============ CONSISTENCY TRACKER ============

def test_consistency_below_500usd():
    from src.ftmo_guards import ConsistencyTracker
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        ct = ConsistencyTracker(state_file=Path(f.name))
    ct.record_pnl(100)
    ct.record_pnl(150)
    status = ct.get_status()
    assert status.allowed  # below 500 = no enforcement


def test_consistency_ok_balanced():
    from src.ftmo_guards import ConsistencyTracker
    import tempfile, json
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    # Inject balanced state directly : 5 days x 300 each
    path.write_text(json.dumps({"daily_pnl": {
        f"2026-04-1{i}": 300.0 for i in range(1, 6)
    }}))
    ct = ConsistencyTracker(threshold_pct=45.0, state_file=path)
    status = ct.get_status()
    # Best 300/1500 = 20% < 45%
    assert status.allowed, f"Expected allowed, got {status.reason}"


def test_consistency_blocked_when_single_big_day():
    from src.ftmo_guards import ConsistencyTracker
    import tempfile, json
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    # Directly inject state: 1 big day
    path.write_text(json.dumps({"daily_pnl": {
        "2026-04-14": 900.0,
        "2026-04-15": 100.0,
        "2026-04-16": 50.0,
    }}))
    ct = ConsistencyTracker(threshold_pct=45.0, state_file=path)
    status = ct.get_status()
    # 900/1050 = 85.7% > 45% → blocked
    assert not status.allowed
    assert status.best_day_pct_of_total > 45


# ============ AUTO EXECUTOR — NEW FEATURES ============

def test_compute_lots_from_mt5_fallback_when_no_mt5():
    from src.auto_execution import AutoExecutor, AutoExecutionConfig
    auto = AutoExecutor(config=AutoExecutionConfig())
    # No MT5 → falls back to simplified formula
    lots = auto.compute_lots_from_mt5(10000, 0.5, 2400, 2395, "XAUUSD")
    assert lots >= 0.0


def test_close_all_before_weekend_not_friday():
    from src.auto_execution import AutoExecutor, AutoExecutionConfig
    auto = AutoExecutor(config=AutoExecutionConfig())
    # Tuesday
    tue = datetime(2026, 4, 21, 16, 0, tzinfo=timezone.utc)
    with patch("src.auto_execution.auto_executor.datetime") as mock_dt:
        mock_dt.now.return_value = tue
        closed = auto.close_all_before_weekend(cutoff_hour_utc=16)
        assert closed == 0


def test_close_all_before_weekend_friday_before_cutoff():
    from src.auto_execution import AutoExecutor, AutoExecutionConfig
    auto = AutoExecutor(config=AutoExecutionConfig())
    # Friday 14h UTC, cutoff 16h
    fri_early = datetime(2026, 4, 17, 14, 0, tzinfo=timezone.utc)
    with patch("src.auto_execution.auto_executor.datetime") as mock_dt:
        mock_dt.now.return_value = fri_early
        closed = auto.close_all_before_weekend(cutoff_hour_utc=16)
        assert closed == 0  # Too early


# ============ POSITION MANAGER STATE PERSISTENCE ============

def test_position_manager_state_save_load():
    from src.auto_execution import PositionManager
    from src.mt5_execution import MT5Executor
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        state_file = Path(f.name)

    mt5 = MT5Executor()
    pm1 = PositionManager(mt5_executor=mt5, state_file=state_file)
    pm1.register(ticket=12345, symbol="XAUUSD", side="long",
                  entry=2400.0, sl=2395.0, tp=2410.0, lots=0.5, atr=3.0)
    pm1.register(ticket=67890, symbol="EURUSD", side="short",
                  entry=1.1000, sl=1.1050, tp=1.0900, lots=0.1)

    # Create fresh manager : should auto-load
    pm2 = PositionManager(mt5_executor=mt5, state_file=state_file)
    assert 12345 in pm2.managed
    assert 67890 in pm2.managed
    assert pm2.managed[12345].symbol == "XAUUSD"
    assert pm2.managed[67890].side == "short"


# ============ EMAIL ALERTER ============

def test_email_alerter_disabled_without_creds():
    from src.alerts_backup import EmailAlerter
    import os
    # Remove creds if set in environment
    for k in ("SMTP_USER", "SMTP_PASSWORD"):
        os.environ.pop(k, None)
    alerter = EmailAlerter(smtp_user="", smtp_password="")
    assert not alerter.enabled
    # send returns False when disabled
    assert alerter.send("Test", "Body") == False


def test_email_alerter_default_recipient():
    from src.alerts_backup import EmailAlerter
    alerter = EmailAlerter()
    assert alerter.email_to == "ghalidavid5@gmail.com"


def test_multi_channel_fallback():
    from src.alerts_backup.multi_channel_alerter import MultiChannelAlerter
    # No telegram → should fallback to email (but email also disabled here)
    # Just verify no crash
    alerter = MultiChannelAlerter(telegram_bot=None)
    try:
        alerter.send_warn("Subject", "Body")
        alerter.send_info("Subject", "Body")
        alerter.send_critical("Subject", "Body")
    except Exception as e:
        pytest.fail(f"Should not raise: {e}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
