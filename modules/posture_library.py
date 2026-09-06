"""Posture labeling for Bubble Stack v0.1.

This is intentionally conservative: it labels broad interaction states, not secret intent.
The job is to help Jeremy choose safer next moves, not pretend a shoulder angle is a confession.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

Vector3 = Tuple[float, float, float]


@dataclass
class PostureResult:
    label: str
    confidence: float
    reasons: list[str]


class PostureLibrary:
    def classify(self, bones: Dict[str, Vector3]) -> PostureResult:
        reasons: list[str] = []
        if not bones:
            return PostureResult("unknown", 0.0, ["no bones supplied"])

        head = bones.get("Head") or bones.get("head")
        spine = bones.get("Spine_01") or bones.get("spine") or bones.get("Chest")
        left_shoulder = bones.get("LeftShoulder") or bones.get("shoulder_l")
        right_shoulder = bones.get("RightShoulder") or bones.get("shoulder_r")

        if head and spine:
            head_drop = spine[1] - head[1]
            if head_drop > -0.1:
                reasons.append("head low relative to spine")
                return PostureResult("withdrawn_or_low_energy", 0.55, reasons)

        if head and spine:
            forward_lean = head[2] - spine[2]
            if forward_lean > 0.35:
                reasons.append("head forward from spine")
                return PostureResult("leaning_in", 0.6, reasons)
            if forward_lean < -0.35:
                reasons.append("head back from spine")
                return PostureResult("leaning_back", 0.6, reasons)

        if left_shoulder and right_shoulder:
            shoulder_width = abs(left_shoulder[0] - right_shoulder[0])
            if shoulder_width < 0.22:
                reasons.append("shoulders compressed")
                return PostureResult("closed_or_hunched", 0.5, reasons)
            if shoulder_width > 0.55:
                reasons.append("shoulders open")
                return PostureResult("open_posture", 0.5, reasons)

        return PostureResult("neutral", 0.4, ["no strong posture pattern"])

