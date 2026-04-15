"""
LIVE SCANNER — transforme le framework de recherche en OUTIL.

Refresh les data latest, détecte les setups ACTIFS (FVG non rempli,
liquidité récente sweepée, killzone en cours), calcule P(win) ML,
et retourne une liste de LiveSignal actionables.

Usage CLI :
    python3 -m src.live_scanner.scanner           # scan one-shot
    python3 -m src.live_scanner.scanner --loop 5  # refresh every 5 min
"""
from __future__ import annotations

import time
import pickle
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd
import numpy as np

from src.data_engine import DataLoader, download_asset
from src.feature_engine import FeatureEngine
from src.ict_engine import (
    FVGDetector, OrderBlockDetector, LiquidityDetector,
)
from src.utils.types import Timeframe, Side, FVG
from src.utils.sessions import which_killzone
from src.utils.config import REPORTS_DIR, get_instrument
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class LiveSignal:
    """Un signal ACTIF au moment du scan."""
    timestamp_scan: str
    symbol: str
    ltf: str
    side: str
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float
    # Contexte
    fvg_size_atr: float
    fvg_age_bars: int
    fvg_impulsion: float
    killzone: str
    current_price: float
    distance_to_entry_pct: float        # % de distance entre price et entry CE
    # ML / scoring
    ml_prob_win: Optional[float]        # None si pas de modèle pour cet asset
    tier: str                            # "ELITE" | "BALANCED" | "VOLUME" | "SKIP"
    priority_score: float                # 0-100 pour ranking


# ======================================================================
# CACHE DES MODÈLES ML (entraînés 1× puis réutilisés)
# ======================================================================
_ML_CACHE_DIR = Path(__file__).parents[2] / "reports" / "ml_models"
_ML_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _get_cached_ml_model(symbol: str, ltf: str):
    path = _ML_CACHE_DIR / f"{symbol}_{ltf}_gbm.pkl"
    if not path.exists():
        return None
    try:
        return pickle.loads(path.read_bytes())
    except Exception:
        return None


def _save_ml_model(symbol: str, ltf: str, model_data: dict):
    path = _ML_CACHE_DIR / f"{symbol}_{ltf}_gbm.pkl"
    path.write_bytes(pickle.dumps(model_data))


# ======================================================================
# THRESHOLDS PAR ASSET (issues du max_edge report)
# ======================================================================
# Ces thresholds sont ceux validés OOS par le Maximum Edge Engine.
# Tier ELITE = WR maximal, tier BALANCED = optimal, VOLUME = max trades.
ML_THRESHOLDS = {
    "XAUUSD_1h": {"elite": 0.45, "balanced": 0.40, "volume": 0.30},
    "XAGUSD_1h": {"elite": 0.40, "balanced": 0.40, "volume": 0.30},
    "BTCUSD_1h": {"elite": 0.45, "balanced": 0.30, "volume": 0.30},
    "NAS100_1h": {"elite": 0.40, "balanced": 0.35, "volume": 0.35},
    "DOW30_1h":  {"elite": 0.30, "balanced": 0.30, "volume": 0.30},
    "SPX500_1h": {"elite": 0.30, "balanced": 0.30, "volume": 0.30},
    "EURUSD_1d": {"elite": 0.30, "balanced": 0.30, "volume": 0.30},
    "GBPUSD_1d": {"elite": 0.30, "balanced": 0.30, "volume": 0.30},
    "USDJPY_1d": {"elite": 0.45, "balanced": 0.35, "volume": 0.35},
    "AUDUSD_1d": {"elite": 0.30, "balanced": 0.30, "volume": 0.30},
    "USDCAD_1d": {"elite": 0.75, "balanced": 0.35, "volume": 0.30},
    "ETHUSD_1d": {"elite": 0.35, "balanced": 0.30, "volume": 0.30},
}


