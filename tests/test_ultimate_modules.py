"""
Tests unitaires — modules Phase 1/2/3 de ICT Cyborg Ultimate.

Couvre :
- exit_manager : partials, trailing, state transitions
- confluence_filter : score, pass/fail, required
- dynamic_risk : hot/cold streak, lockout
- news_ride : spike, retracement, signal generation
- pyramid_manager : register, can_add, adds limit
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


# ============ EXIT MANAGER ============

def test_exit_manager_default_levels():
    from src.exit_manager import ExitManager
    em = ExitManager()
    plan = em.create_plan()
    assert len(plan.levels) == 3
    assert plan.levels[0].at_r == 1.0
    assert plan.levels[1].at_r == 2.0
    assert plan.levels[2].at_r == 3.0


def test_exit_manager_triggers_first_partial():
    from src.exit_manager import ExitManager
    from src.exit_manager.manager import TradeState, ExitAction
    em = ExitManager()
    state = TradeState(
        symbol="XAUUSD", side="long", entry=2400.0,
        sl_original=2395.0, sl_current=2395.0,
        position_size_original=1.0, position_size_current=1.0,
        tp=2415.0, r_unit=5.0,
        exit_plan=em.create_plan(), current_price=2405.0, current_atr=3.0,
    )
    orders = em.evaluate(state)
    actions = [o.action for o in orders]
    assert ExitAction.PARTIAL_CLOSE in actions
    assert ExitAction.MOVE_SL in actions


def test_exit_manager_runner_trailing():
    from src.exit_manager import ExitManager
    from src.exit_manager.manager import TradeState, ExitAction, apply_exit_orders
    em = ExitManager(runner_trailing_atr_mult=2.0)
    plan = em.create_plan()
    # Trigger all partials
    for lvl in plan.levels:
        lvl.triggered = True
    state = TradeState(
        symbol="XAUUSD", side="long", entry=2400.0,
        sl_original=2395.0, sl_current=2395.0,
        position_size_original=1.0, position_size_current=0.25,
        tp=2415.0, r_unit=5.0,
        exit_plan=plan, current_price=2425.0, current_atr=3.0,
    )
    orders = em.evaluate(state)
    assert any(o.action == ExitAction.TRAIL_SL for o in orders)


def test_exit_manager_short_direction():
    from src.exit_manager import ExitManager
    from src.exit_manager.manager import TradeState
    em = ExitManager()
    state = TradeState(
        symbol="EURUSD", side="short", entry=1.1000,
        sl_original=1.1050, sl_current=1.1050,
        position_size_original=1.0, position_size_current=1.0,
        tp=1.0900, r_unit=0.0050,
        exit_plan=em.create_plan(), current_price=1.0950, current_atr=0.0010,
    )
    r = em.current_r_reached(state)
    assert r == pytest.approx(1.0, abs=0.01)


# ============ CONFLUENCE FILTER ============

def test_confluence_all_7():
    from src.confluence_filter import ConfluenceFilter
    cf = ConfluenceFilter(min_score=3)
    r = cf.evaluate(
        multi_tf_aligned=True, smt_divergence=True,
        liquidity_sweep_recent=True, cross_asset_aligned=True,
        in_killzone=True, volume_spike=True, fresh_order_block=True,
    )
    assert r.pass_filter
    assert r.total_score == 7
    assert r.grade.name == "DIVINE"


def test_confluence_fails_below_min():
    from src.confluence_filter import ConfluenceFilter
    cf = ConfluenceFilter(min_score=5, require_multi_tf=False, require_smt=False, require_killzone=False)
    r = cf.evaluate(
        multi_tf_aligned=True, smt_divergence=False,
        liquidity_sweep_recent=False, cross_asset_aligned=False,
        in_killzone=False, volume_spike=False, fresh_order_block=False,
    )
    assert not r.pass_filter
    assert "min 5" in r.reason


def test_confluence_hard_requirement_smt():
    from src.confluence_filter import ConfluenceFilter
    cf = ConfluenceFilter(min_score=1, require_smt=True)
    r = cf.evaluate(
        multi_tf_aligned=True, smt_divergence=False,
        liquidity_sweep_recent=True, cross_asset_aligned=True,
        in_killzone=True, volume_spike=True, fresh_order_block=True,
    )
    assert not r.pass_filter
    assert "SMT" in r.reason


# ============ DYNAMIC RISK ============

def test_dynamic_risk_base():
    from src.dynamic_risk import DynamicRiskManager
    dr = DynamicRiskManager(base_risk=0.5)
    d = dr.decide()
    assert d.allowed
    assert d.risk_pct == 0.5


def test_dynamic_risk_hot_streak():
    from src.dynamic_risk import DynamicRiskManager
    dr = DynamicRiskManager(base_risk=0.5, max_risk=1.0, hot_streak_boost=0.2)
    dr.record_result("win", 2.5)
    dr.record_result("win", 2.5)
    d = dr.decide()
    assert d.risk_pct > 0.5
    assert d.risk_pct <= 1.0


def test_dynamic_risk_cold_streak():
    from src.dynamic_risk import DynamicRiskManager
    # daily_dd_lock_pct bas pour éviter lockout prématuré
    dr = DynamicRiskManager(base_risk=0.5, min_risk=0.25, cold_streak_penalty=0.25,
                            daily_dd_lock_pct=10.0)
    dr.record_result("loss", -0.5)
    dr.record_result("loss", -0.5)
    d = dr.decide()
    assert d.allowed
    assert d.risk_pct < 0.5
    assert d.risk_pct >= 0.25


def test_dynamic_risk_lockout():
    from src.dynamic_risk import DynamicRiskManager
    dr = DynamicRiskManager(lockout_after_losses=3)
    for _ in range(3):
        dr.record_result("loss", -1.0)
    assert dr.state.is_locked_out()
    assert not dr.decide().allowed


def test_dynamic_risk_max_cap():
    from src.dynamic_risk import DynamicRiskManager
    dr = DynamicRiskManager(base_risk=0.5, max_risk=1.0, hot_streak_boost=0.5)
    for _ in range(20):
        dr.record_result("win", 2.5)
    d = dr.decide()
    assert d.risk_pct <= 1.0  # capped


# ============ NEWS RIDE ============

def test_news_ride_register():
    from src.news_ride import NewsRideModule
    from src.news_ride.ride import NewsEvent
    nr = NewsRideModule()
    event = NewsEvent(
        symbol="EURUSD", currency="USD", timestamp=datetime.utcnow(),
        impact="high", name="NFP", pre_release_price=1.0800,
    )
    nr.register_news(event)
    assert nr.active_count() == 1


def test_news_ride_retracement_signal():
    from src.news_ride import NewsRideModule
    from src.news_ride.ride import NewsEvent
    nr = NewsRideModule(wait_minutes=1, retracement_pct=0.618)
    t0 = datetime.utcnow()
    event = NewsEvent(
        symbol="EURUSD", currency="USD", timestamp=t0,
        impact="high", name="NFP", pre_release_price=1.0800,
    )
    nr.register_news(event)
    # spike up
    nr.update_price("EURUSD", 1.0855, t0 + timedelta(minutes=1, seconds=30))
    # retracement
    retrace = 1.0855 - 0.618 * (1.0855 - 1.0800)
    sigs = nr.update_price("EURUSD", retrace - 0.0001, t0 + timedelta(minutes=3))
    assert len(sigs) == 1
    assert sigs[0].side == "short"  # fade the up spike


def test_news_ride_expiration():
    from src.news_ride import NewsRideModule
    from src.news_ride.ride import NewsEvent
    nr = NewsRideModule(valid_window_minutes=1)
    t0 = datetime.utcnow()
    event = NewsEvent(
        symbol="EURUSD", currency="USD", timestamp=t0,
        impact="high", name="NFP", pre_release_price=1.0800,
    )
    nr.register_news(event)
    nr.update_price("EURUSD", 1.0850, t0 + timedelta(minutes=2))
    assert nr.active_count() == 0


# ============ PYRAMID MANAGER ============

def test_pyramid_register_and_progress():
    from src.pyramid_manager import PyramidManager
    pm = PyramidManager()
    pm.register_trade("t1", "XAUUSD", "long", 2400.0, 2395.0)
    pm.update_progress("t1", 2410.0)  # +2R
    assert pm.states["t1"].current_r == pytest.approx(2.0, abs=0.01)
    assert pm.states["t1"].initial_in_profit


def test_pyramid_add_order():
    from src.pyramid_manager import PyramidManager
    pm = PyramidManager(max_adds=2, add_at_r=1.0, add_risk_pct=0.3)
    pm.register_trade("t1", "XAUUSD", "long", 2400.0, 2395.0)
    pm.update_progress("t1", 2410.0)
    order = pm.create_add_order("t1", 2410.0, 2405.0, 100000, confluence_score=5)
    assert order is not None
    assert order.risk_pct == 0.3
    assert order.add_number == 1


def test_pyramid_max_adds():
    from src.pyramid_manager import PyramidManager
    pm = PyramidManager(max_adds=2, add_at_r=1.0)
    pm.register_trade("t1", "XAUUSD", "long", 2400.0, 2395.0)
    pm.update_progress("t1", 2410.0)
    pm.create_add_order("t1", 2410.0, 2405.0, 100000, confluence_score=5)
    pm.create_add_order("t1", 2410.0, 2405.0, 100000, confluence_score=5)
    third = pm.create_add_order("t1", 2410.0, 2405.0, 100000, confluence_score=5)
    assert third is None  # max exceeded


def test_pyramid_disabled_on_be_return():
    from src.pyramid_manager import PyramidManager
    pm = PyramidManager()
    pm.register_trade("t1", "XAUUSD", "long", 2400.0, 2395.0)
    pm.update_progress("t1", 2410.0)  # +2R, in_profit True
    pm.update_progress("t1", 2398.0)  # back below entry
    assert pm.states["t1"].disabled


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
