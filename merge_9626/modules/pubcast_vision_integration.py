from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

from modules.cameras import CameraManager, CameraSource, CameraTransport

logger = logging.getLogger("pubcast.vision")


@dataclass
class Vector3D:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def distance_to(self, other: "Vector3D") -> float:
        dx = self.x - other.x
        dy = self.y - other.y
        dz = self.z - other.z
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def to_dict(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}


@dataclass
class CameraFrustum:
    fov_horizontal: float = 60.0
    fov_vertical: float = 45.0
    near_plane: float = 0.1
    far_plane: float = 100.0

    def is_in_frustum(self, cam_pos: Vector3D, cam_rot: Vector3D, target_pos: Vector3D) -> bool:
        dx = target_pos.x - cam_pos.x
        dy = target_pos.y - cam_pos.y
        dz = target_pos.z - cam_pos.z
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)
        if distance < self.near_plane or distance > self.far_plane:
            return False

        target_yaw = math.degrees(math.atan2(dx, dz))
        target_pitch = math.degrees(math.atan2(dy, math.sqrt(dx * dx + dz * dz)))
        yaw_diff = abs(self._angle_diff(target_yaw, cam_rot.y))
        pitch_diff = abs(self._angle_diff(target_pitch, cam_rot.x))
        return yaw_diff <= self.fov_horizontal / 2 and pitch_diff <= self.fov_vertical / 2

    @staticmethod
    def _angle_diff(a: float, b: float) -> float:
        return (a - b + 180) % 360 - 180


@dataclass
class VisibleObject:
    object_id: str
    object_type: str
    position: Vector3D
    distance: float
    screen_position: Tuple[float, float]
    occlusion_factor: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "object_id": self.object_id,
            "object_type": self.object_type,
            "position": self.position.to_dict(),
            "distance": self.distance,
            "screen_position": [self.screen_position[0], self.screen_position[1]],
            "occlusion_factor": self.occlusion_factor,
        }


@dataclass
class CameraFrame:
    frame_id: int
    timestamp: float
    camera_id: str
    camera_position: Vector3D
    camera_rotation: Vector3D
    visible_avatars: List[VisibleObject] = field(default_factory=list)
    visible_objects: List[VisibleObject] = field(default_factory=list)
    frame_quality: str = "good"
    exposure_level: float = 1.0
    focus_target: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "timestamp": self.timestamp,
            "camera_id": self.camera_id,
            "camera_position": self.camera_position.to_dict(),
            "camera_rotation": self.camera_rotation.to_dict(),
            "visible_avatars": [item.to_dict() for item in self.visible_avatars],
            "visible_objects": [item.to_dict() for item in self.visible_objects],
            "frame_quality": self.frame_quality,
            "exposure_level": self.exposure_level,
            "focus_target": self.focus_target,
        }


class StreamQuality(str, Enum):
    LOW = "360p"
    MEDIUM = "720p"
    HIGH = "1080p"
    ULTRA = "4k"


@dataclass
class StreamConfig:
    quality: StreamQuality = StreamQuality.MEDIUM
    fps: int = 12
    bitrate: int = 5000
    encoding: str = "H264"
    buffer_size: int = 60


