"""
modules/pubcast_take_manager.py

Deterministic performance takes for PubCast AI.

THE CONCEPT (from the session that motivated this):
    Record a performance once as DATA — not as pixels.
    Every avatar position, rotation, and bone state at every tick is captured
    and saved to disk. Then replay that data identically as many times as you
    want, shooting from a different camera each time, changing the lighting,
    adjusting the set — all without asking anyone to perform again.

    The assembled master is itself a data stream: stitch the best segment of
    Take 3 onto the best segment of Take 7, and render the composite from any
    camera angle you choose. The camera and the performance are fully
    decoupled.

HOW IT WORKS WITH EXISTING INFRASTRUCTURE:
    choreography_runtime.py already has:
        Choreography.recording = True  →  record_frame() runs every tick
        Choreography.recorded_frames   →  [{time, avatars: [{id, state, skeleton}]}]
        Choreography.export_json(path) →  saves steps + recorded_frames

    choreography_controller.py's _runner() already:
        - calls choreo.update() every tick  → that calls record_frame()
        - broadcasts choreo_frame WebSocket event with real positions/skeletons

    REPLAY works by bypassing choreo.update() and instead injecting
    recorded frame data directly into the avatar states, then letting the
    controller broadcast the same choreo_frame event as if live. The camera,
    the renderer, and the recording pipeline never know the difference.

ROUTES (registered via create_take_router(choreo_controller)):
    POST  /api/choreo/take/start           start recording a live take
    POST  /api/choreo/take/stop            stop and save the take
    GET   /api/choreo/take/list            list saved takes
    POST  /api/choreo/take/replay          replay a saved take
    POST  /api/choreo/take/replay/stop     stop replay
    POST  /api/choreo/take/composite       assemble segments into a master take
    GET   /api/choreo/take/{take_id}       metadata for a specific take

VERIFIED before writing:
    - choreo_controller._choreo is the live Choreography instance
    - choreo_controller._choreo.recording triggers record_frame()
    - choreo_controller._choreo.recorded_frames accumulates the data
    - choreo_controller._runner broadcasts {type: choreo_frame, payload: {time, avatars, room}}
    - choreo_controller._hub.broadcast_system_event() is the broadcast path
    - AvatarSim has: id, position[3], rotation[3], get_full_skeleton_data(), apply_pose_data()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator

logger = logging.getLogger("pubcast.take_manager")


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TakeSegment:
    """A marked region of a single take to include in a composite."""
    take_id: str
    in_time: float   # seconds from start of that take
    out_time: float  # seconds from start of that take
    label: str = ""

    def __post_init__(self):
        if self.out_time <= self.in_time:
            raise ValueError(f"out_time ({self.out_time}) must be > in_time ({self.in_time})")


@dataclass
class TakeMeta:
    """Saved metadata for a completed take (the frame data lives in the JSON)."""
    take_id: str
    scene_id: str
    label: str
    recorded_at: float
    duration: float
    frame_count: int
    tick_hz: float
    avatar_ids: List[str]
    path: str          # absolute path to the JSON file


# ═══════════════════════════════════════════════════════════════════════════════
# PYDANTIC REQUEST MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class StartTakeRequest(BaseModel):
    scene_id: str = "default"
    label: str = ""

class StopTakeRequest(BaseModel):
    pass  # nothing needed — state is on the server

class ReplayRequest(BaseModel):
    take_id: str
    room: str = "studio"
    speed: float = 1.0   # 1.0 = real-time, 0.5 = half-speed

    @validator("speed")
    def speed_in_range(cls, v):
        if not 0.1 <= v <= 4.0:
            raise ValueError("speed must be between 0.1 and 4.0")
        return v

class CompositeRequest(BaseModel):
    scene_id: str = "composite"
    label: str = ""
    segments: List[Dict[str, Any]]   # [{take_id, in_time, out_time, label?}]

    @validator("segments")
    def at_least_one(cls, v):
        if not v:
            raise ValueError("segments must not be empty")
        return v


# ═══════════════════════════════════════════════════════════════════════════════
# TAKE MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class TakeManager:
    """
    Owns the take lifecycle: start, stop, persist, replay, composite.
    Designed to sit alongside an existing ChoreographyController without
    modifying it — it reaches in to set flags and read state, but never
    replaces the controller's own tick loop.
    """

    def __init__(self, choreo_controller: Any, storage_dir: Optional[Path] = None):
        self._ctrl = choreo_controller
        self._dir  = Path(storage_dir or "data/takes")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "index.json"
        self._index: Dict[str, TakeMeta] = self._load_index()

        # Mutable state
        self._recording_take_id: Optional[str] = None
        self._recording_scene_id: Optional[str] = None
        self._recording_label: Optional[str] = None
        self._recording_started: Optional[float] = None

        self._replay_task: Optional[asyncio.Task] = None
        self._replay_active: bool = False

    # ── Index ──────────────────────────────────────────────────────────────────

    def _load_index(self) -> Dict[str, TakeMeta]:
        if not self._index_path.exists():
            return {}
        try:
            raw = json.loads(self._index_path.read_text())
            return {k: TakeMeta(**v) for k, v in raw.items()}
        except Exception as exc:
            logger.warning("Could not load take index, starting fresh: %s", exc)
            return {}

    def _save_index(self) -> None:
        self._index_path.write_text(
            json.dumps({k: asdict(v) for k, v in self._index.items()}, indent=2)
        )

    # ── Recording ──────────────────────────────────────────────────────────────

    def start_recording(self, scene_id: str = "default", label: str = "") -> str:
        """
        Activate recording on the live choreography.

        Sets Choreography.recording = True so that _runner's existing
        choreo.update() call triggers record_frame() every tick. The frame
        data accumulates in Choreography.recorded_frames.
        """
        choreo = getattr(self._ctrl, "_choreo", None)
        if choreo is None:
            raise RuntimeError(
                "No active choreography. Start a choreo session first "
                "via POST /api/choreo/start."
            )
        if self._recording_take_id:
            raise RuntimeError(
                f"Take {self._recording_take_id} is already recording. "
                "Stop it before starting a new one."
            )

        take_id = f"take_{uuid.uuid4().hex[:12]}"
        choreo.recorded_frames.clear()
        choreo.recording = True

        self._recording_take_id  = take_id
        self._recording_scene_id = scene_id
        self._recording_label    = label or f"Take {len(self._index) + 1}"
        self._recording_started  = time.time()

        logger.info("Recording started: %s (scene=%s)", take_id, scene_id)
        return take_id

    def stop_recording(self) -> TakeMeta:
        """
        Stop recording and persist the take.

        Clears Choreography.recording and saves the accumulated frame data
        to disk. Returns metadata for the completed take.
        """
        choreo = getattr(self._ctrl, "_choreo", None)
        if choreo is None or not self._recording_take_id:
            raise RuntimeError("No take is currently recording.")

        choreo.recording = False
        frames = list(choreo.recorded_frames)
        choreo.recorded_frames.clear()

        take_id  = self._recording_take_id
        scene_id = self._recording_scene_id or "default"
        label    = self._recording_label or take_id
        started  = self._recording_started or time.time()
        tick_hz  = float(getattr(self._ctrl, "_tick_hz", 30.0))

        self._recording_take_id  = None
        self._recording_scene_id = None
        self._recording_label    = None
        self._recording_started  = None

        if not frames:
            raise RuntimeError("Take was empty — no frames were captured.")

        duration = frames[-1]["time"] if frames else 0.0

        # All avatar IDs that appeared in any frame
        avatar_ids = list({
            av["id"] for frame in frames for av in frame.get("avatars", [])
        })

        # Persist
        path = self._dir / f"{take_id}.json"
        path.write_text(json.dumps({
            "take_id":    take_id,
            "scene_id":   scene_id,
            "label":      label,
            "recorded_at": started,
            "tick_hz":    tick_hz,
            "frames":     frames,
        }, indent=2))

        meta = TakeMeta(
            take_id=take_id, scene_id=scene_id, label=label,
            recorded_at=started, duration=duration, frame_count=len(frames),
            tick_hz=tick_hz, avatar_ids=avatar_ids, path=str(path),
        )
        self._index[take_id] = meta
        self._save_index()

        logger.info("Take saved: %s  frames=%d  duration=%.2fs  path=%s",
                    take_id, len(frames), duration, path)
        return meta

    # ── Replay ─────────────────────────────────────────────────────────────────

    def _load_frames(self, take_id: str) -> List[Dict]:
        if take_id not in self._index:
            raise KeyError(f"Unknown take: {take_id}")
        path = Path(self._index[take_id].path)
        if not path.exists():
            raise FileNotFoundError(f"Take file missing: {path}")
        data = json.loads(path.read_text())
        frames = data.get("frames", [])
        if not frames:
            raise ValueError(f"Take {take_id} contains no frames.")
        return frames

    async def replay(self, take_id: str, room: str = "studio", speed: float = 1.0) -> None:
        """
        Replay a saved take by injecting its frames directly into the
        controller's avatar states and broadcasting the same choreo_frame
        WebSocket event that a live run would emit.

        The camera, renderer, and recording pipeline are unaffected — from
        their perspective this is indistinguishable from a live performance.
        Speed < 1.0 slows replay (for detailed review), > 1.0 speeds it up.
        """
        if self._replay_active:
            raise RuntimeError("A replay is already running. Stop it first.")

        frames = self._load_frames(take_id)
        self._replay_active = True

        async def _run():
            try:
                logger.info("Replay starting: %s  frames=%d  speed=%.1fx",
                            take_id, len(frames), speed)

                hub = getattr(self._ctrl, "_hub", None)

                for i, frame in enumerate(frames):
                    if not self._replay_active:
                        break

                    # Apply this frame's data to the live avatar state
                    avatars = getattr(self._ctrl, "_avatars", [])
                    avatar_map = {a.id: a for a in avatars}

                    for av_data in frame.get("avatars", []):
                        av = avatar_map.get(av_data["id"])
                        if av is None:
                            continue
                        state = av_data.get("state", {})
                        if "position" in state:
                            av.position = list(state["position"])
                        if "rotation" in state:
                            av.rotation = list(state["rotation"])
                        skeleton = av_data.get("skeleton", {})
                        if skeleton and hasattr(av, "apply_pose_data"):
                            av.apply_pose_data(skeleton)

                    # Broadcast the same event shape the live runner emits,
                    # so every listener — cameras, PubWorld, recording pipeline
                    # — gets exactly what they would from a live performance.
                    if hub is not None:
                        await hub.broadcast_system_event({
                            "type": "choreo_frame",
                            "payload": {
                                "time": frame["time"],
                                "avatars": [
                                    {
                                        "id": a.id,
                                        "position": list(a.position),
                                        "rotation": list(a.rotation),
                                        "skeleton": a.get_full_skeleton_data(),
                                    }
                                    for a in avatars
                                ],
                                "room": room,
                                "replay": True,    # lets interested listeners know
                                "take_id": take_id,
                            },
                        })

                    # Timing: hold this frame for the same duration it had during
                    # recording, adjusted for speed. The controller's recorded_at
                    # timestamps give us that duration exactly.
                    if i < len(frames) - 1:
                        gap = frames[i + 1]["time"] - frame["time"]
                        await asyncio.sleep(max(0.0, gap / speed))

                # Signal clean completion
                if hub is not None:
                    await hub.broadcast_system_event({
                        "type": "choreo_complete",
                        "payload": {
                            "room": room,
                            "take_id": take_id,
                            "replay": True,
                            "time": frames[-1]["time"] if frames else 0.0,
                        },
                    })
                logger.info("Replay complete: %s", take_id)

            except asyncio.CancelledError:
                logger.info("Replay cancelled: %s", take_id)
            except Exception as exc:
                logger.exception("Replay error for take %s: %s", take_id, exc)
            finally:
                self._replay_active = False

        self._replay_task = asyncio.create_task(_run())

    async def stop_replay(self) -> None:
        self._replay_active = False
        if self._replay_task and not self._replay_task.done():
            self._replay_task.cancel()
            try:
                await self._replay_task
            except asyncio.CancelledError:
                pass
        self._replay_task = None

    # ── Compositor ─────────────────────────────────────────────────────────────

    def composite(
        self,
        segments: List[TakeSegment],
        scene_id: str = "composite",
        label: str = "",
    ) -> TakeMeta:
        """
        Assemble the best segments from multiple takes into a single master
        take. The result is itself a take — it can be replayed, re-composited,
        or used as the source for more takes.

        Timeline stitching: each segment's frames are extracted, re-timed so
        they flow continuously (no gaps or jumps), and merged. The result is
        a new JSON file in the takes directory indexed alongside originals.

        Example:
            Take 3, 0.0s→8.0s  →  Walk-on and greeting  (best of three tries)
            Take 7, 4.5s→12.0s →  The speech             (only good take)
            Take 3, 18.0s→24.0s →  The exit              (same performer, later)
        """
        composite_frames: List[Dict] = []
        clock = 0.0

        if not segments:
            raise ValueError("composite() requires at least one segment — received an empty list.")

        for seg in segments:
            frames = self._load_frames(seg.take_id)

            # Extract frames within [in_time, out_time]
            segment_frames = [
                f for f in frames
                if seg.in_time <= f["time"] <= seg.out_time
            ]

            if not segment_frames:
                logger.warning(
                    "Segment from take %s [%.2f→%.2f] matched no frames (take has %.2f→%.2f)",
                    seg.take_id,
                    seg.in_time, seg.out_time,
                    frames[0]["time"] if frames else 0.0,
                    frames[-1]["time"] if frames else 0.0,
                )
                continue

            # Re-time to flow continuously from the current clock position.
            # Preserve internal timing within the segment exactly.
            origin = segment_frames[0]["time"]
            for f in segment_frames:
                composite_frames.append({
                    "time": clock + (f["time"] - origin),
                    "avatars": f["avatars"],
                    "_source": {"take_id": seg.take_id, "original_time": f["time"]},
                })

            if segment_frames:
                clock += segment_frames[-1]["time"] - origin

        if not composite_frames:
            raise ValueError("Composite produced no frames. Check segment in/out times.")

        take_id = f"take_comp_{uuid.uuid4().hex[:12]}"
        avatar_ids = list({
            av["id"]
            for frame in composite_frames
            for av in frame.get("avatars", [])
        })
        duration = composite_frames[-1]["time"]

        path = self._dir / f"{take_id}.json"
        path.write_text(json.dumps({
            "take_id":     take_id,
            "scene_id":    scene_id,
            "label":       label or f"Composite of {len(segments)} segments",
            "recorded_at": time.time(),
            "tick_hz":     getattr(self._ctrl, "_tick_hz", 30.0),
            "frames":      composite_frames,
            "composite":   [asdict(s) for s in segments],
        }, indent=2))

        meta = TakeMeta(
            take_id=take_id, scene_id=scene_id,
            label=label or f"Composite ({len(segments)} segments)",
            recorded_at=time.time(), duration=duration,
            frame_count=len(composite_frames),
            tick_hz=getattr(self._ctrl, "_tick_hz", 30.0),
            avatar_ids=avatar_ids, path=str(path),
        )
        self._index[take_id] = meta
        self._save_index()

        logger.info("Composite take created: %s  frames=%d  duration=%.2fs",
                    take_id, len(composite_frames), duration)
        return meta

    # ── Queries ────────────────────────────────────────────────────────────────

    def list_takes(self, scene_id: Optional[str] = None) -> List[TakeMeta]:
        takes = list(self._index.values())
        if scene_id:
            takes = [t for t in takes if t.scene_id == scene_id]
        return sorted(takes, key=lambda t: t.recorded_at, reverse=True)

    def get_take(self, take_id: str) -> TakeMeta:
        if take_id not in self._index:
            raise KeyError(take_id)
        return self._index[take_id]

    @property
    def is_recording(self) -> bool:
        return self._recording_take_id is not None

    @property
    def is_replaying(self) -> bool:
        return self._replay_active


# ═══════════════════════════════════════════════════════════════════════════════
# FASTAPI ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

def create_take_router(choreo_controller: Any,
                       storage_dir: Optional[Path] = None) -> APIRouter:
    router  = APIRouter(prefix="/api/choreo/take", tags=["Takes"])
    manager = TakeManager(choreo_controller, storage_dir)

    @router.post("/start")
    async def start_take(req: StartTakeRequest):
        """Start recording the live choreography as a new take."""
        try:
            take_id = manager.start_recording(req.scene_id, req.label)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        return {"take_id": take_id, "recording": True, "scene_id": req.scene_id}

    @router.post("/stop")
    async def stop_take(_: StopTakeRequest = StopTakeRequest()):
        """Stop the active recording and persist the take."""
        try:
            meta = manager.stop_recording()
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        return asdict(meta)

    @router.get("/list")
    async def list_takes(scene_id: Optional[str] = None):
        return [asdict(t) for t in manager.list_takes(scene_id)]

    @router.get("/{take_id}")
    async def get_take(take_id: str):
        try:
            return asdict(manager.get_take(take_id))
        except KeyError:
            raise HTTPException(404, f"Take not found: {take_id}")

    @router.post("/replay")
    async def replay_take(req: ReplayRequest):
        """Replay a saved take. Identical to a live performance from every listener's perspective."""
        try:
            await manager.replay(req.take_id, req.room, req.speed)
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(404, str(exc))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        meta = manager.get_take(req.take_id)
        return {
            "replaying": True,
            "take_id":   req.take_id,
            "label":     meta.label,
            "duration":  meta.duration,
            "speed":     req.speed,
            "room":      req.room,
        }

    @router.post("/replay/stop")
    async def stop_replay():
        await manager.stop_replay()
        return {"replaying": False}

    @router.post("/composite")
    async def composite_takes(req: CompositeRequest):
        """
        Stitch the best segments from multiple takes into a new master take.
        The result is a first-class take — it can itself be replayed, re-shot,
        or composited again.
        """
        try:
            segments = [
                TakeSegment(
                    take_id=s["take_id"],
                    in_time=float(s["in_time"]),
                    out_time=float(s["out_time"]),
                    label=s.get("label", ""),
                )
                for s in req.segments
            ]
            meta = manager.composite(segments, req.scene_id, req.label)
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(404, str(exc))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))
        return asdict(meta)

    @router.get("/status/current")
    async def take_status():
        return {
            "recording":      manager.is_recording,
            "replaying":      manager.is_replaying,
            "active_take_id": manager._recording_take_id,
            "total_takes":    len(manager._index),
        }

    return router
