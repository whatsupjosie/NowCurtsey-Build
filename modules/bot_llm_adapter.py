# PubCast AI — bot_llm_adapter.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
modules/bot_llm_adapter.py  —  PubCast Universal Bot LLM Adapter

Base layer for all LLM providers in PubCast.

Exports consumed by llm_framework.py:
  - BotLLMAdapter         abstract base class
  - PROVIDER_REGISTRY     mutable dict — framework registers adapters here
  - _TIMEOUT              httpx streaming timeout (seconds)
  - _COMPLETE_TIMEOUT     httpx non-streaming timeout (seconds)
  - OpenAIBotAdapter      OpenAI-compatible adapter
  - AnthropicBotAdapter   Anthropic Messages API adapter  (Anthropic SSE fix pass 4)
  - GeminiBotAdapter      Google Gemini adapter
  - EchoBotAdapter        Testing echo adapter

llm_framework.py builds on top of this:
  - OllamaBotAdapter, MistralBotAdapter, GroqBotAdapter
  - HardwareProfile, ModelSpec, MODEL_CATALOG
  - test_character_fidelity, get_adapter_for_provider

byok_manager.py imports from llm_framework.py only — it does not import from
this file directly.

Hardening passes:
  Pass 1 — Base interface + OpenAI adapter
  Pass 2 — EchoBotAdapter fallback for tests
  Pass 3 — Anthropic + Gemini adapters
  Pass 4 — Anthropic SSE fix: accumulate response_body, handle partial JSON
  Pass 5 — PROVIDER_REGISTRY pattern established
  Pass 6 — Error hygiene, timeout discipline, Windows-safe httpx usage
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

logger = logging.getLogger("pubcast.bot_llm_adapter")

# ── Timeout constants (consumed by llm_framework.py) ─────────────────────────

_TIMEOUT = float(os.getenv("PUBCAST_LLM_STREAM_TIMEOUT", "180"))    # streaming
_COMPLETE_TIMEOUT = float(os.getenv("PUBCAST_LLM_COMPLETE_TIMEOUT", "30"))  # one-shot


# ── Abstract base ─────────────────────────────────────────────────────────────

class BotLLMAdapter(ABC):
    """
    Provider-agnostic streaming LLM interface for PubCast bots.

    Subclasses implement stream() — an async generator that yields text chunks.
    complete() is provided as a convenience wrapper around stream().
    is_available() gates whether the adapter should be tried at all.
    """

    provider_name: str = "base"

    def is_available(self) -> bool:
        """Return True if this adapter has what it needs to make calls."""
        return True

    @abstractmethod
    async def stream(
        self,
        prompt: str,
        *,
        system: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        model: str = "",
        temperature: float = 0.8,
    ) -> AsyncGenerator[str, None]:
        """
        Yield text chunks for a given prompt.
        history is a list of message dicts: [{role, content, ...}]
        model overrides the adapter default when supplied.
        Never raises — log and return on error.
        """
        # Make the type checker happy — subclasses must yield
        return
        yield  # noqa: unreachable

    async def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        model: str = "",
        temperature: float = 0.8,
    ) -> str:
        """Convenience: collect all chunks from stream() into a single string."""
        parts: List[str] = []
        async for chunk in self.stream(
            prompt, system=system, history=history,
            model=model, temperature=temperature,
        ):
            parts.append(chunk)
        return "".join(parts)


# ── Echo adapter (testing + safe fallback) ────────────────────────────────────

class EchoBotAdapter(BotLLMAdapter):
    """
    Reflects the last user message back.
    Used for smoke tests and as the last-resort fallback when no backend is up.
    """

    provider_name = "echo"

    def is_available(self) -> bool:
        return True

    async def stream(
        self,
        prompt: str,
        *,
        system: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        model: str = "",
        temperature: float = 0.8,
    ) -> AsyncGenerator[str, None]:
        yield f"[echo] {prompt}"


# ── OpenAI-compatible adapter ─────────────────────────────────────────────────

class OpenAIBotAdapter(BotLLMAdapter):
    """
    OpenAI chat completions endpoint.
    Also works with any OpenAI-compatible API (Groq, Together, etc.) via base_url.
    Reads OPENAI_API_KEY from environment. Subclasses can override _resolve_key().
    """

    provider_name = "openai"
    _DEFAULT_MODEL = "gpt-4o-mini"
    _BASE_URL = "https://api.openai.com/v1"

    def is_available(self) -> bool:
        return bool(self._resolve_key())

    def _resolve_key(self) -> str:
        return os.getenv("OPENAI_API_KEY", "").strip()

    async def stream(
        self,
        prompt: str,
        *,
        system: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        model: str = "",
        temperature: float = 0.8,
    ) -> AsyncGenerator[str, None]:
        api_key = self._resolve_key()
        if not api_key:
            return
        resolved_model = model or self._DEFAULT_MODEL
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
                    "POST",
                    f"{self._BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": resolved_model,
                        "messages": messages,
                        "max_tokens": 1024,
                        "temperature": temperature,
                        "stream": True,
                    },
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        logger.warning("OpenAIBotAdapter HTTP %s: %s", resp.status_code, body[:200])
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
            logger.warning("OpenAIBotAdapter stream error: %s", exc)


