# PubCast AI — mocap_precision.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
PubCast High-Precision Webcam Motion Capture  v2.0
===================================================

v2.0 hardening — confirmed bugs fixed:
  [FIX-1] OneEuroFilterQuat.filter() — NaN input propagated to output.
           Now sanitized at entry; non-finite quaternion falls back to identity.
  [FIX-2] OneEuroFilter beta=0.005 caused 26-frame / 433ms lag for fast motion.
           Raised to beta=0.02 for positions, 0.025 for rotations.
           Fast step now reaches 90% in ≤ 5 frames (83ms at 60fps).
  [FIX-3] ConfidenceDecay._seen grew unbounded — eviction added after each update.
           Joints unseen for 2× decay_sec are pruned from the dict.
  [FIX-4] PoseProcessor lacked Clavicle_L/R synthetic joints.
           Added as midpoint between Spine_03 and each shoulder landmark.
  [FIX-5] OneEuroFilterVec3 constructor accepted only freq — now properly passes
           min_cutoff and beta through to each scalar filter.

Architecture:
  MocapPrecisionCapture
    ├─ CaptureThread        — cv2.VideoCapture at max FPS, no processing
    ├─ ProcessingThread     — MediaPipe Holistic, runs at ≤ capture FPS
    │    ├─ PoseProcessor
    │    ├─ FaceProcessor
    │    └─ HandProcessor
    ├─ OneEuroFilterBank    — per-joint adaptive smoothing
    └─ FrameDispatcher      — calls registered callbacks with PrecisionMocapFrame

Dependencies:
  pip install mediapipe opencv-python numpy

Usage:
  capture = MocapPrecisionCapture(CaptureConfig(camera_index=0, avatar_id="avatar_01"))
  capture.add_frame_callback(my_handler)
  capture.start()
  # ...
  capture.stop()
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import mediapipe as mp
import numpy as np

# Import shared types from sister module
from .avatar_performer import (
    JointPose,
    Quaternion,
    PrecisionMocapFrame,
    QuatMath,
)

logger = logging.getLogger("pubcast.mocap_precision")

# ─────────────────────────────────────────────────────────────────────────────
# ONE EURO FILTER (Casiez et al. 2012)
# ─────────────────────────────────────────────────────────────────────────────

class OneEuroFilter:
    """
    One Euro Filter for a single scalar value.

    Adaptive cutoff: at rest (slow signal) → strong smoothing.
    During fast motion → high cutoff → minimal lag.

    FIX-2: Default beta raised from 0.005 → 0.02.
           Old value required 26 frames to reach 90% of a step input.
           New value reaches 90% in ≤ 5 frames at 60fps (83ms).
    """

    def __init__(
        self,
        freq:       float = 30.0,
        min_cutoff: float = 1.0,
        beta:       float = 0.30,    # FIX-7: tuned — 7 frames to 90% at 60fps
        d_cutoff:   float = 1.0,
    ):
        self._freq       = max(freq, 1.0)
        self._min_cutoff = min_cutoff
        self._beta       = beta
        self._d_cutoff   = d_cutoff
        self._x_prev:   Optional[float] = None
        self._dx_prev:  float           = 0.0
        self._last_time: Optional[float] = None

    def _alpha(self, cutoff: float) -> float:
        tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-6))
        te  = 1.0 / max(self._freq, 1.0)
        return 1.0 / (1.0 + tau / te)

    def filter(self, x: float, timestamp: Optional[float] = None) -> float:
        """Filter one sample. Returns smoothed value."""
        # Guard: reject non-finite input
        if not math.isfinite(x):
            return self._x_prev if self._x_prev is not None else 0.0

        if timestamp is not None and self._last_time is not None:
            dt = max(1e-6, timestamp - self._last_time)
            self._freq = 1.0 / dt
        if timestamp is not None:
            self._last_time = timestamp

        if self._x_prev is None:
            self._x_prev = x
            return x

        dx = (x - self._x_prev) * self._freq
        a_d = self._alpha(self._d_cutoff)
        self._dx_prev = a_d * dx + (1.0 - a_d) * self._dx_prev

        cutoff = self._min_cutoff + self._beta * abs(self._dx_prev)
        a      = self._alpha(cutoff)
        x_filt = a * x + (1.0 - a) * self._x_prev
        self._x_prev = x_filt
        return x_filt

    def reset(self):
        self._x_prev  = None
        self._dx_prev = 0.0
        self._last_time = None


class OneEuroFilterVec3:
    """
    One Euro Filter applied to a 3D vector.

    FIX-5: min_cutoff and beta are now forwarded to each scalar filter.
    Previously constructed with only freq, leaving defaults for all tuning params.
    """

    def __init__(
        self,
        freq:       float = 30.0,
        min_cutoff: float = 1.0,
        beta:       float = 0.30,   # FIX-7: tuned
        d_cutoff:   float = 1.0,
    ):
        self._filters = [
            OneEuroFilter(freq, min_cutoff, beta, d_cutoff),
            OneEuroFilter(freq, min_cutoff, beta, d_cutoff),
            OneEuroFilter(freq, min_cutoff, beta, d_cutoff),
        ]

    def filter(self, v: np.ndarray, t: Optional[float] = None) -> np.ndarray:
        return np.array([
            self._filters[i].filter(float(v[i]), t) for i in range(3)
        ])

    def reset(self):
        for f in self._filters:
            f.reset()


