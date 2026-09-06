# PubCast AI — recording.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from zipfile import ZipFile, ZIP_DEFLATED

from .cameras import CameraManager, CameraSource

logger = logging.getLogger(__name__)


class ContainerFormat(str, Enum):
    MP4 = "mp4"
    WEBM = "webm"
    WAV = "wav"
    MOV = "mov"


@dataclass
class EncodingProfile:
    profile_id: str
    name: str
    container: ContainerFormat
    video_codec: Optional[str]
    audio_codec: Optional[str]
    video_bitrate: Optional[str]
    audio_bitrate: Optional[str]
    resolution: Optional[str]
    frame_rate: Optional[str]
    description: str = ""
    is_audio_only: bool = False


@dataclass
class RecordingArtifact:
    name: str
    format: ContainerFormat
    file_path: Path
    size_bytes: int = 0


@dataclass
class RecordingMarker:
    timestamp: float
    label: str
    operator: Optional[str] = None


class RecordingState(str, Enum):
    REQUESTED = "requested"
    COUNTDOWN = "countdown"
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    ARCHIVED = "archived"


@dataclass
class RecordingSession:
    session_id: str
    sources: List[str]
    profile_id: str
    operator: str
    preset: Optional[str] = None
    host_override: bool = False
    countdown_seconds: int = 5
    state: RecordingState = RecordingState.REQUESTED
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    artifacts: List[RecordingArtifact] = field(default_factory=list)
    markers: List[RecordingMarker] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "sources": self.sources,
            "profile_id": self.profile_id,
            "operator": self.operator,
            "preset": self.preset,
            "host_override": self.host_override,
            "countdown_seconds": self.countdown_seconds,
            "state": self.state.value,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "ended_at": self.ended_at,
            "artifacts": [
                {
                    "name": art.name,
                    "format": art.format.value,
                    "file_path": art.file_path.as_posix(),
                    "size_bytes": art.size_bytes,
                }
                for art in self.artifacts
            ],
            "markers": [
                {
                    "timestamp": marker.timestamp,
                    "label": marker.label,
                    "operator": marker.operator,
                }
                for marker in self.markers
            ],
        }


