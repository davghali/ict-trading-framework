"""Tests Audit Engine — REJECT les faux-positifs."""
import pytest
from datetime import datetime, timedelta

from src.audit_engine import AuditEngine
from src.utils.types import BacktestResult, Trade, Signal, Side, SetupGrade, Regime


def _make_trades(n: int, win_rate: float, avg_win: float, avg_loss: float):
    """Fabrique des trades factices."""
    import random
    random.seed(42)
    trades = []
    for i in range(n):
        is_win = random.random() < win_rate
        pnl = avg_win if is_win else avg_loss
        sig = Signal(
            timestamp=datetime(2024, 1, 1) + timedelta(hours=i * 4),
            symbol="TEST", side=Side.LONG, entry=100, stop_loss=95,
            take_profit_1=110, take_profit_2=None, grade=SetupGrade.A,
            score=70, confluence_count=5, regime=Regime.TRENDING_HIGH_VOL,
            killzone="ny_am_kz", risk_reward=2.0,
        )
        t = Trade(
            signal=sig, entry_time=sig.timestamp, entry_price=100,
            exit_time=sig.timestamp + timedelta(hours=2),
            exit_price=110 if is_win else 95,
            pnl_usd=pnl, pnl_r=2.0 if is_win else -1.0, exit_reason="tp1" if is_win else "sl",
        )
        trades.append(t)
    return trades


def _fabricate_result(trades, initial=100_000):
    """Crée un BacktestResult factice à partir de trades."""
    from src.backtest_engine.metrics import compute_metrics
    final = initial + sum(t.pnl_usd for t in trades)
    m = compute_metrics(trades, initial, final)
    return BacktestResult(
        trades=trades, initial_balance=initial, final_balance=final,
        total_return_pct=(final - initial) / initial * 100,
        max_drawdown_pct=m["max_drawdown_pct"],
        max_daily_drawdown_pct=m["max_daily_drawdown_pct"],
        sharpe_ratio=m["sharpe"], sortino_ratio=m["sortino"], calmar_ratio=m["calmar"],
        win_rate=m["win_rate"], avg_win_r=m["avg_win_r"], avg_loss_r=m["avg_loss_r"],
        expectancy_r=m["expectancy_r"], profit_factor=m["profit_factor"],
        total_trades=len(trades),
        consecutive_wins_max=m["consecutive_wins_max"],
        consecutive_losses_max=m["consecutive_losses_max"],
        performance_by_regime=m["by_regime"],
        performance_by_session=m["by_session"],
        performance_by_grade=m["by_grade"],
        ftmo_compliant=(m["max_daily_drawdown_pct"] <= 5 and m["max_drawdown_pct"] <= 10),
        the5ers_compliant=(m["max_daily_drawdown_pct"] <= 4 and m["max_drawdown_pct"] <= 6),
    )


def test_audit_rejects_too_few_trades():
    trades = _make_trades(n=10, win_rate=0.5, avg_win=200, avg_loss=-100)
    result = _fabricate_result(trades)
    audit = AuditEngine().audit(result)
    assert audit.verdict == "REJECTED"
    assert any("insufficient" in f.message.lower() for f in audit.findings)


def test_audit_rejects_unrealistic_winrate():
    # 90% WR — suspiciously high
    trades = _make_trades(n=100, win_rate=0.90, avg_win=200, avg_loss=-100)
    result = _fabricate_result(trades)
    audit = AuditEngine().audit(result)
    assert audit.verdict == "REJECTED"
    assert any("too good" in f.category.lower() for f in audit.findings)


def test_audit_passes_realistic_results():
    # 40% WR with 2R RR = break-even expectancy, realistic
    trades = _make_trades(n=100, win_rate=0.40, avg_win=200, avg_loss=-100)
    result = _fabricate_result(trades)
    audit = AuditEngine().audit(result)
    # Should not be REJECTED (either PASSED or WARNING)
    assert audit.verdict in ("PASSED", "WARNING")


def test_audit_detects_ftmo_violation():
    # Force a big drawdown trade
    trades = _make_trades(n=50, win_rate=0.5, avg_win=100, avg_loss=-200)
    # Insert a -6000 trade to trigger big daily DD
    sig = trades[0].signal
    big_loss = Trade(
        signal=sig, entry_time=sig.timestamp, entry_price=100, exit_price=88,
        exit_time=sig.timestamp + timedelta(hours=1),
        pnl_usd=-6000, pnl_r=-12.0, exit_reason="sl",
    )
    trades.insert(20, big_loss)
    result = _fabricate_result(trades)
    audit = AuditEngine().audit(result)
    # Max daily DD > 5% should flag FTMO violation
    if result.max_daily_drawdown_pct > 5:
        assert any("FTMO" in f.message for f in audit.findings)


def test_audit_detects_extreme_profit_factor():
    # PF > 5 is suspicious
    trades = _make_trades(n=80, win_rate=0.80, avg_win=500, avg_loss=-50)
    result = _fabricate_result(trades)
    audit = AuditEngine().audit(result)
    pf_warnings = [f for f in audit.findings if "profit factor" in f.message.lower()]
    # Should have a warning about PF
    assert len(pf_warnings) > 0 or result.profit_factor <= 5
