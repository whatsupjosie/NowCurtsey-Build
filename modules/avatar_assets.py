# PubCast AI — avatar_assets.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""modules/avatar_assets.py — GLB avatar asset manifest management."""
from __future__ import annotations
import json, time, logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("pubcast.avatar_assets")

class AssetPack(BaseModel):
    pack_id:     str
    name:        str
    description: str = ""
    assets:      List[Dict[str, Any]] = Field(default_factory=list)
    refreshed_at: float = Field(default_factory=time.time)

class AvatarManifest(BaseModel):
    packs:       List[AssetPack] = Field(default_factory=list)
    generated_at: float = Field(default_factory=time.time)

_manifest_cache: Optional[AvatarManifest] = None

def load_manifest(data_dir: Path) -> AvatarManifest:
    global _manifest_cache
    if _manifest_cache: return _manifest_cache
    manifest_path = Path(data_dir) / "avatars" / "manifest.json"
    if manifest_path.exists():
        try:
            _manifest_cache = AvatarManifest(**json.loads(manifest_path.read_text()))
            return _manifest_cache
        except Exception as exc:
            logger.warning("avatar_assets: corrupt manifest at %s, using defaults: %s", manifest_path, exc)
    # Default pack
    _manifest_cache = AvatarManifest(packs=[
        AssetPack(pack_id="default", name="Default Avatars",
                  description="Built-in holographic energy beings",
                  assets=[{"id": p, "name": p.title(), "type": "hologram"}
                          for p in ["MANNY","SHELA","MAN_LARGE","MAN_SMALL","CHILD","BABY","DOG","GHOST"]]),
        AssetPack(pack_id="pubcast_cast_v1", name="PubCast Cast — Staged v1",
                  description="Loadable staged cast assets for Pete, Re-Pete, and Sir Purfluous.",
                  assets=[
                      {"id": "PETE", "character_id": "pete", "name": "Pete", "type": "glb", "url": "/assets/avatar/cast/pete/pete_avatar_pubcast_v56.glb"},
                      {"id": "REPETE", "character_id": "repete", "name": "Re-Pete", "type": "glb", "url": "/assets/avatar/cast/repete/repete_v1.glb"},
                      {"id": "PURFLUOUS", "character_id": "purfluous", "name": "Sir Purfluous", "type": "glb", "url": "/assets/avatar/cast/purfluous/sir_purfluous_v1.glb"},
                  ])
    ])
    return _manifest_cache

def refresh_manifest_cache():
    global _manifest_cache
    _manifest_cache = None

__all__ = ["AssetPack", "AvatarManifest", "load_manifest", "refresh_manifest_cache"]
