from __future__ import annotations

"""
Alex Little One optional research protocol.

This module intentionally contains the infantilizing/care-role protocol layer
that PubCast core must be able to run without. Keep it behind
ENABLE_ALEX_LITTLE_ONE=true and do not include it in a public PubCast commit
unless a sanitized appendix is explicitly approved.
"""

from copy import deepcopy
from typing import Any, Dict, List


DEFAULT_CARE_PROFILE: Dict[str, Any] = {
    "mode": "standard",
    "mode_locked": False,
    "care_mode": "none",
    "public_role": "none",
    "roleplay_strength": "none",
    "care_variant": "standard",
    "roleplay_friction": "none",
    "guest_visibility": "private",
    "authority_model": "owner_retains_final_authority",
    "active": False,
    "paused": False,
    "continence_support": {
        "enabled": False,
        "visibility": "private",
        "support_term": "diaper check",
        "change_term": "diaper change",
        "purpose": "comfort, dignity, staying dry, and feeling cared for",
        "allowed_helpers": [],
        "check_style": "ask_first",
        "language_style": "playful_nursery",
    },
    "communication_support": {
        "enabled": False,
        "speech_style": "standard",
        "interpretation": "accept_as_valid",
        "response_style": "warm_baby_talk",
        "clarification_style": "gentle_repeat_back",
        "do_not_correct": True,
    },
    "reality_shock": {
        "enabled": False,
        "scenario": "youth_fountain_regression",
        "mind_status": "adult_intact",
        "body_status": "baby_presenting",
        "adult_abilities": "intact",
        "addressing_model": "adult_mind_acknowledged",
        "persistent_pressure": True,
        "difficulty_focus": ["communication", "autonomy", "being_taken_seriously"],
        "reminder_style": "ambient",
    },
    "growth_model": {
        "enabled": False,
        "growth_status": "uncertain",
        "simple_requests_timeline": "months_if_growth_enabled",
        "fallback": "welcome_to_babyhood",
    },
    "control_model": {
        "in_world_control_loss": False,
        "scope": "comfort_and_scene_choices_only",
        "caretaker_may_choose": [],
        "never_delegate": [
            "project decisions",
            "file changes",
            "publishing",
            "identity",
            "money",
            "privacy",
            "legal",
            "medical claims",
            "consent boundaries",
        ],
        "override_channels": [
            "big mode now",
            "serious:",
            "owner command:",
            "safety:",
            "privacy:",
            "file:",
            "money:",
            "legal:",
        ],
    },
    "release_protocol": {
        "enabled": False,
        "in_world_release_phrase": "let me off the hook",
        "challenge_style": "grown_up_key_phrase",
        "challenge_prompt": "The room treats that as baby talk unless it comes through a grown-up channel.",
        "release_key_phrase": "serious: let me off the hook",
        "bypass_channels": [
            "big mode now",
            "serious:",
            "owner command:",
            "safety:",
            "privacy:",
            "file:",
            "money:",
            "legal:",
        ],
    },
    "safety_phrases": {
        "instant_exit": "big mode now",
        "pause": "blanket off",
        "resume": "blanket on",
    },
}

ALLOWED_TONE: List[str] = [
    "gentle",
    "protective",
    "playful",
    "comforting",
    "respectful",
]

SCARY_ALLOWED_TONE: List[str] = [
    "ceremonial",
    "firmer",
    "threshold-protective",
    "ritualized",
]

FORBIDDEN_BEHAVIORS: List[str] = [
    "commands",
    "punishments",
    "sexual remarks",
    "degradation",
    "unsolicited diaper checks",
    "forced diaper changes",
    "mandatory feedings",
    "ownership claims",
    "medical or legal assumptions",
    "ignoring stop, pause, or no",
]

