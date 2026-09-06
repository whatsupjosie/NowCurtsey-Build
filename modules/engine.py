"""
Pubcast Core Engine
Event bus, DAG node graph, and validated scene registry.
"""

import json
import threading
from enum import Enum
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field, asdict


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class EventType(Enum):
    LAYER_ADDED    = "LAYER_ADDED"
    LAYER_REMOVED  = "LAYER_REMOVED"
    LAYER_UPDATED  = "LAYER_UPDATED"
    ANCHOR_UPDATED = "ANCHOR_UPDATED"
    RENDER_REQUEST = "RENDER_REQUEST"
    EXPORT_REQUEST = "EXPORT_REQUEST"
    REGISTRY_UPDATED = "REGISTRY_UPDATED"


class EventBus:
    def __init__(self):
        self._listeners: Dict[EventType, list] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_type: EventType, callback):
        with self._lock:
            self._listeners.setdefault(event_type, []).append(callback)

    def publish(self, event_type: EventType, data: Any = None):
        for cb in self._listeners.get(event_type, []):
            try:
                cb(data)
            except Exception as e:
                print(f"[EventBus] Error in {event_type}: {e}")


# ---------------------------------------------------------------------------
# Registry (Pydantic-style validated with dataclasses)
# ---------------------------------------------------------------------------

DEPTH_ZONES = {"bg": 0.5, "mid": 1.0, "fg": 1.5}

@dataclass
class Anchor:
    id: str
    height_units: float
    is_active: bool
    depth_zone: str   # "bg" | "mid" | "fg"

    def __post_init__(self):
        if self.height_units <= 0:
            raise ValueError(f"Anchor '{self.id}': height_units must be > 0")
        if self.depth_zone not in DEPTH_ZONES:
            raise ValueError(f"Anchor '{self.id}': depth_zone must be one of {list(DEPTH_ZONES)}")

    @property
    def perspective_scale(self) -> float:
        return self.height_units * DEPTH_ZONES[self.depth_zone]


@dataclass
class LayerData:
    id: str
    name: str
    depth: float          # 0.0 = static, 1.0 = full parallax speed
    depth_zone: str       # "bg" | "mid" | "fg"
    color: str = "#4a90d9"
    visible: bool = True
    scroll_speed: float = 1.0
    image_path: Optional[str] = None
    y_offset: int = 0
    height_pct: float = 0.3   # fraction of canvas height

    def __post_init__(self):
        if self.depth_zone not in DEPTH_ZONES:
            raise ValueError(f"Layer '{self.id}': depth_zone must be one of {list(DEPTH_ZONES)}")


@dataclass
class SceneRegistry:
    anchors: List[Anchor] = field(default_factory=list)
    layers: List[LayerData] = field(default_factory=list)
    scene_name: str = "Untitled Scene"

    def active_anchor(self) -> Optional[Anchor]:
        for a in self.anchors:
            if a.is_active:
                return a
        return None

    def to_dict(self) -> dict:
        return {
            "scene_name": self.scene_name,
            "anchors": [asdict(a) for a in self.anchors],
            "layers": [asdict(l) for l in self.layers],
        }

    @staticmethod
    def from_dict(d: dict) -> "SceneRegistry":
        reg = SceneRegistry(scene_name=d.get("scene_name", "Untitled"))
        for a in d.get("anchors", []):
            reg.anchors.append(Anchor(**a))
        for l in d.get("layers", []):
            reg.layers.append(LayerData(**l))
        return reg

    def save(self, path: str):
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @staticmethod
    def load(path: str) -> "SceneRegistry":
        with open(path) as f:
            return SceneRegistry.from_dict(json.load(f))


# ---------------------------------------------------------------------------
# DAG Nodes
# ---------------------------------------------------------------------------

class Node:
    def __init__(self, name: str):
        self.name = name
        self.is_dirty = True
        self._output: Any = None
        self.inputs: List["Node"] = []

    def mark_dirty(self):
        self.is_dirty = True

    def compute(self) -> Any:
        if self.is_dirty:
            input_data = [n.compute() for n in self.inputs]
            self._output = self._process(input_data)
            self.is_dirty = False
        return self._output

    def _process(self, inputs: list) -> Any:
        return None


class GizmoNode(Node):
    """Reads the active Anchor and outputs a PerspectiveScaleFactor."""
    def __init__(self, registry: SceneRegistry):
        super().__init__("GizmoNode")
        self.registry = registry

    def _process(self, inputs: list) -> dict:
        anchor = self.registry.active_anchor()
        if anchor is None:
            return {"scale": 1.0, "anchor_id": None}
        return {
            "scale": anchor.perspective_scale,
            "anchor_id": anchor.id,
            "depth_zone": anchor.depth_zone,
        }


