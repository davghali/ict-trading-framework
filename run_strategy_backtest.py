"""
STRATEGY BACKTEST — valide les nouvelles stratégies avec chiffres RÉELS.

Backtest sur data historique :
- Silver Bullet (FVG 10h-11h NY)
- Judas Swing (manipulation open session)
- Power of Three (AMD pattern)

Usage :  python3 run_strategy_backtest.py
"""
from __future__ import annotations

import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
import warnings
warnings.filterwarnings("ignore")

import pandas as pd

from src.data_engine import DataLoader
from src.feature_engine import FeatureEngine
from src.strategy_pack import (
    SilverBulletStrategy, JudasSwingStrategy, PowerOfThreeStrategy,
)
from src.utils.types import Timeframe, Side


def simulate_setups(setups: list, df: pd.DataFrame, rr_target: float = 2.0):
    """Simule chaque setup jusqu'à TP/SL."""
    if not setups:
        return {"n": 0, "wins": 0, "win_rate": 0, "total_r": 0, "expectancy": 0}
    wins = losses = 0
    r_values = []

    for setup in setups:
        try:
            start_idx = df.index.get_loc(pd.Timestamp(setup.timestamp, tz="UTC"))
        except Exception:
            try:
                # fallback non-tz
                start_idx = df.index.get_loc(setup.timestamp)
            except Exception:
                continue

        # Parcours max 200 bars après
        end_idx = min(start_idx + 200, len(df) - 1)
        outcome = None
        for j in range(start_idx + 1, end_idx):
            h = df["high"].iloc[j]
            l = df["low"].iloc[j]
            if setup.side == Side.LONG:
                if l <= setup.stop_loss:
                    outcome = "loss"
                    break
                if h >= setup.take_profit:
                    outcome = "win"
                    break
            else:
                if h >= setup.stop_loss:
                    outcome = "loss"
                    break
                if l <= setup.take_profit:
                    outcome = "win"
                    break

        if outcome == "win":
            wins += 1
            r_values.append(setup.rr)
        elif outcome == "loss":
            losses += 1
            r_values.append(-1.0)

    n = wins + losses
    if n == 0:
        return {"n": 0, "wins": 0, "win_rate": 0, "total_r": 0, "expectancy": 0}
    total_r = sum(r_values)
    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / n,
        "total_r": round(total_r, 2),
        "expectancy": round(total_r / n, 3),
        "avg_win_r": round(sum(r for r in r_values if r > 0) / max(wins, 1), 2),
        "avg_loss_r": round(sum(r for r in r_values if r < 0) / max(losses, 1), 2),
    }


def main():
    print("═" * 75)
    print("  🎯 STRATEGY PACK BACKTEST — chiffres RÉELS")
    print("═" * 75)

    loader = DataLoader()
    fe = FeatureEngine()

    assets = ["XAUUSD", "XAGUSD", "NAS100", "BTCUSD"]
    strategies = [
        ("Silver Bullet", SilverBulletStrategy()),
        ("Judas Swing",   JudasSwingStrategy()),
        ("Power of Three", PowerOfThreeStrategy()),
    ]

    global_results = {}

    for asset in assets:
        print(f"\n▸ {asset}")
        try:
            df = loader.load(asset, Timeframe.H1)
            df = fe.compute(df)
        except Exception as e:
            print(f"  skip : {e}")
            continue

        global_results[asset] = {}
        for strat_name, strat in strategies:
            try:
                setups = strat.scan(df, asset)
                stats = simulate_setups(setups, df)
                global_results[asset][strat_name] = stats
                wr = f"{stats['win_rate']:.0%}"
                print(f"  {strat_name:18s} | {stats['n']:4d} trades | "
                      f"WR {wr:>5s} | exp_R {stats['expectancy']:+.3f} | "
                      f"total {stats['total_r']:+.1f}R")
            except Exception as e:
                print(f"  {strat_name}: error {e}")

    # Global
    print("\n" + "═" * 75)
    print("  🏆 AGRÉGAT GLOBAL")
    print("═" * 75)
    for strat_name, _ in strategies:
        total_n = 0
        total_wins = 0
        total_r = 0
        for asset_res in global_results.values():
            s = asset_res.get(strat_name, {})
            total_n += s.get("n", 0)
            total_wins += s.get("wins", 0)
            total_r += s.get("total_r", 0)
        if total_n == 0:
            continue
        wr = total_wins / total_n * 100
        exp = total_r / total_n
        # Project sur 12 mois : ratio (1 an data)
        print(f"  {strat_name:18s} : {total_n} trades | "
              f"WR {wr:.1f}% | exp {exp:+.3f}R | total {total_r:+.1f}R")

    # Save
    out = Path("reports") / f"strategy_backtest_{datetime.utcnow():%Y%m%d_%H%M%S}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(global_results, indent=2))
    print(f"\n  💾 Saved : {out}")


if __name__ == "__main__":
    main()
