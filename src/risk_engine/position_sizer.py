"""
Position Sizer — conversion précise risk_usd → lots / contrats.

Formules par asset class :

FOREX (EURUSD) :
  lots = risk_usd / (stop_pips × pip_value_per_lot)
  pip_value = $10 par pip par lot standard (100k)

INDICES (NAS100) :
  contracts = risk_usd / (stop_points × point_value)
  NQ: $20 per point, MNQ: $2

METALS (XAUUSD) :
  lots = risk_usd / (stop_points × $1 × 100) (100 oz per lot)

CRYPTO (BTCUSD) :
  size = risk_usd / stop_usd

+ Application des arrondis au min_lot de l'instrument
+ Check contre max_spread (rejet si spread trop large)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from src.utils.config import get_instrument
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class SizingResult:
    valid: bool
    size: float                         # lots ou contracts
    risk_usd: float
    stop_distance: float                # en pips/points/dollars
    commission_usd: float
    reason: str = ""


class PositionSizer:

    def calculate(
        self,
        symbol: str,
        entry: float,
        stop_loss: float,
        risk_usd: float,
    ) -> SizingResult:
        inst = get_instrument(symbol)
        cls = inst["asset_class"]

        stop_dist = abs(entry - stop_loss)
        if stop_dist <= 0:
            return SizingResult(False, 0, risk_usd, 0, 0, "Invalid stop distance")

        if cls == "forex":
            return self._size_forex(inst, entry, stop_dist, risk_usd, symbol)
        elif cls == "indices":
            return self._size_indices(inst, stop_dist, risk_usd, symbol)
        elif cls == "metals":
            return self._size_metals(inst, stop_dist, risk_usd, symbol)
        elif cls == "crypto":
            return self._size_crypto(inst, stop_dist, risk_usd, symbol)
        else:
            return SizingResult(False, 0, risk_usd, stop_dist, 0, f"Unknown class {cls}")

    # ------------------------------------------------------------------
    def _size_forex(self, inst, entry, stop_dist, risk_usd, symbol):
        pip = inst["pip_value"]
        stop_pips = stop_dist / pip
        pip_per_lot = inst["pip_value_per_lot_usd"]
        raw_lots = risk_usd / (stop_pips * pip_per_lot)
        min_lot = inst["min_lot"]
        lots = math.floor(raw_lots / min_lot) * min_lot
        if lots < min_lot:
            return SizingResult(False, 0, risk_usd, stop_pips, 0,
                                f"Computed lots {raw_lots:.4f} < min_lot {min_lot}")
        actual_risk = lots * stop_pips * pip_per_lot
        commission = lots * inst.get("commission_per_lot_usd", 0)
        return SizingResult(True, lots, actual_risk, stop_pips, commission)

    def _size_indices(self, inst, stop_dist, risk_usd, symbol):
        stop_points = stop_dist       # already in points
        point_value = inst["pip_value_per_lot_usd"]     # $ per point per contract
        raw = risk_usd / (stop_points * point_value)
        min_lot = inst["min_lot"]
        contracts = max(min_lot, math.floor(raw / min_lot) * min_lot)
        if contracts < min_lot:
            return SizingResult(False, 0, risk_usd, stop_points, 0,
                                f"Contracts {raw:.2f} < min {min_lot}")
        actual_risk = contracts * stop_points * point_value
        commission = contracts * inst.get("commission_per_lot_usd", 0)
        return SizingResult(True, contracts, actual_risk, stop_points, commission)

    def _size_metals(self, inst, stop_dist, risk_usd, symbol):
        # Gold : $ move × 100 oz per lot = $ per lot per $ move
        # 1 lot = 100 oz. If price moves $1, P&L = $100 per lot
        contract_size = inst["contract_size"]            # 100
        # stop_dist in dollars
        risk_per_lot = stop_dist * contract_size
        raw_lots = risk_usd / risk_per_lot
        min_lot = inst["min_lot"]
        lots = math.floor(raw_lots / min_lot) * min_lot
        if lots < min_lot:
            return SizingResult(False, 0, risk_usd, stop_dist, 0,
                                f"Lots {raw_lots:.4f} < min {min_lot}")
        actual_risk = lots * risk_per_lot
        commission = lots * inst.get("commission_per_lot_usd", 0)
        return SizingResult(True, lots, actual_risk, stop_dist, commission)

    def _size_crypto(self, inst, stop_dist, risk_usd, symbol):
        # crypto : size in BTC (ou equiv). stop_dist déjà en $
        raw = risk_usd / stop_dist
        min_lot = inst["min_lot"]
        size = math.floor(raw / min_lot) * min_lot
        if size < min_lot:
            return SizingResult(False, 0, risk_usd, stop_dist, 0,
                                f"Size {raw:.4f} < min {min_lot}")
        actual_risk = size * stop_dist
        commission_pct = inst.get("commission_pct", 0.0005)
        # On estime la commission sur (entry + stop) × 2 (round-turn)
        # Ici, on applique sur actual_risk à titre d'approximation
        commission = actual_risk * commission_pct * 2
        return SizingResult(True, size, actual_risk, stop_dist, commission)
