# PubCast AI — save_metadata.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""Save-file metadata helpers for creative authorship, authority, and session credits.

This module keeps credit / provenance structure consistent across autosaves,
manual project saves, and future export pipelines.
"""
from __future__ import annotations

import copy
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_project_identity(slug: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    title = (
        payload.get("title")
        or payload.get("name")
        or payload.get("scene", {}).get("name")
        or payload.get("scene_name")
        or slug.replace("_", " ").replace("-", " ").title()
        or "Untitled Project"
    )
    synopsis = payload.get("original_synopsis") or payload.get("synopsis") or ""
    return {
        "project_id": payload.get("project_id") or slug,
        "slug": slug,
        "canonical_title": title,
        "original_title": payload.get("original_title") or title,
        "original_synopsis": synopsis,
        "current_synopsis": payload.get("current_synopsis") or synopsis,
        "created_at": payload.get("created_at") or _utc_now_iso(),
        "last_modified_at": _utc_now_iso(),
        "created_by": payload.get("created_by") or payload.get("original_host_id") or "unknown",
        "original_host_id": payload.get("original_host_id") or payload.get("created_by") or "unknown",
    }


def _default_project_credits(payload: Dict[str, Any]) -> Dict[str, Any]:
    creator = payload.get("creator") or payload.get("created_by") or payload.get("original_host_id")
    writer = payload.get("writer_of_record") or creator
    director = payload.get("director") or creator
    producer = payload.get("producer") or creator
    return {
        "creator": [creator] if creator else [],
        "writer_of_record": [writer] if writer else [],
        "director": [director] if director else [],
        "producer": [producer] if producer else [],
        "original_host": [payload.get("original_host_id") or creator] if (payload.get("original_host_id") or creator) else [],
    }


def _normalize_participant(entry: Dict[str, Any], default_session_role: str = "collaborator") -> Dict[str, Any]:
    user_id = str(entry.get("user_id") or entry.get("id") or entry.get("display_name") or "unknown")
    display_name = entry.get("display_name") or entry.get("name") or user_id
    session_role = entry.get("session_role") or entry.get("role") or default_session_role
    if isinstance(session_role, str):
        session_role = [session_role]
    project_role = entry.get("project_role") or []
    if isinstance(project_role, str):
        project_role = [project_role]
    permissions = entry.get("permissions_granted_in_session") or []
    if isinstance(permissions, str):
        permissions = [permissions]
    return {
        "user_id": user_id,
        "display_name": display_name,
        "session_role": session_role,
        "project_role": project_role,
        "license_role": entry.get("license_role") or "unknown",
        "joined_at": entry.get("joined_at") or _utc_now_iso(),
        "left_at": entry.get("left_at"),
        "invited_by": entry.get("invited_by"),
        "permissions_granted_in_session": permissions,
        "contributed_changes": bool(entry.get("contributed_changes", False)),
        "contribution_summary": entry.get("contribution_summary") or "",
        "creditable": bool(entry.get("creditable", True)),
        "credit_name_override": entry.get("credit_name_override"),
    }


def _default_session_credits(slug: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    host_id = payload.get("current_host_id") or payload.get("original_host_id") or payload.get("created_by") or "unknown"
    host_name = payload.get("host_display_name") or host_id
    participants = payload.get("session_participants") or payload.get("participants") or []
    normalized = [_normalize_participant(p) for p in participants if isinstance(p, dict)]
    if not normalized:
        normalized = [
            _normalize_participant(
                {
                    "user_id": host_id,
                    "display_name": host_name,
                    "session_role": ["host"],
                    "project_role": ["creator", "writer_of_record"],
                    "license_role": payload.get("license_role") or "master",
                    "joined_at": payload.get("session_started_at") or _utc_now_iso(),
                    "contributed_changes": True,
                    "contribution_summary": "Originating save author",
                },
                default_session_role="host",
            )
        ]
    return {
        "session_id": payload.get("session_id") or f"session_{uuid.uuid4().hex[:12]}",
        "session_started_at": payload.get("session_started_at") or _utc_now_iso(),
        "session_ended_at": payload.get("session_ended_at"),
        "host_user_id": host_id,
        "host_display_name": host_name,
        "participants": normalized,
    }


def attach_save_metadata(
    *,
    slug: str,
    payload: Dict[str, Any],
    save_kind: str,
    save_version: int = 1,
) -> Dict[str, Any]:
    """Return a new payload wrapped in PubCast save-file metadata.

    Existing metadata blocks are preserved and normalized where possible.
    """
    base = copy.deepcopy(payload)

    project_identity = copy.deepcopy(base.get("project_identity") or _default_project_identity(slug, base))
    project_identity.setdefault("project_id", slug)
    project_identity.setdefault("slug", slug)
    project_identity["last_modified_at"] = _utc_now_iso()

    project_credits = copy.deepcopy(base.get("project_credits") or _default_project_credits(base))
    session_credits = copy.deepcopy(base.get("session_credits") or _default_session_credits(slug, base))
    session_credits["participants"] = [
        _normalize_participant(p) for p in session_credits.get("participants", []) if isinstance(p, dict)
    ] or _default_session_credits(slug, base)["participants"]

    authority = copy.deepcopy(base.get("authority") or {
        "current_host_id": session_credits.get("host_user_id"),
        "save_authority": [session_credits.get("host_user_id")],
        "broadcast_authority": [session_credits.get("host_user_id")],
        "export_authority": [session_credits.get("host_user_id")],
    })

    contribution_history = copy.deepcopy(base.get("contribution_history") or [])
    if not isinstance(contribution_history, list):
        contribution_history = []

    save_manifest = {
        "schema": "pubcast.savefile.v1",
        "save_version": save_version,
        "save_kind": save_kind,
        "saved_at": _utc_now_iso(),
        "save_id": base.get("save_id") or uuid.uuid4().hex,
        "source_slug": slug,
        "title": project_identity.get("canonical_title"),
        "session_id": session_credits.get("session_id"),
        "participant_count": len(session_credits.get("participants", [])),
    }

    # Preserve user payload under a stable document section so future export logic
    # can read metadata without guessing at scene/stage shape.
    content = base.get("content") if isinstance(base.get("content"), dict) else None
    if content is None:
        content = {k: v for k, v in base.items() if k not in {
            "save_manifest", "project_identity", "project_credits", "session_credits",
            "authority", "contribution_history", "content"
        }}

    return {
        "save_manifest": save_manifest,
        "project_identity": project_identity,
        "project_credits": project_credits,
        "session_credits": session_credits,
        "authority": authority,
        "contribution_history": contribution_history,
        "content": content,
    }


__all__ = ["attach_save_metadata"]
