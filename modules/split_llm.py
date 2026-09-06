"""
modules/split_llm.py — Compatibility Shim
══════════════════════════════════════════

Thin wrapper around LLMOrchestrator so any code that calls split_llm.route()
or split_llm.status() continues to work without modification.

Do not add logic here. This is a translation layer only.
All routing decisions, circuit breaking, fallback, and telemetry live in
modules/llm_orchestrator.py.

Rear View Foresight LLC — Feic Mo Chroí — 2026
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .llm_orchestrator import (
    ContextPacket,
    LLMOrchestrator,
    OrchestratorResult,
    get_orchestrator,
    VALID_ROLES,
)

logger = logging.getLogger("pubcast.split_llm")


# ── SplitResult — back-compat return type ────────────────────────────────────

@dataclass
class SplitResult:
    """
    Legacy return type. Populated from OrchestratorResult so existing callers
    don't need to change.
    """
    text: str
    role: str
    model: str
    provider: str
    elapsed_ms: float = 0.0
    architect_draft: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return bool(self.text) and self.error is None

    @classmethod
    def from_orchestrator(cls, r: OrchestratorResult) -> "SplitResult":
        provider = "ollama"
        if r.mind_used == "architect":
            provider = "gguf"
        elif r.mind_used == "architect_then_studio":
            provider = "gguf→ollama"
        return cls(
            text=r.text,
            role=r.role_used,
            model=r.model,
            provider=provider,
            elapsed_ms=r.latency_ms,
            architect_draft=r.architect_draft,
            error=r.error,
        )


# ── Public shim API ───────────────────────────────────────────────────────────

async def route(
    prompt: str,
    role: str = "studio",
    system: str = "",
    model: str = "",
    temperature: float = 0.85,
    max_tokens: int = 512,
    history: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any,
) -> SplitResult:
    """
    Back-compat entry point. Builds a ContextPacket from legacy args and
    delegates to the orchestrator.
    """
    ctx = ContextPacket(
        system_prompt=system,
        history=[
            {"role": "user" if not str(h.get("user_id", "")).startswith("bot-") else "assistant",
             "content": str(h.get("text", ""))}
            for h in (history or [])
            if h.get("text")
        ],
    )

    orch = get_orchestrator()
    result = await orch.generate(
        prompt,
        role=role,
        context=ctx,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return SplitResult.from_orchestrator(result)


def status() -> Dict[str, Any]:
    """Back-compat status. Returns orchestrator telemetry."""
    return get_orchestrator().status()


# Re-export so existing imports of _ARCHITECT_AVAILABLE still resolve
try:
    from .llm_orchestrator import _arch_available as _ARCHITECT_AVAILABLE
except ImportError:
    _ARCHITECT_AVAILABLE = False


__all__ = [
    "route",
    "status",
    "SplitResult",
    "VALID_ROLES",
    "_ARCHITECT_AVAILABLE",
]
