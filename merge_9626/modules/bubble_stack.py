# PubCast AI — bubble_stack.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rear View Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
PubCast Bubble Stack route-facing adapter with optional PIKPC v1.6 runtime.

This module preserves the safe v0.1 PubCast-facing API while promoting the
included Bubble Stack PIKPC v1.6 engine behind that adapter when available.
It does not replace Jeremy, Room Conductor, Session Runtime, e-PETE, memory,
recording, or camera systems.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict, is_dataclass
from enum import Enum
import logging
from enum import Enum as _EnumBase
from math import dist
from time import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

Vector3 = Tuple[float, float, float]
logger = logging.getLogger("pubcast.bubble_stack")

BUBBLE_STAT_SCHEMA: Dict[str, str] = {
    "room_id": "str",
    "state": "UNCONFIGURED|CONFIGURED|SLEEPING|ACTIVE|AI_BLIND",
    "ai_present": "bool",
    "bubble_count": "int",
    "active_bubble_count": "int",
    "actors_seen": "list[str]",
    "postures": "dict[str,str]",
    "nearby": "dict[str,list[str]]",
    "meaningful_events": "list[dict]",
    "generated_at": "float",
    "engine_version": "str",
    "engine_summary": "dict",
}


try:  # Optional mature runtime, kept behind this adapter.
    from .bubble_stack_pikpc import (
        AABB as PIKPCAABB,
        BubbleConfig as PIKPCBubbleConfig,
        BubbleStackEngine as PIKPCBubbleStackEngine,
        FrameObject as PIKPCFrameObject,
        Vec3 as PIKPCVec3,
    )
    _HAS_PIKPC_V1_6 = True
except Exception as exc:  # pragma: no cover - safety fallback
    PIKPCAABB = None  # type: ignore[assignment]
    PIKPCBubbleConfig = None  # type: ignore[assignment]
    PIKPCBubbleStackEngine = None  # type: ignore[assignment]
    PIKPCFrameObject = None  # type: ignore[assignment]
    PIKPCVec3 = None  # type: ignore[assignment]
    _HAS_PIKPC_V1_6 = False
    logger.info("Bubble Stack PIKPC v1.6 unavailable; using safe v0.1 runtime: %s", exc)


class BubbleStackState(str, Enum):
    UNCONFIGURED = "UNCONFIGURED"
    CONFIGURED = "CONFIGURED"
    SLEEPING = "SLEEPING"
    ACTIVE = "ACTIVE"
    AI_BLIND = "AI_BLIND"
    # Backward-compatible alias for the v0.1 source name.
    BLIND = "AI_BLIND"


@dataclass(frozen=True)
class BubbleGridConfig:
    room_id: str
    origin: Vector3 = (0.0, 0.0, 0.0)
    dimensions: Vector3 = (10.0, 3.0, 10.0)
    radius: float = 1.0
    spacing: float = 1.0

    def validate(self) -> None:
        if not self.room_id:
            raise ValueError("room_id is required")
        if self.radius <= 0 or self.spacing <= 0:
            raise ValueError("radius and spacing must be positive")
        if any(v <= 0 for v in self.dimensions):
            raise ValueError("dimensions must be positive")


@dataclass
class BonePresence:
    actor_id: str
    bone_name: str
    position: Vector3
    velocity: Vector3 = (0.0, 0.0, 0.0)
    confidence: float = 1.0
    timestamp: float = field(default_factory=time)


@dataclass
class ObjectPresence:
    object_id: str
    kind: str
    position: Vector3
    velocity: Vector3 = (0.0, 0.0, 0.0)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time)


@dataclass
class Bubble:
    bubble_id: str
    center: Vector3
    radius: float
    bones: Dict[str, BonePresence] = field(default_factory=dict)
    objects: Dict[str, ObjectPresence] = field(default_factory=dict)
    updated_at: float = field(default_factory=time)

    def contains(self, position: Vector3) -> bool:
        return dist(self.center, position) <= self.radius

    def clear(self) -> None:
        self.bones.clear()
        self.objects.clear()
        self.updated_at = time()

    def add_bone(self, bone: BonePresence) -> None:
        self.bones[f"{bone.actor_id}:{bone.bone_name}"] = bone
        self.updated_at = time()

    def add_object(self, obj: ObjectPresence) -> None:
        self.objects[obj.object_id] = obj
        self.updated_at = time()


@dataclass
class BubbleStat:
    room_id: str
    state: BubbleStackState
    ai_present: bool
    bubble_count: int
    active_bubble_count: int
    actors_seen: List[str]
    postures: Dict[str, str]
    nearby: Dict[str, List[str]]
    meaningful_events: List[Dict[str, Any]]
    generated_at: float = field(default_factory=time)
    engine_version: str = "v0.1"
    engine_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


