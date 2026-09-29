from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pubcast.twin_engine")


class TwinEngineMode(str, Enum):
    DISCONNECTED = "disconnected"
    DEGRADED = "degraded"
    READY = "ready"


class CameraTransition(str, Enum):
    CUT = "cut"
    DISSOLVE = "dissolve"
    PUSH = "push"
    ORBIT = "orbit"


@dataclass
class Vec3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class VirtualCameraState:
    camera_id: str
    name: str
    position: Vec3 = field(default_factory=Vec3)
    rotation: Vec3 = field(default_factory=Vec3)
    fov: float = 60.0
    target_id: Optional[str] = None
    active: bool = False
    transition: CameraTransition = CameraTransition.CUT
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["transition"] = self.transition.value
        return payload


class TwinEngineService:
    """
    Mountable subsystem for PubCast's twin-engine path.

    Design goals:
    - main.py remains the host and lifecycle owner
    - the twin-engine can run honestly in disconnected/degraded/ready modes
    - canonical virtual camera state lives here, not scattered across handlers
    - bridge / renderer calls degrade safely instead of pretending success
    """

    def __init__(
        self,
        *,
        bridge: Any = None,
        renderer: Any = None,
        telemetry_timeout_s: float = 5.0,
    ) -> None:
        self.bridge = bridge
        self.renderer = renderer
        self.telemetry_timeout_s = telemetry_timeout_s

        self.mode: TwinEngineMode = TwinEngineMode.DISCONNECTED
        self.started_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self.last_telemetry_at: Optional[float] = None
        self.last_command_at: Optional[float] = None
        self.active_scene_id: Optional[str] = None
        self.active_camera_id: Optional[str] = None
        self.cameras: Dict[str, VirtualCameraState] = {}
        self._startup_notes: List[str] = []
        self._lock = asyncio.Lock()

    async def startup(self) -> Dict[str, Any]:
        async with self._lock:
            self.started_at = time.time()
            self._startup_notes.clear()
            self.last_error = None

            bridge_ok = await self._check_bridge()
            renderer_ok = await self._check_renderer()

            if bridge_ok and renderer_ok:
                self.mode = TwinEngineMode.READY
            elif bridge_ok or renderer_ok:
                self.mode = TwinEngineMode.DEGRADED
            else:
                self.mode = TwinEngineMode.DISCONNECTED

            if not self.cameras:
                self._seed_default_cameras()

            logger.info("Twin engine startup complete: %s", self.mode.value)
            return self.health()

    async def shutdown(self) -> None:
        async with self._lock:
            for component in (self.renderer, self.bridge):
                close = getattr(component, "close", None)
                aclose = getattr(component, "aclose", None)
                shutdown = getattr(component, "shutdown", None)
                try:
                    if callable(aclose):
                        await aclose()
                    elif callable(shutdown):
                        result = shutdown()
                        if asyncio.iscoroutine(result):
                            await result
                    elif callable(close):
                        result = close()
                        if asyncio.iscoroutine(result):
                            await result
                except Exception as exc:
                    logger.warning("Twin engine shutdown cleanup failed: %s", exc)
            self.mode = TwinEngineMode.DISCONNECTED

    def register_camera(self, camera: VirtualCameraState) -> None:
        self.cameras[camera.camera_id] = camera
        if self.active_camera_id is None:
            self.active_camera_id = camera.camera_id
            camera.active = True

    async def set_scene(self, scene_id: str) -> Dict[str, Any]:
        async with self._lock:
            self.active_scene_id = scene_id
            self.last_command_at = time.time()
            await self._send_bridge_command("LOAD_SCENE", {"scene_id": scene_id})
            return self.health()

    async def activate_camera(
        self,
        camera_id: str,
        *,
        transition: CameraTransition = CameraTransition.CUT,
    ) -> Dict[str, Any]:
        async with self._lock:
            if camera_id not in self.cameras:
                raise KeyError(f"Unknown camera: {camera_id}")

            if self.active_camera_id and self.active_camera_id in self.cameras:
                self.cameras[self.active_camera_id].active = False

            camera = self.cameras[camera_id]
            camera.active = True
            camera.transition = transition
            camera.updated_at = time.time()
            self.active_camera_id = camera_id
            self.last_command_at = camera.updated_at

            await self._send_bridge_command(
                "ACTIVATE_CAMERA",
                {
                    "camera": camera.to_dict(),
                    "scene_id": self.active_scene_id,
                },
            )
            return camera.to_dict()

    async def update_camera_pose(
        self,
        camera_id: str,
        *,
        position: Optional[Dict[str, float]] = None,
        rotation: Optional[Dict[str, float]] = None,
        fov: Optional[float] = None,
        target_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with self._lock:
            if camera_id not in self.cameras:
                raise KeyError(f"Unknown camera: {camera_id}")

            camera = self.cameras[camera_id]
            if position:
                camera.position = Vec3(**{**asdict(camera.position), **position})
            if rotation:
                camera.rotation = Vec3(**{**asdict(camera.rotation), **rotation})
            if fov is not None:
                camera.fov = float(fov)
            if target_id is not None:
                camera.target_id = target_id
            camera.updated_at = time.time()
            self.last_command_at = camera.updated_at

            if camera.active:
                await self._send_bridge_command(
                    "UPDATE_CAMERA",
                    {
                        "camera": camera.to_dict(),
                        "scene_id": self.active_scene_id,
                    },
                )
            return camera.to_dict()

    async def ingest_telemetry(self, telemetry: Dict[str, Any]) -> None:
        async with self._lock:
            self.last_telemetry_at = time.time()
            renderer_state = telemetry.get("renderer_state")
            if renderer_state == "ready":
                self.mode = TwinEngineMode.READY
            elif renderer_state == "degraded":
                self.mode = TwinEngineMode.DEGRADED

    def health(self) -> Dict[str, Any]:
        now = time.time()
        telemetry_age = None
        if self.last_telemetry_at is not None:
            telemetry_age = round(now - self.last_telemetry_at, 3)

        bridge_connected = bool(
            getattr(self.bridge, "is_connected", False)
            or getattr(self.bridge, "connected", False)
        )

        return {
            "ok": self.mode in {TwinEngineMode.READY, TwinEngineMode.DEGRADED},
            "mode": self.mode.value,
            "started_at": self.started_at,
            "active_scene_id": self.active_scene_id,
            "active_camera_id": self.active_camera_id,
            "camera_count": len(self.cameras),
            "bridge_connected": bridge_connected,
            "renderer_available": self.renderer is not None,
            "last_telemetry_at": self.last_telemetry_at,
            "telemetry_age_s": telemetry_age,
            "last_command_at": self.last_command_at,
            "last_error": self.last_error,
            "startup_notes": list(self._startup_notes),
            "cameras": [camera.to_dict() for camera in self.cameras.values()],
        }

    async def handle_command(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        action = payload.get("action")
        if action == "health":
            return self.health()
        if action == "set_scene":
            return await self.set_scene(str(payload["scene_id"]))
        if action == "activate_camera":
            transition = CameraTransition(payload.get("transition", "cut"))
            return await self.activate_camera(str(payload["camera_id"]), transition=transition)
        if action == "update_camera_pose":
            return await self.update_camera_pose(
                str(payload["camera_id"]),
                position=payload.get("position"),
                rotation=payload.get("rotation"),
                fov=payload.get("fov"),
                target_id=payload.get("target_id"),
            )
        raise ValueError(f"Unknown twin-engine action: {action}")

    async def _check_bridge(self) -> bool:
        if self.bridge is None:
            self._startup_notes.append("Bridge unavailable; running without external renderer bridge.")
            return False

        try:
            connect = getattr(self.bridge, "connect", None)
            start = getattr(self.bridge, "start", None)
            if callable(connect):
                result = connect()
                if asyncio.iscoroutine(result):
                    await result
            elif callable(start):
                result = start()
                if asyncio.iscoroutine(result):
                    await result

            if bool(getattr(self.bridge, "is_connected", False) or getattr(self.bridge, "connected", False)):
                return True
            self._startup_notes.append("Bridge present but not connected.")
            return False
        except Exception as exc:
            self.last_error = f"bridge startup failed: {exc}"
            self._startup_notes.append("Bridge startup failed; twin engine degraded.")
            logger.warning("Twin engine bridge check failed: %s", exc)
            return False

    async def _check_renderer(self) -> bool:
        if self.renderer is None:
            self._startup_notes.append("Renderer unavailable; virtual camera state only.")
            return False

        try:
            health = getattr(self.renderer, "health", None)
            status = getattr(self.renderer, "get_status", None)
            if callable(health):
                result = health()
                if asyncio.iscoroutine(result):
                    result = await result
                if isinstance(result, dict) and result.get("ok"):
                    return True
            elif callable(status):
                result = status()
                if asyncio.iscoroutine(result):
                    result = await result
                if isinstance(result, dict) and result.get("ok"):
                    return True
            self._startup_notes.append("Renderer responded without healthy status.")
            return False
        except Exception as exc:
            self.last_error = f"renderer startup failed: {exc}"
            self._startup_notes.append("Renderer startup failed; twin engine degraded.")
            logger.warning("Twin engine renderer check failed: %s", exc)
            return False

    async def _send_bridge_command(self, command: str, payload: Dict[str, Any]) -> None:
        if self.bridge is None or not bool(getattr(self.bridge, "is_connected", False) or getattr(self.bridge, "connected", False)):
            return

        try:
            send_command = getattr(self.bridge, "send_command", None)
            if callable(send_command):
                result = send_command(command, payload)
                if asyncio.iscoroutine(result):
                    await result
        except Exception as exc:
            self.last_error = f"bridge command failed: {exc}"
            self.mode = TwinEngineMode.DEGRADED
            logger.warning("Twin engine command send failed: %s", exc)

    def _seed_default_cameras(self) -> None:
        defaults = [
            VirtualCameraState(
                camera_id="main",
                name="Main",
                position=Vec3(0.0, 1.7, 4.5),
                rotation=Vec3(0.0, 180.0, 0.0),
                fov=60.0,
                active=True,
            ),
            VirtualCameraState(
                camera_id="wide",
                name="Wide",
                position=Vec3(0.0, 2.4, 7.5),
                rotation=Vec3(-6.0, 180.0, 0.0),
                fov=75.0,
            ),
            VirtualCameraState(
                camera_id="closeup",
                name="Closeup",
                position=Vec3(1.0, 1.65, 2.6),
                rotation=Vec3(0.0, 195.0, 0.0),
                fov=42.0,
            ),
            VirtualCameraState(
                camera_id="overhead",
                name="Overhead",
                position=Vec3(0.0, 5.8, 0.0),
                rotation=Vec3(-90.0, 180.0, 0.0),
                fov=55.0,
            ),
        ]
        for camera in defaults:
            self.register_camera(camera)


async def mount_twin_engine(app: Any, *, bridge: Any = None, renderer: Any = None) -> TwinEngineService:
    service = TwinEngineService(bridge=bridge, renderer=renderer)
    await service.startup()
    app.state.twin_engine = service
    return service


async def twin_engine_status(app: Any) -> Dict[str, Any]:
    service = getattr(app.state, "twin_engine", None)
    if service is None:
        return {
            "ok": False,
            "mode": TwinEngineMode.DISCONNECTED.value,
            "reason": "Twin engine not mounted.",
        }
    return service.health()


def install_twin_engine_routes(app: Any) -> None:
    @app.get("/api/twin/status")
    async def api_twin_status() -> Dict[str, Any]:
        return await twin_engine_status(app)

    @app.post("/api/twin/scene")
    async def api_twin_scene(payload: Dict[str, Any]) -> Dict[str, Any]:
        service = _require_twin_engine(app)
        scene_id = str(payload.get("scene_id") or "").strip()
        if not scene_id:
            raise ValueError("scene_id is required")
        return await service.set_scene(scene_id)

    @app.post("/api/twin/camera/activate")
    async def api_twin_camera_activate(payload: Dict[str, Any]) -> Dict[str, Any]:
        service = _require_twin_engine(app)
        camera_id = str(payload.get("camera_id") or "").strip()
        if not camera_id:
            raise ValueError("camera_id is required")
        transition = CameraTransition(str(payload.get("transition", "cut")))
        return await service.activate_camera(camera_id, transition=transition)

    @app.post("/api/twin/camera/pose")
    async def api_twin_camera_pose(payload: Dict[str, Any]) -> Dict[str, Any]:
        service = _require_twin_engine(app)
        camera_id = str(payload.get("camera_id") or "").strip()
        if not camera_id:
            raise ValueError("camera_id is required")
        return await service.update_camera_pose(
            camera_id,
            position=payload.get("position"),
            rotation=payload.get("rotation"),
            fov=payload.get("fov"),
            target_id=payload.get("target_id"),
        )

    @app.post("/api/twin/command")
    async def api_twin_command(payload: Dict[str, Any]) -> Dict[str, Any]:
        service = _require_twin_engine(app)
        return await service.handle_command(payload)


def _require_twin_engine(app: Any) -> TwinEngineService:
    service = getattr(app.state, "twin_engine", None)
    if service is None:
        raise RuntimeError("Twin engine not mounted")
    return service