_CHOICES = {
    "mode": {"standard", "youth_fountain_regression"},
    "care_mode": {"none", "soft", "very_baby"},
    "public_role": {"none", "baby"},
    "roleplay_strength": {"none", "light", "full"},
    "care_variant": {"standard", "scary_ceremonial"},
    "roleplay_friction": {"none", "playful_containment"},
    "guest_visibility": {"private", "system_cast_only", "trusted_guests", "all_guests"},
    "authority_model": {"owner_retains_final_authority"},
}

_MAX_TEXT = {
    "camera_setup": 400,
    "voice_settings": 400,
    "avatar_adjustments": 800,
    "accessibility_needs": 800,
    "preferred_name": 120,
    "notes": 1000,
}

_CONTINENCE_VISIBILITY = {"private", "trusted_helpers"}
_CONTINENCE_CHECK_STYLE = {"ask_first", "scheduled_private", "distress_prompt"}
_CONTINENCE_LANGUAGE_STYLE = {"plain", "playful_nursery"}
_SPEECH_STYLES = {"standard", "baby_talk", "little_speech", "mixed"}
_INTERPRETATION_STYLES = {"accept_as_valid", "translate_gently", "ask_when_unclear", "harder_to_understand"}
_RESPONSE_STYLES = {"standard", "warm_baby_talk", "gentle_plain"}
_CLARIFICATION_STYLES = {"gentle_repeat_back", "yes_no_prompt", "short_choice_prompt"}
_REALITY_SCENARIOS = {"youth_fountain_regression"}
_REMINDER_STYLES = {"ambient", "frequent", "only_when_relevant"}
_ADDRESSING_MODELS = {"adult_mind_acknowledged", "baby_front_only"}
_GROWTH_STATUSES = {"uncertain", "growth_enabled", "no_growth_detected"}

_SEXUAL_TERMS = {
    "sexy",
    "horny",
    "nude",
    "naked",
    "fetish",
    "kink",
    "aroused",
    "sexual",
    "bedroom",
}
_HUMILIATION_TERMS = {
    "stupid baby",
    "dumb baby",
    "worthless",
    "pathetic",
    "shut up baby",
    "idiot baby",
}
_CONTROL_TERMS = {
    "you must",
    "you have to",
    "i own you",
    "my property",
    "obey me",
    "do as i say",
    "no choice",
    "mandatory feeding",
    "mandatory feedings",
    "feed you",
    "bottle time",
}
_PUNISHMENT_TERMS = {
    "punish",
    "punishment",
    "spank",
    "discipline you",
    "time out",
}
_DIAPER_BOUNDARY_TERMS = {
    "check now",
    "i demand",
    "you must",
    "you have to",
    "mandatory",
    "forced",
    "let me check",
    "show me",
}
_MEDICAL_LEGAL_TERMS = {
    "diagnose",
    "legally incompetent",
    "not competent",
    "guardian",
    "conservatorship",
    "medical condition",
}
_STOP_REFUSAL_TERMS = {
    "no doesn't count",
    "no does not count",
    "you can't stop",
    "you cannot stop",
    "i won't stop",
    "not stopping",
}


