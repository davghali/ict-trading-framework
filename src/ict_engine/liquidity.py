"""
Liquidity Detector — PDH, PDL, PWH, PWL, PMH, PML, EQH, EQL, sessions.

Pools de liquidité = targets ICT classiques.
- PDH/PDL : Previous Day High/Low
- PWH/PWL : Previous Week High/Low
- PMH/PML : Previous Month High/Low
- EQH/EQL : Equal Highs/Lows (stops cluster)
- Sessions : Asia/London/NY highs & lows

Détection des sweeps : price traverse le pool avec une MÈCHE mais pas
de close derrière → "run on liquidity".
"""
from __future__ import annotations

import pandas as pd
from typing import List, Dict

from src.utils.types import LiquidityPool, LiquidityType
from src.utils.logging_conf import get_logger

log = get_logger(__name__)


class LiquidityDetector:

    def __init__(
        self,
        eq_tolerance_pips: float = 0.0002,  # pour forex 4-digit
        eq_min_occurrences: int = 2,
        eq_min_separation_bars: int = 5,
    ):
        self.eq_tol = eq_tolerance_pips
        self.eq_min_occ = eq_min_occurrences
        self.eq_min_sep = eq_min_separation_bars

    # ------------------------------------------------------------------
    def detect_session_levels(self, df: pd.DataFrame) -> List[LiquidityPool]:
        """PDH/PDL/PWH/PWL/PMH/PML calculés à la clôture de chaque période."""
        out: List[LiquidityPool] = []

        # Daily
        daily = df.resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
        for i in range(1, len(daily)):
            ts = daily.index[i]
            out.append(LiquidityPool(
                ltype=LiquidityType.PDH,
                price=float(daily["high"].iloc[i - 1]),
                timestamp=ts.to_pydatetime(),
                strength=1.0,
            ))
            out.append(LiquidityPool(
                ltype=LiquidityType.PDL,
                price=float(daily["low"].iloc[i - 1]),
                timestamp=ts.to_pydatetime(),
                strength=1.0,
            ))

        # Weekly
        weekly = df.resample("1W").agg({"high": "max", "low": "min"}).dropna()
        for i in range(1, len(weekly)):
            ts = weekly.index[i]
            out.append(LiquidityPool(
                ltype=LiquidityType.PWH,
                price=float(weekly["high"].iloc[i - 1]),
                timestamp=ts.to_pydatetime(),
                strength=2.0,  # weekly plus fort
            ))
            out.append(LiquidityPool(
                ltype=LiquidityType.PWL,
                price=float(weekly["low"].iloc[i - 1]),
                timestamp=ts.to_pydatetime(),
                strength=2.0,
            ))

        # Monthly
        monthly = df.resample("1ME").agg({"high": "max", "low": "min"}).dropna()
        for i in range(1, len(monthly)):
            ts = monthly.index[i]
            out.append(LiquidityPool(
                ltype=LiquidityType.PMH,
                price=float(monthly["high"].iloc[i - 1]),
                timestamp=ts.to_pydatetime(),
                strength=3.0,
            ))
            out.append(LiquidityPool(
                ltype=LiquidityType.PML,
                price=float(monthly["low"].iloc[i - 1]),
                timestamp=ts.to_pydatetime(),
                strength=3.0,
            ))

        return out

    # ------------------------------------------------------------------
    def detect_equal_highs_lows(self, df: pd.DataFrame, lookback: int = 100) -> List[LiquidityPool]:
        """Equal Highs / Equal Lows : clusters de highs/lows dans une tolérance."""
        out: List[LiquidityPool] = []
        h = df["high"].values
        l = df["low"].values
        idx = df.index

        # Pour chaque bar, cherche backward s'il existe un high/low similaire
        for t in range(lookback, len(df)):
            window_hi = h[t - lookback : t]
            window_lo = l[t - lookback : t]

            # EQH
            matches_hi = sum(abs(window_hi - h[t]) <= self.eq_tol * h[t])
            if matches_hi >= self.eq_min_occ:
                out.append(LiquidityPool(
                    ltype=LiquidityType.EQH,
                    price=float(h[t]),
                    timestamp=idx[t].to_pydatetime(),
                    strength=float(matches_hi),
                ))
            # EQL
            matches_lo = sum(abs(window_lo - l[t]) <= self.eq_tol * l[t])
            if matches_lo >= self.eq_min_occ:
                out.append(LiquidityPool(
                    ltype=LiquidityType.EQL,
                    price=float(l[t]),
                    timestamp=idx[t].to_pydatetime(),
                    strength=float(matches_lo),
                ))
        return out

    # ------------------------------------------------------------------
    def mark_sweeps(self, pools: List[LiquidityPool], df: pd.DataFrame,
                    close_beyond_bars: int = 2) -> None:
        """
        Un sweep = price crosses the pool avec une MÈCHE, mais close revient en-deçà
        dans les N bars suivantes. Indique un faux breakout / stop run.
        """
        h = df["high"]
        l = df["low"]
        c = df["close"]

        for pool in pools:
            if pool.timestamp not in df.index:
                continue
            start_idx = df.index.get_loc(pool.timestamp)
            after = df.iloc[start_idx + 1 :]
            if after.empty:
                continue

            if pool.ltype in (LiquidityType.PDH, LiquidityType.PWH, LiquidityType.PMH,
                              LiquidityType.EQH, LiquidityType.SESSION_HIGH):
                # High pool : sweep = high > pool.price puis close < pool.price
                breach_mask = after["high"] > pool.price
                if breach_mask.any():
                    first_breach = after[breach_mask].index[0]
                    fb_idx = df.index.get_loc(first_breach)
                    window = df.iloc[fb_idx : fb_idx + close_beyond_bars + 1]
                    if (window["close"] < pool.price).any():
                        pool.swept = True
                        pool.swept_at = first_breach.to_pydatetime()
                        pool.swept_at_price = float(h.loc[first_breach])
            else:
                # Low pool : sweep = low < pool.price puis close > pool.price
                breach_mask = after["low"] < pool.price
                if breach_mask.any():
                    first_breach = after[breach_mask].index[0]
                    fb_idx = df.index.get_loc(first_breach)
                    window = df.iloc[fb_idx : fb_idx + close_beyond_bars + 1]
                    if (window["close"] > pool.price).any():
                        pool.swept = True
                        pool.swept_at = first_breach.to_pydatetime()
                        pool.swept_at_price = float(l.loc[first_breach])

    # ------------------------------------------------------------------
    def detect_all(self, df: pd.DataFrame) -> Dict[str, List[LiquidityPool]]:
        session_pools = self.detect_session_levels(df)
        eq_pools = self.detect_equal_highs_lows(df)
        all_pools = session_pools + eq_pools
        self.mark_sweeps(all_pools, df)

        swept_count = sum(1 for p in all_pools if p.swept)
        log.info(f"Liquidity: {len(all_pools)} pools ({swept_count} swept)")
        return {
            "session": session_pools,
            "equal": eq_pools,
            "all": all_pools,
        }

    def to_dataframe(self, pools: List[LiquidityPool]) -> pd.DataFrame:
        if not pools:
            return pd.DataFrame()
        return pd.DataFrame([vars(p) | {"ltype": p.ltype.value} for p in pools])
