"""modules/chat_rooms.py - Role-gated chat rooms and private DM system. Feic Mo Chroi 2026."""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger("pubcast.chat_rooms")

# Role hierarchy
ROLE_RANK: Dict[str, int] = {
    "guest":    0,
    "friend":   1,
    "crew":     2,
    "security": 3,
    "mod":      4,
    "owner":    5,
}

# Roles that bypass DM request
DM_BYPASS_ROLES: Set[str] = {"owner", "mod", "security"}

# Room registry
ROOM_REGISTRY: Dict[str, Dict[str, Any]] = {
    "stage":       {"display": "Stage",          "tier": "public",    "min_role": "guest",    "desc": "The main stage."},
    "gallery":     {"display": "Gallery",        "tier": "public",    "min_role": "guest",    "desc": "Artwork and community display."},
    "bar":         {"display": "Bar",            "tier": "public",    "min_role": "guest",    "desc": "Casual conversation."},
    "world":       {"display": "World",          "tier": "public",    "min_role": "guest",    "desc": "The PubWorld open space."},
    "greenroom":   {"display": "Green Room",     "tier": "social",    "min_role": "friend",   "desc": "Pre-show space for friends."},
    "lounge":      {"display": "Lounge",         "tier": "social",    "min_role": "friend",   "desc": "Private social space."},
    "dressing":    {"display": "Dressing Room",  "tier": "social",    "min_role": "friend",   "desc": "Avatar setup and prep."},
    "studio":      {"display": "Studio",         "tier": "backstage", "min_role": "crew",     "desc": "Main production floor."},
    "controlroom": {"display": "Control Room",   "tier": "backstage", "min_role": "crew",     "desc": "Technical direction."},
    "director":    {"display": "Director",       "tier": "backstage", "min_role": "crew",     "desc": "Camera switching."},
    "teleprompter":{"display": "Teleprompter",   "tier": "backstage", "min_role": "crew",     "desc": "Script feed."},
    "waitingroom": {"display": "Waiting Room",   "tier": "secure",    "min_role": "security", "desc": "Admission queue."},
    "governance":  {"display": "Governance",     "tier": "secure",    "min_role": "security", "desc": "Bans, mutes, freeze log."},
}

VALID_ROLES: Set[str] = set(ROLE_RANK.keys())


def role_can_access(role: str, room_id: str) -> bool:
    if room_id.startswith("dm____"):
        return True  # validated by DM system at connect time
    room = ROOM_REGISTRY.get(room_id)
    if not room:
        return False
    return ROLE_RANK.get(role, -1) >= ROLE_RANK.get(room["min_role"], 99)


def rooms_for_role(role: str) -> List[Dict[str, Any]]:
    tier_order = {"public": 0, "social": 1, "backstage": 2, "secure": 3}
    accessible = []
    for room_id, info in ROOM_REGISTRY.items():
        if role_can_access(role, room_id):
            accessible.append({
                "room_id":  room_id,
                "display":  info["display"],
                "tier":     info["tier"],
                "desc":     info["desc"],
                "min_role": info["min_role"],
            })
    return sorted(accessible, key=lambda r: (tier_order.get(r["tier"], 9), r["display"]))


def dm_room_id(user_a: str, user_b: str) -> str:
    a, b = sorted([user_a.lower(), user_b.lower()])
    return f"dm____{a}____{b}"


# ── DM Request system ─────────────────────────────────────────────────────────

class DMRequestStatus(str, Enum):
    PENDING  = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    BYPASSED = "bypassed"


@dataclass
class DMRequest:
    request_id:   str
    from_user:    str
    from_role:    str
    from_display: str
    to_user:      str
    status:       DMRequestStatus = DMRequestStatus.PENDING
    created_at:   float = field(default_factory=time.time)
    resolved_at:  Optional[float] = None
    message:      str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