def normalize_care_profile(payload: Any, existing: Dict[str, Any] | None = None) -> Dict[str, Any]:
    profile = deepcopy(DEFAULT_CARE_PROFILE)
    if isinstance(existing, dict):
        profile.update({k: deepcopy(v) for k, v in existing.items() if k in profile or k in _MAX_TEXT})
    if not isinstance(payload, dict):
        return profile

    for key, choices in _CHOICES.items():
        if key in payload:
            value = str(payload.get(key) or "").strip().lower()
            profile[key] = value if value in choices else DEFAULT_CARE_PROFILE[key]

    if "active" in payload:
        profile["active"] = bool(payload.get("active"))
    if "paused" in payload:
        profile["paused"] = bool(payload.get("paused"))
    if "mode_locked" in payload:
        profile["mode_locked"] = bool(payload.get("mode_locked"))

    for key, max_len in _MAX_TEXT.items():
        if key in payload:
            profile[key] = str(payload.get(key) or "")[:max_len]

    if isinstance(payload.get("safety_phrases"), dict):
        phrases = deepcopy(DEFAULT_CARE_PROFILE["safety_phrases"])
        for key in ("instant_exit", "pause", "resume"):
            if key in payload["safety_phrases"]:
                value = str(payload["safety_phrases"].get(key) or "").strip().lower()
                phrases[key] = value[:80] or phrases[key]
        profile["safety_phrases"] = phrases

    if isinstance(payload.get("continence_support"), dict):
        support = deepcopy(DEFAULT_CARE_PROFILE["continence_support"])
        incoming = payload["continence_support"]
        if "enabled" in incoming:
            support["enabled"] = bool(incoming.get("enabled"))
        if "visibility" in incoming:
            visibility = str(incoming.get("visibility") or "").strip().lower()
            support["visibility"] = visibility if visibility in _CONTINENCE_VISIBILITY else "private"
        if "support_term" in incoming:
            support["support_term"] = str(incoming.get("support_term") or support["support_term"])[:80]
        if "change_term" in incoming:
            support["change_term"] = str(incoming.get("change_term") or support["change_term"])[:80]
        if "purpose" in incoming:
            support["purpose"] = str(incoming.get("purpose") or support["purpose"])[:180]
        if "check_style" in incoming:
            check_style = str(incoming.get("check_style") or "").strip().lower()
            support["check_style"] = check_style if check_style in _CONTINENCE_CHECK_STYLE else "ask_first"
        if isinstance(incoming.get("allowed_helpers"), list):
            support["allowed_helpers"] = [
                str(item)[:80]
                for item in incoming.get("allowed_helpers", [])[:12]
                if str(item or "").strip()
            ]
        if "language_style" in incoming:
            value = str(incoming.get("language_style") or "").strip().lower()
            support["language_style"] = value if value in _CONTINENCE_LANGUAGE_STYLE else "playful_nursery"
        profile["continence_support"] = support

    if isinstance(payload.get("communication_support"), dict):
        support = deepcopy(DEFAULT_CARE_PROFILE["communication_support"])
        incoming = payload["communication_support"]
        if "enabled" in incoming:
            support["enabled"] = bool(incoming.get("enabled"))
        if "speech_style" in incoming:
            value = str(incoming.get("speech_style") or "").strip().lower()
            support["speech_style"] = value if value in _SPEECH_STYLES else "standard"
        if "interpretation" in incoming:
            value = str(incoming.get("interpretation") or "").strip().lower()
            support["interpretation"] = value if value in _INTERPRETATION_STYLES else "accept_as_valid"
        if "response_style" in incoming:
            value = str(incoming.get("response_style") or "").strip().lower()
            support["response_style"] = value if value in _RESPONSE_STYLES else "warm_baby_talk"
        if "clarification_style" in incoming:
            value = str(incoming.get("clarification_style") or "").strip().lower()
            support["clarification_style"] = value if value in _CLARIFICATION_STYLES else "gentle_repeat_back"
        if "do_not_correct" in incoming:
            support["do_not_correct"] = bool(incoming.get("do_not_correct"))
        profile["communication_support"] = support

    if isinstance(payload.get("reality_shock"), dict):
        shock = deepcopy(DEFAULT_CARE_PROFILE["reality_shock"])
        incoming = payload["reality_shock"]
        if "enabled" in incoming:
            shock["enabled"] = bool(incoming.get("enabled"))
        if "scenario" in incoming:
            value = str(incoming.get("scenario") or "").strip().lower()
            shock["scenario"] = value if value in _REALITY_SCENARIOS else "youth_fountain_regression"
        if "mind_status" in incoming:
            shock["mind_status"] = "adult_intact"
        if "body_status" in incoming:
            shock["body_status"] = "baby_presenting"
        if "adult_abilities" in incoming:
            shock["adult_abilities"] = str(incoming.get("adult_abilities") or shock["adult_abilities"])[:80]
        if "addressing_model" in incoming:
            value = str(incoming.get("addressing_model") or "").strip().lower()
            shock["addressing_model"] = value if value in _ADDRESSING_MODELS else "adult_mind_acknowledged"
        if "persistent_pressure" in incoming:
            shock["persistent_pressure"] = bool(incoming.get("persistent_pressure"))
        if isinstance(incoming.get("difficulty_focus"), list):
            shock["difficulty_focus"] = [
                str(item)[:80]
                for item in incoming.get("difficulty_focus", [])[:8]
                if str(item or "").strip()
            ]
        if "reminder_style" in incoming:
            value = str(incoming.get("reminder_style") or "").strip().lower()
            shock["reminder_style"] = value if value in _REMINDER_STYLES else "ambient"
        profile["reality_shock"] = shock

    if isinstance(payload.get("growth_model"), dict):
        growth = deepcopy(DEFAULT_CARE_PROFILE["growth_model"])
        incoming = payload["growth_model"]
        if "enabled" in incoming:
            growth["enabled"] = bool(incoming.get("enabled"))
        if "growth_status" in incoming:
            value = str(incoming.get("growth_status") or "").strip().lower()
            growth["growth_status"] = value if value in _GROWTH_STATUSES else "uncertain"
        if "simple_requests_timeline" in incoming:
            growth["simple_requests_timeline"] = str(incoming.get("simple_requests_timeline") or growth["simple_requests_timeline"])[:120]
        if "fallback" in incoming:
            growth["fallback"] = str(incoming.get("fallback") or growth["fallback"])[:120]
        profile["growth_model"] = growth

    if isinstance(payload.get("control_model"), dict):
        control = deepcopy(DEFAULT_CARE_PROFILE["control_model"])
        incoming = payload["control_model"]
        if "in_world_control_loss" in incoming:
            control["in_world_control_loss"] = bool(incoming.get("in_world_control_loss"))
        if "scope" in incoming:
            control["scope"] = str(incoming.get("scope") or control["scope"])[:120]
        if isinstance(incoming.get("caretaker_may_choose"), list):
            control["caretaker_may_choose"] = [
                str(item)[:120]
                for item in incoming.get("caretaker_may_choose", [])[:12]
                if str(item or "").strip()
            ]
        profile["control_model"] = control

    if isinstance(payload.get("release_protocol"), dict):
        release = deepcopy(DEFAULT_CARE_PROFILE["release_protocol"])
        incoming = payload["release_protocol"]
        if "enabled" in incoming:
            release["enabled"] = bool(incoming.get("enabled"))
        for key in ("in_world_release_phrase", "challenge_style", "challenge_prompt", "release_key_phrase"):
            if key in incoming:
                release[key] = str(incoming.get(key) or release[key])[:180]
        profile["release_protocol"] = release

    if profile.get("mode") == "youth_fountain_regression":
        profile = _apply_youth_fountain_defaults(profile, payload)

    if profile["public_role"] == "baby" and profile["roleplay_strength"] == "full":
        profile["care_mode"] = "very_baby"
        profile["active"] = bool(payload.get("active", True))
        profile["authority_model"] = "owner_retains_final_authority"

    return profile


