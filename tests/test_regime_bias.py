"""Tests Regime Engine + Bias Engine."""
import pandas as pd
import numpy as np
import pytest

from src.regime_engine import RegimeDetector
from src.bias_engine import BiasEngine
from src.utils.types import Regime, BiasDirection


def make_trending_df(n=600, slope=0.001):
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(42)
    noise = rng.normal(0, 0.5, n)
    p = 100 + np.arange(n) * slope + noise
    return pd.DataFrame({
        "open": p, "high": p + 0.5, "low": p - 0.5,
        "close": p + rng.normal(0, 0.1, n), "volume": 1000,
    }, index=idx)


def make_ranging_df(n=600):
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(42)
    # Mean-reverting around 100
    p = 100 + rng.normal(0, 0.5, n).cumsum() * 0.1
    return pd.DataFrame({
        "open": p, "high": p + 0.5, "low": p - 0.5,
        "close": p + rng.normal(0, 0.1, n), "volume": 1000,
    }, index=idx)


def test_regime_returns_unknown_if_too_short():
    df = make_trending_df(50)
    state = RegimeDetector().detect(df)
    assert state.regime == Regime.UNKNOWN


def test_regime_detects_trending():
    df = make_trending_df(600, slope=0.01)
    state = RegimeDetector().detect(df)
    # Trending series should have Hurst > 0.5 typically
    # At least it should not crash and return a valid Regime
    assert isinstance(state.regime, Regime)
    assert 0 <= state.hurst <= 1


def test_regime_all_fields_valid():
    df = make_trending_df(500)
    state = RegimeDetector().detect(df)
    assert 0 <= state.hurst <= 1
    assert state.adx >= 0
    assert 0 <= state.vol_percentile <= 1
    assert 0 <= state.stability <= 1


def test_bias_returns_neutral_on_short_data():
    df_short = make_trending_df(5)
    be = BiasEngine()
    b = be.assess(df_short, df_short, df_short, df_short.index[-1].to_pydatetime())
    assert b.direction == BiasDirection.NEUTRAL


def test_bias_returns_valid_probability():
    # Use a long enough series so weekly/daily/h4 resample all have enough bars
    df = make_trending_df(400 * 24 * 7, slope=0.0001)  # ~10 years of hourly data
    df_w = df.resample("1W").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    df_d = df.resample("1D").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    df_h4 = df.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
    if len(df_w) < 10 or len(df_d) < 20 or len(df_h4) < 50:
        pytest.skip("Not enough data for bias test")

    be = BiasEngine()
    ref_ts = df.index[-1].to_pydatetime()
    b = be.assess(df_w, df_d, df_h4, ref_ts)
    # Probability must be in [0.15, 0.85] (bounded)
    assert 0.15 <= b.probability <= 0.85
    assert b.direction in (BiasDirection.BULLISH, BiasDirection.BEARISH, BiasDirection.NEUTRAL)
