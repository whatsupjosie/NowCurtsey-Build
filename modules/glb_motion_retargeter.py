"""GLB motion retargeting helpers for PubCast avatar motion commands.

This module is intentionally small and dependency-free. It normalizes browser-bound
motion payloads, clamps unsafe rotations, and drops bones unknown to the canonical
PubCast/Manny/Sheila bridge map.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping

MAX_ROTATION_DEG = 35.0
ALLOWED_KINDS = {"mocap_pose", "overlay", "procedural_animation", "hold"}

CANONICAL_BONES = {
    "root", "hips", "pelvis", "spine", "spine_01", "spine_02", "chest", "neck", "head", "jaw",
    "left_shoulder", "right_shoulder", "left_arm", "right_arm", "left_forearm", "right_forearm",
    "left_hand", "right_hand", "left_leg", "right_leg", "left_knee", "right_knee", "left_foot",
    "right_foot", "left_toe", "right_toe", "tail_01", "tail_02", "tail_03", "tail_04", "tail_05",
}

ALIASES = {
    "Root": "root", "Pelvis": "hips", "Hips": "hips", "Spine_01": "spine", "Spine_02": "spine_02",
    "Spine_03": "chest", "Spine_04": "chest", "Neck_01": "neck", "Neck_02": "neck", "Head": "head",
    "Jaw": "jaw", "Clavicle_L": "left_shoulder", "Clavicle_R": "right_shoulder",
    "UpperArm_L": "left_arm", "UpperArm_R": "right_arm", "LowerArm_L": "left_forearm",
    "LowerArm_R": "right_forearm", "Hand_L": "left_hand", "Hand_R": "right_hand",
    "Thigh_L": "left_leg", "Thigh_R": "right_leg", "Calf_L": "left_knee", "Calf_R": "right_knee",
    "Foot_L": "left_foot", "Foot_R": "right_foot", "Toe_L": "left_toe", "Toe_R": "right_toe",
    "Tail_01": "tail_01", "Tail_02": "tail_02", "Tail_03": "tail_03", "Tail_04": "tail_04", "Tail_05": "tail_05",
}


def canonical_bone(name: str) -> str | None:
    key = str(name or "").strip()
    if not key:
        return None
    alias = ALIASES.get(key) or ALIASES.get(key.replace(" ", "_"))
    if alias:
        return alias
    lowered = key.lower()
    if lowered in CANONICAL_BONES:
        return lowered
    return None


def _finite_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def clamp_rotation(values: Iterable[Any], max_degrees: float = MAX_ROTATION_DEG) -> list[float]:
    limit = abs(_finite_number(max_degrees, MAX_ROTATION_DEG)) or MAX_ROTATION_DEG
    out = []
    for raw in list(values)[:3]:
        value = _finite_number(raw)
        out.append(max(-limit, min(limit, value)))
    while len(out) < 3:
        out.append(0.0)
    return out


def normalize_bone_pose(pose: Mapping[str, Any], max_degrees: float = MAX_ROTATION_DEG) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    if "rotation" in pose:
        normalized["rotation"] = clamp_rotation(pose.get("rotation") or [], max_degrees)
    else:
        xyz = [pose.get("x", 0.0), pose.get("y", 0.0), pose.get("z", 0.0)]
        if any(v is not None for v in xyz):
            normalized["rotation"] = clamp_rotation(xyz, max_degrees)
    if "position" in pose and isinstance(pose["position"], (list, tuple)):
        normalized["position"] = [_finite_number(v) for v in list(pose["position"])[:3]]
    return normalized


def normalize_command(command: Mapping[str, Any], max_degrees: float = MAX_ROTATION_DEG) -> Dict[str, Any] | None:
    kind = str(command.get("kind") or "mocap_pose")
    if kind not in ALLOWED_KINDS:
        return None
    pose = command.get("pose") if isinstance(command.get("pose"), Mapping) else command
    bones = pose.get("bones", {}) if isinstance(pose, Mapping) else {}
    if not isinstance(bones, Mapping):
        bones = {}
    normalized_bones: Dict[str, Dict[str, Any]] = {}
    for raw_name, raw_pose in bones.items():
        bone = canonical_bone(str(raw_name))
        if not bone or not isinstance(raw_pose, Mapping):
            continue
        normalized_pose = normalize_bone_pose(raw_pose, max_degrees)
        if normalized_pose:
            normalized_bones[bone] = normalized_pose
    if not normalized_bones:
        return None
    out = deepcopy(dict(command))
    out["kind"] = kind
    out["pose"] = {"bones": normalized_bones}
    out["weight"] = max(0.0, min(1.0, _finite_number(command.get("weight", 1.0), 1.0)))
    out["priority"] = int(_finite_number(command.get("priority", 0), 0))
    return out


def normalize_payload(payload: Mapping[str, Any], max_degrees: float = MAX_ROTATION_DEG) -> Dict[str, Any]:
    avatar_id = str(payload.get("avatar_id") or payload.get("avatarId") or "").strip()
    commands = payload.get("commands")
    if not isinstance(commands, list):
        commands = [payload.get("command") or payload]
    normalized = []
    for command in commands:
        if isinstance(command, Mapping):
            item = normalize_command(command, max_degrees=max_degrees)
            if item:
                normalized.append(item)
    return {"avatar_id": avatar_id, "commands": normalized}


__all__ = [
    "ALIASES", "ALLOWED_KINDS", "CANONICAL_BONES", "MAX_ROTATION_DEG", "canonical_bone",
    "clamp_rotation", "normalize_bone_pose", "normalize_command", "normalize_payload",
]
