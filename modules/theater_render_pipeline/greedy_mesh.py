"""
greedy_mesh.py — Real greedy surface mesher for VoxelModel

The existing MeshGenerator in voxel_renderer.py emits one unmerged
triangle-pair per exposed voxel face (its own comment admits this:
"simplified: just use current vertex + offsets"). For a flat wall made
of 100 voxels, that's 200 triangles for what should be a single
rectangle. This module actually merges adjacent same-color, same-facing
voxel faces into the largest possible rectangles first (standard greedy
meshing, the same technique used by Minecraft-style voxel engines),
so a flat surface becomes 1 quad (2 triangles) instead of hundreds.

This is what makes "one cup = one efficient mesh object" literally true.
"""

import numpy as np
from .voxel_renderer_lighting_fixed import VoxelModel, Mesh


def hollow_out(model: VoxelModel) -> VoxelModel:
    """
    Strip fully-enclosed interior voxels from a solid VoxelModel.

    A voxel is "interior" if all 6 of its neighbors are also solid — meaning
    it can never contribute a visible face (every face would be between two
    solid voxels, which the mesher already skips). Removing it from storage
    means the mesher's mask-building loop doesn't have to scan it either.

    This is the data-level counterpart to face culling: face culling skips
    emitting a *polygon* for an interior boundary; this skips even *storing*
    a voxel that can never produce one.
    """
    W, H, D = model.width, model.height, model.depth
    v = model.voxels
    solid = v != 0

    # A voxel is interior if it's solid AND every neighbor is also solid.
    # Out-of-bounds is treated as EMPTY (matching generate_greedy_mesh's own
    # get_voxel() convention) — a voxel at the edge of the array still has
    # a real, visible outward-facing surface there, so it must NOT be
    # treated as interior just because there's no neighbor data beyond the
    # array edge. (First version of this function padded with solid=True,
    # which silently hollowed out an object's entire outer shell whenever
    # it filled its own bounding box — caught by testing on a solid cube,
    # not assumed correct from reading the code alone.)
    padded = np.zeros((W + 2, H + 2, D + 2), dtype=bool)
    padded[1:-1, 1:-1, 1:-1] = solid

    interior = (
        solid &
        padded[0:-2, 1:-1, 1:-1] & padded[2:, 1:-1, 1:-1] &   # x neighbors
        padded[1:-1, 0:-2, 1:-1] & padded[1:-1, 2:, 1:-1] &   # y neighbors
        padded[1:-1, 1:-1, 0:-2] & padded[1:-1, 1:-1, 2:]     # z neighbors
    )

    new_voxels = v.copy()
    new_voxels[interior] = 0

    return VoxelModel(model_id=model.model_id + "_hollowed", width=W, height=H, depth=D,
                       voxels=new_voxels, palette=model.palette)



def generate_greedy_mesh(model: VoxelModel) -> Mesh:
    """
    Convert a VoxelModel into a Mesh using greedy face merging.
    Same output contract as MeshGenerator.generate_mesh() (a Mesh with
    vertices/normals/indices/colors), but with a fraction of the triangles.
    """
    W, H, D = model.width, model.height, model.depth
    grid = model.voxels
    palette = model.palette or [(200, 200, 200)]

    def color_of(v):
        idx = int(v) - 1
        if 0 <= idx < len(palette):
            return np.array(palette[idx], dtype=np.uint8)
        return np.array([200, 200, 200], dtype=np.uint8)

    verts, norms, cols, tris = [], [], [], []

    dims = [W, H, D]

    for d in range(3):  # sweep axis: 0=x, 1=y, 2=z
        u = (d + 1) % 3
        v = (d + 2) % 3

        du = [0, 0, 0]; du[u] = 1
        dv = [0, 0, 0]; dv[v] = 1

        def get_voxel(pos):
            x, y, z = pos
            if 0 <= x < W and 0 <= y < H and 0 <= z < D:
                return int(grid[x, y, z])
            return 0

        for layer in range(dims[d] + 1):
            # Build a 2D mask across (u,v) at this layer boundary.
            # mask value: 0 = no face; else (sign, color_index) packed
            mu, mv = dims[u], dims[v]
            mask_color = np.zeros((mu, mv, 3), dtype=np.int32) - 1  # -1 = empty
            mask_sign = np.zeros((mu, mv), dtype=np.int8)

            for i in range(mu):
                for j in range(mv):
                    pos_a = [0, 0, 0]
                    pos_b = [0, 0, 0]
                    pos_a[d] = layer - 1
                    pos_b[d] = layer
                    pos_a[u] = pos_b[u] = i
                    pos_a[v] = pos_b[v] = j

                    va = get_voxel(pos_a)
                    vb = get_voxel(pos_b)

                    if va != 0 and vb == 0:
                        mask_color[i, j] = color_of(va)
                        mask_sign[i, j] = 1     # face points in -d (outward from a)
                    elif vb != 0 and va == 0:
                        mask_color[i, j] = color_of(vb)
                        mask_sign[i, j] = -1    # face points in +d (outward from b)

            # Greedy rectangle merge over the mask
            done = np.zeros((mu, mv), dtype=bool)
            for i in range(mu):
                for j in range(mv):
                    if done[i, j] or mask_sign[i, j] == 0:
                        continue
                    sign = mask_sign[i, j]
                    color = mask_color[i, j]

                    # Expand width along u
                    w = 1
                    while (i + w < mu and not done[i + w, j] and
                           mask_sign[i + w, j] == sign and
                           np.array_equal(mask_color[i + w, j], color)):
                        w += 1

                    # Expand height along v, requiring the whole width-strip to match
                    h = 1
                    grown = True
                    while i + 1 <= mu and j + h < mv and grown:
                        for k in range(w):
                            if (done[i + k, j + h] or mask_sign[i + k, j + h] != sign or
                                    not np.array_equal(mask_color[i + k, j + h], color)):
                                grown = False
                                break
                        if grown:
                            h += 1

                    done[i:i + w, j:j + h] = True

                    # Emit one quad for this w x h merged rectangle
                    base = [0, 0, 0]
                    base[d] = layer
                    base[u] = i
                    base[v] = j

                    p0 = list(base)
                    p1 = list(base); p1[u] += w
                    p2 = list(base); p2[u] += w; p2[v] += h
                    p3 = list(base); p3[v] += h

                    quad = [p0, p1, p2, p3] if sign > 0 else [p0, p3, p2, p1]

                    start_idx = len(verts)
                    normal = [0, 0, 0]; normal[d] = 1 if sign > 0 else -1
                    for p in quad:
                        verts.append(p)
                        norms.append(normal)
                        cols.append(color)
                    tris.append([start_idx, start_idx + 1, start_idx + 2])
                    tris.append([start_idx, start_idx + 2, start_idx + 3])

    return Mesh(
        vertices=np.array(verts, dtype=np.float32) if verts else np.zeros((0, 3), dtype=np.float32),
        normals=np.array(norms, dtype=np.float32) if norms else np.zeros((0, 3), dtype=np.float32),
        indices=np.array(tris, dtype=np.uint32) if tris else np.zeros((0, 3), dtype=np.uint32),
        colors=np.array(cols, dtype=np.uint8) if cols else None,
    )
