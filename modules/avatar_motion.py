# PubCast AI — avatar_motion.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""modules/avatar_motion.py — Avatar motion-capture presets for PubCast."""
from enum import Enum

class AvatarPreset(str, Enum):
    IDLE        = "idle"
    TALKING     = "talking"
    LISTENING   = "listening"
    GESTURING   = "gesturing"
    WALKING     = "walking"
    DANCING     = "dancing"
    PRESENTING  = "presenting"
    REACTING    = "reacting"

__all__ = ["AvatarPreset"]
