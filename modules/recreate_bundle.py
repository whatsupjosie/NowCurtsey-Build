# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley) · Rear View Foresight LLC · Feic Mo Chroí™
"""PubCast recreate bundle contract.

This module defines the minimum JSON-compatible shape needed to recreate a
session later. It intentionally stays standard-library only so recording,
export, timeline, and director-console code can share the contract without
pulling in runtime dependencies.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _now() -> float:
    return time.time()


@dataclass
class TimedEvent:
    """A timestamped event for camera, lighting, mocap, chat, warning, or AI logs."""

    event_type: str
    timestamp: float = field(default_factory=_now)
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        timestamp = float(self.timestamp)
        return {
            "event_type": self.event_type,
            "timestamp": timestamp,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimedEvent":
        if not data.get("event_type"):
            raise ValueError("TimedEvent.event_type is required")
        return cls(
            event_type=str(data["event_type"]),
            timestamp=float(data.get("timestamp", _now())),
            payload=dict(data.get("payload") or {}),
        )


@dataclass
class AvatarRigRef:
    """3D performer identity and rig/skeleton version."""

    avatar_id: str
    display_name: str
    asset_uri: str
    rig_version: str
    skeleton_version: str
    asset_type: str = "glb"
    performer_asset: bool = True
    production_avatar: bool = True
    sprite_replacement_allowed: bool = False
    animation_status: str = "unknown"
    fallback_policy: str = "visible error if unavailable"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "avatar_id": self.avatar_id,
            "display_name": self.display_name,
            "asset_uri": self.asset_uri,
            "rig_version": self.rig_version,
            "skeleton_version": self.skeleton_version,
            "asset_type": self.asset_type,
            "performer_asset": self.performer_asset,
            "production_avatar": self.production_avatar,
            "sprite_replacement_allowed": self.sprite_replacement_allowed,
            "animation_status": self.animation_status,
            "fallback_policy": self.fallback_policy,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AvatarRigRef":
        required = ("avatar_id", "display_name", "asset_uri", "rig_version", "skeleton_version")
        missing = [key for key in required if not data.get(key)]
        if missing:
            raise ValueError(f"AvatarRigRef missing required fields: {', '.join(missing)}")
        return cls(
            avatar_id=str(data["avatar_id"]),
            display_name=str(data["display_name"]),
            asset_uri=str(data["asset_uri"]),
            rig_version=str(data["rig_version"]),
            skeleton_version=str(data["skeleton_version"]),
            asset_type=str(data.get("asset_type") or "glb"),
            performer_asset=bool(data.get("performer_asset", True)),
            production_avatar=bool(data.get("production_avatar", True)),
            sprite_replacement_allowed=bool(data.get("sprite_replacement_allowed", False)),
            animation_status=str(data.get("animation_status") or "unknown"),
            fallback_policy=str(data.get("fallback_policy") or "visible error if unavailable"),
        )


@dataclass
class RecreateBundle:
    """Minimum PubCast recreate/export metadata bundle."""

    session_id: str
    project_id: str
    scene_id: str
    take_id: str
    final_program_ref: Optional[str] = None
    stage_environment_version: str = "unknown"
    camera_timeline: List[TimedEvent] = field(default_factory=list)
    mocap_events: List[TimedEvent] = field(default_factory=list)
    avatars: List[AvatarRigRef] = field(default_factory=list)
    lighting_events: List[TimedEvent] = field(default_factory=list)
    audio_refs: List[Dict[str, Any]] = field(default_factory=list)
    chat_log: List[TimedEvent] = field(default_factory=list)
    ai_participation_log: List[TimedEvent] = field(default_factory=list)
    system_warnings: List[TimedEvent] = field(default_factory=list)
    export_status: str = "not_started"
    recreate_readiness: str = "metadata_incomplete"

    def add_camera_event(self, event_type: str, **payload: Any) -> None:
        if event_type in {"preview", "program", "cut", "fade"}:
            if "to_camera" not in payload and "to" not in payload:
                raise ValueError("camera events require to_camera or to")
            payload.setdefault("source", "director_switcher")
        self.camera_timeline.append(TimedEvent(event_type=event_type, payload=payload))

    def add_warning(self, event_type: str, **payload: Any) -> None:
        self.system_warnings.append(TimedEvent(event_type=event_type, payload=payload))

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "session_id": self.session_id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "take_id": self.take_id,
            "final_program_ref": self.final_program_ref,
            "camera_timeline": [event.to_dict() for event in self.camera_timeline],
            "mocap_events": [event.to_dict() for event in self.mocap_events],
            "avatars": [avatar.to_dict() for avatar in self.avatars],
            "stage_environment_version": self.stage_environment_version,
            "lighting_events": [event.to_dict() for event in self.lighting_events],
            "audio_refs": list(self.audio_refs),
            "chat_log": [event.to_dict() for event in self.chat_log],
            "ai_participation_log": [event.to_dict() for event in self.ai_participation_log],
            "system_warnings": [event.to_dict() for event in self.system_warnings],
            "export_status": self.export_status,
            "recreate_readiness": self.recreate_readiness,
        }

    def validate(self) -> None:
        required = {
            "session_id": self.session_id,
            "project_id": self.project_id,
            "scene_id": self.scene_id,
            "take_id": self.take_id,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(f"RecreateBundle missing required fields: {', '.join(missing)}")
        for event in self.camera_timeline:
            event.to_dict()
        for event in self.mocap_events:
            event.to_dict()
        for avatar in self.avatars:
            avatar.to_dict()

    def readiness_reasons(self) -> List[str]:
        reasons: List[str] = []
        if not self.final_program_ref:
            reasons.append("missing final program video/export reference")
        if not self.camera_timeline:
            reasons.append("missing camera timeline")
        if not self.avatars:
            reasons.append("missing avatar rig references")
        if not self.audio_refs:
            reasons.append("missing audio references or captured-audio metadata")
        if self.stage_environment_version == "unknown":
            reasons.append("missing stage/environment version")
        if not self.mocap_events:
            reasons.append("missing mocap stream reference or explicit unavailable event")
        return reasons

    def update_readiness(self) -> str:
        reasons = self.readiness_reasons()
        self.recreate_readiness = "ready" if not reasons else "not_ready: " + "; ".join(reasons)
        return self.recreate_readiness

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecreateBundle":
        bundle = cls(
            session_id=str(data.get("session_id") or ""),
            project_id=str(data.get("project_id") or ""),
            scene_id=str(data.get("scene_id") or ""),
            take_id=str(data.get("take_id") or ""),
            final_program_ref=data.get("final_program_ref"),
            stage_environment_version=str(data.get("stage_environment_version") or "unknown"),
            camera_timeline=[TimedEvent.from_dict(e) for e in data.get("camera_timeline", [])],
            mocap_events=[TimedEvent.from_dict(e) for e in data.get("mocap_events", [])],
            avatars=[AvatarRigRef.from_dict(a) for a in data.get("avatars", [])],
            lighting_events=[TimedEvent.from_dict(e) for e in data.get("lighting_events", [])],
            audio_refs=list(data.get("audio_refs") or []),
            chat_log=[TimedEvent.from_dict(e) for e in data.get("chat_log", [])],
            ai_participation_log=[TimedEvent.from_dict(e) for e in data.get("ai_participation_log", [])],
            system_warnings=[TimedEvent.from_dict(e) for e in data.get("system_warnings", [])],
            export_status=str(data.get("export_status") or "not_started"),
            recreate_readiness=str(data.get("recreate_readiness") or "metadata_incomplete"),
        )
        bundle.validate()
        return bundle


def blank_bundle(
    *,
    session_id: str,
    project_id: str,
    scene_id: str,
    take_id: str,
) -> RecreateBundle:
    """Create an empty recreate bundle with required identity fields."""

    return RecreateBundle(
        session_id=session_id,
        project_id=project_id,
        scene_id=scene_id,
        take_id=take_id,
    )
