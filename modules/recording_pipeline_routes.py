"""
modules/recording_pipeline_routes.py — Recording Pipeline Export Routes
Rear View Foresight LLC — Feic Mo Chroí — 2026-04-18

Extends base recording system with detailed event logging and professional exports.
"""
from __future__ import annotations
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Response, Query
from pathlib import Path

from .route_security import require_role

logger = logging.getLogger("pubcast.recording_pipeline_routes")

# ═══════════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════════

router = APIRouter(prefix="/api/recording", tags=["Recording Pipeline"])

# Pipeline sessions registry (injected by main.py)
_pipeline_sessions = {}

def register_pipeline_session(session_id: str, pipeline):
    """Register a pipeline session for export access."""
    _pipeline_sessions[session_id] = pipeline

def unregister_pipeline_session(session_id: str):
    """Remove pipeline session from registry."""
    _pipeline_sessions.pop(session_id, None)

# ═══════════════════════════════════════════════════════════════════════════
# EXPORT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/{session_id}/export/edl")
async def export_edl(session_id: str):
    """Export recording session as EDL (Edit Decision List)."""
    if session_id not in _pipeline_sessions:
        raise HTTPException(404, f"Session '{session_id}' not found or not recordable")
    
    pipeline = _pipeline_sessions[session_id]
    
    try:
        edl_content = pipeline.export_edl()
        
        return Response(
            content=edl_content,
            media_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="{session_id}.edl"',
                "Content-Type": "text/plain; charset=utf-8",
            },
        )
    except Exception as e:
        logger.error(f"EDL export failed for {session_id}: {e}")
        raise HTTPException(500, f"Export failed: {str(e)}")

@router.get("/{session_id}/export/fcpxml")
async def export_fcpxml(session_id: str):
    """Export recording session as Final Cut Pro XML."""
    if session_id not in _pipeline_sessions:
        raise HTTPException(404, f"Session '{session_id}' not found or not recordable")
    
    pipeline = _pipeline_sessions[session_id]
    
    try:
        xml_content = pipeline.export_fcpxml()
        
        return Response(
            content=xml_content,
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="{session_id}.fcpxml"',
                "Content-Type": "application/xml; charset=utf-8",
            },
        )
    except Exception as e:
        logger.error(f"FCP XML export failed for {session_id}: {e}")
        raise HTTPException(500, f"Export failed: {str(e)}")

@router.get("/{session_id}/summary")
async def get_session_summary(session_id: str):
    """Get detailed session summary with event counts."""
    if session_id not in _pipeline_sessions:
        raise HTTPException(404, f"Session '{session_id}' not found")
    
    pipeline = _pipeline_sessions[session_id]
    return pipeline.summary()

@router.post("/{session_id}/marker")
async def add_marker(
    session_id: str,
    label: str = Query(..., min_length=1, max_length=256),
    operator: str = Query("", max_length=128),
    identity: Dict[str, Any] = Depends(require_role("mod")),
):
    """Add a manual marker to the recording."""
    if session_id not in _pipeline_sessions:
        raise HTTPException(404, f"Session '{session_id}' not found")
    
    pipeline = _pipeline_sessions[session_id]
    pipeline.record_marker(label, operator)
    
    return {
        "marker_added": label,
        "operator": operator,
        "total_markers": len(pipeline._markers),
    }

@router.get("/{session_id}/events")
async def get_session_events(session_id: str, limit: int = Query(100, ge=1, le=1000)):
    """Get recent events from recording session."""
    if session_id not in _pipeline_sessions:
        raise HTTPException(404, f"Session '{session_id}' not found")
    
    pipeline = _pipeline_sessions[session_id]
    
    # Get last N events
    events = [e.to_dict() for e in pipeline._events[-limit:]]
    
    return {
        "session_id": session_id,
        "events": events,
        "total_events": len(pipeline._events),
    }
