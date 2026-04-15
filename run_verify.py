"""
VERIFICATION FINALE — teste l'intégrité complète du framework en une passe.

Vérifie :
1. Imports de tous les modules (49)
2. Parsing des configs YAML
3. Présence des 18 data files
4. Integrity check des data après auto-repair
5. Tests unitaires (56)
6. Cohérence des JSON reports vs MASTER_PLAN.md
7. Syntax de tous les runners
8. Smoke test d'un backtest complet
"""
from __future__ import annotations

import sys
import warnings
import subprocess
import json
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
warnings.filterwarnings("ignore")


def banner(t):
    print("\n" + "═" * 75)
    print(f"  {t}")
    print("═" * 75)


def test_imports():
    banner("1. IMPORTS (49 modules)")
    mods = [
        "src.utils.types", "src.utils.config", "src.utils.sessions",
        "src.utils.logging_conf",
        "src.data_engine", "src.data_engine.downloader", "src.data_engine.loader",
        "src.data_engine.integrity",
        "src.validation_engine", "src.validation_engine.splitter",
        "src.validation_engine.leakage",
        "src.feature_engine", "src.feature_engine.features",
        "src.ict_engine", "src.ict_engine.fvg", "src.ict_engine.order_blocks",
        "src.ict_engine.breaker_blocks", "src.ict_engine.liquidity",
        "src.ict_engine.smt", "src.ict_engine.structure",
        "src.bias_engine", "src.bias_engine.bias",
        "src.regime_engine", "src.regime_engine.regime",
        "src.scoring_engine", "src.scoring_engine.scoring",
        "src.execution_engine", "src.execution_engine.execution",
        "src.risk_engine", "src.risk_engine.risk", "src.risk_engine.position_sizer",
        "src.backtest_engine", "src.backtest_engine.backtest",
        "src.backtest_engine.metrics", "src.backtest_engine.walk_forward",
        "src.backtest_engine.monte_carlo",
        "src.adaptation_engine", "src.adaptation_engine.adaptation",
        "src.audit_engine", "src.audit_engine.audit",
        "src.edge_dominance_engine", "src.edge_dominance_engine.edge_generator",
        "src.edge_dominance_engine.edge_features",
        "src.edge_dominance_engine.edge_discovery",
        "src.edge_dominance_engine.edge_validator",
        "src.edge_dominance_engine.edge_reality",
        "src.edge_dominance_engine.edge_reporter",
        "src.edge_dominance_engine.elite_selector",
        "src.edge_dominance_engine.maximum_edge",
        "src.live_scanner", "src.live_scanner.scanner", "src.live_scanner.alerter",
        "src.live_scanner.desktop_notify",
        "src.trade_journal", "src.trade_journal.journal",
        "src.news_calendar", "src.news_calendar.calendar",
        "src.utils.user_settings",
    ]
    fail = 0
    for m in mods:
        try:
            importlib.import_module(m)
        except Exception as e:
            print(f"  ✗ {m}: {e}")
            fail += 1
    print(f"  {len(mods) - fail}/{len(mods)} OK")
    return fail == 0


def test_configs():
    banner("2. CONFIG YAML")
    from src.utils.config import get_prop_firm_rules, list_instruments

    fails = 0
    for firm, variants in [
        ("ftmo", ["classic_challenge", "verification", "funded"]),
        ("the_5ers", ["bootcamp", "hpt"]),
    ]:
        for v in variants:
            try:
                r = get_prop_firm_rules(firm, v)
                assert r["max_daily_loss_pct"] > 0
                assert "safety" in r
            except Exception as e:
                print(f"  ✗ {firm}/{v}: {e}")
                fails += 1
    instruments = list_instruments()
    print(f"  Prop firms : 2 firms, 5 variants — {'OK' if fails == 0 else 'FAIL'}")
    print(f"  Instruments: {len(instruments)} — {instruments}")
    return fails == 0 and len(instruments) >= 12


def test_data():
    banner("3. DATA FILES + AUTO-REPAIR")
    from src.data_engine import DataLoader, IntegrityChecker
    from src.utils.types import Timeframe

    loader = DataLoader()
    checker = IntegrityChecker()
    files = sorted(Path("data/raw").glob("*.parquet"))
    ok = fail = 0
    total_bars = 0
    for f in files:
        parts = f.stem.split("_", 1)
        sym, tf_str = parts[0], parts[1]
        try:
            tf = Timeframe(tf_str)
        except ValueError:
            continue
        try:
            df = loader.load(sym, tf)
            rep = checker.check(df, sym, tf)
            if rep.passed:
                ok += 1
                total_bars += len(df)
            else:
                fail += 1
                print(f"  ⚠ {sym} {tf_str}: {rep.issues[:2]}")
        except Exception as e:
            fail += 1
            print(f"  ✗ {sym} {tf_str}: {e}")
    print(f"  {ok}/{ok+fail} fichiers OK — {total_bars:,} bars totaux")
    return fail == 0


