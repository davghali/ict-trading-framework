"""
EDGE DOMINANCE ENGINE — Phase ultime.

Philosophie : ne présume RIEN. Laisse la DATA décider où un edge existe
(ou prouve qu'il n'en existe pas).

9 phases :
  1. Generation massive (tous les trades candidats, sans filtre)
  2. Feature explosion (vecteur complet par trade)
  3. Edge discovery (pattern mining multi-dim)
  4. Isolation (extraire les conditions gagnantes)
  5. Validation brutale (OOS + cross-asset)
  6. Simulation avancée (Monte Carlo + stress)
  7. Optimisation sans biais (stabilité uniquement)
  8. Test de réalité (slippage/spread/latence)
  9. Destruction des illusions (red team)
"""
from .edge_generator import EdgeCandidateGenerator
from .edge_features import EdgeFeatureBuilder
from .edge_discovery import EdgeDiscovery
from .edge_validator import EdgeValidator
from .edge_reality import RealityStressEngine
from .edge_reporter import EdgeReporter
from .elite_selector import EliteSetupSelector, ASSET_PROFILES
from .maximum_edge import MaximumEdgeEngine, MLEdgeResult, ParetoPoint

__all__ = [
    "EdgeCandidateGenerator",
    "EdgeFeatureBuilder",
    "EdgeDiscovery",
    "EdgeValidator",
    "RealityStressEngine",
    "EdgeReporter",
    "EliteSetupSelector",
    "ASSET_PROFILES",
    "MaximumEdgeEngine",
    "MLEdgeResult",
    "ParetoPoint",
]