def serialize_bubble_stat(stat: Any) -> Dict[str, Any]:
    """Return a stable BubbleStat-shaped dict for routes, Jeremy, and future runtime consumers.

    This adapter is intentionally small. It does not alter the engine; it only
    normalizes dataclasses/enums/fallback dicts into the public PubCast schema.
    """
    if hasattr(stat, "to_dict") and callable(getattr(stat, "to_dict")):
        data = stat.to_dict()
    elif isinstance(stat, dict):
        data = dict(stat)
    else:
        data = _json_safe(stat)
        if not isinstance(data, dict):
            data = {"state": "AI_BLIND", "meaningful_events": [{"type": "invalid_bubble_stat"}]}

    defaults = {
        "room_id": data.get("room_id", "unknown"),
        "state": data.get("state", "AI_BLIND"),
        "ai_present": bool(data.get("ai_present", False)),
        "bubble_count": int(data.get("bubble_count", 0) or 0),
        "active_bubble_count": int(data.get("active_bubble_count", 0) or 0),
        "actors_seen": list(data.get("actors_seen") or []),
        "postures": dict(data.get("postures") or {}),
        "nearby": dict(data.get("nearby") or {}),
        "meaningful_events": list(data.get("meaningful_events") or []),
        "generated_at": data.get("generated_at", time()),
        "engine_version": data.get("engine_version", "v0.1-safe"),
        "engine_summary": dict(data.get("engine_summary") or {}),
    }
    return _json_safe(defaults)


