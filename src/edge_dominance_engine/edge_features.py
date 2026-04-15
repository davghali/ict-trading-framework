"""
PHASE 2 — FEATURE EXPLOSION.

Enrichit chaque candidat avec un vecteur contextuel complet.
Rien n'est omis. La data décidera quelles features portent un edge.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import List

from src.edge_dominance_engine.edge_generator import EdgeCandidate
from src.utils.sessions import which_session, which_killzone
from src.utils.types import Side
from src.ict_engine.structure import MarketStructure, TrendState
from src.ict_engine.liquidity import LiquidityDetector
from src.bias_engine import BiasEngine
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


class EdgeFeatureBuilder:

    def __init__(self, use_htf_bias: bool = True):
        self.use_htf = use_htf_bias
        self.ms = MarketStructure()
        self.liq = LiquidityDetector()
        self.bias_engine = BiasEngine()

    def enrich(
        self,
        candidates: List[EdgeCandidate],
        df_ltf: pd.DataFrame,
        df_daily: pd.DataFrame | None = None,
        df_weekly: pd.DataFrame | None = None,
        df_h4: pd.DataFrame | None = None,
    ) -> List[EdgeCandidate]:
        # Pre-compute structural context on full df (causal: only use t<fvg.index)
        swings = self.ms._find_swings(df_ltf)
        swings_by_idx = {s.index: s for s in swings}

        # Pre-compute liquidity pools once
        pools = self.liq.detect_session_levels(df_ltf)
        self.liq.mark_sweeps(pools, df_ltf)

        # Volatility bucket thresholds (from realized_vol_20)
        if "realized_vol_20" in df_ltf.columns:
            vol_p25 = df_ltf["realized_vol_20"].quantile(0.33)
            vol_p75 = df_ltf["realized_vol_20"].quantile(0.67)
        else:
            vol_p25 = vol_p75 = np.nan

        # BB width percentile ranking (causal-ish : whole series)
        bbw = df_ltf.get("bb_width")
        if bbw is not None:
            bbw_rank = bbw.rank(pct=True)
        else:
            bbw_rank = None

        # Cache bias par date
        bias_cache: dict = {}

        for cand in candidates:
            ts = pd.Timestamp(cand.timestamp)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")

            # Temporal
            cand.hour_utc = ts.hour
            cand.day_of_week = ts.dayofweek
            cand.session = which_session(ts.to_pydatetime()) or "off"
            cand.killzone = which_killzone(ts.to_pydatetime()) or "none"

            # Market context
            if cand.index < len(df_ltf):
                row = df_ltf.iloc[cand.index]
                cand.atr_pct = float(row.get("atr_pct", 0.0) or 0.0)
                cand.realized_vol_20 = float(row.get("realized_vol_20", 0.0) or 0.0)
                if not np.isnan(vol_p25) and cand.realized_vol_20 > 0:
                    if cand.realized_vol_20 < vol_p25:
                        cand.volatility_bucket = "low"
                    elif cand.realized_vol_20 < vol_p75:
                        cand.volatility_bucket = "mid"
                    else:
                        cand.volatility_bucket = "high"
                cand.adx_14 = float(row.get("adx_14", 0.0) or 0.0)
                if bbw_rank is not None and cand.index < len(bbw_rank):
                    cand.bb_width_percentile = float(bbw_rank.iloc[cand.index] or 0.5)

                cand.dist_to_swing_h_atr = float(row.get("dist_to_swing_h_atr", 0.0) or 0.0)
                cand.dist_to_swing_l_atr = float(row.get("dist_to_swing_l_atr", 0.0) or 0.0)
                cand.bos_up_recent = bool(row.get("bos_up", 0))
                cand.bos_down_recent = bool(row.get("bos_down", 0))

            # Trend state (causal : utiliser subset)
            sub = df_ltf.iloc[max(0, cand.index - 200): cand.index]
            if len(sub) > 20:
                tr = self.ms._current_trend(self.ms._find_swings(sub))
                cand.trend_state = tr.value

            # Liquidity sweep dans les 24h avant le candidat
            lookback_hours = 24
            recent_sweeps = [
                p for p in pools
                if p.swept and p.swept_at is not None
                and (cand.timestamp - p.swept_at).total_seconds() <= lookback_hours * 3600
                and (cand.timestamp - p.swept_at).total_seconds() >= 0
            ]
            from src.utils.types import LiquidityType
            lows = {LiquidityType.PDL, LiquidityType.PWL, LiquidityType.PML,
                    LiquidityType.EQL, LiquidityType.SESSION_LOW}
            highs = {LiquidityType.PDH, LiquidityType.PWH, LiquidityType.PMH,
                     LiquidityType.EQH, LiquidityType.SESSION_HIGH}
            cand.recent_sweep_low = any(p.ltype in lows for p in recent_sweeps)
            cand.recent_sweep_high = any(p.ltype in highs for p in recent_sweeps)

            # Distance au pool le plus proche NON swept
            available = [p for p in pools if not p.swept]
            if available and cand.entry > 0:
                closest = min(available, key=lambda p: abs(p.price - cand.entry))
                atr = df_ltf[self.ms._find_swings.__globals__.get("atr_col", "atr_14") if False else "atr_14"].iloc[cand.index]
                if atr and atr > 0:
                    cand.dist_to_nearest_liquidity_atr = float(abs(closest.price - cand.entry) / atr)

            # HTF bias
            if self.use_htf and df_weekly is not None and df_daily is not None and df_h4 is not None:
                date_key = ts.date()
                if date_key not in bias_cache:
                    try:
                        bias_cache[date_key] = self.bias_engine.assess(
                            df_weekly, df_daily, df_h4, ts.to_pydatetime()
                        )
                    except Exception:
                        bias_cache[date_key] = None
                b = bias_cache[date_key]
                if b is not None:
                    cand.htf_bias = b.direction.value
                    cand.htf_align = (
                        (cand.side == Side.LONG and b.direction.value == "bullish") or
                        (cand.side == Side.SHORT and b.direction.value == "bearish")
                    )

        log.info(f"Enriched {len(candidates)} candidates with full feature context")
        return candidates