@dataclass
class VisionCameraBot:
    camera_id: str
    world_id: str
    position: Vector3D
    rotation: Vector3D
    target_avatar_id: Optional[str] = None
    shot_type: str = "medium"
    motion_style: str = "steady"
    frustum: CameraFrustum = field(default_factory=CameraFrustum)
    stream_config: StreamConfig = field(default_factory=StreamConfig)
    is_streaming: bool = False
    frame_buffer: List[CameraFrame] = field(default_factory=list)
    frame_counter: int = 0
    source_id: Optional[str] = None
    visible_count: int = 0
    last_frame: Optional[CameraFrame] = None

    def world_to_screen(self, world_pos: Vector3D) -> Tuple[float, float]:
        dx = world_pos.x - self.position.x
        dy = world_pos.y - self.position.y
        dz = world_pos.z - self.position.z
        horiz = max(math.radians(self.frustum.fov_horizontal / 2), 0.001)
        vert = max(math.radians(self.frustum.fov_vertical / 2), 0.001)
        return (
            math.atan2(dx, dz) / horiz,
            math.atan2(dy, math.sqrt(dx * dx + dz * dz)) / vert,
        )

    def capture_visible_objects(self, scene_objects: List[Dict[str, Any]]) -> List[VisibleObject]:
        visible: List[VisibleObject] = []
        for obj in scene_objects:
            obj_pos = Vector3D(
                float(obj.get("x", 0.0)),
                float(obj.get("y", 0.0)),
                float(obj.get("z", 0.0)),
            )
            if not self.frustum.is_in_frustum(self.position, self.rotation, obj_pos):
                continue
            distance = self.position.distance_to(obj_pos)
            screen_pos = self.world_to_screen(obj_pos)
            visible.append(
                VisibleObject(
                    object_id=str(obj.get("id", "unknown")),
                    object_type=str(obj.get("type", "generic")),
                    position=obj_pos,
                    distance=distance,
                    screen_position=screen_pos,
                    occlusion_factor=float(obj.get("occlusion_factor", 0.0)),
                )
            )
        return visible

    def capture_frame(self, scene_objects: List[Dict[str, Any]], lights: Optional[List[Dict[str, Any]]] = None) -> CameraFrame:
        visible_objects = self.capture_visible_objects(scene_objects)
        visible_avatars = [item for item in visible_objects if item.object_type == "avatar"]
        visible_props = [item for item in visible_objects if item.object_type != "avatar"]

        frame_quality = "good"
        if self.target_avatar_id:
            target_visible = any(item.object_id == self.target_avatar_id for item in visible_avatars)
            if not visible_avatars:
                frame_quality = "blocked"
            elif not target_visible:
                frame_quality = "poor"

        frame = CameraFrame(
            frame_id=self.frame_counter,
            timestamp=time.time(),
            camera_id=self.camera_id,
            camera_position=Vector3D(self.position.x, self.position.y, self.position.z),
            camera_rotation=Vector3D(self.rotation.x, self.rotation.y, self.rotation.z),
            visible_avatars=visible_avatars,
            visible_objects=visible_props,
            frame_quality=frame_quality,
            exposure_level=self._calculate_exposure(lights or []),
            focus_target=self.target_avatar_id,
        )
        self.frame_counter += 1
        self.last_frame = frame
        self.visible_count = len(visible_avatars) + len(visible_props)

        if self.is_streaming:
            self.frame_buffer.append(frame)
            if len(self.frame_buffer) > self.stream_config.buffer_size:
                self.frame_buffer.pop(0)
        return frame

    def _calculate_exposure(self, lights: List[Dict[str, Any]]) -> float:
        total_light = 0.0
        for light in lights:
            light_pos = Vector3D(
                float(light.get("x", 0.0)),
                float(light.get("y", 0.0)),
                float(light.get("z", 0.0)),
            )
            distance = self.position.distance_to(light_pos)
            if distance < 20:
                intensity = float(light.get("intensity", 1.0))
                total_light += intensity / (distance + 0.1)
        return min(max(total_light / 2.0, 0.1), 3.0)

    def start_stream(self, quality: StreamQuality) -> None:
        self.stream_config.quality = quality
        self.is_streaming = True
        self.frame_buffer.clear()

    def stop_stream(self) -> None:
        self.is_streaming = False

    def get_stream_stats(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "is_streaming": self.is_streaming,
            "quality": self.stream_config.quality.value,
            "fps": self.stream_config.fps,
            "buffer_frames": len(self.frame_buffer),
            "total_frames": self.frame_counter,
            "last_visible_count": self.visible_count,
            "frame_quality": self.last_frame.frame_quality if self.last_frame else "unknown",
        }

    def get_frame_report(self) -> Dict[str, Any]:
        if not self.last_frame:
            return {
                "camera_id": self.camera_id,
                "status": "no_frames",
                "position": self.position.to_dict(),
                "rotation": self.rotation.to_dict(),
            }
        frame = self.last_frame
        return {
            "camera_id": self.camera_id,
            "frame_id": frame.frame_id,
            "position": frame.camera_position.to_dict(),
            "rotation": frame.camera_rotation.to_dict(),
            "quality": frame.frame_quality,
            "exposure": frame.exposure_level,
            "visible_avatars": len(frame.visible_avatars),
            "visible_objects": len(frame.visible_objects),
            "avatars": [
                {
                    "id": item.object_id,
                    "distance": round(item.distance, 2),
                    "screen_pos": [round(item.screen_position[0], 2), round(item.screen_position[1], 2)],
                }
                for item in sorted(frame.visible_avatars, key=lambda current: current.distance)
            ],
        }