class LiveScanner:

    def __init__(
        self,
        symbols_h1: List[str] = None,
        symbols_d1: List[str] = None,
        tier: str = "balanced",
        refresh_data: bool = True,
    ):
        self.symbols_h1 = symbols_h1 or [
            "XAUUSD", "XAGUSD", "BTCUSD", "NAS100", "DOW30", "SPX500",
        ]
        self.symbols_d1 = symbols_d1 or [
            "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "ETHUSD",
        ]
        self.tier = tier
        self.refresh = refresh_data

    # ------------------------------------------------------------------
    def scan_once(self) -> List[LiveSignal]:
        """Un scan complet sur tous les assets. Retourne les signaux actifs."""
        signals: List[LiveSignal] = []

        for sym in self.symbols_h1:
            try:
                sigs = self._scan_asset(sym, Timeframe.H1)
                signals.extend(sigs)
            except Exception as e:
                log.warning(f"{sym} 1h: {e}")

        for sym in self.symbols_d1:
            try:
                sigs = self._scan_asset(sym, Timeframe.D1)
                signals.extend(sigs)
            except Exception as e:
                log.warning(f"{sym} 1d: {e}")

        # Sort by priority
        signals.sort(key=lambda s: s.priority_score, reverse=True)
        return signals

    # ------------------------------------------------------------------
    def _scan_asset(self, symbol: str, ltf: Timeframe) -> List[LiveSignal]:
        # Refresh data si demandé (télécharge les dernières bars)
        if self.refresh:
            try:
                download_asset(symbol, ltf, save=True)
                # Invalide le cache loader
                DataLoader.load.cache_clear()
            except Exception as e:
                log.debug(f"Refresh skipped for {symbol}: {e}")

        loader = DataLoader()
        df = loader.load(symbol, ltf)
        fe = FeatureEngine()
        df = fe.compute(df)

        # Detect FVGs + OBs + Liquidité
        fvgs = FVGDetector(min_size_atr=0.2, displacement_min=1.1,
                            close_in_range_min=0.6).detect(df)
        obs = OrderBlockDetector().detect(df, fvgs)
        liq_map = LiquidityDetector().detect_all(df)

        # Current bar context
        last_idx = len(df) - 1
        last_ts = df.index[-1].to_pydatetime()
        last_price = float(df["close"].iloc[-1])
        kz = which_killzone(last_ts) or "none"

        # On veut les FVGs NON REMPLIS, ≤ 100 bars anciens
        active_fvgs = [
            f for f in fvgs
            if not f.filled and (last_idx - f.index) <= 100 and (last_idx - f.index) > 0
        ]

        if not active_fvgs:
            return []

        # Charge / entraîne le modèle ML
        model_data = _get_cached_ml_model(symbol, ltf.value)
        if model_data is None:
            model_data = self._train_cache_ml(symbol, ltf, df)

        ob_by_fvg_idx = {o.associated_fvg_index: o for o in obs}
        signals: List[LiveSignal] = []

        for fvg in active_fvgs:
            # Build live signal
            side = fvg.side
            entry = fvg.ce
            atr = float(df["atr_14"].iloc[fvg.index]) if not pd.isna(df["atr_14"].iloc[fvg.index]) else 0
            if atr <= 0:
                continue

            if side == Side.LONG:
                sl = fvg.bottom - 0.3 * atr
                risk = entry - sl
                tp1 = entry + 2.0 * risk
                tp2 = entry + 3.0 * risk
            else:
                sl = fvg.top + 0.3 * atr
                risk = sl - entry
                tp1 = entry - 2.0 * risk
                tp2 = entry - 3.0 * risk

            if risk <= 0:
                continue
            rr = abs(tp1 - entry) / risk

            # ML prediction
            prob_win = None
            if model_data is not None:
                feat_vec = self._build_feature_vector(df, fvg, last_idx, model_data["feat_cols"])
                try:
                    prob_win = float(model_data["model"].predict_proba([feat_vec])[0, 1])
                except Exception:
                    prob_win = None

            # Tier determination
            tier = self._determine_tier(symbol, ltf.value, prob_win)
            if tier == "SKIP":
                continue  # on skip les setups sous seuil

            # Priority score = f(prob_win, RR, distance to entry)
            dist_pct = abs(last_price - entry) / last_price * 100
            prob_component = (prob_win if prob_win else 0.4) * 100
            priority = prob_component + (rr - 2.0) * 5 - dist_pct * 0.5

            signals.append(LiveSignal(
                timestamp_scan=datetime.utcnow().isoformat(),
                symbol=symbol,
                ltf=ltf.value,
                side=side.value,
                entry=float(entry),
                stop_loss=float(sl),
                take_profit_1=float(tp1),
                take_profit_2=float(tp2),
                risk_reward=float(rr),
                fvg_size_atr=float(fvg.size_in_atr),
                fvg_age_bars=last_idx - fvg.index,
                fvg_impulsion=float(fvg.impulsion_score),
                killzone=kz,
                current_price=last_price,
                distance_to_entry_pct=float(dist_pct),
                ml_prob_win=prob_win,
                tier=tier,
                priority_score=float(priority),
            ))

        return signals

    # ------------------------------------------------------------------
    def _determine_tier(self, symbol: str, ltf: str, prob_win: Optional[float]) -> str:
        """Détermine le tier basé sur P(win)."""
        key = f"{symbol}_{ltf}"
        thresholds = ML_THRESHOLDS.get(key, {"elite": 0.50, "balanced": 0.40, "volume": 0.30})

        if prob_win is None:
            # Pas de modèle ML → tier par défaut = BALANCED si condition basique OK
            return "BALANCED"

        if prob_win >= thresholds["elite"]:
            return "ELITE"
        elif prob_win >= thresholds["balanced"]:
            return "BALANCED"
        elif prob_win >= thresholds["volume"]:
            return "VOLUME"
        else:
            return "SKIP"

    # ------------------------------------------------------------------
    def _train_cache_ml(self, symbol: str, ltf: Timeframe, df_features: pd.DataFrame):
        """Entraîne le modèle ML pour cet asset et le cache."""
        from src.edge_dominance_engine import (
            EdgeCandidateGenerator, EdgeFeatureBuilder, MaximumEdgeEngine,
        )
        log.info(f"Training ML model for {symbol} {ltf.value}...")
        loader = DataLoader()
        df_d = loader.load(symbol, Timeframe.D1)
        df_w = df_d.resample("1W").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()
        df_h4 = (df_features.resample("4h").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna() if ltf.minutes < 240 else df_d)

        gen = EdgeCandidateGenerator()
        fb = EdgeFeatureBuilder(use_htf_bias=True)
        cands = gen.generate(symbol, df_features)
        cands = gen.simulate(cands, df_features)
        cands = fb.enrich(cands, df_features, df_d, df_w, df_h4)
        df_cand = gen.to_dataframe(cands)

        me = MaximumEdgeEngine()
        res = me.analyze_asset(symbol, ltf.value, df_cand, train_pct=0.80)
        if res is None:
            return None

        # Rebuild and fit on full data (train + test) for production use
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.calibration import CalibratedClassifierCV

        df_prep, feat_cols = me._prepare_features(
            df_cand[df_cand["outcome"].isin([-1, 1])]
        )
        X = df_prep[feat_cols].values
        y = (df_prep["outcome"] == 1).astype(int).values

        base = GradientBoostingClassifier(
            n_estimators=150, max_depth=3, learning_rate=0.05,
            subsample=0.8, min_samples_leaf=10, random_state=42,
        )
        try:
            model = CalibratedClassifierCV(base, method="isotonic", cv=3)
            model.fit(X, y)
        except Exception:
            base.fit(X, y)
            model = base

        data = {"model": model, "feat_cols": feat_cols}
        _save_ml_model(symbol, ltf.value, data)
        return data

    # ------------------------------------------------------------------
    def _build_feature_vector(
        self, df: pd.DataFrame, fvg: FVG, last_idx: int, feat_cols: List[str]
    ):
        """Construit un vecteur features pour un FVG spécifique."""
        from src.edge_dominance_engine import (
            EdgeCandidateGenerator, EdgeFeatureBuilder,
        )
        # On reconstruit un candidate pour ce FVG
        gen = EdgeCandidateGenerator()
        # Simuler uniquement ce FVG
        cands_all = gen.generate(fvg.__dict__.get("symbol", "UNKNOWN"), df)
        cand = next((c for c in cands_all if c.index == fvg.index), None)
        if cand is None:
            return [0.0] * len(feat_cols)

        # Enrich avec features
        fb = EdgeFeatureBuilder(use_htf_bias=False)
        cand_enriched = fb.enrich([cand], df)[0]

        # Build dict
        d = vars(cand_enriched).copy()
        d["side"] = cand_enriched.side.value

        # Prepare like ML engine does
        import pandas as pd
        df_one = pd.DataFrame([d])
        from src.edge_dominance_engine import MaximumEdgeEngine
        me = MaximumEdgeEngine()
        df_prep, _ = me._prepare_features(df_one)

        # Align to feat_cols (missing → 0)
        vec = []
        for c in feat_cols:
            if c in df_prep.columns:
                vec.append(float(df_prep[c].iloc[0]) if pd.notna(df_prep[c].iloc[0]) else 0.0)
            else:
                vec.append(0.0)
        return vec


