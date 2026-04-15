"""
PHASE 1 — GENERATION MASSIVE.

NE FILTRE RIEN. Génère un candidat de trade pour CHAQUE FVG détecté,
dans LES DEUX sens (long/short, peu importe le HTF), peu importe la session,
peu importe la liquidité.

On simule chaque trade jusqu'à TP1 (2R) ou SL (1R) et on enregistre l'issue.

Objectif : créer un ÉCHANTILLON massif et NON BIAISÉ pour le pattern mining.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
import numpy as np
import pandas as pd

from src.utils.types import FVG, OrderBlock, BreakerBlock, LiquidityPool, Side
from src.ict_engine import (
    FVGDetector, OrderBlockDetector, BreakerBlockDetector, LiquidityDetector,
    MarketStructure,
)
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class EdgeCandidate:
    """Un trade candidat brut, pré-simulation."""
    symbol: str
    timestamp: datetime
    index: int
    side: Side
    entry: float
    stop_loss: float
    take_profit: float                  # TP unique pour simplicité (RR=2)
    # Contexte structurel
    fvg_size_atr: float = 0.0
    fvg_impulsion: float = 0.0
    fvg_irl_erl: str = "unknown"
    has_ob: bool = False
    has_bb_ifvg: bool = False
    # Contexte temporel (rempli par FeatureBuilder)
    hour_utc: int = -1
    day_of_week: int = -1
    session: str = "unknown"
    killzone: str = "none"
    # Contexte marché
    atr_pct: float = 0.0
    realized_vol_20: float = 0.0
    volatility_bucket: str = "unknown"      # low/mid/high
    bb_width_percentile: float = 0.5
    adx_14: float = 0.0
    trend_state: str = "neutral"
    # Liquidité
    recent_sweep_low: bool = False
    recent_sweep_high: bool = False
    dist_to_nearest_liquidity_atr: float = 0.0
    # Structure
    bos_up_recent: bool = False
    bos_down_recent: bool = False
    dist_to_swing_h_atr: float = 0.0
    dist_to_swing_l_atr: float = 0.0
    # HTF align (calculé par FeatureBuilder)
    htf_bias: str = "neutral"
    htf_align: bool = False
    # Simulation outcome (rempli après run)
    outcome: Optional[int] = None            # +1 (TP), -1 (SL), 0 (timeout)
    bars_to_outcome: int = 0
    pnl_r: float = 0.0


class EdgeCandidateGenerator:
    """
    Génère des candidats à partir de CHAQUE FVG détecté, sans filtre.
    """

    def __init__(
        self,
        rr_target: float = 2.0,
        sl_buffer_atr: float = 0.3,
        timeout_bars: int = 300,            # si ni TP ni SL après N bars, timeout
        atr_col: str = "atr_14",
    ):
        self.rr = rr_target
        self.sl_buffer = sl_buffer_atr
        self.timeout = timeout_bars
        self.atr_col = atr_col

    def generate(
        self,
        symbol: str,
        df: pd.DataFrame,
    ) -> List[EdgeCandidate]:
        fvgs = FVGDetector(
            min_size_atr=0.1,          # très permissif (tout FVG)
            displacement_min=1.0,      # très permissif
            close_in_range_min=0.55,
        ).detect(df, atr_col=self.atr_col)

        obs = OrderBlockDetector(atr_col=self.atr_col).detect(df, fvgs)
        bbs = BreakerBlockDetector().detect(df, obs, fvgs)
        liq_map = LiquidityDetector().detect_all(df)
        struct = MarketStructure().analyze(df)
        swings = struct["swings"]

        ob_by_fvg = {o.associated_fvg_index: o for o in obs}
        bb_by_fvg = {b.origin_ob_index: b for b in bbs}   # approximation

        candidates: List[EdgeCandidate] = []
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values

        for fvg in fvgs:
            atr = df[self.atr_col].iloc[fvg.index]
            if pd.isna(atr) or atr <= 0:
                continue

            # Entry = CE (midpoint)
            entry = fvg.ce
            if fvg.side == Side.LONG:
                sl = fvg.bottom - self.sl_buffer * atr
                tp = entry + self.rr * (entry - sl)
            else:
                sl = fvg.top + self.sl_buffer * atr
                tp = entry - self.rr * (sl - entry)

            if abs(entry - sl) <= 0:
                continue

            cand = EdgeCandidate(
                symbol=symbol,
                timestamp=df.index[fvg.index].to_pydatetime(),
                index=fvg.index,
                side=fvg.side,
                entry=float(entry),
                stop_loss=float(sl),
                take_profit=float(tp),
                fvg_size_atr=float(fvg.size_in_atr),
                fvg_impulsion=float(fvg.impulsion_score),
                fvg_irl_erl=fvg.irl_erl,
                has_ob=fvg.index in ob_by_fvg,
                has_bb_ifvg=False,                   # renseigné plus bas
            )
            candidates.append(cand)

        log.info(f"Generated {len(candidates)} raw candidates (no filter)")
        return candidates

    # ------------------------------------------------------------------
    def simulate(
        self,
        candidates: List[EdgeCandidate],
        df: pd.DataFrame,
    ) -> List[EdgeCandidate]:
        """
        Simule chaque candidat jusqu'à TP/SL/timeout.
        Assume entry fill à CE si price y passe, sinon aborted.
        """
        h = df["high"].values
        l = df["low"].values
        c = df["close"].values
        o = df["open"].values
        n = len(df)

        filled = 0
        tp_count = sl_count = timeout_count = 0

        for cand in candidates:
            start = cand.index + 1           # on entre sur la bar suivante
            # Find first bar where price touches CE
            fill_idx = None
            for k in range(start, min(start + 30, n)):       # attend 30 bars max pour fill
                if cand.side == Side.LONG:
                    if l[k] <= cand.entry <= h[k] or l[k] <= cand.entry:
                        fill_idx = k
                        break
                else:
                    if l[k] <= cand.entry <= h[k] or h[k] >= cand.entry:
                        fill_idx = k
                        break

            if fill_idx is None:
                cand.outcome = None            # never filled
                continue
            filled += 1

            # Simulate hit on TP or SL
            end = min(fill_idx + self.timeout, n)
            outcome = 0
            bars = 0
            for j in range(fill_idx, end):
                bars = j - fill_idx
                if cand.side == Side.LONG:
                    if l[j] <= cand.stop_loss:
                        outcome = -1
                        sl_count += 1
                        break
                    if h[j] >= cand.take_profit:
                        outcome = 1
                        tp_count += 1
                        break
                else:
                    if h[j] >= cand.stop_loss:
                        outcome = -1
                        sl_count += 1
                        break
                    if l[j] <= cand.take_profit:
                        outcome = 1
                        tp_count += 1
                        break
            else:
                timeout_count += 1

            cand.outcome = outcome
            cand.bars_to_outcome = bars
            cand.pnl_r = float(self.rr) if outcome == 1 else (-1.0 if outcome == -1 else 0.0)

        log.info(
            f"Simulation done. Filled: {filled}/{len(candidates)} "
            f"(TP: {tp_count}, SL: {sl_count}, timeout: {timeout_count})"
        )
        return [c for c in candidates if c.outcome is not None]

    # ------------------------------------------------------------------
    def to_dataframe(self, candidates: List[EdgeCandidate]) -> pd.DataFrame:
        if not candidates:
            return pd.DataFrame()
        rows = []
        for c in candidates:
            d = vars(c).copy()
            d["side"] = c.side.value
            rows.append(d)
        return pd.DataFrame(rows)
