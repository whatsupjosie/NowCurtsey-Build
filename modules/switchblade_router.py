from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

AUTO_ROLES = {"auto", "switchblade", "router"}

CREATIVE_TERMS = {
    "act", "character", "creative", "dialog", "dialogue", "improv", "line",
    "monologue", "perform", "poem", "scene", "script", "story", "voice",
    "write",
}

TECHNICAL_TERMS = {
    "analyze", "benchmark", "calculate", "compute", "debug", "diagnose",
    "equation", "error", "math", "measure", "number", "percent", "ratio",
    "status", "technical", "traceback", "validate", "verify",
}

SUPPORT_TERMS = {
    "help", "stuck", "menu", "where", "how", "fix", "issue", "problem",
    "explain", "what happened", "why",
}


@dataclass(frozen=True)
class SwitchbladeDecision:
    requested_role: str
    role: str
    slot: str
    mode: str
    reason: str
    confidence: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "requested_role": self.requested_role,
            "role": self.role,
            "slot": self.slot,
            "mode": self.mode,
            "reason": self.reason,
            "confidence": self.confidence,
        }


def _score(text: str, terms: set[str]) -> int:
    lowered = text.lower()
    return sum(1 for term in terms if term in lowered)


def decide_switchblade_role(requested_role: str, message: str) -> SwitchbladeDecision:
    requested = (requested_role or "pub_partner_alex").strip() or "pub_partner_alex"
    if requested not in AUTO_ROLES:
        slot = {
            "pub_partner_alex": "alex",
            "ministral": "alex",
            "alex_model": "alex",
            "creative": "alex",
            "dialogue": "alex",
            "jeremy": "jeremy",
            "gemma": "jeremy",
            "background_math": "background_math",
            "math": "background_math",
            "e2b": "background_math",
            "background_process": "background_math",
        }.get(requested, "alex")
        return SwitchbladeDecision(requested, requested, slot, "manual", "user_selected_role", 1.0)

    creative = _score(message, CREATIVE_TERMS)
    technical = _score(message, TECHNICAL_TERMS)
    support = _score(message, SUPPORT_TERMS)
    if technical > max(creative, support):
        return SwitchbladeDecision(requested, "background_math", "background_math", "auto", "technical_math_terms", min(0.95, 0.55 + technical * 0.12))
    if support > max(creative, technical):
        return SwitchbladeDecision(requested, "jeremy", "jeremy", "auto", "support_terms", min(0.9, 0.52 + support * 0.12))
    if creative > 0:
        return SwitchbladeDecision(requested, "pub_partner_alex", "alex", "auto", "creative_dialogue_terms", min(0.92, 0.55 + creative * 0.12))
    return SwitchbladeDecision(requested, "pub_partner_alex", "alex", "auto", "default_conversation", 0.5)