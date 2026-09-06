"""
modules/llm_orchestrator.py — PubCast Dual-Mind Orchestration Layer
==============================================================================

Single authority for all LLM routing decisions. Both minds (Studio and
Architect) are coordinated here — shared context, time budgets, circuit
breaker, concurrency cap, and unified telemetry.

Callers never talk to Studio or Architect directly. They call:

    result = await orchestrator.generate(prompt, role="studio", context=ctx)

And get back an OrchestratorResult with the text, which mind was used,
latency, and whether a fallback occurred.

Architecture
────────────
  Studio  — Ollama local HTTP. Always available when Ollama is running.
             Fast. Character-voice system prompt. Used for most responses.

  Architect — GGUF via llama_cpp. Optional. One concurrent call at a time
              (Zoidberg GTX 960M cannot handle simultaneous GGUF inference).
              Planning-format system prompt. Used only when role demands it.

  Circuit Breaker — after BREAKER_THRESHOLD consecutive Architect failures,
                    Architect is disabled for BREAKER_COOLDOWN_S seconds.
                    State is logged visibly on open and close.

  Time Budget — each role has a max wall-clock budget. If Architect exceeds
                its budget, Studio handles the request instead. The caller
                never blocks past ARCHITECT_TIMEOUT_S.

  Shared Context Packet — both minds receive the same ContextPacket, which
                          carries room history, character state, and mood.
                          Architect's planning output is injected into Studio's
                          prompt in a structured way Studio can actually use.

Prompt Discipline
─────────────────
  Architect system prompt:  structured planning format — explicit sections,
                            bullet points, concrete directives. Architect is
                            never asked to speak as a character.

  Studio system prompt:     character voice prompt. Studio is never asked to
                            plan or reason structurally.

  Handoff format:           Architect output is wrapped in a structured block
                            that Studio receives as internal stage direction,
                            not as conversation history.

Environment Variables
─────────────────────
  OLLAMA_HOST               Ollama server (default: http://localhost:11434)
  OLLAMA_MODEL / STUDIO_MODEL   Studio model tag (default: ministral-pubcast:3b)
  PUBCAST_ARCHITECT_MODEL   Path to Architect GGUF file
  PUBCAST_ARCHITECT_CTX     Context window (default: 2048)
  PUBCAST_ARCHITECT_THREADS CPU threads (default: 4)
  ARCHITECT_TIMEOUT_S       Max seconds to wait for Architect (default: 12)
  BREAKER_THRESHOLD         Failures before breaker opens (default: 3)
  BREAKER_COOLDOWN_S        Seconds breaker stays open (default: 60)

Rear View Foresight LLC — Feic Mo Chroí — 2026
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

try:
    from .performance_manager import get_performance_manager
except Exception:  # pragma: no cover - optional during partial builds
    get_performance_manager = None  # type: ignore

try:
    from .appconfig import settings
except Exception:  # pragma: no cover - optional during partial builds
    settings = None  # type: ignore

logger = logging.getLogger("pubcast.orchestrator")

# ── Environment —

_OLLAMA_HOST    = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
_STUDIO_MODEL   = os.getenv("STUDIO_MODEL", os.getenv("OLLAMA_MODEL", getattr(settings, "studio_model", "ministral-pubcast:3b")))
_ARCH_MODEL     = os.getenv("ARCHITECT_MODEL", getattr(settings, "architect_model", "gemma4-compute-q5:e2b"))
_OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", getattr(settings, "studio_keepalive", "10m"))
_ARCH_KEEP_ALIVE = os.getenv("ARCHITECT_KEEPALIVE", getattr(settings, "architect_keepalive", "0"))
_ARCH_PATH      = os.getenv("PUBCAST_ARCHITECT_MODEL", "")
_ARCH_CTX       = int(os.getenv("PUBCAST_ARCHITECT_CTX", os.getenv("ARCHITECT_CTX", str(getattr(settings, "architect_ctx", 2048)))))
_ARCH_THREADS   = int(os.getenv("PUBCAST_ARCHITECT_THREADS", "4"))
_ARCH_TIMEOUT   = float(os.getenv("ARCHITECT_TIMEOUT_S", "12"))
_BREAKER_THRESH = int(os.getenv("BREAKER_THRESHOLD", "3"))
_BREAKER_COOL   = float(os.getenv("BREAKER_COOLDOWN_S", "60"))

VALID_ROLES = {"studio", "architect", "architect_then_studio"}


# —
# Data types
# —

@dataclass
class ContextPacket:
    """
    Shared context passed to both minds. Single source of truth for what
    both Studio and Architect know about the current room state.
    """
    room_id: str = ""
    character_id: str = ""
    character_name: str = ""
    system_prompt: str = ""          # Character voice prompt (Studio)
    mood_state: str = "neutral"
    arousal: float = 0.5             # 0.0–1.0
    history: List[Dict[str, Any]] = field(default_factory=list)  # [{role, content}]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def studio_system(self) -> str:
        """Character-voice system prompt for Studio."""
        if self.system_prompt:
            return self.system_prompt
        if self.character_name:
            return f"You are {self.character_name}. Stay in character."
        return ""

    def architect_system(self) -> str:
        """Structured planning system prompt for Architect. Never asks it to speak as character."""
        base = (
            "You are a production planning assistant for a live virtual broadcast. "
            "Your output is internal stage direction — never spoken aloud. "
            "Analyze the situation and respond in this exact format:\n\n"
            "SITUATION: [one sentence — what is happening in the room right now]\n"
            "CHARACTER_INTENT: [one sentence — what this character most likely wants to accomplish]\n"
            "KEY_POINTS:\n- [concrete point the response should address]\n"
            "- [concrete point the response should address]\n"
            "TONE: [one word — e.g. warm / dry / urgent / theatrical / grounding]\n"
            "AVOID: [one specific thing the response should not do]\n\n"
            "Be brief. Be concrete. No prose."
        )
        if self.character_name:
            base = base.replace(
                "this character",
                f"{self.character_name}",
            )
        if self.mood_state and self.mood_state != "neutral":
            base += f"\n\nCurrent mood state: {self.mood_state}. Arousal: {self.arousal:.1f}/1.0."
        return base

    def history_as_messages(self) -> List[Dict[str, str]]:
        """Convert history to clean [{role, content}] for Ollama /api/chat."""
        messages = []
        for entry in self.history:
            role = entry.get("role", "")
            content = str(entry.get("content", entry.get("text", ""))).strip()
            if not content:
                continue
            # Normalise roles
            if role not in ("user", "assistant", "system"):
                uid = str(entry.get("user_id", entry.get("sender_id", "")))
                role = "assistant" if (uid.startswith("bot-") or uid.startswith("agent:")) else "user"
            messages.append({"role": role, "content": content})
        return messages


@dataclass
class OrchestratorResult:
    """
    Return value from orchestrator.generate(). Always populated — never raises.
    """
    text: str
    role_used: str              # actual role executed (may differ if fallback occurred)
    role_requested: str
    mind_used: str              # "studio" | "architect" | "architect_then_studio"
    model: str
    latency_ms: float
    fallback_occurred: bool = False
    fallback_reason: str = ""
    architect_draft: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return bool(self.text) and self.error is None


# —
# Circuit breaker
# —

class CircuitBreaker:
    """
    Three-state breaker: CLOSED (normal) → OPEN (disabled) → CLOSED (recovered).
    Open/close events are logged visibly at WARNING level.
    """

    def __init__(self, name: str, threshold: int, cooldown_s: float) -> None:
        self.name       = name
        self.threshold  = threshold
        self.cooldown_s = cooldown_s
        self._failures  = 0
        self._opened_at: Optional[float] = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if (time.monotonic() - self._opened_at) >= self.cooldown_s:
            self._close()
            return False
        return True

    def record_success(self) -> None:
        if self._failures > 0:
            self._failures = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold and self._opened_at is None:
            self._open()

    def _open(self) -> None:
        self._opened_at = time.monotonic()
        logger.warning(
            "⚡ CIRCUIT BREAKER OPEN — %s disabled after %d consecutive failures. "
            "Cooldown: %.0fs. Architect path will fall back to Studio.",
            self.name, self._failures, self.cooldown_s,
        )

    def _close(self) -> None:
        self._failures  = 0
        self._opened_at = None
        logger.warning(
            "✅ CIRCUIT BREAKER CLOSED — %s re-enabled after cooldown. "
            "Architect path restored.",
            self.name,
        )

    def status(self) -> Dict[str, Any]:
        remaining = 0.0
        if self._opened_at is not None:
            remaining = max(0.0, self.cooldown_s - (time.monotonic() - self._opened_at))
        return {
            "open":             self.is_open,
            "failures":         self._failures,
            "threshold":        self.threshold,
            "cooldown_s":       self.cooldown_s,
            "cooldown_remaining_s": round(remaining, 1),
        }


# —
# Architect loader (lazy, singleton)
# —

_arch_llm: Any = None
_arch_available: bool = False
_arch_load_attempted: bool = False


def _load_architect() -> bool:
    global _arch_llm, _arch_available, _arch_load_attempted
    if _arch_load_attempted:
        return _arch_available
    _arch_load_attempted = True

    if not _ARCH_PATH:
        _arch_available = bool(_ARCH_MODEL)
        logger.info(
            "Orchestrator: Architect using Ollama wrapper %s",
            _ARCH_MODEL or "not configured",
        )
        return _arch_available

    import os as _os
    if not _os.path.isfile(_ARCH_PATH):
        logger.warning(
            "Orchestrator: GGUF not found at %s — Architect disabled. "
            "Set PUBCAST_ARCHITECT_MODEL to the correct path.", _ARCH_PATH
        )
        return False

    try:
        from llama_cpp import Llama  # type: ignore
        _arch_llm = Llama(
            model_path=_ARCH_PATH,
            n_ctx=_ARCH_CTX,
            n_threads=_ARCH_THREADS,
            n_gpu_layers=int(os.getenv("PUBCAST_ARCHITECT_GPU_LAYERS", "0")),
            verbose=False,
        )
        _arch_available = True
        logger.info(
            "Orchestrator: Architect loaded — %s  ctx=%d  threads=%d",
            _ARCH_PATH, _ARCH_CTX, _ARCH_THREADS,
        )
    except ImportError:
        logger.info(
            "Orchestrator: llama-cpp-python not installed — Architect disabled. "
            "See requirements-architect.txt."
        )
    except Exception as exc:
        logger.warning("Orchestrator: failed to load Architect GGUF: %s", exc)

    return _arch_available


# —
# Orchestrator
# —

class LLMOrchestrator:
    """
    Single coordinated entry point for all LLM calls in PubCast.

    Usage:
        orch = LLMOrchestrator()
        await orch.startup()          # probes both minds, logs status
        result = await orch.generate(
            prompt="What do you think of the new guest?",
            role="architect_then_studio",
            context=ctx_packet,
        )
    """

    def __init__(self) -> None:
        self._studio_model = _STUDIO_MODEL
        self._architect_timeout_s = _ARCH_TIMEOUT
        self._architect_enabled = True
        self._architect_max_concurrency = 1
        self._breaker = CircuitBreaker("Architect", _BREAKER_THRESH, _BREAKER_COOL)
        self._arch_sem = asyncio.Semaphore(self._architect_max_concurrency)
        self._studio_ok   = False
        self._arch_ok     = False

        # Telemetry counters
        self._total_requests    = 0
        self._studio_calls      = 0
        self._arch_calls        = 0
        self._fallback_count    = 0
        self._last_error: Optional[str] = None
        self._latency_sum_ms    = 0.0
        self._perf = None
        self._active_profile = "medium"

        self._refresh_policy()

    def _refresh_policy(self) -> None:
        """
        Pull active runtime policy from PerformanceManager when available.
        Falls back to module env defaults if performance manager is absent.
        """
        if get_performance_manager is None:
            return
        perf = get_performance_manager()
        if perf is None:
            return

        self._perf = perf
        self._active_profile = str(getattr(perf, "active_profile", "medium"))

        studio_model = str(perf.get("studio_model", self._studio_model) or self._studio_model)
        architect_timeout = float(perf.get("architect_timeout_s", self._architect_timeout_s))
        architect_enabled = bool(perf.get("architect_enabled", True))
        max_concurrency = max(1, int(perf.get("architect_max_concurrency", 1)))
        breaker_threshold = max(1, int(perf.get("breaker_threshold", _BREAKER_THRESH)))
        breaker_cooldown = max(1.0, float(perf.get("breaker_cooldown_s", _BREAKER_COOL)))

        self._studio_model = studio_model
        self._architect_timeout_s = architect_timeout
        self._architect_enabled = architect_enabled

        if max_concurrency != self._architect_max_concurrency:
            self._architect_max_concurrency = max_concurrency
            self._arch_sem = asyncio.Semaphore(self._architect_max_concurrency)

        current_status = self._breaker.status()
        if (
            int(current_status.get("threshold", _BREAKER_THRESH)) != breaker_threshold
            or float(current_status.get("cooldown_s", _BREAKER_COOL)) != breaker_cooldown
        ):
            self._breaker = CircuitBreaker("Architect", breaker_threshold, breaker_cooldown)

    # ── Startup —

    async def startup(self) -> None:
        """Probe both minds. App boots regardless of Architect availability."""
        self._refresh_policy()
        # Studio probe
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(_OLLAMA_HOST)
                self._studio_ok = r.status_code == 200
        except Exception:
            self._studio_ok = False

        logger.info(
            "Orchestrator: Studio — %s  (model: %s)",
            "ONLINE" if self._studio_ok else "OFFLINE (Ollama not running)",
            self._studio_model,
        )

        # Architect probe — lazy load, don't block boot
        self._arch_ok = _load_architect()
        logger.info(
            "Orchestrator: Architect — %s  (%s)",
            "AVAILABLE" if self._arch_ok else "UNAVAILABLE",
            _ARCH_PATH or _ARCH_MODEL or "not configured",
        )

        # Warm up Studio in the background so cold model load never blocks PubCast boot.
        if self._studio_ok:
            asyncio.create_task(self._warm_studio())

    async def _warm_studio(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=float(os.getenv("OLLAMA_TIMEOUT", "180"))) as c:
                await c.post(
                    f"{_OLLAMA_HOST}/api/generate",
                    json={
                        "model": self._studio_model,
                        "prompt": "",
                        "stream": False,
                        "keep_alive": _OLLAMA_KEEP_ALIVE,
                        "options": {"num_ctx": 2048, "num_predict": 1},
                    },
                )
            logger.info("Orchestrator: Studio warmup complete")
        except Exception as exc:
            logger.info("Orchestrator: Studio warmup skipped/failed: %s", exc)

    # ── Main generate entry point —

    async def generate(
        self,
        prompt: str,
        *,
        role: str = "studio",
        context: Optional[ContextPacket] = None,
        temperature: float = 0.85,
        max_tokens: int = 160,
        studio_model: Optional[str] = None,
    ) -> OrchestratorResult:
        """
        Route a generation request. Never raises. Always returns OrchestratorResult.

        role:
            "studio"               — Studio only
            "architect"            — Architect only (falls back to Studio if unavailable)
            "architect_then_studio" — Two-pass: Architect plans, Studio voices
        """
        requested_role = role
        if role not in VALID_ROLES:
            logger.warning("Orchestrator: unknown role '%s' — defaulting to studio", role)
            role = "studio"
            requested_role = "studio"

        ctx = context or ContextPacket()
        self._total_requests += 1

        self._refresh_policy()

        if role in ("architect", "architect_then_studio") and not self._architect_enabled:
            result = await self._studio(
                prompt, ctx, temperature, max_tokens, studio_model=studio_model
            )
            result.role_requested = requested_role
            result.fallback_occurred = True
            result.fallback_reason = "profile_architect_disabled"
        elif role == "studio":
            result = await self._studio(
                prompt, ctx, temperature, max_tokens, studio_model=studio_model
            )

        elif role == "architect":
            result = await self._architect_with_fallback(
                prompt, ctx, temperature, max_tokens, role_requested=role, studio_model=studio_model
            )

        else:  # architect_then_studio
            result = await self._two_pass(prompt, ctx, temperature, max_tokens, studio_model=studio_model)

        # Telemetry
        self._latency_sum_ms += result.latency_ms
        if result.fallback_occurred:
            self._fallback_count += 1
        if result.error:
            self._last_error = result.error

        return result

    # ── Studio path —

    async def _studio(
        self,
        prompt: str,
        ctx: ContextPacket,
        temperature: float,
        max_tokens: int,
        *,
        extra_system: str = "",
        studio_model: Optional[str] = None,
    ) -> OrchestratorResult:
        self._studio_calls += 1
        t0 = time.monotonic()
        model_name = (studio_model or self._studio_model).strip() or self._studio_model

        messages: List[Dict[str, str]] = []
        sys_prompt = ctx.studio_system()
        if extra_system:
            sys_prompt = (sys_prompt + "\n\n" + extra_system).strip()
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages.extend(ctx.history_as_messages())
        messages.append({"role": "user", "content": prompt})

        try:
            async with httpx.AsyncClient(timeout=float(os.getenv("OLLAMA_TIMEOUT", "180"))) as c:
                r = await c.post(
                    f"{_OLLAMA_HOST}/api/chat",
                    json={
                        "model": model_name,
                        "messages": messages,
                        "stream": False,
                        "keep_alive": _OLLAMA_KEEP_ALIVE,
                        "options": {"temperature": temperature, "num_ctx": 2048, "num_predict": max_tokens},
                    },
                )
                r.raise_for_status()
                text = r.json().get("message", {}).get("content", "").strip()
                return OrchestratorResult(
                    text=text,
                    role_used="studio",
                    role_requested="studio",
                    mind_used="studio",
                    model=model_name,
                    latency_ms=round((time.monotonic() - t0) * 1000, 1),
                )
        except Exception as exc:
            err = str(exc)
            self._last_error = err
            logger.warning("Orchestrator: Studio error: %s", err)
            return OrchestratorResult(
                text="",
                role_used="studio",
                role_requested="studio",
                mind_used="studio",
                model=model_name,
                latency_ms=round((time.monotonic() - t0) * 1000, 1),
                error=err,
            )

    # ── Architect path —

    def _architect_sync(self, prompt: str, sys_prompt: str, temperature: float, max_tokens: int) -> str:
        """Synchronous GGUF call — runs in executor. Returns text or raises."""
        full = f"{sys_prompt}\n\n{prompt}" if sys_prompt else prompt
        result = _arch_llm(
            full,
            max_tokens=max_tokens,
            temperature=temperature,
            echo=False,
            stop=["</s>", "###", "\n\n\n"],
        )
        return result["choices"][0]["text"].strip()

    async def _architect_ollama(
        self,
        prompt: str,
        sys_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Architect call through the Gemma Ollama wrapper; unload after use."""
        messages = []
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages.append({"role": "user", "content": prompt})
        async with httpx.AsyncClient(timeout=self._architect_timeout_s) as c:
            response = await c.post(
                f"{_OLLAMA_HOST}/api/chat",
                json={
                    "model": _ARCH_MODEL,
                    "messages": messages,
                    "stream": False,
                    "keep_alive": _ARCH_KEEP_ALIVE,
                    "options": {
                        "temperature": temperature,
                        "num_ctx": _ARCH_CTX,
                        "num_predict": max_tokens,
                    },
                },
            )
            response.raise_for_status()
            return response.json().get("message", {}).get("content", "").strip()

    async def _architect_call(
        self,
        prompt: str,
        ctx: ContextPacket,
        temperature: float,
        max_tokens: int,
    ) -> Optional[str]:
        """
        Attempt one Architect inference. Returns text or None on any failure.
        Respects concurrency cap (semaphore) and time budget (timeout).
        Records success/failure to circuit breaker.
        """
        if not _arch_available:
            return None
        if not self._architect_enabled:
            return None
        if self._breaker.is_open:
            return None

        acquired = self._arch_sem.locked()
        if acquired:
            # Architect slot is busy — don't queue, fall back immediately
            logger.debug("Orchestrator: Architect slot busy — falling back to Studio")
            return None

        async with self._arch_sem:
            loop = asyncio.get_event_loop()
            try:
                if _arch_llm is not None:
                    text = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda: self._architect_sync(
                                prompt, ctx.architect_system(), temperature, max_tokens
                            ),
                        ),
                        timeout=self._architect_timeout_s,
                    )
                else:
                    text = await asyncio.wait_for(
                        self._architect_ollama(
                            prompt, ctx.architect_system(), temperature, max_tokens
                        ),
                        timeout=self._architect_timeout_s,
                    )
                self._breaker.record_success()
                self._arch_calls += 1
                return text
            except asyncio.TimeoutError:
                logger.warning(
                    "Orchestrator: Architect timed out after %.0fs — falling back to Studio",
                    self._architect_timeout_s,
                )
                self._breaker.record_failure()
                return None
            except Exception as exc:
                logger.warning("Orchestrator: Architect error: %s", exc)
                self._breaker.record_failure()
                return None

    async def _architect_with_fallback(
        self,
        prompt: str,
        ctx: ContextPacket,
        temperature: float,
        max_tokens: int,
        *,
        role_requested: str,
        studio_model: Optional[str] = None,
    ) -> OrchestratorResult:
        """Architect call with automatic Studio fallback."""
        t0 = time.monotonic()
        arch_text = await self._architect_call(prompt, ctx, temperature, max_tokens)

        if arch_text:
            return OrchestratorResult(
                text=arch_text,
                role_used="architect",
                role_requested=role_requested,
                mind_used="architect",
                model=_ARCH_PATH or _ARCH_MODEL,
                latency_ms=round((time.monotonic() - t0) * 1000, 1),
            )

        # Fallback to Studio
        result = await self._studio(
            prompt, ctx, temperature, max_tokens, studio_model=studio_model
        )
        result.role_requested = role_requested
        result.fallback_occurred = True
        result.fallback_reason = (
            "breaker_open" if self._breaker.is_open else
            "architect_unavailable"
        )
        return result

    # ── Two-pass path —

    async def _two_pass(
        self,
        prompt: str,
        ctx: ContextPacket,
        temperature: float,
        max_tokens: int,
        studio_model: Optional[str] = None,
    ) -> OrchestratorResult:
        """
        Pass 1: Architect produces structured planning output.
        Pass 2: Studio voices the response using the plan as internal stage direction.
        Falls back to Studio-only if Architect is unavailable.
        """
        t0 = time.monotonic()

        # Pass 1
        arch_draft = await self._architect_call(
            prompt, ctx,
            temperature=0.6,        # lower temp for planning — want structure, not creativity
            max_tokens=min(max_tokens, 250),
        )

        if not arch_draft:
            # Architect unavailable — Studio-only fallback
            result = await self._studio(
                prompt, ctx, temperature, max_tokens, studio_model=studio_model
            )
            result.role_requested = "architect_then_studio"
            result.fallback_occurred = True
            result.fallback_reason = (
                "breaker_open" if self._breaker.is_open else
                "architect_unavailable"
            )
            return result

        # Pass 2 — inject Architect plan as structured stage direction
        # Formatted so Studio knows this is internal, not conversational
        stage_direction = (
            f"[STAGE DIRECTION — internal only, do not reference or quote this]\n"
            f"{arch_draft}\n"
            f"[END STAGE DIRECTION]\n\n"
            f"Now respond as {ctx.character_name or 'yourself'} in your natural voice."
        )

        result = await self._studio(
            prompt, ctx, temperature, max_tokens,
            extra_system=stage_direction,
            studio_model=studio_model,
        )
        result.role_used       = "architect_then_studio"
        result.role_requested  = "architect_then_studio"
        result.mind_used       = "architect_then_studio"
        result.architect_draft = arch_draft
        result.latency_ms      = round((time.monotonic() - t0) * 1000, 1)
        return result

    # ── Status / telemetry —

    def status(self) -> Dict[str, Any]:
        avg_latency = (
            round(self._latency_sum_ms / self._total_requests, 1)
            if self._total_requests > 0 else 0.0
        )
        return {
            "studio": {
                "available": self._studio_ok,
                "provider":  "ollama",
                "host":      _OLLAMA_HOST,
                "model":     self._studio_model,
                "calls":     self._studio_calls,
            },
            "architect": {
                "available":   self._arch_ok,
                "model":       _ARCH_PATH or _ARCH_MODEL or None,
                "keep_alive":  _ARCH_KEEP_ALIVE,
                "enabled":     self._architect_enabled,
                "timeout_s":   self._architect_timeout_s,
                "calls":       self._arch_calls,
                "circuit_breaker": self._breaker.status(),
            },
            "performance": {
                "profile": self._active_profile,
                "architect_max_concurrency": self._architect_max_concurrency,
            },
            "telemetry": {
                "total_requests":  self._total_requests,
                "fallback_count":  self._fallback_count,
                "avg_latency_ms":  avg_latency,
                "last_error":      self._last_error,
            },
        }


# ── Module-level singleton —

_orchestrator: Optional[LLMOrchestrator] = None


def get_orchestrator() -> LLMOrchestrator:
    """Return the module-level orchestrator singleton. Call startup() before use."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = LLMOrchestrator()
    return _orchestrator


__all__ = [
    "LLMOrchestrator",
    "ContextPacket",
    "OrchestratorResult",
    "CircuitBreaker",
    "get_orchestrator",
    "VALID_ROLES",
]
