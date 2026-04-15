"""
Data Downloader — Yahoo Finance (gratuit, multi-asset, multi-TF).

LIMITATIONS CONNUES (et ASSUMÉES) :
- yfinance intraday : max 60 jours pour 1m, 2 ans pour 1h
- Pour backtests 10-15 ans : uniquement daily+ disponible gratuitement
- Pour intraday profond : nécessite data vendor payant (Dukascopy/Polygon/Databento)
  → le framework est DATA-SOURCE-AGNOSTIC : n'importe quel parquet OHLCV passe

Stratégie : télécharger le max disponible gratuitement, documenter les limites,
exposer une API propre pour brancher des sources premium plus tard.
"""
from __future__ import annotations

import time
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf

from src.utils.config import RAW_DIR, get_instrument, list_instruments
from src.utils.logging_conf import get_logger
from src.utils.types import Timeframe

log = get_logger(__name__)


# Périodes max par intervalle (limites yfinance)
YF_INTERVAL_LIMITS = {
    "1m": timedelta(days=7),      # max 7 jours par requête, max 30j récents
    "5m": timedelta(days=60),
    "15m": timedelta(days=60),
    "30m": timedelta(days=60),
    "1h": timedelta(days=730),    # 2 ans
    "4h": timedelta(days=730),
    "1d": timedelta(days=365 * 25),   # daily : très long historique
    "1wk": timedelta(days=365 * 50),
    "1mo": timedelta(days=365 * 50),
}


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise colonnes yfinance → lower snake_case + UTC index."""
    if df.empty:
        return df

    df = df.copy()
    # yfinance parfois retourne MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]

    keep = [c for c in ["open", "high", "low", "close", "adj_close", "volume"] if c in df.columns]
    df = df[keep]

    # Force UTC
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df.index.name = "timestamp"

    # Nettoyage : supprimer NaN totaux, dedup
    df = df.dropna(how="all")
    df = df[~df.index.duplicated(keep="first")]
    df = df.sort_index()
    return df


def download_asset(
    symbol: str,
    timeframe: Timeframe,
    start: datetime | None = None,
    end: datetime | None = None,
    save: bool = True,
) -> pd.DataFrame:
    """
    Télécharge OHLCV pour un asset × timeframe.
    Gère automatiquement le chunking pour les limites yfinance.
    """
    inst = get_instrument(symbol)
    yf_symbol = inst["symbol_yf"]
    interval = timeframe.value

    end = end or datetime.utcnow()
    if start is None:
        limit = YF_INTERVAL_LIMITS.get(interval, timedelta(days=365 * 5))
        start = end - limit

    log.info(f"Download {symbol} ({yf_symbol}) {interval} from {start.date()} to {end.date()}")

    # Pour les TF intraday courts : chunking
    max_span = YF_INTERVAL_LIMITS.get(interval, timedelta(days=365 * 25))
    if (end - start) > max_span:
        dfs: list[pd.DataFrame] = []
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + max_span, end)
            try:
                chunk = yf.download(
                    yf_symbol,
                    start=cursor,
                    end=chunk_end,
                    interval=interval,
                    progress=False,
                    auto_adjust=False,
                    prepost=False,
                    threads=False,
                )
                if not chunk.empty:
                    dfs.append(chunk)
            except Exception as e:
                log.warning(f"Chunk {cursor.date()}-{chunk_end.date()} failed: {e}")
            cursor = chunk_end
            time.sleep(0.5)                         # rate-limit polite
        df = pd.concat(dfs) if dfs else pd.DataFrame()
    else:
        df = yf.download(
            yf_symbol,
            start=start,
            end=end,
            interval=interval,
            progress=False,
            auto_adjust=False,
            prepost=False,
            threads=False,
        )

    df = _normalize_ohlcv(df)
    if df.empty:
        log.warning(f"EMPTY data for {symbol} {interval}")
        return df

    log.info(f"  → {len(df)} bars, {df.index[0]} to {df.index[-1]}")

    if save:
        out = RAW_DIR / f"{symbol}_{interval}.parquet"
        df.to_parquet(out)
        log.info(f"  → saved: {out}")
    return df


def download_all(
    symbols: list[str] | None = None,
    timeframes: list[Timeframe] | None = None,
) -> dict[str, dict[str, pd.DataFrame]]:
    """Télécharge toute la matrice symbols × timeframes."""
    symbols = symbols or list_instruments()
    timeframes = timeframes or [
        Timeframe.D1, Timeframe.H4, Timeframe.H1,
        Timeframe.M15, Timeframe.M5,
    ]

    out: dict[str, dict[str, pd.DataFrame]] = {}
    for sym in symbols:
        out[sym] = {}
        for tf in timeframes:
            try:
                df = download_asset(sym, tf)
                out[sym][tf.value] = df
            except Exception as e:
                log.error(f"Failed {sym} {tf.value}: {e}")
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", nargs="+", default=None)
    ap.add_argument("--tfs", nargs="+", default=None,
                    help="e.g. 1d 4h 1h 15m 5m")
    args = ap.parse_args()

    tfs = [Timeframe(t) for t in args.tfs] if args.tfs else None
    download_all(args.assets, tfs)
