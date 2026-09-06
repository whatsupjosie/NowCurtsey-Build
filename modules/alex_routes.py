# PubCast AI — alex_routes.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rear View Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart

"""
Alex Core API Routes
Provides endpoints for interacting with Alex AI companion
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

from .route_security import current_identity, require_role

router = APIRouter(prefix="/api/alex", tags=["alex"])


class MessageRequest(BaseModel):
    """Request to send message to Alex."""
    message: str = Field(..., min_length=1, max_length=10000)
    user_id: Optional[str] = Field("default", min_length=1, max_length=128)
    context: Optional[Dict[str, Any]] = None
    typing_speed: Optional[float] = Field(60.0, ge=0.0, le=1000.0)


class StateResponse(BaseModel):
    """Alex's current state."""
    state: str
    battery: str
    engagement_score: float


def _normalize_recent_memories(memories: Any) -> List[Dict[str, Any]]:
    """Normalize Alex memory payloads for API responses across implementations."""
    normalized: List[Dict[str, Any]] = []
    for memory in memories or []:
        if isinstance(memory, dict):
            normalized.append(memory)
            continue
        normalized.append({
            "id": getattr(memory, "id", ""),
            "content": getattr(memory, "content", ""),
            "memory_type": getattr(getattr(memory, "memory_type", None), "value", str(getattr(memory, "memory_type", ""))),
            "timestamp": getattr(getattr(memory, "timestamp", None), "isoformat", lambda: "")(),
            "emotional_tags": getattr(memory, "emotional_tags", getattr(memory, "tags", [])),
        })
    return normalized


# Global alex instance/provider - will be set by main.py
_alex_core = None
_alex_provider = None
_choreo_hook = None

logger = logging.getLogger("pubcast.alex_routes")


def set_choreo_hook(hook):
    """
    Register an async callable(alex, user_id) invoked after each processed
    message. Used to drive affect→choreography modulation without alex_routes
    needing to import main (which would be circular).
    """
    global _choreo_hook
    _choreo_hook = hook


def set_alex_instance(alex_instance):
    """Set the fallback Alex instance (called from main.py)."""
    global _alex_core
    _alex_core = alex_instance


def set_alex_provider(provider):
    """Set a user-aware Alex provider, e.g. AlexJeremyBridge.alex_for."""
    global _alex_provider
    _alex_provider = provider


def _resolve_alex(user_id: Optional[str] = None):
    if _alex_provider is not None:
        return _alex_provider(user_id or "default")
    return _alex_core


@router.post("/message")
async def send_message(request: MessageRequest, identity: Dict[str, Any] = Depends(current_identity)):
    """Send a message to Alex and get response."""
    alex = _resolve_alex(request.user_id)
    if not alex:
        raise HTTPException(503, "Alex Core not initialized")
    
    try:
        metadata = dict(request.context or {})
        response = await alex.process_message(
            request.message,
            typing_speed=float(request.typing_speed or 60.0),
            metadata=metadata,
            user_id=request.user_id,
        )

        # Affect → choreography. Best-effort and fully isolated: a failure here
        # must never break the chat response the user is waiting on.
        if _choreo_hook is not None:
            try:
                await _choreo_hook(alex, request.user_id or "default")
            except Exception as hook_exc:  # noqa: BLE001 - deliberate catch-all
                logger.warning("affect→choreo hook failed (non-fatal): %s", hook_exc)

        return {"response": response, "status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Alex processing error: {e}")


@router.get("/state")
async def get_state(user_id: str = Query("default", min_length=1, max_length=128)):
    """Get Alex's current state."""
    alex = _resolve_alex(user_id)
    if not alex:
        raise HTTPException(503, "Alex Core not initialized")
    
    try:
        state = alex.get_state()
        return state
    except Exception as e:
        raise HTTPException(500, f"State retrieval error: {e}")


@router.post("/grounding")
async def trigger_grounding(
    user_id: str = Query("default", min_length=1, max_length=128),
    identity: Dict[str, Any] = Depends(current_identity),
):
    """Trigger a grounding exercise."""
    alex = _resolve_alex(user_id)
    if not alex:
        raise HTTPException(503, "Alex Core not initialized")
    
    try:
        result = await alex.grounding_check()
        return {"grounding": result, "status": "ok"}
    except Exception as e:
        raise HTTPException(500, f"Grounding error: {e}")


@router.get("/memory/recent")
async def get_recent_memory(limit: int = Query(10, ge=1, le=200), user_id: str = Query("default", min_length=1, max_length=128)):
    """Get recent conversation memory."""
    alex = _resolve_alex(user_id)
    if not alex:
        raise HTTPException(503, "Alex Core not initialized")
    
    try:
        memories = alex.get_recent_memories(limit)
        normalized = _normalize_recent_memories(memories)
        return {"memories": normalized, "count": len(normalized)}
    except Exception as e:
        raise HTTPException(500, f"Memory retrieval error: {e}")


@router.post("/reset")
async def reset_alex(
    user_id: str = Query("default", min_length=1, max_length=128),
    identity: Dict[str, Any] = Depends(require_role("mod")),
):
    """Reset Alex to initial state."""
    alex = _resolve_alex(user_id)
    if not alex:
        raise HTTPException(503, "Alex Core not initialized")
    
    try:
        alex.reset()
        return {"status": "reset", "message": "Alex has been reset"}
    except Exception as e:
        raise HTTPException(500, f"Reset error: {e}")