# ======================================================================
# CLI
# ======================================================================
def print_signals(signals: List[LiveSignal]) -> None:
    if not signals:
        print("\n  ℹ Aucun signal actif dans les conditions actuelles.")
        return
    print(f"\n  🔔 {len(signals)} signal(s) actif(s) — triés par priorité :\n")
    print(f"  {'#':<3} {'Tier':<10} {'Asset':<8} {'TF':<4} {'Side':<6} "
          f"{'Entry':>10} {'SL':>10} {'TP1':>10} {'RR':>5} {'P(win)':>7} "
          f"{'Dist%':>6} {'Age':>4} {'KZ':<12}")
    print("  " + "─" * 125)
    for i, s in enumerate(signals, 1):
        p_str = f"{s.ml_prob_win:.2%}" if s.ml_prob_win else "  n/a"
        print(f"  {i:<3} {s.tier:<10} {s.symbol:<8} {s.ltf:<4} {s.side:<6} "
              f"{s.entry:>10.4f} {s.stop_loss:>10.4f} {s.take_profit_1:>10.4f} "
              f"{s.risk_reward:>5.2f} {p_str:>7} "
              f"{s.distance_to_entry_pct:>6.2f} {s.fvg_age_bars:>4d} {s.killzone:<12}")


def save_signals_json(signals: List[LiveSignal]) -> Path:
    import json
    out = REPORTS_DIR / f"live_scan_{datetime.utcnow():%Y%m%d_%H%M%S}.json"
    data = {
        "scan_time": datetime.utcnow().isoformat(),
        "n_signals": len(signals),
        "signals": [asdict(s) for s in signals],
    }
    out.write_text(json.dumps(data, indent=2, default=str))
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="balanced", choices=["elite", "balanced", "volume"])
    ap.add_argument("--loop", type=int, default=0,
                    help="Refresh every N minutes. 0 = one-shot.")
    ap.add_argument("--no-refresh", action="store_true")
    args = ap.parse_args()

    scanner = LiveScanner(tier=args.tier, refresh_data=not args.no_refresh)

    if args.loop == 0:
        print(f"\n{'═' * 75}")
        print(f"  LIVE SCANNER — {datetime.utcnow():%Y-%m-%d %H:%M:%S UTC}")
        print(f"  Tier: {args.tier.upper()}")
        print(f"{'═' * 75}")
        sigs = scanner.scan_once()
        print_signals(sigs)
        out = save_signals_json(sigs)
        print(f"\n  💾 {out}")
    else:
        while True:
            print(f"\n{'═' * 75}")
            print(f"  LIVE SCANNER — {datetime.utcnow():%Y-%m-%d %H:%M:%S UTC}")
            print(f"{'═' * 75}")
            sigs = scanner.scan_once()
            print_signals(sigs)
            save_signals_json(sigs)
            print(f"\n  ⏳ Next refresh in {args.loop} min... (Ctrl+C to quit)")
            time.sleep(args.loop * 60)
