"""
modules/media_intake_routes.py — upload endpoints for PubCast media intake.

Mounted through production_routes so the current app can accept practical studio
assets without main.py surgery.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from modules.media_intake import (
    accepted_formats_manifest,
    classify_filename,
    destination_for_upload,
    save_upload_file,
)
from modules.media_router import require_admin


def _resolve_base_dir(recording: Optional[Any], base_dir: Optional[Path]) -> Path:
    if base_dir is not None:
        return Path(base_dir)
    if recording is not None and hasattr(recording, "base_dir"):
        return Path(recording.base_dir)
    return Path("data")


def create_media_intake_router(
    *,
    recording: Optional[Any] = None,
    base_dir: Optional[Path] = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/media", tags=["Media Intake"])

    @router.get("/intake/formats")
    async def media_intake_formats() -> Dict[str, Any]:
        """Return the file extensions PubCast will accept into media intake."""
        return accepted_formats_manifest()

    @router.post("/intake")
    async def media_intake_upload(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
        """Accept one practical media/code asset and store it by classified kind."""
        require_admin(request)

        original_name = file.filename or "upload"
        fmt = classify_filename(original_name)
        if fmt is None:
            raise HTTPException(
                status_code=415,
                detail={
                    "error": "unsupported_file_type",
                    "filename": original_name,
                    "accepted_extensions": accepted_formats_manifest()["accepted_extensions"],
                },
            )

        root = _resolve_base_dir(recording, base_dir)
        destination = destination_for_upload(root, original_name, fmt)
        try:
            size_bytes = await save_upload_file(file, destination)
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail={"error": "storage_failure", "reason": str(exc)},
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail={"error": "upload_failed", "reason": str(exc)},
            )

        manifest = {
            "status": "ok",
            "filename": original_name,
            "stored_name": destination.name,
            "kind": fmt.kind,
            "extension": fmt.extension,
            "label": fmt.label,
            "notes": fmt.notes,
            "size_bytes": size_bytes,
            "stored_path": destination.as_posix(),
            "received_at": time.time(),
            "content_type": file.content_type,
        }
        manifest_path = destination.with_suffix(destination.suffix + ".pubcast.json")
        try:
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
            manifest["manifest_path"] = manifest_path.as_posix()
        except OSError:
            # manifest write failure is non-fatal — the file itself was saved
            manifest["manifest_path"] = None
        return manifest

    return router


__all__ = ["create_media_intake_router"]
