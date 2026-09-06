# PubCast AI — choreography_controller.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
from __future__ import annotations

import asyncio
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .choreography_runtime import Choreography, ChoreographyStep

DEFAULT_ACTIONS: Dict[str, Dict[str, Any]] = {
    # ── Base ─────────────────────────────────────────────────────────────────
    "idle":              {"label": "Idle",                  "duration": 2.0, "category": "base",        "gender": "neutral"},
    "stand":             {"label": "Stand",                 "duration": 1.2, "category": "base",        "gender": "neutral"},
    # ── Locomotion ────────────────────────────────────────────────────────────
    "walk":              {"label": "Walk",                  "duration": 2.0, "category": "locomotion",  "gender": "neutral"},
    "walk_feminine":     {"label": "Walk (Feminine)",       "duration": 2.0, "category": "locomotion",  "gender": "feminine",  "note": "Enhanced hip sway, reduced arm swing, graceful stride"},
    "walk_masculine":    {"label": "Walk (Masculine)",      "duration": 2.0, "category": "locomotion",  "gender": "masculine", "note": "Reduced hip sway, broader step, stronger arm swing"},
    "walk_heels":        {"label": "High Heel Walk",        "duration": 2.4, "category": "locomotion",  "gender": "feminine",  "note": "Slower, deliberate, exaggerated hip movement, pointed foot"},
    "walk_backward":     {"label": "Walk Backward",         "duration": 2.2, "category": "locomotion",  "gender": "neutral"},
    "run":               {"label": "Run",                   "duration": 0.6, "category": "locomotion",  "gender": "neutral"},
    "run_backward":      {"label": "Run Backward",          "duration": 0.7, "category": "locomotion",  "gender": "neutral"},
    "jump":              {"label": "Jump",                  "duration": 0.9, "category": "locomotion",  "gender": "neutral"},
    "jump_crouch":       {"label": "Jump – Crouch",         "duration": 0.3, "category": "locomotion",  "gender": "neutral"},
    "jump_launch":       {"label": "Jump – Launch",         "duration": 0.3, "category": "locomotion",  "gender": "neutral"},
    "jump_land":         {"label": "Jump – Land",           "duration": 0.4, "category": "locomotion",  "gender": "neutral"},
    "crawl":             {"label": "Crawl",                 "duration": 2.4, "category": "locomotion",  "gender": "neutral"},
    "stopping":          {"label": "Stop",                  "duration": 0.5, "category": "locomotion",  "gender": "neutral"},
    "turn_left":         {"label": "Turn Left 90°",         "duration": 0.5, "category": "locomotion",  "gender": "neutral"},
    "turn_right":        {"label": "Turn Right 90°",        "duration": 0.5, "category": "locomotion",  "gender": "neutral"},
    "duck":              {"label": "Duck",                  "duration": 0.4, "category": "locomotion",  "gender": "neutral"},
    # ── Idles ─────────────────────────────────────────────────────────────────
    "idle_arms_folded":  {"label": "Idle – Arms Folded",    "duration": 4.0, "category": "idle",        "gender": "neutral"},
    "idle_pockets":      {"label": "Idle – Hands in Pockets","duration": 4.0,"category": "idle",        "gender": "neutral"},
    "idle_look_around":  {"label": "Idle – Looking Around", "duration": 4.0, "category": "idle",        "gender": "neutral"},
    "idle_weight_shift": {"label": "Idle – Weight Shift",   "duration": 3.0, "category": "idle",        "gender": "neutral"},
    # ── Poses ─────────────────────────────────────────────────────────────────
    "sit_desk":          {"label": "Sit At Desk",           "duration": 2.0, "category": "pose",        "gender": "neutral"},
    "sit_table":         {"label": "Sit At Dinner Table",   "duration": 2.0, "category": "pose",        "gender": "neutral"},
    "sit_chair":         {"label": "Sit In Chair",          "duration": 2.0, "category": "pose",        "gender": "neutral"},
    "stand_from_chair":  {"label": "Stand From Chair",      "duration": 1.5, "category": "pose",        "gender": "neutral"},
    "fall":              {"label": "Fall",                  "duration": 1.0, "category": "pose",        "gender": "neutral"},
    "fall_forward":      {"label": "Fall Forward",          "duration": 1.2, "category": "pose",        "gender": "neutral"},
    "trip":              {"label": "Trip",                  "duration": 0.9, "category": "pose",        "gender": "neutral"},
    "get_up":            {"label": "Get Up From Ground",    "duration": 2.0, "category": "pose",        "gender": "neutral"},
    "sleep":             {"label": "Sleep",                 "duration": 4.0, "category": "pose",        "gender": "neutral"},
    "lie_down":          {"label": "Lie Down",              "duration": 2.0, "category": "pose",        "gender": "neutral"},
    "wake_up":           {"label": "Wake Up",               "duration": 2.5, "category": "pose",        "gender": "neutral"},
    # ── Gestures ──────────────────────────────────────────────────────────────
    "wave":              {"label": "Wave",                  "duration": 2.0, "category": "gesture",     "gender": "neutral"},
    "nod_slow":          {"label": "Nod – Slow",            "duration": 2.0, "category": "gesture",     "gender": "neutral"},
    "nod_quick":         {"label": "Nod – Quick",           "duration": 1.0, "category": "gesture",     "gender": "neutral"},
    "shake_head":        {"label": "Shake Head",            "duration": 1.5, "category": "gesture",     "gender": "neutral"},
    "hand_wave":         {"label": "Hand Wave",             "duration": 2.0, "category": "gesture",     "gender": "neutral"},
    "hands_on_hips":     {"label": "Hands On Hips",        "duration": 2.0, "category": "gesture",     "gender": "neutral"},
    "point":             {"label": "Point",                 "duration": 1.5, "category": "gesture",     "gender": "neutral"},
    "shrug":             {"label": "Shrug",                 "duration": 1.8, "category": "gesture",     "gender": "neutral"},
    "bow":               {"label": "Bow",                   "duration": 2.0, "category": "gesture",     "gender": "neutral"},
    "curtsey":           {"label": "Curtsey",               "duration": 2.2, "category": "gesture",     "gender": "feminine"},
    "handshake":         {"label": "Handshake",             "duration": 2.0, "category": "gesture",     "gender": "neutral"},
    "confident_stance":  {"label": "Confident Stance",      "duration": 2.0, "category": "gesture",     "gender": "neutral"},
    # ── Interaction ───────────────────────────────────────────────────────────
    "eat":               {"label": "Eat",                   "duration": 3.0, "category": "interaction", "gender": "neutral"},
    "hold_coffee":       {"label": "Hold Coffee Mug",       "duration": 3.0, "category": "interaction", "gender": "neutral"},
    "film_camera":       {"label": "Film With Cinema Camera","duration": 3.2, "category": "interaction", "gender": "neutral"},
    "work_console":      {"label": "Work At Console",       "duration": 3.2, "category": "interaction", "gender": "neutral"},
    "type_computer":     {"label": "Type At Computer",      "duration": 4.0, "category": "interaction", "gender": "neutral"},
    "type_console":      {"label": "Type At Console",       "duration": 4.0, "category": "interaction", "gender": "neutral"},
    "read_book":         {"label": "Read Book",             "duration": 3.0, "category": "interaction", "gender": "neutral"},
    "climb_ladder":      {"label": "Climb Ladder",          "duration": 3.0, "category": "interaction", "gender": "neutral"},
    "push":              {"label": "Push",                  "duration": 2.0, "category": "interaction", "gender": "neutral"},
    "pull":              {"label": "Pull",                  "duration": 2.0, "category": "interaction", "gender": "neutral"},
    "drive_car":         {"label": "Drive Car",             "duration": 4.0, "category": "interaction", "gender": "neutral"},
    "ride_bike":         {"label": "Ride Bike",             "duration": 4.0, "category": "interaction", "gender": "neutral"},
    # ── Wardrobe ──────────────────────────────────────────────────────────────
    "coat_on":           {"label": "Put On Coat",           "duration": 2.4, "category": "wardrobe",    "gender": "neutral"},
    "coat_off":          {"label": "Take Off Coat",         "duration": 2.0, "category": "wardrobe",    "gender": "neutral"},
    "hat_on":            {"label": "Put On Hat",            "duration": 1.6, "category": "wardrobe",    "gender": "neutral"},
    "hat_off":           {"label": "Take Off Hat",          "duration": 1.4, "category": "wardrobe",    "gender": "neutral"},
    "shoes_on":          {"label": "Put On Shoes",          "duration": 2.4, "category": "wardrobe",    "gender": "neutral"},
    "shoes_off":         {"label": "Take Off Shoes",        "duration": 1.9, "category": "wardrobe",    "gender": "neutral"},
    # ── Female-specific ───────────────────────────────────────────────────────
    "purse_open":        {"label": "Open Purse",            "duration": 2.0, "category": "feminine",    "gender": "feminine"},
    "lipstick":          {"label": "Apply Lipstick",        "duration": 3.0, "category": "feminine",    "gender": "feminine"},
    "mascara":           {"label": "Apply Mascara",         "duration": 3.0, "category": "feminine",    "gender": "feminine"},
    "powder":            {"label": "Apply Powder",          "duration": 2.5, "category": "feminine",    "gender": "feminine"},
    # ── Emotional overlays ────────────────────────────────────────────────────
    "thoughtful_idle":   {"label": "Thoughtful",            "duration": 4.0, "category": "emotional",   "gender": "neutral"},
    "relaxed_idle":      {"label": "Relaxed",               "duration": 4.0, "category": "emotional",   "gender": "neutral"},
    "adjust_seat":       {"label": "Adjust Seat",           "duration": 1.5, "category": "seated",      "gender": "neutral"},
}


