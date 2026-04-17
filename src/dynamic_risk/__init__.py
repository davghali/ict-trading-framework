"""
Dynamic Risk Manager — anti-martingale adaptatif.

Augmente le risque après hot streaks, diminue après cold streaks.
Plafond strict (max 1.0%) et plancher (min 0.25%).
"""
from .manager import DynamicRiskManager, RiskState, RiskDecision

__all__ = ["DynamicRiskManager", "RiskState", "RiskDecision"]
