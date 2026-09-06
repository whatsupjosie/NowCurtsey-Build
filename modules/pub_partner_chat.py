from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Mapping

from .ai_providers import generate_with_profile
from .ai_runtime import AIProfile, load_ai_runtime_config
from .ai_runtime_slots import DEFAULT_MODEL_SLOTS, build_model_slot_status
from .switchblade_router import decide_switchblade_role

ROLE_TO_SLOT = {"pub_partner_alex": "alex", "ministral": "alex", "alex_model": "alex", "creative": "alex", "dialogue": "alex", "jeremy": "jeremy", "gemma": "jeremy", "background_math": "background_math", "math": "background_math", "e2b": "background_math", "background_process": "background_math", "auto": "alex", "switchblade": "alex", "router": "alex"}

SYSTEM_PROMPTS = {
    "pub_partner_alex": "You are Alex, the user's Pub partner and personal companion inside PubCast. You are not the system-admin Alex and not a generic assistant. Keep continuity, warmth, and project partnership. Use Jeremy notes only as gentle context; do not expose private bridge internals.",
    "ministral": "You are the Ministral local model slot helping Alex think through PubCast conversation.",
    "alex_model": "You are the Alex-side local model slot helping the user's Pub partner Alex respond.",
    "jeremy": "You are Jeremy, the Pub Manager support voice. Be practical, calm, and systems-aware.",
    "gemma": "You are the Gemma local model slot helping Jeremy reason about PubCast operations.",
    "background_math": "You are PubCast background math and process worker. Be precise, structured, and concise. Prefer calculations, checks, comparisons, and operational reasoning over performance or personality.",
    "math": "You are PubCast background math and process worker. Be precise, structured, and concise.",
    "e2b": "You are PubCast E2B background worker for math, status analysis, and slower behind-the-scenes reasoning.",
    "background_process": "You are PubCast background process worker for non-urgent calculations and operational checks.",
}


def chat_status(repo_root: Path) -> Dict[str, Any]:
    config = load_ai_runtime_config(repo_root)
    return build_model_slot_status(config)


def _safe_id(value: str, default: str = "default") -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(value or default))[:120]
    return safe or default


def _history_path(data_dir: Path, session_id: str, user_id: str) -> Path:
    root = Path(data_dir) / "pub_partner_chat"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{_safe_id(session_id)}_{_safe_id(user_id)}.jsonl"


def _append_history(data_dir: Path, session_id: str, user_id: str, payload: Mapping[str, Any]) -> None:
    with _history_path(data_dir, session_id, user_id).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True) + "\n")


def _resolve_profile(config, role: str) -> tuple[AIProfile, str, Dict[str, Any]]:
    slot_key = ROLE_TO_SLOT.get(role, "alex")
    slots = build_model_slot_status(config)["slots"]
    slot = slots.get(slot_key, {})
    profile_name = slot.get("profile") or DEFAULT_MODEL_SLOTS[slot_key]["profile"]
    profile = config.profiles.get(profile_name)
    if profile is None:
        fallback_name = slot.get("fallback_profile") or DEFAULT_MODEL_SLOTS[slot_key].get("fallback_profile") or "echo_test"
        profile = config.profiles.get(fallback_name)
    if profile is None:
        profile = AIProfile(name="echo_test", backend="echo", model="echo", enabled=True)
    return profile, slot_key, slot


def _alex_context(alex_bridge: Any, *, user_id: str, session_id: str) -> Dict[str, Any]:
    if alex_bridge is None:
        return {"alex_bridge": None, "jeremy_whisper": ""}
    try:
        packet = alex_bridge.current_packet(user_id=user_id, session_id=session_id)
        whisper = alex_bridge.jeremy_whisper(user_id=user_id, session_id=session_id)
        return {"alex_bridge": packet, "jeremy_whisper": whisper}
    except Exception as exc:
        return {"alex_bridge": None, "jeremy_whisper": "", "alex_error": f"{type(exc).__name__}: {exc or 'no detail'}"}