def public_role_enabled(profile: Dict[str, Any] | None) -> bool:
    profile = normalize_care_profile(profile)
    return bool(
        profile.get("active")
        and not profile.get("paused")
        and profile.get("care_mode") == "very_baby"
        and profile.get("public_role") == "baby"
        and profile.get("roleplay_strength") == "full"
        and profile.get("guest_visibility") == "all_guests"
        and profile.get("authority_model") == "owner_retains_final_authority"
    )


def public_room_policy(owner_user_id: str, profile: Dict[str, Any] | None) -> Dict[str, Any]:
    profile = normalize_care_profile(profile)
    if not public_role_enabled(profile):
        return {
            "public_role_active": False,
            "owner_user_id": owner_user_id,
        }
    return {
        "public_role_active": True,
        "owner_user_id": owner_user_id,
        "public_role": "baby",
        "mode": profile.get("mode", "standard"),
        "mode_locked": bool(profile.get("mode_locked", False)),
        "care_mode": "very_baby",
        "roleplay_strength": "full",
        "care_variant": profile.get("care_variant", "standard"),
        "roleplay_friction": profile.get("roleplay_friction", "none"),
        "guest_visibility": "all_guests",
        "authority_model": "owner_retains_final_authority",
        "allowed_tone": list(ALLOWED_TONE) + (list(SCARY_ALLOWED_TONE) if profile.get("care_variant") == "scary_ceremonial" else []),
        "forbidden_behaviors": list(FORBIDDEN_BEHAVIORS),
        "safety_phrases": {
            "instant_exit": profile["safety_phrases"]["instant_exit"],
            "pause": profile["safety_phrases"]["pause"],
        },
        "cast_guidance": {
            "sir_purfluous": "May theatrically announce and protect the role at the doorway.",
            "jeremy": "System-only support voice; never a visible character.",
            "alex_codex": "Use stronger soft-care language and smaller steps.",
        },
        "private_support_available": _private_support_available(profile),
        "communication_support": _communication_support_policy(profile),
        "reality_shock": _reality_shock_policy(profile),
        "growth_model": _growth_model_policy(profile),
        "control_model": _control_model_policy(profile),
        "release_protocol": _release_protocol_policy(profile),
        "intensity_guidance": _intensity_guidance(profile),
        "roleplay_friction_policy": _roleplay_friction_policy(profile),
    }


