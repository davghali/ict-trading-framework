"""
MAIN — Pipeline complet ICT Institutional Framework.

Usage :
  python main.py --mode download
  python main.py --mode backtest --symbol EURUSD --firm ftmo
  python main.py --mode walkforward --symbol NAS100
  python main.py --mode audit --symbol EURUSD
  python main.py --mode full --symbol EURUSD
"""
from __future__ import annotations

import argparse
import sys
import json
from datetime import datetime
from pathlib import Path
import pandas as pd

from src.utils.types import Timeframe, SetupGrade
from src.utils.logging_conf import get_logger
from src.utils.config import REPORTS_DIR

from src.data_engine import DataLoader, download_all, IntegrityChecker
from src.validation_engine import DataSplitter, LeakageDetector
from src.feature_engine import FeatureEngine
from src.execution_engine import ExecutionEngine
from src.backtest_engine import Backtester, WalkForwardEngine, MonteCarlo
from src.backtest_engine.backtest import BacktestConfig
from src.audit_engine import AuditEngine
from src.adaptation_engine import AdaptationEngine

log = get_logger(__name__)


def cmd_download(args):
    syms = args.symbols or ["EURUSD", "NAS100", "XAUUSD", "BTCUSD"]
    tfs = [Timeframe.D1, Timeframe.H4, Timeframe.H1, Timeframe.M15]
    if args.include_m5:
        tfs.append(Timeframe.M5)
    download_all(syms, tfs)


def cmd_integrity(args):
    loader = DataLoader()
    checker = IntegrityChecker(crypto_asset=False)
    syms = args.symbols or loader.available_symbols()
    tfs = [Timeframe(t) for t in (args.tfs or ["1d", "1h", "15m"])]
    reports = checker.check_all(syms, tfs, loader=loader)
    passed = sum(1 for r in reports if r.passed)
    log.info(f"\nIntegrity: {passed}/{len(reports)} passed")


def cmd_split(args):
    loader = DataLoader()
    splitter = DataSplitter()
    syms = args.symbols or loader.available_symbols()
    tfs = [Timeframe(t) for t in (args.tfs or ["15m"])]
    for sym in syms:
        for tf in tfs:
            try:
                df = loader.load(sym, tf)
                train, val, test, meta = splitter.split(df, sym, tf,
                                                        force_overwrite=args.overwrite)
                log.info(f"  {sym} {tf.value}: "
                         f"train={len(train)} val={len(val)} test={len(test)}")
            except FileNotFoundError as e:
                log.warning(f"Skip {sym} {tf.value}: {e}")


def cmd_backtest(args):
    """Backtest single-symbol complet."""
    symbol = args.symbol
    firm = args.firm
    variant = args.variant
    loader = DataLoader()
    feat_eng = FeatureEngine()

    # Load multi-TF data
    log.info(f"Loading data for {symbol}...")
    df_w = loader.load(symbol, Timeframe.W1) if Path(
        loader._dir / f"{symbol}_1wk.parquet"
    ).exists() else loader.load(symbol, Timeframe.D1).resample("1W").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum" if "volume" in loader.load(symbol, Timeframe.D1).columns else "last",
    }).dropna()
    df_d = loader.load(symbol, Timeframe.D1)
    df_h4 = loader.load(symbol, Timeframe.H4) if Path(
        loader._dir / f"{symbol}_4h.parquet"
    ).exists() else df_d
    df_ltf = loader.load(symbol, Timeframe(args.ltf))

    log.info("Computing features on LTF...")
    df_ltf = feat_eng.compute(df_ltf)

    # Optional split: use only train set for parameter selection
    if args.split == "train":
        splitter = DataSplitter()
        try:
            train, _, _, _ = splitter.split(df_ltf, symbol, Timeframe(args.ltf))
            df_ltf = train
            log.info(f"Using TRAIN set: {df_ltf.index[0]} → {df_ltf.index[-1]}")
        except Exception:
            pass

    log.info("Generating signals...")
    execer = ExecutionEngine(min_grade=SetupGrade[args.min_grade.replace("+", "_PLUS")])
    signals = execer.generate_signals(symbol, df_ltf, df_w, df_d, df_h4)

    log.info(f"Running backtest — {firm}/{variant}...")
    cfg = BacktestConfig(
        initial_balance=args.balance,
        firm=firm,
        variant=variant,
    )
    bt = Backtester(cfg)
    result = bt.run(symbol, df_ltf, signals)

    _print_result(result)

    if args.save:
        out = REPORTS_DIR / f"backtest_{symbol}_{firm}_{variant}_{datetime.utcnow():%Y%m%d_%H%M}.json"
        _save_result(out, result)
        log.info(f"Saved: {out}")

    # Monte Carlo
    if args.monte_carlo:
        log.info("\nRunning Monte Carlo (1000 simulations)...")
        mc = MonteCarlo(n_simulations=1000)
        mc_res = mc.reshuffle(result.trades, result.initial_balance)
        log.info(mc_res.summary())

    # Audit
    log.info("\nRunning audit...")
    auditor = AuditEngine()
    audit = auditor.audit(result)
    log.info(audit.summary())


