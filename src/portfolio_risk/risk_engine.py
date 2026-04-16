"""
PORTFOLIO RISK ENGINE — empêche la sur-concentration cross-positions.

Principes :
- Corrélation matrix entre assets
- Heat total (somme des R à risque)
- Bloque nouveaux trades si :
  * Heat total > 3% (3 positions 0.5% + 1 corrélé = 3%)
  * Nouvelle position crée > 0.70 corrélation avec existante
  * Déjà 3 positions du même "groupe" (metals, indices, crypto, forex)

Groupes corrélés ICT :
- Metals : XAUUSD, XAGUSD
- Indices : NAS100, SPX500, DOW30
- Crypto : BTCUSD, ETHUSD
- USD Long : USDJPY, USDCAD (long USD)
- USD Short : EURUSD, GBPUSD, AUDUSD (short USD)
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from src.utils.logging_conf import get_logger

log = get_logger(__name__)


ASSET_GROUPS = {
    "XAUUSD": "metals", "XAGUSD": "metals",
    "NAS100": "indices", "SPX500": "indices", "DOW30": "indices",
    "BTCUSD": "crypto", "ETHUSD": "crypto",
    "USDJPY": "usd_long", "USDCAD": "usd_long",
    "EURUSD": "usd_short", "GBPUSD": "usd_short", "AUDUSD": "usd_short",
}

# Corrélations connues (simplifiées)
CORRELATION_MATRIX = {
    ("XAUUSD", "XAGUSD"): 0.85,
    ("NAS100", "SPX500"): 0.90,
    ("NAS100", "DOW30"):  0.80,
    ("SPX500", "DOW30"):  0.85,
    ("BTCUSD", "ETHUSD"): 0.75,
    ("BTCUSD", "NAS100"): 0.50,
    ("ETHUSD", "NAS100"): 0.45,
    ("EURUSD", "GBPUSD"): 0.70,
    ("EURUSD", "AUDUSD"): 0.55,
    ("USDJPY", "USDCAD"): 0.45,
}


def get_correlation(a: str, b: str) -> float:
    """Retourne |corrélation| entre deux assets (0-1)."""
    if a == b:
        return 1.0
    key = tuple(sorted([a, b]))
    return abs(CORRELATION_MATRIX.get(key, CORRELATION_MATRIX.get((b, a), 0.0)))


@dataclass
class OpenPosition:
    """Une position ouverte pour le calcul de risque."""
    symbol: str
    side: str
    risk_pct: float     # % du capital à risque
    account_id: str = ""


@dataclass
class RiskAssessment:
    allow: bool
    total_heat_before: float
    total_heat_after: float
    max_correlation: float
    correlated_asset: str = ""
    group_exposure: Dict[str, int] = field(default_factory=dict)
    reason: str = ""


class PortfolioRisk:

    def __init__(
        self,
        max_total_heat_pct: float = 3.0,     # heat max à risque total
        max_correlation: float = 0.70,       # corrélation max entre 2 positions
        max_per_group: int = 2,              # max positions par groupe
    ):
        self.max_heat = max_total_heat_pct
        self.max_corr = max_correlation
        self.max_group = max_per_group

    # ------------------------------------------------------------------
    def assess_new_trade(
        self,
        new_symbol: str,
        new_risk_pct: float,
        open_positions: List[OpenPosition],
    ) -> RiskAssessment:
        """
        Peut-on ajouter une nouvelle position sans blow-up portfolio ?
        """
        # Heat cumulé
        heat_before = sum(p.risk_pct for p in open_positions)
        heat_after = heat_before + new_risk_pct

        # Group exposure
        group_exposure = {}
        for p in open_positions:
            g = ASSET_GROUPS.get(p.symbol, "other")
            group_exposure[g] = group_exposure.get(g, 0) + 1

        new_group = ASSET_GROUPS.get(new_symbol, "other")
        new_group_count = group_exposure.get(new_group, 0) + 1

        # Max correlation with existing
        max_corr = 0.0
        corr_asset = ""
        for p in open_positions:
            c = get_correlation(new_symbol, p.symbol)
            if c > max_corr:
                max_corr = c
                corr_asset = p.symbol

        # Decision
        if heat_after > self.max_heat:
            return RiskAssessment(
                allow=False,
                total_heat_before=heat_before, total_heat_after=heat_after,
                max_correlation=max_corr, correlated_asset=corr_asset,
                group_exposure=group_exposure,
                reason=f"Heat total {heat_after:.2f}% > max {self.max_heat}%",
            )

        if max_corr > self.max_corr:
            return RiskAssessment(
                allow=False,
                total_heat_before=heat_before, total_heat_after=heat_after,
                max_correlation=max_corr, correlated_asset=corr_asset,
                group_exposure=group_exposure,
                reason=f"Correlation {max_corr:.2f} with {corr_asset} > max {self.max_corr}",
            )

        if new_group_count > self.max_group:
            return RiskAssessment(
                allow=False,
                total_heat_before=heat_before, total_heat_after=heat_after,
                max_correlation=max_corr, correlated_asset=corr_asset,
                group_exposure=group_exposure,
                reason=f"Group '{new_group}' already has {new_group_count - 1} positions",
            )

        return RiskAssessment(
            allow=True,
            total_heat_before=heat_before, total_heat_after=heat_after,
            max_correlation=max_corr, correlated_asset=corr_asset,
            group_exposure=group_exposure,
            reason="OK",
        )

    # ------------------------------------------------------------------
    def portfolio_snapshot(self, open_positions: List[OpenPosition]) -> Dict:
        heat = sum(p.risk_pct for p in open_positions)
        groups = {}
        for p in open_positions:
            g = ASSET_GROUPS.get(p.symbol, "other")
            groups[g] = groups.get(g, 0) + 1

        # Worst-case scenario (tous les SL touchés)
        worst_case_loss = heat

        return {
            "n_positions": len(open_positions),
            "total_heat_pct": heat,
            "worst_case_loss_pct": worst_case_loss,
            "heat_used_pct": heat / self.max_heat * 100,
            "group_exposure": groups,
            "positions": [
                {"symbol": p.symbol, "side": p.side, "risk_pct": p.risk_pct,
                 "account": p.account_id, "group": ASSET_GROUPS.get(p.symbol, "other")}
                for p in open_positions
            ],
        }
