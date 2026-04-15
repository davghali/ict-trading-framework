"""
Tests ICT Engine — FVG, OB, BB détections sur données synthétiques contrôlées.

Approche : on FABRIQUE des séquences OHLC où on SAIT qu'un FVG existe,
puis on vérifie que le détecteur le trouve.
"""
import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timedelta

from src.feature_engine import FeatureEngine
from src.ict_engine import FVGDetector, OrderBlockDetector, LiquidityDetector
from src.utils.types import Side


def make_synthetic_bullish_fvg():
    """Crée une série avec un FVG bullish clair à l'index 25 (après 20+ bars baseline pour ATR)."""
    n = 50
    idx = pd.date_range("2024-01-01 08:00", periods=n, freq="15min", tz="UTC")
    data = []
    for i in range(n):
        base = 1.10000
        data.append({
            "open":  base,
            "high":  base + 0.0005,
            "low":   base - 0.0005,
            "close": base + 0.0001,
            "volume": 100,
        })

    # Bougie 23 : OB bearish (close < open)
    data[23] = {"open": 1.10050, "high": 1.10060, "low": 1.09995, "close": 1.10000, "volume": 100}
    # Bougie 24 : displacement (gros range, bullish, close high)
    data[24] = {"open": 1.10005, "high": 1.10200, "low": 1.10000, "close": 1.10180, "volume": 200}
    # Bougie 25 : FVG bullish (low > high[23])
    data[25] = {"open": 1.10180, "high": 1.10250, "low": 1.10100, "close": 1.10220, "volume": 150}

    df = pd.DataFrame(data, index=idx)
    return df


def make_synthetic_bearish_fvg():
    n = 50
    idx = pd.date_range("2024-01-01 08:00", periods=n, freq="15min", tz="UTC")
    data = []
    for i in range(n):
        base = 1.10000
        data.append({
            "open": base, "high": base + 0.0005, "low": base - 0.0005,
            "close": base - 0.0001, "volume": 100,
        })
    # Bougie 23 : OB bullish
    data[23] = {"open": 1.10000, "high": 1.10050, "low": 1.09990, "close": 1.10040, "volume": 100}
    # Bougie 24 : displacement baissier
    data[24] = {"open": 1.10045, "high": 1.10050, "low": 1.09800, "close": 1.09820, "volume": 200}
    # Bougie 25 : FVG bearish (high < low[23])
    data[25] = {"open": 1.09820, "high": 1.09880, "low": 1.09750, "close": 1.09770, "volume": 150}
    df = pd.DataFrame(data, index=idx)
    return df


def test_fvg_detector_finds_bullish():
    df = make_synthetic_bullish_fvg()
    feat = FeatureEngine()
    df = feat.compute(df)

    det = FVGDetector(min_size_atr=0.05, displacement_min=1.0, close_in_range_min=0.5)
    fvgs = det.detect(df)
    bulls = [f for f in fvgs if f.side == Side.LONG]
    assert len(bulls) >= 1, f"Expected at least 1 bullish FVG, got {len(bulls)}"
    # Le FVG doit être autour de l'index 25
    target = [f for f in bulls if f.index == 25]
    assert len(target) == 1
    fvg = target[0]
    assert fvg.top > fvg.bottom
    assert fvg.size > 0
    assert fvg.side == Side.LONG


def test_fvg_detector_finds_bearish():
    df = make_synthetic_bearish_fvg()
    feat = FeatureEngine()
    df = feat.compute(df)

    det = FVGDetector(min_size_atr=0.05, displacement_min=1.0, close_in_range_min=0.5)
    fvgs = det.detect(df)
    bears = [f for f in fvgs if f.side == Side.SHORT]
    assert len(bears) >= 1, f"Expected ≥1 bearish FVG, got {len(bears)}"


def test_order_block_requires_fvg():
    """Un OB ne doit exister QUE si un FVG accompagne."""
    df = make_synthetic_bullish_fvg()
    feat = FeatureEngine()
    df = feat.compute(df)
    fvgs = FVGDetector(min_size_atr=0.05, displacement_min=1.0,
                       close_in_range_min=0.5).detect(df)
    obs = OrderBlockDetector().detect(df, fvgs)
    # Chaque OB doit référencer un FVG
    for ob in obs:
        assert ob.associated_fvg_index is not None
        assert ob.is_valid


def test_fvg_ce_is_midpoint():
    df = make_synthetic_bullish_fvg()
    feat = FeatureEngine()
    df = feat.compute(df)
    fvgs = FVGDetector(min_size_atr=0.05, displacement_min=1.0,
                       close_in_range_min=0.5).detect(df)
    if fvgs:
        f = fvgs[0]
        assert abs(f.ce - (f.top + f.bottom) / 2) < 1e-9


def test_liquidity_detector_pdh_pdl():
    """Vérifie que PDH/PDL sont bien extraits d'un multi-day set."""
    n = 96  # 4 jours × 24 heures en 1h
    idx = pd.date_range("2024-01-01 00:00", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(42)
    prices = 1.1 + np.cumsum(rng.normal(0, 0.0003, n))
    df = pd.DataFrame({
        "open": prices + rng.normal(0, 0.0001, n),
        "high": prices + 0.0005,
        "low": prices - 0.0005,
        "close": prices,
        "volume": 100,
    }, index=idx)

    det = LiquidityDetector()
    pools = det.detect_session_levels(df)
    pdhs = [p for p in pools if p.ltype.value == "pdh"]
    pdls = [p for p in pools if p.ltype.value == "pdl"]
    assert len(pdhs) >= 2
    assert len(pdls) >= 2