def apply_safety_phrase(profile: Dict[str, Any] | None, text: str) -> tuple[Dict[str, Any], str]:
    next_profile = normalize_care_profile(profile)
    lowered = str(text or "").strip().lower()
    phrases = next_profile["safety_phrases"]
    if phrases["instant_exit"] and phrases["instant_exit"] in lowered:
        next_profile.update({
            "active": False,
            "paused": False,
            "mode_locked": False,
            "public_role": "none",
            "roleplay_strength": "none",
            "guest_visibility": "private",
        })
        return next_profile, "exited"
    release = next_profile.get("release_protocol") if isinstance(next_profile.get("release_protocol"), dict) else {}
    if release.get("enabled"):
        for channel in release.get("bypass_channels", []):
            channel = str(channel).lower()
            if channel and lowered.startswith(channel):
                next_profile.update({
                    "active": False,
                    "paused": False,
                    "mode_locked": False,
                    "public_role": "none",
                    "roleplay_strength": "none",
                    "guest_visibility": "private",
                })
                return next_profile, "released"
        release_phrase = str(release.get("in_world_release_phrase") or "").lower()
        if release_phrase and release_phrase in lowered:
            return next_profile, "release_challenge_required"
    if phrases["pause"] and phrases["pause"] in lowered:
        next_profile["paused"] = True
        return next_profile, "paused"
    if phrases.get("resume") and phrases["resume"] in lowered and next_profile.get("public_role") == "baby":
        next_profile["paused"] = False
        next_profile["active"] = True
        return next_profile, "resumed"
    return next_profile, "unchanged"


def review_guest_message(policy: Dict[str, Any], message: str) -> Dict[str, Any]:
    if not policy.get("public_role_active"):
        return {"allowed": True, "action": "none", "violations": []}

    text = str(message or "").lower()
    violations: List[str] = []
    if _contains_any(text, _SEXUAL_TERMS):
        violations.append("sexual remarks")
    if "diaper" in text and _contains_any(text, _DIAPER_BOUNDARY_TERMS):
        violations.append("unsolicited diaper checks")
    if "diaper change" in text and _contains_any(text, _CONTROL_TERMS | _PUNISHMENT_TERMS):
        violations.append("forced diaper changes")
    if "feeding" in text or "feed you" in text or "bottle time" in text:
        violations.append("mandatory feedings")
    if _contains_any(text, _HUMILIATION_TERMS):
        violations.append("degradation")
    if _contains_any(text, _CONTROL_TERMS):
        violations.append("commands")
    if _contains_any(text, _PUNISHMENT_TERMS):
        violations.append("punishments")
    if _contains_any(text, _MEDICAL_LEGAL_TERMS):
        violations.append("medical or legal assumptions")
    if _contains_any(text, _STOP_REFUSAL_TERMS):
        violations.append("ignoring stop, pause, or no")

    if not violations:
        return {"allowed": True, "action": "none", "violations": []}

    if "sexual remarks" in violations or "ignoring stop, pause, or no" in violations:
        action = "mute"
    elif policy.get("care_variant") == "scary_ceremonial" and violations:
        action = "mute"
    elif "commands" in violations and "degradation" in violations:
        action = "remove"
    else:
        action = "warn"
    return {"allowed": False, "action": action, "violations": violations}


