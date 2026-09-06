"""
Pete Avatar Builder — PubCast AI v5.6
Rear View Foresight LLC 2026  |  Feic Mo Chroí™

Design targets:
  - Reskinnable: body/clothes on separate mesh layers
  - Dual-rig: weights map to 56-bone subset (works on both 56 and 89 bone rigs)
  - Smooth skinning: multi-bone weights, no buckle/stretch
  - Full face rig: 15 lip-sync viseme blend shapes (Preston Blair + extras)
  - Mocap-ready: jaw, brow, cheek, eye blend shapes
  - GLB 2.0 compliant, parallax/holographic material included
"""

import json, struct, math, os
import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# PALETTE
# ─────────────────────────────────────────────────────────────────────────────
SKIN   = [0.785, 0.545, 0.365, 1.0]   # #C68B5E
HAIR   = [0.831, 0.408, 0.478, 1.0]   # #D4687A dusty rose pink
JACKET = [0.102, 0.102, 0.102, 1.0]   # #1A1A1A leather
TANK   = [0.165, 0.165, 0.165, 1.0]   # #2A2A2A
JEANS  = [0.357, 0.478, 0.557, 1.0]   # #5B7A8E
BOOTS  = [0.067, 0.067, 0.067, 1.0]   # #111111
EYE    = [0.243, 0.620, 0.604, 1.0]   # #3E9E9A teal
BELT   = [0.118, 0.098, 0.082, 1.0]
ZIPPER = [0.706, 0.659, 0.498, 1.0]   # antique gold

MATS = {
    # LAYER 0 — body (always present, reskinning base)
    'body_skin':  {'base':SKIN,   'metal':0.0, 'rough':0.75, 'emit':[0,0,0]},
    'body_under': {'base':[0.82,0.60,0.48,1.0],'metal':0.0,'rough':0.80,'emit':[0,0,0]},
    # LAYER 1 — clothing (swappable)
    'jacket':     {'base':JACKET, 'metal':0.0, 'rough':0.32, 'emit':[0,0,0]},
    'tank':       {'base':TANK,   'metal':0.0, 'rough':0.82, 'emit':[0,0,0]},
    'jeans':      {'base':JEANS,  'metal':0.0, 'rough':0.88, 'emit':[0,0,0]},
    'boots':      {'base':BOOTS,  'metal':0.05,'rough':0.58, 'emit':[0,0,0]},
    'belt':       {'base':BELT,   'metal':0.02,'rough':0.55, 'emit':[0,0,0]},
    'zipper':     {'base':ZIPPER, 'metal':0.85,'rough':0.18, 'emit':[0,0,0]},
    # LAYER 2 — face / hair (separate for blend shape performance)
    'hair':       {'base':HAIR,   'metal':0.0, 'rough':0.65, 'emit':[0,0,0]},
    'eye_iris':   {'base':EYE,    'metal':0.0, 'rough':0.08, 'emit':[0.06,0.18,0.18]},
    'eye_white':  {'base':[0.95,0.95,0.95,1.0],'metal':0.0,'rough':0.30,'emit':[0,0,0]},
    'lip':        {'base':[0.698,0.376,0.345,1.0],'metal':0.0,'rough':0.45,'emit':[0,0,0]},
    # Holographic parallax overlay
    'holo':       {'base':[0.24,0.62,0.60,0.55],'metal':0.0,'rough':0.0,
                   'emit':[0.24,0.62,0.60],'alpha':'BLEND'},
}
MNAMES = list(MATS.keys())
MIDX   = {n:i for i,n in enumerate(MNAMES)}

# ─────────────────────────────────────────────────────────────────────────────
# PROPORTIONS  (5'7" = 1.702m canonical)
# ─────────────────────────────────────────────────────────────────────────────
TH = 1.702
HEAD_H   = TH * 0.130
NECK_H   = TH * 0.045
TORSO_H  = TH * 0.290
PELVIS_H = TH * 0.095
THIGH_H  = TH * 0.240
SHIN_H   = TH * 0.220
FOOT_H   = TH * 0.060
UP_ARM   = TH * 0.175
LO_ARM   = TH * 0.145
HAND_L   = TH * 0.100
HW = 0.340; SW = 0.385

foot_y   = 0.0
shin_y   = foot_y   + FOOT_H
thigh_y  = shin_y   + SHIN_H
pelvis_y = thigh_y  + THIGH_H
spine_y  = pelvis_y + PELVIS_H
neck_y   = pelvis_y + PELVIS_H + TORSO_H
head_y   = neck_y   + NECK_H

shldr_y = spine_y + TORSO_H * 0.72
hdx = HW * 0.5; sdx = SW * 0.5
EYE_Z = 0.065; EYE_X = 0.030