def cmd_walkforward(args):
    symbol = args.symbol
    loader = DataLoader()
    feat_eng = FeatureEngine()

    df_w = loader.load(symbol, Timeframe.D1).resample("1W").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
    }).dropna()
    df_d = loader.load(symbol, Timeframe.D1)
    df_h4 = df_d  # fallback si H4 not available
    df_ltf = loader.load(symbol, Timeframe(args.ltf))
    df_ltf = feat_eng.compute(df_ltf)

    def train_fn(train_df):
        return None  # strategy is rule-based; no explicit training here

    def eval_fn(eval_df, _model):
        execer = ExecutionEngine(min_grade=SetupGrade.B)
        signals = execer.generate_signals(symbol, eval_df, df_w, df_d, df_h4)
        cfg = BacktestConfig(initial_balance=args.balance, firm=args.firm, variant=args.variant)
        bt = Backtester(cfg)
        return bt.run(symbol, eval_df, signals)

    wf = WalkForwardEngine(
        train_years=args.train_years,
        test_months=args.test_months,
        step_months=args.test_months,
    )
    report = wf.run(df_ltf, train_fn, eval_fn)
    s = report.summary()
    log.info("\n=== WALK-FORWARD SUMMARY ===")
    for k, v in s.items():
        log.info(f"  {k}: {v}")


def cmd_full(args):
    """Pipeline COMPLET : download → integrity → split → backtest → WF → audit."""
    log.info("====== PIPELINE FULL ======")
    log.info("1. Download (skip if cached)...")
    try:
        cmd_download(args)
    except Exception as e:
        log.warning(f"Download: {e}")

    log.info("\n2. Integrity check...")
    cmd_integrity(args)

    log.info("\n3. Split train/val/test...")
    cmd_split(args)

    log.info("\n4. Backtest...")
    cmd_backtest(args)

    log.info("\n5. Walk-Forward analysis...")
    cmd_walkforward(args)

    log.info("\n====== PIPELINE DONE ======")


# ------------------------------------------------------------------
def _print_result(r):
    log.info("\n=== BACKTEST RESULT ===")
    log.info(f"  Initial        : ${r.initial_balance:,.0f}")
    log.info(f"  Final          : ${r.final_balance:,.0f}")
    log.info(f"  Total return   : {r.total_return_pct:+.2f}%")
    log.info(f"  Max DD         : {r.max_drawdown_pct:.2f}%")
    log.info(f"  Max Daily DD   : {r.max_daily_drawdown_pct:.2f}%")
    log.info(f"  Sharpe         : {r.sharpe_ratio:.2f}")
    log.info(f"  Sortino        : {r.sortino_ratio:.2f}")
    log.info(f"  Calmar         : {r.calmar_ratio:.2f}")
    log.info(f"  Trades         : {r.total_trades}")
    log.info(f"  Win rate       : {r.win_rate * 100:.1f}%")
    log.info(f"  Avg win (R)    : {r.avg_win_r:.2f}")
    log.info(f"  Avg loss (R)   : {r.avg_loss_r:.2f}")
    log.info(f"  Expectancy (R) : {r.expectancy_r:.3f}")
    log.info(f"  Profit factor  : {r.profit_factor:.2f}")
    log.info(f"  Max cons. L    : {r.consecutive_losses_max}")
    log.info(f"  FTMO compliant : {r.ftmo_compliant}")
    log.info(f"  5ers compliant : {r.the5ers_compliant}")


def _save_result(path: Path, r) -> None:
    safe = {
        "initial_balance": r.initial_balance,
        "final_balance": r.final_balance,
        "total_return_pct": r.total_return_pct,
        "max_drawdown_pct": r.max_drawdown_pct,
        "max_daily_drawdown_pct": r.max_daily_drawdown_pct,
        "sharpe": r.sharpe_ratio,
        "sortino": r.sortino_ratio,
        "calmar": r.calmar_ratio,
        "win_rate": r.win_rate,
        "avg_win_r": r.avg_win_r,
        "avg_loss_r": r.avg_loss_r,
        "expectancy_r": r.expectancy_r,
        "profit_factor": r.profit_factor,
        "total_trades": r.total_trades,
        "consecutive_losses_max": r.consecutive_losses_max,
        "by_regime": r.performance_by_regime,
        "by_session": r.performance_by_session,
        "by_grade": r.performance_by_grade,
        "ftmo_compliant": r.ftmo_compliant,
        "the5ers_compliant": r.the5ers_compliant,
    }
    path.write_text(json.dumps(safe, indent=2, default=str))


# ------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="ICT Institutional Framework")
    p.add_argument("--mode", required=True,
                   choices=["download", "integrity", "split", "backtest",
                            "walkforward", "full"])
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--symbols", nargs="+", default=None)
    p.add_argument("--tfs", nargs="+", default=None)
    p.add_argument("--ltf", default="15m")
    p.add_argument("--firm", default="ftmo", choices=["ftmo", "the_5ers"])
    p.add_argument("--variant", default="classic_challenge")
    p.add_argument("--balance", type=float, default=100_000)
    p.add_argument("--min-grade", default="B", choices=["A+", "A", "B"])
    p.add_argument("--split", default="full", choices=["full", "train", "val", "test"])
    p.add_argument("--train-years", type=float, default=2.0)
    p.add_argument("--test-months", type=int, default=6)
    p.add_argument("--monte-carlo", action="store_true")
    p.add_argument("--include-m5", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--save", action="store_true", default=True)
    args = p.parse_args()

    mode_map = {
        "download": cmd_download,
        "integrity": cmd_integrity,
        "split": cmd_split,
        "backtest": cmd_backtest,
        "walkforward": cmd_walkforward,
        "full": cmd_full,
    }
    try:
        mode_map[args.mode](args)
    except KeyboardInterrupt:
        log.warning("Interrupted")
        sys.exit(130)


if __name__ == "__main__":
    main()
