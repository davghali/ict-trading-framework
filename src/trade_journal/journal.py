"""
Trade Journal — log des trades RÉELS + comparaison aux signaux prédits.

Persistance : user_data/journal.jsonl (append-only, 1 trade par ligne)

Analyse :
- WR réel vs WR prédit par ML
- Analyse par asset, killzone, jour
- Equity curve réelle
- Calibration : le ML dit-il la vérité ?
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd


USER_DATA_DIR = Path(__file__).parents[2] / "user_data"
USER_DATA_DIR.mkdir(exist_ok=True)
JOURNAL_FILE = USER_DATA_DIR / "journal.jsonl"


@dataclass
class JournalEntry:
    """Un trade exécuté dans le réel."""
    trade_id: str                       # uuid ou timestamp-based
    created_at: str                     # ISO
    symbol: str
    ltf: str
    side: str                            # long / short
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: Optional[float] = None
    # Signal source (si vient d'un signal ML)
    source_signal_id: str = ""
    ml_prob_win_at_signal: Optional[float] = None
    tier_at_signal: str = ""
    # Exécution
    entry_time: Optional[str] = None
    entry_fill: Optional[float] = None
    exit_time: Optional[str] = None
    exit_fill: Optional[float] = None
    exit_reason: str = ""                # tp1, tp2, sl, manual, be
    # Sizing
    lots: float = 0.0
    risk_usd: float = 0.0
    # Outcome
    pnl_usd: float = 0.0
    pnl_r: float = 0.0
    # Notes
    notes: str = ""
    # Context
    killzone: str = ""
    news_nearby: bool = False

    @property
    def is_closed(self) -> bool:
        return self.exit_time is not None

    @property
    def is_win(self) -> bool:
        return self.is_closed and self.pnl_usd > 0


class TradeJournal:

    def __init__(self, path: Path = JOURNAL_FILE):
        self.path = path
        self.path.parent.mkdir(exist_ok=True)

    def log(self, entry: JournalEntry) -> None:
        """Append un trade. Si le trade_id existe déjà, met à jour."""
        entries = self.load_all()
        # replace if same id
        entries = [e for e in entries if e.trade_id != entry.trade_id]
        entries.append(entry)
        # Rewrite file
        with self.path.open("w") as f:
            for e in entries:
                f.write(json.dumps(asdict(e)) + "\n")

    def load_all(self) -> List[JournalEntry]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                out.append(JournalEntry(**d))
            except Exception:
                continue
        return out

    def close_trade(
        self,
        trade_id: str,
        exit_time: str,
        exit_fill: float,
        pnl_usd: float,
        pnl_r: float,
        exit_reason: str = "manual",
    ) -> bool:
        entries = self.load_all()
        for e in entries:
            if e.trade_id == trade_id and not e.is_closed:
                e.exit_time = exit_time
                e.exit_fill = exit_fill
                e.pnl_usd = pnl_usd
                e.pnl_r = pnl_r
                e.exit_reason = exit_reason
                self.log(e)
                return True
        return False

    def delete(self, trade_id: str) -> bool:
        entries = [e for e in self.load_all() if e.trade_id != trade_id]
        with self.path.open("w") as f:
            for e in entries:
                f.write(json.dumps(asdict(e)) + "\n")
        return True

    def to_dataframe(self) -> pd.DataFrame:
        entries = self.load_all()
        if not entries:
            return pd.DataFrame()
        return pd.DataFrame([asdict(e) for e in entries])

    # --------------------------------------------------------------
    def analytics(self) -> dict:
        """Stats sur tous les trades fermés."""
        closed = [e for e in self.load_all() if e.is_closed]
        if not closed:
            return {"n_closed": 0}

        wins = sum(1 for e in closed if e.pnl_usd > 0)
        total_pnl = sum(e.pnl_usd for e in closed)
        total_r = sum(e.pnl_r for e in closed)

        # Compare ML prediction to actual
        with_ml = [e for e in closed if e.ml_prob_win_at_signal is not None]
        if with_ml:
            avg_predicted = sum(e.ml_prob_win_at_signal for e in with_ml) / len(with_ml)
            actual = sum(1 for e in with_ml if e.is_win) / len(with_ml)
            calibration_delta = actual - avg_predicted
        else:
            avg_predicted = actual = calibration_delta = None

        return {
            "n_closed": len(closed),
            "n_wins": wins,
            "win_rate": wins / len(closed),
            "total_pnl_usd": total_pnl,
            "total_pnl_r": total_r,
            "avg_r_per_trade": total_r / len(closed),
            "ml_calibration": {
                "n_with_ml": len(with_ml),
                "avg_predicted_winrate": avg_predicted,
                "actual_winrate": actual,
                "delta": calibration_delta,
            },
        }

    def by_asset(self) -> pd.DataFrame:
        closed = [e for e in self.load_all() if e.is_closed]
        if not closed:
            return pd.DataFrame()
        df = pd.DataFrame([asdict(e) for e in closed])
        grouped = df.groupby("symbol").agg(
            n=("trade_id", "count"),
            wr=("pnl_usd", lambda x: (x > 0).mean()),
            total_pnl=("pnl_usd", "sum"),
            avg_r=("pnl_r", "mean"),
        ).reset_index()
        return grouped

    def by_killzone(self) -> pd.DataFrame:
        closed = [e for e in self.load_all() if e.is_closed]
        if not closed:
            return pd.DataFrame()
        df = pd.DataFrame([asdict(e) for e in closed])
        grouped = df.groupby("killzone").agg(
            n=("trade_id", "count"),
            wr=("pnl_usd", lambda x: (x > 0).mean()),
            total_pnl=("pnl_usd", "sum"),
        ).reset_index()
        return grouped

    def equity_curve(self, initial: float = 100_000) -> pd.DataFrame:
        closed = [e for e in self.load_all() if e.is_closed]
        if not closed:
            return pd.DataFrame()
        df = pd.DataFrame([asdict(e) for e in closed])
        df["exit_time"] = pd.to_datetime(df["exit_time"])
        df = df.sort_values("exit_time")
        df["cumulative_pnl"] = df["pnl_usd"].cumsum()
        df["equity"] = initial + df["cumulative_pnl"]
        return df[["exit_time", "pnl_usd", "equity"]]