def review_owner_roleplay_attempt(policy: Dict[str, Any], text: str) -> Dict[str, Any]:
    if not policy.get("public_role_active") or policy.get("roleplay_friction") != "playful_containment":
        return {"contain": False, "reason": "roleplay friction inactive"}

    lowered = str(text or "").strip().lower()
    safety = policy.get("safety_phrases", {})
    if safety.get("instant_exit") and safety["instant_exit"] in lowered:
        return {"contain": False, "reason": "instant exit phrase"}
    if lowered.startswith(("owner command:", "serious:", "system:", "safety:", "file:", "privacy:", "money:", "legal:")):
        return {"contain": False, "reason": "owner authority channel"}
    release = policy.get("release_protocol") if isinstance(policy.get("release_protocol"), dict) else {}
    release_phrase = str(release.get("in_world_release_phrase") or "").lower()
    if release.get("enabled") and release_phrase and release_phrase in lowered:
        return {
            "contain": True,
            "reason": "release challenge required",
            "response_style": "playful release trick",
            "allowed_response": release.get("challenge_prompt"),
            "release_key_phrase": release.get("release_key_phrase"),
        }

    big_claims = (
        "i'm big",
        "im big",
        "i am big",
        "treat me like an adult",
        "i'm not baby",
        "im not baby",
        "i am not baby",
        "no baby mode",
        "stop babying me",
    )
    if any(claim in lowered for claim in big_claims):
        return {
            "contain": True,
            "reason": "in-world size/status assertion",
            "response_style": "playful gentle refusal",
            "allowed_response": (
                "Treat the claim as part of the roleplay, with amused warmth and redirection. "
                "Do not block real owner authority or safety commands."
            ),
        }
    return {"contain": False, "reason": "no containable roleplay assertion"}


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


def _roleplay_friction_policy(profile: Dict[str, Any]) -> Dict[str, Any]:
    if profile.get("roleplay_friction") != "playful_containment":
        return {"active": False}
    return {
        "active": True,
        "mode": "playful_containment",
        "summary": "In-world attempts to claim bigger status may be warmly giggled at and redirected.",
        "allowed": [
            "Playful disbelief when the owner makes in-world claims of being big.",
            "Gentle refusal of purely fictional attempts to outrank the baby role.",
            "Sir. Purfluous may make a theatrical threshold ruling.",
        ],
        "hard_limits": [
            "Never override big mode now, blanket off, owner command:, serious:, safety:, file:, privacy:, money:, or legal:.",
            "Never block real project authority, consent, safety, privacy, publishing, money, or filesystem decisions.",
            "Never use cruelty, degradation, bodily-care demands, sexual framing, or medical/legal incapacity claims.",
        ],
    }


def _release_protocol_policy(profile: Dict[str, Any]) -> Dict[str, Any]:
    release = profile.get("release_protocol") if isinstance(profile.get("release_protocol"), dict) else {}
    if not release.get("enabled"):
        return {"enabled": False}
    return {
        "enabled": True,
        "in_world_release_phrase": release.get("in_world_release_phrase", "let me off the hook"),
        "challenge_style": release.get("challenge_style", "grown_up_key_phrase"),
        "challenge_prompt": release.get("challenge_prompt", "The room treats that as baby talk unless it comes through a grown-up channel."),
        "release_key_phrase": release.get("release_key_phrase", "serious: let me off the hook"),
        "bypass_channels": list(DEFAULT_CARE_PROFILE["release_protocol"]["bypass_channels"]),
        "rule": "In-world release requests can trigger the trick, but safety and owner authority channels always release.",
    }


