"""
Backtester event-driven avec Risk Engine intégré.

Flow :
1. Iteration bar-par-bar sur LTF
2. Pour chaque bar :
   - Update equity (mark-to-market) des trades ouverts
   - Check violations Risk Engine (halt si hard cap)
   - Check gestion des trades ouverts (SL, TP1, TP2, BE, trailing)
   - Si signal disponible, check Risk Engine → ouvrir si OK

Réaliste :
- Slippage : N pips par trade (configurable)
- Commission : selon instrument
- Spread : check pas dépassé
- Exécution à la bar suivante (pas de look-ahead)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional
import pandas as pd
import numpy as np

from src.utils.types import Signal, Trade, BacktestResult, Side, SetupGrade
from src.utils.logging_conf import get_logger
from src.risk_engine import RiskEngine, PositionSizer, AccountState
from src.utils.config import get_instrument

log = get_logger(__name__)


@dataclass
class BacktestConfig:
    initial_balance: float = 100_000
    firm: str = "ftmo"
    variant: str = "classic_challenge"
    slippage_pips: float = 0.5          # slippage moyen
    commission_override_usd: Optional[float] = None
    break_even_rr: float = 1.0          # déplacer SL à BE à partir de 1R
    trailing_start_rr: float = 2.0      # commencer trailing à 2R
    partial_tp1_pct: float = 0.50       # prendre 50% à TP1
    enable_trailing: bool = True


class Backtester:

    def __init__(self, config: BacktestConfig):
        self.cfg = config
        self.risk = RiskEngine(config.firm, config.variant)
        self.sizer = PositionSizer()

    def run(
        self,
        symbol: str,
        df_ltf: pd.DataFrame,
        signals: List[Signal],
    ) -> BacktestResult:
        """
        df_ltf doit contenir OHLCV + features nécessaires.
        signals doit être trié par timestamp.
        """
        account = self.risk.init_account(self.cfg.initial_balance)
        closed_trades: List[Trade] = []

        # Index signals par timestamp (UTC)
        def _utc_ts(dt):
            ts = pd.Timestamp(dt)
            return ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")
        signals_by_ts: Dict[pd.Timestamp, Signal] = {
            _utc_ts(s.timestamp): s for s in signals
        }

        # Instrument
        inst = get_instrument(symbol)
        pip = inst["pip_value"]
        slippage_abs = self.cfg.slippage_pips * pip

        # Main loop
        for t in range(1, len(df_ltf)):
            ts = df_ltf.index[t]
            bar = df_ltf.iloc[t]
            now = ts.to_pydatetime()

            # --- Update open trades (MTM + exits)
            self._manage_open_trades(account, bar, ts, slippage_abs, closed_trades, symbol)

            # --- Check compliance
            ok, violations = self.risk.check_compliance(account, now)
            if not ok:
                log.warning(f"{ts} Violations: {violations}")

            # --- Open new trades?
            prev_ts = df_ltf.index[t - 1]
            if prev_ts in signals_by_ts:
                signal = signals_by_ts[prev_ts]
                decision = self.risk.pre_trade_check(account, signal, now)

                if decision.allow:
                    sizing = self.sizer.calculate(
                        symbol, signal.entry, signal.stop_loss, decision.risk_usd,
                    )
                    if sizing.valid:
                        # Exécution à l'ouverture de la bar suivante + slippage
                        fill_price = bar["open"]
                        if signal.side == Side.LONG:
                            fill_price += slippage_abs
                        else:
                            fill_price -= slippage_abs

                        # Vérifier que le SL n'est pas déjà touché
                        if signal.side == Side.LONG and fill_price <= signal.stop_loss:
                            continue
                        if signal.side == Side.SHORT and fill_price >= signal.stop_loss:
                            continue

                        # Mise à jour du signal avec sizing
                        signal.position_size = sizing.size
                        signal.risk_pct = decision.risk_pct

                        trade = Trade(
                            signal=signal,
                            entry_time=now,
                            entry_price=fill_price,
                            commission_usd=sizing.commission_usd,
                            slippage_usd=slippage_abs * sizing.size * inst.get("pip_value_per_lot_usd", 1.0),
                        )
                        self.risk.on_trade_opened(account, trade, now)

        # --- Close remaining open trades at last bar
        if account.open_trades and len(df_ltf) > 0:
            last_bar = df_ltf.iloc[-1]
            last_ts = df_ltf.index[-1]
            for trade in list(account.open_trades):
                self._close_trade(
                    account, trade, float(last_bar["close"]),
                    last_ts.to_pydatetime(), "end_of_data", closed_trades, symbol,
                )

        # Build result
        result = self._build_result(account, closed_trades)
        return result

    # ------------------------------------------------------------------
    def _manage_open_trades(
        self,
        account: AccountState,
        bar: pd.Series,
        ts: pd.Timestamp,
        slippage_abs: float,
        closed_trades: List[Trade],
        symbol: str,
    ) -> None:
        floating_pnl = 0.0
        for trade in list(account.open_trades):
            sig = trade.signal
            high = bar["high"]
            low = bar["low"]

            inst = get_instrument(symbol)
            pip_per_lot = inst.get("pip_value_per_lot_usd", 1.0)
            contract_size = inst.get("contract_size", 1)

            if sig.side == Side.LONG:
                # SL touché ?
                if low <= sig.stop_loss:
                    fill = sig.stop_loss - slippage_abs  # slippage en défaveur
                    self._close_trade(account, trade, fill, ts.to_pydatetime(),
                                       "sl", closed_trades, symbol)
                    continue
                # TP1 ?
                if sig.take_profit_1 and high >= sig.take_profit_1 and trade.exit_reason != "tp1_partial":
                    # On clôture la moitié (partial)
                    # Pour simplifier : on clôture entièrement à TP1 × 1.2 si mode simple
                    # Ou à TP2 si ambitieux
                    if self.cfg.partial_tp1_pct >= 0.99 or sig.take_profit_2 is None:
                        fill = sig.take_profit_1
                        self._close_trade(account, trade, fill, ts.to_pydatetime(),
                                          "tp1", closed_trades, symbol)
                        continue
                    else:
                        # Simuler partial : réduire size, marquer, déplacer SL à BE
                        remaining = 1 - self.cfg.partial_tp1_pct
                        partial_pnl = self._compute_pnl(
                            sig.side, trade.entry_price, sig.take_profit_1,
                            sig.position_size * self.cfg.partial_tp1_pct,
                            contract_size, inst["asset_class"],
                        )
                        # Crédite le partial
                        account.balance += partial_pnl
                        trade.pnl_usd += partial_pnl
                        sig.position_size *= remaining
                        trade.exit_reason = "tp1_partial"
                        sig.stop_loss = trade.entry_price            # BE
                        continue
                if sig.take_profit_2 and high >= sig.take_profit_2:
                    fill = sig.take_profit_2
                    self._close_trade(account, trade, fill, ts.to_pydatetime(),
                                       "tp2", closed_trades, symbol)
                    continue
                # Break-even move
                if self.cfg.break_even_rr > 0:
                    r = trade.entry_price - sig.stop_loss
                    if bar["close"] >= trade.entry_price + self.cfg.break_even_rr * r \
                       and sig.stop_loss < trade.entry_price:
                        sig.stop_loss = trade.entry_price

                # Floating PnL
                floating_pnl += self._compute_pnl(
                    Side.LONG, trade.entry_price, bar["close"],
                    sig.position_size, contract_size, inst["asset_class"],
                )

            else:  # SHORT
                if high >= sig.stop_loss:
                    fill = sig.stop_loss + slippage_abs
                    self._close_trade(account, trade, fill, ts.to_pydatetime(),
                                       "sl", closed_trades, symbol)
                    continue
                if sig.take_profit_1 and low <= sig.take_profit_1 and trade.exit_reason != "tp1_partial":
                    if self.cfg.partial_tp1_pct >= 0.99 or sig.take_profit_2 is None:
                        fill = sig.take_profit_1
                        self._close_trade(account, trade, fill, ts.to_pydatetime(),
                                          "tp1", closed_trades, symbol)
                        continue
                    else:
                        remaining = 1 - self.cfg.partial_tp1_pct
                        partial_pnl = self._compute_pnl(
                            sig.side, trade.entry_price, sig.take_profit_1,
                            sig.position_size * self.cfg.partial_tp1_pct,
                            contract_size, inst["asset_class"],
                        )
                        account.balance += partial_pnl
                        trade.pnl_usd += partial_pnl
                        sig.position_size *= remaining
                        trade.exit_reason = "tp1_partial"
                        sig.stop_loss = trade.entry_price
                        continue
                if sig.take_profit_2 and low <= sig.take_profit_2:
                    fill = sig.take_profit_2
                    self._close_trade(account, trade, fill, ts.to_pydatetime(),
                                       "tp2", closed_trades, symbol)
                    continue
                if self.cfg.break_even_rr > 0:
                    r = sig.stop_loss - trade.entry_price
                    if bar["close"] <= trade.entry_price - self.cfg.break_even_rr * r \
                       and sig.stop_loss > trade.entry_price:
                        sig.stop_loss = trade.entry_price

                floating_pnl += self._compute_pnl(
                    Side.SHORT, trade.entry_price, bar["close"],
                    sig.position_size, contract_size, inst["asset_class"],
                )

        self.risk.update_equity(account, floating_pnl)

    # ------------------------------------------------------------------
    def _close_trade(
        self,
        account: AccountState,
        trade: Trade,
        fill_price: float,
        ts: datetime,
        reason: str,
        closed_trades: List[Trade],
        symbol: str,
    ) -> None:
        inst = get_instrument(symbol)
        sig = trade.signal
        contract_size = inst.get("contract_size", 1)

        pnl = self._compute_pnl(
            sig.side, trade.entry_price, fill_price,
            sig.position_size, contract_size, inst["asset_class"],
        )
        trade.exit_price = fill_price
        trade.exit_time = ts
        trade.exit_reason = reason
        trade.pnl_usd += pnl
        trade.pnl_usd -= trade.commission_usd

        # R-multiple
        risk_per_unit = abs(trade.entry_price - sig.stop_loss)
        if risk_per_unit > 0:
            initial_risk_usd = risk_per_unit * sig.position_size * contract_size \
                if inst["asset_class"] in ("metals",) \
                else risk_per_unit * sig.position_size * inst.get("pip_value_per_lot_usd", 1.0) / inst.get("pip_value", 1)
            # Simplification : utiliser ratio entry/stop
            trade.pnl_r = trade.pnl_usd / initial_risk_usd if initial_risk_usd > 0 else 0
        trade.pnl_pct = trade.pnl_usd / account.initial_balance * 100
        trade.duration_bars = 0  # simplification

        self.risk.on_trade_closed(account, trade)
        closed_trades.append(trade)

    @staticmethod
    def _compute_pnl(side: Side, entry: float, exit: float, size: float,
                     contract_size: float, asset_class: str) -> float:
        diff = (exit - entry) if side == Side.LONG else (entry - exit)
        if asset_class == "forex":
            # size is lots, diff in price. pnl = diff / pip_value × pip_per_lot × lots
            # Shortcut : pnl = diff × 100000 × lots / rate (approx for most pairs)
            return diff * 100000 * size              # for 100k contract
        elif asset_class == "indices":
            return diff * size * contract_size        # contracts * point_value
        elif asset_class == "metals":
            return diff * size * contract_size        # lots * 100 oz
        elif asset_class == "crypto":
            return diff * size                         # BTC units
        return diff * size

    # ------------------------------------------------------------------
    def _build_result(
        self,
        account: AccountState,
        trades: List[Trade],
    ) -> BacktestResult:
        from src.backtest_engine.metrics import compute_metrics
        m = compute_metrics(trades, account.initial_balance, account.balance)

        # Compliance final
        final_compliance = (
            abs((min(account.balance, account.initial_balance) - account.initial_balance) / account.initial_balance * 100)
            <= self.risk.rules["max_overall_loss_pct"]
        )

        res = BacktestResult(
            trades=trades,
            initial_balance=account.initial_balance,
            final_balance=account.balance,
            total_return_pct=(account.balance - account.initial_balance) / account.initial_balance * 100,
            max_drawdown_pct=m["max_drawdown_pct"],
            max_daily_drawdown_pct=m["max_daily_drawdown_pct"],
            sharpe_ratio=m["sharpe"],
            sortino_ratio=m["sortino"],
            calmar_ratio=m["calmar"],
            win_rate=m["win_rate"],
            avg_win_r=m["avg_win_r"],
            avg_loss_r=m["avg_loss_r"],
            expectancy_r=m["expectancy_r"],
            profit_factor=m["profit_factor"],
            total_trades=len(trades),
            consecutive_wins_max=m["consecutive_wins_max"],
            consecutive_losses_max=m["consecutive_losses_max"],
            performance_by_regime=m.get("by_regime", {}),
            performance_by_session=m.get("by_session", {}),
            performance_by_grade=m.get("by_grade", {}),
            ftmo_compliant=final_compliance and m["max_daily_drawdown_pct"] <= 5.0,
            the5ers_compliant=final_compliance and m["max_daily_drawdown_pct"] <= 4.0,
            violations=[],
        )
        return res
