"""
Daily Analyzer — sort pour CHAQUE asset l'analyse complète du jour.

Pour chaque asset :
- HTF bias (weekly + daily trend)
- Current price + volatilité
- Key liquidity pools (PDH/PDL/PWH/PWL) + distance
- FVGs bullish/bearish actifs
- Recommandation : BUY / SELL / WAIT
- Best trade idea si setup valide
- Priority score (rang entre assets)
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Dict

from src.data_engine import DataLoader
from src.feature_engine import FeatureEngine
from src.ict_engine import FVGDetector, OrderBlockDetector, LiquidityDetector
from src.ict_engine.structure import MarketStructure, TrendState
from src.bias_engine import BiasEngine
from src.utils.types import Timeframe, Side, BiasDirection
from src.utils.sessions import which_killzone
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class KeyLevel:
    name: str
    price: float
    distance_pct: float                 # signed % distance from current price
    swept: bool = False


@dataclass
class TradeIdea:
    """Une idée de trade concrète pour aujourd'hui."""
    side: str                            # "long" | "short"
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float
    rationale: str                       # explication humaine
    probability: float                   # 0-1
    tier: str                            # ELITE / BALANCED / VOLUME
    fvg_age_bars: int = 0


@dataclass
class AssetAnalysis:
    """Analyse complète d'UN asset pour la journée."""
    symbol: str
    ltf: str
    timestamp_utc: str
    current_price: float
    # Context
    session_now: str
    killzone_now: str
    is_weekend: bool
    # Bias
    weekly_trend: str                   # bullish / bearish / neutral
    daily_trend: str
    htf_bias: str                       # bullish / bearish / neutral
    bias_probability: float             # 0-1
    # Volatilité
    atr_pct: float                     # % de variation typique
    vol_regime: str                    # low / mid / high
    # ICT elements
    active_fvgs_long: int
    active_fvgs_short: int
    key_levels: List[KeyLevel] = field(default_factory=list)
    # Recommendation
    recommendation: str = "WAIT"        # BUY / SELL / WAIT
    trade_idea: Optional[TradeIdea] = None
    priority_score: float = 0.0         # 0-100 pour classer les assets entre eux
    # Context analysis
    summary_fr: str = ""
    warnings: List[str] = field(default_factory=list)


