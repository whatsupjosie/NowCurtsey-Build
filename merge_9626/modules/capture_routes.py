"""
modules/capture_routes.py — PubCast AI FFmpeg Capture Engine Routes
=====================================================================
FastAPI router for the FFmpegCaptureEngine.

Exposes session-level capture control (start/stop/pause/resume) and
status endpoints. The capture engine itself is instantiated at boot
in main.py and passed here via create_capture_router().

Routes
------
  POST /api/capture/{session_id}/start   — begin capturing all active sources
  POST /api/capture/{session_id}/stop    — stop capturing, register artifacts
  POST /api/capture/{session_id}/pause   — pause (SIGSTOP, Unix only)
  POST /api/capture/{session_id}/resume  — resume (SIGCONT, Unix only)
  GET  /api/capture/{session_id}/status  — is this session capturing?
  GET  /api/capture/sessions             — all active capture sessions

The routes delegate entirely to FFmpegCaptureEngine; they do not touch
RecordingService directly. The recording pipeline (register_artifact,
transcode, export) runs after stop() returns the file paths.

Rear View Foresight LLC — Feic Mo Chroí — 2026-09-05
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger("pubcast.capture_routes")


def create_capture_router(
    capture_engine: Any,
    recording: Any,
    data_dir: Path,
    require_role: Any,
) -> APIRouter:
    """
    Build the /api/capture FastAPI router.

    Args:
        capture_engine: FFmpegCaptureEngine instance from main.py boot
        recording:      RecordingService instance (for register_artifact)
        data_dir:       Server DATA_DIR path for session directories
        require_role:   main.py auth dependency factory
    """
    router = APIRouter(prefix="/api/capture", tags=["Capture"])

    def _require_engine():
        if capture_engine is None or not capture_engine.available:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "capture_unavailable",
                    "reason": "FFmpeg not found or capture engine not initialised. "
                              "Install ffmpeg or set PUBCAST_FFMPEG env var.",
                },
            )

    # ── Start capturing ────────────────────────────────────────────────────────

    @router.post("/{session_id}/start")
    async def start_capture(
        session_id: str,
        request: Request,
        identity: Dict[str, Any] = Depends(require_role("mod")),
    ) -> Dict[str, Any]:
        """
        Begin capturing all active sources for a recording session.

        Body (optional):
          sources:   list of {source_id, transport, endpoint} — defaults to
                     all live cameras from recording.get_session_sources()
          profile:   encoding profile name (default: "medium")
        """
        _require_engine()

        try:
            body = await request.json()
        except Exception:
            body = {}

        profile_name = body.get("profile", "medium")

        # Resolve sources: explicit body list wins, else pull from recording service
        raw_sources = body.get("sources")
        if raw_sources:
            # Build lightweight source objects from the body list
            class _Src:
                def __init__(self, d):
                    self.source_id = d["source_id"]
                    self.transport = type("T", (), {"value": d.get("transport", "virtual")})()
                    self.endpoint  = d.get("endpoint", "")
            sources = [_Src(s) for s in raw_sources]
        elif recording is not None and hasattr(recording, "get_session_sources"):
            sources = recording.get_session_sources(session_id) or []
        else:
            sources = []

        if not sources:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "no_sources",
                    "reason": "No sources resolved for this session. "
                              "Pass 'sources' in the request body or ensure the "
                              "session has active camera sources.",
                },
            )

        # Resolve encoding profile
        profile = None
        if recording is not None and hasattr(recording, "get_profile"):
            profile = recording.get_profile(profile_name)
        if profile is None:
            # Fallback minimal profile that always works
            class _Profile:
                video_codec   = "h264"
                video_bitrate = "4M"
                audio_codec   = "aac"
                audio_bitrate = "128k"
                resolution    = None
                frame_rate    = "30"
                is_audio_only = False
                container     = type("C", (), {"value": "mp4"})()
            profile = _Profile()

        session_dir = data_dir / "recordings" / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        try:
            output_paths = await capture_engine.start(
                session_id=session_id,
                sources=sources,
                profile=profile,
                session_dir=session_dir,
            )
        except Exception as exc:
            logger.error("Capture start failed for session %s: %s", session_id, exc)
            raise HTTPException(
                status_code=500,
                detail={"error": "capture_start_failed", "reason": str(exc)},
            )

        return {
            "ok": True,
            "session_id": session_id,
            "source_count": len(sources),
            "output_paths": [str(p) for p in output_paths],
        }

    # ── Stop capturing ─────────────────────────────────────────────────────────

    @router.post("/{session_id}/stop")
    async def stop_capture(
        session_id: str,
        identity: Dict[str, Any] = Depends(require_role("mod")),
    ) -> Dict[str, Any]:
        """
        Stop capturing and register all written files as recording artifacts.
        Files with zero bytes are reported but not registered.
        """
        _require_engine()

        if not capture_engine.is_capturing(session_id):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "not_capturing",
                    "reason": f"Session '{session_id}' is not currently capturing.",
                },
            )

        try:
            output_paths = await capture_engine.stop(session_id)
        except Exception as exc:
            logger.error("Capture stop failed for session %s: %s", session_id, exc)
            raise HTTPException(
                status_code=500,
                detail={"error": "capture_stop_failed", "reason": str(exc)},
            )

        registered: List[str] = []
        skipped:    List[str] = []

        for path in output_paths:
            if not path.exists() or path.stat().st_size == 0:
                skipped.append(str(path))
                continue
            if recording is not None and hasattr(recording, "register_artifact"):
                try:
                    recording.register_artifact(session_id, str(path))
                    registered.append(str(path))
                except Exception as exc:
                    logger.warning(
                        "Could not register artifact %s for session %s: %s",
                        path, session_id, exc,
                    )
                    registered.append(str(path))  # file exists even if registration failed
            else:
                registered.append(str(path))

        return {
            "ok": True,
            "session_id": session_id,
            "artifacts_registered": len(registered),
            "artifacts_skipped": len(skipped),
            "paths": registered,
            "skipped": skipped,
        }

    # ── Pause / Resume ─────────────────────────────────────────────────────────

    @router.post("/{session_id}/pause")
    async def pause_capture(
        session_id: str,
        identity: Dict[str, Any] = Depends(require_role("mod")),
    ) -> Dict[str, Any]:
        """Pause capture (SIGSTOP). Unix only — no-op on Windows."""
        _require_engine()
        if not capture_engine.is_capturing(session_id):
            raise HTTPException(409, f"Session '{session_id}' is not capturing.")
        await capture_engine.pause(session_id)
        return {"ok": True, "session_id": session_id, "state": "paused"}

    @router.post("/{session_id}/resume")
    async def resume_capture(
        session_id: str,
        identity: Dict[str, Any] = Depends(require_role("mod")),
    ) -> Dict[str, Any]:
        """Resume a paused capture (SIGCONT). Unix only — no-op on Windows."""
        _require_engine()
        if not capture_engine.is_capturing(session_id):
            raise HTTPException(409, f"Session '{session_id}' is not capturing.")
        await capture_engine.resume(session_id)
        return {"ok": True, "session_id": session_id, "state": "capturing"}

    # ── Status ─────────────────────────────────────────────────────────────────

    @router.get("/{session_id}/status")
    async def capture_status(session_id: str) -> Dict[str, Any]:
        """Is this session currently capturing?"""
        if capture_engine is None:
            return {"available": False, "capturing": False}
        return {
            "available": capture_engine.available,
            "session_id": session_id,
            "capturing": capture_engine.is_capturing(session_id),
        }

    @router.get("/sessions")
    async def active_capture_sessions() -> Dict[str, Any]:
        """List all sessions currently being captured."""
        if capture_engine is None:
            return {"available": False, "sessions": []}
        return {
            "available": capture_engine.available,
            "sessions": capture_engine.active_sessions(),
            "count": len(capture_engine.active_sessions()),
        }

    return router


__all__ = ["create_capture_router"]