# ── Anthropic adapter (Pass 4: SSE fix) ───────────────────────────────────────

class AnthropicBotAdapter(BotLLMAdapter):
    """
    Anthropic Messages API with SSE streaming.

    Pass 4 fix: Anthropic does NOT send standard OpenAI-style SSE.
    We accumulate response_body across content_block_delta events.
    Partial-JSON lines are silently skipped to survive chunked delivery.
    """

    provider_name = "anthropic"
    _DEFAULT_MODEL = "claude-haiku-4-5-20251001"
    _API_URL = "https://api.anthropic.com/v1/messages"

    def is_available(self) -> bool:
        return bool(self._resolve_key())

    def _resolve_key(self) -> str:
        return os.getenv("ANTHROPIC_API_KEY", "").strip()

    async def stream(
        self,
        prompt: str,
        *,
        system: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        model: str = "",
        temperature: float = 0.8,
    ) -> AsyncGenerator[str, None]:
        api_key = self._resolve_key()
        if not api_key:
            return
        resolved_model = model or self._DEFAULT_MODEL

        messages: List[Dict[str, str]] = []
        for entry in (history or []):
            uid = str(entry.get("user_id") or entry.get("sender_id") or "")
            text = str(entry.get("text", "")).strip()
            if not text:
                continue
            is_bot = uid.startswith("bot-") or uid.startswith("agent:")
            messages.append({"role": "assistant" if is_bot else "user", "content": text})
        messages.append({"role": "user", "content": prompt})

        body: Dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": 1024,
            "temperature": temperature,
            "messages": messages,
            "stream": True,
        }
        if system:
            body["system"] = system

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    self._API_URL,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=body,
                ) as resp:
                    if resp.status_code != 200:
                        response_body = await resp.aread()
                        logger.warning(
                            "AnthropicBotAdapter HTTP %s: %s",
                            resp.status_code, response_body[:200],
                        )
                        return
                    async for line in resp.aiter_lines():
                        # Anthropic SSE format: event lines + data lines
                        if not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            # Chunked delivery can split JSON across lines — skip partial
                            continue
                        event_type = event.get("type", "")
                        if event_type == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    yield text
                        elif event_type == "message_stop":
                            break
        except Exception as exc:
            logger.warning("AnthropicBotAdapter stream error: %s", exc)


# ── Gemini adapter ────────────────────────────────────────────────────────────

class GeminiBotAdapter(BotLLMAdapter):
    """
    Google Gemini generateContent API.
    Reads GEMINI_API_KEY from environment. Subclasses can override _resolve_key().
    """

    provider_name = "gemini"
    _DEFAULT_MODEL = "gemini-2.0-flash"

    def is_available(self) -> bool:
        return bool(self._resolve_key())

    def _resolve_key(self) -> str:
        return os.getenv("GEMINI_API_KEY", "").strip()

    async def stream(
        self,
        prompt: str,
        *,
        system: str = "",
        history: Optional[List[Dict[str, Any]]] = None,
        model: str = "",
        temperature: float = 0.8,
    ) -> AsyncGenerator[str, None]:
        api_key = self._resolve_key()
        if not api_key:
            return
        resolved_model = model or self._DEFAULT_MODEL
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{resolved_model}:streamGenerateContent?key={api_key}&alt=sse"
        )

        contents: List[Dict[str, Any]] = []
        for entry in (history or []):
            uid = str(entry.get("user_id") or entry.get("sender_id") or "")
            text = str(entry.get("text", "")).strip()
            if not text:
                continue
            is_bot = uid.startswith("bot-") or uid.startswith("agent:")
            contents.append({
                "role": "model" if is_bot else "user",
                "parts": [{"text": text}],
            })
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": 1024,
                "temperature": temperature,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                async with client.stream("POST", url, json=body) as resp:
                    if resp.status_code != 200:
                        response_body = await resp.aread()
                        logger.warning(
                            "GeminiBotAdapter HTTP %s: %s",
                            resp.status_code, response_body[:200],
                        )
                        return
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if not data:
                            continue
                        try:
                            event = json.loads(data)
                            candidates = event.get("candidates", [])
                            if not candidates:
                                continue
                            parts = candidates[0].get("content", {}).get("parts", [])
                            for part in parts:
                                text = part.get("text", "")
                                if text:
                                    yield text
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
        except Exception as exc:
            logger.warning("GeminiBotAdapter stream error: %s", exc)


# ── Provider registry ─────────────────────────────────────────────────────────
# Mutable dict — llm_framework.py registers OllamaBotAdapter, MistralBotAdapter,
# GroqBotAdapter here at import time. Host key adapters live here too.

PROVIDER_REGISTRY: Dict[str, BotLLMAdapter] = {
    "openai":    OpenAIBotAdapter(),
    "anthropic": AnthropicBotAdapter(),
    "gemini":    GeminiBotAdapter(),
    "echo":      EchoBotAdapter(),
}


__all__ = [
    "BotLLMAdapter",
    "EchoBotAdapter",
    "OpenAIBotAdapter",
    "AnthropicBotAdapter",
    "GeminiBotAdapter",
    "PROVIDER_REGISTRY",
    "_TIMEOUT",
    "_COMPLETE_TIMEOUT",
]
