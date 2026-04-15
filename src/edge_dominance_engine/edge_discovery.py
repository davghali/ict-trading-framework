"""
PHASE 3 — EDGE DISCOVERY.

Pattern mining multi-dimensionnel pour découvrir des CONDITIONS STATISTIQUES
où l'edge existe réellement.

Méthodes combinées :
1. Analyse univariée par feature (winrate conditionnel)
2. Analyse bivariée (interactions)
3. Arbre de décision shallow (interprétable, CART-style)
4. Ranking par (winrate × stabilité × fréquence)

On ne cherche PAS à maximiser le winrate seul — on cherche une
configuration REPRODUCTIBLE et STABLE.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Any

from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class EdgeCondition:
    """Une condition statistiquement identifiée."""
    description: str
    filters: Dict[str, Any]              # ex: {"killzone": "ny_am_kz", "htf_align": True}
    n_samples: int
    winrate: float
    expectancy_r: float
    rr: float                             # ratio win/loss en R
    sharpe_like: float                    # mean / std des pnl_r
    stability_score: float                # 0-1 via subsampling
    quality_score: float                  # agrégé


class EdgeDiscovery:

    def __init__(
        self,
        rr_target: float = 2.0,
        min_samples: int = 30,
        min_winrate: float = 0.55,
        min_expectancy: float = 0.10,
        stability_subsamples: int = 20,
        stability_fraction: float = 0.5,
    ):
        self.rr = rr_target
        self.min_n = min_samples
        self.min_wr = min_winrate
        self.min_ex = min_expectancy
        self.stab_samples = stability_subsamples
        self.stab_frac = stability_fraction

    # ------------------------------------------------------------------
    def discover(self, df: pd.DataFrame) -> List[EdgeCondition]:
        """
        df : un DataFrame où chaque ligne = un trade simulé avec features + pnl_r.
        """
        # Guard : empty or missing columns
        if df is None or len(df) == 0 or "outcome" not in df.columns or "pnl_r" not in df.columns:
            log.warning("Empty / invalid input for discovery — returning []")
            return []
        # On ne garde que les candidats filled (outcome != None et != 0 pour WR valide)
        df = df[df["outcome"].isin([-1, 1])].copy()
        if len(df) < self.min_n:
            log.warning(f"Not enough simulated trades ({len(df)}) for discovery")
            return []

        # Baseline
        baseline_wr = (df["pnl_r"] > 0).mean()
        baseline_ex = df["pnl_r"].mean()
        log.info(f"Baseline (no filter) : n={len(df)}, WR={baseline_wr:.3f}, "
                 f"exp_R={baseline_ex:.3f}")

        edges: List[EdgeCondition] = []

        # --- 1. Analyse univariée
        univariate_features = [
            "killzone", "session", "hour_utc", "day_of_week",
            "volatility_bucket", "trend_state", "htf_bias", "htf_align",
            "fvg_irl_erl", "has_ob", "has_bb_ifvg",
            "recent_sweep_low", "recent_sweep_high",
            "bos_up_recent", "bos_down_recent", "side",
        ]
        for feat in univariate_features:
            if feat not in df.columns:
                continue
            for val in df[feat].dropna().unique():
                sub = df[df[feat] == val]
                edge = self._eval_subset(sub, {feat: val})
                if edge is not None:
                    edges.append(edge)

        # --- 2. Analyse bivariée (combinaisons de 2 features discriminantes)
        discriminant = ["killzone", "volatility_bucket", "htf_align",
                        "recent_sweep_low", "recent_sweep_high", "side",
                        "trend_state", "fvg_irl_erl"]
        for i, f1 in enumerate(discriminant):
            if f1 not in df.columns:
                continue
            for f2 in discriminant[i + 1:]:
                if f2 not in df.columns:
                    continue
                for v1 in df[f1].dropna().unique():
                    for v2 in df[f2].dropna().unique():
                        sub = df[(df[f1] == v1) & (df[f2] == v2)]
                        edge = self._eval_subset(sub, {f1: v1, f2: v2})
                        if edge is not None:
                            edges.append(edge)

        # --- 3. Binning quantitatif (FVG impulsion, volatility, adx)
        for feat, bins in [
            ("fvg_impulsion", [0, 0.5, 1.0, 1.5, 3.0]),
            ("adx_14", [0, 15, 22, 30, 60]),
            ("dist_to_nearest_liquidity_atr", [0, 1, 2, 5, 100]),
        ]:
            if feat not in df.columns:
                continue
            df[f"{feat}_bin"] = pd.cut(df[feat], bins=bins, include_lowest=True)
            for val in df[f"{feat}_bin"].dropna().unique():
                sub = df[df[f"{feat}_bin"] == val]
                edge = self._eval_subset(sub, {feat: str(val)})
                if edge is not None:
                    edges.append(edge)

        # --- 4. Trivariate focused : (killzone, side, htf_align)
        for kz in df["killzone"].dropna().unique():
            for side in df["side"].dropna().unique():
                for align in [True, False]:
                    sub = df[(df["killzone"] == kz) & (df["side"] == side) & (df["htf_align"] == align)]
                    edge = self._eval_subset(sub, {
                        "killzone": kz, "side": side, "htf_align": align,
                    })
                    if edge is not None:
                        edges.append(edge)

        # Dedup + sort
        unique = {}
        for e in edges:
            key = tuple(sorted(e.filters.items()))
            if key not in unique or e.quality_score > unique[key].quality_score:
                unique[key] = e
        edges = sorted(unique.values(), key=lambda e: e.quality_score, reverse=True)

        log.info(f"Discovered {len(edges)} candidate edges passing thresholds")
        return edges

    # ------------------------------------------------------------------
    def _eval_subset(self, sub: pd.DataFrame, filters: Dict[str, Any]) -> EdgeCondition | None:
        n = len(sub)
        if n < self.min_n:
            return None
        wr = (sub["pnl_r"] > 0).mean()
        ex = sub["pnl_r"].mean()
        if wr < self.min_wr or ex < self.min_ex:
            return None

        wins = sub[sub["pnl_r"] > 0]["pnl_r"]
        losses = sub[sub["pnl_r"] < 0]["pnl_r"]
        avg_win = wins.mean() if len(wins) else 0
        avg_loss = abs(losses.mean()) if len(losses) else 1
        rr = avg_win / avg_loss if avg_loss > 0 else float("inf")

        sd = sub["pnl_r"].std()
        sharpe_like = ex / sd if sd > 0 else 0

        # Stability via bootstrap
        stab = self._stability_score(sub)

        # Quality score (agrégé)
        # On veut : WR élevé × stabilité × volume suffisant
        volume_bonus = min(1.0, n / 200.0)            # plafonne à 200 trades
        quality = wr * stab * (1 + sharpe_like) * volume_bonus

        desc = " AND ".join([f"{k}={v}" for k, v in filters.items()])

        return EdgeCondition(
            description=desc,
            filters=filters,
            n_samples=n,
            winrate=float(wr),
            expectancy_r=float(ex),
            rr=float(rr),
            sharpe_like=float(sharpe_like),
            stability_score=float(stab),
            quality_score=float(quality),
        )

    def _stability_score(self, sub: pd.DataFrame) -> float:
        """Bootstrap : tire des sous-échantillons et mesure la variance du WR."""
        if len(sub) < 20:
            return 0.0
        rng = np.random.default_rng(42)
        wrs = []
        sample_size = max(10, int(len(sub) * self.stab_frac))
        for _ in range(self.stab_samples):
            idx = rng.choice(sub.index, size=sample_size, replace=True)
            samp = sub.loc[idx]
            wrs.append((samp["pnl_r"] > 0).mean())
        wr_std = np.std(wrs)
        # Plus std est faible, plus c'est stable
        stability = max(0.0, 1.0 - wr_std * 5)       # scale 0-1
        return float(stability)

    # ------------------------------------------------------------------
    def summarize(self, edges: List[EdgeCondition], top_n: int = 15) -> pd.DataFrame:
        if not edges:
            return pd.DataFrame()
        rows = []
        for e in edges[:top_n]:
            rows.append({
                "description": e.description,
                "n": e.n_samples,
                "WR": round(e.winrate, 3),
                "exp_R": round(e.expectancy_r, 3),
                "RR": round(e.rr, 2),
                "sharpe-ish": round(e.sharpe_like, 3),
                "stability": round(e.stability_score, 3),
                "quality": round(e.quality_score, 3),
            })
        return pd.DataFrame(rows)
