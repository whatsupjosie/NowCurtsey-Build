"""Named AI model slots for PubCast conversation roles.

This module does not start Ollama or any model process. It only gives the
runtime, menus, and Pub Manager a stable contract for which configured profile
should serve each AI role once the local model host is available.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .ai_runtime import AIProfile, AIRuntimeConfig, load_ai_runtime_config, validate_ai_runtime_config


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
    "pubpartner_manager": {
        "label": "PubPartner manager AI (oversees PubPartner as a whole)",
        "profile": "same_as_studio",
        "fallback_profile": "gemma3_1b_local",
        "requested_model": "same as PubCast Studio",
    },
    "pubpartner_character_default": {
        "label": "PubPartner individual-character AI (default for any character "
                  "without its own override in character_profiles)",
        "profile": "same_as_studio",
        "fallback_profile": "ollama_gemma3",
        "requested_model": "same as PubCast Studio",
    },
}

# Sentinel profile name: "use whatever AI is currently PubCast's primary Studio
# mind" instead of a fixed profile. Lets PubPartner's manager AI and any
# individual character's AI be configured to either share Studio's brain or
# run on a completely different one, per-slot or per-character, without
# duplicating provider config.
SAME_AS_STUDIO = "same_as_studio"


def resolve_studio_profile(config: AIRuntimeConfig) -> AIProfile:
    """
    Return the AIProfile that PubCast's Studio mind (llm_orchestrator.py) is
    actually answering with right now, so PubPartner can share it exactly.

    Mirrors llm_orchestrator.py's own resolution order:
      1. PUBCAST_PRIMARY_AI_PROFILE, if set and valid+enabled — Studio is
         running through the universal provider registry on this profile.
      2. Otherwise Studio's hardcoded local Ollama call — reconstructed here
         as an equivalent synthetic profile so callers get one consistent
         AIProfile either way, without importing llm_orchestrator (which
         would pull in the whole dual-mind runtime just for this lookup).
    """
    primary = os.getenv("PUBCAST_PRIMARY_AI_PROFILE", "").strip()
    if primary:
        profile = config.profiles.get(primary)
        if profile is not None and profile.enabled:
            return profile

    studio_model = os.getenv(
        "STUDIO_MODEL", os.getenv("OLLAMA_MODEL", "ministral-pubcast:3b")
    )
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    return AIProfile(
        name="studio_local_ollama",
        backend="ollama",
        model=studio_model,
        endpoint=ollama_host,
        enabled=True,
    )


def resolve_named_profile(config: AIRuntimeConfig, profile_name: str) -> Optional[AIProfile]:
    """Resolve a profile name, honoring the SAME_AS_STUDIO sentinel."""
    if profile_name == SAME_AS_STUDIO:
        return resolve_studio_profile(config)
    return config.profiles.get(profile_name)


def resolve_character_profile(
    config: AIRuntimeConfig,
    character_id: str,
    *,
    character_profiles: Optional[Mapping[str, str]] = None,
) -> Optional[AIProfile]:
    """
    Resolve the AI profile for one individual PubPartner character.

    `character_profiles` maps character_id -> profile name (or SAME_AS_STUDIO)
    and normally comes from ai_runtime.json's top-level "character_profiles"
    object, so each character can be pinned to its own model/provider, share
    Studio's, or fall back to the shared pubpartner_character_default slot —
    independently and without code changes.
    """
    mapping = character_profiles or {}
    name = mapping.get(character_id, "").strip() if isinstance(mapping.get(character_id), str) else ""
    if name:
        resolved = resolve_named_profile(config, name)
        if resolved is not None:
            return resolved
    return None


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
        profile = resolve_named_profile(config, profile_name) if profile_name else None
        fallback = resolve_named_profile(config, fallback_name) if fallback_name else None
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
            note = (
                "Slot shares PubCast Studio's current AI (same_as_studio)."
                if profile_name == SAME_AS_STUDIO
                else "Slot is configured. Local availability still depends on the model being present in Ollama."
            )
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
                note=note,
            )
        statuses[role] = status.to_dict()
    return {"active_profile": config.active_profile, "slots": statuses}


def load_model_slot_status(base_dir: Path | None = None) -> Dict[str, Any]:
    config = validate_ai_runtime_config(load_ai_runtime_config(base_dir))
    return build_model_slot_status(config)


__all__ = ["DEFAULT_MODEL_SLOTS", "AIModelSlotStatus", "build_model_slot_status", "load_model_slot_status"]