# ─────────────────────────────────────────────────────────────────────────────
# 56-BONE RIG  (subset of UE5 89-bone — Pete is weighted to THIS set so she
#               works on both 56-bone and 89-bone skeletons)
# ─────────────────────────────────────────────────────────────────────────────
# Index map: what we call bone 0..55 here maps into the full 89-bone list
# by name. Renderers that load 89 bones will just have extra unused bones.
BONES56 = [
    # idx  name                 parent  local_xyz
    ( 0,  "root",               -1,  [0, 0, 0]),
    ( 1,  "pelvis",              0,  [0, pelvis_y, 0]),
    ( 2,  "spine_01",            1,  [0, PELVIS_H, 0]),
    ( 3,  "spine_02",            2,  [0, TORSO_H*0.22, 0]),
    ( 4,  "spine_03",            3,  [0, TORSO_H*0.22, 0]),
    ( 5,  "neck_01",             4,  [0, TORSO_H*0.30, 0]),
    ( 6,  "head",                5,  [0, NECK_H, 0]),
    ( 7,  "jaw",                 6,  [0, HEAD_H*0.10, EYE_Z*0.8]),
    ( 8,  "eye_l",               6,  [EYE_X, HEAD_H*0.35, EYE_Z]),
    ( 9,  "eye_r",               6,  [-EYE_X, HEAD_H*0.35, EYE_Z]),
    # Left arm
    (10,  "clavicle_l",          4,  [sdx*0.35, TORSO_H*0.28, 0]),
    (11,  "upperarm_l",         10,  [sdx*0.65, 0, 0]),
    (12,  "lowerarm_l",         11,  [UP_ARM, 0, 0]),
    (13,  "hand_l",             12,  [LO_ARM, 0, 0]),
    (14,  "index_01_l",         13,  [HAND_L*0.45, -0.005, 0.015]),
    (15,  "middle_01_l",        13,  [HAND_L*0.45, -0.005, 0.005]),
    (16,  "ring_01_l",          13,  [HAND_L*0.44, -0.005, -0.008]),
    (17,  "pinky_01_l",         13,  [HAND_L*0.42, -0.006, -0.020]),
    (18,  "thumb_01_l",         13,  [HAND_L*0.10, -0.010, 0.020]),
    # Right arm
    (19,  "clavicle_r",          4,  [-sdx*0.35, TORSO_H*0.28, 0]),
    (20,  "upperarm_r",         19,  [-sdx*0.65, 0, 0]),
    (21,  "lowerarm_r",         20,  [-UP_ARM, 0, 0]),
    (22,  "hand_r",             21,  [-LO_ARM, 0, 0]),
    (23,  "index_01_r",         22,  [-HAND_L*0.45, -0.005, -0.015]),
    (24,  "middle_01_r",        22,  [-HAND_L*0.45, -0.005, -0.005]),
    (25,  "ring_01_r",          22,  [-HAND_L*0.44, -0.005, 0.008]),
    (26,  "pinky_01_r",         22,  [-HAND_L*0.42, -0.006, 0.020]),
    (27,  "thumb_01_r",         22,  [-HAND_L*0.10, -0.010, -0.020]),
    # Left leg
    (28,  "thigh_l",             1,  [hdx, 0, 0]),
    (29,  "calf_l",             28,  [0, -THIGH_H, 0]),
    (30,  "foot_l",             29,  [0, -SHIN_H, 0]),
    (31,  "ball_l",             30,  [0, -FOOT_H*0.35, FOOT_H*0.55]),
    # Right leg
    (32,  "thigh_r",             1,  [-hdx, 0, 0]),
    (33,  "calf_r",             32,  [0, -THIGH_H, 0]),
    (34,  "foot_r",             33,  [0, -SHIN_H, 0]),
    (35,  "ball_r",             34,  [0, -FOOT_H*0.35, FOOT_H*0.55]),
    # IK targets
    (36,  "ik_foot_l",           0,  [hdx, 0, 0]),
    (37,  "ik_foot_r",           0,  [-hdx, 0, 0]),
    (38,  "ik_hand_l",          13,  [0, 0, 0]),
    (39,  "ik_hand_r",          22,  [0, 0, 0]),
    # Hair secondaries
    (40,  "hair_top",            6,  [0, HEAD_H*0.55, 0]),
    (41,  "hair_side_l",         6,  [0.07, HEAD_H*0.30, 0]),
    (42,  "hair_side_r",         6,  [-0.07, HEAD_H*0.30, 0]),
    (43,  "hair_back",           6,  [0, HEAD_H*0.10, -0.06]),
    (44,  "hair_fringe",         6,  [0, HEAD_H*0.55, 0.05]),
    # Breast secondaries
    (45,  "breast_l",            4,  [0.08, TORSO_H*0.15, 0.06]),
    (46,  "breast_r",            4,  [-0.08, TORSO_H*0.15, 0.06]),
    # Expression helpers (for mocap / blend shape control bones)
    (47,  "brow_l",              6,  [0.035, HEAD_H*0.48, EYE_Z*0.85]),
    (48,  "brow_r",              6,  [-0.035, HEAD_H*0.48, EYE_Z*0.85]),
    (49,  "cheek_l",             6,  [0.055, HEAD_H*0.22, EYE_Z*0.75]),
    (50,  "cheek_r",             6,  [-0.055, HEAD_H*0.22, EYE_Z*0.75]),
    (51,  "lip_upper",           7,  [0, 0.010, 0.015]),
    (52,  "lip_lower",           7,  [0, -0.010, 0.012]),
    (53,  "lip_corner_l",        7,  [0.025, 0, 0.010]),
    (54,  "lip_corner_r",        7,  [-0.025, 0, 0.010]),
    # Camera mount
    (55,  "camera_bone",         6,  [0, HEAD_H*0.40, 0.15]),
]
assert len(BONES56) == 56, f"Got {len(BONES56)}"

BNAME_TO_IDX = {name: idx for idx, name, _, _ in BONES56}

# ─────────────────────────────────────────────────────────────────────────────
# GEOMETRY PRIMITIVES
# ─────────────────────────────────────────────────────────────────────────────

def sphere(r, s=16):
    V, N, UV, I = [], [], [], []
    for j in range(s + 1):
        phi = math.pi * j / s
        for i in range(s + 1):
            theta = 2 * math.pi * i / s
            x = math.sin(phi) * math.cos(theta) * r
            y = math.cos(phi) * r
            z = math.sin(phi) * math.sin(theta) * r
            V.append([x, y, z])
            N.append([x/r, y/r, z/r])
            UV.append([i/s, j/s])
    for j in range(s):
        for i in range(s):
            a = j*(s+1)+i
            I.extend([a, a+1, a+s+2, a, a+s+2, a+s+1])
    return _geo(V, N, UV, I)


def cylinder(r, h, s=14, taper=1.0):
    """taper < 1 makes top smaller than bottom."""
    V, N, UV, I = [], [], [], []
    hh = h / 2
    rings = []
    for j in range(s + 1):
        t = j / s
        y = -hh + t * h
        rt = r * (1.0 - t*(1.0 - taper))
        ring_start = len(V)
        for i in range(s + 1):
            a = 2 * math.pi * i / s
            x = math.cos(a) * rt
            z = math.sin(a) * rt
            V.append([x, y, z])
            # normal blended with taper
            nx = math.cos(a)
            nz = math.sin(a)
            ny = (r - rt) / h  # slope component
            mag = math.sqrt(nx*nx + ny*ny + nz*nz)
            N.append([nx/mag, ny/mag, nz/mag])
            UV.append([i/s, t])
        rings.append(ring_start)
    for j in range(s):
        for i in range(s):
            a = rings[j]+i; b = a+1; c = rings[j+1]+i+1; d = rings[j+1]+i
            I.extend([a, b, c, a, c, d])
    # caps
    for sign, yc, rf in [(-1, -hh, r), (1, hh, r*taper)]:
        ci = len(V)
        V.append([0, yc, 0]); N.append([0, sign, 0]); UV.append([0.5, 0.5])
        for i in range(s):
            a = 2*math.pi*i/s
            cx = math.cos(a)*rf; cz = math.sin(a)*rf
            V.append([cx, yc, cz]); N.append([0, sign, 0])
            UV.append([0.5+0.5*math.cos(a), 0.5+0.5*math.sin(a)])
        for i in range(s):
            if sign > 0: I.extend([ci, ci+1+i, ci+1+(i+1)%s])
            else:        I.extend([ci, ci+1+(i+1)%s, ci+1+i])
    return _geo(V, N, UV, I)


