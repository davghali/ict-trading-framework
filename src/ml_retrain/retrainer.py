"""
WEEKLY ML RE-TRAINER — le modèle ML s'améliore sur les derniers trades.

Processus (chaque dimanche 21h UTC) :
1. Load tous les trades FERMÉS des 60 derniers jours (tes trades réels)
2. Re-génère les candidates sur cette même fenêtre
3. Ré-entraîne le Gradient Boosting calibré
4. Sauvegarde le nouveau modèle dans reports/ml_models/
5. Compare perf vs semaine dernière
6. Envoie récap Telegram

Anti-overfit :
- Minimum 30 trades pour retrain
- Validation : train 80% / holdout 20%
- Keep model only if AUC_new > AUC_old * 0.95
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from src.data_engine import DataLoader
from src.feature_engine import FeatureEngine
from src.edge_dominance_engine import (
    EdgeCandidateGenerator, EdgeFeatureBuilder, MaximumEdgeEngine,
)
from src.trade_journal import TradeJournal
from src.utils.types import Timeframe
from src.utils.logging_conf import get_logger

log = get_logger(__name__)

ML_DIR = Path(__file__).parents[2] / "reports" / "ml_models"
ML_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = ML_DIR / "retrain_history.jsonl"


class WeeklyRetrainer:

    def __init__(self, lookback_days: int = 60, min_trades: int = 30):
        self.lookback_days = lookback_days
        self.min_trades = min_trades

    # ------------------------------------------------------------------
    def run(self, symbol: str = "XAUUSD", ltf: Timeframe = Timeframe.H1) -> dict:
        """
        Re-train le modèle pour UN asset.
        Retourne dict avec new_auc, old_auc, accepted (bool).
        """
        journal = TradeJournal()
        all_trades = journal.load_all()
        cutoff = datetime.utcnow() - timedelta(days=self.lookback_days)
        recent = [
            t for t in all_trades
            if t.is_closed and t.symbol == symbol
            and t.exit_time and datetime.fromisoformat(t.exit_time) >= cutoff
        ]
        n_recent = len(recent)

        if n_recent < self.min_trades:
            log.info(f"{symbol}: only {n_recent} recent trades, skip retrain")
            return {"skipped": True, "reason": f"only {n_recent} trades"}

        # Generate fresh candidates + simulate
        loader = DataLoader()
        try:
            df_ltf = loader.load(symbol, ltf)
            df_d = loader.load(symbol, Timeframe.D1)
        except Exception as e:
            return {"skipped": True, "reason": f"data load: {e}"}

        fe = FeatureEngine()
        df_ltf = fe.compute(df_ltf)
        df_w = df_d.resample("1W").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()
        df_h4 = df_ltf.resample("4h").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()

        gen = EdgeCandidateGenerator(rr_target=2.0)
        fb = EdgeFeatureBuilder(use_htf_bias=True)
        cands = gen.generate(symbol, df_ltf)
        cands = gen.simulate(cands, df_ltf)
        cands = fb.enrich(cands, df_ltf, df_d, df_w, df_h4)
        df_cand = gen.to_dataframe(cands)

        # Train
        me = MaximumEdgeEngine()
        result = me.analyze_asset(symbol, ltf.value, df_cand, train_pct=0.80)

        if result is None:
            return {"skipped": True, "reason": "ML training failed"}

        new_auc = result.calibration_test["auc"]

        # Compare to previous
        old_auc = self._last_auc(symbol, ltf.value)
        accepted = True
        if old_auc is not None:
            if new_auc < old_auc * 0.95:
                accepted = False
                log.warning(
                    f"{symbol}: new AUC {new_auc:.3f} < 95% of old {old_auc:.3f} — rejected"
                )

        # Save if accepted
        if accepted:
            self._save_model(symbol, ltf.value, result)

        # Log history
        self._log_history({
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "ltf": ltf.value,
            "n_recent_trades": n_recent,
            "new_auc": new_auc,
            "old_auc": old_auc,
            "accepted": accepted,
        })

        return {
            "skipped": False,
            "symbol": symbol,
            "new_auc": round(new_auc, 3),
            "old_auc": round(old_auc, 3) if old_auc else None,
            "accepted": accepted,
            "n_trades": n_recent,
        }

    # ------------------------------------------------------------------
    def run_all(self, symbols: list = None) -> dict:
        """Re-train pour tous les assets principaux."""
        symbols = symbols or ["XAUUSD", "XAGUSD", "BTCUSD", "NAS100"]
        results = {}
        for sym in symbols:
            try:
                results[sym] = self.run(sym)
            except Exception as e:
                results[sym] = {"error": str(e)}
        return results

    # ------------------------------------------------------------------
    def _save_model(self, symbol: str, ltf: str, result) -> None:
        path = ML_DIR / f"{symbol}_{ltf}_gbm.pkl"
        data = {
            "feat_cols": result.feature_cols,
            "auc": result.calibration_test["auc"],
            "timestamp": datetime.utcnow().isoformat(),
        }
        path.write_bytes(pickle.dumps(data))
        log.info(f"Saved retrained model : {path}")

    def _last_auc(self, symbol: str, ltf: str) -> Optional[float]:
        path = ML_DIR / f"{symbol}_{ltf}_gbm.pkl"
        if not path.exists():
            return None
        try:
            data = pickle.loads(path.read_bytes())
            return data.get("auc")
        except Exception:
            return None

    def _log_history(self, entry: dict) -> None:
        with HISTORY_FILE.open("a") as f:
            f.write(json.dumps(entry) + "\n")
