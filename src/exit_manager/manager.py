"""
Exit Manager — multi-partial exits + trailing runner.

Stratégie optimale (config par défaut) :
- 25% @ 1R → SL to break-even
- 25% @ 2R → SL to entry + 0.5R
- 25% @ 3R → SL to entry + 1.5R
- 25% runner → trailing ATR (2x), target min 5R

Permet de :
1. Sécuriser rapidement (1R payé)
2. Protéger les gains (SL avance à chaque palier)
3. Laisser courir les gros moves (runner 5R+)

Expectancy moyenne passe de ~1R à ~2R+ pour le même WR.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Literal
from enum import Enum


class ExitAction(str, Enum):
    HOLD = "hold"
    PARTIAL_CLOSE = "partial_close"
    MOVE_SL = "move_sl"
    TRAIL_SL = "trail_sl"
    FULL_CLOSE = "full_close"


@dataclass
class ExitLevel:
    """Un palier de sortie."""
    at_r: float                    # Multiple de R où on agit
    close_pct: float               # % de la position à fermer (0-1)
    move_sl_to: str                # "entry", "entry_plus_0.5R", "entry_plus_1.5R", "trail"
    triggered: bool = False        # Déjà déclenché ?


@dataclass
class ExitPlan:
    """Plan de sortie complet pour un trade."""
    levels: List[ExitLevel]
    runner_trailing_atr_mult: float = 2.0
    runner_target_min_r: float = 5.0
    runner_started: bool = False


@dataclass
class TradeState:
    """État d'un trade pour gestion exit."""
    symbol: str
    side: Literal["long", "short"]
    entry: float
    sl_original: float
    sl_current: float
    position_size_original: float
    position_size_current: float
    tp: float                      # TP ultime (virtuel)
    r_unit: float                  # Valeur d'1R en prix
    exit_plan: ExitPlan
    current_price: float = 0.0
    current_atr: float = 0.0


@dataclass
class ExitOrder:
    """Ordre à exécuter."""
    action: ExitAction
    close_size: float = 0.0
    new_sl: float = 0.0
    reason: str = ""


