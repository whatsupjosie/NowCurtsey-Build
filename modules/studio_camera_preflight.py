"""Camera visibility and recording preflight helpers for PubCast studio.

These helpers do not capture media. They answer the production question that
must be true before capture starts: can the selected sources plausibly see, are
they recordable under current policy, and is the recording profile available?
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .cameras import CameraManager, CameraSource, CameraStatus, CameraTransport
from .recording import RecordingService


def _issue(code: str, message: str, severity: str = "error") -> Dict[str, str]:
    return {"code": code, "message": message, "severity": severity}


def _vector_ok(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 3:
        return False
    try:
        [float(item) for item in value]
    except (TypeError, ValueError):
        return False
    return True


def camera_visibility_report(camera: CameraSource, status: Optional[CameraStatus] = None) -> Dict[str, Any]:
    issues: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    online = bool(status.online) if status is not None else True

    if not online:
        issues.append(_issue("camera_offline", "Camera status is offline."))
    if not str(camera.endpoint or "").strip():
        issues.append(_issue("missing_endpoint", "Camera endpoint is empty."))
    if camera.video_enabled and not (1.0 <= float(camera.fov or 0) <= 180.0):
        issues.append(_issue("invalid_fov", "Camera field of view must be between 1 and 180 degrees."))
    if not _vector_ok(camera.position):
        issues.append(_issue("invalid_position", "Camera position must be a numeric XYZ vector."))
    if not _vector_ok(camera.rotation):
        issues.append(_issue("invalid_rotation", "Camera rotation must be a numeric XYZ vector."))
    if not camera.video_enabled and not camera.audio_enabled:
        issues.append(_issue("no_media_enabled", "Camera has neither video nor audio enabled."))
    if camera.is_private:
        warnings.append(_issue("private_source", "Camera is marked private; recording needs policy approval.", "warning"))

    confidence = "status_only"
    if camera.transport in {CameraTransport.VIRTUAL, CameraTransport.VOXEL_3D}:
        confidence = "synthetic_virtual_frame"
    elif camera.transport == CameraTransport.FILE:
        confidence = "file_endpoint"

    visible = online and camera.video_enabled and not any(item["severity"] == "error" for item in issues)
    recordable = online and (camera.video_enabled or camera.audio_enabled) and not any(item["severity"] == "error" for item in issues)
    return {
        "source_id": camera.source_id,
        "name": camera.name,
        "transport": camera.transport.value,
        "endpoint": camera.endpoint,
        "location": camera.location,
        "online": online,
        "visible": visible,
        "recordable": recordable,
        "confidence": confidence,
        "video_enabled": camera.video_enabled,
        "audio_enabled": camera.audio_enabled,
        "latency_ms": getattr(status, "latency_ms", None),
        "frame_rate": getattr(status, "frame_rate", None),
        "issues": issues,
        "warnings": warnings,
        "checked_at": time.time(),
    }


def all_camera_visibility(cameras: CameraManager) -> Dict[str, Any]:
    statuses = {status.source_id: status for status in cameras.list_status()}
    reports = [camera_visibility_report(camera, statuses.get(camera.source_id)) for camera in cameras.list_sources()]
    return {
        "ok": all(report["recordable"] for report in reports),
        "cameras": reports,
        "program": getattr(cameras.get_program_source(), "source_id", None),
        "preview": getattr(cameras.get_preview_source(), "source_id", None),
    }


def recording_preflight(
    cameras: CameraManager,
    recording: RecordingService,
    *,
    sources: Iterable[str] | None = None,
    profile_id: str = "broadcast_mp4",
    host_override: bool = False,
) -> Dict[str, Any]:
    selected = [str(item).strip() for item in (sources or []) if str(item).strip()]
    if not selected:
        program = cameras.get_program_source()
        if program is not None:
            selected = [program.source_id]

    issues: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    if not selected:
        issues.append(_issue("no_sources", "No recording sources were selected and no program camera is set."))

    try:
        profile = recording.get_profile(profile_id)
        profile_payload: Dict[str, Any] = {
            "profile_id": profile.profile_id,
            "container": profile.container.value,
            "video_codec": profile.video_codec,
            "audio_codec": profile.audio_codec,
            "resolution": profile.resolution,
            "frame_rate": profile.frame_rate,
            "audio_only": profile.is_audio_only,
        }
    except KeyError:
        profile_payload = {"profile_id": profile_id, "missing": True}
        issues.append(_issue("missing_profile", f"Recording profile '{profile_id}' is not registered."))

    statuses = {status.source_id: status for status in cameras.list_status()}
    camera_reports: List[Dict[str, Any]] = []
    for source_id in selected:
        camera = cameras.get(source_id)
        if camera is None:
            issues.append(_issue("unknown_source", f"Camera source '{source_id}' is not registered."))
            continue
        report = camera_visibility_report(camera, statuses.get(source_id))
        camera_reports.append(report)
        if not report["recordable"]:
            issues.append(_issue("source_not_recordable", f"Camera source '{source_id}' is not currently recordable."))
        policy = recording.room_policy(camera.location)
        rule = str(policy.get("recording") or "allowed")
        if rule == "never" and not host_override:
            issues.append(_issue("privacy_forbidden", f"Recording is forbidden in {camera.location}."))
        elif rule == "with_permission" and not host_override:
            issues.append(_issue("consent_required", f"Recording {camera.location} requires explicit consent."))
        elif rule == "host_policy":
            warnings.append(_issue("host_policy", f"Recording policy for {camera.location} is host-defined.", "warning"))

    ready = not issues
    return {
        "ready": ready,
        "ok": ready,
        "sources": selected,
        "profile": profile_payload,
        "host_override": bool(host_override),
        "camera_reports": camera_reports,
        "issues": issues,
        "warnings": warnings,
        "checked_at": time.time(),
    }


def studio_readiness(cameras: CameraManager, recording: RecordingService, *, audio_status: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    camera_report = all_camera_visibility(cameras)
    profile_count = len(recording.list_profiles())
    program = cameras.get_program_source()
    preflight = recording_preflight(
        cameras,
        recording,
        sources=[program.source_id] if program is not None else [],
        profile_id="broadcast_mp4",
    )
    audio_ready = bool(audio_status) if audio_status is not None else False
    issues: List[Dict[str, str]] = []
    if program is None:
        issues.append(_issue("no_program_camera", "No program camera is selected."))
    if profile_count <= 0:
        issues.append(_issue("no_recording_profiles", "No recording profiles are registered."))
    issues.extend(preflight.get("issues", []))
    ready = not issues
    return {
        "ready": ready,
        "ok": ready,
        "program": getattr(program, "source_id", None),
        "preview": getattr(cameras.get_preview_source(), "source_id", None),
        "camera_count": len(camera_report["cameras"]),
        "recording_profiles": profile_count,
        "recording_preflight": preflight,
        "audio_ready": audio_ready,
        "audio": dict(audio_status or {}),
        "issues": issues,
        "checked_at": time.time(),
    }


__all__ = ["all_camera_visibility", "camera_visibility_report", "recording_preflight", "studio_readiness"]
