"""Tests Data Engine — integrity checker + loader."""
import pandas as pd
import numpy as np
import pytest

from src.data_engine import IntegrityChecker
from src.utils.types import Timeframe


def make_clean_df(n=500, freq="1h"):
    idx = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    rng = np.random.default_rng(42)
    p = 1.1 + np.cumsum(rng.normal(0, 0.001, n))
    return pd.DataFrame({
        "open": p, "high": p + 0.002, "low": p - 0.002,
        "close": p + rng.normal(0, 0.0005, n), "volume": 100,
    }, index=idx)


def test_integrity_passes_clean_data():
    df = make_clean_df(500)
    # Force high >= max(o,c) and low <= min(o,c)
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    r = IntegrityChecker().check(df, "TEST", Timeframe.H1)
    assert r.passed


def test_integrity_detects_broken_ohlc():
    df = make_clean_df(100)
    # Break: set high below close
    df.iloc[50, df.columns.get_loc("high")] = df.iloc[50, df.columns.get_loc("close")] - 1
    r = IntegrityChecker().check(df, "TEST", Timeframe.H1)
    assert not r.passed


def test_integrity_detects_duplicate_index():
    df = make_clean_df(100)
    # Create duplicate via concat
    dup = pd.concat([df, df.iloc[[50]]]).sort_index()
    r = IntegrityChecker().check(dup, "TEST", Timeframe.H1)
    assert not r.passed
    assert any("duplicate" in i.lower() for i in r.issues)


def test_integrity_detects_nan():
    df = make_clean_df(100)
    df.iloc[50, df.columns.get_loc("close")] = float("nan")
    r = IntegrityChecker().check(df, "TEST", Timeframe.H1)
    assert not r.passed
    assert any("nan" in i.lower() for i in r.issues)


def test_integrity_detects_non_positive_price():
    df = make_clean_df(100)
    df.iloc[50, df.columns.get_loc("low")] = -1.0
    r = IntegrityChecker().check(df, "TEST", Timeframe.H1)
    assert not r.passed


def test_integrity_empty_df():
    df = pd.DataFrame()
    r = IntegrityChecker().check(df, "TEST", Timeframe.H1)
    assert not r.passed


def test_loader_raises_if_not_found():
    from src.data_engine import DataLoader
    dl = DataLoader()
    with pytest.raises(FileNotFoundError):
        dl.load("NONEXISTENT_SYMBOL_XYZ", Timeframe.H1)
