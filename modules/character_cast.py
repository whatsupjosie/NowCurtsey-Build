# PubCast AI — character_cast.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""Staged cast registry for loadable avatar assets and AI shell readiness.

This module deliberately separates *character shell* integration from final-lock
avatar production. The cast can be registered, loaded, voiced, and staged now
while silhouette / face-performance / wardrobe polish continues.
"""
from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class CastCharacterSpec(BaseModel):
    character_id: str
    display_name: str
    aliases: List[str] = Field(default_factory=list)
    avatar_preset_id: str
    asset_url: str
    asset_path: str
    glb_file: str
    role: str
    idle_mode: str
    placeholder_avatar: str = ""
    voice_profile_id: str
    profile_id: str
    ai_ready: bool = False
    avatar_ready: bool = False
    final_lock: bool = False
    provisional: bool = True
    notes: List[str] = Field(default_factory=list)
    silhouette_notes: str = ""
    wardrobe_notes: str = ""


_CAST: Dict[str, CastCharacterSpec] = {
    "pete": CastCharacterSpec(
        character_id="pete",
        display_name="Pete",
        aliases=["pete", "bot-pete"],
        avatar_preset_id="PETE",
        asset_url="/assets/avatar/cast/pete/pete_avatar_pubcast_v56.glb",
        asset_path="assets/avatar/cast/pete/pete_avatar_pubcast_v56.glb",
        glb_file="pete_avatar_pubcast_v56.glb",
        role="Floor director / camera-floor authority",
        idle_mode="reading_clipboard",
        placeholder_avatar="SHELA",
        voice_profile_id="pete",
        profile_id="pete",
        ai_ready=True,
        avatar_ready=True,
        final_lock=False,
        provisional=True,
        notes=[
            "Strongest current build and best technical baseline.",
            "Needs canon parity cleanup and further face / expression elevation, not just freeze-as-is.",
        ],
        silhouette_notes="Grounded, competent, work-clothes authority. Carries the room without demanding it.",
        wardrobe_notes="Work clothes; ring on the middle finger; production-floor practicality over glam.",
    ),
    "repete": CastCharacterSpec(
        character_id="repete",
        display_name="Re-Pete",
        aliases=["repete", "repeat", "re_pete", "re-pete", "bot-re-pete"],
        avatar_preset_id="REPETE",
        asset_url="/assets/avatar/cast/repete/repete_v1.glb",
        asset_path="assets/avatar/cast/repete/repete_v1.glb",
        glb_file="repete_v1.glb",
        role="Production apprentice / intern / digital helper",
        idle_mode="phone_scroll_nervous",
        placeholder_avatar="MANNY",
        voice_profile_id="re_pete",
        profile_id="repeat",
        ai_ready=True,
        avatar_ready=True,
        final_lock=False,
        provisional=True,
        notes=[
            "Good rig foundation; still needs canon/age/readability tuning.",
            "Treat as staged cast asset, not final lock.",
        ],
        silhouette_notes="Young, slim, babyface, slightly tentative posture. Earnest more than polished.",
        wardrobe_notes="College-studenty practical wear; avoid aging him up or making him too slick.",
    ),
    "purfluous": CastCharacterSpec(
        character_id="purfluous",
        display_name="Sir Purfluous",
        aliases=["purfluous", "sir_purfluous", "sir-purfluous", "sir purfluous", "sir. purfluous", "bot-purfluous"],
        avatar_preset_id="PURFLUOUS",
        asset_url="/assets/avatar/cast/purfluous/sir_purfluous_v1.glb",
        asset_path="assets/avatar/cast/purfluous/sir_purfluous_v1.glb",
        glb_file="sir_purfluous_v1.glb",
        role="Theatrical commentator / director / elder statesman",
        idle_mode="seated_still_brilliance",
        placeholder_avatar="MANNY",
        voice_profile_id="sir_purfluous",
        profile_id="sir_purfluous",
        ai_ready=True,
        avatar_ready=True,
        final_lock=False,
        provisional=True,
        notes=[
            "Now staged into the system, but still needs the hardest canon-correction pass of the trio.",
            "Good for runtime shell integration; not yet the definitive visual lock.",
        ],
        silhouette_notes="Tall, lean, angular, theatrical, slightly ridiculous but still impressive.",
        wardrobe_notes="Burgundy velvet jacket, brass buttons, cream cravat with gold pin, silver hair.",
    ),
}

_ALIAS_TO_ID: Dict[str, str] = {}
for _cid, _spec in _CAST.items():
    _ALIAS_TO_ID[_cid] = _cid
    for _alias in _spec.aliases:
        _ALIAS_TO_ID[_alias.lower()] = _cid


def normalize_character_id(character_id: Optional[str]) -> str:
    key = (character_id or "").strip().lower()
    return _ALIAS_TO_ID.get(key, key)


def get_cast_character(character_id: str) -> Optional[CastCharacterSpec]:
    return _CAST.get(normalize_character_id(character_id))


def list_cast_characters() -> List[CastCharacterSpec]:
    return [_CAST[k] for k in ("pete", "repete", "purfluous")]


def list_cast_avatar_presets() -> List[dict]:
    presets: List[dict] = []
    for spec in list_cast_characters():
        glow = {
            "pete": "#6DD6C7",
            "repete": "#B4C8F8",
            "purfluous": "#C078E0",
        }.get(spec.character_id, "#00FFFF")
        presets.append({
            "id": spec.avatar_preset_id,
            "preset_id": spec.avatar_preset_id,
            "name": spec.display_name,
            "description": f"Staged cast avatar for {spec.display_name}",
            "glow_color": glow,
            "body_type": "character_glb",
            "height": 1.0,
            "emoji": "🎭",
            "silhouette": spec.character_id,
            "character_id": spec.character_id,
            "asset_kind": "glb",
            "glb_url": spec.asset_url,
            "idle_mode": spec.idle_mode,
            "voice_profile_id": spec.voice_profile_id,
            "profile_id": spec.profile_id,
            "staged": True,
            "provisional": spec.provisional,
            "final_lock": spec.final_lock,
            "ai_ready": spec.ai_ready,
            "avatar_ready": spec.avatar_ready,
        })
    return presets


__all__ = [
    "CastCharacterSpec",
    "get_cast_character",
    "list_cast_characters",
    "list_cast_avatar_presets",
    "normalize_character_id",
]
