"""
Confluence Filter — score de confluence multi-facteurs.

Chaque facteur vaut 1 point. Un setup est "full optimiste" si score >= 5/7.
Facteurs évalués :
1. Multi-TF alignment (W+D+H4 bias identique)
2. SMT divergence présente
3. Liquidity sweep récent (< 10 bars)
4. Cross-asset alignment (DXY/VIX/SPX favorables)
5. Killzone active (London/NY AM/NY PM)
6. Volume spike (> 1.5x moyenne 20)
7. Order Block frais (< 20 bars depuis creation)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from enum import Enum


class ConfluenceScore(int, Enum):
    SKIP = 0
    WEAK = 1
    AVERAGE = 2
    GOOD = 3
    STRONG = 4
    ELITE = 5
    GODLIKE = 6
    DIVINE = 7


@dataclass
class ConfluenceResult:
    """Résultat du filtre de confluence."""
    total_score: int
    max_score: int
    pass_filter: bool
    details: Dict[str, bool] = field(default_factory=dict)
    reason: str = ""

    @property
    def grade(self) -> ConfluenceScore:
        return ConfluenceScore(min(self.total_score, 7))

    @property
    def percentage(self) -> float:
        return self.total_score / max(self.max_score, 1)


class ConfluenceFilter:
    """Filtre multi-facteurs de confluence."""

    def __init__(
        self,
        min_score: int = 3,
        require_smt: bool = True,
        require_multi_tf: bool = True,
        require_killzone: bool = True,
    ):
        self.min_score = min_score
        self.require_smt = require_smt
        self.require_multi_tf = require_multi_tf
        self.require_killzone = require_killzone

    def evaluate(
        self,
        multi_tf_aligned: bool = False,
        smt_divergence: bool = False,
        liquidity_sweep_recent: bool = False,
        cross_asset_aligned: bool = False,
        in_killzone: bool = False,
        volume_spike: bool = False,
        fresh_order_block: bool = False,
    ) -> ConfluenceResult:
        """
        Évalue la confluence.
        Chaque True = +1 point.
        """
        details = {
            "multi_tf_aligned": multi_tf_aligned,
            "smt_divergence": smt_divergence,
            "liquidity_sweep_recent": liquidity_sweep_recent,
            "cross_asset_aligned": cross_asset_aligned,
            "in_killzone": in_killzone,
            "volume_spike": volume_spike,
            "fresh_order_block": fresh_order_block,
        }
        score = sum(int(v) for v in details.values())
        max_score = len(details)

        # Hard requirements
        reasons = []
        if self.require_multi_tf and not multi_tf_aligned:
            return ConfluenceResult(
                total_score=score,
                max_score=max_score,
                pass_filter=False,
                details=details,
                reason="Multi-TF not aligned (required)",
            )
        if self.require_smt and not smt_divergence:
            return ConfluenceResult(
                total_score=score,
                max_score=max_score,
                pass_filter=False,
                details=details,
                reason="SMT divergence absent (required)",
            )
        if self.require_killzone and not in_killzone:
            return ConfluenceResult(
                total_score=score,
                max_score=max_score,
                pass_filter=False,
                details=details,
                reason="Not in killzone (required)",
            )

        # Min score check
        if score < self.min_score:
            return ConfluenceResult(
                total_score=score,
                max_score=max_score,
                pass_filter=False,
                details=details,
                reason=f"Score {score} < min {self.min_score}",
            )

        return ConfluenceResult(
            total_score=score,
            max_score=max_score,
            pass_filter=True,
            details=details,
            reason=f"Confluence {score}/{max_score} ✓",
        )

    def evaluate_from_signal(self, enhanced_signal: Any) -> ConfluenceResult:
        """
        Évalue à partir d'un EnhancedSignal (CyborgEnhancer output).
        Mapping soft : on inspecte les attributs disponibles.
        """
        # Multi-TF aligned si multi_tf_score >= 0.55
        multi_tf = False
        try:
            multi_tf = bool(getattr(enhanced_signal, "multi_tf_aligned", False))
            if not multi_tf:
                mtf_score = getattr(enhanced_signal, "multi_tf_score", 0)
                multi_tf = mtf_score >= 0.55
        except Exception:
            pass

        # SMT from signal
        smt = False
        try:
            smt = bool(getattr(enhanced_signal, "smt_detected", False))
            if not smt:
                base = getattr(enhanced_signal, "base", enhanced_signal)
                smt = bool(getattr(base, "smt_divergence", False))
        except Exception:
            pass

        # Liquidity sweep
        liq = False
        try:
            base = getattr(enhanced_signal, "base", enhanced_signal)
            liq = bool(getattr(base, "liquidity_swept", False))
        except Exception:
            pass

        # Cross-asset
        cross = False
        try:
            cross_obj = getattr(enhanced_signal, "cross_asset", None)
            if cross_obj:
                cross = getattr(cross_obj, "score", 0) >= 0.6
        except Exception:
            pass

        # Killzone
        kz = False
        try:
            base = getattr(enhanced_signal, "base", enhanced_signal)
            kz_name = getattr(base, "killzone", "none")
            kz = kz_name not in (None, "", "none")
        except Exception:
            pass

        # Volume spike
        vol = False
        try:
            base = getattr(enhanced_signal, "base", enhanced_signal)
            vr = getattr(base, "volume_ratio", 1.0)
            vol = vr >= 1.5
        except Exception:
            pass

        # Fresh OB
        fresh = False
        try:
            base = getattr(enhanced_signal, "base", enhanced_signal)
            age = getattr(base, "fvg_age_bars", 100)
            fresh = age <= 20
        except Exception:
            pass

        return self.evaluate(
            multi_tf_aligned=multi_tf,
            smt_divergence=smt,
            liquidity_sweep_recent=liq,
            cross_asset_aligned=cross,
            in_killzone=kz,
            volume_spike=vol,
            fresh_order_block=fresh,
        )