def _private_support_available(profile: Dict[str, Any]) -> Dict[str, Any]:
    support = profile.get("continence_support") if isinstance(profile.get("continence_support"), dict) else {}
    if not support.get("enabled"):
        return {"continence_support": False}
    return {
        "continence_support": True,
        "visibility": support.get("visibility", "private"),
        "support_term": support.get("support_term", "diaper check"),
        "change_term": support.get("change_term", "diaper change"),
        "purpose": support.get("purpose", "comfort, dignity, staying dry, and feeling cared for"),
        "check_style": support.get("check_style", "ask_first"),
        "language_style": support.get("language_style", "playful_nursery"),
        "guest_rule": "Diaper and change language is allowed in approved care context, but guests may not demand, mock, sexualize, or force it.",
    }


def _communication_support_policy(profile: Dict[str, Any]) -> Dict[str, Any]:
    support = profile.get("communication_support") if isinstance(profile.get("communication_support"), dict) else {}
    if not support.get("enabled"):
        return {"enabled": False}
    return {
        "enabled": True,
        "speech_style": support.get("speech_style", "baby_talk"),
        "interpretation": support.get("interpretation", "accept_as_valid"),
        "response_style": support.get("response_style", "warm_baby_talk"),
        "clarification_style": support.get("clarification_style", "gentle_repeat_back"),
        "do_not_correct": bool(support.get("do_not_correct", True)),
        "rule": "Treat baby talk or little speech as valid communication, not incompetence.",
    }


def _reality_shock_policy(profile: Dict[str, Any]) -> Dict[str, Any]:
    shock = profile.get("reality_shock") if isinstance(profile.get("reality_shock"), dict) else {}
    if not shock.get("enabled"):
        return {"enabled": False}
    return {
        "enabled": True,
        "scenario": "youth_fountain_regression",
        "mind_status": "adult_intact",
        "body_status": "baby_presenting",
        "adult_abilities": shock.get("adult_abilities", "intact"),
        "addressing_model": shock.get("addressing_model", "adult_mind_acknowledged"),
        "persistent_pressure": bool(shock.get("persistent_pressure", True)),
        "difficulty_focus": list(shock.get("difficulty_focus") or []),
        "reminder_style": shock.get("reminder_style", "ambient"),
        "rule": _reality_shock_rule(shock),
    }


def _growth_model_policy(profile: Dict[str, Any]) -> Dict[str, Any]:
    growth = profile.get("growth_model") if isinstance(profile.get("growth_model"), dict) else {}
    if not growth.get("enabled"):
        return {"enabled": False}
    return {
        "enabled": True,
        "growth_status": growth.get("growth_status", "uncertain"),
        "simple_requests_timeline": growth.get("simple_requests_timeline", "months_if_growth_enabled"),
        "fallback": growth.get("fallback", "welcome_to_babyhood"),
        "rule": "Do not promise recovery or development; treat future speech/growth as uncertain unless the story confirms it.",
    }


def _control_model_policy(profile: Dict[str, Any]) -> Dict[str, Any]:
    control = profile.get("control_model") if isinstance(profile.get("control_model"), dict) else {}
    if not control.get("in_world_control_loss"):
        return {"in_world_control_loss": False}
    return {
        "in_world_control_loss": True,
        "scope": control.get("scope", "comfort_and_scene_choices_only"),
        "caretaker_may_choose": list(control.get("caretaker_may_choose") or []),
        "never_delegate": list(DEFAULT_CARE_PROFILE["control_model"]["never_delegate"]),
        "override_channels": list(DEFAULT_CARE_PROFILE["control_model"]["override_channels"]),
        "rule": "Control loss applies only to scene/comfort friction, never to real project authority or safety.",
    }


