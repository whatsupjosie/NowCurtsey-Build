"""
modules/pubcast_clip_upload_route.py

The missing link between the browser camera and the real recording pipeline.

PubWorld.jsx records the WebGL canvas with MediaRecorder and produces a real
video Blob. Everything downstream of a file on disk already exists and is real:

    register_artifact(session_id, path)   # recording.py, verified real
      -> _transcode_artifact()            # real ffmpeg / libx264, verified real
      -> export_session()                 # real zip bundle, verified real

Nothing connected the two. This route does exactly that and nothing more.

Verified before writing (not assumed):
  - pubcast_vision_routes.py mounts at prefix "/api/vision"
  - /broadcast/start takes BroadcastStartRequest(quality: str) only
  - /broadcast/stop takes NO arguments and returns a JSON summary
  - neither accepts a file upload; no upload route existed anywhere
  - recording.register_artifact(session_id, file_path, *, name, format)
    raises FileNotFoundError if the path is missing, and infers ContainerFormat
    from the file suffix when format is omitted

Mount in main.py next to the vision router:

    from modules.pubcast_clip_upload_route import create_clip_router
    application.include_router(create_clip_router(recording))
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

logger = logging.getLogger("pubcast.clip_upload")

# MediaRecorder realistically emits these. Anything else is rejected rather
# than trusted, since the suffix is used to pick a ContainerFormat downstream.
_ALLOWED_SUFFIXES = {".webm", ".mp4"}

# Refuse absurd uploads outright instead of filling the disk.
_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_filename(raw: Optional[str]) -> str:
    """
    Never trust a client-supplied filename. Strip any path components and any
    character that isn't plainly safe, then verify the extension.
    """
    base = Path(raw or "").name                    # kills ../../ traversal
    base = _SAFE_NAME.sub("_", base).lstrip(".")   # no control chars, no dotfiles
    if not base:
        base = f"clip_{int(time.time())}.webm"

    suffix = Path(base).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported clip format '{suffix or '(none)'}'. Expected one of: "
                   + ", ".join(sorted(_ALLOWED_SUFFIXES)),
        )
    return base


def create_clip_router(recording: Any, storage_dir: Optional[Path] = None) -> APIRouter:
    """
    Build the clip upload router.

    Args:
        recording: the live RecordingManager from main.py (the same object that
            already owns register_artifact / export_session).
        storage_dir: where clips land. Defaults to the recording manager's own
            directory when it exposes one, so clips sit with existing artifacts
            rather than in a second unrelated location.
    """
    router = APIRouter(prefix="/api/vision", tags=["Camera Vision"])

    def _resolve_dir() -> Path:
        if storage_dir is not None:
            target = Path(storage_dir)
        else:
            # Reuse the recording manager's directory if it has one; only fall
            # back to a fixed path if it genuinely doesn't.
            for attr in ("output_dir", "recordings_dir", "data_dir", "base_dir"):
                value = getattr(recording, attr, None)
                if value:
                    target = Path(value) / "clips"
                    break
            else:
                target = Path("data/recordings/clips")
        target.mkdir(parents=True, exist_ok=True)
        return target

    @router.post("/clip/upload")
    async def upload_clip(
        file: UploadFile = File(..., description="Video clip recorded by MediaRecorder"),
        session_id: str = Form(..., description="Recording session to attach this clip to"),
        name: Optional[str] = Form(None, description="Optional display name"),
    ) -> Dict[str, Any]:
        """
        Accept a browser-recorded clip and register it on a recording session.

        This is the entry point to the existing pipeline: once registered, the
        clip can be transcoded and exported by the recording manager exactly
        like any other artifact.
        """
        safe_name = _sanitize_filename(file.filename)
        target_dir = _resolve_dir()
        final_path = target_dir / f"{int(time.time())}_{safe_name}"

        # Stream to a temp file first so a failed or oversized upload never
        # leaves a half-written file where a complete one is expected.
        tmp_fd = tempfile.NamedTemporaryFile(
            delete=False, dir=target_dir, suffix=Path(safe_name).suffix
        )
        tmp_path = Path(tmp_fd.name)
        written = 0
        try:
            with tmp_fd:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > _MAX_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Clip exceeds maximum size of {_MAX_BYTES // (1024**3)} GB",
                        )
                    tmp_fd.write(chunk)

            if written == 0:
                raise HTTPException(status_code=400, detail="Uploaded clip is empty")

            tmp_path.replace(final_path)   # atomic on the same filesystem

        except HTTPException:
            tmp_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            tmp_path.unlink(missing_ok=True)
            logger.exception("Clip upload failed for session %s", session_id)
            raise HTTPException(status_code=500, detail=f"Clip upload failed: {exc}") from exc

        # Hand off to the real pipeline. If registration fails, the file itself
        # is still on disk — say so plainly rather than implying it was lost.
        try:
            artifact = recording.register_artifact(
                session_id, final_path, name=name or safe_name
            )
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="Clip vanished before registration")
        except KeyError:
            # Deliberately do NOT delete the clip — it may be the only copy of a
            # take. But never let it become a silent orphan either: say exactly
            # where it is so it can be re-registered once a session exists.
            logger.warning(
                "Clip %s uploaded for unknown session '%s'; retained at %s",
                final_path.name, session_id, final_path,
            )
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Unknown recording session '{session_id}'. The clip was NOT lost — "
                    f"it is saved at {final_path}. Start a session and re-register it."
                ),
            )
        except Exception as exc:
            logger.exception("register_artifact failed for session %s", session_id)
            raise HTTPException(
                status_code=500,
                detail=f"Clip saved to {final_path} but could not be registered: {exc}",
            ) from exc

        logger.info(
            "Registered clip %s (%.2f MB) on session %s",
            final_path.name, written / 1048576, session_id,
        )

        return {
            "success": True,
            "session_id": session_id,
            "path": str(final_path),
            "bytes": written,
            "artifact_id": getattr(artifact, "artifact_id", None) or getattr(artifact, "id", None),
            "message": "Clip registered on recording session",
        }

    return router
