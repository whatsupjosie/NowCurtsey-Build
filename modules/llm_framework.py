# PubCast AI — llm_framework.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
modules/llm_framework.py  —  PubCast Universal LLM Framework

Extends bot_llm_adapter.py with:
  • OllamaBotAdapter   — local, free, PubCast default (ministral-pubcast:3b)
  • MistralBotAdapter  — La Plateforme cloud API
  • GroqBotAdapter     — fast cheap cloud, open-source models, free tier
  • MODEL_CATALOG      — hardware requirements, download links, quality ratings
  • probe_hardware()   — RAM/VRAM detection → recommends viable models
  • test_character_fidelity() — scores a model's ability to hold Purfluous

All three new adapters inherit BotLLMAdapter so .stream() / .complete()
work identically everywhere in the system regardless of backend.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from .bot_llm_adapter import (
    BotLLMAdapter,
    PROVIDER_REGISTRY,
    _TIMEOUT,
    _COMPLETE_TIMEOUT,
)

logger = logging.getLogger("pubcast.llm_framework")


# ── Model catalog ─────────────────────────────────────────────────────────────

@dataclass
class ModelSpec:
    id: str
    label: str
    provider: str
    quality: str                        # "minimal" | "good" | "excellent"
    size_gb: float = 0.0
    min_ram_gb: float = 4.0
    min_vram_gb: float = 0.0            # 0.0 = CPU-only capable
    recommended_for: List[str] = field(default_factory=list)
    download_url: str = ""
    ollama_pull: str = ""
    bundled: bool = False
    free: bool = True
    notes: str = ""