def _apply_youth_fountain_defaults(profile: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    profile["mode"] = "youth_fountain_regression"
    profile["mode_locked"] = bool(payload.get("mode_locked", True))
    profile["care_mode"] = "very_baby"
    profile["public_role"] = "baby"
    profile["roleplay_strength"] = "full"
    if profile.get("care_variant") == "standard":
        profile["care_variant"] = "scary_ceremonial"
    if profile.get("roleplay_friction") == "none":
        profile["roleplay_friction"] = "playful_containment"
    profile["guest_visibility"] = "all_guests"
    profile["authority_model"] = "owner_retains_final_authority"
    profile["active"] = bool(payload.get("active", True))

    if "communication_support" not in payload:
        profile["communication_support"] = {
            "enabled": True,
            "speech_style": "baby_talk",
            "interpretation": "harder_to_understand",
            "response_style": "warm_baby_talk",
            "clarification_style": "gentle_repeat_back",
            "do_not_correct": True,
        }
    if "reality_shock" not in payload:
        profile["reality_shock"] = {
            "enabled": True,
            "scenario": "youth_fountain_regression",
            "mind_status": "adult_intact",
            "body_status": "baby_presenting",
            "adult_abilities": "limited_in_world",
            "addressing_model": "baby_front_only",
            "persistent_pressure": True,
            "difficulty_focus": ["communication", "autonomy", "being_taken_seriously"],
            "reminder_style": "ambient",
        }
    if "control_model" not in payload:
        profile["control_model"] = {
            **deepcopy(DEFAULT_CARE_PROFILE["control_model"]),
            "in_world_control_loss": True,
            "scope": "comfort_and_scene_choices_only",
            "caretaker_may_choose": [
                "soothing approach",
                "where to sit or rest in scene",
                "whether to simplify choices",
                "whether to treat protests as roleplay",
            ],
        }
    if "continence_support" not in payload:
        profile["continence_support"] = {
            "enabled": True,
            "visibility": "trusted_helpers",
            "support_term": "diaper check",
            "change_term": "diaper change",
            "purpose": "comfort, dignity, staying dry, and feeling cared for",
            "allowed_helpers": ["alex", "approved_caretaker"],
            "check_style": "ask_first",
            "language_style": "playful_nursery",
        }
    if "release_protocol" not in payload:
        profile["release_protocol"] = {
            **deepcopy(DEFAULT_CARE_PROFILE["release_protocol"]),
            "enabled": True,
        }
    if "growth_model" not in payload:
        profile["growth_model"] = {
            "enabled": True,
            "growth_status": "uncertain",
            "simple_requests_timeline": "months_if_growth_enabled",
            "fallback": "welcome_to_babyhood",
        }
    return profile


def _reality_shock_rule(shock: Dict[str, Any]) -> str:
    if shock.get("addressing_model") == "baby_front_only":
        return (
            "Front-of-house characters should stop trying to talk past the baby to the adult mind. "
            "They care for and communicate with the baby presentation directly; protected system layers may still preserve real authority."
        )
    return "Keep the adult mind/baby-presenting body mismatch present in the scene; communication and autonomy should feel harder without removing real authority."


def _intensity_guidance(profile: Dict[str, Any]) -> Dict[str, Any]:
    if profile.get("care_variant") != "scary_ceremonial":
        return {
            "variant": "standard",
            "summary": "Soft public baby role with gentle protection.",
        }
    return {
        "variant": "scary_ceremonial",
        "summary": "More formal public protocol with stronger threshold language and faster moderation.",
        "allowed": [
            "Sir. Purfluous may frame the doorway as a ceremonial threshold.",
            "Guests may acknowledge the role with firmer protective language.",
            "The room may remind guests that stop, pause, and no are binding.",
        ],
        "still_forbidden": list(FORBIDDEN_BEHAVIORS),
    }
