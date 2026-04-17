"""Tests unitaires auto-execution + filtres trading days."""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


def test_auto_executor_init():
    from src.auto_execution import AutoExecutor, AutoExecutionConfig
    cfg = AutoExecutionConfig(enabled=True)
    auto = AutoExecutor(config=cfg)
    assert auto.is_paused == False
    assert auto.config.trading_days_utc == (0, 1, 2, 3, 4)


def test_auto_executor_pause_resume():
    from src.auto_execution import AutoExecutor, AutoExecutionConfig
    auto = AutoExecutor(config=AutoExecutionConfig())
    auto.pause(reason="test")
    assert auto.is_paused
    auto.resume()
    assert not auto.is_paused


def test_compute_lots_xauusd():
    from src.auto_execution import AutoExecutor
    lots = AutoExecutor.compute_lots(
        account_balance=10000, risk_pct=0.5,
        entry=2400, stop_loss=2395, symbol='XAUUSD',
    )
    assert 0.01 <= lots <= 10.0


def test_compute_lots_eurusd():
    from src.auto_execution import AutoExecutor
    lots = AutoExecutor.compute_lots(
        account_balance=10000, risk_pct=0.5,
        entry=1.1000, stop_loss=1.0950, symbol='EURUSD',
    )
    assert 0.01 <= lots <= 10.0


def test_compute_lots_invalid_inputs():
    from src.auto_execution import AutoExecutor
    # Same entry/sl
    lots = AutoExecutor.compute_lots(10000, 0.5, 2400, 2400, 'XAUUSD')
    assert lots == 0.0
    # Zero balance
    lots = AutoExecutor.compute_lots(0, 0.5, 2400, 2395, 'XAUUSD')
    assert lots == 0.0


def test_trading_days_monday_to_friday():
    """Default config should allow Mon-Fri only."""
    from src.auto_execution import AutoExecutionConfig
    cfg = AutoExecutionConfig()
    assert 0 in cfg.trading_days_utc  # Mon
    assert 4 in cfg.trading_days_utc  # Fri
    assert 5 not in cfg.trading_days_utc  # Sat
    assert 6 not in cfg.trading_days_utc  # Sun


def test_guard_blocks_on_weekend():
    """Mock datetime to simulate Saturday."""
    from src.auto_execution import AutoExecutor, AutoExecutionConfig

    auto = AutoExecutor(config=AutoExecutionConfig(trading_days_utc=(0, 1, 2, 3, 4)))

    # Simulate Saturday (weekday=5)
    saturday = datetime(2026, 4, 18, 10, 0, tzinfo=timezone.utc)  # Saturday
    assert saturday.weekday() == 5

    with patch("src.auto_execution.auto_executor.datetime") as mock_dt:
        mock_dt.now.return_value = saturday
        mock_dt.strftime = datetime.strftime
        reason = auto._check_guards("XAUUSD")
        assert reason is not None
        assert "weekday 5" in reason.lower() or "trading disabled" in reason.lower()


def test_guard_blocks_friday_after_cutoff():
    """Friday after 15h UTC should block."""
    from src.auto_execution import AutoExecutor, AutoExecutionConfig

    cfg = AutoExecutionConfig(friday_cutoff_hour_utc=15)
    auto = AutoExecutor(config=cfg)

    # Friday 16h UTC
    friday_late = datetime(2026, 4, 17, 16, 0, tzinfo=timezone.utc)
    assert friday_late.weekday() == 4

    with patch("src.auto_execution.auto_executor.datetime") as mock_dt:
        mock_dt.now.return_value = friday_late
        reason = auto._check_guards("XAUUSD")
        assert reason is not None
        assert "Friday" in reason or "friday" in reason.lower()


def test_guard_blocks_monday_too_early():
    """Monday before 7h UTC should block."""
    from src.auto_execution import AutoExecutor, AutoExecutionConfig

    cfg = AutoExecutionConfig(monday_earliest_hour_utc=7)
    auto = AutoExecutor(config=cfg)

    # Monday 5h UTC
    monday_early = datetime(2026, 4, 20, 5, 0, tzinfo=timezone.utc)
    assert monday_early.weekday() == 0

    with patch("src.auto_execution.auto_executor.datetime") as mock_dt:
        mock_dt.now.return_value = monday_early
        reason = auto._check_guards("XAUUSD")
        assert reason is not None
        assert "Monday" in reason or "monday" in reason.lower() or "early" in reason.lower()


def test_guard_allows_tuesday_morning():
    """Tuesday 10h UTC should allow."""
    from src.auto_execution import AutoExecutor, AutoExecutionConfig

    cfg = AutoExecutionConfig()
    auto = AutoExecutor(config=cfg)

    # Tuesday 10h UTC
    tuesday = datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc)
    assert tuesday.weekday() == 1

    with patch("src.auto_execution.auto_executor.datetime") as mock_dt:
        mock_dt.now.return_value = tuesday
        reason = auto._check_guards("XAUUSD")
        # May still block on balance/positions but NOT on day
        if reason:
            assert "weekday" not in reason.lower()
            assert "friday" not in reason.lower()
            assert "monday" not in reason.lower() or "early" not in reason.lower()


def test_position_manager_register():
    from src.auto_execution import PositionManager
    from src.mt5_execution import MT5Executor
    mt5 = MT5Executor()
    pm = PositionManager(mt5_executor=mt5)
    mp = pm.register(ticket=999, symbol="XAUUSD", side="long",
                      entry=2400, sl=2395, tp=2410, lots=0.5)
    assert mp.ticket == 999
    assert mp.r_unit == 5.0
    assert 999 in pm.managed
    pm.unregister(999)
    assert 999 not in pm.managed


def test_daily_pnl_tracking():
    from src.auto_execution import AutoExecutor, AutoExecutionConfig
    auto = AutoExecutor(config=AutoExecutionConfig(daily_loss_cap_pct=3.5))
    auto.record_daily_pnl(-1.0)
    auto.record_daily_pnl(-1.0)
    assert auto._daily_pnl_pct == pytest.approx(-2.0, abs=0.01)
    # Not yet hitting cap
    auto.record_daily_pnl(-2.0)
    assert auto._daily_pnl_pct == pytest.approx(-4.0, abs=0.01)
    # Now guard should block
    reason = auto._check_guards("XAUUSD")
    assert reason is not None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
