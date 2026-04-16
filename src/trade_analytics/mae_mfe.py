"""
MAE/MFE Analytics — Maximum Adverse/Favorable Excursion.

Pour chaque trade fermé :
- MAE = max drawdown INTRA-trade (pire moment)
- MFE = max profit INTRA-trade (meilleur moment avant exit)

Insights :
- Si MFE >> exit_price → "j'ai sorti trop tôt"
- Si MAE close à SL → "j'ai évité le SL de justesse"
- Ratio MFE/MAE : qualité de gestion

Usage : après chaque trade fermé, calcule MAE/MFE depuis la data H1 du jour.
"""
from __future__ import annotations

import pandas as pd
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List

from src.data_engine import DataLoader
from src.trade_journal import TradeJournal, JournalEntry
from src.utils.types import Timeframe
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class MAEMFEResult:
    trade_id: str
    symbol: str
    side: str
    entry: float
    exit: Optional[float]
    mae: float              # max adverse excursion (USD/pts)
    mfe: float              # max favorable excursion
    mae_r: float            # en R multiples
    mfe_r: float
    exit_efficiency: float  # exit_pnl / MFE (0-1, 1 = exit au sommet)


class MAEMFEAnalyzer:

    def __init__(self):
        self.loader = DataLoader()
        self.journal = TradeJournal()

    # ------------------------------------------------------------------
    def analyze_trade(self, trade: JournalEntry) -> Optional[MAEMFEResult]:
        if not trade.is_closed or not trade.entry_time or not trade.exit_time:
            return None

        try:
            entry_ts = datetime.fromisoformat(trade.entry_time)
            exit_ts = datetime.fromisoformat(trade.exit_time)
        except Exception:
            return None

        # Load H1 data around the trade
        try:
            df = self.loader.load(trade.symbol, Timeframe.H1)
        except Exception:
            try:
                df = self.loader.load(trade.symbol, Timeframe.D1)
            except Exception:
                return None

        # Convert index to tz-aware if needed
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        import pytz
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.replace(tzinfo=pytz.UTC)
        if exit_ts.tzinfo is None:
            exit_ts = exit_ts.replace(tzinfo=pytz.UTC)

        # Intra-trade window
        mask = (df.index >= entry_ts) & (df.index <= exit_ts)
        sub = df[mask]
        if sub.empty:
            return None

        entry = trade.entry
        sl = trade.stop_loss
        risk_unit = abs(entry - sl)
        if risk_unit == 0:
            return None

        if trade.side == "long":
            mfe = sub["high"].max() - entry
            mae = entry - sub["low"].min()
        else:
            mfe = entry - sub["low"].min()
            mae = sub["high"].max() - entry

        mfe_r = mfe / risk_unit
        mae_r = mae / risk_unit

        # Exit efficiency
        if mfe <= 0:
            exit_eff = 0.0
        elif trade.exit_fill is None:
            exit_eff = 0.0
        else:
            realised_pnl = abs(trade.exit_fill - entry)
            if trade.side == "long":
                realised_pnl = trade.exit_fill - entry
            else:
                realised_pnl = entry - trade.exit_fill
            exit_eff = max(0, realised_pnl / mfe) if mfe > 0 else 0

        return MAEMFEResult(
            trade_id=trade.trade_id,
            symbol=trade.symbol,
            side=trade.side,
            entry=entry,
            exit=trade.exit_fill,
            mae=mae,
            mfe=mfe,
            mae_r=round(mae_r, 2),
            mfe_r=round(mfe_r, 2),
            exit_efficiency=round(exit_eff, 2),
        )

    # ------------------------------------------------------------------
    def analyze_all_closed(self) -> List[MAEMFEResult]:
        results = []
        for trade in self.journal.load_all():
            if trade.is_closed:
                r = self.analyze_trade(trade)
                if r:
                    results.append(r)
        return results

    # ------------------------------------------------------------------
    def aggregate_stats(self) -> dict:
        results = self.analyze_all_closed()
        if not results:
            return {"n": 0}

        avg_mae = sum(r.mae_r for r in results) / len(results)
        avg_mfe = sum(r.mfe_r for r in results) / len(results)
        avg_eff = sum(r.exit_efficiency for r in results) / len(results)

        # Trades where MFE was 2R+ but we exited at 1R → "exit too early"
        exit_too_early = [
            r for r in results
            if r.mfe_r >= 2.0 and r.exit_efficiency < 0.5
        ]

        return {
            "n": len(results),
            "avg_mae_r": round(avg_mae, 2),
            "avg_mfe_r": round(avg_mfe, 2),
            "avg_exit_efficiency": round(avg_eff, 2),
            "exit_too_early_count": len(exit_too_early),
            "improvement_opportunity": round(
                sum(r.mfe_r - r.exit_efficiency * r.mfe_r for r in results), 2
            ),
        }
