"""Visual Patch Kit to PubWorld voxel payload adapter.

This module is deliberately boring and side-effect free. It translates approved
visual patch/adaptive prop proposals into payloads that existing PubWorld and
voxel-set code can store or render.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


DEFAULT_SCENE_ID = "scene_default"
DEFAULT_COLOR = "#888888"
MAX_ADAPTER_BLOCKS = 50000


def visual_patch_to_pubworld_prop(
    patch: Mapping[str, Any],
    scene_id: str = DEFAULT_SCENE_ID,
    label: Optional[str] = None,
    max_blocks: int = MAX_ADAPTER_BLOCKS,
) -> Dict[str, Any]:
    """Translate a visual patch request into a PubWorld prop payload."""

    patch_id = _text(patch.get("patch_id"), f"visual_patch_{int(time.time() * 1000)}")
    dimensions = _dimensions(patch.get("dimensions"), [3, 3, 1])
    color = _color_for_hint(_text(patch.get("color_hint"), "match_outfit"))
    blocks = _blocks_from_dimensions(
        dimensions=dimensions,
        color=color,
        kind=_text(patch.get("kind"), "cover"),
        max_blocks=max_blocks,
        hollow=True,
    )
    return {
        "scene_id": scene_id,
        "label": label or f"Visual Patch {patch_id}",
        "description": _text(patch.get("reason"), "temporary visual patch"),
        "blocks": blocks,
        "variants": [
            {
                "variant_id": "live_overlay",
                "patch_id": patch_id,
                "performer_id": patch.get("performer_id"),
                "anchor_joint": patch.get("anchor_joint"),
                "offset": _float_vector(patch.get("offset"), [0.0, 0.0, 0.0]),
                "voxel_size": _finite_float(patch.get("voxel_size"), 0.035),
                "opacity": _finite_float(patch.get("opacity"), 0.92),
                "blend_mode": _text(patch.get("blend_mode"), "soft_overlay"),
                "bake_after_seconds": _finite_float(patch.get("bake_after_seconds"), 0.75),
                "bake_to_mesh": bool(patch.get("bake_to_mesh", True)),
                "temporary": True,
            }
        ],
    }


def adaptive_extension_to_pubworld_prop(
    extension: Mapping[str, Any],
    scene_id: str = DEFAULT_SCENE_ID,
    label: Optional[str] = None,
    max_blocks: int = MAX_ADAPTER_BLOCKS,
) -> Dict[str, Any]:
    """Translate an adaptive object extension into a PubWorld prop payload."""

    extension_id = _text(extension.get("extension_id"), f"adaptive_ext_{int(time.time() * 1000)}")
    voxel_patch = _mapping(extension.get("voxel_patch"))
    dimensions = _dimensions(voxel_patch.get("dimensions"), [1, 1, 1])
    clearance_zones = _list_of_mappings(extension.get("clearance_zones"))
    subtractive_cutouts = _list_of_mappings(voxel_patch.get("subtractive_cutouts")) or clearance_zones
    color = _color_for_hint(_text(voxel_patch.get("color_hint"), "match_prop_material"))
    blocks = _blocks_from_dimensions(
        dimensions=dimensions,
        color=color,
        kind=_text(extension.get("kind"), _text(voxel_patch.get("kind"), "extend")),
        subtractive_cutouts=subtractive_cutouts,
        max_blocks=max_blocks,
        hollow=True,
    )
    return {
        "scene_id": scene_id,
        "label": label or f"Adaptive Prop {extension_id}",
        "description": _text(extension.get("reason"), "temporary adaptive prop extension"),
        "blocks": blocks,
        "variants": [
            {
                "variant_id": "adaptive_overlay",
                "extension_id": extension_id,
                "performer_id": extension.get("performer_id"),
                "object_id": extension.get("object_id"),
                "object_type": extension.get("object_type"),
                "interaction": extension.get("interaction"),
                "anchor": voxel_patch.get("anchor"),
                "offset": _float_vector(voxel_patch.get("offset"), [0.0, 0.0, 0.0]),
                "voxel_size": _finite_float(voxel_patch.get("voxel_size"), 0.035),
                "repair_effort": _mapping(extension.get("repair_effort")),
                "quality_assurance": _mapping(extension.get("quality_assurance")),
                "approval": _mapping(extension.get("approval")),
                "presence": _mapping(extension.get("presence")),
                "persistence": _mapping(extension.get("persistence")),
                "clearance_zones": clearance_zones,
                "subtractive_cutouts": subtractive_cutouts,
                "temporary": bool(extension.get("retire_when_interaction_ends", True)),
            }
        ],
    }


def pubworld_prop_to_voxel_set(
    prop_payload: Mapping[str, Any],
    asset_id: str,
    name: Optional[str] = None,
    approved_by_user: bool = False,
) -> Dict[str, Any]:
    """Build a canonical voxel-set payload from a PubWorld prop payload."""

    blocks = [
        {
            "x": int(block["x"]),
            "y": int(block["y"]),
            "z": int(block["z"]),
            "material": "adaptive_patch",
            "color": str(block.get("color") or DEFAULT_COLOR),
            "metadata": {"kind": block.get("kind", "cube")},
        }
        for block in prop_payload.get("blocks", [])
        if isinstance(block, Mapping)
    ]
    return {
        "asset_id": _safe_id(asset_id),
        "name": name or _text(prop_payload.get("label"), "Adaptive Visual Patch"),
        "version": 1,
        "units": "voxel",
        "dimensions": _dimensions_xyz(blocks),
        "origin": {"x": 0, "y": 0, "z": 0},
        "blocks": blocks,
        "materials": {
            "adaptive_patch": {
                "kind": "temporary_overlay",
                "label": "Adaptive Visual Patch",
            }
        },
        "created_by": "builder",
        "source_prompt": _text(prop_payload.get("description"), "approved visual patch"),
        "safety": {
            "ai_authority": "advisory",
            "approved_by_user": bool(approved_by_user),
            "sandbox_only": True,
        },
    }


def _blocks_from_dimensions(
    dimensions: List[int],
    color: str,
    kind: str,
    max_blocks: int,
    hollow: bool,
    subtractive_cutouts: Optional[List[Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    x_len, y_len, z_len = dimensions[:3]
    blocks: List[Dict[str, Any]] = []
    for x, y, z in _iter_grid(x_len, y_len, z_len):
        if hollow and not _is_shell(x, y, z, x_len, y_len, z_len):
            continue
        if _inside_any_cutout(x, y, z, x_len, y_len, z_len, subtractive_cutouts or []):
            continue
        blocks.append({"x": x, "y": y, "z": z, "kind": kind or "cube", "color": color})
        if len(blocks) >= max(1, int(max_blocks)):
            break
    return blocks


def _iter_grid(x_len: int, y_len: int, z_len: int) -> Iterable[Tuple[int, int, int]]:
    for x in range(max(1, x_len)):
        for y in range(max(1, y_len)):
            for z in range(max(1, z_len)):
                yield x, y, z


def _is_shell(x: int, y: int, z: int, x_len: int, y_len: int, z_len: int) -> bool:
    return x in {0, x_len - 1} or y in {0, y_len - 1} or z in {0, z_len - 1}


def _inside_any_cutout(
    x: int,
    y: int,
    z: int,
    x_len: int,
    y_len: int,
    z_len: int,
    cutouts: List[Mapping[str, Any]],
) -> bool:
    for cutout in cutouts:
        if str(cutout.get("operation") or "").lower() != "subtract":
            continue
        kind = str(cutout.get("kind") or cutout.get("shape") or "").lower()
        if "tail" in kind or "slot" in kind:
            slot_width = max(1, int(math.ceil(x_len * 0.28)))
            slot_height = max(1, int(math.ceil(y_len * 0.55)))
            slot_depth = max(1, int(math.ceil(z_len * 0.34)))
            x_mid = x_len // 2
            if abs(x - x_mid) <= max(1, slot_width // 2) and y < slot_height and z < slot_depth:
                return True
    return False


def _dimensions(value: Any, default: List[int]) -> List[int]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return [max(1, int(_finite_float(item, 1))) for item in value[:3]]
    return list(default)


def _dimensions_xyz(blocks: List[Mapping[str, Any]]) -> Dict[str, int]:
    if not blocks:
        return {"x": 0, "y": 0, "z": 0}
    return {
        "x": max(int(block.get("x", 0)) for block in blocks) + 1,
        "y": max(int(block.get("y", 0)) for block in blocks) + 1,
        "z": max(int(block.get("z", 0)) for block in blocks) + 1,
    }


def _color_for_hint(hint: str) -> str:
    text = hint.lower()
    if "outfit" in text or "costume" in text:
        return "#4a5568"
    if "skin" in text or "makeup" in text:
        return "#c58f72"
    if "prop" in text or "material" in text:
        return "#8a7f72"
    return DEFAULT_COLOR


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _float_vector(value: Any, default: List[float]) -> List[float]:
    if not isinstance(value, (list, tuple)):
        return list(default)
    out = [_finite_float(item, 0.0) for item in value[: len(default)]]
    while len(out) < len(default):
        out.append(default[len(out)])
    return out


def _finite_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _text(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _safe_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    return safe[:96] or f"visual_patch_{int(time.time())}"


__all__ = [
    "adaptive_extension_to_pubworld_prop",
    "pubworld_prop_to_voxel_set",
    "visual_patch_to_pubworld_prop",
]
