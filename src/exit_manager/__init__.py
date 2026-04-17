"""
Exit Manager — gestion multi-partials + trailing runner.

Remplace le TP fixe 2R par une stratégie de sortie optimisée :
- 25% @ 1R (SL → entry)
- 25% @ 2R (SL → entry + 0.5R)
- 25% @ 3R (SL → entry + 1.5R)
- 25% runner → trailing ATR, target min 5R
"""
from .manager import ExitManager, ExitLevel, ExitPlan

__all__ = ["ExitManager", "ExitLevel", "ExitPlan"]
