"""
mic_routes.py — Mic profile persistence + cough flag API

Routes
------
POST /api/mic/cough          — record cough event, flag orchestrator
GET  /api/mic/profiles       — list saved profiles (server-side backup)
POST /api/mic/profiles       — save/update a profile
DELETE /api/mic/profiles/{id} — remove a profile

The cough endpoint also broadcasts a WebSocket event to the hub so
the ConversationOrchestrator can suppress agent scheduling while
any mic is gated.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mic", tags=["mic"])

# ── Active cough state (in-memory, per server lifetime) ───────────────────
# { user_id: { active: bool, since: float } }
_cough_state: Dict[str, Dict] = {}


# ── Models ────────────────────────────────────────────────────────────────

class CoughEvent(BaseModel):
    type: str = "cough"
    payload: Dict[str, Any]


class MicProfile(BaseModel):
    id: str
    name: str
    role: str                    # host | guest | crew
    cough_key: str = "`"


# ── Cough endpoint ────────────────────────────────────────────────────────

@router.post("/cough")
async def mic_cough(request: Request, event: CoughEvent):
    """
    Record a cough event and broadcast to the hub.

    Payload: { user_id, display_name, active }

    The hub forwards this as a 'cough' event to all connected clients.
    The orchestrator watches for this and suppresses agent scheduling
    while active=True for the relevant user.
    """
    payload = event.payload
    user_id = payload.get("user_id", "unknown")
    active = bool(payload.get("active", False))
    display_name = payload.get("display_name", user_id)

    now = time.time()

    if active:
        _cough_state[user_id] = {"active": True, "since": now, "name": display_name}
        logger.info("🔇 Cough active: %s (%s)", display_name, user_id)
    else:
        entry = _cough_state.pop(user_id, None)
        if entry:
            duration = round(now - entry["since"], 2)
            logger.info("🎙 Cough released: %s (%s) — %.2fs", display_name, user_id, duration)

    # Broadcast through hub if available on app state
    hub = getattr(request.app.state, "hub", None)
    if hub:
        await hub.broadcast_system_event({
            "type": "cough",
            "payload": {
                "user_id": user_id,
                "display_name": display_name,
                "active": active,
                "ts": now,
            }
        })

    return JSONResponse({"ok": True, "user_id": user_id, "active": active})


@router.get("/cough/status")
async def cough_status():
    """Return currently active cough states. Useful for orchestrator polling."""
    return JSONResponse({
        "active_coughs": list(_cough_state.keys()),
        "detail": _cough_state,
    })


# ── Profile persistence (server-side backup; client uses localStorage) ────

@router.post("/profiles")
async def save_mic_profile(request: Request, profile: MicProfile):
    """Save a mic profile to disk (server-side backup)."""
    data_dir = _get_data_dir(request)
    profile_path = data_dir / f"{profile.id}.json"
    profile_path.write_text(profile.model_dump_json(), encoding="utf-8")
    return JSONResponse({"ok": True, "id": profile.id})


@router.get("/profiles")
async def list_mic_profiles(request: Request):
    """List all saved mic profiles."""
    data_dir = _get_data_dir(request)
    profiles = []
    for f in data_dir.glob("*.json"):
        try:
            import json
            profiles.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return JSONResponse(profiles)


@router.delete("/profiles/{profile_id}")
async def delete_mic_profile(request: Request, profile_id: str):
    """Remove a mic profile."""
    data_dir = _get_data_dir(request)
    # Sanitize: only allow safe filenames
    safe_id = "".join(c for c in profile_id if c.isalnum() or c == "_")
    profile_path = data_dir / f"{safe_id}.json"
    if profile_path.exists():
        profile_path.unlink()
        return JSONResponse({"ok": True, "deleted": safe_id})
    return JSONResponse({"ok": False, "detail": "not found"}, status_code=404)


# ── Helpers ───────────────────────────────────────────────────────────────

def _get_data_dir(request: Request) -> Path:
    base = getattr(request.app.state, "data_dir", Path("data"))
    d = Path(base) / "mic_profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d
