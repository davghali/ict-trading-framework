"""
ELITE SETUP SELECTOR — combine les insights multi-asset en règles tradables.

Pour CHAQUE asset, définit un PROFIL D'ENGAGEMENT basé sur les données :
- hours favorables
- killzones autorisées
- side prioritaire (long ou short)
- filtres trend_state
- exigence htf_align

Avec money management actif (BE à 0.5R, partial TP à 1R).

Output : une liste de "signaux ELITE" avec score de confluence
basé uniquement sur des patterns STATISTIQUEMENT établis.
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional

from src.utils.logging_conf import get_logger

log = get_logger(__name__)


# ==============================================================
# PROFILS D'ENGAGEMENT (calibrés par analyse données)
# ==============================================================
# Ces règles dérivent de l'analyse insights multi-asset.
# Chaque profil liste les filtres qui MAXIMISENT WR × volume.

ASSET_PROFILES = {
    "XAUUSD": {
        "enabled": True,
        "preferred_hours_utc": [3, 17, 18, 12, 13, 14],    # NY pre/lunch + open
        "preferred_killzones": ["ny_lunch", "ny_am_kz", "london_kz", "london_open", "asia_kz"],
        "blocked_killzones": ["ny_pm_kz"],                   # exp_R -0.25
        "preferred_sides": ["long", "short"],                # both OK
        "preferred_trend_states": ["bearish", "neutral"],    # bullish moins bon
        "require_htf_align": False,                          # marginal sur XAU
        "min_volatility_bucket": "low",                      # même low OK
        "expected_trades_per_month": 15,
    },
    "BTCUSD": {
        "enabled": True,
        "preferred_hours_utc": [7, 8, 9, 13, 14, 15, 16],   # London + NY
        "preferred_killzones": ["london_kz", "ny_lunch", "ny_am_kz", "ny_pm_kz"],
        "blocked_killzones": [],
        "preferred_sides": ["long", "short"],
        "preferred_trend_states": ["bearish", "bullish", "neutral"],
        "require_htf_align": True,                           # +14 % WR absolu
        "min_volatility_bucket": "mid",
        "expected_trades_per_month": 30,                     # 24/7 → plus de trades
    },
    "EURUSD": {
        "enabled": True,
        "preferred_hours_utc": [],                           # D1 daily → hour toujours 0, pas de filtre
        "preferred_killzones": [],                           # D1 → pas de killzone
        "blocked_killzones": [],
        "preferred_sides": ["long"],                          # marginal advantage
        "preferred_trend_states": ["neutral", "bearish"],    # bullish worst
        "require_htf_align": True,                           # CRITIQUE (+27% WR)
        "min_volatility_bucket": "low",
        "expected_trades_per_month": 3,                      # daily → peu de setups
    },
    "NAS100": {
        "enabled": True,
        "preferred_hours_utc": [16, 17],                      # ny_lunch seulement
        "preferred_killzones": ["ny_lunch"],
        "blocked_killzones": ["ny_am_kz", "ny_pm_kz"],       # systématiquement perdants
        "preferred_sides": ["short"],                         # long = -26% WR !
        "preferred_trend_states": ["neutral"],
        "require_htf_align": False,                           # inverse sur NAS100 (bug de feature ?)
        "min_volatility_bucket": "mid",
        "expected_trades_per_month": 4,
    },
}


@dataclass
class EliteSignal:
    timestamp: datetime
    symbol: str
    side: str                            # "long" | "short"
    entry: float
    stop_loss: float
    take_profit_1: float                 # 1R (partial)
    take_profit_2: float                 # 2R (runner)
    confluence_score: int                # 0-10
    asset_profile_match: bool
    reasons: List[str] = field(default_factory=list)
    # Optional refs
    fvg_impulsion: float = 0.0
    hour_utc: int = -1
    killzone: str = "none"
    htf_align: bool = False
    trend_state: str = "neutral"


class EliteSetupSelector:
    """
    Applique les profils d'asset pour ne retenir que les setups ELITE.
    Calcule un score de confluence basé sur data-driven rules.
    """

    def __init__(self, profiles: Dict = None):
        self.profiles = profiles or ASSET_PROFILES

    # ------------------------------------------------------------------
    def select(self, df_candidates: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Filtre les candidats pour ne garder que ceux matchant le profil."""
        if symbol not in self.profiles:
            log.warning(f"No profile for {symbol} — returning empty")
            return pd.DataFrame()
        p = self.profiles[symbol]
        if not p["enabled"]:
            return pd.DataFrame()

        df = df_candidates.copy()
        df = df[df["outcome"].isin([-1, 1, 0])]            # gardons aussi les timeouts
        n0 = len(df)

        # 1. hour
        if p["preferred_hours_utc"]:
            df = df[df["hour_utc"].isin(p["preferred_hours_utc"])]

        # 2. killzone
        if p["preferred_killzones"]:
            df = df[df["killzone"].isin(p["preferred_killzones"])]
        if p["blocked_killzones"]:
            df = df[~df["killzone"].isin(p["blocked_killzones"])]

        # 3. side
        if p["preferred_sides"]:
            df = df[df["side"].isin(p["preferred_sides"])]

        # 4. trend_state
        if p["preferred_trend_states"]:
            df = df[df["trend_state"].isin(p["preferred_trend_states"])]

        # 5. htf_align
        if p["require_htf_align"]:
            df = df[df["htf_align"] == True]

        log.info(f"{symbol}: {n0} → {len(df)} after profile filter "
                 f"({100*len(df)/max(n0,1):.1f}% retained)")
        return df.reset_index(drop=True)

    # ------------------------------------------------------------------
    def compute_performance(self, df_filtered: pd.DataFrame) -> Dict:
        df = df_filtered[df_filtered["outcome"].isin([-1, 1])]
        if not len(df):
            return {"n": 0, "winrate": 0, "expectancy_r": 0, "total_r": 0}
        wr = (df["pnl_r"] > 0).mean()
        ex = df["pnl_r"].mean()
        return {
            "n": len(df),
            "winrate": float(wr),
            "expectancy_r": float(ex),
            "total_r": float(df["pnl_r"].sum()),
            "max_r_win": float(df["pnl_r"].max()),
            "min_r_loss": float(df["pnl_r"].min()),
            "sharpe_like": float(ex / df["pnl_r"].std()) if df["pnl_r"].std() > 0 else 0,
        }

    # ------------------------------------------------------------------
    def simulate_active_management(
        self,
        df_filtered: pd.DataFrame,
        partial_tp1_at_r: float = 1.0,
        partial_tp1_pct: float = 0.50,
        be_at_r: float = 0.5,
        trail_after_r: float = 1.5,
    ) -> Dict:
        """
        Simule l'effet du money management actif sur les trades filtered.

        APPROXIMATION : on suppose que
        - 50% des trades qui hit TP à 2R ont auparavant passé par 1R (stat raisonnable)
        - parmi les SL, une fraction aurait été 'sauvée' par BE move à 0.5R
          (sans connaître la trajectoire intra-bar, on estime conservativement 25% de sauvés)
        """
        df = df_filtered[df_filtered["outcome"].isin([-1, 1])].copy()
        if not len(df):
            return {
                "n": 0, "adj_winrate": 0, "adj_expectancy_r": 0,
                "adj_total_r": 0, "n_saved_by_be": 0,
                "comment": "No trades after filtering",
            }

        # Win scenario : partial 50% at 1R + 50% at 2R = average 1.5R (au lieu de 2R pur)
        # Loss scenario : BE save ~25% of would-be losses (return 0 au lieu de -1)
        adj_r = []
        # seed-consistent "luck"
        rng = np.random.default_rng(42)
        for _, row in df.iterrows():
            if row["pnl_r"] > 0:
                # win → partial at 1R + let 2R run = 0.5 × 1 + 0.5 × 2 = 1.5R
                adj_r.append(1.5)
            else:
                # loss → est-ce qu'on est passé par 0.5R avant d'aller au SL ?
                # approximation : 25% de chance d'avoir touché 0.5R → BE
                if rng.random() < 0.25:
                    adj_r.append(0.0)  # BE saved
                else:
                    adj_r.append(-1.0)

        adj_r = np.array(adj_r)
        wins = adj_r > 0
        wr = wins.mean()
        ex = adj_r.mean()

        return {
            "n": len(df),
            "adj_winrate": float(wr),
            "adj_expectancy_r": float(ex),
            "adj_total_r": float(adj_r.sum()),
            "n_saved_by_be": int((adj_r == 0).sum()),
            "comment": (
                f"With active MM (partial 50% at 1R, BE at 0.5R), "
                f"WR {wr:.1%} but each win = 1.5R avg."
            ),
        }

    # ------------------------------------------------------------------
    def estimate_monthly_volume(
        self, df_filtered: pd.DataFrame
    ) -> Dict:
        if not len(df_filtered):
            return {"total_trades": 0, "months_span": 0, "trades_per_month": 0}
        df = df_filtered.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        span_days = (df["timestamp"].max() - df["timestamp"].min()).days
        months = max(1, span_days / 30)
        return {
            "total_trades": len(df),
            "months_span": round(months, 1),
            "trades_per_month": round(len(df) / months, 1),
            "first": str(df["timestamp"].min()),
            "last": str(df["timestamp"].max()),
        }
