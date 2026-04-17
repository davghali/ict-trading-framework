"""
FTMO Guards — Safety rules specific to FTMO challenges.

- ConsistencyTracker : enforce "best day <= 45% of total profit" (keeps margin vs 50% rule)
- MinTradingDaysTracker : track minimum 4 trading days for Swing
- NewsRestrictions : detect high-impact news windows
"""
from .consistency_tracker import ConsistencyTracker, ConsistencyStatus

__all__ = ["ConsistencyTracker", "ConsistencyStatus"]
