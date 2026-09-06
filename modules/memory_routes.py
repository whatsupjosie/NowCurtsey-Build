# PubCast AI — memory_routes.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rear View Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart

"""
Universal Memory System API Routes
Persistent memory storage and retrieval
"""

import inspect
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .route_security import current_identity

router = APIRouter(prefix="/api/memory", tags=["memory"])

class MemoryEntryRequest(BaseModel):
    """Request to store a memory."""
    character_id: str = Field(..., min_length=1, max_length=128)
    content: str = Field(..., min_length=1, max_length=20000)
    memory_type: str = Field("conversation", min_length=1, max_length=64)
    importance: float = Field(0.5, ge=0.0, le=1.0)

_memory_system = None

def set_memory_instance(memory_instance):
    """Set global memory instance (called from main.py)."""
    global _memory_system
    _memory_system = memory_instance

@router.post("/store")
async def store_memory(
    request: MemoryEntryRequest,
    identity: Dict[str, Any] = Depends(current_identity),
):
    """Store a new memory."""
    if not _memory_system:
        raise HTTPException(503, "Memory system not initialized")
    try:
        stored = _memory_system.store(
            request.character_id,
            request.content,
            memory_type=request.memory_type,
            importance=request.importance
        )
        entry_id = await stored if inspect.isawaitable(stored) else stored
        return {"entry_id": entry_id, "status": "stored"}
    except Exception as e:
        raise HTTPException(500, f"Memory storage error: {e}")

@router.get("/{character_id}/recent")
async def get_recent_memories(character_id: str, limit: int = Query(20, ge=1, le=200)):
    """Get recent memories for a character."""
    if not _memory_system:
        raise HTTPException(503, "Memory system not initialized")
    try:
        memories = _memory_system.get_recent(character_id, limit)
        return {"character": character_id, "memories": memories, "count": len(memories)}
    except Exception as e:
        raise HTTPException(500, f"Memory retrieval error: {e}")

@router.get("/{character_id}/search")
async def search_memories(character_id: str, query: str = Query(..., min_length=1, max_length=500), limit: int = Query(10, ge=1, le=200)):
    """Search memories for a character."""
    if not _memory_system:
        raise HTTPException(503, "Memory system not initialized")
    try:
        results = _memory_system.search(character_id, query, limit)
        return {"character": character_id, "results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(500, f"Memory search error: {e}")
