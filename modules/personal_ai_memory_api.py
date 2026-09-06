# PubCast AI - personal_ai_memory_api.py
# Copyright 2024-2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rear View Foresight LLC - All Rights Reserved
# Feic Mo Chroi - See My Heart
"""User-scoped memory API for external or personal AI context handoff."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from . import memory_engine
from .context_block import ContextBlock, ContextKind, ContextSource
from .context_retriever import ContextRetriever
from .memory_ingestor import MemoryIngestor
from .route_security import current_identity


router = APIRouter(prefix="/api/personal-memory", tags=["personal-memory"])

_data_dir: Optional[Path] = None
_memory_system: Any = None
_ingestor: Optional[MemoryIngestor] = None
_retriever: Optional[ContextRetriever] = None


class PersonalMemoryWrite(BaseModel):
    user_id: str = Field("", max_length=128)
    content: str = Field(..., min_length=1, max_length=20000)
    memory_type: str = Field("conversation", max_length=64)
    importance: float = Field(0.5, ge=0.0, le=1.0)
    source_model: str = Field("personal_ai", max_length=128)
    session_id: str = Field("default", max_length=128)
    room_id: str = Field("personal_ai", max_length=128)
    project_id: str = Field("pubcast", max_length=128)


def configure_personal_memory_api(
    *,
    data_dir: Path,
    memory_system: Any = None,
    ingestor: Optional[MemoryIngestor] = None,
) -> None:
    """Wire runtime dependencies from main.py."""
    global _data_dir, _memory_system, _ingestor, _retriever
    _data_dir = Path(data_dir)
    _memory_system = memory_system
    _ingestor = ingestor or MemoryIngestor(_data_dir, memory_system=memory_system, project_id="pubcast")
    _retriever = ContextRetriever(_data_dir, memory_system=memory_system)


def _scoped_user(identity: Dict[str, Any]) -> str:
    return str(identity.get("user_id") or "anon").strip() or "anon"


def _kind(memory_type: str) -> ContextKind:
    normalized = (memory_type or "conversation").strip().lower()
    if normalized in ContextKind._value2member_map_:
        return ContextKind(normalized)
    if normalized == "emotion":
        return ContextKind.EMOTIONAL
    if normalized == "relationship":
        return ContextKind.RELATIONAL
    return ContextKind.CONVERSATION


@router.post("/write")
async def write_memory(
    request: PersonalMemoryWrite,
    identity: Dict[str, Any] = Depends(current_identity),
):
    if _ingestor is None:
        raise HTTPException(503, "Personal memory API not initialized")
    scoped_user = _scoped_user(identity)
    block = ContextBlock.new(
        content=request.content,
        source=ContextSource.PERSONAL_AI,
        kind=_kind(request.memory_type),
        author_id=scoped_user,
        session_id=request.session_id,
        room_id=request.room_id,
        project_id=request.project_id,
        importance=request.importance,
        raw_payload={
            "declared_user_id": request.user_id,
            "source_model": request.source_model,
            "scoped_user_id": scoped_user,
        },
    )
    result = await _ingestor.ingest(block)
    return {
        "accepted": result.accepted,
        "entry_id": result.block_id,
        "reason": result.skipped_reason,
        "scoped_user_id": scoped_user,
    }


@router.get("/query")
async def query_memory(
    query: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(10, ge=1, le=50),
    project_id: str = Query("pubcast", max_length=128),
    identity: Dict[str, Any] = Depends(current_identity),
):
    if _retriever is None:
        raise HTTPException(503, "Personal memory API not initialized")
    scoped_user = _scoped_user(identity)
    memories = _retriever.retrieve(
        query=query,
        user_id=scoped_user,
        project_id=project_id,
        character_id=scoped_user,
        limit=limit,
    )
    return {
        "scoped_user_id": scoped_user,
        "memories": [asdict(memory) for memory in memories],
        "count": len(memories),
    }


@router.get("/recent")
async def recent_memory(
    limit: int = Query(10, ge=1, le=100),
    identity: Dict[str, Any] = Depends(current_identity),
):
    if _data_dir is None:
        raise HTTPException(503, "Personal memory API not initialized")
    scoped_user = _scoped_user(identity)
    memories = memory_engine.recent_for_user(_data_dir, user_id=scoped_user, limit=limit)
    return {"scoped_user_id": scoped_user, "memories": memories, "count": len(memories)}


__all__ = ["router", "configure_personal_memory_api"]
