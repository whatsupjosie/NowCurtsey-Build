from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(order=True)
class AnimationCommand:
    priority: int
    layer: str = field(compare=False)
    weight: float = field(compare=False, default=1.0)
    pose: Dict[str, Any] = field(compare=False, default_factory=dict)


class AnimationAuthority:
    """Arbitrates animation layers without owning performer position."""

    def __init__(self) -> None:
        self._commands: Dict[str, List[AnimationCommand]] = {}

    def submit(self, performer_id: str, layer: str, pose: Dict[str, Any], priority: int = 50, weight: float = 1.0) -> None:
        command = AnimationCommand(priority=int(priority), layer=str(layer), weight=max(0.0, min(1.0, float(weight))), pose=deepcopy(pose or {}))
        commands = [item for item in self._commands.get(performer_id, []) if item.layer != command.layer]
        commands.append(command)
        self._commands[performer_id] = sorted(commands, reverse=True)

    def clear_layer(self, performer_id: str, layer: str) -> None:
        self._commands[performer_id] = [item for item in self._commands.get(performer_id, []) if item.layer != layer]

    def resolve(self, performer_id: str) -> Dict[str, Any]:
        bones: Dict[str, Any] = {}
        layers = []
        for command in self._commands.get(performer_id, []):
            layers.append({"layer": command.layer, "priority": command.priority, "weight": command.weight})
            for bone, transform in (command.pose.get("bones") or {}).items():
                bones.setdefault(bone, deepcopy(transform))
        return {"animation": "resolved", "layers": layers, "bones": bones}