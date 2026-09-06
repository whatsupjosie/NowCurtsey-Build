"""
modules/governance_routes.py — Governance REST API
═══════════════════════════════════════════════════
FastAPI router for moderation, consent, waiting room, AI disclosure.

Usage in main.py:
    from modules.governance import GovernanceEngine
    from modules.governance_routes import create_governance_router
    gov = GovernanceEngine(DATA_DIR)
    app.include_router(create_governance_router(gov, hub))

Rear View Foresight LLC — Feic Mo Chroí — 2026-03-24T09:30Z
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from modules.governance import (
    GovernanceEngine, BanType, ConsentType, EntryStatus,
)
from modules.route_security import bound_actor, current_identity, require_role

logger = logging.getLogger("pubcast.governance_routes")


async def _json_dict(request: Request) -> Dict[str, Any]:
    """Parse a request body as a JSON object with clean 400s."""
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"Malformed JSON body: {exc.msg}")
    except Exception as exc:
        raise HTTPException(400, f"Invalid JSON body: {exc}")
    if not isinstance(body, dict):
        raise HTTPException(400, "JSON body must be an object")
    return body


def _string_field(body: Dict[str, Any], key: str, *, default: str = "", required: bool = False,
                  max_length: int = 256) -> str:
    value = body.get(key, default)
    if value is None:
        value = default
    if not isinstance(value, str):
        raise HTTPException(400, f"{key} must be a string")
    value = value.strip()
    if required and not value:
        raise HTTPException(400, f"{key} required")
    if len(value) > max_length:
        raise HTTPException(400, f"{key} must be <= {max_length} characters")
    return value


def _optional_non_negative_number(body: Dict[str, Any], key: str) -> float | None:
    value = body.get(key, None)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(400, f"{key} must be a non-negative number")
    if value < 0:
        raise HTTPException(400, f"{key} must be non-negative")
    return float(value)


def _bool_field(body: Dict[str, Any], key: str, *, default: bool = False) -> bool:
    value = body.get(key, default)
    if not isinstance(value, bool):
        raise HTTPException(400, f"{key} must be a boolean")
    return value


def create_governance_router(gov: GovernanceEngine, hub: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api/governance", tags=["Governance"])

    # ═══ CONSENT & ENTRY ═══════════════════════════════════════════════════

    @router.get("/terms")
    async def get_terms():
        return {"terms": gov.get_terms_of_service()}

    @router.get("/ai-disclosure")
    async def get_ai_disclosure():
        # Pull bot names from hub if available
        bot_names = ["Pete", "Sir Purfluous", "Jeremy Cricket"]
        return {"disclosure": gov.get_ai_disclosure(bot_names)}

    @router.post("/consent")
    async def record_consent(request: Request, identity: Dict[str, Any] = Depends(current_identity)):
        body = await _json_dict(request)
        user_id = _string_field(body, "user_id", required=True, max_length=128)
        consent_type = _string_field(body, "consent_type", required=True, max_length=64)
        granted = _bool_field(body, "granted", default=False)
        try:
            ct = ConsentType(consent_type)
        except ValueError:
            raise HTTPException(400, f"Invalid consent type: {consent_type}")
        record = gov.record_consent(user_id, ct, granted)
        return {"ok": True, "consent_type": ct.value, "granted": granted}

    @router.get("/consent/{user_id}")
    async def get_consents(user_id: str):
        return gov.get_all_consents(user_id)

    @router.get("/consent/{user_id}/check")
    async def check_entry(user_id: str):
        allowed, msg = gov.can_enter(user_id)
        missing = gov.get_missing_consents(user_id)
        return {
            "allowed": allowed,
            "message": msg,
            "missing_consents": [c.value for c in missing],
        }

    # ═══ WAITING ROOM ══════════════════════════════════════════════════════

    @router.post("/waiting-room/request")
    async def request_entry(request: Request, identity: Dict[str, Any] = Depends(current_identity)):
        body = await _json_dict(request)
        user_id = _string_field(body, "user_id", required=True, max_length=128)
        display_name = _string_field(body, "display_name", default="Guest", max_length=128) or "Guest"
        target_room = _string_field(body, "target_room", default="studio", max_length=128) or "studio"
        consents = body.get("consents", {})
        if not isinstance(consents, dict):
            raise HTTPException(400, "consents must be an object")
        entry = gov.request_entry(user_id, display_name, target_room, consents)
        # Notify host via WebSocket
        if hub:
            import asyncio
            asyncio.create_task(hub.broadcast_system_event({
                "type": "waiting_room_request",
                "payload": {
                    "entry_id": entry.entry_id,
                    "user_id": user_id,
                    "display_name": display_name,
                    "target_room": target_room,
                },
            }))
        return {"ok": True, "entry_id": entry.entry_id, "status": entry.status.value}

    @router.get("/waiting-room")
    async def list_waiting(room: str | None = Query(None, max_length=128)):
        entries = gov.list_waiting(room)
        return {
            "waiting": [
                {
                    "entry_id": e.entry_id,
                    "user_id": e.user_id,
                    "display_name": e.display_name,
                    "target_room": e.target_room,
                    "requested_at": e.requested_at,
                }
                for e in entries
            ]
        }

    @router.post("/waiting-room/{entry_id}/approve")
    async def approve_entry(entry_id: str, request: Request, identity: Dict[str, Any] = Depends(require_role("mod"))):
        body = await _json_dict(request)
        approved_by = bound_actor(request=request, identity=identity, explicit_value=body.get("approved_by"), field_name="approved_by")
        entry = gov.approve_entry(entry_id, approved_by)
        if not entry:
            raise HTTPException(404, "Entry not found or already resolved")
        if hub:
            import asyncio
            asyncio.create_task(hub.broadcast_system_event({
                "type": "entry_approved",
                "payload": {"entry_id": entry_id, "user_id": entry.user_id,
                            "target_room": entry.target_room},
            }))
        return {"ok": True, "status": entry.status.value}

    @router.post("/waiting-room/{entry_id}/deny")
    async def deny_entry(entry_id: str, request: Request, identity: Dict[str, Any] = Depends(require_role("mod"))):
        body = await _json_dict(request)
        denied_by = bound_actor(request=request, identity=identity, explicit_value=body.get("denied_by"), field_name="denied_by")
        reason = _string_field(body, "reason", default="", max_length=512)
        entry = gov.deny_entry(entry_id, denied_by, reason)
        if not entry:
            raise HTTPException(404, "Entry not found or already resolved")
        return {"ok": True, "status": entry.status.value}

    # ═══ MODERATION ════════════════════════════════════════════════════════

    @router.post("/ban")
    async def ban_user(request: Request, identity: Dict[str, Any] = Depends(require_role("mod"))):
        body = await _json_dict(request)
        user_id = _string_field(body, "user_id", required=True, max_length=128)
        reason = _string_field(body, "reason", default="No reason given", max_length=512) or "No reason given"
        issued_by = bound_actor(request=request, identity=identity, explicit_value=body.get("issued_by"), field_name="issued_by")
        duration = _optional_non_negative_number(body, "duration_hours")
        try:
            ban_type = BanType(_string_field(body, "ban_type", default="session", max_length=64) or "session")
        except ValueError:
            raise HTTPException(400, f"Invalid ban type: {body.get('ban_type', 'session')}")
        ban = gov.ban_user(user_id, reason, issued_by, ban_type, duration)
        if hub:
            import asyncio
            asyncio.create_task(hub.broadcast_system_event({
                "type": "user_banned",
                "payload": {"user_id": user_id, "reason": reason},
            }))
        return {"ok": True, "ban_id": ban.ban_id}

    @router.post("/unban")
    async def unban_user(request: Request, identity: Dict[str, Any] = Depends(require_role("mod"))):
        body = await _json_dict(request)
        user_id = _string_field(body, "user_id", required=True, max_length=128)
        lifted_by = bound_actor(request=request, identity=identity, explicit_value=body.get("lifted_by"), field_name="lifted_by")
        if not gov.unban_user(user_id, lifted_by):
            raise HTTPException(404, "No active ban found")
        return {"ok": True}

    @router.post("/freeze")
    async def freeze_avatar(request: Request, identity: Dict[str, Any] = Depends(require_role("mod"))):
        body = await _json_dict(request)
        user_id = _string_field(body, "user_id", required=True, max_length=128)
        frozen_by = bound_actor(request=request, identity=identity, explicit_value=body.get("frozen_by"), field_name="frozen_by")
        reason = _string_field(body, "reason", default="", max_length=512)
        pose = body.get("pose_override", None)
        state = gov.freeze_avatar(user_id, frozen_by, reason, pose)
        if hub:
            import asyncio
            asyncio.create_task(hub.broadcast_system_event({
                "type": "avatar_frozen",
                "payload": {"user_id": user_id, "frozen_by": frozen_by, "reason": reason},
            }))
        return {"ok": True}

    @router.post("/unfreeze")
    async def unfreeze_avatar(request: Request, identity: Dict[str, Any] = Depends(require_role("mod"))):
        body = await _json_dict(request)
        user_id = _string_field(body, "user_id", required=True, max_length=128)
        unfrozen_by = bound_actor(request=request, identity=identity, explicit_value=body.get("unfrozen_by"), field_name="unfrozen_by")
        if not gov.unfreeze_avatar(user_id, unfrozen_by):
            raise HTTPException(404, "User not frozen")
        return {"ok": True}

    @router.post("/mute")
    async def mute_user(request: Request, identity: Dict[str, Any] = Depends(require_role("mod"))):
        body = await _json_dict(request)
        user_id = _string_field(body, "user_id", required=True, max_length=128)
        muted_by = bound_actor(request=request, identity=identity, explicit_value=body.get("muted_by"), field_name="muted_by")
        duration = _optional_non_negative_number(body, "duration_seconds") or 0
        gov.mute_user(user_id, muted_by, duration)
        return {"ok": True}

    @router.post("/unmute")
    async def unmute_user(request: Request, identity: Dict[str, Any] = Depends(require_role("mod"))):
        body = await _json_dict(request)
        user_id = _string_field(body, "user_id", required=True, max_length=128)
        unmuted_by = bound_actor(request=request, identity=identity, explicit_value=body.get("unmuted_by"), field_name="unmuted_by")
        gov.unmute_user(user_id, unmuted_by)
        return {"ok": True}

    @router.post("/kick")
    async def kick_user(request: Request, identity: Dict[str, Any] = Depends(require_role("mod"))):
        body = await _json_dict(request)
        user_id = _string_field(body, "user_id", required=True, max_length=128)
        kicked_by = bound_actor(request=request, identity=identity, explicit_value=body.get("kicked_by"), field_name="kicked_by")
        reason = _string_field(body, "reason", default="", max_length=512)
        gov.ban_user(user_id, reason or "Kicked", kicked_by, BanType.SESSION)
        if hub:
            import asyncio
            asyncio.create_task(hub.broadcast_system_event({
                "type": "user_kicked",
                "payload": {"user_id": user_id, "reason": reason},
            }))
        return {"ok": True}

    # ═══ AUDIT ═════════════════════════════════════════════════════════════

    @router.get("/audit")
    async def get_audit_log(limit: int = Query(100, ge=1, le=1000)):
        return gov.get_audit_log(limit)

    @router.get("/audit/{user_id}")
    async def get_user_audit(user_id: str):
        return gov.get_user_history(user_id)

    @router.get("/status")
    async def governance_status():
        return {
            "active_bans": len(gov.list_active_bans()),
            "frozen_avatars": len(gov.list_frozen_avatars()),
            "muted_users": len(gov.list_muted_users()),
            "waiting_room": len(gov.list_waiting()),
        }

    return router