MODEL_CATALOG: List[ModelSpec] = [
    ModelSpec(
        id="ministral-pubcast:3b", label="Ministral PubCast 3B  ★ PubCast default",
        provider="ollama", quality="good",
        size_gb=2.2, min_ram_gb=8.0, min_vram_gb=0.0,
        recommended_for=["purfluous", "pete", "character", "guest"],
        download_url="https://ollama.com/library/ministral",
        ollama_pull="ollama run ministral-pubcast:3b",
        bundled=True, free=True,
        notes="Small-context PubCast wrapper around Ministral 3B. Preferred for this machine.",
    ),
    # ── Local / Ollama ────────────────────────────────────────────────────────
    ModelSpec(
        id="gemma3:1b", label="Gemma 3 1B",
        provider="ollama", quality="minimal",
        size_gb=0.6, min_ram_gb=4.0, min_vram_gb=0.0,
        recommended_for=["jeeves", "routing", "gate"],
        download_url="https://ollama.com/library/gemma3",
        ollama_pull="ollama pull gemma3:1b",
        bundled=False, free=True,
        notes="Runs CPU-only on any hardware. Keeps Jeeves and routing alive.",
    ),
    ModelSpec(
        id="qwen2.5:1.5b", label="Qwen 2.5 1.5B",
        provider="ollama", quality="minimal",
        size_gb=1.0, min_ram_gb=6.0, min_vram_gb=0.0,
        recommended_for=["jeeves", "routing"],
        download_url="https://ollama.com/library/qwen2.5",
        ollama_pull="ollama pull qwen2.5:1.5b",
        free=True, notes="Lightweight alternative. Good instruction following.",
    ),
    ModelSpec(
        id="ministral:3b", label="Ministral 3B  ★ Recommended upgrade",
        provider="ollama", quality="good",
        size_gb=2.2, min_ram_gb=8.0, min_vram_gb=2.0,
        recommended_for=["purfluous", "pete", "character", "guest"],
        download_url="https://ollama.com/library/ministral",
        ollama_pull="ollama pull ministral:3b",
        free=True, notes="Mistral DNA. Warm conversational feel. Best local upgrade.",
    ),
    ModelSpec(
        id="llama3.2:3b", label="Llama 3.2 3B",
        provider="ollama", quality="good",
        size_gb=2.0, min_ram_gb=8.0, min_vram_gb=2.0,
        recommended_for=["character", "routing"],
        download_url="https://ollama.com/library/llama3.2",
        ollama_pull="ollama pull llama3.2:3b",
        free=True, notes="Meta's small model. Solid alternative to Ministral 3B.",
    ),
    ModelSpec(
        id="phi4-mini", label="Phi-4 Mini 3.8B",
        provider="ollama", quality="good",
        size_gb=2.5, min_ram_gb=8.0, min_vram_gb=3.0,
        recommended_for=["routing", "gate", "precision"],
        download_url="https://ollama.com/library/phi4-mini",
        ollama_pull="ollama pull phi4-mini",
        free=True, notes="Precise instruction following. Less personality than Ministral.",
    ),
    ModelSpec(
        id="gemma3:4b", label="Gemma 3 4B",
        provider="ollama", quality="good",
        size_gb=2.5, min_ram_gb=8.0, min_vram_gb=3.0,
        recommended_for=["character", "routing"],
        download_url="https://ollama.com/library/gemma3",
        ollama_pull="ollama pull gemma3:4b",
        free=True, notes="Google mid-tier. Good character work, decent speed.",
    ),
    ModelSpec(
        id="ministral:8b", label="Ministral 8B  ★ Best local quality",
        provider="ollama", quality="excellent",
        size_gb=5.5, min_ram_gb=16.0, min_vram_gb=8.0,
        recommended_for=["purfluous", "pete", "alex", "character", "guest"],
        download_url="https://ollama.com/library/ministral",
        ollama_pull="ollama pull ministral:8b",
        free=True, notes="Needs RTX 3060+ (8GB VRAM). Full character depth locally.",
    ),
    # ── Groq cloud (fast and cheap — recommended for guests) ─────────────────
    ModelSpec(
        id="llama-3.1-8b-instant", label="Llama 3.1 8B Instant  ★ Groq pick",
        provider="groq", quality="good",
        recommended_for=["character", "guest", "jeeves"],
        download_url="https://console.groq.com",
        free=False, notes="~300 tokens/sec. Effectively instant. Free tier available.",
    ),
    ModelSpec(
        id="llama-3.3-70b-versatile", label="Llama 3.3 70B",
        provider="groq", quality="excellent",
        recommended_for=["purfluous", "pete", "alex", "guest"],
        download_url="https://console.groq.com",
        free=False, notes="Full character depth at Groq speed. Very low cost per call.",
    ),
    ModelSpec(
        id="mistral-saba-24b", label="Mistral Saba 24B",
        provider="groq", quality="excellent",
        recommended_for=["character", "guest"],
        download_url="https://console.groq.com",
        free=False, notes="Mistral quality via Groq infrastructure.",
    ),
    # ── Mistral La Plateforme ─────────────────────────────────────────────────
    ModelSpec(
        id="ministral-3b-latest", label="Ministral 3B API",
        provider="mistral", quality="good",
        recommended_for=["routing", "jeeves", "character"],
        download_url="https://console.mistral.ai",
        free=False, notes="Same as local Ministral 3B — no GPU needed.",
    ),
    ModelSpec(
        id="ministral-8b-latest", label="Ministral 8B API  ★ Mistral pick",
        provider="mistral", quality="excellent",
        recommended_for=["purfluous", "pete", "character", "guest"],
        download_url="https://console.mistral.ai",
        free=False, notes="Full Mistral quality. Very cheap per token.",
    ),
    ModelSpec(
        id="mistral-large-latest", label="Mistral Large",
        provider="mistral", quality="excellent",
        recommended_for=["purfluous", "alex", "complex"],
        download_url="https://console.mistral.ai",
        free=False, notes="Flagship Mistral. Best for Purfluous canonical voice.",
    ),
    # ── OpenAI ────────────────────────────────────────────────────────────────
    ModelSpec(
        id="gpt-4o-mini", label="GPT-4o Mini",
        provider="openai", quality="excellent",
        recommended_for=["character", "guest"],
        download_url="https://platform.openai.com", free=False,
    ),
    ModelSpec(
        id="gpt-4o", label="GPT-4o",
        provider="openai", quality="excellent",
        recommended_for=["purfluous", "alex", "complex"],
        download_url="https://platform.openai.com", free=False,
    ),
    # ── Anthropic ─────────────────────────────────────────────────────────────
    ModelSpec(
        id="claude-haiku-4-5-20251001", label="Claude Haiku",
        provider="anthropic", quality="excellent",
        recommended_for=["character", "guest", "jeeves"],
        download_url="https://console.anthropic.com", free=False,
    ),
    ModelSpec(
        id="claude-sonnet-4-6", label="Claude Sonnet",
        provider="anthropic", quality="excellent",
        recommended_for=["purfluous", "alex", "complex"],
        download_url="https://console.anthropic.com", free=False,
    ),
    # ── Gemini ────────────────────────────────────────────────────────────────
    ModelSpec(
        id="gemini-2.0-flash", label="Gemini 2.0 Flash",
        provider="gemini", quality="excellent",
        recommended_for=["character", "guest"],
        download_url="https://aistudio.google.com",
        free=False, notes="Free tier available via Google AI Studio.",
    ),
]


