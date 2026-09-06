"""Dry-run PubBlock and visual-patch voxel previews.

This module is intentionally side-effect free. It lets PubCast ask what a
simple PubBlock object or adaptive visual patch would generate without saving
files, creating rooms, or mutating PubWorld state.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Tuple

from .visual_patch_voxel_adapter import (
    adaptive_extension_to_pubworld_prop,
    pubworld_prop_to_voxel_set,
    visual_patch_to_pubworld_prop,
)
from .voxel_block_kit import (
    DEFAULT_MATERIALS,
    backdrop_panel,
    doorway_wall,
    flat_wall,
    guide_grid,
    make_voxel_set,
    rectangular_prism,
    stage_floor,
)
from .voxel_set_contract import normalize_voxel_set, pub_block_measurement

MAX_PREVIEW_BLOCKS = 20000
SUPPORTED_PREVIEWS = {
    "stage_floor",
    "flat_wall",
    "backdrop_panel",
    "guide_grid",
    "doorway_wall",
    "rectangular_prism",
    "visual_patch",
    "adaptive_extension",
}


class VoxelBlockPreviewError(ValueError):
    """Raised when a preview request cannot be safely normalized."""


def preview_voxel_asset(preview_kind: str, params: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Return a canonical, unsaved voxel preview payload."""

    kind = _clean_kind(preview_kind)
    body = dict(params or {})
    if kind in {"visual_patch", "adaptive_extension"}:
        voxel_set = _preview_visual_patch(kind, body)
    else:
        voxel_set = _preview_pubblock(kind, body)

    normalized = normalize_voxel_set(voxel_set)
    blocks = normalized["blocks"]
    if len(blocks) > MAX_PREVIEW_BLOCKS:
        raise VoxelBlockPreviewError(f"preview exceeds {MAX_PREVIEW_BLOCKS} blocks")
    return {
        "ok": True,
        "available": True,
        "preview_kind": kind,
        "read_only": True,
        "saved": False,
        "creates_map_rooms": False,
        "creates_consoles": False,
        "block_count": len(blocks),
        "dimensions": normalized["dimensions"],
        "measurement": normalized["measurement"],
        "materials": normalized["materials"],
        "voxel_set": normalized,
        "stage_voxels": _stage_voxels(blocks),
    }


def preview_capabilities() -> Dict[str, Any]:
    """Describe dry-run preview support without creating anything."""

    return {
        "available": True,
        "read_only": True,
        "max_preview_blocks": MAX_PREVIEW_BLOCKS,
        "supported_previews": sorted(SUPPORTED_PREVIEWS),
        "pubblock_measurement": pub_block_measurement(),
        "default_materials": sorted(DEFAULT_MATERIALS.keys()),
        "creates_map_rooms": False,
        "creates_consoles": False,
        "saves_assets": False,
    }


def _preview_pubblock(kind: str, body: Mapping[str, Any]) -> Dict[str, Any]:
    subdivision = _subdivision(body.get("subdivision", 1))
    color = _text(body.get("color"), "#888888")
    if kind == "stage_floor":
        blocks = stage_floor(_positive_int(body.get("width"), 4), _positive_int(body.get("depth"), 4), subdivision=subdivision, color=color)
    elif kind == "flat_wall":
        blocks = flat_wall(
            _non_negative_int(body.get("x"), 0),
            _non_negative_int(body.get("z"), 0),
            _positive_int(body.get("length"), 4),
            _positive_int(body.get("height"), 3),
            axis=_axis(body.get("axis")),
            subdivision=subdivision,
            color=color,
        )
    elif kind == "backdrop_panel":
        blocks = backdrop_panel(
            _positive_int(body.get("width"), 4),
            _positive_int(body.get("height"), 3),
            _non_negative_int(body.get("z"), 0),
            subdivision=subdivision,
            image_id=_optional_text(body.get("image_id")),
        )
    elif kind == "guide_grid":
        blocks = guide_grid(
            _positive_int(body.get("width"), 4),
            _positive_int(body.get("depth"), 4),
            subdivision=subdivision,
            every_blocks=_positive_int(body.get("every_blocks"), 1),
        )
    elif kind == "doorway_wall":
        blocks = doorway_wall(
            _positive_int(body.get("width"), 8),
            _positive_int(body.get("height"), 8),
            _non_negative_int(body.get("door_x"), 3),
            door_width=_positive_int(body.get("door_width"), 2),
            door_height=_positive_int(body.get("door_height"), 7),
            subdivision=subdivision,
        )
    elif kind == "rectangular_prism":
        blocks = rectangular_prism(
            _triple(body.get("origin"), (0, 0, 0), allow_zero=True),
            _triple(body.get("size"), (1, 1, 1), allow_zero=False),
            _text(body.get("material"), "stage_floor"),
            color,
            shell=bool(body.get("shell", False)),
            part=_text(body.get("part"), "preview_prism"),
            visible_to_program=True,
        )
    else:
        raise VoxelBlockPreviewError(f"unsupported preview kind: {kind}")

    _guard_block_count(blocks)
    return make_voxel_set(
        asset_id=_safe_id(body.get("asset_id"), f"preview_{kind}"),
        name=_text(body.get("name"), f"Preview {kind.replace('_', ' ').title()}"),
        blocks=blocks,
        subdivision=subdivision,
        materials=_extra_materials(body),
        approved_by_user=False,
        sandbox_only=True,
    )


