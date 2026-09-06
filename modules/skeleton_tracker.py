"""Skeleton frame adapter for Bubble Stack v0.1."""
from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Dict, Iterable, Tuple

from .bubble_stack import BonePresence, Vector3
from .posture_library import PostureLibrary, PostureResult


@dataclass
class SkeletonFrame:
    actor_id: str
    bones: Dict[str, Vector3]
    timestamp: float = field(default_factory=time)


class SkeletonTracker:
    def __init__(self, posture_library: PostureLibrary | None = None):
        self._last_positions: Dict[str, Dict[str, Vector3]] = {}
        self._last_time: Dict[str, float] = {}
        self.posture_library = posture_library or PostureLibrary()

    def to_bone_presence(self, frame: SkeletonFrame, confidence: float = 1.0) -> Iterable[BonePresence]:
        last = self._last_positions.get(frame.actor_id, {})
        last_t = self._last_time.get(frame.actor_id, frame.timestamp)
        dt = max(frame.timestamp - last_t, 1e-6)
        presences = []
        for bone_name, position in frame.bones.items():
            prev = last.get(bone_name, position)
            velocity = tuple((position[i] - prev[i]) / dt for i in range(3))
            presences.append(BonePresence(
                actor_id=frame.actor_id,
                bone_name=bone_name,
                position=position,
                velocity=velocity,  # type: ignore[arg-type]
                confidence=confidence,
                timestamp=frame.timestamp,
            ))
        self._last_positions[frame.actor_id] = dict(frame.bones)
        self._last_time[frame.actor_id] = frame.timestamp
        return presences

    def classify_posture(self, frame: SkeletonFrame) -> PostureResult:
        return self.posture_library.classify(frame.bones)

