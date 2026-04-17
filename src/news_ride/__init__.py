"""
News Ride Module — capitalise sur les spikes news au lieu de les éviter.

Stratégie : attendre le spike initial (2-5 min), identifier retracement 61.8%,
entrer SNIPER dans le sens de la structure. Risque réduit 50%.
"""
from .ride import NewsRideModule, NewsRideSignal, NewsRideState

__all__ = ["NewsRideModule", "NewsRideSignal", "NewsRideState"]
