"""
PubWorld Scene Management System

Manages 3D virtual environments, block-based building, and scene timelines.
Integrates with Rust rendering core for real-time 3D visualization.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, Field, ValidationError, constr

from .persistence import sanitize_filename


class AtmosphereSettings(BaseModel):
    """Environmental atmosphere configuration."""
    sky: constr(strip_whitespace=True, min_length=1) = "day"
    ground: constr(strip_whitespace=True, min_length=1) = "grass"
    weather: constr(strip_whitespace=True, min_length=1) = "clear"
    fog_density: float = Field(default=0.0, ge=0.0, le=1.0)
    ambient_light: float = Field(default=0.3, ge=0.0, le=1.0)
    sun_intensity: float = Field(default=1.0, ge=0.0, le=2.0)


class GridCell(BaseModel):
    """A single cell in the 3D block grid."""
    x: int
    y: int
    z: int = 0  # Added Z coordinate for 3D
    height: float = 1.0
    width: float = 1.0
    depth: float = 1.0
    color: constr(strip_whitespace=True, min_length=1) = "#ffffff"
    material: str = "default"
    tags: List[str] = Field(default_factory=list)


class TriggerConfig(BaseModel):
    """Interactive trigger configuration."""
    trigger_id: constr(strip_whitespace=True, min_length=1)
    label: constr(strip_whitespace=True, min_length=1)
    kind: constr(strip_whitespace=True, min_length=1)
    position: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    parameters: Dict[str, Any] = Field(default_factory=dict)


class CameraPosition(BaseModel):
    """Predefined camera position in the scene."""
    camera_id: constr(strip_whitespace=True, min_length=1)
    name: str
    position: List[float] = Field(min_items=3, max_items=3)
    rotation: List[float] = Field(min_items=3, max_items=3)
    fov: float = Field(default=60.0, gt=0.0, le=180.0)


class PubWorldScene(BaseModel):
    """Complete 3D scene definition."""
    scene_id: constr(strip_whitespace=True, min_length=6, max_length=48)
    name: constr(strip_whitespace=True, min_length=1, max_length=64)
    description: str = ""
    grid: List[GridCell] = Field(default_factory=list)
    atmosphere: AtmosphereSettings = Field(default_factory=AtmosphereSettings)
    triggers: List[TriggerConfig] = Field(default_factory=list)
    cameras: List[CameraPosition] = Field(default_factory=list)
    created_at: float
    updated_at: float


class TimelineEvent(BaseModel):
    """A timed event in the scene timeline."""
    event_id: constr(strip_whitespace=True, min_length=1)
    label: constr(strip_whitespace=True, min_length=1)
    timestamp: float
    event_type: str = "generic"
    target_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class PubWorldTimeline(BaseModel):
    """Timeline of events for scene automation."""
    scene_id: constr(strip_whitespace=True, min_length=6, max_length=48)
    events: List[TimelineEvent] = Field(default_factory=list)
    duration: float = 0.0
    loop: bool = False
    updated_at: float


class PubWorldManager:
    """Manages PubWorld scenes and timelines."""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self._scene_cache: Dict[str, PubWorldScene] = {}
        self._timeline_cache: Dict[str, PubWorldTimeline] = {}
        
        # Ensure directories exist
        self._scene_dir().mkdir(parents=True, exist_ok=True)
        self._timeline_dir().mkdir(parents=True, exist_ok=True)

    def _scene_dir(self) -> Path:
        """Get scenes directory."""
        return self.base_dir / "pubworld" / "scenes"

    def _timeline_dir(self) -> Path:
        """Get timelines directory.""" 
        return self.base_dir / "pubworld" / "timelines"

    def _scene_path(self, scene_id: str) -> Path:
        """Get file path for scene."""
        safe = sanitize_filename(scene_id)
        return self._scene_dir() / f"{safe}.json"

    def _timeline_path(self, scene_id: str) -> Path:
        """Get file path for timeline."""
        safe = sanitize_filename(scene_id)
        return self._timeline_dir() / f"{safe}.json"

    # Scene management
    def create_scene(self, name: str, description: str = "", **kwargs: Any) -> PubWorldScene:
        """Create a new scene."""
        scene_id = f"scn_{uuid.uuid4().hex[:10]}"
        timestamp = time.time()
        
        scene = PubWorldScene(
            scene_id=scene_id,
            name=name,
            description=description,
            grid=[GridCell(**cell) for cell in kwargs.get("grid", [])],
            atmosphere=AtmosphereSettings(**kwargs.get("atmosphere", {})),
            triggers=[TriggerConfig(**entry) for entry in kwargs.get("triggers", [])],
            cameras=[CameraPosition(**cam) for cam in kwargs.get("cameras", [])],
            created_at=timestamp,
            updated_at=timestamp,
        )
        
        return self.save_scene(scene)

    def save_scene(self, scene: PubWorldScene) -> PubWorldScene:
        """Save scene to disk and cache."""
        payload = scene.dict()
        self._scene_path(scene.scene_id).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        
        # Update cache
        self._scene_cache[scene.scene_id] = scene
        
        return scene

    def get_scene(self, scene_id: str) -> PubWorldScene:
        """Get scene by ID."""
        # Check cache first
        if scene_id in self._scene_cache:
            return self._scene_cache[scene_id]
        
        # Load from disk
        path = self._scene_path(scene_id)
        if not path.exists():
            raise KeyError(f"Scene '{scene_id}' not found.")
        
        payload = json.loads(path.read_text(encoding="utf-8"))
        scene = PubWorldScene(**payload)
        
        # Cache it
        self._scene_cache[scene_id] = scene
        
        return scene

    def list_scenes(self) -> List[PubWorldScene]:
        """Get all available scenes."""
        scenes: List[PubWorldScene] = []
        
        for file in self._scene_dir().glob("*.json"):
            try:
                payload = json.loads(file.read_text(encoding="utf-8"))
                scene = PubWorldScene(**payload)
                scenes.append(scene)
                
                # Update cache
                self._scene_cache[scene.scene_id] = scene
                
            except (ValidationError, json.JSONDecodeError):
                continue
        
        scenes.sort(key=lambda s: s.updated_at, reverse=True)
        return scenes

    def update_scene(self, scene_id: str, payload: Dict[str, Any]) -> PubWorldScene:
        """Update existing scene."""
        scene = self.get_scene(scene_id)
        
        data = scene.dict()
        data.update(payload or {})
        data["scene_id"] = scene.scene_id  # enforce immutability
        data["created_at"] = scene.created_at
        data["updated_at"] = time.time()
        
        # Validate components
        data["grid"] = [GridCell(**cell).dict() for cell in data.get("grid", [])]
        data["triggers"] = [TriggerConfig(**entry).dict() for entry in data.get("triggers", [])]
        data["cameras"] = [CameraPosition(**cam).dict() for cam in data.get("cameras", [])]
        data["atmosphere"] = AtmosphereSettings(**data.get("atmosphere", {})).dict()
        
        updated = PubWorldScene(**data)
        return self.save_scene(updated)

    def delete_scene(self, scene_id: str) -> None:
        """Delete scene and its timeline."""
        self._scene_path(scene_id).unlink(missing_ok=True)
        self._timeline_path(scene_id).unlink(missing_ok=True)
        
        # Clear from cache
        self._scene_cache.pop(scene_id, None)
        self._timeline_cache.pop(scene_id, None)

    # Timeline management
    def get_timeline(self, scene_id: str) -> PubWorldTimeline:
        """Get timeline for scene."""
        # Check cache first
        if scene_id in self._timeline_cache:
            return self._timeline_cache[scene_id]
        
        path = self._timeline_path(scene_id)
        if not path.exists():
            # Create empty timeline
            timeline = PubWorldTimeline(
                scene_id=scene_id, 
                events=[], 
                updated_at=time.time()
            )
            return timeline
        
        payload = json.loads(path.read_text(encoding="utf-8"))
        timeline = PubWorldTimeline(**payload)
        
        # Cache it
        self._timeline_cache[scene_id] = timeline
        
        return timeline

    def save_timeline(self, timeline: PubWorldTimeline) -> PubWorldTimeline:
        """Save timeline to disk and cache."""
        payload = timeline.dict()
        self._timeline_path(timeline.scene_id).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        
        # Update cache
        self._timeline_cache[timeline.scene_id] = timeline
        
        return timeline

    def add_timeline_event(self, scene_id: str, event: Dict[str, Any]) -> PubWorldTimeline:
        """Add event to scene timeline."""
        timeline = self.get_timeline(scene_id)
        
        # Create event with auto-generated ID if needed
        event_data = {
            "event_id": event.get("event_id") or f"evt_{uuid.uuid4().hex[:8]}",
            "label": event.get("label", "Untitled Event"),
            "timestamp": float(event.get("timestamp") or time.time()),
            "event_type": event.get("event_type", "generic"),
            "target_id": event.get("target_id"),
            "payload": event.get("payload", {}),
        }
        
        new_event = TimelineEvent(**event_data)
        timeline.events.append(new_event)
        
        # Sort events by timestamp
        timeline.events.sort(key=lambda e: e.timestamp)
        
        # Update timeline metadata
        timeline.updated_at = time.time()
        if timeline.events:
            timeline.duration = max(e.timestamp for e in timeline.events)
        
        return self.save_timeline(timeline)

    # Block building helpers
    def add_block(self, scene_id: str, x: int, y: int, z: int = 0, 
                  material: str = "default", color: str = "#ffffff") -> PubWorldScene:
        """Add a block to the scene grid."""
        scene = self.get_scene(scene_id)
        
        # Check if block already exists at position
        existing_block = next(
            (cell for cell in scene.grid if cell.x == x and cell.y == y and cell.z == z),
            None
        )
        
        if existing_block:
            # Update existing block
            existing_block.material = material
            existing_block.color = color
        else:
            # Add new block
            new_block = GridCell(
                x=x, y=y, z=z,
                material=material,
                color=color
            )
            scene.grid.append(new_block)
        
        scene.updated_at = time.time()
        return self.save_scene(scene)

    def remove_block(self, scene_id: str, x: int, y: int, z: int = 0) -> PubWorldScene:
        """Remove block from scene grid."""
        scene = self.get_scene(scene_id)
        
        # Filter out the block
        scene.grid = [
            cell for cell in scene.grid 
            if not (cell.x == x and cell.y == y and cell.z == z)
        ]
        
        scene.updated_at = time.time()
        return self.save_scene(scene)

    def get_blocks_in_area(self, scene_id: str, x1: int, y1: int, 
                          x2: int, y2: int, z: int = 0) -> List[GridCell]:
        """Get all blocks in rectangular area."""
        scene = self.get_scene(scene_id)
        
        min_x, max_x = min(x1, x2), max(x1, x2)
        min_y, max_y = min(y1, y2), max(y1, y2)
        
        return [
            cell for cell in scene.grid
            if (min_x <= cell.x <= max_x and 
                min_y <= cell.y <= max_y and 
                cell.z == z)
        ]

    # Camera management
    def add_camera_position(self, scene_id: str, camera_id: str, name: str,
                           position: List[float], rotation: List[float],
                           fov: float = 60.0) -> PubWorldScene:
        """Add predefined camera position to scene."""
        scene = self.get_scene(scene_id)
        
        # Remove existing camera with same ID
        scene.cameras = [cam for cam in scene.cameras if cam.camera_id != camera_id]
        
        # Add new camera position
        camera_pos = CameraPosition(
            camera_id=camera_id,
            name=name,
            position=position,
            rotation=rotation,
            fov=fov
        )
        scene.cameras.append(camera_pos)
        
        scene.updated_at = time.time()
        return self.save_scene(scene)

    # Asset management (placeholder for future expansion)
    def list_placeholder_assets(self) -> List[Dict[str, str]]:
        """List assets that need to be created."""
        return [
            {"id": "portal_energy_shader", "label": "Portal Energy Shader", "status": "missing"},
            {"id": "pubworld_skybox", "label": "Pub World Skybox", "status": "missing"},
            {"id": "character_animations", "label": "Character Animation Set", "status": "missing"},
            {"id": "particle_systems", "label": "Particle Effects", "status": "missing"},
        ]


# Factory function for creating default scenes
def create_default_scene(manager: PubWorldManager) -> PubWorldScene:
    """Create a default scene for testing."""
    
    # Create basic room with blocks
    grid = [
        # Floor
        {"x": i, "y": j, "z": 0, "material": "floor", "color": "#8B4513"} 
        for i in range(10) for j in range(10)
    ] + [
        # Walls
        {"x": 0, "y": j, "z": 1, "material": "wall", "color": "#A0A0A0"} for j in range(10)
    ] + [
        {"x": 9, "y": j, "z": 1, "material": "wall", "color": "#A0A0A0"} for j in range(10)  
    ] + [
        {"x": i, "y": 0, "z": 1, "material": "wall", "color": "#A0A0A0"} for i in range(1, 9)
    ] + [
        {"x": i, "y": 9, "z": 1, "material": "wall", "color": "#A0A0A0"} for i in range(1, 9)
    ]
    
    # Define camera positions
    cameras = [
        {
            "camera_id": "default_wide",
            "name": "Wide Shot",
            "position": [5.0, 2.0, 3.0],
            "rotation": [0.0, 0.0, 0.0],
            "fov": 75.0
        },
        {
            "camera_id": "default_medium", 
            "name": "Medium Shot",
            "position": [7.0, 3.0, 2.0],
            "rotation": [0.0, -30.0, 0.0],
            "fov": 50.0
        }
    ]
    
    # Create atmosphere
    atmosphere = {
        "sky": "day",
        "ground": "wood",
        "weather": "clear",
        "fog_density": 0.1,
        "ambient_light": 0.4,
        "sun_intensity": 1.2
    }
    
    return manager.create_scene(
        name="Default Room",
        description="A basic room for testing and demos",
        grid=grid,
        cameras=cameras,
        atmosphere=atmosphere
    )