class RecordingService:
    """
    Coordinates recording sessions and maintains metadata for import/export.
    The class intentionally separates orchestration from the underlying
    capture pipeline so that future integrations (FFmpeg, cloud encoders,
    etc.) can target the same API surface.
    """

    def __init__(self, base_dir: Path, cameras: CameraManager, blackbox_witness: Optional[Any] = None) -> None:
        self.base_dir = base_dir
        self.cameras = cameras
        self.blackbox_witness = blackbox_witness
        self._profiles: Dict[str, EncodingProfile] = {}
        self._sessions: Dict[str, RecordingSession] = {}
        self._room_privacy: Dict[str, Dict[str, str]] = {}
        
        # NEW: Pipeline sessions for detailed event logging
        self._pipeline_sessions: Dict[str, Any] = {}

        self.recordings_dir = self.base_dir / "recordings"
        self.exports_dir = self.base_dir / "exports"
        self.imports_dir = self.base_dir / "imports"
        for directory in (self.recordings_dir, self.exports_dir, self.imports_dir):
            directory.mkdir(parents=True, exist_ok=True)

        self._storage_cache = {
            "local_free_gb": 240,
            "cloud_used_gb": 1200,
            "backup_status": "syncing",
        }

    def _blackbox_event(self, event_type: str, *, actor: str = "SYS", data: Optional[Dict[str, Any]] = None) -> None:
        if self.blackbox_witness is not None:
            self.blackbox_witness.record_event(event_type, source="recording", actor=actor, data=data or {})

    # ------------------------------------------------------------------
    # Profiles
    def register_profile(self, profile: EncodingProfile) -> None:
        self._profiles[profile.profile_id] = profile

    def list_profiles(self) -> List[EncodingProfile]:
        return list(self._profiles.values())

    def get_profile(self, profile_id: str) -> EncodingProfile:
        if profile_id not in self._profiles:
            raise KeyError(f"Unknown encoding profile '{profile_id}'")
        return self._profiles[profile_id]

    # ------------------------------------------------------------------
    # Sources & privacy
    def list_sources(self) -> List[CameraSource]:
        return self.cameras.list_sources()

    def configure_room_privacy(self, config: Dict[str, Dict[str, str]]) -> None:
        self._room_privacy = config

    def room_policy(self, room: str) -> Dict[str, str]:
        return self._room_privacy.get(room, {"recording": "allowed"})

    def privacy_matrix(self) -> Dict[str, Dict[str, str]]:
        return self._room_privacy

    def _validate_sources(self, sources: Iterable[str], *, host_override: bool) -> None:
        for source_id in sources:
            camera = self.cameras.get(source_id)
            if not camera:
                raise ValueError(f"Unknown source '{source_id}'")
            policy = self.room_policy(camera.location)
            rule = policy.get("recording", "allowed")
            if rule == "never" and not host_override:
                raise PermissionError(f"Recording is forbidden in {camera.location}")
            if rule == "with_permission" and not host_override:
                raise PermissionError(f"Recording {camera.location} requires consent")

    # ------------------------------------------------------------------
    # Session lifecycle
    def list_sessions(self) -> List[RecordingSession]:
        return list(self._sessions.values())

    def get_session(self, session_id: str) -> RecordingSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"Session '{session_id}' not found") from exc

    def _session_dir(self, session_id: str) -> Path:
        return self.recordings_dir / session_id

    def start_session(
        self,
        session_id: Optional[str],
        sources: List[str],
        *,
        profile_id: str,
        operator: str,
        preset: Optional[str] = None,
        host_override: bool = False,
        countdown_seconds: int = 5,
    ) -> RecordingSession:
        if not sources:
            raise ValueError("At least one source is required")
        session_id = session_id or f"rec_{uuid.uuid4().hex[:10]}"
        if session_id in self._sessions:
            raise ValueError(f"Session '{session_id}' already active")
        self._validate_sources(sources, host_override=host_override)
        profile = self.get_profile(profile_id)

        session = RecordingSession(
            session_id=session_id,
            sources=sources,
            profile_id=profile.profile_id,
            operator=operator,
            preset=preset,
            host_override=host_override,
            countdown_seconds=countdown_seconds,
            state=RecordingState.COUNTDOWN if countdown_seconds else RecordingState.ACTIVE,
        )
        self._sessions[session_id] = session
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        self._write_metadata(session)
        
        # NEW: Create pipeline session for detailed event logging
        try:
            from .recording_pipeline import ServerRecordingSession
            pipeline = ServerRecordingSession(session_id, self.recordings_dir)
            self._pipeline_sessions[session_id] = pipeline
            
            # Register with export routes
            try:
                from . import recording_pipeline_routes
                recording_pipeline_routes.register_pipeline_session(session_id, pipeline)
            except ImportError:
                pass  # Routes not loaded yet
            
            logger.info("Recording session %s created with pipeline logging", session_id)
        except ImportError:
            logger.info("Recording session %s created (pipeline logging unavailable)", session_id)

        self._blackbox_event("recording.state", actor=operator, data={"session_id": session.session_id, "state": session.state.value, "sources": ",".join(session.sources), "profile_id": session.profile_id})
        logger.info("Recording session %s created with sources %s", session_id, sources)
        return session

    def activate_session(self, session_id: str) -> RecordingSession:
        session = self.get_session(session_id)
        if session.state not in {RecordingState.REQUESTED, RecordingState.COUNTDOWN}:
            raise ValueError(f"Cannot activate session in state {session.state}")
        session.state = RecordingState.ACTIVE
        session.updated_at = time.time()
        self._write_metadata(session)
        self._blackbox_event("recording.state", actor=session.operator, data={"session_id": session.session_id, "state": "active"})
        logger.info("Recording session %s is now active", session_id)
        return session

    def stop_session(self, session_id: str) -> RecordingSession:
        session = self.get_session(session_id)
        if session.state == RecordingState.STOPPED:
            return session
        session.state = RecordingState.STOPPED
        session.ended_at = time.time()
        session.updated_at = session.ended_at
        self._write_metadata(session)
        
        # NEW: Stop pipeline session and log summary
        pipeline = self._pipeline_sessions.pop(session_id, None)
        if pipeline:
            summary = pipeline.stop()
            logger.info("Pipeline session %s stopped: %s", session_id, summary)
            
            # Unregister from export routes
            try:
                from . import recording_pipeline_routes
                recording_pipeline_routes.unregister_pipeline_session(session_id)
            except ImportError:
                pass
        
        self._blackbox_event("recording.state", actor=session.operator, data={"session_id": session.session_id, "state": "stopped", "duration_sec": round((session.ended_at or time.time()) - session.started_at, 3)})
        logger.info("Recording session %s stopped", session_id)
        return session

    def pause_session(self, session_id: str, paused: bool) -> RecordingSession:
        session = self.get_session(session_id)
        if session.state not in {RecordingState.ACTIVE, RecordingState.PAUSED}:
            raise ValueError("Cannot pause a session that is not active")
        session.state = RecordingState.PAUSED if paused else RecordingState.ACTIVE
        session.updated_at = time.time()
        self._write_metadata(session)
        self._blackbox_event("recording.state", actor=session.operator, data={"session_id": session.session_id, "state": session.state.value, "paused": paused})
        logger.info("Recording session %s %s", session_id, "paused" if paused else "resumed")
        return session

    def archive_session(self, session_id: str) -> RecordingSession:
        session = self.get_session(session_id)
        if session.state != RecordingState.STOPPED:
            raise ValueError("Only stopped sessions can be archived")
        session.state = RecordingState.ARCHIVED
        session.updated_at = time.time()
        self._write_metadata(session)
        logger.info("Recording session %s archived", session_id)
        return session

    def mark_moment(self, session_id: str, label: str, operator: Optional[str] = None) -> RecordingMarker:
        session = self.get_session(session_id)
        marker = RecordingMarker(timestamp=time.time(), label=label, operator=operator)
        session.markers.append(marker)
        session.updated_at = marker.timestamp
        self._write_metadata(session)
        self._blackbox_event("recording.state", actor=operator or session.operator, data={"session_id": session.session_id, "state": session.state.value, "marker_label": label})
        logger.info("Session %s :: marker '%s'", session_id, label)
        return marker

    def register_artifact(
        self,
        session_id: str,
        file_path: Path,
        *,
        name: Optional[str] = None,
        format: Optional[ContainerFormat] = None,
    ) -> RecordingArtifact:
        """Register a captured media file on a recording session."""
        session = self.get_session(session_id)
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(path)

        artifact_format = format
        if artifact_format is None:
            suffix = path.suffix.lstrip(".").lower()
            try:
                artifact_format = ContainerFormat(suffix)
            except ValueError:
                artifact_format = self.get_profile(session.profile_id).container

        artifact = RecordingArtifact(
            name=name or path.name,
            format=artifact_format,
            file_path=path,
            size_bytes=path.stat().st_size,
        )
        session.artifacts = [
            existing for existing in session.artifacts
            if Path(existing.file_path).resolve() != path.resolve()
        ]
        session.artifacts.append(artifact)
        session.updated_at = time.time()
        self._write_metadata(session)
        self._blackbox_event(
            "recording.artifact",
            actor=session.operator,
            data={
                "session_id": session.session_id,
                "name": artifact.name,
                "format": artifact.format.value,
                "size_bytes": artifact.size_bytes,
            },
        )
        return artifact

    # ------------------------------------------------------------------
    # Import / export
    @staticmethod
    def _find_ffmpeg() -> Optional[str]:
        """Return path to ffmpeg binary, or None if not installed."""
        import shutil as _shutil
        return _shutil.which("ffmpeg")

    @staticmethod
    def _ffmpeg_bitrate(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        clean = str(value).strip()
        lower = clean.lower()
        if lower.endswith("mbps"):
            return clean[:-4] + "M"
        if lower.endswith("kbps"):
            return clean[:-4] + "k"
        return clean

    def _transcode_artifact(
        self,
        src: Path,
        dst: Path,
        profile: EncodingProfile,
    ) -> bool:
        """
        Transcode a single source file to the target format using FFmpeg.
        Returns True on success, False on failure (src is kept, dst cleaned up).
        Runs synchronously — call from a thread or export_session which is
        already expected to be a blocking operation.
        """
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            logger.warning("ffmpeg not found — copying source file without transcoding")
            shutil.copy2(src, dst)
            return True

        cmd: List[str] = [ffmpeg, "-y", "-i", str(src)]

        if profile.is_audio_only:
            # Strip video, encode audio
            cmd += ["-vn"]
            if profile.audio_codec:
                cmd += ["-acodec", profile.audio_codec]
            audio_bitrate = self._ffmpeg_bitrate(profile.audio_bitrate)
            if audio_bitrate:
                cmd += ["-b:a", audio_bitrate]
        else:
            if profile.video_codec:
                video_codec = "libx264" if profile.video_codec == "h264" else profile.video_codec
                cmd += ["-vcodec", video_codec]
            if profile.audio_codec:
                cmd += ["-acodec", profile.audio_codec]
            video_bitrate = self._ffmpeg_bitrate(profile.video_bitrate)
            if video_bitrate:
                cmd += ["-b:v", video_bitrate]
            audio_bitrate = self._ffmpeg_bitrate(profile.audio_bitrate)
            if audio_bitrate:
                cmd += ["-b:a", audio_bitrate]
            if profile.resolution:
                cmd += ["-s", profile.resolution]
            if profile.frame_rate:
                cmd += ["-r", profile.frame_rate]
            if profile.video_codec == "h264":
                cmd += ["-pix_fmt", "yuv420p"]

        cmd.append(str(dst))

        logger.info("FFmpeg transcode: %s → %s", src.name, dst.name)
        logger.debug("FFmpeg cmd: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10-minute hard limit per file
            )
            if result.returncode != 0:
                logger.error(
                    "FFmpeg failed (rc=%d) for %s:\n%s",
                    result.returncode, src.name, result.stderr[-2000:]
                )
                dst.unlink(missing_ok=True)
                return False
            logger.info(
                "FFmpeg complete: %s → %s (%.1f MB)",
                src.name, dst.name, dst.stat().st_size / (1024 * 1024)
            )
            return True
        except subprocess.TimeoutExpired:
            logger.error("FFmpeg timed out transcoding %s", src.name)
            dst.unlink(missing_ok=True)
            return False
        except Exception as exc:
            logger.error("FFmpeg error transcoding %s: %s", src.name, exc)
            dst.unlink(missing_ok=True)
            return False

    def export_session(self, session_id: str, *, container: ContainerFormat) -> Path:
        """
        Export a recording session as a zip bundle.

        If the session has a registered EncodingProfile, each artifact is
        transcoded via FFmpeg to the target container/codec before bundling.
        If FFmpeg is not installed, source files are copied without transcoding
        (graceful degradation — the zip will still contain the original media).

        Returns the path to the zip bundle.
        """
        session = self.get_session(session_id)
        profile = self._profiles.get(session.profile_id)
        archive_path = self.exports_dir / f"{session_id}.{container.value}.zip"
        metadata_name = f"{session_id}.json"
        transcode_dir = self.exports_dir / f"{session_id}_transcode"

        try:
            transcode_dir.mkdir(parents=True, exist_ok=True)
            with ZipFile(archive_path, "w", ZIP_DEFLATED) as bundle:
                bundle.writestr(metadata_name, json.dumps(session.to_dict(), indent=2))
                for artifact in session.artifacts:
                    if not artifact.file_path.exists():
                        logger.warning("Artifact missing: %s", artifact.file_path)
                        continue

                    if profile and self._find_ffmpeg():
                        # Transcode to target container
                        out_name = artifact.file_path.stem + f".{container.value}"
                        out_path = transcode_dir / out_name
                        # Use a copy of profile with updated container
                        export_profile = EncodingProfile(
                            profile_id=profile.profile_id,
                            name=profile.name,
                            container=container,
                            video_codec=profile.video_codec,
                            audio_codec=profile.audio_codec,
                            video_bitrate=profile.video_bitrate,
                            audio_bitrate=profile.audio_bitrate,
                            resolution=profile.resolution,
                            frame_rate=profile.frame_rate,
                            description=profile.description,
                            is_audio_only=profile.is_audio_only or container == ContainerFormat.WAV,
                        )
                        success = self._transcode_artifact(artifact.file_path, out_path, export_profile)
                        src_for_bundle = out_path if success and out_path.exists() else artifact.file_path
                    else:
                        src_for_bundle = artifact.file_path

                    bundle.write(src_for_bundle, arcname=f"media/{src_for_bundle.name}")
        finally:
            # Clean up transcode staging area
            if transcode_dir.exists():
                shutil.rmtree(transcode_dir, ignore_errors=True)

        logger.info("Exported session %s to %s", session_id, archive_path)
        return archive_path

    def import_session(self, bundle_path: Path) -> RecordingSession:
        if not bundle_path.exists():
            raise FileNotFoundError(bundle_path)
        with ZipFile(bundle_path, "r") as bundle:
            metadata_candidates = [name for name in bundle.namelist() if name.endswith(".json")]
            if not metadata_candidates:
                raise ValueError("Bundle does not contain metadata")
            meta_name = metadata_candidates[0]
            payload = json.loads(bundle.read(meta_name))
            session_id = payload.get("session_id") or f"rec_{uuid.uuid4().hex[:10]}"
            session_dir = self._session_dir(session_id)
            if session_dir.exists():
                raise ValueError(f"Session directory already exists for {session_id}")
            session_dir.mkdir(parents=True, exist_ok=True)
            for member in bundle.namelist():
                if member.startswith("media/"):
                    target = session_dir / Path(member).name
                    with bundle.open(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
            session = self._session_from_dict(payload)
            session.session_id = session_id
            self._sessions[session_id] = session
            self._write_metadata(session)
            logger.info("Imported recording session %s", session_id)
            return session

    # ------------------------------------------------------------------
    # Storage & diagnostics
    def storage_status(self) -> Dict[str, float]:
        usage_bytes = sum(
            file.stat().st_size
            for file in self.recordings_dir.glob("**/*")
            if file.is_file()
        )
        self._storage_cache["recorded_gb"] = round(usage_bytes / (1024 ** 3), 2)
        return self._storage_cache

    def set_storage_status(self, **kwargs) -> None:
        self._storage_cache.update(kwargs)

    # ------------------------------------------------------------------
    # NEW: Pipeline event logging methods
    def record_camera_switch(self, session_id: str, from_cam: str, to_cam: str, transition: str = "cut") -> None:
        """Log camera switch to active pipeline session."""
        pipeline = self._pipeline_sessions.get(session_id)
        if pipeline:
            pipeline.record_camera_switch(from_cam, to_cam, transition)

    def record_chat_message(self, session_id: str, user: str, text: str, user_id: str = "") -> None:
        """Log chat message to active pipeline session."""
        pipeline = self._pipeline_sessions.get(session_id)
        if pipeline:
            pipeline.record_chat(user, text, user_id)

    def add_marker(self, session_id: str, label: str, operator: str = "") -> None:
        """Add manual marker to active pipeline session."""
        pipeline = self._pipeline_sessions.get(session_id)
        if pipeline:
            pipeline.record_marker(label, operator)

    def get_pipeline_session(self, session_id: str):
        """Get pipeline session for export operations."""
        return self._pipeline_sessions.get(session_id)

    # ------------------------------------------------------------------
    def _write_metadata(self, session: RecordingSession) -> None:
        metadata_path = self._session_dir(session.session_id) / f"{session.session_id}.json"
        metadata_path.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")

    def _session_from_dict(self, payload: Dict) -> RecordingSession:
        session = RecordingSession(
            session_id=payload["session_id"],
            sources=list(payload.get("sources", [])),
            profile_id=payload["profile_id"],
            operator=payload.get("operator", "unknown"),
            preset=payload.get("preset"),
            host_override=payload.get("host_override", False),
            countdown_seconds=payload.get("countdown_seconds", 5),
            state=RecordingState(payload.get("state", RecordingState.STOPPED.value)),
            started_at=payload.get("started_at", time.time()),
            updated_at=payload.get("updated_at", time.time()),
            ended_at=payload.get("ended_at"),
        )
        session.artifacts = [
            RecordingArtifact(
                name=item["name"],
                format=ContainerFormat(item["format"]),
                file_path=self._session_dir(session.session_id) / Path(item["file_path"]).name,
                size_bytes=item.get("size_bytes", 0),
            )
            for item in payload.get("artifacts", [])
        ]
        session.markers = [
            RecordingMarker(
                timestamp=item["timestamp"],
                label=item["label"],
                operator=item.get("operator"),
            )
            for item in payload.get("markers", [])
        ]
        return session


# ----------------------------------------------------------------------
# Factory

def create_recording_service(base_dir: Path, cameras: CameraManager, blackbox_witness: Optional[Any] = None) -> RecordingService:
    service = RecordingService(base_dir=base_dir, cameras=cameras, blackbox_witness=blackbox_witness)
    service.register_profile(
        EncodingProfile(
            profile_id="prores_hq",
            name="Apple ProRes HQ",
            container=ContainerFormat.MOV,
            video_codec="prores",
            audio_codec="pcm_s24le",
            video_bitrate="880Mbps",
            audio_bitrate="1.5Mbps",
            resolution="3840x2160",
            frame_rate="60",
            description="Mastering quality profile",
        )
    )
    service.register_profile(
        EncodingProfile(
            profile_id="broadcast_mp4",
            name="Broadcast MP4",
            container=ContainerFormat.MP4,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate="50Mbps",
            audio_bitrate="320kbps",
            resolution="1920x1080",
            frame_rate="59.94",
            description="Delivery-ready broadcast encode",
        )
    )
    service.register_profile(
        EncodingProfile(
            profile_id="web_stream",
            name="Web Stream",
            container=ContainerFormat.WEBM,
            video_codec="vp9",
            audio_codec="opus",
            video_bitrate="8Mbps",
            audio_bitrate="192kbps",
            resolution="1280x720",
            frame_rate="30",
            description="Low-latency web playback",
        )
    )
    service.register_profile(
        EncodingProfile(
            profile_id="audio_only",
            name="Audio Only WAV",
            container=ContainerFormat.WAV,
            video_codec=None,
            audio_codec="pcm_s16le",
            video_bitrate=None,
            audio_bitrate="1Mbps",
            resolution=None,
            frame_rate=None,
            description="High fidelity audio capture",
            is_audio_only=True,
        )
    )

    service.configure_room_privacy(
        {
            "pub": {"recording": "allowed", "notice": "This is a public space that may be recorded."},
            "green": {"recording": "with_permission", "notice": "Recording requires explicit consent."},
            "conference": {"recording": "host_policy", "notice": "Recording policy defined by meeting host."},
            "studio": {"recording": "expected", "notice": "Production area"},
            "dressing": {"recording": "never", "notice": "Private space"},
        }
    )
    return service