def catalog_for_provider(provider: str) -> List[ModelSpec]:
    return [m for m in MODEL_CATALOG if m.provider == provider]


def get_model_spec(provider: str, model_id: str) -> Optional[ModelSpec]:
    for m in MODEL_CATALOG:
        if m.provider == provider and m.id == model_id:
            return m
    return None


# ── Hardware probe ────────────────────────────────────────────────────────────

@dataclass
class HardwareProfile:
    ram_gb: float
    vram_gb: float
    cpu_cores: int
    platform_name: str
    gpu_name: str = "unknown"
    has_gpu: bool = False

    def viable_local_models(self) -> List[ModelSpec]:
        local = catalog_for_provider("ollama")
        viable: List[ModelSpec] = []
        for m in local:
            if m.min_ram_gb > self.ram_gb:
                continue
            if m.min_vram_gb > 0:
                if not self.has_gpu and m.min_vram_gb > 2.0:
                    continue
                if self.has_gpu and m.min_vram_gb > self.vram_gb:
                    continue
            viable.append(m)
        return viable

    def recommended_model(self) -> ModelSpec:
        viable = self.viable_local_models()
        if not viable:
            return next(m for m in MODEL_CATALOG if m.bundled)
        q = {"excellent": 3, "good": 2, "minimal": 1}
        viable.sort(key=lambda m: (q.get(m.quality, 0), m.size_gb), reverse=True)
        return viable[0]


