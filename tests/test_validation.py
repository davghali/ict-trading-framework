"""
Tests Validation Engine — les séparations doivent être CORRECTES ET IMMUABLES.
"""
import pandas as pd
import numpy as np
import pytest
from datetime import datetime

from src.validation_engine import DataSplitter, LeakageDetector
from src.utils.types import Timeframe


def make_df(n=1000, freq="15min"):
    idx = pd.date_range("2020-01-01", periods=n, freq=freq, tz="UTC")
    rng = np.random.default_rng(42)
    p = 100 + np.cumsum(rng.normal(0, 0.1, n))
    return pd.DataFrame({
        "open": p, "high": p + 0.5, "low": p - 0.5, "close": p + rng.normal(0, 0.1, n),
        "volume": 1000,
    }, index=idx)


def test_split_proportions():
    df = make_df(1000)
    sp = DataSplitter(train_pct=0.6, val_pct=0.2, test_pct=0.2, embargo_days=0)
    train, val, test, meta = sp.split(df, "TEST1", Timeframe.M15, force_overwrite=True)
    total = len(train) + len(val) + len(test)
    assert total <= len(df)
    assert len(train) > len(val)
    assert len(val) >= len(test) - 1  # tolérance


def test_no_overlap_between_sets():
    df = make_df(1000)
    sp = DataSplitter(embargo_days=0)
    train, val, test, _ = sp.split(df, "TEST2", Timeframe.M15, force_overwrite=True)
    assert set(train.index).isdisjoint(set(val.index))
    assert set(train.index).isdisjoint(set(test.index))
    assert set(val.index).isdisjoint(set(test.index))


def test_temporal_ordering():
    df = make_df(1000)
    sp = DataSplitter(embargo_days=0)
    train, val, test, _ = sp.split(df, "TEST3", Timeframe.M15, force_overwrite=True)
    assert train.index.max() < val.index.min()
    assert val.index.max() < test.index.min()


def test_test_hash_verification():
    df = make_df(1000)
    sp = DataSplitter(embargo_days=0)
    _, _, test, meta = sp.split(df, "TEST4", Timeframe.M15, force_overwrite=True)
    # Vérifie que le hash courant correspond
    assert sp.verify_test_integrity(test, "TEST4", Timeframe.M15)
    # Modifie test → devrait fail
    tampered = test.copy()
    tampered.iloc[0, tampered.columns.get_loc("close")] = 999999
    assert not sp.verify_test_integrity(tampered, "TEST4", Timeframe.M15)


def test_leakage_detects_overlap():
    det = LeakageDetector()
    df = make_df(300)
    train = df.iloc[:200]
    val = df.iloc[150:250]         # OVERLAP volontaire
    test = df.iloc[250:]
    r = det.check_dataset_overlap(train, val, test)
    assert not r.passed
    assert any("overlap" in i.lower() for i in r.issues)


def test_leakage_detects_temporal_break():
    det = LeakageDetector()
    df = make_df(300)
    train = df.iloc[200:]           # train APRÈS test
    val = df.iloc[100:200]
    test = df.iloc[:100]
    r = det.check_dataset_overlap(train, val, test)
    assert not r.passed


def test_embargo_is_applied():
    df = make_df(1000)
    sp = DataSplitter(train_pct=0.6, val_pct=0.2, test_pct=0.2, embargo_days=1)
    train, val, test, _ = sp.split(df, "TEST_EMB", Timeframe.M15, force_overwrite=True)
    # il doit y avoir un GAP entre train.last et val.first
    gap_tv = (val.index.min() - train.index.max()).total_seconds() / 3600
    assert gap_tv > 0