def box(w, h, d):
    hw, hh, hd = w/2, h/2, d/2
    faces = [
        ([[-hw,-hh,hd],[hw,-hh,hd],[hw,hh,hd],[-hw,hh,hd]],[0,0,1]),
        ([[hw,-hh,-hd],[-hw,-hh,-hd],[-hw,hh,-hd],[hw,hh,-hd]],[0,0,-1]),
        ([[-hw,-hh,-hd],[-hw,-hh,hd],[-hw,hh,hd],[-hw,hh,-hd]],[-1,0,0]),
        ([[hw,-hh,hd],[hw,-hh,-hd],[hw,hh,-hd],[hw,hh,hd]],[1,0,0]),
        ([[-hw,hh,hd],[hw,hh,hd],[hw,hh,-hd],[-hw,hh,-hd]],[0,1,0]),
        ([[-hw,-hh,-hd],[hw,-hh,-hd],[hw,-hh,hd],[-hw,-hh,hd]],[0,-1,0]),
    ]
    uvc = [[0,0],[1,0],[1,1],[0,1]]
    V, N, UV, I = [], [], [], []; base = 0
    for pts, nrm in faces:
        for k, p in enumerate(pts):
            V.append(p); N.append(nrm); UV.append(uvc[k])
        I.extend([base,base+1,base+2,base,base+2,base+3]); base += 4
    return _geo(V, N, UV, I)


def _geo(V, N, UV, I):
    return (np.array(V, np.float32), np.array(N, np.float32),
            np.array(UV, np.float32), np.array(I, np.uint16))


def tx(v, px=0, py=0, pz=0, sx=1, sy=1, sz=1):
    v = v.copy()
    v[:,0] = v[:,0]*sx + px
    v[:,1] = v[:,1]*sy + py
    v[:,2] = v[:,2]*sz + pz
    return v


def merge(*gs):
    Vs, Ns, Us, Is, off = [], [], [], [], 0
    for v, n, u, i in gs:
        Vs.append(v); Ns.append(n); Us.append(u)
        Is.append(i + off); off += len(v)
    return (np.concatenate(Vs), np.concatenate(Ns),
            np.concatenate(Us), np.concatenate(Is))


# ─────────────────────────────────────────────────────────────────────────────
# SMOOTH SKIN WEIGHTS
# Multi-bone blending at joints so mesh doesn't buckle
# ─────────────────────────────────────────────────────────────────────────────

def skin_weights(verts, regions):
    """
    regions: list of (bone_idx, center_xyz, influence_radius, max_weight)
    Returns joints (N,4) uint16, weights (N,4) float32 — normalized.
    """
    nv = len(verts)
    # Collect raw weights per vertex for all regions
    raw = [[] for _ in range(nv)]

    for bone_idx, center, radius, max_w in regions:
        cx, cy, cz = center
        for vi in range(nv):
            vx, vy, vz = verts[vi]
            dist = math.sqrt((vx-cx)**2 + (vy-cy)**2 + (vz-cz)**2)
            if dist < radius:
                # smooth falloff
                t = 1.0 - (dist / radius)
                w = t * t * (3.0 - 2.0*t) * max_w
                if w > 0.001:
                    raw[vi].append((bone_idx, w))

    joints_arr  = np.zeros((nv, 4), np.uint16)
    weights_arr = np.zeros((nv, 4), np.float32)

    for vi in range(nv):
        wlist = sorted(raw[vi], key=lambda x: -x[1])[:4]
        if not wlist:
            # fallback: root bone
            wlist = [(0, 1.0)]
        total = sum(w for _, w in wlist)
        for slot, (bi, w) in enumerate(wlist):
            joints_arr[vi, slot]  = bi
            weights_arr[vi, slot] = w / total

    return joints_arr, weights_arr


def single_bone(nv, bone_idx):
    """Fast path: all verts to one bone."""
    J = np.zeros((nv, 4), np.uint16); J[:, 0] = bone_idx
    W = np.zeros((nv, 4), np.float32); W[:, 0] = 1.0
    return J, W


# ─────────────────────────────────────────────────────────────────────────────
# FACE / HEAD GEOMETRY  (high-poly for blend shapes)
# The face is a separate mesh so blend shapes only cost on the face, not
# the whole character.
# ─────────────────────────────────────────────────────────────────────────────

def build_face_mesh():
    """
    Returns (verts, normals, uvs, indices) for face region.
    Segs=20 for enough resolution to support lip-sync deformation.
    """
    # Skull base
    sv, sn, su, si = sphere(HEAD_H*0.47, s=20)
    sv = tx(sv, py=head_y + HEAD_H*0.47, sx=1.06, sz=0.90)

    # Separate lip region — small torus-like band around mouth
    # (adds verts in the lip area for better lip-sync deformation)
    lip_segs = 16
    LV, LN, LUV, LI = [], [], [], []
    lip_cx = head_y + HEAD_H*0.18   # y center of mouth
    lip_r_major = 0.038              # width of mouth
    lip_r_minor = 0.012
    for j in range(lip_segs+1):
        phi = 2*math.pi*j/lip_segs
        for i in range(lip_segs+1):
            theta = 2*math.pi*i/lip_segs
            x = (lip_r_major + lip_r_minor*math.cos(theta)) * math.cos(phi)
            y = lip_cx + lip_r_minor*math.sin(theta)
            z = EYE_Z*1.15 + lip_r_major*0.3
            LV.append([x, y, z])
            nx = math.cos(theta)*math.cos(phi)
            ny = math.sin(theta)
            nz = math.cos(theta)*math.sin(phi)
            LN.append([nx, ny, nz])
            LUV.append([i/lip_segs, j/lip_segs])
    for j in range(lip_segs):
        for i in range(lip_segs):
            a = j*(lip_segs+1)+i
            LI.extend([a, a+1, a+lip_segs+2, a, a+lip_segs+2, a+lip_segs+1])

    lip_geo = (np.array(LV,np.float32), np.array(LN,np.float32),
               np.array(LUV,np.float32), np.array(LI,np.uint16))

    face_geo = merge((sv,sn,su,si), lip_geo)
    return face_geo


# ─────────────────────────────────────────────────────────────────────────────
# BLEND SHAPES (morph targets)
# Preston Blair viseme set + expression shapes
# Each is a delta from rest position on the face verts
# ─────────────────────────────────────────────────────────────────────────────