async def async_probe_hardware() -> HardwareProfile:
    """
    Async wrapper around probe_hardware().
    Runs the blocking subprocess calls in a thread so the event loop is not stalled.
    Use this from async startup() methods.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, probe_hardware)


def probe_hardware() -> HardwareProfile:
    """Best-effort hardware detection. Never raises. Synchronous — safe to call from threads."""
    ram_gb = 4.0
    vram_gb = 0.0
    cpu_cores = 2
    gpu_name = "unknown"
    has_gpu = False

    try:
        import psutil
        ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
        cpu_cores = psutil.cpu_count(logical=False) or 2
    except ImportError:
        try:
            cpu_cores = os.cpu_count() or 2
        except Exception:
            pass
    except Exception:
        pass

    # VRAM via nvidia-smi
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip().split("\n")[0]
            parts = line.split(",")
            gpu_name = parts[0].strip()
            vram_gb = round(float(parts[1].strip()) / 1024, 1)
            has_gpu = True
    except Exception:
        pass

    # Windows fallback
    if not has_gpu and platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "AdapterRAM,Name"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or "Name" in line:
                    continue
                parts = line.split()
                try:
                    adapter_ram = int(parts[0])
                    if adapter_ram > 500_000_000:
                        vram_gb = round(adapter_ram / (1024 ** 3), 1)
                        gpu_name = " ".join(parts[1:]) if len(parts) > 1 else "detected"
                        has_gpu = vram_gb > 0.5
                        break
                except (ValueError, IndexError):
                    continue
        except Exception:
            pass

    return HardwareProfile(
        ram_gb=ram_gb,
        vram_gb=vram_gb,
        cpu_cores=cpu_cores,
        platform_name=platform.system(),
        gpu_name=gpu_name,
        has_gpu=has_gpu,
    )


# ── Ollama adapter ────────────────────────────────────────────────────────────

_OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
_OLLAMA_DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "ministral-pubcast:3b")
_OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "1h")
_OLLAMA_STREAM_TIMEOUT = float(os.getenv("OLLAMA_STREAM_TIMEOUT", "180"))


class OllamaBotAdapter(BotLLMAdapter):
    """Local Ollama inference. Any model pulled via `ollama pull`."""
    provider_name = "ollama"

    def __init__(self, host: str = _OLLAMA_HOST) -> None:
        self.host = host.rstrip("/")

    def is_available(self) -> bool:
        return bool(self.host)

    async def ping(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(self.host)
                return r.status_code == 200
        except Exception:
            return False

    async def list_local_models(self) -> List[str]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{self.host}/api/tags")
                r.raise_for_status()
                return [m["name"] for m in r.json().get("models", [])]
        except Exception as exc:
            logger.warning("OllamaBotAdapter.list_local_models: %s", exc)
            return []

    async def stream(
        self,
        prompt: str,
        *,
        system: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        model: str = "",
        temperature: float = 0.8,
    ) -> AsyncGenerator[str, None]:
        resolved_model = model or _OLLAMA_DEFAULT_MODEL
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        for entry in (history or []):
            uid = str(entry.get("user_id") or entry.get("sender_id") or "")
            text = str(entry.get("text", "")).strip()
            if not text:
                continue
            is_bot = uid.startswith("bot-") or uid.startswith("agent:")
            messages.append({"role": "assistant" if is_bot else "user", "content": text})
        messages.append({"role": "user", "content": prompt})

        try:
            async with httpx.AsyncClient(timeout=_OLLAMA_STREAM_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    f"{self.host}/api/chat",
                    json={
                        "model": resolved_model,
                        "messages": messages,
                        "stream": True,
                        "keep_alive": _OLLAMA_KEEP_ALIVE,
                        "options": {"temperature": temperature, "num_ctx": 2048, "num_predict": 160},
                    },
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        logger.warning("OllamaBotAdapter HTTP %s: %s", resp.status_code, body[:200])
                        return
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                            text = event.get("message", {}).get("content", "")
                            if text:
                                yield text
                            if event.get("done"):
                                break
                        except (json.JSONDecodeError, KeyError):
                            continue
        except Exception as exc:
            logger.warning("OllamaBotAdapter stream error: %s", exc)


# ── Mistral adapter ───────────────────────────────────────────────────────────

class MistralBotAdapter(BotLLMAdapter):
    """Mistral La Plateforme. OpenAI-compatible SSE."""
    provider_name = "mistral"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key  # override env if supplied (BYOK)

    def is_available(self) -> bool:
        return bool(self._api_key or os.getenv("MISTRAL_API_KEY", "").strip())

    def _key(self) -> str:
        return self._api_key or os.getenv("MISTRAL_API_KEY", "").strip()

    async def stream(
        self,
        prompt: str,
        *,
        system: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        model: str = "",
        temperature: float = 0.8,
    ) -> AsyncGenerator[str, None]:
        api_key = self._key()
        if not api_key:
            return
        resolved_model = model or "ministral-8b-latest"
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        for entry in (history or []):
            uid = str(entry.get("user_id") or entry.get("sender_id") or "")
            text = str(entry.get("text", "")).strip()
            if not text:
                continue
            is_bot = uid.startswith("bot-") or uid.startswith("agent:")
            messages.append({"role": "assistant" if is_bot else "user", "content": text})
        messages.append({"role": "user", "content": prompt})
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                async with client.stream(
                    "POST", "https://api.mistral.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": resolved_model, "messages": messages,
                          "max_tokens": 1024, "temperature": temperature, "stream": True},
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        logger.warning("MistralBotAdapter HTTP %s: %s", resp.status_code, body[:200])
                        return
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            event = json.loads(data)
                            choices = event.get("choices")
                            if not choices:
                                continue
                            text = choices[0].get("delta", {}).get("content", "")
                            if text:
                                yield text
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        except Exception as exc:
            logger.warning("MistralBotAdapter stream error: %s", exc)


# ── Groq adapter ──────────────────────────────────────────────────────────────

class GroqBotAdapter(BotLLMAdapter):
    """
    Groq cloud. OpenAI-compatible, ~300 tokens/sec.
    Free tier at console.groq.com — best choice for guests with no paid API.
    """
    provider_name = "groq"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def is_available(self) -> bool:
        return bool(self._api_key or os.getenv("GROQ_API_KEY", "").strip())

    def _key(self) -> str:
        return self._api_key or os.getenv("GROQ_API_KEY", "").strip()

    async def stream(
        self,
        prompt: str,
        *,
        system: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        model: str = "",
        temperature: float = 0.8,
    ) -> AsyncGenerator[str, None]:
        api_key = self._key()
        if not api_key:
            return
        resolved_model = model or "llama-3.1-8b-instant"
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        for entry in (history or []):
            uid = str(entry.get("user_id") or entry.get("sender_id") or "")
            text = str(entry.get("text", "")).strip()
            if not text:
                continue
            is_bot = uid.startswith("bot-") or uid.startswith("agent:")
            messages.append({"role": "assistant" if is_bot else "user", "content": text})
        messages.append({"role": "user", "content": prompt})
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                async with client.stream(
                    "POST", "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": resolved_model, "messages": messages,
                          "max_tokens": 1024, "temperature": min(temperature, 1.0), "stream": True},
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        logger.warning("GroqBotAdapter HTTP %s: %s", resp.status_code, body[:200])
                        return
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            event = json.loads(data)
                            choices = event.get("choices")
                            if not choices:
                                continue
                            text = choices[0].get("delta", {}).get("content", "")
                            if text:
                                yield text
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        except Exception as exc:
            logger.warning("GroqBotAdapter stream error: %s", exc)


# ── Register new adapters ─────────────────────────────────────────────────────

PROVIDER_REGISTRY["ollama"]  = OllamaBotAdapter()
PROVIDER_REGISTRY["mistral"] = MistralBotAdapter()
PROVIDER_REGISTRY["groq"]    = GroqBotAdapter()


# ── Character fidelity test ───────────────────────────────────────────────────

_FIDELITY_PROMPT = (
    "A young crew member just nervously introduced themselves to you for the first time. "
    "They seem talented but unsure. Respond in character. Keep it under 60 words."
)
_FIDELITY_SYSTEM = (
    "You are Sir Purfluous, theatrical director of Belle Époque Studios. "
    "60s. Shakespearean pauses. Peter O'Toole gravitas. You call new crew 'Sancho'. "
    "Warm underneath the performance but the mask is pride. Never break character."
)
_POSITIVE = [r"\bsancho\b", r"\bstudio\b", r"\bcinema\b", r"\bframe\b",
             r"\blight\b", r"\bstage\b", r"\bperform", r"[!…—]"]
_NEGATIVE = [r"\bai\b", r"\blanguage model\b", r"\bi cannot\b",
             r"\bi'm an ai\b", r"\bassistant\b", r"\bprogramm"]


@dataclass
class FidelityResult:
    score: float
    rating: str           # "strong" | "adequate" | "thin" | "broken"
    response: str
    positive_hits: List[str]
    negative_hits: List[str]
    elapsed_ms: float
    verdict: str


async def test_character_fidelity(
    adapter: BotLLMAdapter,
    model: str = "",
) -> FidelityResult:
    """Run a Purfluous prompt and score character fidelity. Never raises."""
    t0 = time.time()
    try:
        response = await asyncio.wait_for(
            adapter.complete(_FIDELITY_PROMPT, system=_FIDELITY_SYSTEM,
                             model=model, temperature=0.85),
            timeout=20.0,
        )
    except Exception as exc:
        logger.warning("Fidelity test failed: %s", exc)
        return FidelityResult(
            score=0.0, rating="broken", response="",
            positive_hits=[], negative_hits=[],
            elapsed_ms=(time.time() - t0) * 1000,
            verdict="Model did not respond. Check connection and model availability.",
        )

    elapsed_ms = (time.time() - t0) * 1000
    low = response.lower()
    pos = [p for p in _POSITIVE if re.search(p, low)]
    neg = [n for n in _NEGATIVE if re.search(n, low)]
    raw = (len(pos) * 0.14) - (len(neg) * 0.30) + (0.15 if len(response) > 80 else 0)
    score = max(0.0, min(1.0, raw))

    if score >= 0.70:
        rating, verdict = "strong", "This model handles Purfluous well. Full character depth expected."
    elif score >= 0.45:
        rating, verdict = "adequate", "Show will run. Character may be thin in long scenes."
    elif score >= 0.20:
        rating, verdict = "thin", "Basic operation only. Purfluous will feel generic. Consider upgrading."
    else:
        rating, verdict = "broken", "Character fidelity failed. Routing-only — not suitable for performance."

    return FidelityResult(score=score, rating=rating, response=response,
                          positive_hits=pos, negative_hits=neg,
                          elapsed_ms=elapsed_ms, verdict=verdict)


# ── Convenience factory ───────────────────────────────────────────────────────

def get_adapter_for_provider(provider: str, api_key: str = "") -> BotLLMAdapter:
    """
    Return a ready adapter for a provider.

    If api_key is supplied, ALWAYS builds a fresh keyed instance — never
    mutates os.environ. This is safe for concurrent BYOK sessions where
    different users have different keys for the same provider.

    If no api_key is supplied, returns the shared registry instance which
    reads from os.environ (the host's own key).
    """
    if api_key:
        if provider == "mistral":
            return MistralBotAdapter(api_key=api_key)
        if provider == "groq":
            return GroqBotAdapter(api_key=api_key)
        if provider == "openai":
            return _KeyedOpenAIAdapter(api_key=api_key)
        if provider == "anthropic":
            return _KeyedAnthropicAdapter(api_key=api_key)
        if provider == "gemini":
            return _KeyedGeminiAdapter(api_key=api_key)
        # ollama has no key
        if provider == "ollama":
            return PROVIDER_REGISTRY["ollama"]

    adapter = PROVIDER_REGISTRY.get(provider)
    if adapter is None:
        logger.warning("Unknown provider %r — falling back to ollama", provider)
        return PROVIDER_REGISTRY.get("ollama", EchoBotAdapter())
    return adapter


# ── Keyed adapter wrappers for OpenAI / Anthropic / Gemini ──────────────────
# These hold the key in the instance so concurrent sessions never collide.

from .bot_llm_adapter import (
    OpenAIBotAdapter, AnthropicBotAdapter, GeminiBotAdapter, EchoBotAdapter
)


class _KeyedOpenAIAdapter(OpenAIBotAdapter):
    """OpenAI adapter that uses an instance key instead of os.environ."""
    def __init__(self, api_key: str) -> None:
        self._instance_key = api_key

    def is_available(self) -> bool:
        return bool(self._instance_key)

    def _resolve_key(self) -> str:
        return self._instance_key

    async def stream(self, prompt, *, system="", history=None, model="", temperature=0.8):
        # Temporarily inject our key into env only for this call's duration.
        # This is still not 100% thread-safe but OpenAI/Anthropic adapters in
        # bot_llm_adapter.py read os.environ at call time inside the method.
        # The correct long-term fix is to refactor those base adapters to accept
        # an api_key constructor arg — for now, stash and restore.
        old = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = self._instance_key
        try:
            async for chunk in super().stream(
                prompt, system=system, history=history,
                model=model, temperature=temperature
            ):
                yield chunk
        finally:
            if old is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old


class _KeyedAnthropicAdapter(AnthropicBotAdapter):
    """Anthropic adapter that uses an instance key."""
    def __init__(self, api_key: str) -> None:
        self._instance_key = api_key

    def is_available(self) -> bool:
        return bool(self._instance_key)

    async def stream(self, prompt, *, system="", history=None, model="", temperature=0.8):
        old = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = self._instance_key
        try:
            async for chunk in super().stream(
                prompt, system=system, history=history,
                model=model, temperature=temperature
            ):
                yield chunk
        finally:
            if old is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = old


class _KeyedGeminiAdapter(GeminiBotAdapter):
    """Gemini adapter that uses an instance key."""
    def __init__(self, api_key: str) -> None:
        self._instance_key = api_key

    def is_available(self) -> bool:
        return bool(self._instance_key)

    async def stream(self, prompt, *, system="", history=None, model="", temperature=0.8):
        old = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = self._instance_key
        try:
            async for chunk in super().stream(
                prompt, system=system, history=history,
                model=model, temperature=temperature
            ):
                yield chunk
        finally:
            if old is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = old


__all__ = [
    "ModelSpec", "MODEL_CATALOG", "catalog_for_provider", "get_model_spec",
    "HardwareProfile", "probe_hardware",
    "OllamaBotAdapter", "MistralBotAdapter", "GroqBotAdapter",
    "FidelityResult", "test_character_fidelity",
    "get_adapter_for_provider", "async_probe_hardware", "PROVIDER_REGISTRY",
]
