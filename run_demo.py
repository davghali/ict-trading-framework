"""
Démo end-to-end — ICT Institutional Framework.

Exécute le pipeline complet :
1. Chargement données (NAS100 déjà téléchargé)
2. Feature engineering
3. Détection ICT (FVG, OB, BB, Liquidité)
4. Génération signaux (Execution Engine avec gates)
5. Backtest (Risk Engine FTMO)
6. Monte Carlo stress test
7. Audit Engine (red team)
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
warnings.filterwarnings("ignore")

from src.data_engine import DataLoader, IntegrityChecker
from src.feature_engine import FeatureEngine
from src.execution_engine import ExecutionEngine
from src.backtest_engine import Backtester, MonteCarlo
from src.backtest_engine.backtest import BacktestConfig
from src.audit_engine import AuditEngine
from src.utils.types import Timeframe, SetupGrade


def banner(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def run(symbol: str = "NAS100",
        ltf: Timeframe = Timeframe.H1,
        firm: str = "ftmo",
        variant: str = "classic_challenge",
        initial: float = 100_000,
        min_grade: SetupGrade = SetupGrade.B,
        run_monte_carlo: bool = True):

    banner(f"ICT INSTITUTIONAL FRAMEWORK — DEMO {symbol} {ltf.value}")

    # -----------------------------------------------------------
    # 1. Data loading
    loader = DataLoader()
    df_d = loader.load(symbol, Timeframe.D1)
    df_ltf = loader.load(symbol, ltf)
    df_w = df_d.resample("1W").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    df_h4 = (df_ltf.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna() if ltf.minutes < 240 else df_d)
    print(f"  Daily : {len(df_d)} bars, {df_d.index[0].date()} → {df_d.index[-1].date()}")
    print(f"  {ltf.value}    : {len(df_ltf)} bars, {df_ltf.index[0]} → {df_ltf.index[-1]}")

    # -----------------------------------------------------------
    # 2. Integrity check
    banner("1. INTEGRITY CHECK")
    ic = IntegrityChecker(crypto_asset=(symbol == "BTCUSD"))
    rep = ic.check(df_ltf, symbol, ltf)
    print(rep.summary())
    if not rep.passed:
        print("⚠ INTEGRITY FAILED — aborting")
        return

    # -----------------------------------------------------------
    # 3. Feature engineering
    banner("2. FEATURE ENGINEERING")
    fe = FeatureEngine()
    df_ltf = fe.compute(df_ltf)
    print(f"  Features: {df_ltf.shape[1]} colonnes")

    # -----------------------------------------------------------
    # 4. Signal generation
    banner("3. EXECUTION ENGINE (gates ICT stricts)")
    execer = ExecutionEngine(min_grade=min_grade)
    signals = execer.generate_signals(symbol, df_ltf, df_w, df_d, df_h4)
    print(f"  Signals générés : {len(signals)}")
    if signals:
        from collections import Counter
        gc = Counter(s.grade.value for s in signals)
        kc = Counter(s.killzone for s in signals)
        print(f"  Grades          : {dict(gc)}")
        print(f"  Killzones       : {dict(kc)}")

    # -----------------------------------------------------------
    # 5. Backtest
    banner(f"4. BACKTEST — {firm.upper()} / {variant}")
    cfg = BacktestConfig(initial_balance=initial, firm=firm, variant=variant)
    bt = Backtester(cfg)
    result = bt.run(symbol, df_ltf, signals)

    print(f"  Trades        : {result.total_trades}")
    print(f"  Return        : {result.total_return_pct:+.2f}%")
    print(f"  Max DD        : {result.max_drawdown_pct:.2f}%")
    print(f"  Max Daily DD  : {result.max_daily_drawdown_pct:.2f}%")
    print(f"  Sharpe        : {result.sharpe_ratio:.2f}")
    print(f"  Sortino       : {result.sortino_ratio:.2f}")
    print(f"  Calmar        : {result.calmar_ratio:.2f}")
    print(f"  Win rate      : {result.win_rate * 100:.1f}%")
    print(f"  Avg win (R)   : {result.avg_win_r:.2f}")
    print(f"  Avg loss (R)  : {result.avg_loss_r:.2f}")
    print(f"  Expectancy R  : {result.expectancy_r:+.3f}")
    print(f"  Profit factor : {result.profit_factor:.2f}")
    print(f"  Max cons L    : {result.consecutive_losses_max}")
    print(f"  FTMO compliant: {'YES' if result.ftmo_compliant else 'NO'}")
    print(f"  5ers compliant: {'YES' if result.the5ers_compliant else 'NO'}")

    # -----------------------------------------------------------
    # 6. Monte Carlo
    if run_monte_carlo and result.total_trades >= 5:
        banner("5. MONTE CARLO STRESS TEST")
        mc = MonteCarlo(n_simulations=2000, seed=42)
        mc_reshuffle = mc.reshuffle(result.trades, result.initial_balance)
        print("  Reshuffle (ordre aléatoire des mêmes trades) :")
        print(f"    " + mc_reshuffle.summary())
        if result.total_trades >= 20:
            mc_boot = mc.bootstrap(result.trades, result.initial_balance,
                                    n_trades=result.total_trades * 2)
            print("\n  Bootstrap (échantillonnage 2× trades) :")
            print(f"    " + mc_boot.summary())

    # -----------------------------------------------------------
    # 7. Audit
    banner("6. AUDIT ENGINE (red team critique)")
    auditor = AuditEngine()
    audit = auditor.audit(result)
    print(audit.summary())

    # -----------------------------------------------------------
    banner("DEMO DONE")
    print(f"\n  VERDICT FINAL : {audit.verdict}")
    print("\n  Ce verdict est celui du framework LUI-MÊME, pas d'un humain.")
    print("  C'est le principe : le système doit CHERCHER à se détruire.")


if __name__ == "__main__":
    run(symbol="NAS100", ltf=Timeframe.H1, firm="ftmo",
        variant="classic_challenge", min_grade=SetupGrade.B)