class DailyAnalyzer:

    def __init__(self):
        self.loader = DataLoader()
        self.fe = FeatureEngine()
        self.fvg_det = FVGDetector(min_size_atr=0.2, displacement_min=1.1)
        self.ob_det = OrderBlockDetector()
        self.liq_det = LiquidityDetector()
        self.bias_engine = BiasEngine()
        self.structure = MarketStructure()

    # ------------------------------------------------------------------
    def analyze(self, symbol: str, ltf: Timeframe) -> Optional[AssetAnalysis]:
        try:
            df_d = self.loader.load(symbol, Timeframe.D1)
            df_ltf = self.loader.load(symbol, ltf) if ltf != Timeframe.D1 else df_d
            df_w = df_d.resample("1W").agg({
                "open": "first", "high": "max", "low": "min",
                "close": "last", "volume": "sum",
            }).dropna()
            df_h4 = (df_ltf.resample("4h").agg({
                "open": "first", "high": "max", "low": "min",
                "close": "last", "volume": "sum",
            }).dropna() if ltf.minutes < 240 else df_d)
        except Exception as e:
            log.warning(f"{symbol}: data load failed: {e}")
            return None

        df_ltf = self.fe.compute(df_ltf)
        if len(df_ltf) < 100:
            return None

        last_idx = len(df_ltf) - 1
        last_ts = df_ltf.index[-1].to_pydatetime()
        current = float(df_ltf["close"].iloc[-1])

        # Bias
        bias = self.bias_engine.assess(df_w, df_d, df_h4, last_ts)

        # Structure
        struct_d = self.structure.analyze(df_d.tail(100))
        struct_w = self.structure.analyze(df_w.tail(50))

        # FVGs
        fvgs = self.fvg_det.detect(df_ltf)
        active_long = [f for f in fvgs
                       if f.side == Side.LONG and not f.filled
                       and (last_idx - f.index) <= 150]
        active_short = [f for f in fvgs
                        if f.side == Side.SHORT and not f.filled
                        and (last_idx - f.index) <= 150]

        obs = self.ob_det.detect(df_ltf, fvgs)
        liq_map = self.liq_det.detect_all(df_ltf)

        # Key levels closest
        all_pools = sorted(liq_map["all"],
                            key=lambda p: abs(p.price - current))[:8]
        key_levels = []
        for p in all_pools:
            dist_pct = (p.price - current) / current * 100
            key_levels.append(KeyLevel(
                name=p.ltype.value.upper(),
                price=float(p.price),
                distance_pct=float(dist_pct),
                swept=p.swept,
            ))

        # Volatility bucket
        atr = df_ltf["atr_14"].iloc[-1] if "atr_14" in df_ltf.columns else 0
        atr_pct = float(atr / current * 100) if current > 0 else 0
        vol_20 = df_ltf["realized_vol_20"].iloc[-1] if "realized_vol_20" in df_ltf.columns else 0
        vol_hist = df_ltf["realized_vol_20"].tail(500).dropna() if "realized_vol_20" in df_ltf.columns else pd.Series()
        if len(vol_hist) > 20:
            rank = (vol_hist < vol_20).mean()
            vol_regime = "low" if rank < 0.33 else ("high" if rank > 0.67 else "mid")
        else:
            vol_regime = "mid"

        # Build analysis
        a = AssetAnalysis(
            symbol=symbol,
            ltf=ltf.value,
            timestamp_utc=last_ts.isoformat(),
            current_price=current,
            session_now=which_killzone(last_ts) or "off",
            killzone_now=which_killzone(last_ts) or "none",
            is_weekend=last_ts.weekday() >= 5,
            weekly_trend=struct_w["current_trend"].value,
            daily_trend=struct_d["current_trend"].value,
            htf_bias=bias.direction.value,
            bias_probability=bias.probability,
            atr_pct=atr_pct,
            vol_regime=vol_regime,
            active_fvgs_long=len(active_long),
            active_fvgs_short=len(active_short),
            key_levels=key_levels,
        )

        # Build recommendation + trade idea
        self._build_trade_idea(a, df_ltf, active_long, active_short, obs)

        # Priority score (pour ranking multi-asset)
        a.priority_score = self._priority(a)

        # Summary FR
        a.summary_fr = self._summary_fr(a)

        # Warnings
        if a.is_weekend:
            a.warnings.append("Weekend — pas de trading FTMO Classic")
        if a.atr_pct < 0.1:
            a.warnings.append("Volatilité très faible — peu d'opportunités")
        if a.vol_regime == "high":
            a.warnings.append("Volatilité haute — réduis la size")

        return a

    # ------------------------------------------------------------------
    def _build_trade_idea(self, a: AssetAnalysis, df, active_long, active_short, obs):
        """Choisit le meilleur FVG aligné avec le biais HTF, et calcule entry/SL/TP."""
        # Si biais neutre ou HTF bias incertain, recommandation = WAIT
        if a.htf_bias == "neutral" or a.bias_probability < 0.55:
            a.recommendation = "WAIT"
            return

        target_side = Side.LONG if a.htf_bias == "bullish" else Side.SHORT
        candidates = active_long if target_side == Side.LONG else active_short
        if not candidates:
            a.recommendation = "WAIT"
            return

        # Plus récent FVG aligné
        best = max(candidates, key=lambda f: f.index)
        current = a.current_price
        atr = float(df["atr_14"].iloc[-1]) if "atr_14" in df.columns else 0
        if atr <= 0:
            a.recommendation = "WAIT"
            return

        entry = best.ce
        if target_side == Side.LONG:
            sl = best.bottom - 0.3 * atr
            risk = entry - sl
            tp1 = entry + 2.0 * risk
            tp2 = entry + 3.0 * risk
        else:
            sl = best.top + 0.3 * atr
            risk = sl - entry
            tp1 = entry - 2.0 * risk
            tp2 = entry - 3.0 * risk

        if risk <= 0:
            a.recommendation = "WAIT"
            return

        rr = abs(tp1 - entry) / risk

        # Probability — simple heuristic : bias probability × FVG impulsion
        prob = a.bias_probability * min(1.0, best.impulsion_score / 1.5)

        # Tier
        if prob >= 0.45:
            tier = "ELITE"
        elif prob >= 0.35:
            tier = "BALANCED"
        else:
            tier = "VOLUME"

        # Rationale FR
        side_fr = "achat" if target_side == Side.LONG else "vente"
        rationale = (
            f"Biais HTF {a.htf_bias} (proba {a.bias_probability:.0%}). "
            f"FVG {side_fr} non rempli détecté, taille {best.size_in_atr:.1f} ATR, "
            f"impulsion {best.impulsion_score:.1f}. "
            f"RR atteignable {rr:.1f} à {tier}."
        )

        a.recommendation = "BUY" if target_side == Side.LONG else "SELL"
        a.trade_idea = TradeIdea(
            side=target_side.value,
            entry=float(entry),
            stop_loss=float(sl),
            take_profit_1=float(tp1),
            take_profit_2=float(tp2),
            risk_reward=float(rr),
            rationale=rationale,
            probability=float(prob),
            tier=tier,
            fvg_age_bars=len(df) - 1 - best.index,
        )

    # ------------------------------------------------------------------
    def _priority(self, a: AssetAnalysis) -> float:
        score = 0.0
        if a.trade_idea is not None:
            score += a.trade_idea.probability * 50
            score += min(a.trade_idea.risk_reward, 3) * 10
            if a.trade_idea.tier == "ELITE":
                score += 20
            elif a.trade_idea.tier == "BALANCED":
                score += 10
        if a.htf_bias != "neutral":
            score += 5
        if a.killzone_now != "none":
            score += 5
        if a.vol_regime == "mid":
            score += 3
        if a.is_weekend:
            score -= 30
        return round(score, 1)

    # ------------------------------------------------------------------
    def _summary_fr(self, a: AssetAnalysis) -> str:
        parts = []
        tr_fr = {"bullish": "haussier", "bearish": "baissier", "neutral": "neutre"}
        parts.append(f"{a.symbol} est en tendance {tr_fr.get(a.htf_bias, 'inconnue')} "
                      f"(confiance {a.bias_probability:.0%}).")
        if a.active_fvgs_long or a.active_fvgs_short:
            parts.append(f"{a.active_fvgs_long} FVG bull + {a.active_fvgs_short} FVG bear actifs.")
        if a.killzone_now != "none":
            parts.append(f"Session {a.killzone_now} active.")
        if a.trade_idea:
            action = "ACHETER" if a.trade_idea.side == "long" else "VENDRE"
            parts.append(f"Setup {a.trade_idea.tier} : {action} @ {a.trade_idea.entry:.4f} "
                          f"(RR {a.trade_idea.risk_reward:.1f}, proba {a.trade_idea.probability:.0%}).")
        else:
            parts.append("Pas de setup clair — attendre.")
        return " ".join(parts)

    # ------------------------------------------------------------------
    def analyze_all(self) -> List[AssetAnalysis]:
        """Analyse tous les assets, retourne trié par priority desc."""
        from src.utils.user_settings import UserSettings
        s = UserSettings.load()
        results = []

        # H1 assets
        for sym in s.assets_h1:
            a = self.analyze(sym, Timeframe.H1)
            if a:
                results.append(a)

        # D1 assets
        for sym in s.assets_d1:
            a = self.analyze(sym, Timeframe.D1)
            if a:
                results.append(a)

        results.sort(key=lambda a: a.priority_score, reverse=True)
        return results
