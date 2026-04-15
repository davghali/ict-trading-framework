"""
Audit Engine — RED TEAM du système.

Cherche ACTIVEMENT :
1. Illusions de performance (résultats trop beaux)
2. Biais cachés (cherry picking, survivorship)
3. Leakage résiduel
4. Instabilité temporelle (performance concentrée sur une période)
5. Sensibilité aux paramètres (robustesse fragile)
6. Risk of ruin caché

VERDICT final :
- PASSED : système est sain dans les limites testées
- WARNING : concerns importants à investiguer
- REJECTED : le système n'est PAS DÉPLOYABLE
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict

from src.utils.types import BacktestResult, Trade
from src.utils.logging_conf import get_logger
from src.backtest_engine.walk_forward import WalkForwardReport

log = get_logger(__name__)


@dataclass
class AuditFinding:
    severity: str                       # "INFO", "WARNING", "CRITICAL"
    category: str
    message: str
    evidence: dict = field(default_factory=dict)


@dataclass
class AuditReport:
    verdict: str                        # "PASSED", "WARNING", "REJECTED"
    findings: List[AuditFinding] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "CRITICAL")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "WARNING")

    def summary(self) -> str:
        out = [f"\n=== AUDIT REPORT: {self.verdict} ==="]
        out.append(f"Critical: {self.critical_count} | Warnings: {self.warning_count}")
        for f in self.findings:
            out.append(f"  [{f.severity}] {f.category}: {f.message}")
        return "\n".join(out)


class AuditEngine:

    def __init__(
        self,
        too_good_sharpe: float = 3.5,
        too_good_winrate: float = 0.80,
        min_trades_for_stability: int = 50,
        max_time_concentration_pct: float = 0.40,
    ):
        self.too_good_sharpe = too_good_sharpe
        self.too_good_winrate = too_good_winrate
        self.min_trades = min_trades_for_stability
        self.max_time_conc = max_time_concentration_pct

    # ------------------------------------------------------------------
    def audit(
        self,
        result: BacktestResult,
        wf_report: WalkForwardReport | None = None,
    ) -> AuditReport:
        report = AuditReport(verdict="PASSED")

        self._check_performance_plausibility(result, report)
        self._check_trade_count(result, report)
        self._check_time_concentration(result, report)
        self._check_sharpe_vs_drawdown(result, report)
        self._check_breakdowns(result, report)
        self._check_compliance(result, report)

        if wf_report:
            self._check_walk_forward(wf_report, report)

        self._finalize_verdict(report)
        return report

    # ------------------------------------------------------------------
    def _check_performance_plausibility(self, r: BacktestResult, rep: AuditReport) -> None:
        # Sharpe absurdement élevé
        if r.sharpe_ratio > self.too_good_sharpe:
            rep.findings.append(AuditFinding(
                severity="CRITICAL",
                category="Too Good To Be True",
                message=(
                    f"Sharpe {r.sharpe_ratio:.2f} > {self.too_good_sharpe}. "
                    "Strong suspicion of look-ahead, overfitting, or survivorship bias."
                ),
                evidence={"sharpe": r.sharpe_ratio},
            ))

        # Win rate absurdement élevé
        if r.win_rate > self.too_good_winrate:
            rep.findings.append(AuditFinding(
                severity="CRITICAL",
                category="Too Good To Be True",
                message=(
                    f"Win rate {r.win_rate * 100:.1f}% > {self.too_good_winrate * 100}%. "
                    "Verify no data leakage, fill assumptions, or cherry picking."
                ),
                evidence={"win_rate": r.win_rate},
            ))

        # Profit factor extreme
        if r.profit_factor > 5:
            rep.findings.append(AuditFinding(
                severity="WARNING",
                category="Too Good To Be True",
                message=f"Profit factor {r.profit_factor:.2f} — verify avg_loss is realistic",
            ))

    def _check_trade_count(self, r: BacktestResult, rep: AuditReport) -> None:
        if r.total_trades < 30:
            rep.findings.append(AuditFinding(
                severity="CRITICAL",
                category="Statistical Significance",
                message=f"Only {r.total_trades} trades — insufficient for any statistical claim",
            ))
        elif r.total_trades < self.min_trades:
            rep.findings.append(AuditFinding(
                severity="WARNING",
                category="Statistical Significance",
                message=f"{r.total_trades} trades — marginally significant (recommend ≥{self.min_trades})",
            ))

    def _check_time_concentration(self, r: BacktestResult, rep: AuditReport) -> None:
        """Détecte si > X% du profit vient d'une seule courte période."""
        if not r.trades:
            return
        pnls = np.array([t.pnl_usd for t in r.trades])
        dates = pd.DatetimeIndex([pd.Timestamp(t.exit_time) for t in r.trades if t.exit_time])
        if len(dates) < 10:
            return

        # Bucketing par mois
        months = dates.to_period("M")
        monthly = pd.Series(pnls[:len(months)]).groupby(months).sum()
        total = monthly.sum()
        if total <= 0:
            return

        max_month_pct = monthly.max() / total
        if max_month_pct > self.max_time_conc:
            rep.findings.append(AuditFinding(
                severity="WARNING",
                category="Time Concentration",
                message=(
                    f"{max_month_pct * 100:.1f}% of profit from a single month. "
                    "Performance not well-distributed over time."
                ),
                evidence={"peak_month": str(monthly.idxmax()), "pct": float(max_month_pct)},
            ))

    def _check_sharpe_vs_drawdown(self, r: BacktestResult, rep: AuditReport) -> None:
        # Calmar inversé — return vs max DD
        if r.max_drawdown_pct > 15:
            rep.findings.append(AuditFinding(
                severity="CRITICAL",
                category="Risk",
                message=f"Max DD {r.max_drawdown_pct:.2f}% — exceeds FTMO threshold",
            ))
        elif r.max_drawdown_pct > 10:
            rep.findings.append(AuditFinding(
                severity="WARNING",
                category="Risk",
                message=f"Max DD {r.max_drawdown_pct:.2f}% — close to FTMO limit",
            ))
        if r.max_daily_drawdown_pct > 5:
            rep.findings.append(AuditFinding(
                severity="CRITICAL",
                category="Risk",
                message=f"Max daily DD {r.max_daily_drawdown_pct:.2f}% breaches FTMO 5%",
            ))

    def _check_breakdowns(self, r: BacktestResult, rep: AuditReport) -> None:
        # Si tout le PnL vient d'UN régime ou UNE session → fragilité
        if r.performance_by_regime:
            pnls = [v["pnl_usd"] for v in r.performance_by_regime.values()]
            total_abs = sum(abs(p) for p in pnls)
            if total_abs > 0:
                max_pct = max(abs(p) for p in pnls) / total_abs
                if max_pct > 0.80:
                    rep.findings.append(AuditFinding(
                        severity="WARNING",
                        category="Concentration",
                        message=(
                            f"{max_pct * 100:.1f}% of PnL tied to a single regime — "
                            "fragile to regime changes"
                        ),
                    ))

    def _check_compliance(self, r: BacktestResult, rep: AuditReport) -> None:
        if not r.ftmo_compliant:
            rep.findings.append(AuditFinding(
                severity="CRITICAL",
                category="Compliance",
                message="Backtest VIOLATES FTMO rules — not tradeable there",
            ))
        if not r.the5ers_compliant:
            rep.findings.append(AuditFinding(
                severity="WARNING",
                category="Compliance",
                message="Backtest violates The 5ers conservative rules (4% daily)",
            ))

    def _check_walk_forward(self, wf: WalkForwardReport, rep: AuditReport) -> None:
        s = wf.summary()
        if s["n_folds"] == 0:
            rep.findings.append(AuditFinding(
                severity="WARNING",
                category="Walk-Forward",
                message="No walk-forward folds completed",
            ))
            return
        verdict = s["verdict"]
        robustness = s["robustness_ratio_return"]
        if verdict == "OVERFIT_SUSPECT":
            rep.findings.append(AuditFinding(
                severity="CRITICAL",
                category="Walk-Forward",
                message=(
                    f"Walk-forward robustness ratio {robustness:.2f} — "
                    f"strong overfitting signal. OOS fails to confirm IS."
                ),
                evidence=s,
            ))
        elif verdict == "MARGINAL":
            rep.findings.append(AuditFinding(
                severity="WARNING",
                category="Walk-Forward",
                message=f"Marginal robustness ({robustness:.2f}) — improve or reduce params",
                evidence=s,
            ))
        else:
            rep.findings.append(AuditFinding(
                severity="INFO",
                category="Walk-Forward",
                message=f"Walk-forward verdict: {verdict} (robustness={robustness:.2f})",
                evidence=s,
            ))

    def _finalize_verdict(self, rep: AuditReport) -> None:
        if rep.critical_count > 0:
            rep.verdict = "REJECTED"
        elif rep.warning_count >= 3:
            rep.verdict = "WARNING"
        else:
            rep.verdict = "PASSED"
