"""
modules/hotspot_system.py — Interactive Hotspot Management & Triggering
Rear View Foresight LLC — Feic Mo Chroí — 2026-04-18

Loads hotspot definitions from data/hotspots/ and handles trigger events.
"""
from __future__ import annotations
import json, logging
from pathlib import Path
from typing import Dict, Optional, Callable, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .route_security import current_identity

logger = logging.getLogger("pubcast.hotspots")

# ═══════════════════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════════════════

class HotspotTriggerRequest(BaseModel):
    room: str
    hotspot_id: str
    user_id: str

# ═══════════════════════════════════════════════════════════════════════════
# HOTSPOT MANAGER
# ═══════════════════════════════════════════════════════════════════════════

class HotspotManager:
    def __init__(self, hotspots_dir: Path):
        self._hotspots_dir = hotspots_dir
        self._rooms: Dict[str, dict] = {}
        self._handlers: Dict[str, Callable] = {}
        self._load_all_hotspots()
    
    def _load_all_hotspots(self):
        """Load all hotspot definitions from data/hotspots/."""
        if not self._hotspots_dir.exists():
            logger.warning(f"Hotspots directory not found: {self._hotspots_dir}")
            return
        
        for path in self._hotspots_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                room_name = path.stem
                self._rooms[room_name] = data
                logger.info(f"Loaded hotspots for '{room_name}': {len(data.get('hotspots', []))} hotspots")
            except Exception as e:
                logger.error(f"Failed to load {path.name}: {e}")
    
    def register_handler(self, action_type: str, handler: Callable):
        """
        Register a handler for hotspot action types.
        
        Examples:
            hotspot_manager.register_handler("transition", handle_room_transition)
            hotspot_manager.register_handler("animation", handle_animation)
            hotspot_manager.register_handler("custom", handle_custom_event)
        
        Handler signature:
            async def handler(action: dict, user_id: str, hotspot_id: str, room: str) -> Any
        """
        self._handlers[action_type] = handler
        logger.info(f"Registered handler for action type: {action_type}")
    
    def get_room_hotspots(self, room: str) -> Optional[dict]:
        """Get all hotspots for a room."""
        return self._rooms.get(room)
    
    def get_hotspot(self, room: str, hotspot_id: str) -> Optional[dict]:
        """Get specific hotspot by room and ID."""
        room_data = self._rooms.get(room)
        if not room_data:
            return None
        
        for hotspot in room_data.get("hotspots", []):
            if hotspot["id"] == hotspot_id:
                return hotspot
        
        return None
    
    async def trigger_hotspot(self, room: str, hotspot_id: str, user_id: str) -> dict:
        """
        Trigger a hotspot action.
        Returns action result or raises error.
        """
        hotspot = self.get_hotspot(room, hotspot_id)
        if not hotspot:
            raise ValueError(f"Hotspot '{hotspot_id}' not found in room '{room}'")
        
        action = hotspot.get("action")
        if not action:
            raise ValueError(f"Hotspot '{hotspot_id}' has no action")
        
        action_type = action.get("type")
        handler = self._handlers.get(action_type)
        
        if not handler:
            logger.warning(f"No handler registered for action type: {action_type}")
            return {
                "hotspot_id": hotspot_id,
                "action_type": action_type,
                "status": "no_handler",
                "message": f"No handler for '{action_type}' (will implement)",
            }
        
        # Call handler
        try:
            result = await handler(action, user_id, hotspot_id, room)
            return {
                "hotspot_id": hotspot_id,
                "action_type": action_type,
                "status": "triggered",
                "result": result,
            }
        except Exception as e:
            logger.error(f"Hotspot handler error ({action_type}): {e}")
            raise

# Global instance
_hotspot_manager: Optional[HotspotManager] = None

def init_hotspot_system(data_dir: Path):
    """Initialize hotspot system."""
    global _hotspot_manager
    hotspots_dir = data_dir / "hotspots"
    _hotspot_manager = HotspotManager(hotspots_dir)
    return _hotspot_manager

def get_hotspot_manager() -> HotspotManager:
    """Get hotspot manager instance."""
    if not _hotspot_manager:
        raise RuntimeError("Hotspot system not initialized")
    return _hotspot_manager

# ═══════════════════════════════════════════════════════════════════════════
# DEFAULT HANDLERS
# ═══════════════════════════════════════════════════════════════════════════

async def default_transition_handler(action: dict, user_id: str, hotspot_id: str, room: str):
    """
    Default transition handler.
    Broadcasts room transition event via WebSocket hub.
    """
    destination = action.get("destination", "unknown")
    spawn_point = action.get("spawnPoint", "default")
    
    logger.info(f"Transition: {user_id} from {room} → {destination} (spawn: {spawn_point})")
    
    # This will be wired to hub.broadcast() in main.py
    return {
        "type": "transition",
        "from_room": room,
        "to_room": destination,
        "spawn_point": spawn_point,
        "user_id": user_id,
    }

async def default_animation_handler(action: dict, user_id: str, hotspot_id: str, room: str):
    """
    Default animation handler.
    Triggers avatar animation via WebSocket.
    """
    animation = action.get("animation", "")
    
    logger.info(f"Animation: {user_id} in {room} → {animation}")
    
    return {
        "type": "animation",
        "animation": animation,
        "user_id": user_id,
        "room": room,
    }

async def default_custom_handler(action: dict, user_id: str, hotspot_id: str, room: str):
    """
    Default custom event handler.
    Broadcasts custom event via WebSocket.
    """
    event = action.get("event", "")
    
    logger.info(f"Custom event: {user_id} in {room} → {event}")
    
    return {
        "type": "custom_event",
        "event": event,
        "user_id": user_id,
        "room": room,
        "hotspot_id": hotspot_id,
    }

# ═══════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════

router = APIRouter(prefix="/api/hotspots", tags=["Hotspots"])

@router.get("/rooms")
async def list_rooms():
    """List all rooms with hotspot data."""
    hm = get_hotspot_manager()
    return {
        "rooms": list(hm._rooms.keys()),
        "count": len(hm._rooms),
    }

@router.get("/{room}")
async def get_room_hotspots(room: str):
    """Get all hotspots for a specific room."""
    hm = get_hotspot_manager()
    
    data = hm.get_room_hotspots(room)
    if not data:
        raise HTTPException(404, f"Room '{room}' has no hotspot data")
    
    return data

@router.post("/trigger")
async def trigger_hotspot(req: HotspotTriggerRequest, identity: Dict[str, Any] = Depends(current_identity)):
    """Trigger a hotspot action."""
    hm = get_hotspot_manager()
    
    try:
        result = await hm.trigger_hotspot(req.room, req.hotspot_id, req.user_id)
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Hotspot trigger failed: {e}")
        raise HTTPException(500, f"Trigger failed: {str(e)}")
