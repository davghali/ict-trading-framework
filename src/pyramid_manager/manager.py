"""
Pyramid Manager — ajoute des positions sur setups gagnants.

Règles strictes :
1. Trade initial doit être en profit >= +1R
2. Nouveau setup même direction validé (confluence >= 3)
3. Max 2 ajouts par trade initial
4. Chaque ajout : risque 0.3% du compte (réduit vs initial 0.5%)
5. SL des ajouts : sur la structure locale (plus serré)
6. Si trade initial revient en break-even → STOP ajouts

Effet : multiplie le gain sur les gros moves tendanciels (Silver Bullet,
Judas Swing) sans risquer davantage sur setups moyens.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Literal, Dict
from datetime import datetime


@dataclass
class PyramidAddOrder:
    """Ordre d'ajout d'une position."""
    symbol: str
    side: Literal["long", "short"]
    entry: float
    sl: float
    tp: float
    size: float
    risk_pct: float
    parent_trade_id: str
    add_number: int                  # 1er ajout, 2ème ajout
    reason: str


@dataclass
class PyramidState:
    """État de pyramid pour un trade initial."""
    parent_trade_id: str
    symbol: str
    side: Literal["long", "short"]
    initial_entry: float
    initial_r_unit: float
    current_r: float = 0.0
    adds_count: int = 0
    adds_history: List[PyramidAddOrder] = field(default_factory=list)
    initial_in_profit: bool = False
    disabled: bool = False           # True si initial revient en BE


class PyramidManager:
    """Gère les ajouts pyramidaux."""

    def __init__(
        self,
        max_adds: int = 2,
        add_at_r: float = 1.0,
        add_risk_pct: float = 0.3,
        require_confluence: bool = True,
        min_confluence_score: int = 3,
    ):
        self.max_adds = max_adds
        self.add_at_r = add_at_r
        self.add_risk_pct = add_risk_pct
        self.require_confluence = require_confluence
        self.min_confluence_score = min_confluence_score
        self.states: Dict[str, PyramidState] = {}

    def register_trade(
        self,
        trade_id: str,
        symbol: str,
        side: Literal["long", "short"],
        entry: float,
        sl: float,
    ):
        """Enregistre un nouveau trade initial éligible au pyramid."""
        r_unit = abs(entry - sl)
        if r_unit <= 0:
            return
        self.states[trade_id] = PyramidState(
            parent_trade_id=trade_id,
            symbol=symbol,
            side=side,
            initial_entry=entry,
            initial_r_unit=r_unit,
        )

    def update_progress(self, trade_id: str, current_price: float) -> None:
        """Met à jour le R actuel du trade initial."""
        state = self.states.get(trade_id)
        if state is None or state.disabled:
            return
        if state.side == "long":
            move = current_price - state.initial_entry
        else:
            move = state.initial_entry - current_price
        r = move / state.initial_r_unit if state.initial_r_unit > 0 else 0.0
        state.current_r = r
        if r >= self.add_at_r:
            state.initial_in_profit = True
        # Si initial revient en BE après avoir été en profit → disable adds
        if state.initial_in_profit and r < 0.0:
            state.disabled = True

    def can_add(
        self,
        trade_id: str,
        confluence_score: int = 0,
    ) -> bool:
        """True si on peut ajouter une position."""
        state = self.states.get(trade_id)
        if state is None or state.disabled:
            return False
        if state.adds_count >= self.max_adds:
            return False
        if state.current_r < self.add_at_r:
            return False
        if self.require_confluence and confluence_score < self.min_confluence_score:
            return False
        return True

    def create_add_order(
        self,
        trade_id: str,
        current_price: float,
        local_sl: float,
        account_balance: float,
        tp_target: Optional[float] = None,
        confluence_score: int = 0,
    ) -> Optional[PyramidAddOrder]:
        """Crée un ordre d'ajout si conditions remplies.

        Note : si require_confluence=True, passer confluence_score explicitement.
        """
        state = self.states.get(trade_id)
        if state is None:
            return None
        # Check hors-confluence (on ne ré-évalue pas ici si appelé après validation externe)
        if state.disabled:
            return None
        if state.adds_count >= self.max_adds:
            return None
        if state.current_r < self.add_at_r:
            return None
        if self.require_confluence and confluence_score < self.min_confluence_score:
            return None

        r_unit_add = abs(current_price - local_sl)
        if r_unit_add <= 0:
            return None

        # Position sizing
        risk_amount = account_balance * (self.add_risk_pct / 100)
        size = risk_amount / r_unit_add

        # TP : si pas spécifié, utiliser 2x R_unit_add
        if tp_target is None:
            if state.side == "long":
                tp_target = current_price + 2 * r_unit_add
            else:
                tp_target = current_price - 2 * r_unit_add

        order = PyramidAddOrder(
            symbol=state.symbol,
            side=state.side,
            entry=current_price,
            sl=local_sl,
            tp=tp_target,
            size=size,
            risk_pct=self.add_risk_pct,
            parent_trade_id=trade_id,
            add_number=state.adds_count + 1,
            reason=(
                f"Pyramid add #{state.adds_count + 1} @ {state.current_r:.1f}R "
                f"on parent {trade_id}"
            ),
        )

        state.adds_count += 1
        state.adds_history.append(order)
        return order

    def close_trade(self, trade_id: str):
        """Nettoie l'état quand le trade initial est clôturé."""
        self.states.pop(trade_id, None)

    def summary(self, trade_id: str) -> str:
        """Résumé d'état d'un trade."""
        state = self.states.get(trade_id)
        if state is None:
            return "No pyramid state"
        return (
            f"Parent {trade_id[:8]}: {state.side.upper()} @ {state.initial_entry:.5f} | "
            f"R={state.current_r:+.2f} | Adds={state.adds_count}/{self.max_adds} | "
            f"{'DISABLED' if state.disabled else 'ACTIVE'}"
        )
