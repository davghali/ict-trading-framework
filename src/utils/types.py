"""
Types & Enums — Vocabulaire formel du framework.

Toute la logique utilise ces types. Jamais de strings magiques.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List


# ============================================================
# ENUMS
# ============================================================

class Side(Enum):
    LONG = "long"
    SHORT = "short"


class Timeframe(Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1wk"
    MN1 = "1mo"

    @property
    def minutes(self) -> int:
        return {
            "1m": 1, "5m": 5, "15m": 15, "30m": 30,
            "1h": 60, "4h": 240, "1d": 1440,
            "1wk": 10080, "1mo": 43200,
        }[self.value]


class Regime(Enum):
    TRENDING_HIGH_VOL = "trending_high_vol"
    TRENDING_LOW_VOL = "trending_low_vol"
    RANGING_HIGH_VOL = "ranging_high_vol"
    RANGING_LOW_VOL = "ranging_low_vol"
    MANIPULATION = "manipulation"
    UNKNOWN = "unknown"


class BiasDirection(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SetupGrade(Enum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    REJECT = "reject"


class ICTElement(Enum):
    FVG = "fvg"
    ORDER_BLOCK = "ob"
    BREAKER_BLOCK = "bb"
    IFVG = "ifvg"
    LIQUIDITY_POOL = "liquidity"
    SMT_DIVERGENCE = "smt"


class LiquidityType(Enum):
    PDH = "pdh"   # Previous Day High
    PDL = "pdl"   # Previous Day Low
    PWH = "pwh"   # Previous Week High
    PWL = "pwl"   # Previous Week Low
    PMH = "pmh"   # Previous Month High
    PML = "pml"   # Previous Month Low
    EQH = "eqh"   # Equal Highs
    EQL = "eql"   # Equal Lows
    SESSION_HIGH = "session_high"
    SESSION_LOW = "session_low"


# ============================================================
# DATACLASSES — STRUCTURES CORE
# ============================================================

@dataclass
class FVG:
    """Fair Value Gap formalisé."""
    index: int                          # bar index in df
    timestamp: datetime
    side: Side                          # bullish or bearish gap
    top: float                          # upper boundary
    bottom: float                        # lower boundary
    size: float                         # top - bottom
    size_in_atr: float                  # size / ATR at formation (NORMALIZED)
    displacement: float                 # momentum of the 3rd candle (range/body)
    impulsion_score: float              # composite score of strength
    ce: float                           # Consequent Encroachment (midpoint)
    filled: bool = False
    filled_at_index: Optional[int] = None
    respected: int = 0                  # count of times price respected it
    # Quality metrics
    volume_at_formation: float = 0.0
    overlap_with_ob: bool = False       # does this FVG overlap with an OB?
    irl_erl: str = "unknown"            # Internal Range Liquidity vs External

    @property
    def is_valid(self) -> bool:
        return self.top > self.bottom and self.size > 0


@dataclass
class OrderBlock:
    """Order Block — valide uniquement si FVG présent (règle ICT stricte)."""
    index: int
    timestamp: datetime
    side: Side
    high: float
    low: float
    open: float
    close: float
    associated_fvg_index: Optional[int] = None   # MUST exist for validity
    is_valid: bool = False                        # True only if FVG confirmed
    tested: int = 0
    held: bool = True                             # did price respect it?
    strength_score: float = 0.0


@dataclass
class BreakerBlock:
    """Breaker Block — ancien OB violé puis retesté dans le sens inverse."""
    origin_ob_index: int
    index: int
    timestamp: datetime
    side: Side                          # direction après break
    high: float
    low: float
    associated_ifvg_index: Optional[int] = None
    is_valid: bool = False


@dataclass
class LiquidityPool:
    """Pool de liquidité — PDH/PDL/EQH/EQL/sessions."""
    ltype: LiquidityType
    price: float
    timestamp: datetime
    swept: bool = False
    swept_at: Optional[datetime] = None
    swept_at_price: Optional[float] = None
    strength: float = 1.0               # multi-touch = stronger


@dataclass
class Signal:
    """Signal de trading — output du Scoring Engine."""
    timestamp: datetime
    symbol: str
    side: Side
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: Optional[float]
    grade: SetupGrade
    score: float                        # 0-100
    confluence_count: int
    reasons: List[str] = field(default_factory=list)
    # Context
    htf_bias: BiasDirection = BiasDirection.NEUTRAL
    regime: Regime = Regime.UNKNOWN
    killzone: str = ""
    fvg_ref: Optional[FVG] = None
    ob_ref: Optional[OrderBlock] = None
    swept_liquidity: Optional[LiquidityPool] = None
    # Risk metrics
    risk_reward: float = 0.0
    risk_pct: float = 0.0
    position_size: float = 0.0


@dataclass
class Trade:
    """Trade exécuté — piste d'audit complète."""
    signal: Signal
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""               # "tp1", "tp2", "sl", "trailing", "manual"
    pnl_usd: float = 0.0
    pnl_r: float = 0.0                  # en multiples de R (risque initial)
    pnl_pct: float = 0.0                # % du balance au moment du trade
    commission_usd: float = 0.0
    slippage_usd: float = 0.0
    duration_bars: int = 0

    @property
    def is_win(self) -> bool:
        return self.pnl_usd > 0

    @property
    def is_open(self) -> bool:
        return self.exit_time is None


@dataclass
class BacktestResult:
    """Résultats agrégés d'un backtest."""
    trades: List[Trade]
    initial_balance: float
    final_balance: float
    total_return_pct: float
    max_drawdown_pct: float
    max_daily_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    win_rate: float
    avg_win_r: float
    avg_loss_r: float
    expectancy_r: float
    profit_factor: float
    total_trades: int
    consecutive_wins_max: int
    consecutive_losses_max: int
    # Régime-split
    performance_by_regime: dict = field(default_factory=dict)
    performance_by_session: dict = field(default_factory=dict)
    performance_by_grade: dict = field(default_factory=dict)
    # Compliance
    ftmo_compliant: bool = False
    the5ers_compliant: bool = False
    violations: List[str] = field(default_factory=list)