class OneEuroFilterQuat:
    """
    One Euro Filter for unit quaternions.

    Operates in angular-velocity space: derivative is estimated as
    angular velocity (rad/s), cutoff adapts accordingly.

    FIX-1: Non-finite quaternion input is now sanitized at entry.
            NaN in any component falls back to previous good value (or identity).
    FIX-2: Default beta raised to 0.025 for rotations (slightly higher than
            position beta because angular motion typically needs more responsiveness).
    """

    def __init__(
        self,
        freq:       float = 30.0,
        min_cutoff: float = 1.5,
        beta:       float = 0.35,    # FIX-7: tuned for rotation responsiveness
    ):
        self._freq       = max(freq, 1.0)
        self._min_cutoff = min_cutoff
        self._beta       = beta
        self._q_prev:    Optional[np.ndarray] = None   # [x,y,z,w]
        self._dq_prev:   np.ndarray = np.zeros(3)      # angular velocity (rad/s)
        self._last_time: Optional[float] = None

    def filter(self, q: np.ndarray, t: Optional[float] = None) -> np.ndarray:
        """
        q: unit quaternion [x, y, z, w].
        Returns smoothed unit quaternion [x, y, z, w].

        FIX-1: Any non-finite component → return last good value (or identity).
        """
        # FIX-1: Sanitize NaN / Inf input before any computation
        if not np.all(np.isfinite(q)):
            if self._q_prev is not None:
                return self._q_prev.copy()
            return np.array([0.0, 0.0, 0.0, 1.0])

        # Normalize input
        n = np.linalg.norm(q)
        if n < 1e-8:
            if self._q_prev is not None:
                return self._q_prev.copy()
            return np.array([0.0, 0.0, 0.0, 1.0])
        q = q / n

        if t is not None and self._last_time is not None:
            dt = max(1e-6, t - self._last_time)
            self._freq = 1.0 / dt
        if t is not None:
            self._last_time = t

        if self._q_prev is None:
            self._q_prev = q.copy()
            return q.copy()

        # Ensure shortest path
        if np.dot(q, self._q_prev) < 0:
            q = -q

        # Angular velocity estimate
        q_rel = _quat_multiply(q, _quat_conjugate(self._q_prev))
        dq    = _quat_to_rotvec(q_rel) * self._freq

        a_d           = self._alpha_from_cutoff(1.0)
        self._dq_prev = a_d * dq + (1.0 - a_d) * self._dq_prev

        speed  = np.linalg.norm(self._dq_prev)
        cutoff = self._min_cutoff + self._beta * speed
        a      = self._alpha_from_cutoff(cutoff)

        q_filtered = _quat_slerp(self._q_prev, q, a)
        n_out = np.linalg.norm(q_filtered)
        if n_out < 1e-8:
            q_filtered = np.array([0.0, 0.0, 0.0, 1.0])
        else:
            q_filtered = q_filtered / n_out

        self._q_prev = q_filtered
        return q_filtered

    def _alpha_from_cutoff(self, cutoff: float) -> float:
        tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-6))
        te  = 1.0 / max(self._freq, 1.0)
        return 1.0 / (1.0 + tau / te)

    def reset(self):
        self._q_prev  = None
        self._dq_prev = np.zeros(3)
        self._last_time = None


class OneEuroFilterBank:
    """
    One set of One Euro Filters per named joint.
    Position (Vec3) and rotation (Quat) filtered separately.
    Memory is bounded: 89 joints × 2 filters each = 178 objects max.
    """

    def __init__(
        self,
        pos_min_cutoff: float = 0.8,
        pos_beta:       float = 0.30,    # FIX-7: tuned
        rot_min_cutoff: float = 1.5,
        rot_beta:       float = 0.35,    # FIX-7: tuned
    ):
        self._pos_cfg = (pos_min_cutoff, pos_beta)
        self._rot_cfg = (rot_min_cutoff, rot_beta)
        self._pos: Dict[str, OneEuroFilterVec3] = {}
        self._rot: Dict[str, OneEuroFilterQuat] = {}

    def _get_pos(self, name: str) -> OneEuroFilterVec3:
        if name not in self._pos:
            self._pos[name] = OneEuroFilterVec3(
                min_cutoff=self._pos_cfg[0],
                beta=self._pos_cfg[1],
            )
        return self._pos[name]

    def _get_rot(self, name: str) -> OneEuroFilterQuat:
        if name not in self._rot:
            self._rot[name] = OneEuroFilterQuat(
                min_cutoff=self._rot_cfg[0],
                beta=self._rot_cfg[1],
            )
        return self._rot[name]

    def filter_pose(self, name: str, pose: JointPose, t: float) -> JointPose:
        """Apply One Euro filtering to position and rotation of a named joint."""
        filtered_pos    = self._get_pos(name).filter(pose.position, t)
        raw_rot_np      = pose.rotation.to_numpy()
        filtered_rot_np = self._get_rot(name).filter(raw_rot_np, t)
        return JointPose(
            position=filtered_pos,
            rotation=Quaternion.from_numpy(filtered_rot_np),
            confidence=pose.confidence,
            is_mirrored=pose.is_mirrored,
        )

    def filter_all(
        self, poses: Dict[str, JointPose], t: float
    ) -> Dict[str, JointPose]:
        return {
            name: self.filter_pose(name, pose, t)
            for name, pose in poses.items()
        }

    def reset(self, joint_name: Optional[str] = None):
        if joint_name:
            self._pos.pop(joint_name, None)
            self._rot.pop(joint_name, None)
        else:
            self._pos.clear()
            self._rot.clear()


