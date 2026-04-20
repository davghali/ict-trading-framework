"""
CLAUDE AI SIGNAL AUDITOR — 2e niveau de validation par IA.

Pour chaque signal généré :
1. On envoie un contexte structuré à Claude API
2. Claude répond avec : grade (S/A+/A/B/Skip) + raisonnement
3. On compare avec le grade cyborg
4. Si AI désaccord fort → filtre le signal

Usage :
    auditor = ClaudeSignalAuditor()           # requires ANTHROPIC_API_KEY
    review = auditor.audit(signal, context)
    if review.recommended_action == "take":
        # signal validé par IA
"""
from __future__ import annotations

import os
import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any

from src.utils.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class AuditResult:
    timestamp: str
    signal_summary: str
    ai_grade: str                    # "S" | "A+" | "A" | "B" | "Skip"
    recommended_action: str          # "take" | "skip" | "review"
    confidence: float                # 0-1
    reasoning: str
    risks_flagged: list = None
    raw_response: str = ""


PROMPT_TEMPLATE = """You are an elite institutional trader reviewing a trade signal.

SIGNAL CONTEXT:
{context}

Evaluate this setup on ICT / Smart Money Concepts principles. Consider:
- Is the multi-TF alignment solid?
- Is the cross-asset confluence coherent?
- Is the entry location optimal (FVG CE, OB, liquidity sweep)?
- Is RR asymmetric favorably?
- Are there latent risks (news, correlation, regime mismatch)?

Respond ONLY in strict JSON:
{{
  "grade": "S" or "A+" or "A" or "B" or "Skip",
  "action": "take" or "skip" or "review",
  "confidence": 0.0 to 1.0,
  "reasoning": "2-3 sentences max",
  "risks": ["risk 1", "risk 2"]
}}"""


class ClaudeSignalAuditor:

    def __init__(self, api_key: str = None, model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model
        self.enabled = bool(self.api_key)
        if not self.enabled:
            log.info("Claude API key not configured — AI auditor in passthrough mode")

    # ------------------------------------------------------------------
    def audit(self, signal, enhanced=None) -> AuditResult:
        """
        Audit un signal via Claude API.
        Si API non configurée, retourne un verdict "take" par défaut (pas-filter).
        """
        if not self.enabled:
            return AuditResult(
                timestamp=datetime.utcnow().isoformat(),
                signal_summary=f"{signal.symbol} {signal.side}",
                ai_grade=enhanced.cyborg_grade if enhanced else "B",
                recommended_action="take",
                confidence=0.5,
                reasoning="AI auditor disabled (no API key)",
                risks_flagged=[],
            )

        context = self._build_context(signal, enhanced)
        prompt = PROMPT_TEMPLATE.format(context=context)

        try:
            response = self._call_claude(prompt)
            parsed = self._parse_response(response)
            return AuditResult(
                timestamp=datetime.utcnow().isoformat(),
                signal_summary=f"{signal.symbol} {signal.side}",
                ai_grade=parsed.get("grade", "B"),
                recommended_action=parsed.get("action", "review"),
                confidence=float(parsed.get("confidence", 0.5)),
                reasoning=parsed.get("reasoning", ""),
                risks_flagged=parsed.get("risks", []),
                raw_response=response,
            )
        except Exception as e:
            log.warning(f"Claude audit failed: {e}")
            return AuditResult(
                timestamp=datetime.utcnow().isoformat(),
                signal_summary=f"{signal.symbol} {signal.side}",
                ai_grade="B",
                recommended_action="review",
                confidence=0.3,
                reasoning=f"API error: {e}",
                risks_flagged=["API unavailable"],
            )

    # ------------------------------------------------------------------
    def _build_context(self, signal, enhanced) -> str:
        ctx = (
            f"Asset: {signal.symbol}\n"
            f"Timeframe: {signal.ltf}\n"
            f"Side: {signal.side.upper()}\n"
            f"Entry: {signal.entry:.4f}\n"
            f"Stop Loss: {signal.stop_loss:.4f}\n"
            f"Take Profit: {signal.take_profit_1:.4f}\n"
            f"Risk:Reward: {signal.risk_reward:.2f}\n"
            f"ML P(win): {signal.ml_prob_win}\n"
            f"Killzone: {signal.killzone}\n"
            f"Tier (cyborg): {signal.tier}\n"
            f"FVG age (bars): {signal.fvg_age_bars}\n"
            f"FVG size ATR: {signal.fvg_size_atr}\n"
            f"Current price: {signal.current_price}\n"
        )
        if enhanced:
            ctx += f"\nEnhanced grade: {enhanced.cyborg_grade}\n"
            ctx += f"Final probability: {enhanced.final_probability:.0%}\n"
            if enhanced.cross_asset:
                ctx += f"Cross-asset score: {enhanced.cross_asset.score:.2f}\n"
                ctx += f"Confirmations: {', '.join(enhanced.cross_asset.confirmations[:3])}\n"
            if enhanced.multi_tf_details:
                ctx += f"Multi-TF: {', '.join(enhanced.multi_tf_details)}\n"
            if enhanced.exit_plan:
                ctx += f"Regime: {enhanced.exit_plan.regime}\n"
        return ctx

    def _call_claude(self, prompt: str) -> str:
        """Appel minimaliste à l'API Claude."""
        url = "https://api.anthropic.com/v1/messages"
        payload = {
            "model": self.model,
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            response = json.loads(resp.read().decode())
        return response["content"][0]["text"]

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """Parse le JSON de la réponse Claude (robust aux formatings)."""
        # Extract JSON block
        start = response.find("{")
        end = response.rfind("}") + 1
        if start < 0 or end <= start:
            return {}
        try:
            return json.loads(response[start:end])
        except Exception:
            return {}
