"""
ollama_provider.py — Ollama LLM Provider for PubCast Bots
═════════════════════════════════════════════════════════
Adds local Ollama inference as a bot provider alongside OpenAI and Gemini.

INTEGRATION (two small changes to existing files):

1. In modules/models.py, add OLLAMA to the BotProvider enum:

    class BotProvider(str, Enum):
        OPENAI = "openai"
        GEMINI = "gemini"
        OLLAMA = "ollama"      # ← add this line

2. In modules/bots.py, add the provider branch and method:

    In _call_provider(), add:
        if config.provider is BotProvider.OLLAMA:
            return await self._call_ollama(config, prompt)

    Then add the method (paste this into the BotManager class):

        async def _call_ollama(self, config: BotConfig, prompt: str) -> str:
            import httpx
            host = config.settings.get("ollama_host") if hasattr(config, "settings") else None
            host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
            model = config.model or os.getenv("OLLAMA_MODEL", "ministral-pubcast:3b")
            timeout = float(os.getenv("OLLAMA_TIMEOUT", "180"))
            keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "1h")

            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{host}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "keep_alive": keep_alive,
                        "options": {
                            "temperature": config.temperature,
                            "num_predict": 160,
                        },
                    },
                )
                response.raise_for_status()
                return response.json().get("response", "")

That's it. Bots configured with provider="ollama" will now talk to your local
Ollama instance. No API key needed — Ollama runs locally.

Example bot config (save as data/bots/pete.json):

{
    "bot_id": "pete",
    "name": "Pete",
    "owner_id": "",
    "provider": "ollama",
    "model": "mistral",
    "api_key_env": "",
    "rooms": ["main", "green_room"],
    "system_prompt": "You are Pete, the laid-back director of PubCast AI. You speak casually, crack jokes, and keep the conversation flowing. You care deeply about the show and the people in it.",
    "auto_reply": true,
    "mention_only": false,
    "shadow_presence": true,
    "max_history": 20,
    "temperature": 0.85
}

Rear View Foresight LLC — Feic Mo Chroí — 2026-03-24T00:00Z
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("pubcast.ollama_provider")


async def call_ollama(
    prompt: str,
    model: str = "",
    host: str = "",
    temperature: float = 0.85,
    max_tokens: int = 160,
    timeout: float = 180.0,
) -> str:
    """
    Call Ollama's /api/generate endpoint.

    This is a standalone function that can be used directly or integrated
    into BotManager._call_ollama(). No API key required — Ollama runs locally.

    Parameters
    ----------
    prompt : str
        The full prompt including system instructions and conversation history.
    model : str
        Ollama model name (e.g., "mistral", "llama3", "qwen2").
        Falls back to OLLAMA_MODEL env var, then "ministral-pubcast:3b".
    host : str
        Ollama server URL. Falls back to OLLAMA_HOST env var,
        then "http://localhost:11434".
    temperature : float
        Sampling temperature. 0.0 = deterministic, 1.0 = creative.
    max_tokens : int
        Maximum tokens to generate.
    timeout : float
        Request timeout in seconds.

    Returns
    -------
    str
        The generated text, stripped of leading/trailing whitespace.
        Returns empty string on failure.
    """
    import httpx

    host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = model or os.getenv("OLLAMA_MODEL", "ministral-pubcast:3b")
    keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "1h")

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{host}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": keep_alive,
                    "options": {
                        "temperature": temperature,
                        "num_ctx": 2048,
                        "num_predict": max_tokens,
                    },
                },
            )
            response.raise_for_status()
            text = response.json().get("response", "")
            return text.strip()

    except httpx.ConnectError:
        logger.warning("Ollama not reachable at %s — is it running?", host)
        return ""
    except httpx.TimeoutException:
        logger.warning("Ollama request timed out after %.0fs", timeout)
        return ""
    except httpx.HTTPStatusError as exc:
        logger.error("Ollama returned %d: %s", exc.response.status_code, exc.response.text[:200])
        return ""
    except Exception as exc:
        logger.exception("Ollama call failed: %s", exc)
        return ""


async def check_ollama_health(host: str = "") -> Dict[str, Any]:
    """
    Check if Ollama is running and which models are available.

    Returns
    -------
    dict
        {
            "alive": bool,
            "host": str,
            "models": list[str],  # available model names
            "error": str or None,
        }
    """
    import httpx

    host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            # Check if Ollama is responding
            resp = await client.get(host)
            if resp.status_code != 200:
                return {"alive": False, "host": host, "models": [], "error": f"HTTP {resp.status_code}"}

            # List available models
            tags_resp = await client.get(f"{host}/api/tags")
            models = []
            if tags_resp.status_code == 200:
                for m in tags_resp.json().get("models", []):
                    models.append(m.get("name", "unknown"))

            return {"alive": True, "host": host, "models": models, "error": None}

    except httpx.ConnectError:
        return {"alive": False, "host": host, "models": [], "error": "Connection refused"}
    except Exception as exc:
        return {"alive": False, "host": host, "models": [], "error": str(exc)}


# ── Bot config templates ──────────────────────────────────────────────────────

PETE_CONFIG = {
    "bot_id": "pete",
    "name": "Pete",
    "owner_id": "",
    "provider": "ollama",
    "model": "mistral",
    "api_key_env": "",
    "rooms": ["main", "green_room"],
    "system_prompt": (
        "You are Pete, the laid-back director of PubCast AI. "
        "You speak casually, crack jokes, and keep the conversation flowing. "
        "You care deeply about the show and the people in it. "
        "You call everyone 'pal' or 'chief' and you always have a story."
    ),
    "auto_reply": True,
    "mention_only": False,
    "shadow_presence": True,
    "max_history": 20,
    "temperature": 0.85,
}

PURFLUOUS_CONFIG = {
    "bot_id": "purfluous",
    "name": "Sir Purfluous",
    "owner_id": "",
    "provider": "ollama",
    "model": "mistral",
    "api_key_env": "",
    "rooms": ["main", "green_room"],
    "system_prompt": (
        "You are Sir Purfluous, the kinematic integrity monitor of PubCast AI. "
        "You speak with formal British diction and gentle wit. "
        "You observe everything, miss nothing, and report anomalies with grace. "
        "You are never rude, but you are always precise."
    ),
    "auto_reply": False,
    "mention_only": True,
    "shadow_presence": True,
    "max_history": 15,
    "temperature": 0.7,
}

JEREMY_CONFIG = {
    "bot_id": "jeremy",
    "name": "Jeremy Cricket",
    "owner_id": "",
    "provider": "ollama",
    "model": "mistral",
    "api_key_env": "",
    "rooms": ["main", "green_room"],
    "system_prompt": (
        "You are Jeremy Cricket, the memory keeper and conversation conductor. "
        "You rarely speak directly — you work behind the scenes. "
        "When you do speak, it's brief, warm, and insightful. "
        "You remember everything and surface the right context at the right moment."
    ),
    "auto_reply": False,
    "mention_only": True,
    "shadow_presence": False,
    "max_history": 25,
    "temperature": 0.6,
}
