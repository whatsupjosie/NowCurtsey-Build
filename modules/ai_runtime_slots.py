"""Named AI model slots for PubCast conversation roles.

This module does not start Ollama or any model process. It only gives the
runtime, menus, and Pub Manager a stable contract for which configured profile
should serve each AI role once the local model host is available.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping

from .ai_runtime import AIRuntimeConfig, load_ai_runtime_config, validate_ai_runtime_config


DEFAULT_MODEL_SLOTS: Dict[str, Dict[str, str]] = {
    "alex": {
        "label": "Alex conversation layer",
        "profile": "ministral_3b_local",
        "fallback_profile": "ollama_gemma3",
        "requested_model": "ministral 3b",
    },
    "jeremy": {
        "label": "Jeremy Pub Manager / system helper layer",
        "profile": "gemma3_1b_q4_local",
        "fallback_profile": "gemma3_1b_local",
        "requested_model": "gemma3 1b q4 interactive",
    },
    "background_math": {
        "label": "Background math / process worker",
        "profile": "gemma4_compute_q5_e2b_local",
        "fallback_profile": "gemma3_1b_q4_local",
        "requested_model": "gemma4 e2b q5 background",
    },
}


@dataclass(frozen=True)
class AIModelSlotStatus:
    role: str
    label: str
    profile: str
    requested_model: str
    available: bool
    enabled: bool
    backend: str = ""
    model: str = ""
    endpoint: str = ""
    fallback_profile: str = ""
    fallback_available: bool = False
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "label": self.label,
            "profile": self.profile,
            "requested_model": self.requested_model,
            "available": self.available,
            "enabled": self.enabled,
            "backend": self.backend,
            "model": self.model,
            "endpoint": self.endpoint,
            "fallback_profile": self.fallback_profile,
            "fallback_available": self.fallback_available,
            "note": self.note,
        }


def build_model_slot_status(config: AIRuntimeConfig, slots: Mapping[str, Mapping[str, str]] | None = None) -> Dict[str, Any]:
    slots = slots or DEFAULT_MODEL_SLOTS
    statuses: Dict[str, Dict[str, Any]] = {}
    for role, slot in slots.items():
        profile_name = str(slot.get("profile", "")).strip()
        fallback_name = str(slot.get("fallback_profile", "")).strip()
        profile = config.profiles.get(profile_name)
        fallback = config.profiles.get(fallback_name) if fallback_name else None
        if profile is None:
            status = AIModelSlotStatus(
                role=role,
                label=str(slot.get("label", role)),
                profile=profile_name,
                requested_model=str(slot.get("requested_model", "")),
                available=False,
                enabled=False,
                fallback_profile=fallback_name,
                fallback_available=fallback is not None,
                note="Slot profile is not present yet; fallback can hold the place until the model tag is confirmed.",
            )
        else:
            status = AIModelSlotStatus(
                role=role,
                label=str(slot.get("label", role)),
                profile=profile_name,
                requested_model=str(slot.get("requested_model", profile.model)),
                available=True,
                enabled=profile.enabled,
                backend=profile.backend,
                model=profile.model,
                endpoint=profile.endpoint,
                fallback_profile=fallback_name,
                fallback_available=fallback is not None,
                note="Slot is configured. Local availability still depends on the model being present in Ollama.",
            )
        statuses[role] = status.to_dict()
    return {"active_profile": config.active_profile, "slots": statuses}


def load_model_slot_status(base_dir: Path | None = None) -> Dict[str, Any]:
    config = validate_ai_runtime_config(load_ai_runtime_config(base_dir))
    return build_model_slot_status(config)


__all__ = ["DEFAULT_MODEL_SLOTS", "AIModelSlotStatus", "build_model_slot_status", "load_model_slot_status"]