class ExitManager:
    """Gère les sorties multi-partials + trailing runner."""

    DEFAULT_LEVELS = [
        ExitLevel(at_r=1.0, close_pct=0.25, move_sl_to="entry"),
        ExitLevel(at_r=2.0, close_pct=0.25, move_sl_to="entry_plus_0.5R"),
        ExitLevel(at_r=3.0, close_pct=0.25, move_sl_to="entry_plus_1.5R"),
    ]

    def __init__(
        self,
        partial_levels: Optional[List[dict]] = None,
        runner_trailing_atr_mult: float = 2.0,
        runner_target_min_r: float = 5.0,
    ):
        if partial_levels:
            self.default_levels = [
                ExitLevel(
                    at_r=lvl["at_r"],
                    close_pct=lvl["close_pct"],
                    move_sl_to=lvl.get("move_sl_to", "entry"),
                )
                for lvl in partial_levels
            ]
        else:
            self.default_levels = list(self.DEFAULT_LEVELS)
        self.runner_trailing_atr_mult = runner_trailing_atr_mult
        self.runner_target_min_r = runner_target_min_r

    def create_plan(self) -> ExitPlan:
        """Retourne un plan fresh pour un nouveau trade."""
        return ExitPlan(
            levels=[
                ExitLevel(
                    at_r=lvl.at_r,
                    close_pct=lvl.close_pct,
                    move_sl_to=lvl.move_sl_to,
                )
                for lvl in self.default_levels
            ],
            runner_trailing_atr_mult=self.runner_trailing_atr_mult,
            runner_target_min_r=self.runner_target_min_r,
        )

    def current_r_reached(self, state: TradeState) -> float:
        """R actuel atteint par le trade."""
        if state.r_unit <= 0:
            return 0.0
        if state.side == "long":
            move = state.current_price - state.entry
        else:
            move = state.entry - state.current_price
        return move / state.r_unit

    def compute_new_sl(self, state: TradeState, target_str: str) -> float:
        """Calcule le nouveau SL selon la règle."""
        e = state.entry
        r = state.r_unit
        sign = 1 if state.side == "long" else -1

        if target_str == "entry":
            return e
        if target_str == "entry_plus_0.5R":
            return e + sign * 0.5 * r
        if target_str == "entry_plus_1.5R":
            return e + sign * 1.5 * r
        if target_str == "entry_plus_2.5R":
            return e + sign * 2.5 * r
        # default = move to break-even
        return e

    def compute_trailing_sl(self, state: TradeState) -> float:
        """SL trailing ATR-based pour le runner."""
        if state.current_atr <= 0:
            return state.sl_current
        offset = self.runner_trailing_atr_mult * state.current_atr
        if state.side == "long":
            new_sl = state.current_price - offset
            return max(new_sl, state.sl_current)  # jamais reculer
        else:
            new_sl = state.current_price + offset
            return min(new_sl, state.sl_current)  # jamais reculer

    def evaluate(self, state: TradeState) -> List[ExitOrder]:
        """
        Évalue le trade actuel et retourne les ordres à exécuter.
        Appelé à chaque tick / mise à jour.
        """
        orders: List[ExitOrder] = []
        r_reached = self.current_r_reached(state)

        # 1. Check each partial level
        all_triggered = True
        for lvl in state.exit_plan.levels:
            if lvl.triggered:
                continue
            all_triggered = False
            if r_reached >= lvl.at_r:
                # Trigger partial close
                close_size = state.position_size_current * lvl.close_pct
                orders.append(ExitOrder(
                    action=ExitAction.PARTIAL_CLOSE,
                    close_size=close_size,
                    reason=f"Partial {int(lvl.close_pct*100)}% @ {lvl.at_r}R",
                ))
                # Move SL
                new_sl = self.compute_new_sl(state, lvl.move_sl_to)
                if new_sl != state.sl_current:
                    orders.append(ExitOrder(
                        action=ExitAction.MOVE_SL,
                        new_sl=new_sl,
                        reason=f"SL → {lvl.move_sl_to}",
                    ))
                lvl.triggered = True

        # 2. Runner trailing (after all partials done)
        if all_triggered or all(l.triggered for l in state.exit_plan.levels):
            state.exit_plan.runner_started = True
            trail_sl = self.compute_trailing_sl(state)
            if trail_sl != state.sl_current:
                orders.append(ExitOrder(
                    action=ExitAction.TRAIL_SL,
                    new_sl=trail_sl,
                    reason=f"Trail ATR x{self.runner_trailing_atr_mult}",
                ))

            # Optional: force close at runner target
            if r_reached >= state.exit_plan.runner_target_min_r * 2:
                # Close the runner if we reach 2x the min target (e.g. 10R)
                orders.append(ExitOrder(
                    action=ExitAction.FULL_CLOSE,
                    close_size=state.position_size_current,
                    reason=f"Runner moonshot @ {r_reached:.1f}R",
                ))

        return orders

    def is_position_safe(self, state: TradeState) -> bool:
        """True si la position est en break-even ou en profit garanti."""
        return any(lvl.triggered for lvl in state.exit_plan.levels)


def apply_exit_orders(state: TradeState, orders: List[ExitOrder]) -> TradeState:
    """Applique les ordres à l'état (pour simulation/dry-run)."""
    for order in orders:
        if order.action == ExitAction.PARTIAL_CLOSE:
            state.position_size_current -= order.close_size
        elif order.action in (ExitAction.MOVE_SL, ExitAction.TRAIL_SL):
            state.sl_current = order.new_sl
        elif order.action == ExitAction.FULL_CLOSE:
            state.position_size_current = 0.0
    return state