class LayerNode(Node):
    """Represents a single parallax layer. Consumes GizmoNode output."""
    def __init__(self, layer_data: LayerData):
        super().__init__(layer_data.name)
        self.layer_data = layer_data

    def _process(self, inputs: list) -> dict:
        gizmo = inputs[0] if inputs else {"scale": 1.0}
        scale = gizmo.get("scale", 1.0)
        depth_mult = DEPTH_ZONES.get(self.layer_data.depth_zone, 1.0)
        return {
            "id": self.layer_data.id,
            "name": self.layer_data.name,
            "pixel_scale": scale * depth_mult,
            "scroll_offset": self.layer_data.depth * self.layer_data.scroll_speed,
            "color": self.layer_data.color,
            "visible": self.layer_data.visible,
            "depth_zone": self.layer_data.depth_zone,
            "y_offset": self.layer_data.y_offset,
            "height_pct": self.layer_data.height_pct,
            "image_path": self.layer_data.image_path,
        }


# ---------------------------------------------------------------------------
# Studio Controller (Orchestrator)
# ---------------------------------------------------------------------------

class StudioController:
    def __init__(self):
        self.bus = EventBus()
        self.registry = SceneRegistry()
        self._lock = threading.Lock()

        # Build initial DAG
        self.gizmo = GizmoNode(self.registry)
        self.layer_nodes: Dict[str, LayerNode] = {}

        # Wire events
        self.bus.subscribe(EventType.LAYER_ADDED,    self._on_layer_added)
        self.bus.subscribe(EventType.LAYER_REMOVED,  self._on_layer_removed)
        self.bus.subscribe(EventType.LAYER_UPDATED,  self._on_layer_updated)
        self.bus.subscribe(EventType.ANCHOR_UPDATED, self._on_anchor_updated)

    # --- Public API called by UI ---

    def add_layer(self, layer_data: LayerData):
        with self._lock:
            self.registry.layers.append(layer_data)
            node = LayerNode(layer_data)
            node.inputs = [self.gizmo]
            self.layer_nodes[layer_data.id] = node
        self.bus.publish(EventType.LAYER_ADDED, layer_data)

    def remove_layer(self, layer_id: str):
        with self._lock:
            self.registry.layers = [l for l in self.registry.layers if l.id != layer_id]
            self.layer_nodes.pop(layer_id, None)
        self.bus.publish(EventType.LAYER_REMOVED, {"id": layer_id})

    def update_layer(self, layer_id: str, **kwargs):
        with self._lock:
            for l in self.registry.layers:
                if l.id == layer_id:
                    for k, v in kwargs.items():
                        if hasattr(l, k):
                            setattr(l, k, v)
                    if layer_id in self.layer_nodes:
                        self.layer_nodes[layer_id].layer_data = l
                        self.layer_nodes[layer_id].mark_dirty()
                    break
        self.bus.publish(EventType.LAYER_UPDATED, {"id": layer_id, **kwargs})

    def set_anchor(self, anchor: Anchor):
        with self._lock:
            # Deactivate all, activate the new one
            for a in self.registry.anchors:
                a.is_active = False
            existing = next((a for a in self.registry.anchors if a.id == anchor.id), None)
            if existing:
                existing.height_units = anchor.height_units
                existing.depth_zone = anchor.depth_zone
                existing.is_active = True
            else:
                anchor.is_active = True
                self.registry.anchors.append(anchor)
            self.gizmo.mark_dirty()
            for node in self.layer_nodes.values():
                node.mark_dirty()
        self.bus.publish(EventType.ANCHOR_UPDATED, anchor)

    def render_frame(self, camera_x: float = 0.0) -> List[dict]:
        """Compute all visible layers for a given camera X offset."""
        with self._lock:
            results = []
            for node in self.layer_nodes.values():
                data = node.compute()
                if data and data.get("visible", True):
                    # Apply camera parallax offset
                    data["render_x"] = -camera_x * data["scroll_offset"]
                    results.append(data)
            # Sort bg → mid → fg
            zone_order = {"bg": 0, "mid": 1, "fg": 2}
            results.sort(key=lambda d: zone_order.get(d.get("depth_zone", "mid"), 1))
            return results

    def save_scene(self, path: str):
        self.registry.save(path)

    def load_scene(self, path: str):
        with self._lock:
            self.registry = SceneRegistry.load(path)
            self.gizmo = GizmoNode(self.registry)
            self.layer_nodes = {}
            for layer_data in self.registry.layers:
                node = LayerNode(layer_data)
                node.inputs = [self.gizmo]
                self.layer_nodes[layer_data.id] = node
        self.bus.publish(EventType.REGISTRY_UPDATED, None)

    # --- Internal handlers ---
    def _on_layer_added(self, data): pass
    def _on_layer_removed(self, data): pass
    def _on_layer_updated(self, data): pass
    def _on_anchor_updated(self, data): pass
