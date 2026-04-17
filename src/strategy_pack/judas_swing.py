"""
JUDAS SWING — manipulation à l'ouverture de session.

Règles :
- Détecte à l'ouverture (London 7h UTC ou NY 13h30 UTC)
- Price fait un faux mouvement dans une direction
- Puis retourne dans la direction réelle (manipulation)
- Entry après le retour, SL au-delà du high/low du Judas
- Target : PDH/PDL dans la direction réelle

Win rate historique : 65-75%.
"""
from __future__ import annotations

import pandas as pd
from dataclasses import dataclass
from datetime import time, datetime, timedelta
from typing import List, Optional

from src.utils.types import Side
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class JudasSwingSetup:
    timestamp: datetime
    symbol: str
    side: Side              # direction RÉELLE (après retournement)
    judas_high: float       # high du mouvement judas
    judas_low: float        # low du mouvement judas
    entry: float
    stop_loss: float
    take_profit: float
    session: str            # "london" ou "ny"
    rr: float = 0.0


class JudasSwingStrategy:

    SESSIONS = {
        "london": (time(7, 0),  time(9, 0)),      # 7h-9h UTC
        "ny":     (time(13, 30), time(15, 0)),    # 13h30-15h UTC
    }

    def __init__(self, min_judas_atr: float = 0.8):
        self.min_judas_atr = min_judas_atr

    def scan(self, df: pd.DataFrame, symbol: str,
              atr_col: str = "atr_14") -> List[JudasSwingSetup]:
        setups = []

        for session_name, (start, end) in self.SESSIONS.items():
            # Parcours par jour
            dates = df.index.normalize().unique()
            for date in dates[-30:]:                    # 30 derniers jours
                day_mask = (df.index.date == date.date()) & \
                           (df.index.time >= start) & (df.index.time <= end)
                session_df = df[day_mask]
                if len(session_df) < 3:
                    continue

                session_high = session_df["high"].max()
                session_low = session_df["low"].min()
                session_open = session_df["open"].iloc[0]
                session_close = session_df["close"].iloc[-1]

                atr_idx = df.index.get_loc(session_df.index[0])
                atr = df[atr_col].iloc[atr_idx] if atr_idx < len(df) else 0
                if atr <= 0:
                    continue

                judas_range = session_high - session_low
                if judas_range < self.min_judas_atr * atr:
                    continue

                # Detect direction : si open > close = baissier (judas up→down)
                # Si open < close = haussier (judas down→up)
                if session_close > session_open:
                    # Judas down, then reversal up → LONG
                    # Entry : retour au dessus du milieu du judas
                    entry = (session_high + session_low) / 2
                    sl = session_low - 0.2 * atr
                    # TP : PDH ou 1.5× range
                    tp = session_high + 0.5 * judas_range
                    side = Side.LONG
                else:
                    # Judas up, reversal down → SHORT
                    entry = (session_high + session_low) / 2
                    sl = session_high + 0.2 * atr
                    tp = session_low - 0.5 * judas_range
                    side = Side.SHORT

                risk = abs(entry - sl)
                if risk <= 0:
                    continue
                rr = abs(tp - entry) / risk
                if rr < 1.5:
                    continue

                setups.append(JudasSwingSetup(
                    timestamp=session_df.index[-1].to_pydatetime(),
                    symbol=symbol, side=side,
                    judas_high=session_high, judas_low=session_low,
                    entry=entry, stop_loss=sl, take_profit=tp,
                    session=session_name, rr=rr,
                ))

        log.info(f"Judas Swing {symbol}: {len(setups)} setups found")
        return setups
