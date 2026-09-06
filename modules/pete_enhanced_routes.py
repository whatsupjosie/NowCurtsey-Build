# PubCast AI — pete_enhanced_routes.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rear View Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart

"""
Pete Enhanced API Routes
Twin engine orchestrator control and monitoring
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from .route_security import require_role

router = APIRouter(prefix="/api/pete-enhanced", tags=["pete-enhanced"])


class ProductionCommand(BaseModel):
    """Production control command for Pete Enhanced."""
    command: str = Field(..., min_length=1, max_length=128)
    params: Dict[str, Any] = Field(default_factory=dict)


# Global Pete Enhanced instance
_pete_enhanced = None


def set_pete_enhanced_instance(pete_instance):
    """Set the global Pete Enhanced instance (called from main.py)."""
    global _pete_enhanced
    _pete_enhanced = pete_instance


@router.get("/status")
async def get_status():
    """Get complete twin engine system status."""
    if not _pete_enhanced:
        raise HTTPException(503, "Pete Enhanced not initialized")
    
    try:
        status = _pete_enhanced.get_twin_engine_status()
        return status
    except Exception as e:
        raise HTTPException(500, f"Status retrieval error: {e}")


@router.get("/health")
async def get_health():
    """Get twin engine health assessment."""
    if not _pete_enhanced:
        raise HTTPException(503, "Pete Enhanced not initialized")
    
    try:
        status = _pete_enhanced.get_twin_engine_status()
        return {
            "health": status.get("twin_engine_health"),
            "operational": status.get("system_operational"),
            "bridge_status": status.get("bridge", {}).get("status"),
            "streaming_fps": status.get("streaming", {}).get("fps"),
            "total_latency_ms": status.get("performance", {}).get("total_pipeline_latency_ms")
        }
    except Exception as e:
        raise HTTPException(500, f"Health check error: {e}")


@router.post("/control")
async def production_control(
    request: ProductionCommand,
    identity: Dict[str, Any] = Depends(require_role("mod")),
):
    """Send production control command to Pete Enhanced."""
    if not _pete_enhanced:
        raise HTTPException(503, "Pete Enhanced not initialized")
    
    try:
        await _pete_enhanced.handle_production_control(
            request.command,
            request.params
        )
        return {"status": "ok", "command": request.command}
    except Exception as e:
        raise HTTPException(500, f"Production control error: {e}")


@router.post("/quality/{level}")
async def set_quality(level: str, identity: Dict[str, Any] = Depends(require_role("mod"))):
    """Set rendering quality level (low/medium/high)."""
    if not _pete_enhanced:
        raise HTTPException(503, "Pete Enhanced not initialized")
    
    if level not in ["low", "medium", "high"]:
        raise HTTPException(400, f"Invalid quality level: {level}")
    
    try:
        await _pete_enhanced._set_rendering_quality(level)
        return {"quality": level, "status": "ok"}
    except Exception as e:
        raise HTTPException(500, f"Quality adjustment error: {e}")


@router.get("/metrics/bridge")
async def get_bridge_metrics():
    """Get Bridge (Python → Rust) metrics."""
    if not _pete_enhanced:
        raise HTTPException(503, "Pete Enhanced not initialized")
    
    try:
        status = _pete_enhanced.get_twin_engine_status()
        return status.get("bridge", {})
    except Exception as e:
        raise HTTPException(500, f"Metrics error: {e}")


@router.get("/metrics/streaming")
async def get_streaming_metrics():
    """Get WebRTC streaming (Rust → Browser) metrics."""
    if not _pete_enhanced:
        raise HTTPException(503, "Pete Enhanced not initialized")
    
    try:
        status = _pete_enhanced.get_twin_engine_status()
        return status.get("streaming", {})
    except Exception as e:
        raise HTTPException(500, f"Metrics error: {e}")


@router.get("/metrics/rust-engine")
async def get_rust_engine_metrics():
    """Get Rust engine health metrics."""
    if not _pete_enhanced:
        raise HTTPException(503, "Pete Enhanced not initialized")
    
    try:
        status = _pete_enhanced.get_twin_engine_status()
        return status.get("rust_engine", {})
    except Exception as e:
        raise HTTPException(500, f"Metrics error: {e}")


@router.get("/metrics/performance")
async def get_performance_metrics():
    """Get overall performance metrics."""
    if not _pete_enhanced:
        raise HTTPException(503, "Pete Enhanced not initialized")
    
    try:
        status = _pete_enhanced.get_twin_engine_status()
        return status.get("performance", {})
    except Exception as e:
        raise HTTPException(500, f"Metrics error: {e}")


@router.post("/shutdown")
async def shutdown(identity: Dict[str, Any] = Depends(require_role("mod"))):
    """Gracefully shutdown the twin engine system."""
    if not _pete_enhanced:
        raise HTTPException(503, "Pete Enhanced not initialized")
    
    try:
        await _pete_enhanced.shutdown_twin_engine_system()
        return {"status": "shutdown_initiated"}
    except Exception as e:
        raise HTTPException(500, f"Shutdown error: {e}")