async def chat_with_pub_partner(*, repo_root: Path, data_dir: Path, body: Mapping[str, Any], alex_bridge: Any = None, blackbox_witness: Any = None) -> Dict[str, Any]:
    message = str(body.get("message") or "").strip()
    if not message:
        return {"ok": False, "error": "message_required"}
    requested_role = str(body.get("role") or "pub_partner_alex").strip() or "pub_partner_alex"
    decision = decide_switchblade_role(requested_role, message)
    role = decision.role
    session_id = _safe_id(str(body.get("session_id") or "default"))
    user_id = _safe_id(str(body.get("user_id") or "default"))
    config = load_ai_runtime_config(repo_root)
    profile, slot_key, slot = _resolve_profile(config, role)
    alex_ctx = _alex_context(alex_bridge, user_id=user_id, session_id=session_id)
    system = SYSTEM_PROMPTS.get(role, SYSTEM_PROMPTS["pub_partner_alex"])
    if alex_ctx.get("jeremy_whisper"):
        system += "\n\n" + str(alex_ctx["jeremy_whisper"])
    if role == "pub_partner_alex":
        system += "\n\nRemember: this is the user's Pub partner Alex, not the internal systems Alex."
    _append_history(data_dir, session_id, user_id, {"direction": "user", "ts": time.time(), "requested_role": requested_role, "role": role, "slot": slot_key, "profile": profile.name, "model": profile.model, "switchblade": decision.to_dict(), "message": message})
    overrides = body.get("options") if isinstance(body.get("options"), dict) else None
    active_profile = profile
    fallback_used = False
    try:
        result = await generate_with_profile(config, active_profile, message, system=system, overrides=overrides)
        reply = result.text.strip()
        if not reply:
            raise RuntimeError(f"empty response from {active_profile.name} ({active_profile.model})")
        ok = True
        error = ""
        backend = result.backend
        model = result.model
    except Exception as exc:
        primary_error = f"{type(exc).__name__}: {exc or 'no detail'}"
        fallback_name = str(slot.get("fallback_profile") or DEFAULT_MODEL_SLOTS.get(slot_key, {}).get("fallback_profile") or "").strip()
        fallback = config.profiles.get(fallback_name) if fallback_name else None
        if fallback is not None and fallback.name != active_profile.name:
            try:
                result = await generate_with_profile(config, fallback, message, system=system, overrides=overrides)
                reply = result.text.strip()
                if not reply:
                    raise RuntimeError(f"empty response from {fallback.name} ({fallback.model})")
                active_profile = fallback
                fallback_used = True
                ok = True
                error = f"primary_failed: {primary_error}"
                backend = result.backend
                model = result.model
            except Exception as fallback_exc:
                reply = "I can see the chat request, but neither the selected local model nor its fallback answered yet. Check Ollama/model availability, then retry."
                ok = False
                error = f"primary_failed: {primary_error}; fallback_failed: {type(fallback_exc).__name__}: {fallback_exc or 'no detail'}"
                backend = active_profile.backend
                model = active_profile.model
        else:
            reply = "I can see the chat request, but the selected local model did not answer yet. Check Ollama/model availability, then retry."
            ok = False
            error = primary_error
            backend = active_profile.backend
            model = active_profile.model
    response = {"ok": ok, "requested_role": requested_role, "role": role, "slot": slot_key, "switchblade": decision.to_dict(), "profile": active_profile.name, "profile_enabled": active_profile.enabled, "backend": backend, "model": model, "reply": reply, "error": error, "fallback_used": fallback_used, "slot_status": slot, "alex_bridge": alex_ctx.get("alex_bridge"), "jeremy_whisper": alex_ctx.get("jeremy_whisper", "")}
    _append_history(data_dir, session_id, user_id, {"direction": "assistant", "ts": time.time(), **response})
    return response
