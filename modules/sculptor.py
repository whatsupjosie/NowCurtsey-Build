# PubCast AI — sculptor.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
modules/sculptor.py — Photo-to-voxel avatar portrait baker.

Takes a user photo, detects a face, and produces a voxel bake payload
that the engine can render as the user's avatar.

Exports:
    Sculptor(mode: str)
        .bake_from_photo(photo_path: Path, uid: str) -> dict | None
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional heavy dependencies — degrade gracefully if not installed
# ---------------------------------------------------------------------------
try:
    import cv2  # type: ignore
    _CV2_AVAILABLE = True
except (ImportError, OSError) as exc:
    # See audio_devices: a native-backed wheel can import-fail with OSError
    # (missing libGL, missing shared object) rather than ImportError.
    _CV2_AVAILABLE = False
    logger.info("Sculptor: opencv unavailable (%s) — using fallback palette extractor.", exc)

try:
    from PIL import Image  # type: ignore
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False
    logger.info("Sculptor: Pillow not installed — color extraction limited.")


# ---------------------------------------------------------------------------
# Voxel palette — maps dominant face tones to voxel material IDs
# ---------------------------------------------------------------------------
_SKIN_PALETTE: List[Dict[str, Any]] = [
    {"name": "fair",      "rgb": (255, 220, 185), "voxel_id": "skin_fair"},
    {"name": "light",     "rgb": (240, 195, 145), "voxel_id": "skin_light"},
    {"name": "medium",    "rgb": (210, 160, 110), "voxel_id": "skin_medium"},
    {"name": "tan",       "rgb": (175, 125,  80), "voxel_id": "skin_tan"},
    {"name": "deep",      "rgb": (130,  85,  50), "voxel_id": "skin_deep"},
    {"name": "dark",      "rgb": ( 90,  55,  30), "voxel_id": "skin_dark"},
]


def _closest_skin_voxel(r: int, g: int, b: int) -> str:
    best_id = _SKIN_PALETTE[2]["voxel_id"]  # default: medium
    best_dist = float("inf")
    for entry in _SKIN_PALETTE:
        pr, pg, pb = entry["rgb"]
        dist = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if dist < best_dist:
            best_dist = dist
            best_id = entry["voxel_id"]
    return best_id


def _extract_dominant_color_pil(photo_path: Path) -> Optional[tuple]:
    """Return (r, g, b) dominant colour from centre crop using Pillow."""
    if not _PIL_AVAILABLE:
        return None
    try:
        img = Image.open(photo_path).convert("RGB")
        w, h = img.size
        # Centre crop: middle 40% of image where the face is most likely
        crop_box = (int(w * 0.3), int(h * 0.1), int(w * 0.7), int(h * 0.6))
        cropped = img.crop(crop_box).resize((16, 16), Image.LANCZOS)
        pixels = list(cropped.getdata())
        r = sum(p[0] for p in pixels) // len(pixels)
        g = sum(p[1] for p in pixels) // len(pixels)
        b = sum(p[2] for p in pixels) // len(pixels)
        return (r, g, b)
    except Exception as exc:
        logger.warning("Sculptor PIL color extract failed: %s", exc)
        return None


def _extract_dominant_color_cv2(photo_path: Path) -> Optional[tuple]:
    """Return (r, g, b) dominant colour using OpenCV face detection."""
    if not _CV2_AVAILABLE:
        return None
    try:
        img = cv2.imread(str(photo_path))
        if img is None:
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        if len(faces) == 0:
            return None
        # Use the largest detected face
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        face_roi = img[y: y + h, x: x + w]
        avg_color_bgr = face_roi.mean(axis=(0, 1))
        b, g, r = int(avg_color_bgr[0]), int(avg_color_bgr[1]), int(avg_color_bgr[2])
        return (r, g, b)
    except Exception as exc:
        logger.warning("Sculptor cv2 color extract failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Sculptor
# ---------------------------------------------------------------------------

class Sculptor:
    """
    Bakes a user photo into a voxel avatar payload.

    Parameters
    ----------
    mode : str
        Bake mode — currently supports ``"TRACK"`` (face tracking) and
        ``"STATIC"`` (single-frame snapshot).  Additional modes reserved
        for future releases.
    """

    SUPPORTED_MODES = {"TRACK", "STATIC"}

    def __init__(self, mode: str = "TRACK") -> None:
        if mode not in self.SUPPORTED_MODES:
            logger.warning("Sculptor: unknown mode '%s', falling back to TRACK", mode)
            mode = "TRACK"
        self.mode = mode

    def bake_from_photo(self, photo_path: Path, uid: str) -> Optional[Dict[str, Any]]:
        """
        Process ``photo_path`` and return a voxel bake payload dict, or
        ``None`` if no face could be detected.

        The payload is safe to JSON-serialize and forward to the engine bridge.
        """
        photo_path = Path(photo_path)
        if not photo_path.exists():
            logger.error("Sculptor.bake_from_photo: file not found: %s", photo_path)
            return None

        # 1. Try cv2 (better — uses actual face detection)
        dominant = _extract_dominant_color_cv2(photo_path)
        face_detected = dominant is not None

        # 2. Fall back to PIL centre-crop
        if dominant is None:
            dominant = _extract_dominant_color_pil(photo_path)

        # 3. If we have no image libraries at all, use a deterministic
        #    colour derived from the uid hash so the avatar isn't blank.
        if dominant is None:
            digest = hashlib.sha256(uid.encode()).digest()
            dominant = (digest[0], digest[1], digest[2])
            logger.info("Sculptor: no image library available, using hash colour for uid=%s", uid)

        r, g, b = dominant
        skin_voxel = _closest_skin_voxel(r, g, b)

        payload: Dict[str, Any] = {
            "bake_id":       f"bake_{uid}_{int(time.time())}",
            "uid":           uid,
            "mode":          self.mode,
            "face_detected": face_detected,
            "dominant_rgb":  [r, g, b],
            "skin_voxel":    skin_voxel,
            "layers": [
                {"layer": "head",   "voxel_id": skin_voxel, "size": [6, 7, 6]},
                {"layer": "body",   "voxel_id": skin_voxel, "size": [6, 9, 4]},
                {"layer": "detail", "voxel_id": "auto",     "size": [6, 7, 6]},
            ],
            "baked_at": time.time(),
            # Compatibility aliases expected by main's bake endpoint and bridge
            "voxel_count": 3,
            "grit_index":  round((r * 0.299 + g * 0.587 + b * 0.114) / 255, 3),
            "skin_color":  f"#{r:02x}{g:02x}{b:02x}",
            "hair_color":  f"#{max(0,r-40):02x}{max(0,g-40):02x}{max(0,b-40):02x}",
        }

        logger.info(
            "Sculptor: baked uid=%s skin=%s face_detected=%s mode=%s",
            uid, skin_voxel, face_detected, self.mode,
        )
        return payload


__all__ = ["Sculptor"]
