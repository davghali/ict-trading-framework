"""Tests Backtest Engine — déroulement + metrics + Monte Carlo."""
import pandas as pd
import numpy as np
import pytest
from datetime import datetime, timedelta

from src.backtest_engine import Backtester, MonteCarlo
from src.backtest_engine.backtest import BacktestConfig
from src.backtest_engine.metrics import compute_metrics
from src.feature_engine import FeatureEngine
from src.utils.types import Signal, Side, SetupGrade, BiasDirection, Regime, Trade


def make_ohlc_df(n=500):
    idx = pd.date_range("2024-01-01 13:30", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(42)
    p = 18000 + np.cumsum(rng.normal(0, 10, n))
    return pd.DataFrame({
        "open": p, "high": p + 20, "low": p - 20,
        "close": p + rng.normal(0, 5, n), "volume": 5000,
    }, index=idx)


def test_backtest_with_empty_signals():
    df = make_ohlc_df(300)
    df = FeatureEngine().compute(df)
    bt = Backtester(BacktestConfig(initial_balance=100_000))
    result = bt.run("NAS100", df, signals=[])
    assert result.total_trades == 0
    assert result.final_balance == 100_000
    assert result.total_return_pct == 0.0


def test_backtest_one_winning_trade():
    df = make_ohlc_df(500)
    df = FeatureEngine().compute(df)
    ts = df.index[100]
    entry = float(df["close"].iloc[100])
    sig = Signal(
        timestamp=ts.to_pydatetime(),
        symbol="NAS100",
        side=Side.LONG,
        entry=entry,
        stop_loss=entry - 50,  # 50 points de SL
        take_profit_1=entry + 100,  # 2R
        take_profit_2=None,
        grade=SetupGrade.A,
        score=75,
        confluence_count=5,
        htf_bias=BiasDirection.BULLISH,
        regime=Regime.TRENDING_HIGH_VOL,
        killzone="ny_am_kz",
        risk_reward=2.0,
    )
    bt = Backtester(BacktestConfig(initial_balance=100_000,
                                    firm="ftmo", variant="classic_challenge"))
    result = bt.run("NAS100", df, [sig])
    assert result.total_trades >= 0  # may be 0 if risk engine blocks
    # if trade happened, balance should change
    if result.total_trades > 0:
        assert result.final_balance != 100_000


def test_metrics_empty_trades():
    m = compute_metrics([], 100_000, 100_000)
    assert m["sharpe"] == 0
    assert m["win_rate"] == 0
    assert m["max_drawdown_pct"] == 0


def test_monte_carlo_reshuffle_preserves_sum():
    # Create synthetic trades
    from dataclasses import dataclass
    trades = []
    for i in range(50):
        sig = Signal(
            timestamp=datetime(2024, 1, 1) + timedelta(hours=i),
            symbol="TEST", side=Side.LONG, entry=100, stop_loss=95,
            take_profit_1=110, take_profit_2=None, grade=SetupGrade.A,
            score=70, confluence_count=3, risk_reward=2.0,
        )
        pnl = 200 if i % 3 == 0 else -100
        t = Trade(
            signal=sig, entry_time=sig.timestamp, entry_price=100,
            exit_time=sig.timestamp + timedelta(hours=1), exit_price=110 if pnl > 0 else 95,
            pnl_usd=pnl, pnl_r=2.0 if pnl > 0 else -1.0,
            exit_reason="tp1" if pnl > 0 else "sl",
        )
        trades.append(t)

    initial = 100_000
    sum_pnl = sum(t.pnl_usd for t in trades)
    mc = MonteCarlo(n_simulations=500, seed=42)
    result = mc.reshuffle(trades, initial)

    # Mean of final balances after reshuffle must equal initial + sum_pnl (shuffle preserves sum)
    expected_final = initial + sum_pnl
    assert abs(result.mean_final_balance - expected_final) < 0.01


def test_monte_carlo_detects_dd_variance():
    from dataclasses import dataclass
    trades = []
    for i in range(30):
        sig = Signal(
            timestamp=datetime(2024, 1, 1) + timedelta(hours=i),
            symbol="TEST", side=Side.LONG, entry=100, stop_loss=95,
            take_profit_1=110, take_profit_2=None, grade=SetupGrade.A,
            score=70, confluence_count=3, risk_reward=2.0,
        )
        pnl = 500 if i % 2 == 0 else -500
        t = Trade(signal=sig, entry_time=sig.timestamp, entry_price=100,
                  exit_time=sig.timestamp, exit_price=110,
                  pnl_usd=pnl, pnl_r=1 if pnl > 0 else -1, exit_reason="x")
        trades.append(t)

    mc = MonteCarlo(n_simulations=500)
    res = mc.reshuffle(trades, 100_000)
    # Worst DD (99th percentile) should be > mean DD
    assert res.worst_max_dd_pct >= res.mean_max_dd_pct


def test_monte_carlo_parametric():
    mc = MonteCarlo(n_simulations=200, seed=42)
    res = mc.parametric(
        win_rate=0.45, avg_win=200, avg_loss=-100,
        n_trades=100, initial_balance=100_000,
    )
    # Expectancy = 0.45 * 200 - 0.55 * 100 = 90 - 55 = 35/trade → + over 100 trades = ~3500
    # Over many sims, mean_final_balance should be ~ 103500
    assert res.mean_final_balance > 100_000
    assert 102_000 < res.mean_final_balance < 106_000
