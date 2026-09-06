"""
modules/inference.py — PubCast Inference Manager
══════════════════════════════════════════════════

Thin coordination layer. All actual LLM calls go through LLMOrchestrator.
InferenceManager is kept for API compatibility with main.py and the /health
endpoint — it does not talk to Ollama or GGUF directly.

API contract (what main.py calls):
    inference.generate_text(
        prompt         = "...",
        temperature    = 0.7,
        max_tokens     = 256,
        requested_route = "studio" | "architect" | "architect_then_studio" | "auto",
        task_type      = "",       # optional hint for routing
        user_facing    = None,     # bool | None
        allow_fallback = None,     # bool | None
    )

Legacy callers may use:
    inference.generate_text(prompt="...", role="studio")

Both signatures are supported without error.

Rear View Foresight LLC — Feic Mo Chroí — 2026
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Dict, Optional

import httpx

from .appconfig import settings
from .llm_orchestrator import ContextPacket, get_orchestrator

logger = logging.getLogger("pubcast.inference")

# ── Route normalisation ────────────────────────────────────────────────────────

_ROUTE_ALIASES: Dict[str, str] = {
    "auto":                  "studio",
    "studio":                "studio",
    "architect":             "architect",
    "architect_then_studio": "architect_then_studio",
    "dual":                  "architect_then_studio",
    "two_pass":              "architect_then_studio",
    "plan":                  "architect",
    "express":               "studio",
    "character":             "studio",
    "":                      "studio",
}

# task_type hints that should bump to architect_then_studio
_COMPLEX_TASK_TYPES = {
    "analysis", "planning", "structured_data", "troubleshoot",
    "explain", "recommend", "escalation",
}


def _resolve_route(
    requested_route: Optional[str],
    role: Optional[str],
    task_type: Optional[str],
    allow_fallback: Optional[bool],
) -> str:
    """
    Merge the old `role` param and new `requested_route` param into a
    canonical orchestrator role string.

    Priority: requested_route > role > task_type hint > default (studio).
    """
    # Start from whichever caller provided
    raw = (requested_route or role or "").strip().lower()
    canonical = _ROUTE_ALIASES.get(raw, "studio")
    route_was_explicit = bool((requested_route or role or "").strip())

    # Task-type bump: only when no explicit route was given.
    # An explicit route ("studio", "architect", etc.) always wins —
    # task_type is a hint for the ambiguous/auto case only.
    if not route_was_explicit and (task_type or "").lower() in _COMPLEX_TASK_TYPES:
        canonical = "architect_then_studio"

    return canonical


# ═══════════════════════════════════════════════════════════════════════════════
# InferenceManager
# ═══════════════════════════════════════════════════════════════════════════════

class InferenceManager:
    """
    Thin facade over LLMOrchestrator. Preserves the interface that main.py
    and existing REST endpoints expect while adding the new param surface.
    """

    def __init__(self) -> None:
        self._orch = get_orchestrator()
        # _worker_alive is read by main.py boot log — set after startup()
        self._worker_alive: bool = False

    async def startup(self) -> None:
        await self._orch.startup()
        self._worker_alive = self._orch._studio_ok

    def status(self) -> Dict[str, Any]:
        """
        Report inference state.

        Must remain callable even when the orchestrator was never constructed
        (e.g. a config-validation failure, or a bare instance in tests) —
        this is a diagnostics surface, so a partially-initialised manager
        should report that fact rather than raising AttributeError.
        """
        orch = getattr(self, "_orch", None)
        s: Dict[str, Any] = {}
        if orch is not None:
            try:
                s = orch.status() or {}
            except Exception as exc:  # noqa: BLE001 — diagnostics must not raise
                s = {"orchestrator_error": str(exc)}

        cfg = getattr(self, "_config", None) or {}
        perf = s.get("performance") if isinstance(s.get("performance"), dict) else {}

        # Re-validate the configured AI config path on every status call.
        # PUBCAST_AI_CONFIG_PATH is env-controlled, so it can change after
        # construction — and a path outside the repo root is a traversal risk
        # that must be reported rather than silently ignored.
        last_error = getattr(self, "_last_error", "") or ""
        try:
            from modules.ai_runtime import resolve_ai_runtime_path
            resolve_ai_runtime_path(getattr(self, "_base_dir", None))
        except Exception as exc:  # noqa: BLE001 — report, never raise from status
            last_error = str(exc)

        # Surface profile / available_profiles / last_error at the top level.
        # The orchestrator nests profile under "performance"; callers and the
        # smoke suite expect it flat.
        profile = perf.get("profile")
        if profile is None:
            profile = (cfg.get("performance") or {}).get("profile") if isinstance(cfg, dict) else None

        available_profiles = s.get("available_profiles")
        if available_profiles is None:
            perf_cfg = (cfg.get("performance_profiles") or {}) if isinstance(cfg, dict) else {}
            available_profiles = sorted(perf_cfg.keys()) if isinstance(perf_cfg, dict) else []

        return {
            "worker_alive": getattr(self, "_worker_alive", False),
            **s,
            "profile": profile,
            "available_profiles": available_profiles,
            "last_error": last_error,
        }

    async def generate_text(
        self,
        prompt: str,
        *,
        # ── New API (main.py v5.0) ────────────────────────────────────────────
        requested_route: Optional[str] = None,
        task_type: Optional[str] = None,
        user_facing: Optional[bool] = None,
        allow_fallback: Optional[bool] = None,
        # ── Legacy API (old callers) ──────────────────────────────────────────
        role: Optional[str] = None,
        # ── Shared ───────────────────────────────────────────────────────────
        temperature: float = 0.7,
        max_tokens: int = 256,
        context: Optional[ContextPacket] = None,
    ) -> Dict[str, Any]:
        """
        Generate text. Returns dict with:
            text, model, provider, role_used, role_requested,
            latency_ms, fallback_occurred, fallback_reason,
            architect_draft, error

        Accepts both old `role=` and new `requested_route=` signatures.
        """
        route = _resolve_route(
            requested_route=requested_route,
            role=role,
            task_type=task_type,
            allow_fallback=allow_fallback,
        )

        result = await self._orch.generate(
            prompt,
            role=route,
            context=context,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return {
            "text":              result.text,
            "model":             result.model,
            "provider":          result.mind_used,
            "role_used":         result.role_used,
            "role_requested":    result.role_requested,
            "latency_ms":        result.latency_ms,
            "fallback_occurred": result.fallback_occurred,
            "fallback_reason":   result.fallback_reason,
            "architect_draft":   result.architect_draft,
            "error":             result.error,
            # surfaced so callers know whether fallback was allowed
            "user_facing":       bool(user_facing) if user_facing is not None else True,
        }

    async def synthesize_speech(self, text: str, voice: str = "default") -> Dict[str, Any]:
        cleaned = (text or "").strip()
        if not cleaned:
            return {"status": "error", "error": "text is empty", "voice": voice}

        base = f"http://{settings.larynx_host}:{settings.larynx_port}"
        endpoints = [
            f"{base}/api/tts",
            f"{base}/api/tts?format=wav",
        ]
        payload = {
            "text":    cleaned,
            "voice":   voice,
            "speaker": voice,
            "model":   settings.piper_model,
        }

        last_error = ""
        for endpoint in endpoints:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(endpoint, json=payload)
                    response.raise_for_status()

                    content_type = response.headers.get("content-type", "").lower()
                    if "audio/" in content_type:
                        audio_bytes = response.content
                        return {
                            "status":       "ok",
                            "voice":        voice,
                            "model":        settings.piper_model,
                            "endpoint":     endpoint,
                            "content_type": content_type,
                            "size_bytes":   len(audio_bytes),
                            "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                        }

                    data: Dict[str, Any]
                    try:
                        data = response.json()
                    except Exception:
                        data = {"raw": response.text}

                    return {
                        "status":            "ok",
                        "voice":             voice,
                        "model":             settings.piper_model,
                        "endpoint":          endpoint,
                        "provider_response": data,
                    }
            except Exception as exc:
                last_error = str(exc)

        return {
            "status": "tts_unavailable",
            "voice":  voice,
            "model":  settings.piper_model,
            "host":   settings.larynx_host,
            "port":   settings.larynx_port,
            "error":  last_error or "Larynx/Piper endpoint did not respond",
        }


__all__ = ["InferenceManager"]