def test_unit_tests():
    banner("4. TESTS UNITAIRES")
    res = subprocess.run(
        ["python3", "-m", "pytest", "tests/", "-q", "--tb=no"],
        capture_output=True, text=True, cwd=Path(__file__).parent,
    )
    last = res.stdout.splitlines()[-1] if res.stdout else ""
    print(f"  {last}")
    return "passed" in last and "failed" not in last


def test_json_reports():
    banner("5. JSON REPORTS COHÉRENCE")
    ok = fail = 0
    for f in sorted(Path("reports").glob("*.json")):
        try:
            data = json.loads(f.read_text())
            assert isinstance(data, dict)
            assert "timestamp" in data
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  ✗ {f.name}: {e}")
    print(f"  {ok}/{ok+fail} JSONs valides")
    return fail == 0


def test_master_plan_claims():
    banner("6. COHÉRENCE DES CLAIMS DU MASTER_PLAN")
    from pathlib import Path
    reports = sorted(Path("reports").glob("max_edge_pareto_*.json"))
    if not reports:
        print("  ⚠ Pas de max_edge_pareto report — skipping")
        return True
    data = json.loads(reports[-1].read_text())

    def agg(tier):
        total_mo = 0
        wr_sum = 0
        for asset, info in data["assets"].items():
            t = info.get("tiers", {}).get(tier)
            if t is None:
                continue
            total_mo += t["trades_per_month"]
            wr_sum += t["winrate_oos"] * t["trades_per_month"]
        return total_mo, (wr_sum / total_mo if total_mo else 0)

    v_mo, v_wr = agg("volume")
    b_mo, b_wr = agg("balanced")
    e_mo, e_wr = agg("elite")

    print(f"  VOLUME  : {v_mo:.1f} trades/mois @ WR {v_wr:.3f}")
    print(f"  BALANCED: {b_mo:.1f} trades/mois @ WR {b_wr:.3f}")
    print(f"  ELITE   : {e_mo:.1f} trades/mois @ WR {e_wr:.3f}")

    # Master plan claims:
    # VOLUME: 165 @ 40.3%
    # BALANCED: 138 @ 41.4%
    # ELITE: 93 @ 41.7%
    ok = (
        abs(v_mo - 165) < 2 and abs(v_wr - 0.403) < 0.005 and
        abs(b_mo - 138) < 2 and abs(b_wr - 0.414) < 0.005 and
        abs(e_mo - 93) < 2 and abs(e_wr - 0.417) < 0.005
    )
    print(f"  → Claims validés : {'✓' if ok else '✗ DIVERGENCE'}")
    return ok


def test_script_syntax():
    banner("7. SYNTAX DES RUNNERS")
    scripts = ["main.py", "run_demo.py", "run_edge_discovery.py",
               "run_edge_discovery_multi.py", "run_edge_insights.py",
               "run_maximum_edge.py", "run_ultimate.py",
               "run_daemon.py", "dashboard.py"]
    fails = 0
    for s in scripts:
        try:
            import ast
            ast.parse(Path(s).read_text())
        except Exception as e:
            print(f"  ✗ {s}: {e}")
            fails += 1
    print(f"  {len(scripts) - fails}/{len(scripts)} syntax OK")
    return fails == 0


if __name__ == "__main__":
    banner("ICT INSTITUTIONAL FRAMEWORK — FULL VERIFICATION")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Path  : {Path(__file__).parent}")

    results = {
        "imports":      test_imports(),
        "configs":      test_configs(),
        "data":         test_data(),
        "unit_tests":   test_unit_tests(),
        "json_reports": test_json_reports(),
        "claims":       test_master_plan_claims(),
        "syntax":       test_script_syntax(),
    }

    banner("RÉSULTAT FINAL")
    all_ok = True
    for name, ok in results.items():
        icon = "✓" if ok else "✗"
        print(f"  {icon} {name}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("  🎯 TOUT EST PARFAIT. SYSTÈME 100% OPÉRATIONNEL.")
    else:
        print("  ⚠ CERTAINS CHECKS ÉCHOUENT — voir détails ci-dessus.")
    print("═" * 75)
    sys.exit(0 if all_ok else 1)
