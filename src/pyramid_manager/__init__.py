"""
Pyramid Manager — ajout de positions sur setups forts en profit.

Règle : si trade va à +1R ET nouveau setup same-side validé → ajout position (risque 0.3%).
Max 2 ajouts. Chaque ajout a son propre SL sur la structure locale.
"""
from .manager import PyramidManager, PyramidAddOrder, PyramidState

__all__ = ["PyramidManager", "PyramidAddOrder", "PyramidState"]
