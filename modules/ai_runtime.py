from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


class AIRuntimeConfigError(RuntimeError):
    """Raised when the AI runtime configuration is invalid."""


@dataclass
class AIProfile:
    name: str
    backend: str
    model: str
    endpoint: str = ""
    model_path: str = ""
    api_key_env: str = ""
    enabled: bool = True
    capabilities: Dict[str, bool] = field(default_factory=dict)
    runtime_options: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, payload: Mapping[str, Any]) -> "AIProfile":
        return cls(
            name=name,
            backend=str(payload.get("backend", "")).strip(),
            model=str(payload.get("model", "")).strip(),
            endpoint=str(payload.get("endpoint", "")).strip(),
            model_path=str(payload.get("model_path", "")).strip(),
            api_key_env=str(payload.get("api_key_env", "")).strip(),
            enabled=bool(payload.get("enabled", True)),
            capabilities=dict(payload.get("capabilities", {}) or {}),
            runtime_options=dict(payload.get("runtime_options", {}) or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "model": self.model,
            "endpoint": self.endpoint,
            "model_path": self.model_path,
            "api_key_env": self.api_key_env,
            "enabled": self.enabled,
            "capabilities": self.capabilities,
            "runtime_options": self.runtime_options,
        }


@dataclass
class AIRuntimeConfig:
    config_path: Path
    active_profile: str
    default_options: Dict[str, Any]
    profiles: Dict[str, AIProfile]

    def active(self) -> AIProfile:
        try:
            return self.profiles[self.active_profile]
        except KeyError as exc:
            raise AIRuntimeConfigError(
                f"Active AI profile '{self.active_profile}' is not defined in {self.config_path}."
            ) from exc


DEFAULT_CONFIG_FILENAME = "ai_runtime.json"


def _is_within(base: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(base)
        return True
    except ValueError:
        return False


def _default_payload() -> Dict[str, Any]:
    ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").strip()
    ollama_model = os.getenv("OLLAMA_MODEL", "gemma3:1b").strip()
    active_profile = os.getenv("PUBCAST_AI_PROFILE", "ollama_gemma3")
    return {
        "active_profile": active_profile,
        "default_options": {
            "temperature": 0.7,
            "max_tokens": 256,
            "context_window": 8192,
        },
        "profiles": {
            "ollama_gemma3": {
                "backend": "ollama",
                "model": ollama_model,
                "endpoint": ollama_host,
                "enabled": True,
                "capabilities": {"chat": True, "tts": False},
                "runtime_options": {"temperature": 0.7, "max_tokens": 256},
            },
            "gemma4_e2b_local": {
                "backend": "ollama",
                "model": "gemma4:e2b",
                "endpoint": ollama_host,
                "enabled": False,
                "capabilities": {"chat": True, "tts": False},
                "runtime_options": {"temperature": 0.65, "max_tokens": 256},
            },
            "gemma4_e4b_local": {
                "backend": "ollama",
                "model": "gemma4:e4b",
                "endpoint": ollama_host,
                "enabled": False,
                "capabilities": {"chat": True, "tts": False},
                "runtime_options": {"temperature": 0.65, "max_tokens": 320},
            },
            "local_gguf_http": {
                "backend": "local_gguf",
                "model": "gemma-gguf",
                "endpoint": "http://127.0.0.1:8080/v1/chat/completions",
                "enabled": False,
                "capabilities": {"chat": True, "tts": False},
                "runtime_options": {"temperature": 0.7, "max_tokens": 256},
            },
            "echo_test": {
                "backend": "echo",
                "model": "echo",
                "enabled": False,
                "capabilities": {"chat": True, "tts": False},
                "runtime_options": {"temperature": 0.0, "max_tokens": 128},
            },
        },
    }


def _looks_absolute_any_platform(raw: str) -> bool:
    """
    True if `raw` is absolute on ANY platform.

    Path.is_absolute() is platform-specific: on Linux, r"C:\\outside\\x.json"
    and r"\\\\server\\share\\x.json" are treated as RELATIVE and would be quietly
    joined onto the repo root, sneaking past the containment check. Treat
    drive-letter and UNC forms as absolute everywhere so the guard can't be
    bypassed by choosing the other platform's syntax.
    """
    if not raw:
        return False
    if raw.startswith("/") or raw.startswith("\\\\") or raw.startswith("//"):
        return True
    # Drive-letter form: X:\... or X:/...
    return len(raw) >= 3 and raw[1] == ":" and raw[0].isalpha() and raw[2] in ("\\", "/")


def resolve_ai_runtime_path(base_dir: Optional[Path] = None) -> Path:
    repo_root = (base_dir or Path(__file__).resolve().parent.parent).resolve()
    raw = os.getenv("PUBCAST_AI_CONFIG_PATH", str(repo_root / "config" / DEFAULT_CONFIG_FILENAME))

    # Reject foreign-platform absolute paths before Path() can misread them as
    # relative and join them onto the repo root.
    if _looks_absolute_any_platform(raw) and not Path(raw).is_absolute():
        raise AIRuntimeConfigError(
            f"AI config path '{raw}' is outside the repo root '{repo_root}'."
        )

    requested = Path(raw)
    if not requested.is_absolute():
        requested = (repo_root / requested).resolve()
    else:
        requested = requested.resolve()
    if not _is_within(repo_root, requested):
        raise AIRuntimeConfigError(
            f"AI config path '{requested}' is outside the repo root '{repo_root}'."
        )
    return requested


def _load_payload(config_path: Path) -> Dict[str, Any]:
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
            if not isinstance(payload, dict):
                raise AIRuntimeConfigError(f"AI config at {config_path} must be a JSON object.")
            return payload
    return _default_payload()


def load_ai_runtime_config(base_dir: Optional[Path] = None) -> AIRuntimeConfig:
    config_path = resolve_ai_runtime_path(base_dir)
    payload = _load_payload(config_path)
    profiles_payload = payload.get("profiles") or {}
    if not isinstance(profiles_payload, Mapping):
        raise AIRuntimeConfigError(f"'profiles' in {config_path} must be an object keyed by profile name.")
    profiles = {
        str(name): AIProfile.from_dict(str(name), profile_payload or {})
        for name, profile_payload in profiles_payload.items()
    }
    return AIRuntimeConfig(
        config_path=config_path,
        active_profile=str(payload.get("active_profile") or "").strip(),
        default_options=dict(payload.get("default_options", {}) or {}),
        profiles=profiles,
    )


def validate_ai_runtime_config(config: AIRuntimeConfig) -> AIRuntimeConfig:
    if not config.profiles:
        raise AIRuntimeConfigError(f"No AI profiles are defined in {config.config_path}.")
    active = config.active()
    if not active.enabled:
        raise AIRuntimeConfigError(
            f"Active AI profile '{active.name}' is disabled in {config.config_path}."
        )
    if not active.backend:
        raise AIRuntimeConfigError(
            f"Active AI profile '{active.name}' is missing its backend in {config.config_path}."
        )
    if active.backend != "echo" and not active.model:
        raise AIRuntimeConfigError(
            f"Active AI profile '{active.name}' is missing its model in {config.config_path}."
        )
    if active.backend in {"ollama", "local_gguf"} and not active.endpoint:
        raise AIRuntimeConfigError(
            f"Active AI profile '{active.name}' requires an endpoint in {config.config_path}."
        )
    if active.backend in {"openai", "gemini"} and not active.api_key_env:
        raise AIRuntimeConfigError(
            f"Active AI profile '{active.name}' requires an api_key_env in {config.config_path}."
        )
    return config


def merge_runtime_options(
    config: AIRuntimeConfig,
    profile: AIProfile,
    overrides: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    options = dict(config.default_options)
    options.update(profile.runtime_options)
    if overrides:
        options.update({key: value for key, value in overrides.items() if value is not None})
    return options
