# PubCast AI — surfaces.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""modules/surfaces.py — Placeable media surfaces in PubWorld rooms."""
from __future__ import annotations
import time, uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class Surface(BaseModel):
    surface_id:  str
    room_id:     str
    label:       str
    kind:        str = "custom"
    quad:        List[List[float]] = Field(default_factory=list)
    creator_id:  Optional[str] = None
    media_mode:  str = "video"
    locked:      bool = False
    expires_at:  Optional[float] = None
    stream_id:   Optional[str] = None
    stream_uri:  Optional[str] = None
    metadata:    Dict[str, Any] = Field(default_factory=dict)
    created_at:  float = Field(default_factory=time.time)
    updated_at:  float = Field(default_factory=time.time)

class SurfaceManager:
    def __init__(self, data_dir): self._surfaces: Dict[str, Surface] = {}
    async def list_surfaces(self, room_id=None):
        s = list(self._surfaces.values())
        return [x for x in s if x.room_id == room_id] if room_id else s
    async def create_surface(self, room_id, label, kind="custom", quad=None,
                             creator_id=None, media_mode="video", locked=False,
                             expires_at=None, metadata=None):
        s = Surface(surface_id=str(uuid.uuid4()), room_id=room_id, label=label,
                    kind=kind, quad=quad or [], creator_id=creator_id,
                    media_mode=media_mode, locked=locked, expires_at=expires_at,
                    metadata=metadata or {})
        self._surfaces[s.surface_id] = s; return s
    async def get_surface(self, sid): return self._surfaces.get(sid)
    async def bind_stream(self, sid, stream_id=None, stream_uri=None, metadata=None):
        s = self._surfaces[sid]
        s.stream_id = stream_id; s.stream_uri = stream_uri
        if metadata: s.metadata.update(metadata)
        s.updated_at = time.time(); return s
    async def update_surface_state(self, sid, changes):
        s = self._surfaces.get(sid)
        if not s: raise KeyError(sid)
        for k, v in (changes or {}).items():
            if hasattr(s, k): setattr(s, k, v)
        s.updated_at = time.time(); return s
    async def delete_surface(self, sid): self._surfaces.pop(sid, None)

__all__ = ["Surface", "SurfaceManager"]
