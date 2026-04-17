"""
Auto Execution — Full-auto trading engine for ICT Cyborg Ultimate.

Place les ordres automatiquement sur MT5 à la détection de signaux A+.
Gère les exits multi-partials via un position manager threadé.
Supporte /pause et /resume via Telegram pour arrêt d'urgence.
"""
from .auto_executor import AutoExecutor, AutoExecutionConfig
from .position_manager import PositionManager, ManagedPosition

__all__ = [
    "AutoExecutor",
    "AutoExecutionConfig",
    "PositionManager",
    "ManagedPosition",
]
