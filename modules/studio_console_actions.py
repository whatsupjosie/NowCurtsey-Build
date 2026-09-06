"""Studio console action registry.

This is the click-target mechanism for future console/hotspot art. The image can
place hotspots wherever it wants later; each hotspot only needs an action_id and
optional payload to call these stable backend actions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from .cameras import CameraManager
from .program_audio import ProgramAudioState, apply_audio_event
from .recording import RecordingService
from .studio_camera_preflight import all_camera_visibility, camera_visibility_report, recording_preflight, studio_readiness


@dataclass(frozen=True)
class StudioActionSpec:
    action_id: str
    label: str
    category: str
    safety: str
    description: str
    required_fields: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "label": self.label,
            "category": self.category,
            "safety": self.safety,
            "description": self.description,
            "required_fields": list(self.required_fields),
        }


_ACTIONS = [
    StudioActionSpec("studio.readiness", "Studio readiness", "studio", "safe", "Check camera, recording, and audio readiness.", []),
    StudioActionSpec("camera.visibility.all", "Check all cameras", "camera", "safe", "Check visibility and recordability for every camera.", []),
    StudioActionSpec("camera.visibility.one", "Check camera", "camera", "safe", "Check one camera source.", ["source_id"]),
    StudioActionSpec("camera.switch.program", "Take program camera", "camera", "mod", "Set the live/program camera.", ["source_id"]),
    StudioActionSpec("camera.switch.preview", "Set preview camera", "camera", "safe", "Set the preview camera.", ["source_id"]),
    StudioActionSpec("camera.cut", "Cut cameras", "camera", "mod", "Swap program and preview.", []),
    StudioActionSpec("recording.preflight", "Recording preflight", "recording", "safe", "Check selected sources and profile before recording.", []),
    StudioActionSpec("recording.start", "Start recording", "recording", "confirm", "Start a recording session after explicit confirmation.", ["confirm"]),
    StudioActionSpec("recording.stop", "Stop recording", "recording", "confirm", "Stop a recording session after explicit confirmation.", ["session_id", "confirm"]),
    StudioActionSpec("audio.status", "Audio status", "audio", "safe", "Read current program audio state.", []),
    StudioActionSpec("audio.event", "Audio event", "audio", "safe", "Apply a validated program audio event.", ["action"]),
    StudioActionSpec("audio.stop_all", "Stop all audio", "audio", "safe", "Stop all active program audio sources.", []),
]


def list_studio_actions() -> List[Dict[str, Any]]:
    return [spec.to_dict() for spec in _ACTIONS]


def _require(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _confirmed(payload: Mapping[str, Any]) -> bool:
    return payload.get("confirm") is True or str(payload.get("confirm") or "").strip().lower() == "yes"


def execute_studio_action(
    action_id: str,
    payload: Mapping[str, Any],
    *,
    cameras: CameraManager,
    recording: RecordingService,
    audio_state: ProgramAudioState,
    actor: str = "director",
) -> Dict[str, Any]:
    body = dict(payload or {})
    action_id = str(action_id or "").strip()

    if action_id == "studio.readiness":
        result = studio_readiness(cameras, recording, audio_status=audio_state.status())
    elif action_id == "camera.visibility.all":
        result = all_camera_visibility(cameras)
    elif action_id == "camera.visibility.one":
        source_id = _require(body, "source_id")
        camera = cameras.get(source_id)
        if camera is None:
            raise ValueError(f"Camera source '{source_id}' not found")
        result = camera_visibility_report(camera, cameras.status(source_id))
    elif action_id in {"camera.switch.program", "camera.switch.preview"}:
        source_id = _require(body, "source_id")
        ok = cameras.set_program_source(source_id) if action_id.endswith("program") else cameras.set_preview_source(source_id)
        if not ok:
            raise ValueError(f"Camera source '{source_id}' not found")
        result = {"ok": True, "target": "program" if action_id.endswith("program") else "preview", "source_id": source_id}
    elif action_id == "camera.cut":
        program = cameras.get_program_source()
        preview = cameras.get_preview_source()
        if program is None or preview is None:
            raise ValueError("Both program and preview must be set before cut")
        cameras.set_program_source(preview.source_id)
        cameras.set_preview_source(program.source_id)
        result = {"ok": True, "program": preview.source_id, "preview": program.source_id}
    elif action_id == "recording.preflight":
        sources = body.get("sources") if isinstance(body.get("sources"), list) else []
        result = recording_preflight(
            cameras,
            recording,
            sources=sources,
            profile_id=str(body.get("profile_id") or "broadcast_mp4"),
            host_override=bool(body.get("host_override")),
        )
    elif action_id == "recording.start":
        if not _confirmed(body):
            raise ValueError("recording.start requires confirm=true")
        sources = body.get("sources") if isinstance(body.get("sources"), list) else []
        if not sources:
            program = cameras.get_program_source()
            sources = [program.source_id] if program is not None else []
        session = recording.start_session(
            str(body.get("session_id") or "").strip() or None,
            [str(item) for item in sources],
            profile_id=str(body.get("profile_id") or "broadcast_mp4"),
            operator=actor,
            countdown_seconds=int(body.get("countdown_seconds", 0) or 0),
            host_override=bool(body.get("host_override")),
        )
        result = session.to_dict()
    elif action_id == "recording.stop":
        if not _confirmed(body):
            raise ValueError("recording.stop requires confirm=true")
        result = recording.stop_session(_require(body, "session_id")).to_dict()
    elif action_id == "audio.status":
        result = audio_state.status()
    elif action_id == "audio.event":
        result = apply_audio_event(audio_state, body)
    elif action_id == "audio.stop_all":
        result = apply_audio_event(audio_state, {"action": "stop_all"})
    else:
        raise ValueError(f"Unknown studio action: {action_id}")

    return {"ok": True, "action_id": action_id, "actor": actor, "result": result}


__all__ = ["execute_studio_action", "list_studio_actions", "StudioActionSpec"]