@dataclass
class MotionConstraints:
    enabled: bool = True
    max_horizontal_speed: float = 2.2
    max_vertical_speed: float = 2.8
    max_turn_rate_deg: float = 220.0
    x_min: float = -2.4
    x_max: float = 2.4
    y_min: float = -1.1
    y_max: float = 1.8
    z_min: float = -2.0
    z_max: float = 2.0
    allow_extreme_postures: bool = False

    def apply_patch(self, patch: Dict[str, Any]) -> None:
        if not isinstance(patch, dict):
            return
        for key, value in patch.items():
            if not hasattr(self, key):
                continue
            current = getattr(self, key)
            if isinstance(current, bool):
                setattr(self, key, bool(value))
            else:
                try:
                    setattr(self, key, float(value))
                except (TypeError, ValueError):
                    continue
        # Keep bounds sane even when patches arrive out of order.
        if self.x_min > self.x_max:
            self.x_min, self.x_max = self.x_max, self.x_min
        if self.y_min > self.y_max:
            self.y_min, self.y_max = self.y_max, self.y_min
        if self.z_min > self.z_max:
            self.z_min, self.z_max = self.z_max, self.z_min


@dataclass
class AvatarSim:
    """Lightweight simulated avatar implementing the runtime interface."""

    id: str
    position: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotation: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    _skeleton: Dict[str, List[float]] = field(default_factory=dict)

    def get_full_skeleton_data(self) -> Dict[str, List[float]]:
        return {k: list(v) for k, v in self._skeleton.items()}

    def apply_pose_data(self, pose: Dict[str, List[float]]) -> None:
        self._skeleton = {k: list(v) for k, v in pose.items()}

    def get_sync_state(self) -> Dict[str, Any]:
        return {"position": list(self.position), "rotation": list(self.rotation)}