class PubcastVisionManager:
    def __init__(
        self,
        camera_manager: CameraManager,
        data_dir: Path,
        broadcast_event: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        update_hz: float = 6.0,
    ) -> None:
        self.camera_manager = camera_manager
        self.data_dir = data_dir
        self.broadcast_event = broadcast_event
        self.vision_cameras: Dict[str, VisionCameraBot] = {}
        self.broadcast_name = "PubCast Live"
        self.is_broadcasting = False
        self.primary_camera: Optional[str] = None
        self.current_scene_objects: List[Dict[str, Any]] = []
        self.current_lights: List[Dict[str, Any]] = []
        self.frames_captured = 0
        self.broadcasts_started = 0
        self.stream_clients: Set[Any] = set()
        self._update_hz = max(1.0, float(update_hz))
        self._loop_task: Optional[asyncio.Task] = None
        self._bootstrap_from_camera_manager()

    def _bootstrap_from_camera_manager(self) -> None:
        for source in self.camera_manager.list_sources():
            self._upsert_bot_from_source(source)
        program = self.camera_manager.get_program_source()
        if program:
            self.primary_camera = program.source_id
        elif self.vision_cameras:
            self.primary_camera = next(iter(self.vision_cameras))

    def _upsert_bot_from_source(self, source: CameraSource, config: Optional[Dict[str, Any]] = None) -> VisionCameraBot:
        config = config or {}
        bot = self.vision_cameras.get(source.source_id)
        if bot is None:
            bot = VisionCameraBot(
                camera_id=source.source_id,
                world_id=str(config.get("world_id", "default")),
                position=Vector3D(*list(source.position[:3])),
                rotation=Vector3D(*list(source.rotation[:3])),
                target_avatar_id=config.get("target_avatar"),
                shot_type=str(config.get("shot_type", self._infer_shot_type(source))),
                motion_style=str(config.get("motion_style", "steady")),
                source_id=source.source_id,
            )
            self.vision_cameras[source.source_id] = bot
        else:
            bot.position = Vector3D(*list(source.position[:3]))
            bot.rotation = Vector3D(*list(source.rotation[:3]))
            bot.source_id = source.source_id
        bot.frustum.fov_horizontal = float(config.get("fov", source.fov))
        bot.frustum.fov_vertical = max(30.0, bot.frustum.fov_horizontal * 0.75)
        return bot

    def _infer_shot_type(self, source: CameraSource) -> str:
        tag_map = set(source.tags or [])
        if "close" in tag_map:
            return "closeup"
        if "wide" in tag_map or "establishing" in tag_map:
            return "wide"
        if "overhead" in tag_map:
            return "overhead"
        return "medium"

    async def register_vision_camera(self, config: Dict[str, Any]) -> bool:
        camera_id = str(config.get("camera_id", "")).strip()
        if not camera_id:
            return False

        source = self.camera_manager.get(camera_id)
        if source is None:
            source = CameraSource(
                source_id=camera_id,
                name=str(config.get("name") or camera_id.replace("_", " ").title()),
                location=str(config.get("world_id", "vision")),
                description=str(config.get("description") or "Vision-enabled virtual camera"),
                transport=CameraTransport.VIRTUAL,
                endpoint=str(config.get("endpoint") or f"vision://{camera_id}"),
                tags=["vision", str(config.get("shot_type", "medium"))],
                position=[
                    float(config.get("position_x", 0.0)),
                    float(config.get("position_y", 2.0)),
                    float(config.get("position_z", -10.0)),
                ],
                rotation=[0.0, 0.0, 0.0],
                fov=float(config.get("fov", 60.0)),
            )
            self.camera_manager.register(source)

        bot = self._upsert_bot_from_source(source, config)
        bot.target_avatar_id = config.get("target_avatar")
        bot.motion_style = str(config.get("motion_style", bot.motion_style))
        bot.shot_type = str(config.get("shot_type", bot.shot_type))

        if self.primary_camera is None:
            self.primary_camera = camera_id
            self.camera_manager.set_program_source(camera_id)
        elif self.camera_manager.get_preview_source() is None:
            self.camera_manager.set_preview_source(camera_id)
        return True

    def update_scene_objects(self, objects: List[Dict[str, Any]], lights: Optional[List[Dict[str, Any]]] = None) -> None:
        self.current_scene_objects = list(objects or [])
        self.current_lights = list(lights or [])

    async def update_all_cameras(self) -> Dict[str, CameraFrame]:
        frames: Dict[str, CameraFrame] = {}
        for camera_id, bot in self.vision_cameras.items():
            frame = bot.capture_frame(self.current_scene_objects, self.current_lights)
            frames[camera_id] = frame
            self.frames_captured += 1
            if bot.is_streaming and self.stream_clients:
                await self._broadcast_frame(frame)
        return frames

    async def _broadcast_frame(self, frame: CameraFrame) -> None:
        payload = {"type": "camera_frame", "data": frame.to_dict()}
        disconnected: Set[Any] = set()
        for client in self.stream_clients:
            try:
                await client.send_json(payload)
            except Exception:
                disconnected.add(client)
        self.stream_clients -= disconnected

    async def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if not self.broadcast_event:
            return
        try:
            await self.broadcast_event({"type": event_type, "payload": payload})
        except Exception as exc:
            logger.warning("vision event emit failed for %s: %s", event_type, exc)

    async def _run_loop(self) -> None:
        interval = 1.0 / self._update_hz
        try:
            while self.is_broadcasting:
                await self.update_all_cameras()
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    def start_broadcast(self, quality: StreamQuality = StreamQuality.HIGH) -> None:
        for bot in self.vision_cameras.values():
            bot.start_stream(quality)
        self.is_broadcasting = True
        self.broadcasts_started += 1
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._run_loop())
        if self.broadcast_event:
            asyncio.create_task(
                self._emit(
                    "vision_broadcast_start",
                    {
                        "quality": quality.value,
                        "camera_count": len(self.vision_cameras),
                    },
                )
            )

    async def stop_broadcast(self) -> None:
        for bot in self.vision_cameras.values():
            bot.stop_stream()
        self.is_broadcasting = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        self._loop_task = None
        await self._emit(
            "vision_broadcast_stop",
            {
                "frames_captured": self.frames_captured,
                "camera_count": len(self.vision_cameras),
            },
        )

    async def set_primary_camera(self, camera_id: str) -> bool:
        if camera_id not in self.vision_cameras:
            return False
        self.primary_camera = camera_id
        self.camera_manager.set_program_source(camera_id)
        await self._emit("vision_primary_camera", {"camera_id": camera_id})
        return True

    def get_best_camera(self) -> Optional[str]:
        scored: List[Tuple[float, str]] = []
        for camera_id, bot in self.vision_cameras.items():
            frame = bot.last_frame
            if frame is None:
                score = 0.0
            else:
                quality_score = {"good": 30.0, "poor": 10.0, "blocked": -10.0}.get(frame.frame_quality, 0.0)
                score = quality_score + len(frame.visible_avatars) * 8 + len(frame.visible_objects) * 1.5
                if bot.target_avatar_id and frame.focus_target == bot.target_avatar_id:
                    score += 5.0
            scored.append((score, camera_id))
        if not scored:
            return None
        scored.sort(reverse=True)
        return scored[0][1]

    def get_camera_stats(self, camera_id: str) -> Optional[Dict[str, Any]]:
        bot = self.vision_cameras.get(camera_id)
        if not bot:
            return None
        source = self.camera_manager.get(camera_id)
        status = self.camera_manager.status(camera_id)
        return {
            "camera_id": camera_id,
            "source": {
                "name": source.name if source else camera_id,
                "transport": source.transport.value if source else "virtual",
                "location": source.location if source else "vision",
                "fov": source.fov if source else bot.frustum.fov_horizontal,
            },
            "stream": bot.get_stream_stats(),
            "target_avatar_id": bot.target_avatar_id,
            "shot_type": bot.shot_type,
            "motion_style": bot.motion_style,
            "status": {
                "online": status.online if status else True,
                "latency_ms": status.latency_ms if status else None,
                "frame_rate": status.frame_rate if status else None,
                "notes": status.notes if status else None,
            },
            "last_frame": bot.last_frame.to_dict() if bot.last_frame else None,
        }

    def get_camera_view(self, camera_id: str) -> Optional[Dict[str, Any]]:
        bot = self.vision_cameras.get(camera_id)
        if not bot:
            return None
        return bot.get_frame_report()

    def get_all_camera_views(self) -> Dict[str, Any]:
        return {
            "primary_camera": self.primary_camera,
            "views": {camera_id: bot.get_frame_report() for camera_id, bot in self.vision_cameras.items()},
        }

    def get_all_cameras_status(self) -> Dict[str, Any]:
        return {
            "broadcast_name": self.broadcast_name,
            "is_broadcasting": self.is_broadcasting,
            "primary_camera": self.primary_camera,
            "camera_count": len(self.vision_cameras),
            "cameras": [self.get_camera_stats(camera_id) for camera_id in self.vision_cameras],
        }

    async def add_stream_client(self, client: Any) -> None:
        self.stream_clients.add(client)

    async def remove_stream_client(self, client: Any) -> None:
        self.stream_clients.discard(client)


def create_vision_manager(
    camera_manager: CameraManager,
    data_dir: Path,
    broadcast_event: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
) -> PubcastVisionManager:
    return PubcastVisionManager(
        camera_manager=camera_manager,
        data_dir=data_dir,
        broadcast_event=broadcast_event,
    )
