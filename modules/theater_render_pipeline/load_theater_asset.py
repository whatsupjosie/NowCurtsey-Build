"""
load_theater_asset.py — Loads the "small theater platform" builder JSON
into the same VoxelModel format the real greedy mesher / rasterizer expect.

This is the first REAL content (not a synthetic test cube) run through the
actual pipeline built this session: JSON asset -> dense voxel grid ->
greedy mesh -> camera render -> real image.
"""

import json
import numpy as np
from .voxel_renderer_lighting_fixed import VoxelModel


def _hex_to_rgb(hexcolor: str) -> tuple:
    h = hexcolor.lstrip("#")
    if len(h) != 6:
        return (128, 128, 128)  # fallback gray, never crash on bad color
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (128, 128, 128)


def load_builder_json(path: str) -> VoxelModel:
    with open(path) as f:
        data = json.load(f)

    dims = data["dimensions"]
    W, H, D = dims["x"], dims["y"], dims["z"]

    # Build palette only from materials that actually appear in at least one
    # block. Declared-but-unused materials in the materials dict are skipped
    # rather than crashing with StopIteration when no block references them.
    used_materials = dict.fromkeys(
        b["material"] for b in data["blocks"]
        if "material" in b
    )  # insertion-ordered, deduped

    palette = []
    for name in used_materials:
        # Get color from the first block that uses this material
        block = next(
            (b for b in data["blocks"] if b.get("material") == name), None
        )
        hexcolor = (block or {}).get("color", "#808080")
        palette.append(_hex_to_rgb(hexcolor))

    material_names = list(used_materials.keys())

    voxels = np.zeros((W, H, D), dtype=np.uint8)
    for b in data["blocks"]:
        mat = b.get("material")
        if mat not in used_materials:
            continue  # skip blocks with no material field
        x, y, z = b["x"], b["y"], b["z"]
        if 0 <= x < W and 0 <= y < H and 0 <= z < D:
            idx = material_names.index(mat) + 1  # +1: 0 is reserved for empty
            voxels[x, y, z] = idx

    return VoxelModel(
        model_id=data["asset_id"],
        width=W, height=H, depth=D,
        voxels=voxels,
        palette=palette,
    )
