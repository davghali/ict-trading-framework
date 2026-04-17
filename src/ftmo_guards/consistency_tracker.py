"""
Consistency Tracker — FTMO rule "best day <= 50% of total profit".

On applique 45% de seuil (marge de sécurité vs 50% FTMO).
Si le jour actuel dépasse ce seuil, on bloque les nouveaux trades pour la journée.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional


STATE_FILE = Path(__file__).parents[2] / "user_data" / "consistency_state.json"


@dataclass
class ConsistencyStatus:
    allowed: bool
    reason: str
    current_day_pnl: float = 0.0
    total_profit: float = 0.0
    best_day_pnl: float = 0.0
    best_day_pct_of_total: float = 0.0
    threshold_pct: float = 45.0


class ConsistencyTracker:
    """Track daily PnL and enforce FTMO consistency rule."""

    def __init__(
        self,
        threshold_pct: float = 45.0,
        state_file: Optional[Path] = None,
    ):
        self.threshold_pct = threshold_pct
        self.state_file = state_file or STATE_FILE
        self.daily_pnl: Dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_file.exists():
            return
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.daily_pnl = data.get("daily_pnl", {})
        except Exception:
            pass

    def _save(self) -> None:
        try:
            self.state_file.parent.mkdir(exist_ok=True)
            self.state_file.write_text(
                json.dumps({"daily_pnl": self.daily_pnl}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _today_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def record_pnl(self, pnl_usd: float) -> None:
        """Ajoute un PnL au total du jour (appelé après chaque trade clos)."""
        key = self._today_key()
        self.daily_pnl[key] = self.daily_pnl.get(key, 0.0) + pnl_usd
        self._save()

    def get_status(self, additional_planned_pnl: float = 0.0) -> ConsistencyStatus:
        """
        Retourne le statut actuel. Si additional_planned_pnl fourni,
        simule l'impact d'un trade supplémentaire avant de décider.
        """
        today = self._today_key()
        current_day = self.daily_pnl.get(today, 0.0) + additional_planned_pnl
        # Total profit = somme des jours POSITIFS
        positive_days = {k: v for k, v in self.daily_pnl.items() if v > 0}
        if today in positive_days:
            positive_days[today] = current_day
        elif current_day > 0:
            positive_days[today] = current_day

        total_profit = sum(positive_days.values())
        best_day_pnl = max(positive_days.values(), default=0.0)
        best_pct = (best_day_pnl / total_profit * 100) if total_profit > 0 else 0.0

        # Si total < 500 USD, pas de vérif (trop peu pour être pertinent)
        if total_profit < 500:
            return ConsistencyStatus(
                allowed=True,
                reason="Below 500 USD total profit threshold — consistency not enforced",
                current_day_pnl=current_day,
                total_profit=total_profit,
                best_day_pnl=best_day_pnl,
                best_day_pct_of_total=best_pct,
                threshold_pct=self.threshold_pct,
            )

        if best_pct > self.threshold_pct:
            return ConsistencyStatus(
                allowed=False,
                reason=(
                    f"Consistency rule HIT: best day ({best_day_pnl:.0f} USD) "
                    f"= {best_pct:.1f}% of total ({total_profit:.0f} USD) "
                    f"> threshold {self.threshold_pct}%"
                ),
                current_day_pnl=current_day,
                total_profit=total_profit,
                best_day_pnl=best_day_pnl,
                best_day_pct_of_total=best_pct,
                threshold_pct=self.threshold_pct,
            )

        return ConsistencyStatus(
            allowed=True,
            reason=f"OK (best day {best_pct:.1f}% <= {self.threshold_pct}%)",
            current_day_pnl=current_day,
            total_profit=total_profit,
            best_day_pnl=best_day_pnl,
            best_day_pct_of_total=best_pct,
            threshold_pct=self.threshold_pct,
        )

    def summary(self) -> str:
        status = self.get_status()
        return (
            f"Consistency: {'OK' if status.allowed else 'BLOCKED'} | "
            f"Today: {status.current_day_pnl:+.0f} USD | "
            f"Total: {status.total_profit:+.0f} USD | "
            f"Best day: {status.best_day_pnl:+.0f} ({status.best_day_pct_of_total:.1f}%)"
        )
