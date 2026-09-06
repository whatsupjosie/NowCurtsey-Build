"""FastAPI routes for PubCast Bubble Stack adapter.

Import and include with:
    app.include_router(router)
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .bubble_stack import BUBBLE_STAT_SCHEMA, BubbleGridConfig, BubbleStack, serialize_bubble_stat
from .skeleton_tracker import SkeletonFrame, SkeletonTracker

router = APIRouter(prefix="/api/bubble-stack", tags=["bubble-stack"])
_stacks: Dict[str, BubbleStack] = {}
_tracker = SkeletonTracker()


class ConfigureRoomPayload(BaseModel):
    room_id: str
    origin: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    dimensions: Tuple[float, float, float] = (10.0, 3.0, 10.0)
    radius: float = Field(default=1.0, gt=0)
    spacing: float = Field(default=1.0, gt=0)


class AIPresencePayload(BaseModel):
    actor_ids: List[str] = []


class SkeletonFramePayload(BaseModel):
    actor_id: str
    bones: Dict[str, Tuple[float, float, float]]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)




@router.get("")
def list_bubble_rooms():
    """List configured Bubble Stack rooms without creating or waking them."""
    return {"ok": True, "rooms": list_stacks()}


@router.get("/schema")
def get_bubble_stat_schema():
    """Return the stable public BubbleStat schema used by PubCast adapters."""
    return {"ok": True, "schema": BUBBLE_STAT_SCHEMA}


@router.post("/{room_id}/configure")
def configure_room(room_id: str, payload: ConfigureRoomPayload):
    if payload.room_id != room_id:
        raise HTTPException(status_code=400, detail="room_id path and payload must match")
    config = BubbleGridConfig(
        room_id=room_id,
        origin=payload.origin,
        dimensions=payload.dimensions,
        radius=payload.radius,
        spacing=payload.spacing,
    )
    stack = BubbleStack(config)
    _stacks[room_id] = stack
    return {"ok": True, "room_id": room_id, "state": stack.state.value, "bubble_count": len(stack.bubbles)}


@router.post("/{room_id}/ai-presence")
def set_ai_presence(room_id: str, payload: AIPresencePayload):
    stack = get_stack(room_id)
    if stack is None:
        # Human-only rooms remain valid. AI presence without a configured
        # Bubble Stack is reported as AI_BLIND instead of crashing the room.
        return {"ok": True, "room_id": room_id, "state": "AI_BLIND", "ai_actor_ids": payload.actor_ids}
    stack.set_ai_presence(payload.actor_ids)
    return {"ok": True, "room_id": room_id, "state": stack.state.value, "ai_actor_ids": payload.actor_ids}


@router.post("/{room_id}/skeleton-frame")
def ingest_skeleton_frame(room_id: str, payload: SkeletonFramePayload):
    stack = get_stack(room_id)
    if stack is None:
        return {"ok": True, "room_id": room_id, "state": "AI_BLIND", "actor_id": payload.actor_id}
    frame = SkeletonFrame(actor_id=payload.actor_id, bones=payload.bones)
    posture = _tracker.classify_posture(frame)
    bones = _tracker.to_bone_presence(frame, confidence=payload.confidence)
    stack.ingest_skeleton_frame(payload.actor_id, bones, posture=posture.label)
    return {"ok": True, "room_id": room_id, "actor_id": payload.actor_id, "posture": posture.__dict__}


@router.get("/{room_id}/status")
def get_room_status(room_id: str):
    """Room status is the same stable BubbleStat summary exposed for diagnostics."""
    return get_bubble_summary(room_id)


@router.post("/{room_id}/sleep")
def sleep_room(room_id: str):
    """Put a configured Bubble Stack into SLEEPING by clearing AI presence."""
    stack = get_stack(room_id)
    if stack is None:
        return {"ok": True, "room_id": room_id, "state": "AI_BLIND"}
    stack.set_ai_presence([])
    return {"ok": True, "room_id": room_id, "state": stack.state.value}


@router.get("/{room_id}/stat")
def get_bubble_stat(room_id: str):
    return get_bubble_summary(room_id)


@router.get("/{room_id}/ai-context")
def get_ai_context(room_id: str):
    stack = get_stack(room_id)
    if stack is None:
        return {
            "world_state": get_bubble_summary(room_id),
            "active_conversation": [],
            "event_queue": [],
            "jeremy": "Bubble Stack: AI spatial awareness is blind/unconfigured for this room.",
        }
    return stack.build_ai_context()


def _require_stack(room_id: str) -> BubbleStack:
    try:
        return _stacks[room_id]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Bubble Stack is not configured for this room") from exc


# ─────────────────────────────────────────────────────────────────────────────
# Adapter helpers for PubCast integration
# ─────────────────────────────────────────────────────────────────────────────

def get_stack(room_id: str) -> BubbleStack | None:
    """Return a configured BubbleStack for adapters, or None if absent."""
    return _stacks.get(room_id)


def list_stacks() -> Dict[str, str]:
    """Return room_id → state for lightweight diagnostics."""
    return {room_id: stack.state.value for room_id, stack in _stacks.items()}


def get_bubble_summary(room_id: str) -> Dict[str, object]:
    """Return BubbleStat as a plain dict, using AI_BLIND when no stack exists."""
    stack = _stacks.get(room_id)
    if stack is None:
        return {
            "room_id": room_id,
            "state": "AI_BLIND",
            "ai_present": False,
            "bubble_count": 0,
            "active_bubble_count": 0,
            "actors_seen": [],
            "postures": {},
            "nearby": {},
            "meaningful_events": [{"type": "bubble_stack_missing_or_unconfigured"}],
        }
    return serialize_bubble_stat(stack.build_stat())