class BubbleStack:
    """Room-local PubCast Bubble Stack with optional PIKPC v1.6 promotion.

    Public/runtime state remains PubCast-shaped:
    - UNCONFIGURED means no room geometry exists.
    - CONFIGURED means geometry exists but no AI has entered yet.
    - SLEEPING means geometry exists and no AI is present.
    - ACTIVE means AI is present and Bubble Stat updates matter.
    - AI_BLIND means AI spatial awareness cannot be trusted for the room.

    PIKPC v1.6 is active only behind this adapter. If it fails, the v0.1
    runtime continues safely.
    """

    def __init__(self, config: Optional[BubbleGridConfig] = None):
        self.config = config
        self.state = BubbleStackState.UNCONFIGURED
        self.bubbles: Dict[str, Bubble] = {}
        self.ai_actor_ids: set[str] = set()
        self.actor_postures: Dict[str, str] = {}
        self._last_actor_bubbles: Dict[str, set[str]] = {}
        self._events: List[Dict[str, Any]] = []
        self._pikpc_engine: Optional[Any] = None
        self._pikpc_frame_objects: Dict[str, Any] = {}
        self._pikpc_last_summary: Dict[str, Any] = {}
        self._pikpc_error: Optional[str] = None
        if config:
            self.configure(config)

    @property
    def room_id(self) -> str:
        return self.config.room_id if self.config else "unconfigured"

    @property
    def pikpc_active(self) -> bool:
        return self._pikpc_engine is not None and self._pikpc_error is None

    @property
    def engine_version(self) -> str:
        return "v1.6-pikpc" if self.pikpc_active else "v0.1-safe"

    def configure(self, config: BubbleGridConfig) -> None:
        config.validate()
        self.config = config
        self.bubbles = self._generate_grid(config)
        self.state = BubbleStackState.CONFIGURED
        self._events.append({"type": "bubble_stack_configured", "room_id": config.room_id, "at": time()})
        self._init_pikpc_engine(config)

    def set_ai_presence(self, actor_ids: Iterable[str]) -> None:
        self.ai_actor_ids = set(actor_ids)
        if self.state == BubbleStackState.UNCONFIGURED:
            return
        self.state = BubbleStackState.ACTIVE if self.ai_actor_ids else BubbleStackState.SLEEPING
        if self.state == BubbleStackState.ACTIVE:
            self._step_pikpc_if_active(reason="ai_presence_active")

    def ingest_skeleton_frame(self, actor_id: str, bones: Iterable[BonePresence], posture: Optional[str] = None) -> None:
        if self.state == BubbleStackState.UNCONFIGURED:
            self._events.append({"type": "ai_blind_or_room_unconfigured", "actor_id": actor_id, "at": time()})
            return
        if posture:
            self.actor_postures[actor_id] = posture
        # Remove actor's old bone entries before placing current frame.
        for bubble in self.bubbles.values():
            for key in list(bubble.bones.keys()):
                if key.startswith(f"{actor_id}:"):
                    del bubble.bones[key]
        actor_bubbles: set[str] = set()
        bone_list = list(bones)
        for bone in bone_list:
            for bubble in self._candidate_bubbles(bone.position):
                if bubble.contains(bone.position):
                    bubble.add_bone(bone)
                    actor_bubbles.add(bubble.bubble_id)
        previous = self._last_actor_bubbles.get(actor_id, set())
        entered = actor_bubbles - previous
        exited = previous - actor_bubbles
        if entered or exited:
            self._events.append({
                "type": "actor_bubble_transition",
                "actor_id": actor_id,
                "entered": sorted(entered),
                "exited": sorted(exited),
                "at": time(),
            })
        self._last_actor_bubbles[actor_id] = actor_bubbles
        self._update_pikpc_actor_bones(actor_id, bone_list)
        self._step_pikpc_if_active(reason="skeleton_frame")

    def ingest_object(self, obj: ObjectPresence) -> None:
        if self.state == BubbleStackState.UNCONFIGURED:
            return
        for bubble in self.bubbles.values():
            bubble.objects.pop(obj.object_id, None)
        for bubble in self._candidate_bubbles(obj.position):
            if bubble.contains(obj.position):
                bubble.add_object(obj)
        self._update_pikpc_object(obj)
        self._step_pikpc_if_active(reason="object_frame")

    def build_stat(self) -> BubbleStat:
        if self.state == BubbleStackState.UNCONFIGURED:
            return BubbleStat(
                room_id=self.room_id,
                state=BubbleStackState.AI_BLIND,
                ai_present=False,
                bubble_count=0,
                active_bubble_count=0,
                actors_seen=[],
                postures={},
                nearby={},
                meaningful_events=self._drain_events(),
                engine_version=self.engine_version,
                engine_summary={},
            )
        active = [b for b in self.bubbles.values() if b.bones or b.objects]
        actors = sorted({bone.actor_id for bubble in active for bone in bubble.bones.values()})
        nearby = self._build_nearby(active)
        engine_summary = self.get_engine_summary()
        return BubbleStat(
            room_id=self.room_id,
            state=self.state,
            ai_present=bool(self.ai_actor_ids),
            bubble_count=len(self.bubbles),
            active_bubble_count=len(active),
            actors_seen=actors,
            postures={k: self.actor_postures[k] for k in actors if k in self.actor_postures},
            nearby=nearby,
            meaningful_events=self._drain_events(),
            engine_version=self.engine_version,
            engine_summary=engine_summary,
        )

    def build_ai_context(
        self,
        active_conversation: Optional[List[Dict[str, Any]]] = None,
        event_queue: Optional[List[Dict[str, Any]]] = None,
        jeremy_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "world_state": self.build_stat().to_dict(),
            "active_conversation": active_conversation or [],
            "event_queue": event_queue or [],
            "jeremy": jeremy_prompt or "",
        }

    def get_engine_summary(self) -> Dict[str, Any]:
        if not self._pikpc_engine:
            return {"engine": "v0.1-safe", "active": False}
        if self._pikpc_error:
            return {"engine": "v1.6-pikpc", "active": False, "error": self._pikpc_error}
        try:
            summary = self._pikpc_engine.jeremy_room_summary()
            if isinstance(summary, dict):
                summary = dict(summary)
                summary.setdefault("engine", "v1.6-pikpc")
                summary.setdefault("active", True)
                summary = _json_safe(summary)
                self._pikpc_last_summary = summary
                return summary
        except Exception as exc:
            self._pikpc_error = str(exc)
            logger.warning("Bubble Stack PIKPC summary failed; retaining safe v0.1 path: %s", exc)
        return self._pikpc_last_summary or {"engine": "v1.6-pikpc", "active": False, "error": self._pikpc_error}

    def _generate_grid(self, config: BubbleGridConfig) -> Dict[str, Bubble]:
        ox, oy, oz = config.origin
        sx, sy, sz = config.dimensions
        bubbles: Dict[str, Bubble] = {}
        xi = 0
        x = ox
        while x <= ox + sx:
            yi = 0
            y = oy
            while y <= oy + sy:
                zi = 0
                z = oz
                while z <= oz + sz:
                    bubble_id = f"{config.room_id}:b:{xi}:{yi}:{zi}"
                    bubbles[bubble_id] = Bubble(bubble_id=bubble_id, center=(x, y, z), radius=config.radius)
                    zi += 1
                    z += config.spacing
                yi += 1
                y += config.spacing
            xi += 1
            x += config.spacing
        return bubbles

    def _candidate_bubbles(self, position: Vector3) -> Iterable[Bubble]:
        # v0.1 correctness first: scan all bubbles. PIKPC v1.6 handles its own
        # adaptive spatial hierarchy behind the adapter.
        return self.bubbles.values()

    def _build_nearby(self, active_bubbles: List[Bubble]) -> Dict[str, List[str]]:
        relationships: Dict[str, set[str]] = {}
        for bubble in active_bubbles:
            actors = sorted({bone.actor_id for bone in bubble.bones.values()})
            for actor in actors:
                relationships.setdefault(actor, set()).update(a for a in actors if a != actor)
        return {actor: sorted(peers) for actor, peers in relationships.items()}

    def _drain_events(self) -> List[Dict[str, Any]]:
        events = self._events[:50]
        self._events = self._events[50:]
        return events

    # ──────────────────────────────────────────────────────────────────────
    # PIKPC v1.6 promotion bridge
    # ──────────────────────────────────────────────────────────────────────

    def _init_pikpc_engine(self, config: BubbleGridConfig) -> None:
        self._pikpc_engine = None
        self._pikpc_frame_objects = {}
        self._pikpc_last_summary = {}
        self._pikpc_error = None
        if not _HAS_PIKPC_V1_6:
            self._pikpc_error = "PIKPC v1.6 package unavailable"
            return
        try:
            root_size = max(float(config.spacing), float(config.radius) * 2.0, 0.01)
            self._pikpc_engine = PIKPCBubbleStackEngine(PIKPCBubbleConfig(root_bubble_size=root_size))  # type: ignore[misc,operator]
            self._events.append({"type": "pikpc_v1_6_promoted", "room_id": config.room_id, "at": time()})
        except Exception as exc:
            self._pikpc_error = str(exc)
            self._pikpc_engine = None
            logger.warning("Bubble Stack PIKPC v1.6 startup failed; using safe v0.1 runtime: %s", exc)

    def _step_pikpc_if_active(self, reason: str) -> None:
        if not self._pikpc_engine or self._pikpc_error:
            return
        # Zero/near-zero processing law: when no AI is present, the engine keeps
        # current cached frame objects but does not step the kinetic runtime.
        if self.state != BubbleStackState.ACTIVE or not self.ai_actor_ids:
            return
        try:
            result = self._pikpc_engine.step(list(self._pikpc_frame_objects.values()))
            self._pikpc_last_summary = self._pikpc_engine.jeremy_room_summary()
            self._events.append({
                "type": "pikpc_v1_6_step",
                "reason": reason,
                "active_bubbles": getattr(result, "active_bubbles", None),
                "event_count": len(getattr(result, "events", []) or []),
                "at": time(),
            })
        except Exception as exc:
            self._pikpc_error = str(exc)
            logger.warning("Bubble Stack PIKPC v1.6 step failed; falling back to v0.1 summaries: %s", exc)
            self._events.append({"type": "pikpc_v1_6_disabled", "error": str(exc), "at": time()})

    def _update_pikpc_actor_bones(self, actor_id: str, bones: List[BonePresence]) -> None:
        if not self._pikpc_engine or self._pikpc_error:
            return
        for key in list(self._pikpc_frame_objects.keys()):
            if key.startswith(f"bone:{actor_id}:"):
                del self._pikpc_frame_objects[key]
        for bone in bones:
            object_id = f"bone:{actor_id}:{bone.bone_name}"
            self._pikpc_frame_objects[object_id] = self._pikpc_frame_object(
                object_id=object_id,
                center=bone.position,
                size=(0.12, 0.12, 0.12),
                tags=("actor", "bone", actor_id, bone.bone_name),
            )

    def _update_pikpc_object(self, obj: ObjectPresence) -> None:
        if not self._pikpc_engine or self._pikpc_error:
            return
        size = obj.metadata.get("size") or obj.metadata.get("dimensions") or (0.25, 0.25, 0.25)
        if isinstance(size, (int, float)):
            size_tuple = (float(size), float(size), float(size))
        else:
            try:
                size_tuple = (float(size[0]), float(size[1]), float(size[2]))  # type: ignore[index]
            except Exception:
                size_tuple = (0.25, 0.25, 0.25)
        self._pikpc_frame_objects[f"object:{obj.object_id}"] = self._pikpc_frame_object(
            object_id=f"object:{obj.object_id}",
            center=obj.position,
            size=size_tuple,
            tags=("object", obj.kind),
        )

    def _pikpc_frame_object(self, object_id: str, center: Vector3, size: Vector3, tags: Tuple[str, ...]) -> Any:
        cx, cy, cz = center
        sx, sy, sz = size
        half = (max(sx, 0.001) / 2.0, max(sy, 0.001) / 2.0, max(sz, 0.001) / 2.0)
        bounds = PIKPCAABB(  # type: ignore[operator]
            PIKPCVec3(cx - half[0], cy - half[1], cz - half[2]),  # type: ignore[operator]
            PIKPCVec3(cx + half[0], cy + half[1], cz + half[2]),  # type: ignore[operator]
        )
        return PIKPCFrameObject(object_id=object_id, bounds=bounds, semantic_tags=tags)  # type: ignore[operator]


def _json_safe(value: Any) -> Any:
    """Convert PIKPC dataclasses/enums into FastAPI/JSON-safe values."""
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, _EnumBase):
        return value.value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value

