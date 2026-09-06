"""
camera_engine_bridge.py — Python↔Rust CameraEngine bridge
═══════════════════════════════════════════════════════════

Connects modules/cameras.py CameraManager to the Rust pubcast_camera_engine
crate via WebSocket commands to ws_renderer (the existing, tested bridge
from Run 2/3).

WHAT IT DOES:
  When a VOXEL_3D CameraSource is set as program or preview, this bridge
  translates the Python CameraManager state into Rust EngineMode commands
  and sends them over the live ws_renderer WebSocket connection.

WHAT IT DOES NOT DO:
  It does not replace the existing CameraManager.
  It does not affect NDI/RTMP/SRT/VIRTUAL camera sources.
  It only activates for VOXEL_3D transport sources.

INTEGRATION POINT:
  Call bridge.on_program_switch(source_id) after main.cameras.set_program_source()
  Call bridge.on_preview_switch(source_id) after main.cameras.set_preview_source()
  Both calls in main.py's /api/cameras/program and /api/cameras/preview routes.

Rear View Foresight LLC — Feic Mo Chroí — 2026-08-24
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.cameras import CameraManager, CameraSource, CameraTransport

logger = logging.getLogger("pubcast.camera_engine_bridge")

# Map Python program/preview states to Rust EngineMode variants
# Matches pubcast_camera_engine/src/camera.rs enum EngineMode
RUST_MODE_PROGRAM    = "Program"
RUST_MODE_PREVIEW    = "Preview"
RUST_MODE_DONOR      = "Donor"
RUST_MODE_TRANSITION = "Transition"


class CameraEngineBridge:
    """
    Translates CameraManager state changes into Rust CameraEngine mode commands.

    Maintains a lightweight registry of which camera_ids have active
    Rust CameraEngine instances, and sends mode-switch commands via the
    ws_renderer WebSocket connection whenever a VOXEL_3D source switches
    program or preview state.
    """

    def __init__(self, cameras: "CameraManager") -> None:
        self._cameras = cameras
        self._ws: Optional[Any] = None  # ws_renderer WebSocket connection
        self._connected = False
        # Track which VOXEL_3D sources have engine instances in Rust
        self._engine_ids: set[str] = set()

    def set_connection(self, ws: Any) -> None:
        """
        Register the ws_renderer WebSocket connection.
        Called after AvatarPerformerManager starts — same connection,
        different command type.
        """
        self._ws = ws
        self._connected = ws is not None
        logger.info("CameraEngineBridge: renderer connection %s",
                    "registered" if self._connected else "cleared")

    def _is_voxel_source(self, source_id: str) -> bool:
        """True if source_id refers to a VOXEL_3D camera source."""
        src = self._cameras.get(source_id)
        if src is None:
            return False
        # Avoid importing CameraTransport at module load (circular-safe)
        return str(src.transport) in ("voxel_3d", "CameraTransport.VOXEL_3D")

    async def on_program_switch(self, source_id: str) -> None:
        """
        Called after cameras.set_program_source(source_id).
        If the source is VOXEL_3D, send EngineMode::Program to Rust.
        Demote the previous program to Donor mode.
        """
        if not self._is_voxel_source(source_id):
            return

        src = self._cameras.get(source_id)
        await self._send_mode(source_id, RUST_MODE_PROGRAM, src)

        # Current preview becomes donor — it was warming up, now stands by
        prev_preview = self._cameras.get_preview_source()
        if prev_preview and prev_preview.source_id != source_id:
            if self._is_voxel_source(prev_preview.source_id):
                await self._send_mode(prev_preview.source_id, RUST_MODE_DONOR, prev_preview)

    async def on_preview_switch(self, source_id: str) -> None:
        """
        Called after cameras.set_preview_source(source_id).
        If the source is VOXEL_3D, send EngineMode::Transition (starts preheat)
        to Rust. Preview enters Transition → warms up → becomes Preview once
        FPS > 55 and min preheat time has elapsed.
        """
        if not self._is_voxel_source(source_id):
            return

        src = self._cameras.get(source_id)
        # Transition mode starts the 2000ms preheat sequence in Rust
        await self._send_mode(source_id, RUST_MODE_TRANSITION, src)

    async def _send_mode(
        self,
        camera_id: str,
        mode: str,
        src: Optional["CameraSource"],
    ) -> None:
        """
        Send a CAMERA_MODE_SWITCH command to the Rust CameraEngine via
        the ws_renderer WebSocket.

        The Rust side reads this as a BridgeMotionPayload with a
        camera-specific event_type that the CameraEngine dispatch loop
        handles separately from avatar frame data.
        """
        if not self._connected or self._ws is None:
            logger.debug(
                "CameraEngineBridge: no renderer connection, "
                "queuing mode %s for %s (no-op until connected)",
                mode, camera_id,
            )
            return

        payload: Dict[str, Any] = {
            "event_type": "CAMERA_MODE_SWITCH",
            "camera_id": camera_id,
            "mode": mode,
        }

        # Include 3D placement so Rust can update the camera's world transform
        if src is not None:
            payload["position"] = getattr(src, "position", [0.0, 0.0, 0.0])
            payload["rotation"] = getattr(src, "rotation", [0.0, 0.0, 0.0])
            payload["fov"]      = getattr(src, "fov", 60.0)

        try:
            await self._ws.send(json.dumps(payload))
            logger.info(
                "CameraEngineBridge: %s → mode=%s pos=%s fov=%.1f",
                camera_id, mode,
                payload.get("position", [0, 0, 0]),
                payload.get("fov", 60.0),
            )
        except Exception as exc:  # noqa: BLE001 — never break a camera switch
            logger.warning(
                "CameraEngineBridge: failed to send mode %s for %s: %s",
                mode, camera_id, exc,
            )

    async def register_voxel_camera(self, source_id: str) -> None:
        """
        Tell the Rust engine to initialize a CameraEngine instance for this
        source_id and put it in Donor mode (standby, low resource use).
        """
        src = self._cameras.get(source_id)
        if src is None or not self._is_voxel_source(source_id):
            return

        self._engine_ids.add(source_id)
        await self._send_mode(source_id, RUST_MODE_DONOR, src)
        logger.info("CameraEngineBridge: registered voxel camera %s", source_id)

    async def boot_voxel_cameras(self) -> None:
        """
        Register all currently-known VOXEL_3D sources with the Rust engine.
        Call once after the renderer connection is established.
        """
        for src in self._cameras.list_sources():
            if self._is_voxel_source(src.source_id):
                await self.register_voxel_camera(src.source_id)

        prog = self._cameras.get_program_source()
        prev = self._cameras.get_preview_source()

        if prog and self._is_voxel_source(prog.source_id):
            await self._send_mode(prog.source_id, RUST_MODE_PROGRAM, prog)
        if prev and self._is_voxel_source(prev.source_id):
            await self._send_mode(prev.source_id, RUST_MODE_PREVIEW, prev)

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def voxel_camera_count(self) -> int:
        return len(self._engine_ids)
