"""
Tests Risk Engine — compliance FTMO & The 5ers est critique.
"""
import pytest
from datetime import datetime, timedelta
from dataclasses import replace

from src.risk_engine import RiskEngine, PositionSizer, AccountState
from src.utils.types import Signal, Side, SetupGrade, BiasDirection, Regime


def make_signal(side=Side.LONG):
    return Signal(
        timestamp=datetime(2024, 3, 4, 13, 30),
        symbol="EURUSD",
        side=side,
        entry=1.1000,
        stop_loss=1.0980 if side == Side.LONG else 1.1020,
        take_profit_1=1.1040 if side == Side.LONG else 1.0960,
        take_profit_2=None,
        grade=SetupGrade.A,
        score=75,
        confluence_count=5,
        htf_bias=BiasDirection.BULLISH if side == Side.LONG else BiasDirection.BEARISH,
        regime=Regime.TRENDING_HIGH_VOL,
        killzone="ny_am_kz",
        risk_reward=2.0,
    )


def test_ftmo_initial_state():
    rk = RiskEngine("ftmo", "classic_challenge")
    acc = rk.init_account(100_000)
    assert acc.balance == 100_000
    assert acc.equity == 100_000
    assert not acc.trading_halted


def test_ftmo_blocks_weekend():
    rk = RiskEngine("ftmo", "classic_challenge")
    acc = rk.init_account(100_000)
    sig = make_signal()
    # samedi 10h
    sat = datetime(2024, 3, 2, 10, 0)
    dec = rk.pre_trade_check(acc, sig, sat)
    assert not dec.allow
    assert "Weekend" in dec.reason or "weekend" in dec.reason.lower()


def test_ftmo_hard_cap_halts():
    rk = RiskEngine("ftmo", "classic_challenge")
    acc = rk.init_account(100_000)
    # Simulate -4% daily loss (au-delà du hard cap 3.5% interne)
    acc.balance = 96_000
    acc.equity = 96_000
    acc.start_of_day_balance = 100_000
    acc.last_reset_day = datetime(2024, 3, 4).date()

    sig = make_signal()
    dec = rk.pre_trade_check(acc, sig, datetime(2024, 3, 4, 14, 0))
    assert not dec.allow
    assert acc.trading_halted


def test_consecutive_losses_pause():
    rk = RiskEngine("ftmo", "classic_challenge")
    acc = rk.init_account(100_000)
    acc.consecutive_losses = 3
    acc.last_reset_day = datetime(2024, 3, 4).date()
    sig = make_signal()
    dec = rk.pre_trade_check(acc, sig, datetime(2024, 3, 4, 13, 30))
    assert not dec.allow
    assert "consecutive" in dec.reason.lower()


def test_the_5ers_stricter_than_ftmo():
    ftmo = RiskEngine("ftmo", "classic_challenge")
    fivers = RiskEngine("the_5ers", "hpt")
    # The 5ers HPT a des limites plus strictes
    assert fivers.rules["max_daily_loss_pct"] < ftmo.rules["max_daily_loss_pct"]


def test_position_sizer_forex():
    s = PositionSizer()
    # Risque $500 sur EURUSD, SL 20 pips
    res = s.calculate("EURUSD", entry=1.1000, stop_loss=1.0980, risk_usd=500)
    assert res.valid
    # stop_pips = 20, pip_per_lot = 10 → risk per lot = $200
    # Target : $500 / $200 = 2.5 lots → arrondi à 2.50
    assert res.size == pytest.approx(2.5, rel=0.1)


def test_position_sizer_invalid_stop():
    s = PositionSizer()
    # Stop = entry → invalide
    res = s.calculate("EURUSD", entry=1.1000, stop_loss=1.1000, risk_usd=500)
    assert not res.valid


def test_position_sizer_respects_min_lot():
    s = PositionSizer()
    # Très petit risque → pourrait donner < min_lot
    res = s.calculate("EURUSD", entry=1.1000, stop_loss=1.0999, risk_usd=1)
    # Soit valide et >= min_lot, soit invalid
    if res.valid:
        assert res.size >= 0.01


def test_daily_reset_on_new_day():
    rk = RiskEngine("ftmo", "classic_challenge")
    acc = rk.init_account(100_000)
    acc.trades_today = 3
    acc.last_reset_day = datetime(2024, 3, 4).date()
    # Pre-trade check un nouveau jour
    rk._maybe_reset_daily(acc, datetime(2024, 3, 5, 10, 0))
    assert acc.trades_today == 0
    assert acc.last_reset_day == datetime(2024, 3, 5).date()
