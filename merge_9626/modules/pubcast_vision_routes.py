"""
PUBCAST CAMERA VISION API ROUTES
FastAPI router for camera vision and streaming endpoints
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Query, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from modules.pubcast_vision_integration import (
    PubcastVisionManager,
    StreamQuality,
    VisionCameraBot
)

logger = structlog.get_logger("pubcast.vision.api")

# ============================================================================
# PYDANTIC MODELS FOR API
# ============================================================================

class CameraRegisterRequest(BaseModel):
    """Request model for registering a new vision camera"""
    camera_id: str = Field(..., description="Unique camera identifier")
    name: Optional[str] = Field(None, description="Human-readable camera name")
    world_id: str = Field("default", description="World/scene identifier")
    position_x: float = Field(0.0, description="Camera X position")
    position_y: float = Field(2.0, description="Camera Y position")
    position_z: float = Field(-10.0, description="Camera Z position")
    shot_type: str = Field("medium", description="Shot type: closeup, medium, wide, establishing")
    motion_style: str = Field("steady", description="Motion style: steady, handheld, dolly")
    fov: Optional[float] = Field(60.0, description="Horizontal field of view in degrees")
    target_avatar: Optional[str] = Field(None, description="Avatar ID to track")


class SceneObjectUpdate(BaseModel):
    """Model for scene object updates"""
    objects: List[Dict[str, Any]] = Field(default_factory=list, description="List of scene objects")
    lights: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="List of light sources")


class BroadcastStartRequest(BaseModel):
    """Request to start broadcasting"""
    quality: str = Field("HIGH", description="Stream quality: LOW, MEDIUM, HIGH, ULTRA")


class CameraSwitchRequest(BaseModel):
    """Request to switch primary camera"""
    camera_id: str = Field(..., description="Camera ID to switch to")


# ============================================================================
# ROUTER SETUP
# ============================================================================

def create_vision_router(vision_manager: PubcastVisionManager) -> APIRouter:
    """
    Create FastAPI router for camera vision endpoints.
    
    Args:
        vision_manager: PubcastVisionManager instance
    
    Returns:
        Configured APIRouter
    """
    router = APIRouter(prefix="/api/vision", tags=["Camera Vision"])
    
    # ========================================================================
    # CAMERA MANAGEMENT ENDPOINTS
    # ========================================================================
    
    @router.post("/cameras/register")
    async def register_camera(request: CameraRegisterRequest):
        """
        Register a new vision-enabled camera.
        
        This creates a camera with full vision capabilities including
        frustum culling, object detection, and streaming support.
        """
        config = request.dict()
        success = await vision_manager.register_vision_camera(config)
        
        if success:
            return {
                "success": True,
                "camera_id": request.camera_id,
                "message": f"Camera {request.camera_id} registered successfully"
            }
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to register camera {request.camera_id}"
            )
    
    @router.get("/cameras")
    async def list_cameras():
        """
        Get list of all registered vision cameras and their current status.
        """
        status = vision_manager.get_all_cameras_status()
        return JSONResponse(status)
    
    @router.get("/cameras/{camera_id}")
    async def get_camera_stats(camera_id: str):
        """
        Get detailed statistics for a specific camera.
        
        Includes:
        - Streaming status
        - Frame count
        - Quality metrics
        - Buffer status
        """
        stats = vision_manager.get_camera_stats(camera_id)
        
        if stats:
            return JSONResponse(stats)
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Camera {camera_id} not found"
            )
    
    @router.get("/cameras/{camera_id}/view")
    async def get_camera_view(camera_id: str):
        """
        Get what the camera currently sees.
        
        Returns:
        - Visible avatars with distances
        - Visible objects
        - Frame quality
        - Exposure level
        """
        view = vision_manager.get_camera_view(camera_id)
        
        if view:
            return JSONResponse(view)
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Camera {camera_id} not found"
            )
    
    @router.get("/cameras/views/all")
    async def get_all_camera_views():
        """
        Get what all cameras currently see.
        
        Useful for director view / multi-camera monitoring.
        """
        views = vision_manager.get_all_camera_views()
        return JSONResponse(views)
    
    # ========================================================================
    # BROADCASTING ENDPOINTS
    # ========================================================================
    
    @router.post("/broadcast/start")
    async def start_broadcast(request: BroadcastStartRequest):
        """
        Start broadcasting from all registered cameras.
        
        Quality options:
        - LOW: 360p
        - MEDIUM: 720p
        - HIGH: 1080p
        - ULTRA: 4K
        """
        try:
            quality = StreamQuality[request.quality.upper()]
        except KeyError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid quality: {request.quality}. Use LOW, MEDIUM, HIGH, or ULTRA"
            )
        
        vision_manager.start_broadcast(quality)
        
        return {
            "success": True,
            "message": "Broadcast started",
            "quality": quality.value,
            "camera_count": len(vision_manager.vision_cameras)
        }
    
    @router.post("/broadcast/stop")
    async def stop_broadcast():
        """
        Stop broadcasting from all cameras.
        """
        vision_manager.stop_broadcast()
        
        return {
            "success": True,
            "message": "Broadcast stopped",
            "frames_captured": vision_manager.frames_captured
        }
    
    @router.get("/broadcast/status")
    async def get_broadcast_status():
        """
        Get current broadcast status.
        """
        status = vision_manager.get_all_cameras_status()
        return JSONResponse(status)
    
    @router.post("/broadcast/camera/switch")
    async def switch_primary_camera(request: CameraSwitchRequest):
        """
        Switch the primary broadcasting camera.
        
        This will update both the vision system and integrate with
        the camera manager's program/preview switching system if available.
        """
        vision_manager.set_primary_camera(request.camera_id)
        
        return {
            "success": True,
            "primary_camera": request.camera_id,
            "message": f"Switched to camera {request.camera_id}"
        }
    
    @router.post("/broadcast/camera/auto")
    async def auto_select_camera():
        """
        Automatically select the best camera based on frame quality.
        
        Algorithm considers:
        - Frame quality (good > poor > blocked)
        - Number of visible avatars
        - Target visibility
        """
        best_camera = vision_manager.get_best_camera()
        
        if best_camera:
            vision_manager.set_primary_camera(best_camera)
            return {
                "success": True,
                "selected_camera": best_camera,
                "message": f"Auto-selected camera {best_camera}"
            }
        else:
            raise HTTPException(
                status_code=404,
                detail="No suitable camera found"
            )
    
    # ========================================================================
    # SCENE UPDATE ENDPOINTS
    # ========================================================================
    
    @router.post("/scene/update")
    async def update_scene(request: SceneObjectUpdate):
        """
        Update scene objects and lights for vision calculations.
        
        This should be called whenever the scene changes to keep
        camera vision synchronized with the 3D world.
        
        Objects should include:
        - id: unique identifier
        - type: "avatar", "prop", "furniture", etc.
        - x, y, z: position coordinates
        
        Lights should include:
        - id: unique identifier
        - x, y, z: position coordinates
        - intensity: light intensity (default 1.0)
        """
        vision_manager.update_scene_objects(request.objects, request.lights)
        
        # Trigger camera update
        frames = await vision_manager.update_all_cameras()
        
        return {
            "success": True,
            "objects_updated": len(request.objects),
            "lights_updated": len(request.lights or []),
            "frames_captured": len(frames),
            "camera_updates": {
                camera_id: {
                    "visible_count": frame.visible_count,
                    "quality": frame.frame_quality
                }
                for camera_id, frame in frames.items()
            }
        }
    
    # ========================================================================
    # WEBSOCKET ENDPOINT FOR REAL-TIME STREAMING
    # ========================================================================
    
    @router.websocket("/stream")
    async def camera_stream_websocket(websocket: WebSocket):
        """
        WebSocket endpoint for real-time camera frame streaming.
        
        Clients receive camera frames in real-time with:
        - Frame data
        - Visible objects
        - Quality metrics
        - Exposure information
        
        Message format:
        {
            "type": "camera_frame",
            "data": {
                "frame_id": 123,
                "camera_id": "cam_wide",
                "timestamp": 1234567890.123,
                "visible_avatars": [...],
                "frame_quality": "good"
            }
        }
        """
        await websocket.accept()
        await vision_manager.add_stream_client(websocket)
        
        logger.info("websocket_connected", 
                   client=websocket.client,
                   total_clients=len(vision_manager.stream_clients))
        
        try:
            # Keep connection alive and handle messages
            while True:
                # Wait for messages from client (e.g., control commands)
                try:
                    data = await websocket.receive_json()
                    
                    # Handle client commands
                    if data.get("type") == "switch_camera":
                        camera_id = data.get("camera_id")
                        if camera_id:
                            vision_manager.set_primary_camera(camera_id)
                            await websocket.send_json({
                                "type": "camera_switched",
                                "camera_id": camera_id
                            })
                    
                    elif data.get("type") == "get_status":
                        status = vision_manager.get_all_cameras_status()
                        await websocket.send_json({
                            "type": "status",
                            "data": status
                        })
                    
                except Exception as e:
                    logger.error("websocket_message_error", error=str(e))
                    break
        
        except WebSocketDisconnect:
            logger.info("websocket_disconnected", client=websocket.client)
        
        finally:
            await vision_manager.remove_stream_client(websocket)
    
    # ========================================================================
    # METRICS & MONITORING
    # ========================================================================
    
    @router.get("/metrics")
    async def get_metrics():
        """
        Get performance metrics for the vision system.
        
        Includes:
        - Total frames captured
        - Broadcast count
        - Active cameras
        - Stream client count
        """
        status = vision_manager.get_all_cameras_status()
        
        return {
            "frames_captured": vision_manager.frames_captured,
            "broadcasts_started": vision_manager.broadcasts_started,
            "active_cameras": len(vision_manager.vision_cameras),
            "streaming_clients": len(vision_manager.stream_clients),
            "is_broadcasting": vision_manager.is_broadcasting,
            "primary_camera": vision_manager.primary_camera,
            "cameras": status["cameras"]
        }
    
    return router


# ============================================================================
# INTEGRATION HELPER
# ============================================================================

def integrate_vision_with_fastapi(app, vision_manager: PubcastVisionManager):
    """
    Integrate vision router with existing FastAPI application.
    
    Usage:
        from fastapi import FastAPI
        from modules.pubcast_vision_integration import create_integrated_vision_manager
        from pubcast_vision_routes import integrate_vision_with_fastapi
        
        app = FastAPI()
        vision_manager = create_integrated_vision_manager()
        integrate_vision_with_fastapi(app, vision_manager)
    
    Args:
        app: FastAPI application instance
        vision_manager: PubcastVisionManager instance
    """
    router = create_vision_router(vision_manager)
    app.include_router(router)
    
    logger.info("vision_routes_integrated", 
               prefix="/api/vision",
               endpoints=len(router.routes))
    
    return router