class DMManager:
    def __init__(self):
        self._requests: Dict[str, DMRequest] = {}
        self._pending_pairs: Dict[tuple, str] = {}

    def request_dm(self, from_user: str, from_role: str, from_display: str,
                   to_user: str, message: str = "") -> DMRequest:
        if from_user.lower() == to_user.lower():
            raise ValueError("Cannot send a DM request to yourself")
        pair = (from_user.lower(), to_user.lower())
        if pair in self._pending_pairs:
            eid = self._pending_pairs[pair]
            existing = self._requests.get(eid)
            if existing and existing.status == DMRequestStatus.PENDING:
                raise ValueError(f"You already have a pending DM request to {to_user}.")

        status = (DMRequestStatus.BYPASSED if from_role in DM_BYPASS_ROLES
                  else DMRequestStatus.PENDING)
        req = DMRequest(
            request_id=str(uuid.uuid4())[:12],
            from_user=from_user, from_role=from_role, from_display=from_display,
            to_user=to_user, status=status, message=message[:280],
        )
        self._requests[req.request_id] = req
        if status == DMRequestStatus.PENDING:
            self._pending_pairs[pair] = req.request_id
        logger.info("DM %s: %s (%s) -> %s status=%s",
                    req.request_id, from_user, from_role, to_user, status.value)
        return req

    def accept(self, request_id: str, acting_user: str) -> DMRequest:
        req = self._validate(request_id, acting_user)
        if req.status != DMRequestStatus.PENDING:
            raise ValueError(f"Request {request_id} is not pending")
        req.status = DMRequestStatus.ACCEPTED
        req.resolved_at = time.time()
        self._pending_pairs.pop((req.from_user.lower(), req.to_user.lower()), None)
        return req

    def decline(self, request_id: str, acting_user: str) -> DMRequest:
        req = self._validate(request_id, acting_user)
        if req.status != DMRequestStatus.PENDING:
            raise ValueError(f"Request {request_id} is not pending")
        req.status = DMRequestStatus.DECLINED
        req.resolved_at = time.time()
        self._pending_pairs.pop((req.from_user.lower(), req.to_user.lower()), None)
        return req

    def can_open_dm(self, user_a: str, user_b: str) -> bool:
        a, b = sorted([user_a.lower(), user_b.lower()])
        for req in self._requests.values():
            ra, rb = sorted([req.from_user.lower(), req.to_user.lower()])
            if [ra, rb] == [a, b]:
                if req.status in (DMRequestStatus.ACCEPTED, DMRequestStatus.BYPASSED):
                    return True
        return False

    def pending_for_user(self, user_id: str) -> List[DMRequest]:
        return [r for r in self._requests.values()
                if r.to_user.lower() == user_id.lower()
                and r.status == DMRequestStatus.PENDING]

    def _validate(self, request_id: str, acting_user: str) -> DMRequest:
        req = self._requests.get(request_id)
        if not req:
            raise KeyError(f"DM request '{request_id}' not found")
        if req.to_user.lower() != acting_user.lower():
            raise PermissionError(f"Request {request_id} is addressed to {req.to_user}")
        return req


_dm_manager = DMManager()


def get_dm_manager() -> DMManager:
    return _dm_manager


# ── Router factory ────────────────────────────────────────────────────────────