def _preview_visual_patch(kind: str, body: Mapping[str, Any]) -> Dict[str, Any]:
    proposal = _proposal(body)
    max_blocks = min(MAX_PREVIEW_BLOCKS, _positive_int(body.get("max_blocks"), MAX_PREVIEW_BLOCKS))
    if kind == "adaptive_extension":
        prop_payload = adaptive_extension_to_pubworld_prop(proposal, scene_id=_text(body.get("scene_id"), "scene_default"), label=_optional_text(body.get("label")), max_blocks=max_blocks)
        asset_id = _safe_id(body.get("asset_id"), _text(proposal.get("extension_id"), "adaptive_extension_preview"))
    else:
        prop_payload = visual_patch_to_pubworld_prop(proposal, scene_id=_text(body.get("scene_id"), "scene_default"), label=_optional_text(body.get("label")), max_blocks=max_blocks)
        asset_id = _safe_id(body.get("asset_id"), _text(proposal.get("patch_id"), "visual_patch_preview"))
    _guard_block_count(prop_payload.get("blocks", []))
    return pubworld_prop_to_voxel_set(prop_payload, asset_id=asset_id, name=prop_payload["label"], approved_by_user=False)


def _stage_voxels(blocks: Iterable[Mapping[str, Any]]) -> List[List[int]]:
    return [[int(block["x"]), int(block["y"]), int(block["z"])] for block in blocks]


def _clean_kind(value: Any) -> str:
    kind = str(value or "stage_floor").strip().lower().replace("-", "_")
    if kind not in SUPPORTED_PREVIEWS:
        raise VoxelBlockPreviewError(f"preview_kind must be one of {sorted(SUPPORTED_PREVIEWS)}")
    return kind


def _proposal(body: Mapping[str, Any]) -> Dict[str, Any]:
    for key in ("proposal", "patch", "visual_patch", "adaptive_extension", "extension"):
        value = body.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return dict(body)


def _extra_materials(body: Mapping[str, Any]) -> Dict[str, Any]:
    value = body.get("materials")
    return dict(value) if isinstance(value, Mapping) else {}


def _subdivision(value: Any) -> int:
    subdivision = _positive_int(value, 1)
    if subdivision not in {1, 2, 4}:
        raise VoxelBlockPreviewError("subdivision must be 1, 2, or 4")
    return subdivision


def _axis(value: Any) -> str:
    axis = str(value or "x").strip().lower()
    if axis not in {"x", "z"}:
        raise VoxelBlockPreviewError("axis must be x or z")
    return axis


def _triple(value: Any, default: Tuple[int, int, int], allow_zero: bool) -> Tuple[int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return default
    items = []
    for index, item in enumerate(value[:3]):
        items.append(_non_negative_int(item, default[index]) if allow_zero else _positive_int(item, max(1, default[index])))
    return (items[0], items[1], items[2])


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = int(default)
    return max(1, number)


def _non_negative_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = int(default)
    return max(0, number)


def _guard_block_count(blocks: Iterable[Mapping[str, Any]]) -> None:
    count = len(blocks) if isinstance(blocks, list) else sum(1 for _ in blocks)
    if count > MAX_PREVIEW_BLOCKS:
        raise VoxelBlockPreviewError(f"preview exceeds {MAX_PREVIEW_BLOCKS} blocks")


def _text(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _safe_id(value: Any, default: str) -> str:
    raw = _text(value, default)
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw)
    return safe[:96] or default


__all__ = ["MAX_PREVIEW_BLOCKS", "SUPPORTED_PREVIEWS", "VoxelBlockPreviewError", "preview_capabilities", "preview_voxel_asset"]