class ChoreoController:
    """Server-owned choreography runtime + action cue broadcaster."""

    def __init__(self, hub: Any, *, tick_hz: float = 30.0) -> None:
        self._hub = hub
        self._tick_hz = max(1.0, float(tick_hz))
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._room: Optional[str] = None
        self._choreo: Optional[Choreography] = None
        self._avatars: List[AvatarSim] = []
        self._last_frame_ts: float = 0.0
        self._constraints = MotionConstraints()
        self._actions = dict(DEFAULT_ACTIONS)
        self._last_error: Optional[str] = None

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "room": self._room,
            "fps": self._tick_hz,
            "time": self._choreo.current_time if self._choreo else 0.0,
            "steps": len(self._choreo.steps) if self._choreo else 0,
            "avatars": [a.id for a in self._avatars],
            "last_frame_ts": self._last_frame_ts,
            "constraints": asdict(self._constraints),
            "last_error": self._last_error,
        }

    def list_actions(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._actions)

    def get_constraints(self) -> Dict[str, Any]:
        return asdict(self._constraints)

    def set_constraints(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        self._constraints.apply_patch(patch)
        return self.get_constraints()

    async def cue_action(
        self,
        *,
        room: str,
        avatar_id: str,
        action: str,
        intensity: float = 1.0,
        duration: Optional[float] = None,
        props: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        name = (action or "").strip().lower()
        if name not in self._actions:
            raise ValueError(f"Unknown action: {action!r}")
        if not avatar_id:
            raise ValueError("avatar_id is required")

        action_cfg = self._actions[name]
        payload = {
            "room": room,
            "avatar_id": avatar_id,
            "action": name,
            "label": action_cfg["label"],
            "category": action_cfg["category"],
            "intensity": max(0.1, min(3.0, float(intensity or 1.0))),
            "duration": max(0.2, float(duration or action_cfg["duration"])),
            "props": props or {},
            "constraints_enabled": self._constraints.enabled,
            "sent_at": time.time(),
        }
        await self._hub.broadcast_system_event({"type": "avatar_action_cue", "payload": payload})
        return payload

    async def start(
        self,
        *,
        room: str,
        avatars: Optional[List[Dict[str, Any]]],
        steps: List[Dict[str, Any]],
        tick_hz: Optional[float] = None,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if self._running:
            await self.stop()
        if tick_hz is not None:
            self._tick_hz = max(1.0, float(tick_hz))
        if constraints:
            self._constraints.apply_patch(constraints)

        avatar_map: Dict[str, AvatarSim] = {}
        if avatars:
            for a in avatars:
                aid = str(a.get("id", "")).strip()
                if not aid:
                    continue
                avatar_map[aid] = AvatarSim(
                    id=aid,
                    position=list(a.get("position") or [0.0, 0.0, 0.0]),
                    rotation=list(a.get("rotation") or [0.0, 0.0, 0.0]),
                )
        for s in steps:
            aid = str(s.get("avatar_id", "")).strip()
            if aid and aid not in avatar_map:
                avatar_map[aid] = AvatarSim(id=aid)

        self._avatars = list(avatar_map.values())
        choreo = Choreography(name="server_runtime")
        for s in steps:
            try:
                step = ChoreographyStep(
                    avatar_id=str(s.get("avatar_id")),
                    animation_type=str(s.get("animation_type")),
                    start_time=float(s.get("start_time", 0.0)),
                    duration=float(s.get("duration", 1.0)),
                    target_position=list(s.get("target_position") or [0.0, 0.0, 0.0]),
                    target_rotation=list(s.get("target_rotation") or [0.0, 0.0, 0.0]),
                    target_skeleton=dict(s.get("target_skeleton") or {}),
                )
            except Exception:
                continue
            choreo.add_step(step)

        self._choreo = choreo
        self._room = room
        self._choreo.start(self._avatars)
        self._running = True
        self._last_error = None
        self._task = asyncio.create_task(self._runner())
        await self._hub.broadcast_system_event(
            {"type": "choreo_start", "payload": {"room": room, "status": self.status()}}
        )
        return self.status()

    async def stop(self) -> None:
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=0.6)
            except asyncio.TimeoutError:
                self._task.cancel()
            finally:
                self._task = None
        if self._choreo:
            self._choreo.stop()
        await self._hub.broadcast_system_event({"type": "choreo_stop", "payload": {"room": self._room}})
        self._room = None

    async def _runner(self) -> None:
        interval = 1.0 / self._tick_hz
        prev_states: Dict[str, Dict[str, List[float]]] = {}
        try:
            while self._running and self._choreo:
                start = time.perf_counter()
                self._choreo.update(self._avatars)
                elapsed = time.perf_counter() - start
                dt = max(interval, elapsed, 1e-3)
                self._apply_constraints(prev_states, dt)
                prev_states = {
                    a.id: {"position": list(a.position), "rotation": list(a.rotation)}
                    for a in self._avatars
                }

                payload = {
                    "time": self._choreo.current_time,
                    "avatars": [
                        {
                            "id": a.id,
                            "position": list(a.position),
                            "rotation": list(a.rotation),
                            "skeleton": a.get_full_skeleton_data(),
                        }
                        for a in self._avatars
                    ],
                    "room": self._room,
                }
                await self._hub.broadcast_system_event({"type": "choreo_frame", "payload": payload})
                self._last_frame_ts = time.time()

                done = bool(self._choreo.steps) and all(step.completed for step in self._choreo.steps)
                if done:
                    await self._hub.broadcast_system_event(
                        {"type": "choreo_complete", "payload": {"room": self._room, "time": self._choreo.current_time}}
                    )
                    self._running = False
                    break

                await asyncio.sleep(max(0.0, interval - elapsed))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._last_error = str(exc)
            await self._hub.broadcast_system_event(
                {"type": "choreo_error", "payload": {"room": self._room, "error": str(exc)}}
            )
        finally:
            self._running = False

    def _apply_constraints(self, prev_states: Dict[str, Dict[str, List[float]]], dt: float) -> None:
        c = self._constraints
        if not c.enabled:
            return
        max_h_step = max(0.01, c.max_horizontal_speed * dt)
        max_v_step = max(0.01, c.max_vertical_speed * dt)
        max_turn_step = max(0.1, c.max_turn_rate_deg * dt)

        for avatar in self._avatars:
            prev = prev_states.get(avatar.id)
            if not prev:
                # First frame: only hard bounds.
                avatar.position[0] = self._clamp(avatar.position[0], c.x_min, c.x_max)
                avatar.position[1] = self._clamp(avatar.position[1], c.y_min, c.y_max)
                avatar.position[2] = self._clamp(avatar.position[2], c.z_min, c.z_max)
                continue

            px, py, pz = prev["position"]
            cx, cy, cz = avatar.position

            if not self._is_finite_triplet(cx, cy, cz):
                avatar.position = [px, py, pz]
                avatar.rotation = list(prev["rotation"])
                continue

            dx = cx - px
            dz = cz - pz
            horizontal_dist = math.hypot(dx, dz)
            if horizontal_dist > max_h_step and horizontal_dist > 1e-9:
                scale = max_h_step / horizontal_dist
                dx *= scale
                dz *= scale
            avatar.position[0] = self._clamp(px + dx, c.x_min, c.x_max)
            avatar.position[2] = self._clamp(pz + dz, c.z_min, c.z_max)

            dy = cy - py
            if abs(dy) > max_v_step:
                dy = math.copysign(max_v_step, dy)
            avatar.position[1] = self._clamp(py + dy, c.y_min, c.y_max)

            prev_rot = prev["rotation"]
            if len(avatar.rotation) < 3:
                avatar.rotation = list(prev_rot)
            else:
                # Yaw rate limit keeps turns human-readable and avoids instant snaps.
                yaw_prev = float(prev_rot[1])
                yaw_now = float(avatar.rotation[1])
                yaw_delta = self._wrap_angle(yaw_now - yaw_prev)
                yaw_delta = self._clamp(yaw_delta, -max_turn_step, max_turn_step)
                avatar.rotation[1] = yaw_prev + yaw_delta

                if not c.allow_extreme_postures:
                    avatar.rotation[0] = self._clamp(float(avatar.rotation[0]), -65.0, 65.0)
                    avatar.rotation[2] = self._clamp(float(avatar.rotation[2]), -55.0, 55.0)

    @staticmethod
    def _clamp(v: float, lo: float, hi: float) -> float:
        return min(max(float(v), lo), hi)

    @staticmethod
    def _is_finite_triplet(a: float, b: float, c: float) -> bool:
        return math.isfinite(a) and math.isfinite(b) and math.isfinite(c)

    @staticmethod
    def _wrap_angle(deg: float) -> float:
        wrapped = (deg + 180.0) % 360.0 - 180.0
        return wrapped


__all__ = ["ChoreoController", "MotionConstraints", "AvatarSim", "DEFAULT_ACTIONS"]