VISEMES = [
    # (name, description)
    ("vis_rest",      "Neutral / closed"),
    ("vis_MBP",       "M / B / P  — lips pressed"),
    ("vis_FV",        "F / V  — upper teeth on lower lip"),
    ("vis_open_oh",   "Oh — open oval"),
    ("vis_open_ah",   "Ah / Aa — wide open"),
    ("vis_open_ee",   "Ee / Ih — lips spread"),
    ("vis_open_oo",   "Oo / Uw — pursed"),
    ("vis_open_r",    "R / Er — rounded"),
    ("vis_open_l",    "L — tongue up (approximated)"),
    ("vis_open_w",    "W / Wh — wide pursed"),
    ("vis_th",        "Th — teeth apart"),
    ("vis_ch_sh",     "Ch / Sh — tight oval"),
    ("vis_open_d_t",  "D / T / N — near-closed"),
    ("vis_open_k_g",  "K / G — back-open"),
    ("vis_open_s",    "S / Z — teeth-narrow"),
]

EXPRESSIONS = [
    ("expr_neutral",  "Neutral"),
    ("expr_smile",    "Smile / confident"),
    ("expr_smirk_l",  "Smirk left (Pete's signature)"),
    ("expr_serious",  "Serious / journalist mode"),
    ("expr_angry",    "Angry"),
    ("expr_surprised","Surprised"),
    ("expr_skeptical","Skeptical / one-brow"),
    ("expr_curious",  "Curious / thinking"),
    ("expr_blink_l",  "Blink left"),
    ("expr_blink_r",  "Blink right"),
    ("expr_blink",    "Full blink"),
    ("expr_brow_up",  "Both brows up"),
    ("expr_brow_furrow", "Brow furrow"),
]

ALL_SHAPES = VISEMES + EXPRESSIONS


