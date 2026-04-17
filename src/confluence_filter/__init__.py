"""
Confluence Filter — filtrage ultra-strict avec score multi-facteurs.

Ne laisse passer que les setups avec :
- Multi-TF alignment (W+D+H4 tous d'accord)
- SMT divergence présente
- Liquidity sweep récent
- Cross-asset alignment (DXY/VIX)
- Killzone active
- Volume spike
"""
from .filter import ConfluenceFilter, ConfluenceResult, ConfluenceScore

__all__ = ["ConfluenceFilter", "ConfluenceResult", "ConfluenceScore"]
