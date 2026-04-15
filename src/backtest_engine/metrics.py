"""
Metrics — Sharpe, Sortino, Calmar, expectancy, profit factor, etc.
Tous calculés à partir d'une liste de Trades.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
from typing import Dict, List

from src.utils.types import Trade


def compute_metrics(
    trades: List[Trade], initial_balance: float, final_balance: float
) -> dict:
    if not trades:
        return _empty_metrics()

    pnls = np.array([t.pnl_usd for t in trades])
    r_values = np.array([t.pnl_r for t in trades if t.pnl_r is not None])
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]

    # Equity curve (trade-by-trade)
    equity = initial_balance + np.cumsum(pnls)
    equity_series = pd.Series(equity)
    rolling_max = equity_series.cummax()
    drawdown = (equity_series - rolling_max) / rolling_max * 100
    max_dd = float(drawdown.min()) if not drawdown.empty else 0.0

    # Daily DD (group by date)
    daily_pnl: Dict[pd.Timestamp, float] = {}
    for t in trades:
        if t.exit_time is None:
            continue
        d = pd.Timestamp(t.exit_time).normalize()
        daily_pnl[d] = daily_pnl.get(d, 0) + t.pnl_usd
    if daily_pnl:
        daily_series = pd.Series(daily_pnl).sort_index()
        daily_dd = (daily_series / initial_balance * 100)
        max_daily_dd = float(daily_dd.min())
    else:
        max_daily_dd = 0.0

    # Returns per trade (pct of initial)
    trade_returns = pnls / initial_balance
    mean_r = np.mean(trade_returns) if len(trade_returns) else 0
    std_r = np.std(trade_returns) if len(trade_returns) else 1e-9
    sharpe = math.sqrt(len(trades)) * mean_r / std_r if std_r > 0 else 0

    downside = trade_returns[trade_returns < 0]
    dev_d = np.std(downside) if len(downside) else 1e-9
    sortino = math.sqrt(len(trades)) * mean_r / dev_d if dev_d > 0 else 0

    total_return = (final_balance - initial_balance) / initial_balance * 100
    calmar = total_return / abs(max_dd) if max_dd < 0 else float("inf")

    win_rate = len(wins) / len(trades) if trades else 0
    avg_win_r = float(np.mean(r_values[r_values > 0])) if (r_values > 0).any() else 0
    avg_loss_r = float(np.mean(r_values[r_values < 0])) if (r_values < 0).any() else 0
    expectancy_r = win_rate * avg_win_r + (1 - win_rate) * avg_loss_r
    profit_factor = float(wins.sum() / abs(losses.sum())) if losses.sum() else float("inf")

    # Consecutive streaks
    cons_wins = cons_losses = max_w = max_l = 0
    for t in trades:
        if t.is_win:
            cons_wins += 1
            cons_losses = 0
            max_w = max(max_w, cons_wins)
        else:
            cons_losses += 1
            cons_wins = 0
            max_l = max(max_l, cons_losses)

    # Breakdown
    by_regime = _group_metric(trades, lambda t: t.signal.regime.value)
    by_session = _group_metric(trades, lambda t: t.signal.killzone or "none")
    by_grade = _group_metric(trades, lambda t: t.signal.grade.value)

    return {
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "calmar": float(calmar) if calmar != float("inf") else 9999.0,
        "max_drawdown_pct": abs(max_dd),
        "max_daily_drawdown_pct": abs(max_daily_dd),
        "win_rate": float(win_rate),
        "avg_win_r": avg_win_r,
        "avg_loss_r": avg_loss_r,
        "expectancy_r": float(expectancy_r),
        "profit_factor": profit_factor,
        "consecutive_wins_max": int(max_w),
        "consecutive_losses_max": int(max_l),
        "by_regime": by_regime,
        "by_session": by_session,
        "by_grade": by_grade,
    }


def _group_metric(trades: List[Trade], key_fn) -> Dict[str, dict]:
    groups: Dict[str, List[Trade]] = {}
    for t in trades:
        try:
            k = key_fn(t)
        except Exception:
            k = "unknown"
        groups.setdefault(k, []).append(t)

    out = {}
    for k, ts in groups.items():
        pnl = sum(t.pnl_usd for t in ts)
        wr = sum(1 for t in ts if t.is_win) / len(ts)
        out[k] = {
            "n": len(ts),
            "pnl_usd": round(pnl, 2),
            "win_rate": round(wr, 3),
            "avg_r": round(np.mean([t.pnl_r for t in ts if t.pnl_r is not None]) or 0, 3),
        }
    return out


def _empty_metrics() -> dict:
    return {
        "sharpe": 0.0, "sortino": 0.0, "calmar": 0.0,
        "max_drawdown_pct": 0.0, "max_daily_drawdown_pct": 0.0,
        "win_rate": 0.0, "avg_win_r": 0.0, "avg_loss_r": 0.0,
        "expectancy_r": 0.0, "profit_factor": 0.0,
        "consecutive_wins_max": 0, "consecutive_losses_max": 0,
        "by_regime": {}, "by_session": {}, "by_grade": {},
    }
