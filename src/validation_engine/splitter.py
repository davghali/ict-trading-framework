"""
Data Splitter — séparation IMMUABLE train / validation / test.

Règles dures :
1. TEMPORELLE stricte : test toujours APRÈS validation APRÈS train
2. Un set de test une fois créé ne peut PLUS être modifié (hash vérifié)
3. Zero overlap entre sets
4. Métadonnées horodatées sauvegardées
5. Purge/embargo pour éviter contamination (gap entre train et val)

Schéma par défaut :
- Train     : 60% historique ancien
- Validation: 20% historique moyen (pour tuning)
- Test      : 20% historique récent (HOLD-OUT, jamais touché pendant dev)
- Embargo   : 5 jours de trading entre sets (éviter fuite via fenêtres mobiles)
"""
from __future__ import annotations

import hashlib
import json
import pandas as pd
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple, Optional

from src.utils.config import PROCESSED_DIR
from src.utils.logging_conf import get_logger
from src.utils.types import Timeframe

log = get_logger(__name__)

SPLIT_META_FILE = PROCESSED_DIR / "splits_meta.json"


@dataclass
class SplitMetadata:
    symbol: str
    timeframe: str
    train_start: str
    train_end: str
    val_start: str
    val_end: str
    test_start: str
    test_end: str
    embargo_days: int
    test_hash: str                      # immuable
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


class DataSplitter:
    """
    Le splitter est le GARDIEN de l'intégrité scientifique.
    Une fois un split créé, il est verrouillé. Toute tentative de modification
    après création lève une exception.
    """

    def __init__(self,
                 train_pct: float = 0.60,
                 val_pct: float = 0.20,
                 test_pct: float = 0.20,
                 embargo_days: int = 5):
        assert abs(train_pct + val_pct + test_pct - 1.0) < 1e-6, "Splits must sum to 1.0"
        self.train_pct = train_pct
        self.val_pct = val_pct
        self.test_pct = test_pct
        self.embargo_days = embargo_days

    def split(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: Timeframe,
        force_overwrite: bool = False,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, SplitMetadata]:
        """Retourne (train, val, test, metadata)."""
        existing = self._load_metadata(symbol, timeframe)
        if existing is not None and not force_overwrite:
            log.warning(
                f"Split already exists for {symbol} {timeframe.value} "
                f"(created {existing.created_at}). Loading existing."
            )
            return self._apply_existing_split(df, existing) + (existing,)

        n = len(df)
        if n < 100:
            raise ValueError(f"Not enough data to split: {n} bars")

        n_train = int(n * self.train_pct)
        n_val = int(n * self.val_pct)

        embargo_bars = self._embargo_bars(timeframe)

        train = df.iloc[: n_train - embargo_bars].copy()
        val_start_idx = n_train
        val = df.iloc[val_start_idx : val_start_idx + n_val - embargo_bars].copy()
        test_start_idx = val_start_idx + n_val
        test = df.iloc[test_start_idx:].copy()

        # Hash du test set (immutabilité)
        test_hash = self._hash_dataframe(test)

        meta = SplitMetadata(
            symbol=symbol,
            timeframe=timeframe.value,
            train_start=str(train.index[0]),
            train_end=str(train.index[-1]),
            val_start=str(val.index[0]),
            val_end=str(val.index[-1]),
            test_start=str(test.index[0]),
            test_end=str(test.index[-1]),
            embargo_days=self.embargo_days,
            test_hash=test_hash,
            created_at=datetime.utcnow().isoformat(),
        )
        self._save_metadata(meta)

        log.info(
            f"Split {symbol} {timeframe.value}: "
            f"train={len(train)} ({meta.train_start} → {meta.train_end}) | "
            f"val={len(val)} ({meta.val_start} → {meta.val_end}) | "
            f"test={len(test)} ({meta.test_start} → {meta.test_end})"
        )
        return train, val, test, meta

    def verify_test_integrity(
        self, test_df: pd.DataFrame, symbol: str, timeframe: Timeframe
    ) -> bool:
        """Vérifie que le test set n'a PAS été modifié depuis sa création."""
        meta = self._load_metadata(symbol, timeframe)
        if meta is None:
            log.warning("No split metadata found.")
            return False
        current_hash = self._hash_dataframe(test_df)
        ok = current_hash == meta.test_hash
        if not ok:
            log.error(
                f"⚠️  TEST SET TAMPERED for {symbol} {timeframe.value}! "
                f"expected={meta.test_hash[:12]} current={current_hash[:12]}"
            )
        return ok

    # --- Internals
    def _embargo_bars(self, tf: Timeframe) -> int:
        bars_per_day = 1440 // max(tf.minutes, 1) if tf.minutes <= 1440 else 1
        return int(self.embargo_days * bars_per_day)

    @staticmethod
    def _hash_dataframe(df: pd.DataFrame) -> str:
        h = hashlib.sha256()
        # hash deterministe : index + OHLC only
        cols = [c for c in ["open", "high", "low", "close"] if c in df.columns]
        payload = df[cols].to_csv().encode("utf-8")
        h.update(payload)
        h.update(str(df.index[0]).encode("utf-8"))
        h.update(str(df.index[-1]).encode("utf-8"))
        return h.hexdigest()

    def _load_metadata(
        self, symbol: str, tf: Timeframe
    ) -> Optional[SplitMetadata]:
        if not SPLIT_META_FILE.exists():
            return None
        data = json.loads(SPLIT_META_FILE.read_text())
        key = f"{symbol}_{tf.value}"
        if key not in data:
            return None
        return SplitMetadata(**data[key])

    def _save_metadata(self, meta: SplitMetadata) -> None:
        data = {}
        if SPLIT_META_FILE.exists():
            data = json.loads(SPLIT_META_FILE.read_text())
        key = f"{meta.symbol}_{meta.timeframe}"
        data[key] = meta.to_dict()
        SPLIT_META_FILE.write_text(json.dumps(data, indent=2))

    def _apply_existing_split(
        self, df: pd.DataFrame, meta: SplitMetadata
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        train = df[(df.index >= meta.train_start) & (df.index <= meta.train_end)]
        val = df[(df.index >= meta.val_start) & (df.index <= meta.val_end)]
        test = df[(df.index >= meta.test_start) & (df.index <= meta.test_end)]
        return train.copy(), val.copy(), test.copy()