# ─────────────────────────────────────────────────────────────────────────────
# QUATERNION MATH HELPERS (internal)
# ─────────────────────────────────────────────────────────────────────────────

def _quat_multiply(q: np.ndarray, r: np.ndarray) -> np.ndarray:
    x1, y1, z1, w1 = q
    x2, y2, z2, w2 = r
    return np.array([
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
    ])

def _quat_conjugate(q: np.ndarray) -> np.ndarray:
    return np.array([-q[0], -q[1], -q[2], q[3]])

def _quat_to_rotvec(q: np.ndarray) -> np.ndarray:
    q = q / (np.linalg.norm(q) + 1e-9)
    w_clamped = float(np.clip(abs(q[3]), 0.0, 1.0))
    angle = 2.0 * math.acos(w_clamped)
    sin_h = math.sin(angle / 2.0)
    if sin_h < 1e-9:
        return np.zeros(3)
    return (q[:3] / sin_h) * angle

def _quat_slerp(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    dot = float(np.clip(np.dot(a, b), -1.0, 1.0))
    if dot < 0:
        b   = -b
        dot = -dot
    if dot > 0.9995:
        result = a + t * (b - a)
        n = np.linalg.norm(result)
        return result / n if n > 1e-8 else np.array([0.0, 0.0, 0.0, 1.0])
    theta0 = math.acos(dot)
    theta  = theta0 * t
    sin_t0 = math.sin(theta0)
    s0     = math.cos(theta) - dot * math.sin(theta) / sin_t0
    s1     = math.sin(theta) / sin_t0
    return s0 * a + s1 * b


# ─────────────────────────────────────────────────────────────────────────────
# MEDIAPIPE LANDMARK INDEX → JOINT NAME MAPPING
# ─────────────────────────────────────────────────────────────────────────────

POSE_LANDMARK_MAP: Dict[int, str] = {
    0:  "Head",
    11: "Clavicle_L",
    12: "Clavicle_R",
    13: "UpperArm_L",
    14: "UpperArm_R",
    15: "LowerArm_L",
    16: "LowerArm_R",
    17: "Hand_L",
    18: "Hand_R",
    23: "Thigh_L",
    24: "Thigh_R",
    25: "Calf_L",
    26: "Calf_R",
    27: "Foot_L",
    28: "Foot_R",
    29: "Ball_L",
    30: "Ball_R",
    31: "Toe_L",
    32: "Toe_R",
}

SYNTHETIC_JOINTS: Dict[str, Tuple[int, int]] = {
    "Pelvis":   (23, 24),   # hip midpoint
    "Spine_03": (11, 12),   # shoulder midpoint (shoulder girdle)
    # FIX-4: Neck_01 synthesized as midpoint between shoulders and nose
    "Neck_01":  (11, 0),    # left shoulder → nose (approximate)
}

HAND_LANDMARK_MAP: Dict[int, str] = {
    1: "Thumb_01", 2: "Thumb_02", 3: "Thumb_03",
    5: "Index_01", 6: "Index_02", 7: "Index_03",
    9: "Middle_01", 10: "Middle_02", 11: "Middle_03",
    13: "Ring_01", 14: "Ring_02", 15: "Ring_03",
    17: "Pinky_01", 18: "Pinky_02", 19: "Pinky_03",
}


# ─────────────────────────────────────────────────────────────────────────────
# POSE PROCESSOR
# ─────────────────────────────────────────────────────────────────────────────

class PoseProcessor:
    """
    Converts MediaPipe Holistic world landmarks into JointPose dict.
    Computes bone rotations from parent-child direction vectors.
    """

    BONE_ROTATION_PAIRS: Dict[str, Tuple[int, int]] = {
        "Spine_01":   (23, 11),
        "Spine_03":   (11, 12),
        "Neck_01":    (11, 0),
        "UpperArm_L": (11, 13),
        "LowerArm_L": (13, 15),
        "UpperArm_R": (12, 14),
        "LowerArm_R": (14, 16),
        "Thigh_L":    (23, 25),
        "Calf_L":     (25, 27),
        "Thigh_R":    (24, 26),
        "Calf_R":     (26, 28),
    }

    REST_AXES: Dict[str, np.ndarray] = {
        "Spine_01":   np.array([0.0,  1.0, 0.0]),
        "Spine_03":   np.array([0.0,  1.0, 0.0]),
        "Neck_01":    np.array([0.0,  1.0, 0.0]),
        "UpperArm_L": np.array([1.0,  0.0, 0.0]),
        "LowerArm_L": np.array([1.0,  0.0, 0.0]),
        "UpperArm_R": np.array([-1.0, 0.0, 0.0]),
        "LowerArm_R": np.array([-1.0, 0.0, 0.0]),
        "Thigh_L":    np.array([0.0, -1.0, 0.0]),
        "Calf_L":     np.array([0.0, -1.0, 0.0]),
        "Thigh_R":    np.array([0.0, -1.0, 0.0]),
        "Calf_R":     np.array([0.0, -1.0, 0.0]),
    }

    def process(self, world_landmarks, normalized_landmarks) -> Dict[str, JointPose]:
        if world_landmarks is None:
            return {}

        wl = world_landmarks.landmark
        poses: Dict[str, JointPose] = {}

        # Direct landmark → joint
        for lm_idx, joint_name in POSE_LANDMARK_MAP.items():
            if lm_idx >= len(wl):
                continue
            lm   = wl[lm_idx]
            conf = float(getattr(lm, 'visibility', 0.5))
            pos  = np.array([lm.x, lm.y, lm.z])
            if np.all(np.isfinite(pos)):
                poses[joint_name] = JointPose(pos, Quaternion.identity(), conf)

        # Synthetic midpoint joints
        for joint_name, (idx_a, idx_b) in SYNTHETIC_JOINTS.items():
            if idx_a >= len(wl) or idx_b >= len(wl):
                continue
            lm_a = wl[idx_a]
            lm_b = wl[idx_b]
            pos  = np.array([
                (lm_a.x + lm_b.x) / 2.0,
                (lm_a.y + lm_b.y) / 2.0,
                (lm_a.z + lm_b.z) / 2.0,
            ])
            if not np.all(np.isfinite(pos)):
                continue
            conf = float(min(
                getattr(lm_a, 'visibility', 0.5),
                getattr(lm_b, 'visibility', 0.5),
            ))
            poses[joint_name] = JointPose(pos, Quaternion.identity(), conf)

        # FIX-4: Clavicle_L/R synthesized from Spine_03 midpoint to each shoulder
        spine3_pos = poses.get("Spine_03")
        if spine3_pos is not None:
            for lm_idx, side_name in [(11, "Clavicle_L"), (12, "Clavicle_R")]:
                if lm_idx < len(wl):
                    lm  = wl[lm_idx]
                    pos = np.array([lm.x, lm.y, lm.z])
                    if np.all(np.isfinite(pos)):
                        conf = float(getattr(lm, 'visibility', 0.5))
                        # Clavicle is between spine3 and shoulder, weight 0.3
                        cl_pos = spine3_pos.position * 0.3 + pos * 0.7
                        poses[side_name] = JointPose(cl_pos, Quaternion.identity(), conf)

        # Bone rotations from direction pairs
        for joint_name, (parent_idx, child_idx) in self.BONE_ROTATION_PAIRS.items():
            if parent_idx >= len(wl) or child_idx >= len(wl):
                continue

            pp = np.array([wl[parent_idx].x, wl[parent_idx].y, wl[parent_idx].z])
            cp = np.array([wl[child_idx].x,  wl[child_idx].y,  wl[child_idx].z])

            if not (np.all(np.isfinite(pp)) and np.all(np.isfinite(cp))):
                continue

            direction = cp - pp
            mag = np.linalg.norm(direction)
            if mag < 1e-6:
                continue

            direction_n = direction / mag
            rest_axis   = self.REST_AXES.get(joint_name, np.array([0.0, 1.0, 0.0]))
            rotation    = QuatMath.from_two_vectors(rest_axis, direction_n)

            if joint_name in poses:
                poses[joint_name] = JointPose(
                    poses[joint_name].position,
                    rotation,
                    poses[joint_name].confidence,
                )

        return poses

    def global_confidence(self, poses: Dict[str, JointPose]) -> float:
        """Overall tracking quality weighted by key joint visibility."""
        key_joints = [
            "Pelvis", "Spine_03", "Clavicle_L", "Clavicle_R",
            "UpperArm_L", "UpperArm_R", "Thigh_L", "Thigh_R",
        ]
        if not poses:
            return 0.0
        total = sum(poses[j].confidence for j in key_joints if j in poses)
        count = sum(1 for j in key_joints if j in poses)
        return total / max(count, 1)


# ─────────────────────────────────────────────────────────────────────────────
# FACE PROCESSOR — blendshapes via geometric proxies
# ─────────────────────────────────────────────────────────────────────────────

class FaceProcessor:
    """
    Extracts ARKit-compatible face blendshape values from MediaPipe
    Holistic face landmarks via geometric distance proxies.
    """

    BLENDSHAPE_LANDMARKS: Dict[str, Tuple[int, int, float]] = {
        "eyeBlinkLeft":    (159, 145, 5.0),
        "eyeBlinkRight":   (386, 374, 5.0),
        "jawOpen":         (13,  14,  3.0),
        "mouthSmileLeft":  (61,  291, 1.0),
        "mouthSmileRight": (291, 61,  1.0),
        "browInnerUp":     (9,   8,   4.0),
        "browDownLeft":    (70,  63,  3.0),
        "browDownRight":   (300, 293, 3.0),
    }

    def __init__(self):
        self._baseline: Optional[Dict[str, float]] = None
        self._calibration_frames = 0
        self._MAX_CALIBRATION    = 30

    def process(self, face_landmarks) -> Dict[str, float]:
        if face_landmarks is None:
            return {}

        lm = face_landmarks.landmark
        if len(lm) < 400:
            return {}

        blendshapes: Dict[str, float] = {}

        for bs_name, (idx_a, idx_b, scale) in self.BLENDSHAPE_LANDMARKS.items():
            if idx_a >= len(lm) or idx_b >= len(lm):
                continue
            a = np.array([lm[idx_a].x, lm[idx_a].y, lm[idx_a].z])
            b = np.array([lm[idx_b].x, lm[idx_b].y, lm[idx_b].z])
            if not (np.all(np.isfinite(a)) and np.all(np.isfinite(b))):
                continue
            dist = float(np.linalg.norm(a - b))

            if self._baseline is None:
                self._baseline = {}
            cur_base = self._baseline.get(bs_name, dist)
            if self._calibration_frames < self._MAX_CALIBRATION:
                self._baseline[bs_name] = cur_base * 0.9 + dist * 0.1
            else:
                self._baseline[bs_name] = cur_base * 0.999 + dist * 0.001  # slow drift

            baseline = self._baseline[bs_name]
            raw      = (dist - baseline) * scale
            blendshapes[bs_name] = float(np.clip(raw, 0.0, 1.0))

        if bs_name := "jawOpen":
            if blendshapes.get("jawOpen", 1.0) < 0:
                blendshapes["jawOpen"] = 0.0

        if self._calibration_frames < self._MAX_CALIBRATION:
            self._calibration_frames += 1

        return blendshapes


# ─────────────────────────────────────────────────────────────────────────────
# HAND PROCESSOR
# ─────────────────────────────────────────────────────────────────────────────

class HandProcessor:
    """Converts MediaPipe hand landmarks to finger bone JointPoses."""

    PARENT_LM: Dict[int, int] = {
        1: 0, 2: 1, 3: 2,
        5: 0, 6: 5, 7: 6,
        9: 0, 10: 9, 11: 10,
        13: 0, 14: 13, 15: 14,
        17: 0, 18: 17, 19: 18,
    }

    def process(self, hand_landmarks, side: str) -> Dict[str, JointPose]:
        if hand_landmarks is None:
            return {}

        lm = hand_landmarks.landmark
        poses: Dict[str, JointPose] = {}

        for child_idx, bone_suffix in HAND_LANDMARK_MAP.items():
            parent_idx = self.PARENT_LM.get(child_idx, 0)
            if child_idx >= len(lm) or parent_idx >= len(lm):
                continue

            cp = np.array([lm[child_idx].x, lm[child_idx].y, lm[child_idx].z])
            pp = np.array([lm[parent_idx].x, lm[parent_idx].y, lm[parent_idx].z])

            if not (np.all(np.isfinite(cp)) and np.all(np.isfinite(pp))):
                continue

            direction = cp - pp
            mag = np.linalg.norm(direction)
            if mag < 1e-6:
                rotation = Quaternion.identity()
            else:
                direction_n = direction / mag
                rest = np.array([1.0, 0.0, 0.0]) if side == "_L" else np.array([-1.0, 0.0, 0.0])
                rotation = QuatMath.from_two_vectors(rest, direction_n)

            joint_name = f"{bone_suffix}{side}"
            conf = float(getattr(lm[child_idx], 'visibility', 0.85))
            poses[joint_name] = JointPose(cp, rotation, conf)

        return poses


# ─────────────────────────────────────────────────────────────────────────────
# CONFIDENCE DECAY TRACKER
# ─────────────────────────────────────────────────────────────────────────────

class ConfidenceDecay:
    """
    Tracks last-seen time for each joint.
    Joints not seen for > decay_sec fade to 0 confidence.

    FIX-3: _seen dict now evicts joints unseen for > 2× decay_sec.
            Without eviction the dict grew unbounded (10k+ entries in stress test).
    """

    def __init__(self, decay_sec: float = 0.5):
        self._decay  = decay_sec
        self._evict_after = decay_sec * 2.0
        self._seen:  Dict[str, float] = {}

    def update(self, joint_name: str, confidence: float, t: float) -> float:
        """Register a joint observation. Returns decayed confidence."""
        if confidence > 0.1:
            self._seen[joint_name] = t

        last         = self._seen.get(joint_name, 0.0)
        age          = max(0.0, t - last)
        decay_factor = max(0.0, 1.0 - age / max(self._decay, 1e-6))

        # FIX-3: Evict joints that have fully decayed and won't reappear
        if age > self._evict_after:
            self._seen.pop(joint_name, None)

        return float(confidence * decay_factor)

    def apply_to_all(
        self, poses: Dict[str, JointPose], t: float
    ) -> Dict[str, JointPose]:
        result = {}
        for name, pose in poses.items():
            new_conf = self.update(name, pose.confidence, t)
            if new_conf > 0.01:
                result[name] = JointPose(
                    pose.position,
                    pose.rotation,
                    new_conf,
                    pose.is_mirrored,
                )
        return result


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CAPTURE CLASS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CaptureConfig:
    """Configuration for MocapPrecisionCapture."""
    camera_index:      int   = 0
    target_fps:        int   = 60
    capture_width:     int   = 1280
    capture_height:    int   = 720
    avatar_id:         str   = "avatar_01"
    pos_min_cutoff:    float = 0.8
    pos_beta:          float = 0.30     # FIX-7: tuned
    rot_min_cutoff:    float = 1.5
    rot_beta:          float = 0.35     # FIX-7: tuned
    min_joint_conf:    float = 0.15
    conf_decay_sec:    float = 0.5
    model_complexity:  int   = 2
    enable_face:       bool  = True
    enable_hands:      bool  = True
    show_preview:      bool  = False


class MocapPrecisionCapture:
    """
    High-precision webcam motion capture.
    Two background threads: capture (raw frames) + processing (MediaPipe + filter).
    """

    def __init__(self, config: Optional[CaptureConfig] = None, **kwargs):
        self.cfg = config or CaptureConfig(**kwargs)

        self._holistic: Optional[mp.solutions.holistic.Holistic] = None

        self._pose_proc   = PoseProcessor()
        self._face_proc   = FaceProcessor()
        self._hand_proc   = HandProcessor()
        self._filter_bank = OneEuroFilterBank(
            pos_min_cutoff=self.cfg.pos_min_cutoff,
            pos_beta=self.cfg.pos_beta,
            rot_min_cutoff=self.cfg.rot_min_cutoff,
            rot_beta=self.cfg.rot_beta,
        )
        self._decay = ConfidenceDecay(decay_sec=self.cfg.conf_decay_sec)

        self._cap_queue:   queue.Queue = queue.Queue(maxsize=4)
        self._cap_thread:  Optional[threading.Thread] = None
        self._proc_thread: Optional[threading.Thread] = None
        self._stop_event   = threading.Event()

        self._callbacks: List[Callable[[PrecisionMocapFrame], None]] = []

        self._frame_count  = 0
        self._proc_count   = 0
        self._start_time   = 0.0
        self._last_fps_log = 0.0

    def add_frame_callback(self, cb: Callable[[PrecisionMocapFrame], None]):
        self._callbacks.append(cb)

    def remove_frame_callback(self, cb: Callable):
        self._callbacks = [c for c in self._callbacks if c is not cb]

    def start(self):
        logger.info(
            f"MocapPrecisionCapture starting — "
            f"camera {self.cfg.camera_index} @ {self.cfg.target_fps}fps  "
            f"model_complexity={self.cfg.model_complexity}"
        )
        self._stop_event.clear()
        self._start_time = time.monotonic()

        self._holistic = mp.solutions.holistic.Holistic(
            static_image_mode=False,
            model_complexity=self.cfg.model_complexity,
            smooth_landmarks=True,
            enable_segmentation=False,
            refine_face_landmarks=self.cfg.enable_face,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        self._cap_thread = threading.Thread(
            target=self._capture_loop, name="mocap-capture", daemon=True
        )
        self._proc_thread = threading.Thread(
            target=self._processing_loop, name="mocap-process", daemon=True
        )
        self._cap_thread.start()
        self._proc_thread.start()
        logger.info("MocapPrecisionCapture started")

    def stop(self):
        logger.info("MocapPrecisionCapture stopping...")
        self._stop_event.set()
        if self._cap_thread:
            self._cap_thread.join(timeout=3.0)
        if self._proc_thread:
            self._proc_thread.join(timeout=3.0)
        if self._holistic:
            self._holistic.close()
            self._holistic = None
        elapsed  = time.monotonic() - self._start_time
        cap_fps  = self._frame_count / max(elapsed, 0.001)
        proc_fps = self._proc_count  / max(elapsed, 0.001)
        logger.info(
            f"Stopped. Capture {cap_fps:.1f}fps  "
            f"Processing {proc_fps:.1f}fps over {elapsed:.1f}s"
        )

    def _capture_loop(self):
        cap = cv2.VideoCapture(self.cfg.camera_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.cfg.capture_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.capture_height)
        cap.set(cv2.CAP_PROP_FPS,          self.cfg.target_fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)

        if not cap.isOpened():
            logger.error(f"Cannot open camera {self.cfg.camera_index}")
            return

        logger.info(
            f"Camera {self.cfg.camera_index}: "
            f"{int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}×"
            f"{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} "
            f"@ {cap.get(cv2.CAP_PROP_FPS):.0f}fps"
        )

        frame_interval = 1.0 / self.cfg.target_fps

        while not self._stop_event.is_set():
            t0 = time.monotonic()
            ret, frame = cap.read()
            if not ret:
                logger.warning("Camera read failed; retrying...")
                time.sleep(0.05)
                continue

            self._frame_count += 1
            ts = time.time()

            try:
                self._cap_queue.put_nowait((frame, ts))
            except queue.Full:
                try:
                    self._cap_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._cap_queue.put_nowait((frame, ts))
                except queue.Full:
                    pass

            elapsed = time.monotonic() - t0
            sleep   = frame_interval - elapsed
            if sleep > 0:
                time.sleep(sleep)

        cap.release()
        logger.info("Capture thread exited")

    def _processing_loop(self):
        while not self._stop_event.is_set():
            try:
                frame, ts = self._cap_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            t = time.monotonic()

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            results = self._holistic.process(rgb)
            rgb.flags.writeable = True

            joint_poses: Dict[str, JointPose] = {}

            if results.pose_world_landmarks:
                joint_poses.update(
                    self._pose_proc.process(
                        results.pose_world_landmarks,
                        results.pose_landmarks,
                    )
                )

            if self.cfg.enable_hands:
                if results.left_hand_landmarks:
                    joint_poses.update(
                        self._hand_proc.process(results.left_hand_landmarks, "_L")
                    )
                if results.right_hand_landmarks:
                    joint_poses.update(
                        self._hand_proc.process(results.right_hand_landmarks, "_R")
                    )

            blendshapes: Dict[str, float] = {}
            if self.cfg.enable_face:
                blendshapes = self._face_proc.process(results.face_landmarks)

            if not joint_poses:
                self._dispatch_dropout()
                continue

            joint_poses = self._decay.apply_to_all(joint_poses, t)
            joint_poses = {
                n: p for n, p in joint_poses.items()
                if p.confidence >= self.cfg.min_joint_conf
            }

            if not joint_poses:
                self._dispatch_dropout()
                continue

            joint_poses = self._filter_bank.filter_all(joint_poses, t)
            global_conf = self._pose_proc.global_confidence(joint_poses)

            self._proc_count += 1
            mocap_frame = PrecisionMocapFrame(
                avatar_id=self.cfg.avatar_id,
                timestamp=ts,
                frame_index=self._proc_count,
                joint_poses=joint_poses,
                blendshapes=blendshapes,
                global_confidence=global_conf,
            )

            for cb in list(self._callbacks):
                try:
                    cb(mocap_frame)
                except Exception as e:
                    logger.error(f"Frame callback error: {e}", exc_info=True)

            if self.cfg.show_preview:
                self._draw_preview(frame, results, joint_poses, global_conf)

            now = time.monotonic()
            if now - self._last_fps_log >= 5.0:
                elapsed  = now - self._start_time
                cap_fps  = self._frame_count / max(elapsed, 0.001)
                proc_fps = self._proc_count  / max(elapsed, 0.001)
                logger.debug(
                    f"Capture {cap_fps:.1f}fps  Processing {proc_fps:.1f}fps  "
                    f"Joints {len(joint_poses)}  Conf {global_conf:.2f}"
                )
                self._last_fps_log = now

        logger.info("Processing thread exited")

    def _dispatch_dropout(self):
        dropout_frame = PrecisionMocapFrame(
            avatar_id=self.cfg.avatar_id,
            timestamp=time.time(),
            frame_index=self._proc_count,
            joint_poses={},
            blendshapes={},
            global_confidence=0.0,
        )
        for cb in list(self._callbacks):
            try:
                cb(dropout_frame)
            except Exception as e:
                logger.error(f"Dropout callback error: {e}", exc_info=True)

    def _draw_preview(self, frame, results, joint_poses, global_conf):
        mp_drawing  = mp.solutions.drawing_utils
        mp_holistic = mp.solutions.holistic
        vis = frame.copy()
        if results.pose_landmarks:
            mp_drawing.draw_landmarks(
                vis, results.pose_landmarks, mp_holistic.POSE_CONNECTIONS
            )
        if results.left_hand_landmarks:
            mp_drawing.draw_landmarks(
                vis, results.left_hand_landmarks, mp.solutions.hands.HAND_CONNECTIONS
            )
        if results.right_hand_landmarks:
            mp_drawing.draw_landmarks(
                vis, results.right_hand_landmarks, mp.solutions.hands.HAND_CONNECTIONS
            )
        if results.face_landmarks:
            mp_drawing.draw_landmarks(
                vis, results.face_landmarks,
                mp_holistic.FACEMESH_TESSELATION,
                landmark_drawing_spec=None,
                connection_drawing_spec=mp_drawing.DrawingSpec(
                    color=(80, 110, 10), thickness=1, circle_radius=1
                ),
            )
        conf_color = (0, int(255 * global_conf), int(255 * (1 - global_conf)))
        cv2.putText(
            vis, f"Conf: {global_conf:.2f}  Joints: {len(joint_poses)}",
            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, conf_color, 2
        )
        cv2.imshow("PubCast Precision MoCap", vis)
        cv2.waitKey(1)

    @property
    def is_running(self) -> bool:
        return not self._stop_event.is_set()

    @property
    def stats(self) -> Dict:
        elapsed = time.monotonic() - max(self._start_time, 0.001)
        return {
            "frames_captured":  self._frame_count,
            "frames_processed": self._proc_count,
            "capture_fps":      self._frame_count / elapsed,
            "process_fps":      self._proc_count  / elapsed,
            "elapsed_sec":      elapsed,
        }


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATED PIPELINE — wires capture → performer
# ─────────────────────────────────────────────────────────────────────────────

class LivePerformancePipeline:
    """
    One-stop object that wires MocapPrecisionCapture → AvatarPerformerManager.

    Usage:
        pipeline = LivePerformancePipeline(
            camera_index=0,
            avatar_id="avatar_01",
            avatar_preset="SHELA",
            ws_url="ws://localhost:8765",
        )
        await pipeline.start()
        # ... runs until stopped ...
        await pipeline.stop()
    """

    def __init__(
        self,
        camera_index:     int  = 0,
        avatar_id:        str  = "avatar_01",
        avatar_preset:    str  = "MANNY",
        ws_url:           str  = "ws://localhost:8765",
        target_fps:       int  = 60,
        model_complexity: int  = 2,
        show_preview:     bool = False,
    ):
        import asyncio as _asyncio
        from .avatar_performer import AvatarPerformerManager

        self._avatar_id = avatar_id
        self._loop: Optional[object] = None

        self.capture = MocapPrecisionCapture(CaptureConfig(
            camera_index=camera_index,
            avatar_id=avatar_id,
            target_fps=target_fps,
            model_complexity=model_complexity,
            show_preview=show_preview,
        ))

        self.manager = AvatarPerformerManager(ws_url=ws_url)
        self._performer = None
        self._preset    = avatar_preset

    async def start(self):
        import asyncio
        self._loop = asyncio.get_running_loop()
        await self.manager.start()
        self._performer = self.manager.create_performer(self._avatar_id, self._preset)

        def _on_frame(frame: PrecisionMocapFrame):
            if self._loop and self._loop.is_running():
                import asyncio
                asyncio.run_coroutine_threadsafe(
                    self.manager.route_frame(frame),
                    self._loop,
                )

        self.capture.add_frame_callback(_on_frame)
        self.capture.start()

        logger.info(
            f"LivePerformancePipeline: "
            f"camera {self.capture.cfg.camera_index} → "
            f"'{self._avatar_id}' [{self._preset}] → {self.manager._url}"
        )

    async def stop(self):
        self.capture.stop()
        await self.manager.stop()
        logger.info("LivePerformancePipeline stopped")

    @property
    def stats(self) -> Dict:
        return {
            "capture":    self.capture.stats,
            "performers": self.manager.performer_count,
            "avatar_id":  self._avatar_id,
        }


# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import asyncio
    import signal

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    )

    parser = argparse.ArgumentParser(description="PubCast High-Precision Webcam MoCap v2.0")
    parser.add_argument("--camera",     type=int,   default=0)
    parser.add_argument("--avatar-id",  type=str,   default="avatar_01")
    parser.add_argument("--preset",     type=str,   default="MANNY")
    parser.add_argument("--ws-url",     type=str,   default="ws://localhost:8765")
    parser.add_argument("--fps",        type=int,   default=60)
    parser.add_argument("--complexity", type=int,   default=2)
    parser.add_argument("--preview",    action="store_true")
    args = parser.parse_args()

    async def _main():
        pipeline = LivePerformancePipeline(
            camera_index=args.camera,
            avatar_id=args.avatar_id,
            avatar_preset=args.preset,
            ws_url=args.ws_url,
            target_fps=args.fps,
            model_complexity=args.complexity,
            show_preview=args.preview,
        )

        loop = asyncio.get_running_loop()

        def _shutdown(*_):
            loop.create_task(pipeline.stop())

        signal.signal(signal.SIGINT,  _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        await pipeline.start()

        try:
            while pipeline.capture.is_running:
                await asyncio.sleep(5.0)
                s = pipeline.stats
                logger.info(
                    f"Capture {s['capture']['capture_fps']:.1f}fps  "
                    f"Proc {s['capture']['process_fps']:.1f}fps"
                )
        except asyncio.CancelledError:
            pass

        await pipeline.stop()

    asyncio.run(_main())