def create_chat_router(hub: Any, get_identity_fn: Any) -> APIRouter:
    router = APIRouter(prefix="/api/chat", tags=["chat"])
    dm = get_dm_manager()

    @router.get("/rooms")
    async def list_rooms(identity: Dict[str, Any] = Depends(get_identity_fn)):
        role = identity.get("role", "guest")
        accessible = rooms_for_role(role)
        for r in accessible:
            r["online"] = len(hub.rooms.get(r["room_id"], set()))
        return {"role": role, "room_count": len(accessible), "rooms": accessible}

    @router.get("/rooms/{room_id}")
    async def room_info(room_id: str, identity: Dict[str, Any] = Depends(get_identity_fn)):
        if room_id not in ROOM_REGISTRY:
            raise HTTPException(404, f"Room not found: {room_id}")
        role = identity.get("role", "guest")
        if not role_can_access(role, room_id):
            req = ROOM_REGISTRY[room_id]["min_role"]
            raise HTTPException(403, f"Role '{role}' cannot access this room (requires {req})")
        info = ROOM_REGISTRY[room_id].copy()
        info["room_id"] = room_id
        info["online"] = len(hub.rooms.get(room_id, set()))
        info["recent_messages"] = await hub.get_recent_history(room_id, limit=20)
        return info

    @router.post("/rooms/{room_id}/send")
    async def send_message(room_id: str, request: Request,
                           identity: Dict[str, Any] = Depends(get_identity_fn)):
        if room_id not in ROOM_REGISTRY:
            raise HTTPException(404, f"Room not found: {room_id}")
        role = identity.get("role", "guest")
        if not role_can_access(role, room_id):
            raise HTTPException(403, f"Role '{role}' cannot send to this room")
        body = await request.json()
        text = (body.get("text") or body.get("message") or "").strip()
        if not text:
            raise HTTPException(400, "text is required")
        user_id = identity.get("user_id", "unknown")
        await hub.post_chat_message(room_id, user_id, text)
        return {"ok": True, "room_id": room_id, "user_id": user_id, "text": text}

    @router.get("/roles")
    async def list_roles():
        result = []
        for role, rank in sorted(ROLE_RANK.items(), key=lambda x: x[1]):
            accessible = rooms_for_role(role)
            tiers = sorted(set(r["tier"] for r in accessible))
            result.append({
                "role": role, "rank": rank,
                "tiers": tiers, "room_count": len(accessible),
                "dm_bypass": role in DM_BYPASS_ROLES,
            })
        return {"roles": result}

    @router.post("/dm/request")
    async def request_dm(request: Request, identity: Dict[str, Any] = Depends(get_identity_fn)):
        body = await request.json()
        to_user = (body.get("to_user") or "").strip()
        message = (body.get("message") or "").strip()
        if not to_user:
            raise HTTPException(400, "to_user is required")
        from_user    = identity.get("user_id", "")
        from_role    = identity.get("role", "guest")
        from_display = identity.get("display_name") or identity.get("username") or from_user
        try:
            req = dm.request_dm(from_user, from_role, from_display, to_user, message)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        room = dm_room_id(from_user, to_user)
        is_open = req.status.value in ("accepted", "bypassed")
        await hub.broadcast_system_event({
            "type": "dm_request",
            "payload": {
                "request_id": req.request_id,
                "from_user": from_user, "from_display": from_display,
                "from_role": from_role, "message": message,
                "bypassed": is_open, "dm_room": room if is_open else None,
            }
        })
        return {
            "ok": True, "request_id": req.request_id,
            "status": req.status.value,
            "dm_room": room if is_open else None,
            "message": (
                f"Channel open - connect to /ws/chat/{room}" if is_open
                else f"Request sent to {to_user}. Waiting for acceptance."
            ),
        }

    @router.post("/dm/accept/{request_id}")
    async def accept_dm(request_id: str, identity: Dict[str, Any] = Depends(get_identity_fn)):
        user_id = identity.get("user_id", "")
        try:
            req = dm.accept(request_id, user_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        room = dm_room_id(req.from_user, req.to_user)
        await hub.broadcast_system_event({
            "type": "dm_accepted",
            "payload": {"request_id": request_id,
                        "from_user": req.from_user, "to_user": req.to_user,
                        "dm_room": room}
        })
        return {"ok": True, "status": "accepted", "dm_room": room}

    @router.post("/dm/decline/{request_id}")
    async def decline_dm(request_id: str, identity: Dict[str, Any] = Depends(get_identity_fn)):
        user_id = identity.get("user_id", "")
        try:
            req = dm.decline(request_id, user_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        await hub.broadcast_system_event({
            "type": "dm_declined",
            "payload": {"request_id": request_id,
                        "from_user": req.from_user, "to_user": req.to_user}
        })
        return {"ok": True, "status": "declined"}

    @router.get("/dm/pending")
    async def pending_dms(identity: Dict[str, Any] = Depends(get_identity_fn)):
        user_id = identity.get("user_id", "")
        pending = dm.pending_for_user(user_id)
        return {"count": len(pending), "requests": [r.to_dict() for r in pending]}

    return router


def install_chat_websocket(app: Any, hub: Any, get_identity_fn: Any) -> None:
    dm = get_dm_manager()

    @app.websocket("/ws/chat/{room_id}")
    async def chat_ws(ws: WebSocket, room_id: str):
        identity: Dict[str, Any] = {}
        try:
            if callable(get_identity_fn):
                identity = await get_identity_fn(ws)
        except Exception:
            pass

        role    = identity.get("role", "guest")
        user_id = identity.get("user_id", f"anon-{int(time.time())}")
        display = identity.get("display_name") or identity.get("username") or user_id

        # Private room gate
        if room_id.startswith("dm____"):
            parts = room_id.replace("dm____", "").split("____")
            if len(parts) != 2:
                await ws.close(code=1008, reason="Malformed DM room ID"); return
            a, b = parts
            if user_id.lower() not in (a, b):
                await ws.close(code=1008, reason="You are not a participant in this DM"); return
            other = b if user_id.lower() == a else a
            if not dm.can_open_dm(user_id, other):
                await ws.close(code=1008,
                    reason="No accepted DM request. Use /api/chat/dm/request first."); return
        else:
            if room_id not in ROOM_REGISTRY:
                await ws.close(code=1008, reason=f"Unknown room: {room_id}"); return
            if not role_can_access(role, room_id):
                req = ROOM_REGISTRY[room_id]["min_role"]
                await ws.close(code=1008,
                    reason=f"Role '{role}' cannot access this room (requires {req})")
                logger.warning("WS denied: %s (%s) -> %s requires %s", user_id, role, room_id, req)
                return

        await hub.connect(ws, room_id)
        hub.user_display_name[user_id] = display
        tier = "private" if room_id.startswith("dm____") else ROOM_REGISTRY.get(room_id, {}).get("tier", "?")
        logger.info("WS chat: %s (%s) joined %s [%s]", display, role, room_id, tier)

        await hub._broadcast(room_id, {
            "type": "system",
            "payload": {"event": "join", "user_id": user_id,
                        "display": display, "role": role, "room": room_id}
        })

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    data = json.loads(raw)
                    if data.get("type") == "chat":
                        data["user"] = display
                        data["user_id"] = user_id
                        data["role"] = role
                        raw = json.dumps(data)
                except Exception:
                    pass
                await hub.handle_message(ws, room_id, raw)
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.warning("WS error: %s in %s: %s", user_id, room_id, exc)
        finally:
            await hub.disconnect(ws, room_id)
            hub.user_display_name.pop(user_id, None)
            logger.info("WS chat: %s left %s", display, room_id)
