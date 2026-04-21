"""
PARAMETER SWEEP — find the TRUE optimal config
================================================
Tests 12 combos of filters on XAU+XAG H1 to find the Pareto-optimal.
"""
from __future__ import annotations
import sys
from pathlib import Path
import json
from datetime import datetime
from dataclasses import asdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from bot_world_class import (
    load_asset, compute_d1_bias, backtest_world_class, stats,
    Timeframe, MIN_QUALITY_SCORE
)

print("Loading data...")
xau_h1 = load_asset("XAUUSD", Timeframe.H1)
xag_h1 = load_asset("XAGUSD", Timeframe.H1)
xau_d1 = load_asset("XAUUSD", Timeframe.D1)
xag_d1 = load_asset("XAGUSD", Timeframe.D1)
xau_d1_bias = compute_d1_bias(xau_d1)
xag_d1_bias = compute_d1_bias(xag_d1)


def test_config(label, **kwargs):
    xau = backtest_world_class("XAUUSD", xau_h1, xag_h1, xau_d1_bias, **kwargs)
    xag = backtest_world_class("XAGUSD", xag_h1, xau_h1, xag_d1_bias, **kwargs)
    all_t = xau + xag
    return stats(all_t, label)


configs = [
    ("A. Baseline (no filters)", dict(use_htf_filter=False, use_smt_filter=False, use_quality_filter=False, use_regime_filter=False, use_dynamic_rr=False)),
    ("B. HTF only", dict(use_htf_filter=True, use_smt_filter=False, use_quality_filter=False, use_regime_filter=False, use_dynamic_rr=False)),
    ("C. HTF + SMT", dict(use_htf_filter=True, use_smt_filter=True, use_quality_filter=False, use_regime_filter=False, use_dynamic_rr=False)),
    ("D. HTF + Regime", dict(use_htf_filter=True, use_smt_filter=False, use_quality_filter=False, use_regime_filter=True, use_dynamic_rr=False)),
    ("E. HTF + Dynamic RR", dict(use_htf_filter=True, use_smt_filter=False, use_quality_filter=False, use_regime_filter=False, use_dynamic_rr=True)),
    ("F. HTF + SMT + Regime + DynRR", dict(use_htf_filter=True, use_smt_filter=True, use_quality_filter=False, use_regime_filter=True, use_dynamic_rr=True)),
    ("G. Quality 45 only", dict(use_htf_filter=False, use_smt_filter=False, use_quality_filter=True, use_regime_filter=False, use_dynamic_rr=False, min_quality=45)),
    ("H. Quality 55 only", dict(use_htf_filter=False, use_smt_filter=False, use_quality_filter=True, use_regime_filter=False, use_dynamic_rr=False, min_quality=55)),
    ("I. HTF + Quality 45", dict(use_htf_filter=True, use_smt_filter=False, use_quality_filter=True, use_regime_filter=False, use_dynamic_rr=False, min_quality=45)),
    ("J. All filters + Quality 45", dict(use_htf_filter=True, use_smt_filter=True, use_quality_filter=True, use_regime_filter=True, use_dynamic_rr=True, min_quality=45)),
    ("K. All filters + Quality 35", dict(use_htf_filter=True, use_smt_filter=True, use_quality_filter=True, use_regime_filter=True, use_dynamic_rr=True, min_quality=35)),
    ("L. Dynamic RR + Regime only", dict(use_htf_filter=False, use_smt_filter=False, use_quality_filter=False, use_regime_filter=True, use_dynamic_rr=True)),
    ("M. Regime + DynRR (no HTF)", dict(use_htf_filter=False, use_smt_filter=False, use_quality_filter=False, use_regime_filter=True, use_dynamic_rr=True)),
]

print(f"\n{'CONFIG':<36} {'n':>5} {'WR%':>6} {'Exp':>7} {'PF':>5} {'RR':>5} {'/wk':>6} {'Ret%':>8} {'Ann%':>6} {'DD%':>7}")
print("-" * 110)

results = []
for label, kw in configs:
    s = test_config(label, **kw)
    results.append(s)
    pf = s.get("profit_factor", 0) or 0
    pf_s = f"{pf:.2f}" if pf else "inf"
    if s["n"] > 0:
        print(f"{label:<36} {s['n']:>5} {s['win_rate']:>5.1f}% {s['expectancy_R']:>+6.3f} {pf_s:>5} "
              f"{s['avg_RR']:>5.2f} {s['trades_per_week']:>5.2f} "
              f"{s['return_pct']:>+7.1f}% {s['annualized_pct']:>+5.1f}% {s['max_dd_pct']:>+6.1f}%")
    else:
        print(f"{label:<36} 0 trades")

print("-" * 110)

# Find pareto optimal : best by (annualized × WR × (1 / |DD|))
for s in results:
    if s["n"] > 0:
        ann = s.get("annualized_pct", 0)
        wr = s.get("win_rate", 0)
        dd = abs(s.get("max_dd_pct", 1)) or 1
        s["composite"] = round(ann * wr / dd / 100, 3)

results_sorted = sorted([r for r in results if r["n"] > 0], key=lambda x: x.get("composite", 0), reverse=True)
print("\n🏆 TOP 3 BY COMPOSITE SCORE (Annual × WR / |DD|):")
for i, r in enumerate(results_sorted[:3], 1):
    print(f"  {i}. {r['label']} | n={r['n']} · WR {r['win_rate']}% · Ann {r['annualized_pct']:+.1f}% · DD {r['max_dd_pct']:+.1f}% · Score {r.get('composite', 0):.2f}")

tsid = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
(ROOT / "reports" / f"bot_param_sweep_{tsid}.json").write_text(json.dumps({"results": results}, indent=2, default=str))
print(f"\n📄 Saved: bot_param_sweep_{tsid}.json")
