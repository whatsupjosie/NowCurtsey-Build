from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Protocol

import httpx

from .ai_runtime import AIProfile, AIRuntimeConfig, merge_runtime_options

logger = logging.getLogger("pubcast.ai.providers")


class AIProviderError(RuntimeError):
    """Raised for readable AI provider failures."""


@dataclass
class GenerateRequest:
    prompt: str
    system: str = ""
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerateResult:
    text: str
    provider: str
    backend: str
    model: str
    meta: Dict[str, Any] = field(default_factory=dict)


class TextProvider(Protocol):
    backend: str

    async def healthcheck(self, profile: AIProfile) -> Dict[str, Any]:
        ...

    async def generate(self, profile: AIProfile, request: GenerateRequest) -> GenerateResult:
        ...


class EchoProvider:
    backend = "echo"

    async def healthcheck(self, profile: AIProfile) -> Dict[str, Any]:
        return {"ok": True, "backend": self.backend, "detail": "Echo adapter is always available."}

    async def generate(self, profile: AIProfile, request: GenerateRequest) -> GenerateResult:
        return GenerateResult(
            text=f"[echo:{profile.name}] {request.prompt}",
            provider=profile.name,
            backend=self.backend,
            model=profile.model or "echo",
        )


class OllamaProvider:
    backend = "ollama"

    async def healthcheck(self, profile: AIProfile) -> Dict[str, Any]:
        endpoint = profile.endpoint.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{endpoint}/api/tags")
                response.raise_for_status()
            return {"ok": True, "backend": self.backend, "endpoint": profile.endpoint}
        except Exception as exc:
            return {"ok": False, "backend": self.backend, "endpoint": profile.endpoint, "error": str(exc)}

    async def generate(self, profile: AIProfile, request: GenerateRequest) -> GenerateResult:
        endpoint = profile.endpoint.rstrip("/")
        options: Dict[str, Any] = {
            "temperature": request.options.get("temperature", 0.7),
            "num_predict": request.options.get("max_tokens", 256),
        }
        context_window = request.options.get("num_ctx", request.options.get("context_window"))
        if context_window:
            options["num_ctx"] = int(context_window)
        for key in ("num_thread", "top_k", "top_p", "repeat_penalty", "seed"):
            if key in request.options:
                options[key] = request.options[key]
        payload = {
            "model": profile.model,
            "prompt": request.prompt if not request.system else f"{request.system}\n\n{request.prompt}",
            "stream": False,
            "options": options,
        }
        if request.options.get("keep_alive"):
            payload["keep_alive"] = str(request.options["keep_alive"])
        timeout_seconds = float(request.options.get("timeout_seconds", request.options.get("timeout", 60.0)))
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(f"{endpoint}/api/generate", json=payload)
            response.raise_for_status()
            text = response.json().get("response", "")
        return GenerateResult(
            text=text,
            provider=profile.name,
            backend=self.backend,
            model=profile.model,
            meta={"endpoint": profile.endpoint},
        )


class OpenAIProvider:
    backend = "openai"

    async def healthcheck(self, profile: AIProfile) -> Dict[str, Any]:
        api_key = os.getenv(profile.api_key_env, "").strip()
        return {
            "ok": bool(api_key),
            "backend": self.backend,
            "api_key_env": profile.api_key_env,
            "detail": "Configured" if api_key else "Missing API key env var.",
        }

    async def generate(self, profile: AIProfile, request: GenerateRequest) -> GenerateResult:
        api_key = os.getenv(profile.api_key_env, "").strip()
        if not api_key:
            raise AIProviderError(
                f"OpenAI profile '{profile.name}' requires env var '{profile.api_key_env}' to be set."
            )
        try:
            from openai import AsyncOpenAI  # type: ignore
        except ImportError as exc:
            raise AIProviderError("openai package is not installed.") from exc

        client = AsyncOpenAI(api_key=api_key)
        response = await client.responses.create(
            model=profile.model,
            input=[
                {
                    "role": "user",
                    "content": (f"{request.system}\n\n{request.prompt}" if request.system else request.prompt),
                }
            ],
            temperature=float(request.options.get("temperature", 0.7)),
        )
        parts = []
        if hasattr(response, "output"):
            for item in response.output:
                if getattr(item, "type", "") == "output_text":
                    parts.append(getattr(item, "text", ""))
        if not parts and hasattr(response, "output_text"):
            parts.append(getattr(response, "output_text"))
        return GenerateResult(
            text="".join(parts).strip(),
            provider=profile.name,
            backend=self.backend,
            model=profile.model,
        )


