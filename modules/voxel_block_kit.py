"""PubCast voxel block kit.

Builder helpers for simple 3D stage pieces using PubBlocks.
One full PubBlock is 10 inches. Coordinates are integer subdivision units:
- subdivision 1: full blocks, 10 inches
- subdivision 2: half blocks, 5 inches
- subdivision 4: quarter blocks, 2.5 inches
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Tuple

from .voxel_set_contract import normalize_voxel_set, pub_block_measurement

DEFAULT_MATERIALS = {
    "stage_floor": {"kind": "solid", "label": "Stage floor"},
    "wall_flat": {"kind": "solid", "label": "Flat wall"},
    "backdrop": {"kind": "image_surface", "label": "Image backdrop"},
    "guide": {"kind": "guide_only", "label": "Guide overlay"},
    "trim": {"kind": "solid", "label": "Trim"},
}


def block(x: int, y: int, z: int, material: str, color: str = "#888888", **metadata: Any) -> Dict[str, Any]:
    return {"x": int(x), "y": int(y), "z": int(z), "material": material, "color": color, "metadata": dict(metadata)}


def rectangular_prism(
    origin: Tuple[int, int, int],
    size: Tuple[int, int, int],
    material: str,
    color: str = "#888888",
    shell: bool = False,
    **metadata: Any,
) -> List[Dict[str, Any]]:
    ox, oy, oz = origin
    sx, sy, sz = [max(1, int(v)) for v in size]
    blocks: List[Dict[str, Any]] = []
    for x in range(ox, ox + sx):
        for y in range(oy, oy + sy):
            for z in range(oz, oz + sz):
                if shell and not (x in {ox, ox + sx - 1} or y in {oy, oy + sy - 1} or z in {oz, oz + sz - 1}):
                    continue
                blocks.append(block(x, y, z, material, color, **metadata))
    return blocks


def stage_floor(width: int, depth: int, subdivision: int = 1, color: str = "#444444") -> List[Dict[str, Any]]:
    return rectangular_prism((0, 0, 0), (width * subdivision, 1, depth * subdivision), "stage_floor", color, part="stage_floor", visible_to_program=True, walkable=True)


def flat_wall(x: int, z: int, length: int, height: int, axis: str = "x", subdivision: int = 1, color: str = "#777777") -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    length_units = length * subdivision
    height_units = height * subdivision
    for i in range(length_units):
        for y in range(1, height_units + 1):
            bx, bz = (x * subdivision + i, z * subdivision) if axis == "x" else (x * subdivision, z * subdivision + i)
            blocks.append(block(bx, y, bz, "wall_flat", color, part="wall", blocks_movement=True, visible_to_program=True))
    return blocks


def backdrop_panel(width: int, height: int, z: int, subdivision: int = 1, image_id: str | None = None) -> List[Dict[str, Any]]:
    blocks = flat_wall(0, z, width, height, axis="x", subdivision=subdivision, color="#222244")
    for item in blocks:
        item["material"] = "backdrop"
        item["metadata"].update({"part": "backdrop", "image_id": image_id, "image_fit": "cover"})
    return blocks


def guide_grid(width: int, depth: int, subdivision: int = 1, every_blocks: int = 1) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    step = max(1, every_blocks * subdivision)
    seen = set()

    def add_guide(x: int, z: int) -> None:
        coord = (int(x), 1, int(z))
        if coord in seen:
            return
        seen.add(coord)
        blocks.append(block(coord[0], coord[1], coord[2], "guide", "#4aa3ff", part="floor_grid", visible_to_program=False, guide_only=True, collision=False))

    for x in range(0, width * subdivision, step):
        for z in range(depth * subdivision):
            add_guide(x, z)
    for z in range(0, depth * subdivision, step):
        for x in range(width * subdivision):
            add_guide(x, z)
    return blocks


def doorway_wall(width: int, height: int, door_x: int, door_width: int = 1, door_height: int = 8, subdivision: int = 1) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    width_units = width * subdivision
    height_units = height * subdivision
    door_start = door_x * subdivision
    door_end = door_start + door_width * subdivision
    door_top = door_height * subdivision
    for x in range(width_units):
        for y in range(1, height_units + 1):
            inside_door = door_start <= x < door_end and y <= door_top
            if inside_door:
                continue
            blocks.append(block(x, y, 0, "wall_flat", "#777777", part="doorway_wall", blocks_movement=True, visible_to_program=True))
    return blocks


def make_voxel_set(
    asset_id: str,
    name: str,
    blocks: Iterable[Mapping[str, Any]],
    subdivision: int = 1,
    materials: Mapping[str, Any] | None = None,
    approved_by_user: bool = False,
    sandbox_only: bool = True,
) -> Dict[str, Any]:
    blocks_list = [dict(item) for item in blocks]
    payload = {
        "asset_id": asset_id,
        "name": name,
        "version": 1,
        "units": "voxel",
        "measurement": pub_block_measurement(subdivision),
        "origin": {"x": 0, "y": 0, "z": 0},
        "blocks": blocks_list,
        "materials": dict(DEFAULT_MATERIALS | dict(materials or {})),
        "created_by": "builder",
        "source_prompt": "PubBlock voxel block kit",
        "safety": {
            "ai_authority": "off",
            "approved_by_user": bool(approved_by_user),
            "sandbox_only": bool(sandbox_only),
        },
    }
    return normalize_voxel_set(payload)


__all__ = [
    "DEFAULT_MATERIALS", "backdrop_panel", "block", "doorway_wall", "flat_wall", "guide_grid",
    "make_voxel_set", "rectangular_prism", "stage_floor",
]