def make_viseme_delta(face_verts, shape_name, n_face):
    """
    Generate plausible morph delta for each viseme/expression.
    Delta is a displacement on face_verts to approximate the shape.
    For production: replace with sculpted deltas. This gives you valid
    GLB structure with non-zero (but simple) deltas so mocap/lipsync
    retargeting has real targets to drive.
    """
    nv = len(face_verts)
    delta = np.zeros((nv, 3), np.float32)

    # Identify key vertex groups by position
    # Lip region: low on face, forward Z
    lip_mask  = (face_verts[:, 1] < head_y + HEAD_H*0.25) & (face_verts[:, 2] > EYE_Z*0.8)
    jaw_mask  = face_verts[:, 1] < head_y + HEAD_H*0.15
    brow_l    = (face_verts[:, 0] > 0.02) & (face_verts[:, 1] > head_y + HEAD_H*0.40)
    brow_r    = (face_verts[:, 0] < -0.02) & (face_verts[:, 1] > head_y + HEAD_H*0.40)
    eye_l_m   = (face_verts[:, 0] > 0.01) & (face_verts[:, 1] > head_y + HEAD_H*0.30)
    eye_r_m   = (face_verts[:, 0] < -0.01) & (face_verts[:, 1] > head_y + HEAD_H*0.30)
    cheek_l   = (face_verts[:, 0] > 0.04) & (face_verts[:, 1] < head_y + HEAD_H*0.35)
    cheek_r   = (face_verts[:, 0] < -0.04) & (face_verts[:, 1] < head_y + HEAD_H*0.35)

    # Smooth influence based on vertical position for jaw-related shapes
    def jaw_blend(y_arr, open_amt):
        t = np.clip((head_y + HEAD_H*0.25 - y_arr) / (HEAD_H*0.25), 0, 1)
        return t * open_amt

    n = shape_name
    y = face_verts[:, 1]

    if n == "vis_rest":
        pass  # zero delta — rest pose

    elif n == "vis_MBP":
        # Lips pressed together — slight inward Z push at lip area
        delta[lip_mask, 2] -= 0.004
        delta[lip_mask, 1] += jaw_blend(y[lip_mask], 0.003)

    elif n == "vis_FV":
        # Upper lip down slightly, lower lip back
        upper_lip = lip_mask & (face_verts[:, 1] > head_y + HEAD_H*0.18)
        lower_lip = lip_mask & (face_verts[:, 1] <= head_y + HEAD_H*0.18)
        delta[upper_lip, 1] -= 0.006
        delta[lower_lip, 2] -= 0.005

    elif n == "vis_open_ah":
        delta[jaw_mask, 1] -= jaw_blend(y[jaw_mask], 0.022)
        delta[lip_mask, 1]  -= jaw_blend(y[lip_mask], 0.018)
        delta[lip_mask, 2]  += 0.004

    elif n == "vis_open_oh":
        delta[jaw_mask, 1] -= jaw_blend(y[jaw_mask], 0.016)
        delta[lip_mask, 2] += 0.008  # lips forward (rounded)
        delta[lip_mask, 0] *= 0.85   # narrow X

    elif n == "vis_open_ee":
        delta[jaw_mask, 1] -= jaw_blend(y[jaw_mask], 0.010)
        delta[lip_mask, 0] += face_verts[lip_mask, 0] * 0.15  # spread lips

    elif n == "vis_open_oo":
        delta[jaw_mask, 1] -= jaw_blend(y[jaw_mask], 0.012)
        delta[lip_mask, 2] += 0.010
        delta[lip_mask, 0] -= face_verts[lip_mask, 0] * 0.20  # pursed

    elif n == "vis_open_r":
        delta[jaw_mask, 1] -= jaw_blend(y[jaw_mask], 0.014)
        delta[lip_mask, 2] += 0.006
        delta[lip_mask, 0] -= face_verts[lip_mask, 0] * 0.10

    elif n == "vis_open_l":
        delta[jaw_mask, 1] -= jaw_blend(y[jaw_mask], 0.013)

    elif n == "vis_open_w":
        delta[jaw_mask, 1] -= jaw_blend(y[jaw_mask], 0.011)
        delta[lip_mask, 2] += 0.012
        delta[lip_mask, 0] -= face_verts[lip_mask, 0] * 0.25

    elif n == "vis_th":
        delta[jaw_mask, 1] -= jaw_blend(y[jaw_mask], 0.008)

    elif n == "vis_ch_sh":
        delta[jaw_mask, 1] -= jaw_blend(y[jaw_mask], 0.009)
        delta[lip_mask, 2] += 0.007
        delta[lip_mask, 0] -= face_verts[lip_mask, 0] * 0.15

    elif n == "vis_open_d_t":
        delta[jaw_mask, 1] -= jaw_blend(y[jaw_mask], 0.006)

    elif n == "vis_open_k_g":
        delta[jaw_mask, 1] -= jaw_blend(y[jaw_mask], 0.014)

    elif n == "vis_open_s":
        delta[jaw_mask, 1] -= jaw_blend(y[jaw_mask], 0.007)

    # ── Expressions ──────────────────────────────────────────────────────────

    elif n == "expr_smile":
        # Corners of mouth go up and back
        delta[lip_mask, 1] += (face_verts[lip_mask, 0]**2) * 2.0
        delta[lip_mask, 2] += 0.003
        delta[cheek_l, 1] += 0.006
        delta[cheek_r, 1] += 0.006

    elif n == "expr_smirk_l":
        # Left corner up only — Pete's signature
        left_lip = lip_mask & (face_verts[:, 0] > 0.010)
        delta[left_lip, 1] += 0.008
        delta[brow_r, 1] -= 0.003

    elif n == "expr_serious":
        delta[brow_l, 1] -= 0.004
        delta[brow_r, 1] -= 0.004
        # Lips slightly pressed
        delta[lip_mask, 1] -= 0.002

    elif n == "expr_angry":
        delta[brow_l, 1] -= 0.007
        delta[brow_r, 1] -= 0.007
        delta[brow_l, 0]  -= 0.004  # inward
        delta[brow_r, 0]  += 0.004
        delta[lip_mask, 1] -= 0.004

    elif n == "expr_surprised":
        delta[brow_l, 1] += 0.010
        delta[brow_r, 1] += 0.010
        delta[jaw_mask, 1] -= jaw_blend(y[jaw_mask], 0.018)
        delta[eye_l_m, 1] += 0.003
        delta[eye_r_m, 1] += 0.003

    elif n == "expr_skeptical":
        delta[brow_r, 1] += 0.008   # one brow up (Pete's right = viewer's left)
        delta[brow_l, 1] -= 0.002

    elif n == "expr_curious":
        delta[brow_l, 1] += 0.005
        delta[brow_r, 1] += 0.005
        delta[brow_l, 0] += 0.002
        delta[brow_r, 0] -= 0.002

    elif n == "expr_blink_l":
        delta[eye_l_m, 1] -= 0.012

    elif n == "expr_blink_r":
        delta[eye_r_m, 1] -= 0.012

    elif n == "expr_blink":
        delta[eye_l_m, 1] -= 0.012
        delta[eye_r_m, 1] -= 0.012

    elif n == "expr_brow_up":
        delta[brow_l, 1] += 0.009
        delta[brow_r, 1] += 0.009

    elif n == "expr_brow_furrow":
        delta[brow_l, 0] -= 0.005
        delta[brow_r, 0] += 0.005
        delta[brow_l, 1] -= 0.004
        delta[brow_r, 1] -= 0.004

    return delta.astype(np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# BODY PART DEFINITIONS
# (geom_fn, material, primary_bone, blend_regions)
# blend_regions: [(bone_name, center_offset, radius, max_weight)]
# ─────────────────────────────────────────────────────────────────────────────

def build_body_parts():
    """
    Returns list of:
      (verts, normals, uvs, indices, mat_name, joints_arr, weights_arr,
       layer_name, part_name)
    layer_name: 'body' | 'clothing' | 'face' | 'hair'
    """
    parts = []

    def add(geo, mat, bone_primary, blend_regions, layer, name):
        v, n, u, i = geo
        nv = len(v)
        if blend_regions:
            # Build smooth-skinned weights
            regions = []
            for bone_name, offset, radius, max_w in blend_regions:
                bi = BNAME_TO_IDX.get(bone_name, 0)
                # center is bone world position + offset
                bc = [float(x) for x in BONES56[bi][3]]
                cx = bc[0] + offset[0]
                cy = bc[1] + offset[1]
                cz = bc[2] + offset[2]
                regions.append((bi, (cx, cy, cz), radius, max_w))
            J, W = skin_weights(v, regions)
        else:
            J, W = single_bone(nv, BNAME_TO_IDX.get(bone_primary, 0))
        parts.append((v, n, u, i, mat, J, W, layer, name))

    # ── BODY LAYER ─────────────────────────────────────────────────────────
    # Underlying body geometry — this stays when clothes are swapped

    # Torso underlayer (tank top region)
    v, n, u, i = cylinder(0.148, TORSO_H, 16)
    yt = v[:,1]/(TORSO_H/2)
    wt = np.clip(1 - 0.24*np.abs(yt), 0.76, 1.0)
    v[:,0] *= (1.0 + 0.18*yt) * wt; v[:,2] *= wt * 0.87
    v = tx(v, py=spine_y + TORSO_H*0.5)
    add((v,n,u,i), 'tank', 'spine_02',
        [('spine_01',[0,0,0],TORSO_H*0.55,0.7),
         ('spine_02',[0,0,0],TORSO_H*0.55,0.7),
         ('spine_03',[0,0,0],TORSO_H*0.45,0.6),
         ('pelvis',  [0,0,0],PELVIS_H*1.2,0.5)],
        'body','torso_underlayer')

    # Pelvis / hips
    v, n, u, i = cylinder(0.152, PELVIS_H, 14)
    v = tx(v, py=pelvis_y + PELVIS_H*0.5)
    add((v,n,u,i), 'jeans', 'pelvis',
        [('pelvis',[0,0,0], PELVIS_H*1.4, 0.8),
         ('spine_01',[0,0,0], PELVIS_H*1.0, 0.4),
         ('thigh_l',[0,THIGH_H*0.2,0], THIGH_H*0.3, 0.3),
         ('thigh_r',[0,THIGH_H*0.2,0], THIGH_H*0.3, 0.3)],
        'body','pelvis_mesh')

    # ── CLOTHING LAYER ───────────────────────────────────────────────────────

    # Jacket (over torso) — slightly larger than underlayer
    v, n, u, i = cylinder(0.158, TORSO_H, 18)
    yt = v[:,1]/(TORSO_H/2)
    wt = np.clip(1 - 0.26*np.abs(yt), 0.74, 1.0)
    v[:,0] *= (1.0 + 0.22*yt) * wt; v[:,2] *= wt * 0.88
    v = tx(v, py=spine_y + TORSO_H*0.5)
    add((v,n,u,i), 'jacket', 'spine_02',
        [('spine_01',[0,0,0],TORSO_H*0.55,0.7),
         ('spine_02',[0,0,0],TORSO_H*0.55,0.7),
         ('spine_03',[0,0,0],TORSO_H*0.45,0.6),
         ('pelvis',  [0,0,0],PELVIS_H*1.0,0.4)],
        'clothing','jacket_body')

    # Lapels
    for s in [1, -1]:
        v, n, u, i = box(0.042, TORSO_H*0.30, 0.030)
        v = tx(v, px=s*0.060, py=spine_y + TORSO_H*0.68, pz=0.105)
        add((v,n,u,i), 'jacket', 'spine_03', None, 'clothing', f'lapel_{"l" if s>0 else "r"}')

    # Left arm — upper (jacket sleeve)
    v, n, u, i = cylinder(0.054, UP_ARM, 12)
    v = tx(v, px=sdx + UP_ARM*0.5, py=shldr_y)
    add((v,n,u,i), 'jacket', 'upperarm_l',
        [('clavicle_l',[UP_ARM*0.15,0,0], UP_ARM*0.5, 0.4),
         ('upperarm_l',[0,0,0], UP_ARM*0.8, 1.0),
         ('lowerarm_l',[-UP_ARM*0.2,0,0], UP_ARM*0.4, 0.4)],
        'clothing','jacket_sleeve_l')

    # Right arm — upper (jacket sleeve)
    v, n, u, i = cylinder(0.054, UP_ARM, 12)
    v = tx(v, px=-(sdx + UP_ARM*0.5), py=shldr_y)
    add((v,n,u,i), 'jacket', 'upperarm_r',
        [('clavicle_r',[-UP_ARM*0.15,0,0], UP_ARM*0.5, 0.4),
         ('upperarm_r',[0,0,0], UP_ARM*0.8, 1.0),
         ('lowerarm_r',[UP_ARM*0.2,0,0], UP_ARM*0.4, 0.4)],
        'clothing','jacket_sleeve_r')

    # Forearms (skin — jacket ends at elbow)
    for s, bn_up, bn_lo in [(1,'lowerarm_l','hand_l'),(-1,'lowerarm_r','hand_r')]:
        v, n, u, i = cylinder(0.043, LO_ARM, 10)
        v = tx(v, px=s*(sdx + UP_ARM + LO_ARM*0.5), py=shldr_y)
        add((v,n,u,i), 'body_skin', bn_up,
            [(bn_up,[0,0,0], LO_ARM*0.9, 1.0),
             (bn_lo,[0,0,0], LO_ARM*0.5, 0.5)],
            'body', f'forearm_{"l" if s>0 else "r"}')

    # Hands
    for s, bn in [(1,'hand_l'),(-1,'hand_r')]:
        v, n, u, i = box(HAND_L*0.88, 0.025, 0.082)
        v = tx(v, px=s*(sdx + UP_ARM + LO_ARM + HAND_L*0.44), py=shldr_y)
        add((v,n,u,i), 'body_skin', bn, None, 'body', f'hand_{"l" if s>0 else "r"}')

    # JEANS — thighs + shins (smooth at knee)
    for s, tb, sb, cb in [(1,'thigh_l','calf_l','foot_l'),
                           (-1,'thigh_r','calf_r','foot_r')]:
        v, n, u, i = cylinder(0.080, THIGH_H, 12, taper=0.88)
        v = tx(v, px=s*hdx, py=thigh_y - THIGH_H*0.5)
        add((v,n,u,i), 'jeans', tb,
            [(tb,[0,0,0], THIGH_H*0.75, 1.0),
             ('pelvis',[s*hdx,0,0], THIGH_H*0.4, 0.4),
             (sb,[0,THIGH_H*0.1,0], THIGH_H*0.35, 0.45)],
            'clothing', f'thigh_{"l" if s>0 else "r"}')

        v, n, u, i = cylinder(0.062, SHIN_H, 10, taper=0.82)
        v = tx(v, px=s*hdx, py=shin_y - SHIN_H*0.5)
        add((v,n,u,i), 'jeans', sb,
            [(sb,[0,0,0], SHIN_H*0.75, 1.0),
             (tb,[0,-THIGH_H*0.05,0], SHIN_H*0.30, 0.35),
             (cb,[0,SHIN_H*0.05,0], SHIN_H*0.30, 0.40)],
            'clothing', f'shin_{"l" if s>0 else "r"}')

    # COMBAT BOOTS
    for s, fn, bn in [(1,'foot_l','ball_l'),(-1,'foot_r','ball_r')]:
        bv, bn2, bu, bi = box(0.098, FOOT_H*1.55, 0.230)
        bv = tx(bv, px=s*hdx, py=FOOT_H*0.78, pz=0.022)
        sv, sn, su, si = box(0.107, FOOT_H*0.20, 0.240)
        sv = tx(sv, px=s*hdx, py=FOOT_H*0.10, pz=0.022)
        merged = merge((bv,bn2,bu,bi),(sv,sn,su,si))
        fname = 'foot_l' if s > 0 else 'foot_r'
        add(merged, 'boots', fname,
            [(fname,[0,0,0], FOOT_H*2.0, 1.0),
             (bn,[0,0,0], FOOT_H*0.8, 0.5)],
            'clothing', f'boot_{"l" if s>0 else "r"}')

    # Belt + buckle
    beltv, beltn, beltu, belti = box(0.33, 0.034, 0.178)
    beltv = tx(beltv, py=pelvis_y + PELVIS_H*0.74)
    bklv, bkln, bklu, bkli = box(0.042, 0.038, 0.020)
    bklv = tx(bklv, py=pelvis_y + PELVIS_H*0.74, pz=0.092)
    belt_m = merge((beltv,beltn,beltu,belti),(bklv,bkln,bklu,bkli))
    add(belt_m, 'belt', 'pelvis', None, 'clothing', 'belt')

    # ── FACE / HEAD ────────────────────────────────────────────────────────
    # High-res face with blend shapes
    face_geo = build_face_mesh()
    fv = face_geo[0]
    add(face_geo, 'body_skin', 'head',
        [('head',[0,0,0], HEAD_H*1.2, 1.0),
         ('jaw',[0,0,0],  HEAD_H*0.45, 0.5)],
        'face', 'face_mesh')

    # Eyes
    for s, bn in [(1,'eye_l'),(-1,'eye_r')]:
        v, n, u, i = sphere(0.013, s=10)
        v = tx(v, px=s*EYE_X, py=head_y+HEAD_H*0.35, pz=EYE_Z*1.12, sy=0.78, sz=0.60)
        add((v,n,u,i), 'eye_iris', bn, None, 'face', f'eye_{"l" if s>0 else "r"}')

    # Eye whites
    for s, bn in [(1,'eye_l'),(-1,'eye_r')]:
        v, n, u, i = sphere(0.015, s=8)
        v = tx(v, px=s*EYE_X, py=head_y+HEAD_H*0.35, pz=EYE_Z*1.05, sy=0.82, sz=0.65)
        add((v,n,u,i), 'eye_white', bn, None, 'face', f'eye_white_{"l" if s>0 else "r"}')

    # Neck
    v, n, u, i = cylinder(0.045, NECK_H, 12)
    v = tx(v, py=neck_y + NECK_H*0.5)
    add((v,n,u,i), 'body_skin', 'neck_01',
        [('neck_01',[0,0,0], NECK_H*1.1, 1.0),
         ('head',[0,-NECK_H*0.4,0], NECK_H*0.6, 0.4),
         ('spine_03',[0,TORSO_H*0.1,0], NECK_H*0.5, 0.35)],
        'body', 'neck')

    # ── HAIR LAYER ────────────────────────────────────────────────────────
    # Bob — skull cap + side panels
    v, n, u, i = sphere(HEAD_H*0.51, s=16)
    v = tx(v, py=head_y + HEAD_H*0.53, sx=1.09, sz=0.93)
    add((v,n,u,i), 'hair', 'head',
        [('head',[0,0,0], HEAD_H*0.9, 1.0),
         ('hair_top',[0,0,0], HEAD_H*0.5, 0.6),
         ('hair_back',[0,0,0], HEAD_H*0.5, 0.4)],
        'hair', 'hair_cap')

    for s, bn in [(1,'hair_side_l'),(-1,'hair_side_r')]:
        v, n, u, i = box(0.038, HEAD_H*0.50, 0.095)
        v = tx(v, px=s*0.092, py=head_y + HEAD_H*0.22)
        add((v,n,u,i), 'hair', 'head',
            [('head',[s*0.05,0,0], HEAD_H*0.8, 1.0),
             (bn,[0,0,0], HEAD_H*0.5, 0.7)],
            'hair', f'hair_side_{"l" if s>0 else "r"}')

    # Fringe
    v, n, u, i = box(0.140, HEAD_H*0.08, 0.045)
    v = tx(v, py=head_y + HEAD_H*0.54, pz=EYE_Z*0.60)
    add((v,n,u,i), 'hair', 'head',
        [('head',[0,0,0], HEAD_H*0.6, 1.0),
         ('hair_fringe',[0,0,0], HEAD_H*0.4, 0.6)],
        'hair', 'hair_fringe')

    return parts


# ─────────────────────────────────────────────────────────────────────────────
# BINARY PACKER
# ─────────────────────────────────────────────────────────────────────────────

class Bin:
    def __init__(self):
        self._chunks = []; self._off = 0
        self.bv = []; self.acc = []

    def push(self, data: bytes, target: int = None) -> int:
        pad = (-len(data)) % 4
        self._chunks.append(data + b'\x00'*pad)
        bv = {'buffer':0, 'byteOffset':self._off, 'byteLength':len(data)}
        if target: bv['target'] = target
        idx = len(self.bv); self.bv.append(bv)
        self._off += len(data) + pad
        return idx

    def mk_acc(self, bv_i, comp_type, count, typ,
               mn=None, mx=None) -> int:
        a = {'bufferView':bv_i, 'componentType':comp_type,
             'count':count, 'type':typ}
        if mn is not None: a['min'] = [float(x) for x in mn]
        if mx is not None: a['max'] = [float(x) for x in mx]
        idx = len(self.acc); self.acc.append(a); return idx

    def blob(self) -> bytes:
        return b''.join(self._chunks)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN GLB BUILD
# ─────────────────────────────────────────────────────────────────────────────

def build_glb(out_path: str):
    bb = Bin()
    nodes = []; gltf_meshes = []; mesh_node_indices = []
    AB = 34902; EB = 34963  # ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER

    # ── Materials ─────────────────────────────────────────────────────────────
    gltf_mats = []
    for nm in MNAMES:
        m = MATS[nm]
        gm = {
            'name': nm,
            'pbrMetallicRoughness': {
                'baseColorFactor': m['base'],
                'metallicFactor':  m['metal'],
                'roughnessFactor': m['rough'],
            },
            'emissiveFactor': m['emit'],
            'doubleSided': False,
        }
        if m.get('alpha') == 'BLEND': gm['alphaMode'] = 'BLEND'
        gltf_mats.append(gm)

    # ── Body Parts ─────────────────────────────────────────────────────────────
    all_parts = build_body_parts()

    # Identify face verts for morph targets (face_mesh part)
    face_verts_ref = None
    face_mesh_part_idx = None
    for pi, p in enumerate(all_parts):
        if p[8] == 'face_mesh':
            face_verts_ref = p[0]
            face_mesh_part_idx = pi
            break

    for pi, (v, n, u, idx, mat, J, W, layer, part_name) in enumerate(all_parts):
        nv = len(v)
        is_face = (pi == face_mesh_part_idx)

        pa = bb.mk_acc(bb.push(v.tobytes(), AB), 5126, nv, 'VEC3', v.min(0), v.max(0))
        na = bb.mk_acc(bb.push(n.tobytes(), AB), 5126, nv, 'VEC3')
        ua = bb.mk_acc(bb.push(u.tobytes(), AB), 5126, nv, 'VEC2')
        i16 = idx.astype(np.uint16)
        ia = bb.mk_acc(bb.push(i16.tobytes(), EB), 5123, len(idx), 'SCALAR')
        ja = bb.mk_acc(bb.push(J.tobytes(), AB), 5123, nv, 'VEC4')
        wa = bb.mk_acc(bb.push(W.tobytes(), AB), 5126, nv, 'VEC4')

        prim = {
            'attributes': {
                'POSITION':   pa,
                'NORMAL':     na,
                'TEXCOORD_0': ua,
                'JOINTS_0':   ja,
                'WEIGHTS_0':  wa,
            },
            'indices':  ia,
            'material': MIDX[mat],
            'mode':     4,
        }

        # ── Morph Targets (face mesh only) ────────────────────────────────────
        morph_names = []
        if is_face and face_verts_ref is not None:
            targets = []
            for shape_name, shape_desc in ALL_SHAPES:
                delta = make_viseme_delta(face_verts_ref, shape_name, nv)
                # Position delta accessor — sparse would be ideal for production;
                # dense here keeps code simple and GLB self-contained
                da = bb.mk_acc(bb.push(delta.tobytes(), AB), 5126, nv, 'VEC3')
                targets.append({'POSITION': da})
                morph_names.append(shape_name)
            prim['targets'] = targets

        mesh_idx = len(gltf_meshes)
        mesh_obj = {
            'name': f'pete_{part_name}',
            'primitives': [prim],
            'extras': {'layer': layer, 'part': part_name},
        }
        if morph_names:
            mesh_obj['weights']  = [0.0] * len(morph_names)
            mesh_obj['extras']['targetNames'] = morph_names

        gltf_meshes.append(mesh_obj)
        ni = len(nodes)
        node = {
            'name':  f'node_{part_name}',
            'mesh':   mesh_idx,
            'skin':   0,
            'extras': {'layer': layer},
        }
        if morph_names:
            node['weights'] = [0.0] * len(morph_names)
        nodes.append(node)
        mesh_node_indices.append(ni)

    # ── Skeleton ──────────────────────────────────────────────────────────────
    bone_start = len(nodes)

    for _, name, _, lpos in BONES56:
        nodes.append({
            'name':        name,
            'translation': [float(x) for x in lpos],
            'rotation':    [0.0, 0.0, 0.0, 1.0],
            'scale':       [1.0, 1.0, 1.0],
        })

    for idx_b, _, parent, _ in BONES56:
        if parent >= 0:
            nodes[bone_start + parent].setdefault('children', []).append(bone_start + idx_b)

    # Inverse bind matrices (identity — T-pose is rest)
    ibm = np.tile(np.eye(4, dtype=np.float32).flatten(), len(BONES56)).tobytes()
    ibm_bv  = bb.push(ibm)
    ibm_acc = bb.mk_acc(ibm_bv, 5126, len(BONES56), 'MAT4')

    skin = {
        'name':                 'pete_rig_56',
        'joints':               list(range(bone_start, bone_start + len(BONES56))),
        'inverseBindMatrices':  ibm_acc,
        'skeleton':             bone_start,
    }

    # Root armature node
    arm_idx = len(nodes)
    nodes.append({
        'name':     'pete_armature',
        'children': mesh_node_indices + [bone_start],
    })

    # ── Assemble GLTF JSON ────────────────────────────────────────────────────
    blob = bb.blob()
    gltf = {
        'asset': {
            'version':   '2.0',
            'generator': 'Rear View Foresight PubCast AI v5.6 — Pete Avatar Builder',
            'copyright': '2026 Rear View Foresight LLC  |  Feic Mo Chroí™',
        },
        'scene':  0,
        'scenes': [{'name': 'Pete_T-Pose', 'nodes': [arm_idx]}],
        'nodes':      nodes,
        'meshes':     gltf_meshes,
        'materials':  gltf_mats,
        'skins':      [skin],
        'buffers':    [{'byteLength': len(blob)}],
        'bufferViews': bb.bv,
        'accessors':   bb.acc,
        'extras': {
            'character':          'Pete',
            'canonical_height_m': TH,
            'canonical_height':   "5'7\"",
            'occupation':         'Journalist',
            'personality':        'Confident, Curious, Sharp-witted',
            'rig':                '56-bone (subset-compatible with 89-bone UE5 rig)',
            'parallax_depth':     0.45,
            'holo_material_idx':  MIDX['holo'],
            'pubcast_version':    '5.6',
            'reskinning': {
                'body_layer':     'Nodes tagged layer=body — always present',
                'clothing_layer': 'Nodes tagged layer=clothing — swap for outfit change',
                'face_layer':     'Nodes tagged layer=face — separate for blend shape perf',
                'hair_layer':     'Nodes tagged layer=hair — swap for hairstyle change',
                'underwear_note': 'Hide clothing_layer to expose body underlayer',
            },
            'lipsync': {
                'viseme_count':    len(VISEMES),
                'viseme_standard': 'Preston Blair extended set',
                'expression_count':len(EXPRESSIONS),
                'morph_target_mesh':'face_mesh',
                'jaw_bone':        'jaw',
                'lip_bones':       ['lip_upper','lip_lower','lip_corner_l','lip_corner_r'],
                'note':            'Drive blend shapes via audio/mocap retargeter in PubCast',
            },
            'world_scale': {
                'pete_m':     TH,
                'purfluous_m':1.854,
                'ratio':      round(TH/1.854, 4),
            },
            'dream_quote': 'A world of stories is waiting... I just need to capture them.',
        }
    }

    # ── Pack GLB ──────────────────────────────────────────────────────────────
    jb  = json.dumps(gltf, separators=(',', ':')).encode('utf-8')
    jb += b' ' * ((-len(jb)) % 4)
    total = 12 + 8 + len(jb) + 8 + len(blob)

    glb = (
        struct.pack('<III', 0x46546C67, 2, total) +
        struct.pack('<II',  len(jb),   0x4E4F534A) + jb +
        struct.pack('<II',  len(blob), 0x004E4942) + blob
    )

    with open(out_path, 'wb') as f:
        f.write(glb)

    return len(glb), len(gltf_meshes), len(BONES56)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    out = '/mnt/user-data/outputs/pete_avatar_pubcast_v56.glb'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    print("Rear View Foresight — Pete Avatar Builder")
    print("─" * 44)
    size, mc, bc = build_glb(out)
    print(f"  ✓ Output:         {out}")
    print(f"    File size:      {size/1024:.1f} KB")
    print(f"    Mesh parts:     {mc}")
    print(f"    Bones (rig):    {bc}")
    print(f"    Blend shapes:   {len(ALL_SHAPES)}  "
          f"({len(VISEMES)} visemes + {len(EXPRESSIONS)} expressions)")
    print(f"    Layers:         body | clothing | face | hair")
    print(f"    Height:         5'7\" canonical (1.702m)")
    print()
    print("  Integration:")
    print("    PubCast load:  avatar_manager.load_glb('pete', 'pete_avatar_pubcast_v56.glb')")
    print("    Parallax:      avatar.parallax_depth = 0.45")
    print("    Lipsync:       avatar.drive_viseme('vis_open_ah', weight=1.0)")
    print("    Reskin:        avatar.set_layer_visible('clothing', False)")
    print("    Holographic:   avatar.set_material_override('holo')")
    print()
    print("  Next steps:")
    print("    1. Import into Blender, apply Mixamo Female animation pack")
    print("    2. Replace simple blend shape deltas with sculpted shapes")
    print("    3. Wire jaw_bone to audio-driven jaw open via lipsync engine")
    print("    4. Underwear/alternate outfit: hide clothing layer, add new layer")