class GeminiProvider:
    backend = "gemini"

    async def healthcheck(self, profile: AIProfile) -> Dict[str, Any]:
        api_key = os.getenv(profile.api_key_env, "").strip()
        return {
            "ok": bool(api_key),
            "backend": self.backend,
            "api_key_env": profile.api_key_env,
            "detail": "Configured" if api_key else "Missing API key env var.",
        }

    async def generate(self, profile: AIProfile, request: GenerateRequest) -> GenerateResult:
        api_key = os.getenv(profile.api_key_env, "").strip()
        if not api_key:
            raise AIProviderError(
                f"Gemini profile '{profile.name}' requires env var '{profile.api_key_env}' to be set."
            )
        try:
            import google.generativeai as genai  # type: ignore
        except ImportError as exc:
            raise AIProviderError("google-generativeai package is not installed.") from exc

        genai.configure(api_key=api_key)

        def _generate() -> str:
            model = genai.GenerativeModel(
                profile.model,
                generation_config={"temperature": float(request.options.get("temperature", 0.7))},
            )
            result = model.generate_content(
                f"{request.system}\n\n{request.prompt}" if request.system else request.prompt
            )
            if getattr(result, "text", ""):
                return result.text
            for candidate in getattr(result, "candidates", []) or []:
                content = getattr(candidate, "content", None)
                for part in getattr(content, "parts", []) or []:
                    text = getattr(part, "text", "")
                    if text:
                        return text
            return ""

        text = await asyncio.to_thread(_generate)
        return GenerateResult(
            text=text.strip(),
            provider=profile.name,
            backend=self.backend,
            model=profile.model,
        )


class LocalGGUFProvider:
    """Adapter for local GGUF models served over HTTP."""

    backend = "local_gguf"

    async def healthcheck(self, profile: AIProfile) -> Dict[str, Any]:
        endpoint = profile.endpoint.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(endpoint)
            return {
                "ok": response.status_code < 500,
                "backend": self.backend,
                "endpoint": profile.endpoint,
                "status_code": response.status_code,
            }
        except Exception as exc:
            return {"ok": False, "backend": self.backend, "endpoint": profile.endpoint, "error": str(exc)}

    async def generate(self, profile: AIProfile, request: GenerateRequest) -> GenerateResult:
        endpoint = profile.endpoint.rstrip("/")
        prompt = f"{request.system}\n\n{request.prompt}" if request.system else request.prompt
        if endpoint.endswith("/completion"):
            payload: Dict[str, Any] = {
                "prompt": prompt,
                "temperature": float(request.options.get("temperature", 0.7)),
                "n_predict": int(request.options.get("max_tokens", 256)),
                "stream": False,
            }
        else:
            payload = {
                "model": profile.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": float(request.options.get("temperature", 0.7)),
                "max_tokens": int(request.options.get("max_tokens", 256)),
                "stream": False,
            }
        timeout_seconds = float(request.options.get("timeout_seconds", request.options.get("timeout", 60.0)))
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            data = response.json()
        text = (
            data.get("content")
            or data.get("response")
            or (((data.get("choices") or [{}])[0].get("message") or {}).get("content"))
            or ""
        )
        return GenerateResult(
            text=str(text).strip(),
            provider=profile.name,
            backend=self.backend,
            model=profile.model,
            meta={"endpoint": profile.endpoint},
        )


PROVIDER_REGISTRY: Dict[str, TextProvider] = {
    "echo": EchoProvider(),
    "ollama": OllamaProvider(),
    "openai": OpenAIProvider(),
    "gemini": GeminiProvider(),
    "local_gguf": LocalGGUFProvider(),
}


def get_provider(backend: str) -> TextProvider:
    provider = PROVIDER_REGISTRY.get((backend or "").strip().lower())
    if provider is None:
        raise AIProviderError(f"Unsupported AI backend '{backend}'.")
    return provider


async def generate_with_profile(
    config: AIRuntimeConfig,
    profile: AIProfile,
    prompt: str,
    *,
    system: str = "",
    overrides: Optional[Mapping[str, Any]] = None,
) -> GenerateResult:
    provider = get_provider(profile.backend)
    request = GenerateRequest(
        prompt=prompt,
        system=system,
        options=merge_runtime_options(config, profile, overrides),
    )
    return await provider.generate(profile, request)
