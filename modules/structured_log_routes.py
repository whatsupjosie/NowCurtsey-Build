"""
modules/structured_log_routes.py — Production Event Logging Routes
Rear View Foresight LLC — Feic Mo Chroí — 2026-04-18
"""
from __future__ import annotations
import asyncio, logging
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel

from .structured_log import get_production_log

logger = logging.getLogger("pubcast.structured_log_routes")

# ═══════════════════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════════════════

class LogQueryParams(BaseModel):
    limit: int = 50
    system: Optional[str] = None
    severity: Optional[str] = None

# ═══════════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════════

router = APIRouter(prefix="/api/logs", tags=["Production Logs"])

@router.get("/recent")
async def get_recent_logs(
    limit: int = Query(50, ge=1, le=1000),
    system: Optional[str] = Query(None, max_length=128),
    severity: Optional[str] = Query(None, max_length=32),
):
    """Query recent production log events."""
    log = get_production_log()
    if not log:
        return {"events": [], "warning": "Production log not initialized"}
    
    events = log.recent(limit=limit, system=system, severity=severity)
    return {
        "events": events,
        "count": len(events),
        "filters": {
            "system": system,
            "severity": severity,
            "limit": limit,
        },
    }

@router.get("/systems")
async def get_systems():
    """Get list of all logged systems."""
    log = get_production_log()
    if not log:
        return {"systems": []}
    
    # Extract unique systems from recent events
    events = log.recent(limit=1000)
    systems = sorted(set(e["system"] for e in events))
    
    return {"systems": systems}

@router.websocket("/ws")
async def logs_websocket(websocket: WebSocket):
    """Real-time production log feed."""
    await websocket.accept()
    logger.info("Production log WebSocket client connected")
    
    log = get_production_log()
    if not log:
        await websocket.send_json({"error": "Production log not initialized"})
        await websocket.close()
        return
    
    # Subscribe to real-time events
    async def on_event(event):
        try:
            await websocket.send_json(event)
        except Exception:
            pass  # Client disconnected
    
    log.subscribe(on_event)
    
    try:
        # Keep connection alive
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("Production log WebSocket client disconnected")
