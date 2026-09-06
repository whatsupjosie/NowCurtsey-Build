"""
virtual_camera_bus.py — Virtual Camera Frame Transport
════════════════════════════════════════════════════════

The pipe between the 3D renderer and everything that needs to see it.

ARCHITECTURE (important — this is the thing that was misunderstood):

  PubCast's virtual cameras live inside a 3D scene. There is no server-side
  rasterizer — `ws_renderer.rs` computes skeleton world matrices and stops at
  a "RENDER BACKEND INTEGRATION POINT" comment. The actual renderer is the
  browser: three.js / WebGL drawing avatars and voxel sets, with a
  THREE.PerspectiveCamera per virtual camera.

  So pixels originate CLIENT-side and flow INWARD:

      browser three.js scene
        └─ PerspectiveCamera "cam_wide"
             └─ renderer.render(scene, camWide)
                  └─ canvas.toDataURL("image/jpeg", q)
                       └─ POST /api/cameras/{id}/frame
                            └─ VirtualCameraBus
                                 ├─ control room monitors  (GET .../frame)
                                 ├─ recording sink         (write to disk)
                                 └─ program/preview routing

  A USB webcam is an INPUT for mocap and guest video. It is not what films
  the show. The show is filmed by virtual cameras inside the 3D world.

WHY A BUS AND NOT DIRECT WIRING:
  Multiple consumers want the same frame at different rates — a monitor
  refreshes at 15fps, a recorder wants every frame, a thumbnail wants one
  every few seconds. The bus holds the latest frame per camera plus optional
  recording taps, so producers push once and consumers pull at their own pace.

Rear View Foresight LLC — Feic Mo Chroí — 2026-08-24
"""
from __future__ import annotations

import base64
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pubcast.virtual_camera_bus")


@dataclass
class CameraFrame:
    """One rendered frame from a virtual camera."""
    camera_id: str
    data: bytes
    mime_type: str
    width: int
    height: int
    received_at: float
    frame_number: int
    # Where the virtual camera was when this frame was rendered
    position: Optional[List[float]] = None
    rotation: Optional[List[float]] = None
    fov: Optional[float] = None

    @property
    def age_ms(self) -> float:
        return (time.time() - self.received_at) * 1000.0


@dataclass
class CameraFeedStats:
    camera_id: str
    frames_received: int = 0
    bytes_received: int = 0
    first_frame_at: float = 0.0
    last_frame_at: float = 0.0
    dropped: int = 0

    @property
    def fps(self) -> float:
        """Measured over the whole feed lifetime, not instantaneous."""
        span = self.last_frame_at - self.first_frame_at
        if span <= 0 or self.frames_received < 2:
            return 0.0
        return round((self.frames_received - 1) / span, 1)

    @property
    def live(self) -> bool:
        """A feed is live if we've seen a frame in the last 2 seconds."""
        return self.last_frame_at > 0 and (time.time() - self.last_frame_at) < 2.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "frames_received": self.frames_received,
            "bytes_received": self.bytes_received,
            "fps": self.fps,
            "live": self.live,
            "last_frame_ago_ms": round((time.time() - self.last_frame_at) * 1000, 1)
                                 if self.last_frame_at else None,
            "dropped": self.dropped,
        }


