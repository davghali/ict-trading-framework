"""
Execution Engine — génère des SIGNALS candidats à partir des outputs ICT.

Flow strict :
1. Pour chaque bar t :
   a. Reject si off-hours / weekend / news
   b. Reject si pas en killzone
   c. Check biais HTF (Weekly + Daily)
   d. Check regime
   e. Chercher FVG récent non rempli aligné avec biais
   f. Chercher OB valide (avec FVG)
   g. Require : liquidité récente swept dans la bonne direction
   h. Compute SL/TP avec ATR
   i. Compute RR — reject si < 1.8
   j. Score via Scoring Engine
   k. Emit Signal si grade >= B

Discipline :
- ZÉRO trade hors killzone
- ZÉRO trade sans liquidity sweep préalable
- ZÉRO trade sans FVG+OB aligné
- ZÉRO trade si régime = MANIPULATION
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

import pandas as pd

from src.utils.types import (
    Signal, SetupGrade, BiasDirection, Regime, Side, FVG, OrderBlock,
    LiquidityPool, BreakerBlock,
)
from src.utils.sessions import which_killzone
from src.utils.logging_conf import get_logger
from src.scoring_engine import ScoringEngine
from src.bias_engine import BiasEngine
from src.regime_engine import RegimeDetector
from src.ict_engine import (
    FVGDetector, OrderBlockDetector, BreakerBlockDetector, LiquidityDetector,
)

log = get_logger(__name__)


ALLOWED_KILLZONES = {
    "london_open", "london_kz", "ny_am_kz", "ny_open", "ny_pm_kz",
}


class ExecutionEngine:

    def __init__(
        self,
        sl_atr_multiplier: float = 1.2,
        tp1_rr: float = 2.0,
        tp2_rr: float = 3.5,
        min_grade: SetupGrade = SetupGrade.B,
        atr_col: str = "atr_14",
    ):
        self.sl_atr = sl_atr_multiplier
        self.tp1_rr = tp1_rr
        self.tp2_rr = tp2_rr
        self.min_grade = min_grade
        self.atr_col = atr_col

        self.scorer = ScoringEngine()
        self.bias_engine = BiasEngine()
        self.regime_detector = RegimeDetector()
        self.fvg_detector = FVGDetector()
        self.ob_detector = OrderBlockDetector()
        self.bb_detector = BreakerBlockDetector()
        self.liq_detector = LiquidityDetector()

    # ------------------------------------------------------------------
    def generate_signals(
        self,
        symbol: str,
        df_ltf: pd.DataFrame,
        df_weekly: pd.DataFrame,
        df_daily: pd.DataFrame,
        df_h4: pd.DataFrame,
    ) -> List[Signal]:
        """
        Parcourt df_ltf (ex: M15) et produit des signaux.
        Fait les analyses HTF une fois par jour (cache) pour perf.
        """
        signals: List[Signal] = []

        # Pré-calculs : FVG, OB, BB, Liquidité sur df_ltf
        fvgs = self.fvg_detector.detect(df_ltf, atr_col=self.atr_col)
        obs = self.ob_detector.detect(df_ltf, fvgs)
        bbs = self.bb_detector.detect(df_ltf, obs, fvgs)
        liq_map = self.liq_detector.detect_all(df_ltf)

        # Index lookups
        fvgs_by_idx = {f.index: f for f in fvgs}
        obs_by_idx = {o.index: o for o in obs}
        bbs_by_idx = {b.index: b for b in bbs}

        # Cache HTF par date
        bias_cache: dict = {}
        regime_cache: dict = {}

        for t in range(100, len(df_ltf)):
            ts = df_ltf.index[t]
            bar = df_ltf.iloc[t]

            # ----------- A) GATES
            kz = which_killzone(ts.to_pydatetime())
            if kz is None or kz not in ALLOWED_KILLZONES:
                continue
            if bar.get("is_weekend", False):
                continue

            # ----------- B) HTF BIAS (cache par jour)
            date_key = ts.date()
            if date_key not in bias_cache:
                bias_cache[date_key] = self.bias_engine.assess(
                    df_weekly, df_daily, df_h4, ts.to_pydatetime()
                )
            bias = bias_cache[date_key]

            if bias.direction == BiasDirection.NEUTRAL:
                continue

            # ----------- C) REGIME (cache par jour aussi)
            if date_key not in regime_cache:
                regime_cache[date_key] = self.regime_detector.detect(df_ltf.iloc[:t])
            regime_state = regime_cache[date_key]

            if regime_state.regime == Regime.MANIPULATION:
                continue

            # ----------- D) Chercher FVG récent aligné
            proposed_side = Side.LONG if bias.direction == BiasDirection.BULLISH else Side.SHORT
            recent_fvg = self._find_recent_unfilled_fvg(fvgs, t, proposed_side, max_age=50)
            if recent_fvg is None:
                continue

            # Entry = retour dans le FVG (touche CE)
            if proposed_side == Side.LONG:
                if bar["low"] > recent_fvg.ce:
                    continue
                entry = recent_fvg.ce
            else:
                if bar["high"] < recent_fvg.ce:
                    continue
                entry = recent_fvg.ce

            # ----------- E) OB associé
            ob = obs_by_idx.get(recent_fvg.index)
            if ob is None:
                # try by association
                ob_candidates = [o for o in obs if o.associated_fvg_index == recent_fvg.index]
                ob = ob_candidates[0] if ob_candidates else None

            # ----------- F) BB (optionnel, bonus)
            bb = None
            for b in bbs[-10:]:
                if b.index > recent_fvg.index and abs(b.index - t) <= 30:
                    bb = b
                    break

            # ----------- G) Liquidity sweep récent
            recent_swept = self._find_recent_sweep(
                liq_map["all"], ts.to_pydatetime(), proposed_side, hours=24,
            )
            if recent_swept is None:
                continue

            # ----------- H) SL / TP
            atr_val = bar.get(self.atr_col, float("nan"))
            if pd.isna(atr_val) or atr_val <= 0:
                continue

            if proposed_side == Side.LONG:
                sl = min(recent_fvg.bottom, ob.low if ob else recent_fvg.bottom) - 0.2 * atr_val
                risk = entry - sl
                tp1 = entry + self.tp1_rr * risk
                tp2 = entry + self.tp2_rr * risk
            else:
                sl = max(recent_fvg.top, ob.high if ob else recent_fvg.top) + 0.2 * atr_val
                risk = sl - entry
                tp1 = entry - self.tp1_rr * risk
                tp2 = entry - self.tp2_rr * risk

            if risk <= 0:
                continue
            rr = abs(tp1 - entry) / risk

            if rr < 1.8:
                continue

            # ----------- I) Scoring
            feats, score, grade = self.scorer.evaluate_setup(
                htf_bias=bias.direction,
                proposed_side=proposed_side,
                current_killzone=kz,
                recent_swept_liquidity=recent_swept,
                fvg=recent_fvg,
                ob=ob,
                bb=bb,
                regime=regime_state.regime,
                rr=rr,
                smt_present=False,              # TODO: brancher SMT
            )

            if grade == SetupGrade.REJECT or self._grade_rank(grade) < self._grade_rank(self.min_grade):
                continue

            sig = Signal(
                timestamp=ts.to_pydatetime(),
                symbol=symbol,
                side=proposed_side,
                entry=float(entry),
                stop_loss=float(sl),
                take_profit_1=float(tp1),
                take_profit_2=float(tp2),
                grade=grade,
                score=score,
                confluence_count=sum(feats.to_dict().values()),
                reasons=[
                    f"Bias {bias.direction.value} ({bias.probability:.2f})",
                    f"KZ {kz}",
                    f"FVG impulsion {recent_fvg.impulsion_score:.2f}",
                    f"Regime {regime_state.regime.value}",
                    f"RR {rr:.2f}",
                    f"Liquidity swept {recent_swept.ltype.value}",
                ],
                htf_bias=bias.direction,
                regime=regime_state.regime,
                killzone=kz,
                fvg_ref=recent_fvg,
                ob_ref=ob,
                swept_liquidity=recent_swept,
                risk_reward=rr,
            )
            signals.append(sig)

        log.info(f"Execution: {len(signals)} signals for {symbol}")
        return signals

    # ------------------------------------------------------------------
    @staticmethod
    def _find_recent_unfilled_fvg(
        fvgs: List[FVG], current_idx: int, side: Side, max_age: int = 50
    ) -> Optional[FVG]:
        """
        IMPORTANT : `filled` est calculé post-hoc sur toute la série.
        Pour décider si un FVG est encore vivant à l'instant t, on vérifie
        que filled_at_index est None OU > current_idx.
        """
        candidates = [
            f for f in fvgs
            if f.side == side
            and f.index < current_idx
            and (current_idx - f.index) <= max_age
            and (f.filled_at_index is None or f.filled_at_index >= current_idx)
        ]
        if not candidates:
            return None
        # plus récent d'abord
        return max(candidates, key=lambda f: f.index)

    @staticmethod
    def _find_recent_sweep(
        pools: List[LiquidityPool], ts: datetime, side: Side, hours: int = 24
    ) -> Optional[LiquidityPool]:
        swept = [p for p in pools if p.swept and p.swept_at is not None
                 and (ts - p.swept_at).total_seconds() <= hours * 3600
                 and (ts - p.swept_at).total_seconds() >= 0]
        if not swept:
            return None
        # Pour LONG : besoin d'avoir sweepé une low (PDL, EQL, PWL, PML, SESSION_LOW)
        # Pour SHORT : besoin d'avoir sweepé une high
        from src.utils.types import LiquidityType
        lows = {LiquidityType.PDL, LiquidityType.PWL, LiquidityType.PML,
                LiquidityType.EQL, LiquidityType.SESSION_LOW}
        highs = {LiquidityType.PDH, LiquidityType.PWH, LiquidityType.PMH,
                 LiquidityType.EQH, LiquidityType.SESSION_HIGH}
        if side == Side.LONG:
            filt = [p for p in swept if p.ltype in lows]
        else:
            filt = [p for p in swept if p.ltype in highs]
        if not filt:
            return None
        return max(filt, key=lambda p: p.swept_at)

    @staticmethod
    def _grade_rank(g: SetupGrade) -> int:
        return {SetupGrade.REJECT: 0, SetupGrade.B: 1, SetupGrade.A: 2, SetupGrade.A_PLUS: 3}[g]
