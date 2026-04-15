"""
Expectations — calcule les espérances chiffrées par asset.

Source : max_edge_pareto_*.json (OOS validé par ML).

Pour chaque asset + tier, on sort :
- Trades par semaine
- WR attendu
- Expectancy en R par trade
- Rendement mensuel attendu (avec money management)
- Jours pour passer target FTMO 10%
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional


PAYOUT_MM_MULT = 0.75    # money management actif → 0.75x pure R (partial TP + BE saves)


@dataclass
class AssetExpectation:
    asset: str
    tf: str
    tier: str
    trades_per_week: float
    winrate: float
    expectancy_r: float
    monthly_r_expected: float
    monthly_return_pct_at_risk: Dict[str, float]     # par niveau de risque
    days_to_10pct_at_risk: Dict[str, int]
    data_confidence: str             # "high" / "medium" / "low" basé sur OOS n


@dataclass
class GlobalExpectation:
    total_trades_per_week: float
    blended_winrate: float
    blended_expectancy_r: float
    monthly_return_pct_at_risk: Dict[str, float]
    days_to_pass_ftmo: Dict[str, int]
    worst_case_dd_pct: float            # approximation
    best_day_r: float


def _find_latest_pareto() -> Optional[Dict]:
    rep_dir = Path(__file__).parents[2] / "reports"
    reports = sorted(rep_dir.glob("max_edge_pareto_*.json"))
    if not reports:
        return None
    return json.loads(reports[-1].read_text())


def _tier_for(tier_name: str):
    return {"elite": "🎯 ELITE", "balanced": "⚖ BALANCED", "volume": "🚀 VOLUME"}.get(tier_name, tier_name)


RISK_LEVELS_PCT = [0.25, 0.5, 1.0]    # % du capital par trade


def compute_asset_expectations(tier_name: str = "balanced") -> List[AssetExpectation]:
    """Retourne une ligne par asset pour le tier choisi."""
    data = _find_latest_pareto()
    if data is None:
        return []

    out = []
    for asset, info in data["assets"].items():
        tier = info.get("tiers", {}).get(tier_name)
        if not tier:
            continue

        tpm = tier["trades_per_month"]
        tpw = tpm / 4.33

        wr = tier["winrate_oos"]
        exp_r = tier["expectancy_r_oos"]

        # Apply money management adjustment
        adj_exp_r = exp_r * PAYOUT_MM_MULT

        # Expected R per month
        monthly_r = tpm * adj_exp_r

        # Convert to % return at each risk level
        monthly_pct = {f"{r}%": round(monthly_r * r, 2) for r in RISK_LEVELS_PCT}

        # Days to FTMO 10%
        days = {}
        for r in RISK_LEVELS_PCT:
            daily_r = tpm / 22 * adj_exp_r    # ~22 jours de trading/mois
            daily_pct = daily_r * r
            if daily_pct > 0:
                # Compounding : balance × (1 + daily_pct/100)^N = 1.10
                # N = log(1.10) / log(1 + daily_pct/100)
                try:
                    n = math.log(1.10) / math.log(1 + daily_pct / 100)
                    days[f"{r}%"] = max(1, int(math.ceil(n)))
                except Exception:
                    days[f"{r}%"] = 999
            else:
                days[f"{r}%"] = 999

        # Confidence
        n_oos = tier["n_trades_oos"]
        if n_oos >= 100:
            confidence = "high"
        elif n_oos >= 30:
            confidence = "medium"
        else:
            confidence = "low"

        out.append(AssetExpectation(
            asset=asset, tf=info["ltf"], tier=tier_name,
            trades_per_week=round(tpw, 1),
            winrate=round(wr, 3),
            expectancy_r=round(adj_exp_r, 3),
            monthly_r_expected=round(monthly_r, 1),
            monthly_return_pct_at_risk=monthly_pct,
            days_to_10pct_at_risk=days,
            data_confidence=confidence,
        ))
    # sort by monthly R
    out.sort(key=lambda a: a.monthly_r_expected, reverse=True)
    return out


def compute_global(tier_name: str = "balanced") -> Optional[GlobalExpectation]:
    items = compute_asset_expectations(tier_name)
    if not items:
        return None

    tot_tpw = sum(a.trades_per_week for a in items)
    if tot_tpw == 0:
        return None
    tot_tpm = tot_tpw * 4.33

    # Blended WR (weighted by volume)
    blended_wr = sum(a.winrate * a.trades_per_week for a in items) / tot_tpw
    blended_exp_r = sum(a.expectancy_r * a.trades_per_week for a in items) / tot_tpw

    # Monthly return
    monthly_r = tot_tpm * blended_exp_r
    monthly_pct = {f"{r}%": round(monthly_r * r, 2) for r in RISK_LEVELS_PCT}

    # Days to FTMO 10% (compounding at average risk)
    days = {}
    for r in RISK_LEVELS_PCT:
        daily_r = tot_tpm / 22 * blended_exp_r
        daily_pct = daily_r * r
        if daily_pct > 0:
            try:
                n = math.log(1.10) / math.log(1 + daily_pct / 100)
                days[f"{r}%"] = max(1, int(math.ceil(n)))
            except Exception:
                days[f"{r}%"] = 999
        else:
            days[f"{r}%"] = 999

    # Worst case DD (approximation Kelly) ≈ risk × sqrt(trades/month) × 2
    # Conservative estimate
    worst_dd = RISK_LEVELS_PCT[1] * math.sqrt(tot_tpm) * 2

    # Best day R (approx 3 trades × avg R best case)
    best_day_r = 3 * max((a.expectancy_r * 2 for a in items), default=0)

    return GlobalExpectation(
        total_trades_per_week=round(tot_tpw, 1),
        blended_winrate=round(blended_wr, 3),
        blended_expectancy_r=round(blended_exp_r, 3),
        monthly_return_pct_at_risk=monthly_pct,
        days_to_pass_ftmo=days,
        worst_case_dd_pct=round(worst_dd, 1),
        best_day_r=round(best_day_r, 1),
    )
