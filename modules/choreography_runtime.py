# PubCast AI — choreography_runtime.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .persistence import write_json
from typing import Dict, Iterable, List


class Easing:
    """Common easing helpers for cinematic motion."""

    @staticmethod
    def ease_in_out_cubic(t: float) -> float:
        return 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2


@dataclass
class ChoreographyStep:
    avatar_id: str
    animation_type: str
    start_time: float
    duration: float
    target_position: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    target_rotation: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    target_skeleton: Dict[str, List[float]] = field(default_factory=dict)

    initial_position: List[float] = field(default_factory=list)
    initial_rotation: List[float] = field(default_factory=list)
    initial_skeleton: Dict[str, List[float]] = field(default_factory=dict)
    completed: bool = False

    def activate(self, avatar) -> None:
        """Capture the avatar state when the step becomes active."""
        self.initial_position = list(getattr(avatar, "position", [0.0, 0.0, 0.0]))
        self.initial_rotation = list(getattr(avatar, "rotation", [0.0, 0.0, 0.0]))
        getter = getattr(avatar, "get_full_skeleton_data", None)
        self.initial_skeleton = getter() if callable(getter) else {}
        self.completed = False

    def update(self, avatar, current_time: float) -> None:
        if self.completed or not self.is_active(current_time):
            return

        progress = (current_time - self.start_time) / max(self.duration, 0.001)
        eased = Easing.ease_in_out_cubic(max(0.0, min(1.0, progress)))

        if self.animation_type in {"walk", "move", "run", "crawl", "climb"}:
            for idx in range(3):
                delta = self.target_position[idx] - self.initial_position[idx]
                avatar.position[idx] = self.initial_position[idx] + delta * eased
        elif self.animation_type in {"turn", "look"}:
            delta = self.target_rotation[1] - self.initial_rotation[1]
            avatar.rotation[1] = self.initial_rotation[1] + delta * eased
        elif self.animation_type == "pose_transition" and self.target_skeleton:
            apply_pose = getattr(avatar, "apply_pose_data", None)
            if callable(apply_pose):
                new_pose: Dict[str, List[float]] = {}
                for joint, begin in self.initial_skeleton.items():
                    target = self.target_skeleton.get(joint, begin)
                    new_pose[joint] = [
                        begin[i] + (target[i] - begin[i]) * eased for i in range(len(begin))
                    ]
                apply_pose(new_pose)

        if progress >= 1.0:
            self.completed = True

    def is_active(self, current_time: float) -> bool:
        return self.start_time <= current_time < self.start_time + self.duration


@dataclass
class Choreography:
    name: str = "Choreography"
    steps: List[ChoreographyStep] = field(default_factory=list)
    start_time: float = 0.0
    playing: bool = False
    current_time: float = 0.0
    recording: bool = False
    recorded_frames: List[Dict[str, object]] = field(default_factory=list)

    def add_step(self, step: ChoreographyStep) -> None:
        self.steps.append(step)
        self.steps.sort(key=lambda s: s.start_time)

    def start(self, avatars: Iterable) -> None:
        self.playing = True
        self.start_time = time.time()
        self.current_time = 0.0

        # O(1) lookup for larger avatar sets.
        avatar_map = {getattr(a, "id", None): a for a in avatars}

        for step in self.steps:
            avatar = avatar_map.get(step.avatar_id)
            if avatar:
                step.activate(avatar)

    def stop(self) -> None:
        self.playing = False
        self.current_time = 0.0

    def update(self, avatars: Iterable) -> None:
        if not self.playing:
            return
        self.current_time = time.time() - self.start_time

        avatar_map = {getattr(a, "id", None): a for a in avatars}

        for step in self.steps:
            avatar = avatar_map.get(step.avatar_id)
            if avatar:
                step.update(avatar, self.current_time)

        if self.recording:
            self.record_frame(avatars)

    def record_frame(self, avatars: Iterable) -> None:
        frame = {
            "time": self.current_time,
            "avatars": [
                {
                    "id": getattr(avatar, "id", "unknown"),
                    "state": getattr(avatar, "get_sync_state", lambda: {})(),
                    "skeleton": getattr(avatar, "get_full_skeleton_data", lambda: {})(),
                }
                for avatar in avatars
            ],
        }
        self.recorded_frames.append(frame)

    def export_json(self, path: Path) -> None:
        # Persist only authored step definitions, not runtime internals.
        def serialize_step(step: ChoreographyStep) -> Dict[str, object]:
            return {
                "avatar_id": step.avatar_id,
                "animation_type": step.animation_type,
                "start_time": step.start_time,
                "duration": step.duration,
                "target_position": step.target_position,
                "target_rotation": step.target_rotation,
                "target_skeleton": step.target_skeleton,
            }

        payload = {
            "name": self.name,
            "steps": [serialize_step(step) for step in self.steps],
            "recorded_frames": self.recorded_frames,
        }
        write_json(path, payload)