class VirtualCameraBus:
    """
    Holds the latest rendered frame for each virtual camera and fans it out.

    Thread-safe: frames arrive on request handlers, recording taps write from
    a separate thread, monitors read concurrently.
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._frames: Dict[str, CameraFrame] = {}
        self._stats: Dict[str, CameraFeedStats] = {}
        self._lock = threading.RLock()
        self._counters: Dict[str, int] = {}

        # Recording taps: camera_id -> open directory for numbered frames
        self._taps: Dict[str, Path] = {}
        self._data_dir = data_dir

    # ═══ PRODUCER SIDE — the browser pushes frames in ═════════════════════════

    def publish(
        self,
        camera_id: str,
        data: bytes,
        *,
        mime_type: str = "image/jpeg",
        width: int = 0,
        height: int = 0,
        position: Optional[List[float]] = None,
        rotation: Optional[List[float]] = None,
        fov: Optional[float] = None,
    ) -> CameraFrame:
        """
        Accept a rendered frame from a virtual camera.

        Replaces whatever was there — monitors want the newest frame, not a
        backlog. Recording taps get every frame written before replacement.
        """
        now = time.time()
        with self._lock:
            n = self._counters.get(camera_id, 0) + 1
            self._counters[camera_id] = n

            frame = CameraFrame(
                camera_id=camera_id,
                data=data,
                mime_type=mime_type,
                width=width,
                height=height,
                received_at=now,
                frame_number=n,
                position=position,
                rotation=rotation,
                fov=fov,
            )
            self._frames[camera_id] = frame

            st = self._stats.setdefault(camera_id, CameraFeedStats(camera_id=camera_id))
            if st.first_frame_at == 0.0:
                st.first_frame_at = now
            st.frames_received += 1
            st.bytes_received += len(data)
            st.last_frame_at = now

            tap_dir = self._taps.get(camera_id)

        # Write outside the lock — disk I/O must not block the next frame
        if tap_dir is not None:
            try:
                ext = "jpg" if "jpeg" in mime_type else mime_type.split("/")[-1]
                (tap_dir / f"{n:08d}.{ext}").write_bytes(data)
            except Exception as exc:  # noqa: BLE001 — a bad tap must not kill the feed
                logger.warning("Recording tap write failed for %s: %s", camera_id, exc)
                with self._lock:
                    self._stats[camera_id].dropped += 1

        return frame

    def publish_data_url(self, camera_id: str, data_url: str, **kwargs) -> CameraFrame:
        """
        Convenience for browsers: accepts a canvas.toDataURL() string
        ("data:image/jpeg;base64,...") and decodes it.
        """
        if "," not in data_url:
            raise ValueError("Not a data URL")
        header, b64 = data_url.split(",", 1)
        mime = "image/jpeg"
        if header.startswith("data:") and ";" in header:
            mime = header[5:].split(";", 1)[0] or mime
        return self.publish(camera_id, base64.b64decode(b64), mime_type=mime, **kwargs)

    # ═══ CONSUMER SIDE — monitors and recorders pull frames out ═══════════════

    def latest(self, camera_id: str) -> Optional[CameraFrame]:
        with self._lock:
            return self._frames.get(camera_id)

    def live_cameras(self) -> List[str]:
        """Cameras that have produced a frame in the last 2 seconds."""
        with self._lock:
            return sorted(cid for cid, st in self._stats.items() if st.live)

    def stats(self, camera_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if camera_id:
                st = self._stats.get(camera_id)
                return st.to_dict() if st else {"camera_id": camera_id, "live": False}
            return {cid: st.to_dict() for cid, st in self._stats.items()}

    # ═══ RECORDING TAPS ═══════════════════════════════════════════════════════

    def open_tap(self, camera_id: str, session_dir: Path) -> Path:
        """
        Start writing every frame from this camera to disk.

        Frames land as numbered images, which ffmpeg can assemble into video
        afterwards. This is deliberately simple — a frame-sequence tap can't
        get out of sync the way a live encoder pipe can, and PubCast already
        has ffmpeg available for the assembly step.
        """
        out = session_dir / f"cam_{camera_id}"
        out.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._taps[camera_id] = out
        logger.info("Recording tap OPEN for camera %s → %s", camera_id, out)
        return out

    def close_tap(self, camera_id: str) -> Optional[Path]:
        with self._lock:
            path = self._taps.pop(camera_id, None)
        if path:
            logger.info("Recording tap CLOSED for camera %s", camera_id)
        return path

    def active_taps(self) -> Dict[str, str]:
        with self._lock:
            return {cid: str(p) for cid, p in self._taps.items()}

    def clear(self, camera_id: Optional[str] = None) -> None:
        with self._lock:
            if camera_id:
                self._frames.pop(camera_id, None)
                self._stats.pop(camera_id, None)
                self._counters.pop(camera_id, None)
            else:
                self._frames.clear()
                self._stats.clear()
                self._counters.clear()
