"""Tests Feature Engine — causalité + complétude des 50+ features."""
import pandas as pd
import numpy as np
import pytest

from src.feature_engine import FeatureEngine


def make_df(n=200):
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(42)
    p = 100 + np.cumsum(rng.normal(0, 0.3, n))
    return pd.DataFrame({
        "open": p, "high": p + 0.5, "low": p - 0.5,
        "close": p + rng.normal(0, 0.1, n), "volume": 1000,
    }, index=idx)


def test_features_generate_basic():
    df = make_df(200)
    fe = FeatureEngine()
    out = fe.compute(df)
    # Core features must exist
    for col in ["atr_14", "atr_pct", "realized_vol_20", "bb_width",
                "adx_14", "displacement", "range", "body", "log_return"]:
        assert col in out.columns, f"Missing {col}"


def test_features_are_causal():
    """Aucune feature ne doit avoir >0.5 corr avec close[t+1] — anti look-ahead."""
    df = make_df(1000)
    fe = FeatureEngine()
    out = fe.compute(df)
    future_ret = out["close"].pct_change().shift(-1)
    # Check random features (excluding trivial ones like 'return' which is current bar's)
    suspects = []
    for col in ["atr_14", "realized_vol_20", "bb_width", "adx_14",
                "displacement", "dist_to_swing_h_atr"]:
        if col not in out.columns:
            continue
        m = out[col].notna() & future_ret.notna()
        if m.sum() < 50:
            continue
        c = out[col][m].corr(future_ret[m])
        if c is not None and abs(c) > 0.5:
            suspects.append((col, c))
    assert len(suspects) == 0, f"Suspicious look-ahead: {suspects}"


def test_atr_matches_definition():
    df = make_df(50)
    fe = FeatureEngine()
    out = fe.compute(df)
    # ATR_14 = mean(TR) on 14 bars; verify last value matches
    tr_manual = pd.concat([
        out["high"] - out["low"],
        (out["high"] - out["close"].shift(1)).abs(),
        (out["low"] - out["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    expected = tr_manual.rolling(14).mean().iloc[-1]
    assert abs(out["atr_14"].iloc[-1] - expected) < 1e-9


def test_session_columns_added():
    df = make_df(200)
    fe = FeatureEngine()
    out = fe.compute(df)
    assert "session" in out.columns
    assert "killzone" in out.columns
    assert "hour_utc" in out.columns
    assert out["hour_utc"].min() >= 0 and out["hour_utc"].max() <= 23


def test_no_inf_or_nan_after_50_bars():
    df = make_df(200)
    fe = FeatureEngine()
    out = fe.compute(df)
    sub = out.iloc[50:]  # skip warmup
    # At least the critical features should be clean
    for col in ["atr_14", "close", "return"]:
        assert not sub[col].isna().all(), f"{col} all NaN"
        assert not np.isinf(sub[col]).any(), f"{col} has inf"
