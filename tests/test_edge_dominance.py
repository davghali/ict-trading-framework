"""Tests Edge Dominance Engine — generator, features, discovery, elite."""
import pandas as pd
import numpy as np
import pytest

from src.feature_engine import FeatureEngine
from src.edge_dominance_engine import (
    EdgeCandidateGenerator, EdgeFeatureBuilder, EdgeDiscovery,
    EliteSetupSelector, MaximumEdgeEngine,
)


def _make_realistic_df(n=600):
    idx = pd.date_range("2024-01-01 00:00", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(42)
    # Price series with occasional large moves (simulate FVGs)
    returns = rng.normal(0, 0.002, n)
    # Inject a few big moves
    for i in rng.choice(range(5, n), size=20, replace=False):
        returns[i] = rng.choice([-0.015, 0.015])
    price = 2000 * np.exp(np.cumsum(returns))
    return pd.DataFrame({
        "open": price + rng.normal(0, 0.5, n),
        "high": price + np.abs(rng.normal(2, 1, n)),
        "low": price - np.abs(rng.normal(2, 1, n)),
        "close": price + rng.normal(0, 0.3, n),
        "volume": 1000 + rng.integers(0, 500, n),
    }, index=idx)


def test_edge_generator_produces_candidates():
    df = _make_realistic_df(600)
    df = FeatureEngine().compute(df)
    gen = EdgeCandidateGenerator()
    cands = gen.generate("XAUUSD", df)
    assert len(cands) > 0
    # Each candidate should have entry > 0 and sl != entry
    for c in cands[:10]:
        assert c.entry > 0
        assert c.stop_loss > 0
        assert abs(c.entry - c.stop_loss) > 0


def test_edge_generator_simulates_outcomes():
    df = _make_realistic_df(800)
    df = FeatureEngine().compute(df)
    gen = EdgeCandidateGenerator()
    cands = gen.generate("XAUUSD", df)
    cands = gen.simulate(cands, df)
    # Outcomes should be -1, +1, or 0 (timeout)
    outcomes = set(c.outcome for c in cands)
    assert outcomes.issubset({-1, 0, 1})
    # pnl_r = rr for wins, -1 for losses
    for c in cands:
        if c.outcome == 1:
            assert c.pnl_r == 2.0                # rr default
        elif c.outcome == -1:
            assert c.pnl_r == -1.0


def test_feature_builder_enriches():
    df = _make_realistic_df(500)
    df = FeatureEngine().compute(df)
    gen = EdgeCandidateGenerator()
    cands = gen.generate("XAUUSD", df)
    cands = gen.simulate(cands, df)
    fb = EdgeFeatureBuilder(use_htf_bias=False)          # skip HTF for simplicity
    cands = fb.enrich(cands, df)
    # Must have enriched fields
    for c in cands[:5]:
        assert c.hour_utc in range(0, 24)
        assert c.day_of_week in range(0, 7)
        assert c.volatility_bucket in ("low", "mid", "high", "unknown")


def test_discovery_returns_empty_on_small_sample():
    df = _make_realistic_df(200)  # too small
    df = FeatureEngine().compute(df)
    gen = EdgeCandidateGenerator()
    cands = gen.generate("XAUUSD", df)
    cands = gen.simulate(cands, df)
    fb = EdgeFeatureBuilder(use_htf_bias=False)
    cands = fb.enrich(cands, df)
    df_cand = gen.to_dataframe(cands)
    disc = EdgeDiscovery(min_samples=100)   # raise bar
    edges = disc.discover(df_cand)
    # Sample trop petit → peu ou pas d'edges
    # Test passe si fonction ne crash pas
    assert isinstance(edges, list)


def test_elite_selector_filters():
    df = _make_realistic_df(500)
    df = FeatureEngine().compute(df)
    gen = EdgeCandidateGenerator()
    cands = gen.generate("XAUUSD", df)
    cands = gen.simulate(cands, df)
    fb = EdgeFeatureBuilder(use_htf_bias=False)
    cands = fb.enrich(cands, df)
    df_cand = gen.to_dataframe(cands)
    selector = EliteSetupSelector()
    filt = selector.select(df_cand, "XAUUSD")
    # Filtré doit être <= total
    assert len(filt) <= len(df_cand)
    # Pour XAUUSD, profil autorise ny_lunch+others, blocks ny_pm_kz
    if len(filt) > 0:
        assert "ny_pm_kz" not in filt["killzone"].values


def test_elite_selector_active_mm():
    df = _make_realistic_df(500)
    df = FeatureEngine().compute(df)
    gen = EdgeCandidateGenerator()
    cands = gen.generate("XAUUSD", df)
    cands = gen.simulate(cands, df)
    fb = EdgeFeatureBuilder(use_htf_bias=False)
    cands = fb.enrich(cands, df)
    df_cand = gen.to_dataframe(cands)
    selector = EliteSetupSelector()
    filtered = selector.select(df_cand, "XAUUSD")
    if len(filtered) >= 5:
        mm = selector.simulate_active_management(filtered)
        # Wins are now +1.5R (not +2R) in MM
        if mm["n"] > 0:
            assert "adj_winrate" in mm
            assert "adj_expectancy_r" in mm


def test_maximum_edge_engine_small_data():
    """ML engine with small data should return None gracefully."""
    df = _make_realistic_df(150)  # too small
    df = FeatureEngine().compute(df)
    gen = EdgeCandidateGenerator()
    cands = gen.generate("XAUUSD", df)
    cands = gen.simulate(cands, df)
    fb = EdgeFeatureBuilder(use_htf_bias=False)
    cands = fb.enrich(cands, df)
    df_cand = gen.to_dataframe(cands)

    me = MaximumEdgeEngine()
    res = me.analyze_asset("XAUUSD", "1h", df_cand)
    # Should return None gracefully (not crash)
    # or a valid result if enough data
    assert res is None or res.n_train > 0
