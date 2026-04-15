"""
Integrity Checker — DÉTECTE tout ce qui peut corrompre un backtest.

Vérifie :
1. OHLC cohérent (high >= max(o,c), low <= min(o,c))
2. Pas de duplicats d'index
3. Pas de trous anormaux (gaps > N × timeframe attendu)
4. Pas de look-ahead évident (prix = 0, inf, nan)
5. Monotonie temporelle stricte
6. Distribution des returns (outliers suspects)
7. Weekend gaps OK pour forex (sam-dim vides), pas OK pour crypto (24/7)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List

from src.utils.logging_conf import get_logger
from src.utils.types import Timeframe

log = get_logger(__name__)


@dataclass
class IntegrityReport:
    symbol: str
    timeframe: str
    passed: bool
    n_bars: int
    first_ts: str
    last_ts: str
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def summary(self) -> str:
        status = "✓ PASS" if self.passed else "✗ FAIL"
        out = [
            f"[{status}] {self.symbol} {self.timeframe} — {self.n_bars} bars",
            f"  Range: {self.first_ts} → {self.last_ts}",
        ]
        for issue in self.issues:
            out.append(f"  ✗ {issue}")
        for w in self.warnings:
            out.append(f"  ⚠ {w}")
        return "\n".join(out)


class IntegrityChecker:
    """Check complet d'un OHLCV DataFrame."""

    def __init__(self,
                 max_gap_multiplier: float = 5.0,
                 max_return_stddev: float = 15.0,
                 crypto_asset: bool = False):
        self.max_gap_multiplier = max_gap_multiplier
        self.max_return_stddev = max_return_stddev
        self.crypto_asset = crypto_asset

    def check(self, df: pd.DataFrame, symbol: str, timeframe: Timeframe) -> IntegrityReport:
        report = IntegrityReport(
            symbol=symbol,
            timeframe=timeframe.value,
            passed=True,
            n_bars=len(df),
            first_ts=str(df.index[0]) if len(df) else "EMPTY",
            last_ts=str(df.index[-1]) if len(df) else "EMPTY",
        )

        if df.empty:
            report.issues.append("EMPTY DataFrame")
            report.passed = False
            return report

        # --- 1. Colonnes OHLC présentes
        required = {"open", "high", "low", "close"}
        if not required.issubset(df.columns):
            report.issues.append(f"Missing columns: {required - set(df.columns)}")
            report.passed = False
            return report

        # --- 2. OHLC cohérent
        bad_hi = df[df["high"] < df[["open", "close"]].max(axis=1)]
        bad_lo = df[df["low"] > df[["open", "close"]].min(axis=1)]
        if len(bad_hi):
            report.issues.append(f"{len(bad_hi)} bars with high < max(open,close)")
            report.passed = False
        if len(bad_lo):
            report.issues.append(f"{len(bad_lo)} bars with low > min(open,close)")
            report.passed = False

        # --- 3. Valeurs invalides
        inval = df[(df[["open", "high", "low", "close"]] <= 0).any(axis=1)]
        if len(inval):
            report.issues.append(f"{len(inval)} bars with non-positive prices")
            report.passed = False

        inf_mask = np.isinf(df[["open", "high", "low", "close"]].values).any(axis=1)
        if inf_mask.any():
            report.issues.append(f"{int(inf_mask.sum())} bars with inf values")
            report.passed = False

        nan_mask = df[["open", "high", "low", "close"]].isna().any(axis=1)
        if nan_mask.any():
            report.issues.append(f"{int(nan_mask.sum())} bars with NaN")
            report.passed = False

        # --- 4. Duplicats
        dups = df.index.duplicated()
        if dups.any():
            report.issues.append(f"{int(dups.sum())} duplicate timestamps")
            report.passed = False

        # --- 5. Monotonie
        if not df.index.is_monotonic_increasing:
            report.issues.append("Index not monotonically increasing")
            report.passed = False

        # --- 6. Gaps temporels
        expected_delta = pd.Timedelta(minutes=timeframe.minutes)
        diffs = df.index.to_series().diff().dropna()
        if len(diffs):
            max_ok = expected_delta * self.max_gap_multiplier
            big_gaps = diffs[diffs > max_ok]
            # Pour forex/indices : gaps weekend attendus (jusqu'à 3 jours)
            if self.crypto_asset:
                for gap_start, gap_size in big_gaps.items():
                    report.warnings.append(f"Gap {gap_size} at {gap_start}")
            else:
                # filter expected weekend gaps
                weekend_expected = pd.Timedelta(days=3) + expected_delta
                abnormal = big_gaps[big_gaps > weekend_expected]
                for gap_start, gap_size in abnormal.items():
                    report.warnings.append(f"Unusual gap {gap_size} at {gap_start}")

        # --- 7. Outliers de returns
        returns = df["close"].pct_change(fill_method=None).dropna()
        if len(returns):
            std = returns.std()
            mean = returns.mean()
            outliers = returns[(returns - mean).abs() > self.max_return_stddev * std]
            if len(outliers) > len(returns) * 0.001:      # > 0.1%
                report.warnings.append(
                    f"{len(outliers)} return outliers (>{self.max_return_stddev}σ) — "
                    f"check for data errors or real flash events"
                )
            report.stats["return_mean"] = float(mean)
            report.stats["return_std"] = float(std)
            report.stats["return_skew"] = float(returns.skew())
            report.stats["return_kurt"] = float(returns.kurt())

        # --- 8. Volume check (si présent)
        if "volume" in df.columns:
            zero_vol = (df["volume"] == 0).sum()
            if zero_vol > 0:
                report.warnings.append(f"{int(zero_vol)} bars with zero volume")

        report.stats["n_bars"] = len(df)
        report.stats["date_span_days"] = (df.index[-1] - df.index[0]).days

        return report

    def check_all(self, symbols: List[str], timeframes: List[Timeframe],
                  loader=None) -> List[IntegrityReport]:
        from src.data_engine.loader import DataLoader
        loader = loader or DataLoader()
        out = []
        for sym in symbols:
            for tf in timeframes:
                try:
                    df = loader.load(sym, tf)
                    r = self.check(df, sym, tf)
                    log.info("\n" + r.summary())
                    out.append(r)
                except FileNotFoundError as e:
                    log.warning(f"Skipped {sym} {tf.value}: {e}")
        return out
