# PubCast AI — lighting_engine.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
PubCast Lighting Engine — Python Backend
hub.py integration, WebSocket broadcast, preset management, audio-reactive driver.

Drop-in alongside your existing hub.py. Wires into the same WebSocket
message loop that handles choreography and skin events.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Tuple


# ─────────────────────────────────────────────
#  LIGHT STATE  (Python mirror of JS LightState)
# ─────────────────────────────────────────────

@dataclass
class LightState:
    # Key light
    key_kelvin:        float = 5600.0
    key_intensity:     float = 1.0
    key_azimuth:       float = -45.0
    key_elevation:     float = 35.0
    key_softness:      float = 0.3
    key_shadow_den:    float = 0.8
    key_shadow_sharp:  float = 0.7

    # Fill light
    fill_kelvin:       float = 6200.0
    fill_intensity:    float = 0.35
    fill_azimuth:      float = 60.0
    fill_elevation:    float = 20.0
    fill_softness:     float = 0.9

    # Rim
    rim_intensity:     float = 0.6
    rim_kelvin:        float = 5600.0
    rim_width:         float = 0.15
    rim_always_on:     bool  = True

    # Ambient
    ambient_intensity: float = 0.25
    ambient_color:     List[float] = field(default_factory=lambda: [0.12, 0.13, 0.18])

    # Color grade
    shadow_hue:        List[float] = field(default_factory=lambda: [0.08, 0.10, 0.18])
    highlight_hue:     List[float] = field(default_factory=lambda: [1.0, 0.96, 0.88])
    midtone_tint:      List[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    saturation:        float = 1.0
    contrast:          float = 1.0
    exposure:          float = 0.0

    # Volumetrics
    fog_density:       float = 0.0
    fog_color:         List[float] = field(default_factory=lambda: [0.6, 0.65, 0.75])
    fog_height:        float = 0.3
    god_ray_intensity: float = 0.0
    god_ray_angle:     float = -45.0
    god_ray_color:     List[float] = field(default_factory=lambda: [1.0, 0.98, 0.90])

    # Glow
    bloom_threshold:   float = 0.85
    bloom_intensity:   float = 0.2
    bloom_radius:      float = 0.4
    emissive_scale:    float = 1.0

    # Film/lens
    grain_intensity:   float = 0.0
    grain_size:        float = 1.0
    halation_radius:   float = 0.0
    halation_color:    List[float] = field(default_factory=lambda: [1.0, 0.3, 0.1])
    vignette:          float = 0.0
    vignette_color:    List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    lens_distortion:   float = 0.0
    chromatic_ab:      float = 0.0
    dof_strength:      float = 0.0
    dof_focal_z:       float = 0.5

    # Temporal
    simulated_fps:     int   = 0
    motion_blur:       float = 0.0
    gate_flicker:      float = 0.0

    # Strobe
    strobe_enabled:    bool  = False
    strobe_freq:       float = 4.0
    strobe_duty:       float = 0.2
    strobe_color:      List[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    flash_color:       List[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    flash_decay:       float = 0.1

    # Audio reactive
    audio_reactive:      bool  = False
    audio_band:          str   = 'all'
    audio_intensity_mod: float = 0.3
    audio_color_mod:     float = 0.0
    audio_beat_flash:    bool  = False

    # 2.5D layer
    layer_light_wrap:  float = 0.0
    sprite_rim_force:  bool  = False
    z_parallax_light:  bool  = True

    def lerp(self, other: 'LightState', t: float) -> 'LightState':
        """Interpolate between two states."""
        result = LightState()
        for f in self.__dataclass_fields__:
            a = getattr(self, f)
            b = getattr(other, f)
            if isinstance(a, float) and isinstance(b, float):
                setattr(result, f, a + (b - a) * t)
            elif isinstance(a, list) and isinstance(b, list):
                setattr(result, f, [ai + (bi - ai) * t for ai, bi in zip(a, b)])
            else:
                setattr(result, f, b if t >= 0.5 else a)
        return result

    def to_js_camel(self) -> Dict:
        """Convert to camelCase dict for JS frontend consumption."""
        def to_camel(s): 
            parts = s.split('_')
            return parts[0] + ''.join(p.capitalize() for p in parts[1:])
        return {to_camel(k): v for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: Dict) -> 'LightState':
        # Accept both snake_case and camelCase
        def to_snake(s):
            import re
            return re.sub(r'(?<!^)(?=[A-Z])', '_', s).lower()
        normalized = {to_snake(k): v for k, v in d.items()}
        valid = {k: v for k, v in normalized.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


# ─────────────────────────────────────────────
#  PRESET LIBRARY  (Python mirror)
# ─────────────────────────────────────────────

def _make_presets() -> Dict[str, LightState]:
    return {
        "STUDIO_NEUTRAL": LightState(),

        "HITCHCOCK": LightState(
            key_kelvin=3200, key_intensity=1.6, key_azimuth=-70, key_elevation=25,
            key_softness=0.05, key_shadow_den=0.98, key_shadow_sharp=0.98,
            fill_intensity=0.05, ambient_intensity=0.08,
            shadow_hue=[0.03, 0.03, 0.08],
            contrast=1.5, saturation=0.7,
            vignette=0.4, grain_intensity=0.06, grain_size=0.8,
        ),

        "SPIELBERG": LightState(
            key_kelvin=4800, key_intensity=0.9, key_azimuth=180, key_elevation=10,
            key_softness=0.7,
            fill_intensity=0.8, fill_kelvin=5800,
            rim_intensity=2.5, rim_kelvin=4200,
            ambient_intensity=0.45,
            bloom_intensity=0.6, bloom_radius=0.8, bloom_threshold=0.7,
            god_ray_intensity=0.3, god_ray_angle=180,
            shadow_hue=[0.10, 0.12, 0.20],
            highlight_hue=[1.02, 0.98, 0.92],
            contrast=0.9, saturation=1.15,
            layer_light_wrap=0.5, sprite_rim_force=True,
        ),

        "NOLAN": LightState(
            key_kelvin=5800, key_intensity=1.1, key_azimuth=-30, key_elevation=40,
            key_softness=0.45, key_shadow_den=0.85, key_shadow_sharp=0.6,
            fill_intensity=0.4, ambient_intensity=0.3,
            shadow_hue=[0.08, 0.09, 0.15],
            contrast=1.1, saturation=1.0,
            dof_strength=0.3, dof_focal_z=0.4,
            grain_intensity=0.02,
        ),

        "FINCHER": LightState(
            key_kelvin=4000, key_intensity=0.85, key_azimuth=-20, key_elevation=60,
            key_softness=0.3, key_shadow_den=0.9,
            fill_intensity=0.15, fill_kelvin=4200,
            ambient_intensity=0.12,
            shadow_hue=[0.08, 0.12, 0.06],
            midtone_tint=[0.88, 0.92, 0.78],
            saturation=0.8, contrast=1.2,
            grain_intensity=0.04, vignette=0.35,
        ),

        "RIDLEY_SCOTT": LightState(
            key_kelvin=3000, key_intensity=0.5, key_azimuth=-90, key_elevation=5,
            key_softness=0.1, key_shadow_den=0.95,
            fill_intensity=0.0,
            ambient_intensity=0.4, ambient_color=[0.0, 0.02, 0.12],
            shadow_hue=[0.0, 0.0, 0.12],
            midtone_tint=[0.80, 0.72, 0.62],
            fog_density=0.25, fog_color=[0.06, 0.04, 0.18],
            bloom_intensity=0.8, bloom_radius=0.6, bloom_threshold=0.5,
            emissive_scale=2.0,
            saturation=1.3, contrast=1.4,
            vignette=0.5, chromatic_ab=0.8,
        ),

        "MICHAEL_BAY": LightState(
            key_kelvin=3400, key_intensity=1.8, key_azimuth=-120, key_elevation=8,
            key_softness=0.2, key_shadow_den=0.7,
            fill_intensity=0.6, fill_kelvin=8000,
            rim_intensity=1.8, rim_kelvin=3000,
            shadow_hue=[0.02, 0.12, 0.18],
            midtone_tint=[1.1, 0.95, 0.7],
            saturation=1.5, contrast=1.3,
            bloom_intensity=0.7, bloom_radius=0.9, bloom_threshold=0.6,
            lens_distortion=-0.05,
            god_ray_intensity=0.4, god_ray_angle=-120,
            layer_light_wrap=0.4,
        ),

        "DEL_TORO": LightState(
            key_kelvin=3200, key_intensity=0.9, key_azimuth=-45, key_elevation=20,
            key_softness=0.5, key_shadow_den=0.88,
            fill_intensity=0.5, fill_kelvin=8500,
            ambient_intensity=0.25, ambient_color=[0.04, 0.06, 0.22],
            shadow_hue=[0.04, 0.06, 0.22],
            midtone_tint=[0.95, 0.82, 0.62],
            saturation=1.2, contrast=1.15,
            fog_density=0.15, fog_color=[0.05, 0.05, 0.18],
            bloom_intensity=0.4, vignette=0.3,
        ),

        "GHIBLI": LightState(
            key_kelvin=5200, key_intensity=1.0, key_azimuth=-20, key_elevation=45,
            key_softness=0.85,
            fill_intensity=0.7, fill_kelvin=6500,
            ambient_intensity=0.55,
            shadow_hue=[0.15, 0.10, 0.22],
            highlight_hue=[1.02, 1.00, 0.95],
            saturation=0.9, contrast=0.85,
            bloom_intensity=0.15,
            layer_light_wrap=0.7, sprite_rim_force=False,
        ),

        "PIXAR": LightState(
            key_kelvin=5600, key_intensity=1.1, key_azimuth=-35, key_elevation=40,
            key_softness=0.6, key_shadow_den=0.75, key_shadow_sharp=0.5,
            fill_intensity=0.55, fill_kelvin=6000,
            rim_intensity=0.8, rim_kelvin=5800,
            ambient_intensity=0.4,
            saturation=1.05,
            bloom_intensity=0.2, bloom_threshold=0.88,
            layer_light_wrap=0.3, sprite_rim_force=True,
        ),

        "AKIRA_NEON": LightState(
            key_kelvin=4000, key_intensity=0.3, key_azimuth=0, key_elevation=80,
            key_softness=0.4,
            fill_intensity=0.0,
            ambient_intensity=0.05, ambient_color=[0.0, 0.0, 0.08],
            emissive_scale=3.5,
            bloom_intensity=2.0, bloom_radius=0.8, bloom_threshold=0.2,
            saturation=2.0, contrast=1.6,
            chromatic_ab=1.5,
            fog_density=0.3, fog_color=[0.02, 0.0, 0.08],
            motion_blur=0.6, vignette=0.4,
        ),

        "BATMAN_TAS": LightState(
            key_kelvin=3000, key_intensity=1.4, key_azimuth=-60, key_elevation=70,
            key_softness=0.05, key_shadow_den=1.0, key_shadow_sharp=1.0,
            fill_intensity=0.02,
            ambient_intensity=0.03, ambient_color=[0.02, 0.03, 0.08],
            saturation=0.7, contrast=2.0,
            fog_density=0.4, fog_color=[0.04, 0.04, 0.06],
            god_ray_intensity=0.6, god_ray_angle=-60,
            vignette=0.6,
        ),

        "SPIDER_VERSE_NPR": LightState(
            key_kelvin=5600, key_intensity=1.4, key_azimuth=-45, key_elevation=50,
            key_softness=0.0, key_shadow_den=1.0, key_shadow_sharp=1.0,
            fill_intensity=0.0, ambient_intensity=0.5,
            saturation=1.6, contrast=1.5,
            chromatic_ab=2.0, emissive_scale=1.5,
        ),

        "NOIR": LightState(
            key_kelvin=3800, key_intensity=1.8, key_azimuth=-50, key_elevation=40,
            key_softness=0.0, key_shadow_den=1.0, key_shadow_sharp=1.0,
            fill_intensity=0.0, ambient_intensity=0.04,
            saturation=0.0, contrast=2.5,
            vignette=0.5, grain_intensity=0.1, grain_size=0.9,
            simulated_fps=24,
        ),

        "FANTASY_WARM": LightState(
            key_kelvin=3500, key_intensity=1.0, key_azimuth=-30, key_elevation=20,
            key_softness=0.8,
            fill_intensity=0.6, fill_kelvin=4000,
            rim_intensity=1.2, rim_kelvin=3200,
            ambient_intensity=0.5, ambient_color=[0.18, 0.12, 0.06],
            emissive_scale=2.0,
            bloom_intensity=0.8, bloom_radius=0.9, bloom_threshold=0.5,
            fog_density=0.12, god_ray_intensity=0.3,
            saturation=1.2, layer_light_wrap=0.6, sprite_rim_force=True,
        ),

        "CANDLELIGHT": LightState(
            key_kelvin=1900, key_intensity=0.9, key_azimuth=0, key_elevation=-10,
            key_softness=0.3, key_shadow_den=0.9,
            fill_intensity=0.0,
            ambient_intensity=0.05, ambient_color=[0.08, 0.04, 0.01],
            emissive_scale=1.2,
            bloom_intensity=0.4, bloom_threshold=0.5,
            fog_density=0.05,
            saturation=0.9, contrast=1.3,
            vignette=0.6, gate_flicker=0.15, grain_intensity=0.04,
        ),

        "PSYCHEDELIC": LightState(
            key_kelvin=5600, key_intensity=1.0,
            fill_intensity=0.8, ambient_intensity=0.8,
            saturation=2.0, contrast=1.2,
            bloom_intensity=2.0, bloom_radius=1.5, bloom_threshold=0.1,
            emissive_scale=3.0,
            chromatic_ab=3.0,
            audio_reactive=True, audio_band='all', audio_color_mod=1.0,
            audio_intensity_mod=0.5,
            gate_flicker=0.2,
        ),

        "RAVE_STROBE": LightState(
            key_intensity=0.0, fill_intensity=0.0, ambient_intensity=0.0,
            emissive_scale=2.5,
            bloom_intensity=1.5, bloom_radius=0.7, bloom_threshold=0.2,
            strobe_enabled=True, strobe_freq=6.0, strobe_duty=0.15,
            strobe_color=[1, 1, 1],
            audio_reactive=True, audio_band='bass', audio_intensity_mod=1.0,
            audio_beat_flash=True,
            saturation=1.8, contrast=1.5,
            chromatic_ab=1.0, motion_blur=0.4, vignette=0.3,
        ),

        "HORROR": LightState(
            key_kelvin=3200, key_intensity=0.9, key_azimuth=0, key_elevation=-30,
            key_softness=0.1, key_shadow_den=0.95, key_shadow_sharp=0.9,
            fill_intensity=0.05,
            ambient_intensity=0.08, ambient_color=[0.06, 0.04, 0.0],
            saturation=0.7, contrast=1.5,
            vignette=0.55, grain_intensity=0.08, gate_flicker=0.06,
        ),

        "ROM_COM_GOLDEN": LightState(
            key_kelvin=3800, key_intensity=1.0, key_azimuth=-100, key_elevation=12,
            key_softness=0.7,
            fill_intensity=0.6, fill_kelvin=5000,
            rim_intensity=1.0, rim_kelvin=3600,
            ambient_intensity=0.45,
            bloom_intensity=0.5, bloom_radius=1.0, bloom_threshold=0.65,
            saturation=1.15, contrast=0.95,
            god_ray_intensity=0.2, god_ray_angle=-100,
            layer_light_wrap=0.5,
            halation_radius=0.2, halation_color=[1.0, 0.8, 0.5],
        ),

        "MARVEL_ACTION": LightState(
            key_kelvin=5600, key_intensity=1.3, key_azimuth=-40, key_elevation=35,
            key_softness=0.4, key_shadow_den=0.7,
            fill_intensity=0.5, fill_kelvin=6000,
            rim_intensity=1.5, rim_kelvin=7000,
            ambient_intensity=0.4,
            saturation=1.3, contrast=1.1,
            bloom_intensity=0.5, bloom_radius=0.7, bloom_threshold=0.75,
            emissive_scale=1.8, layer_light_wrap=0.4, sprite_rim_force=True,
        ),

        "GOLDEN_HOUR": LightState(
            key_kelvin=3200, key_intensity=1.1, key_azimuth=-110, key_elevation=5,
            key_softness=0.55, key_shadow_den=0.75,
            fill_intensity=0.4, fill_kelvin=7500,
            rim_intensity=2.0, rim_kelvin=3000,
            god_ray_intensity=0.5, god_ray_angle=-110,
            god_ray_color=[1.0, 0.85, 0.6],
            bloom_intensity=0.7, bloom_radius=1.0, bloom_threshold=0.55,
            saturation=1.25, contrast=1.05,
            halation_radius=0.4, halation_color=[1.0, 0.7, 0.3],
            layer_light_wrap=0.7,
        ),

        "NEWS_FLAT": LightState(
            key_kelvin=6500, key_intensity=1.0, key_azimuth=0, key_elevation=30,
            key_softness=0.95,
            fill_intensity=0.9, fill_kelvin=6500,
            ambient_intensity=0.6,
            key_shadow_den=0.1,
            rim_intensity=0.3, rim_always_on=True,
            saturation=0.95, bloom_intensity=0.0, grain_intensity=0.0,
        ),

        "MAGIC_REALISM": LightState(
            key_kelvin=4800, key_intensity=0.9, key_azimuth=10, key_elevation=55,
            key_softness=0.95,
            fill_intensity=0.8, fill_kelvin=6200,
            ambient_intensity=0.6,
            bloom_intensity=0.5, bloom_radius=1.0, bloom_threshold=0.6,
            emissive_scale=1.5,
            saturation=1.1, contrast=0.85,
            halation_radius=0.3, halation_color=[1.0, 0.85, 0.6],
            layer_light_wrap=0.8,
        ),

        # ── Realism & Documentary ──────────────────────────────────────────
        "GREENGRASS": LightState(
            key_kelvin=5600, key_intensity=0.8, key_azimuth=10, key_elevation=50,
            key_softness=0.7,
            fill_intensity=0.6, fill_kelvin=5800,
            ambient_intensity=0.5,
            saturation=0.75, contrast=1.05,
            shadow_hue=[0.1, 0.12, 0.12],
            grain_intensity=0.12, grain_size=1.2,
            simulated_fps=30, motion_blur=0.3,
            vignette=0.1,
        ),

        "ROTOSCOPE": LightState(
            key_kelvin=5200, key_intensity=0.9, key_azimuth=-20, key_elevation=35,
            key_softness=0.6,
            fill_intensity=0.6,
            saturation=0.85, contrast=0.9,
            grain_intensity=0.03, gate_flicker=0.08,
        ),

        "TARANTINO": LightState(
            key_kelvin=3600, key_intensity=1.3, key_azimuth=-30, key_elevation=30,
            key_softness=0.15, key_shadow_den=0.85, key_shadow_sharp=0.8,
            fill_intensity=0.5, fill_kelvin=3800,
            ambient_intensity=0.3,
            shadow_hue=[0.12, 0.08, 0.02],
            midtone_tint=[1.08, 0.96, 0.78],
            saturation=1.4, contrast=1.25,
            grain_intensity=0.08, grain_size=1.5,
            vignette=0.25, simulated_fps=24,
        ),

        # ── Painterly & Artistic ────────────────────────────────────────────
        "IMPRESSIONIST": LightState(
            key_kelvin=5500, key_intensity=0.7, key_azimuth=20, key_elevation=65,
            key_softness=1.0,
            fill_intensity=0.9, fill_softness=1.0,
            ambient_intensity=0.7,
            key_shadow_den=0.1,
            saturation=1.0, contrast=0.75,
            bloom_intensity=0.6, bloom_radius=1.5, bloom_threshold=0.4,
            dof_strength=0.2, layer_light_wrap=0.9,
        ),

        # ── Studio & Commercial ─────────────────────────────────────────────
        "STUDIO_BEAUTY": LightState(
            key_kelvin=5600, key_intensity=1.2, key_azimuth=0, key_elevation=15,
            key_softness=0.95, key_shadow_den=0.2,
            fill_intensity=0.9, fill_elevation=-10,
            rim_intensity=0.4, vignette=0.15,
            saturation=1.05, bloom_intensity=0.1,
        ),

        "PRODUCT_BEAUTY": LightState(
            key_kelvin=5600, key_intensity=1.0, key_azimuth=90, key_elevation=20,
            key_softness=1.0,
            fill_intensity=1.0, fill_azimuth=-90,
            ambient_intensity=0.8,
            key_shadow_den=0.0,
            rim_intensity=1.2, rim_always_on=True,
            saturation=1.05, bloom_intensity=0.3, bloom_threshold=0.8,
        ),

        "SPORTS_FLOODLIGHT": LightState(
            key_kelvin=5600, key_intensity=1.4, key_azimuth=0, key_elevation=80,
            key_softness=0.2, key_shadow_den=0.6, key_shadow_sharp=0.7,
            fill_intensity=0.6, fill_azimuth=90, fill_elevation=45,
            rim_intensity=0.4,
            ambient_intensity=0.5,
            saturation=1.1, contrast=1.15, bloom_intensity=0.1,
        ),

        # ── Atmosphere & Environment ────────────────────────────────────────
        "BLUE_HOUR": LightState(
            key_kelvin=8000, key_intensity=0.4, key_azimuth=0, key_elevation=-5,
            key_softness=1.0,
            fill_intensity=0.5, fill_kelvin=9000,
            ambient_intensity=0.65, ambient_color=[0.08, 0.10, 0.25],
            key_shadow_den=0.15,
            rim_intensity=0.8, rim_kelvin=8500,
            saturation=0.9, contrast=0.85,
            bloom_intensity=0.3,
            fog_density=0.1, fog_color=[0.08, 0.10, 0.22],
        ),

        "UNDERWATER": LightState(
            key_kelvin=8500, key_intensity=0.6, key_azimuth=0, key_elevation=80,
            key_softness=0.9,
            fill_intensity=0.4, fill_kelvin=9000,
            ambient_intensity=0.55, ambient_color=[0.04, 0.10, 0.22],
            fog_density=0.4, fog_color=[0.04, 0.12, 0.28],
            bloom_intensity=0.3, saturation=0.85, contrast=0.9,
            key_shadow_den=0.3,
        ),

        # ── High-Energy & Stylised ──────────────────────────────────────────
        "DBZ_AURA": LightState(
            key_intensity=0.3, fill_intensity=0.1, ambient_intensity=0.2,
            emissive_scale=4.0,
            bloom_intensity=1.5, bloom_radius=1.2, bloom_threshold=0.3,
            rim_intensity=3.0, rim_always_on=True,
            sprite_rim_force=True,
            saturation=1.6, contrast=1.3,
            audio_beat_flash=True,
        ),

        "FREEZE_DREAM": LightState(
            key_kelvin=7000, key_intensity=2.5, key_azimuth=0, key_elevation=90,
            key_softness=0.0, key_shadow_den=0.4,
            fill_intensity=1.5, ambient_intensity=1.0,
            bloom_intensity=3.0, bloom_radius=2.0, bloom_threshold=0.0,
            saturation=0.4, contrast=2.0, exposure=1.5,
            chromatic_ab=2.0, gate_flicker=0.4,
            strobe_enabled=True, strobe_freq=12.0, strobe_duty=0.08,
            motion_blur=0.8,
        ),

        # ── PubCast Native Identity ────────────────────────────────────────
        #
        # "This shadow is a secret."
        #
        # The platform's own voice. Not a genre reference. Not inherited.
        #
        # Warm key that feels safe — but the shadow density is high and its
        # effective direction is slightly displaced from where the key says
        # it should fall. The Flub not as correction but as authorship.
        # The gap between the warmth you expect and the coolness you feel
        # IS the meaning.
        #
        # Inspired by Edward Hopper's interior light: present, directional,
        # warm — and yet the room holds something withheld. The shadow
        # doesn't announce itself. That's what makes it true.
        #
        # Per-layer intent:
        #   background  — run this at full strength
        #   avatar      — warm key, force rim so nothing fully disappears
        #   foreground  — layer_light_wrap pulls bg warmth onto fg sprites,
        #                 but the cool ambient keeps the gap alive
        #
        "PUBCAST_SIGNATURE": LightState(
            # Key: warm, present, inviting — but not golden-hour dramatic
            key_kelvin=3900,
            key_intensity=0.88,
            key_azimuth=-38,        # slightly off-center — not frontal, not dramatic
            key_elevation=28,       # low enough to cast, not so low it's horror
            key_softness=0.55,      # soft enough to feel safe
            key_shadow_den=0.82,    # shadow is real — it earns its presence
            key_shadow_sharp=0.45,  # but not a razor — it has weight, not violence

            # Fill: cooler than the key by a deliberate gap
            # This is the secret: the fill is 2400K cooler than the key.
            # Physically plausible. Emotionally wrong in the best way.
            fill_kelvin=5400,       # cool-neutral against the warm key
            fill_intensity=0.28,    # present but not compensating
            fill_azimuth=55,
            fill_elevation=18,
            fill_softness=0.85,

            # Rim: always on, quiet — prevents anything from fully vanishing
            rim_intensity=0.45,
            rim_kelvin=6200,        # cooler rim reinforces the shadow-secret gap
            rim_width=0.12,
            rim_always_on=True,     # Flub: sprite anchor, no exceptions

            # Ambient: cool-blue bias — the room remembers something
            ambient_intensity=0.22,
            ambient_color=[0.10, 0.11, 0.20],

            # Color grade: the shadow is blue, the highlight is amber.
            # They do not resolve. That unresolved tension is the aesthetic.
            shadow_hue=[0.06, 0.08, 0.22],      # Hopper blue-shadow
            highlight_hue=[1.02, 0.96, 0.84],   # warm amber highlight
            midtone_tint=[0.96, 0.95, 0.98],    # very slightly cool midtones
                                                 # — cooler than the key earns

            saturation=0.92,        # slightly desaturated — restraint, not style
            contrast=1.08,          # just enough to give the shadow weight
            exposure=0.0,

            # Atmosphere: fog so subtle you feel it, not see it
            fog_density=0.06,
            fog_color=[0.10, 0.11, 0.20],
            fog_height=0.15,

            # No god rays — this light doesn't announce itself
            god_ray_intensity=0.0,

            # Bloom: minimal — no declarations
            bloom_threshold=0.88,
            bloom_intensity=0.12,
            bloom_radius=0.5,
            emissive_scale=1.0,

            # Film: just enough grain to feel like it was captured, not rendered
            grain_intensity=0.018,
            grain_size=0.9,

            # No halation — halation is warmth boasting, this doesn't boast
            halation_radius=0.0,

            # Vignette: present, dark, quiet
            vignette=0.22,
            vignette_color=[0.0, 0.0, 0.04],    # vignette has the faintest blue

            # Lens: clean — no chromatic aberration, no distortion
            # The image should feel like someone was paying attention, not like
            # equipment was present
            chromatic_ab=0.0,
            lens_distortion=0.0,
            dof_strength=0.0,

            # Temporal: 24fps feel without simulation artifacts
            simulated_fps=0,
            gate_flicker=0.0,

            # 2.5D layer behavior:
            # Light wraps from bg onto sprites — they belong to the same room
            # But only partially — they're also slightly apart from it
            layer_light_wrap=0.32,
            sprite_rim_force=True,   # nothing disappears
            z_parallax_light=True,   # depth reads through shadow parallax
        ),
    }


LIGHT_PRESETS: Dict[str, LightState] = _make_presets()


# ─────────────────────────────────────────────
#  LIGHTING RESOLVER  (Python)
# ─────────────────────────────────────────────

class LightingResolver:
    MOOD_KELVIN_SHIFT = {
        'calm': 0, 'happy': 200, 'excited': -300, 'sad': 400, 'angry': -500,
    }

    def resolve(
        self,
        preset_name: str = 'STUDIO_NEUTRAL',
        manual_overrides: Dict = None,
        audio_data: Dict = None,
        emotion_state: Dict = None,
        timeline_event: Dict = None,
    ) -> LightState:
        base = LIGHT_PRESETS.get(preset_name, LIGHT_PRESETS['STUDIO_NEUTRAL'])
        state = LightState.from_dict(asdict(base))

        # Audio reactivity
        if state.audio_reactive and audio_data:
            band  = audio_data.get(state.audio_band, audio_data.get('all', 0))
            state.key_intensity  = state.key_intensity * (1 + band * state.audio_intensity_mod)
            state.bloom_intensity = min(3.0, state.bloom_intensity + band * 0.5)
            state.emissive_scale  = state.emissive_scale * (1 + band * 0.3)

            if state.audio_beat_flash and audio_data.get('beat'):
                state.flash_color = state.strobe_color[:]
                state.flash_decay  = 0.08

        # Emotion color temp shift
        if emotion_state:
            mood  = emotion_state.get('mood', 'calm')
            intens = emotion_state.get('intensity', 1.0)
            shift = self.MOOD_KELVIN_SHIFT.get(mood, 0)
            state.key_kelvin += shift * intens
            state.saturation += intens * 0.1

        # Timeline events
        if timeline_event:
            evt = timeline_event.get('type')
            if evt == 'flash':
                state.flash_color = timeline_event.get('color', [1, 1, 1])
                state.flash_decay  = timeline_event.get('decay', 0.1)
                state.exposure     = timeline_event.get('stops', 1.5)
            elif evt == 'cut_darkness':
                state.exposure = -3.0

        # Manual overrides (highest priority)
        if manual_overrides:
            for k, v in manual_overrides.items():
                if hasattr(state, k):
                    setattr(state, k, v)

        return state


# ─────────────────────────────────────────────
#  LIGHTING ENGINE  (Python)
# ─────────────────────────────────────────────

class LightingEngine:
    LAYERS = ('background', 'midground', 'foreground', 'avatar', 'ui')

    def __init__(self):
        self.resolver = LightingResolver()
        self._presets: Dict[str, str] = {l: 'STUDIO_NEUTRAL' for l in self.LAYERS}
        self._states:  Dict[str, LightState] = {
            l: LightState() for l in self.LAYERS
        }
        self._transitions: Dict[str, Dict] = {}
        self._start_time = time.time()

    def _t(self) -> float:
        return time.time() - self._start_time

    def set_preset(
        self,
        preset_name: str,
        layer: Optional[str] = None,
        transition_seconds: float = 0.0,
    ):
        layers = [layer] if layer else list(self.LAYERS)
        for l in layers:
            if l not in self.LAYERS:
                continue
            if transition_seconds > 0:
                self._transitions[l] = {
                    'from': LightState.from_dict(asdict(self._states[l])),
                    'to':   self.resolver.resolve(preset_name),
                    'start': self._t(),
                    'dur':   transition_seconds,
                    'target_name': preset_name,
                }
            else:
                self._presets[l] = preset_name
                self._states[l]  = self.resolver.resolve(preset_name)

    def mix_presets(
        self,
        preset_a: str,
        preset_b: str,
        blend: float,
        layer: Optional[str] = None,
    ):
        a = LIGHT_PRESETS.get(preset_a, LIGHT_PRESETS['STUDIO_NEUTRAL'])
        b = LIGHT_PRESETS.get(preset_b, LIGHT_PRESETS['STUDIO_NEUTRAL'])
        mixed = a.lerp(b, blend)
        layers = [layer] if layer else list(self.LAYERS)
        for l in layers:
            self._states[l] = mixed
            self._presets[l] = f'mix:{preset_a}:{preset_b}:{blend:.2f}'

    def update(
        self,
        audio_data: Dict = None,
        emotion_state: Dict = None,
    ):
        t = self._t()

        # Advance transitions
        for layer, trans in list(self._transitions.items()):
            elapsed  = t - trans['start']
            progress = min(1.0, elapsed / trans['dur'])
            eased    = 1 - (1 - progress) ** 3  # ease-out cubic
            self._states[layer] = trans['from'].lerp(trans['to'], eased)
            if progress >= 1.0:
                self._presets[layer] = trans['target_name']
                del self._transitions[layer]

        # Re-resolve reactive layers
        for layer, preset in self._presets.items():
            if ':' in preset:
                continue  # custom mix, skip re-resolve
            state = self._states[layer]
            if state.audio_reactive or emotion_state:
                self._states[layer] = self.resolver.resolve(
                    preset_name=preset,
                    audio_data=audio_data,
                    emotion_state=emotion_state,
                )

    def get_state(self, layer: str = 'avatar') -> LightState:
        return self._states.get(layer, LightState())

    def serialize(self) -> Dict:
        return {
            'timestamp': time.time(),
            'layers': {l: asdict(s) for l, s in self._states.items()},
            'presets': dict(self._presets),
        }

    def deserialize(self, data: Dict):
        for layer, state_dict in data.get('layers', {}).items():
            if layer in self.LAYERS:
                self._states[layer] = LightState.from_dict(state_dict)
        for layer, preset in data.get('presets', {}).items():
            if layer in self.LAYERS:
                self._presets[layer] = preset


# ─────────────────────────────────────────────
#  HUB.PY INTEGRATION PATCH
# ─────────────────────────────────────────────

class LightingHubPatch:
    """
    Drop this into your existing hub.py WebSocket message handler.

    Usage in hub.py:
        from pubcast_lighting_backend import LightingEngine, LightingHubPatch

        # In your app startup:
        app.state.lighting = LightingEngine()
        lighting_hub = LightingHubPatch(app.state.lighting)

        # In handle_message, BEFORE your existing handlers:
        handled = await lighting_hub.handle(ws, room, data, broadcast_fn)
        if handled:
            return
    """

    def __init__(self, engine: LightingEngine, hub=None):
        self.engine = engine
        self._hub = hub

    def handle_message(self, data: Dict) -> None:
        """Synchronous convenience used by main.py WebSocket loop.

        Applies lighting state changes locally.  Because this is called
        inside the synchronous parse-check in the WS handler, we apply
        the engine mutation immediately and schedule the broadcast on
        the running loop so the caller can stay non-async.
        """
        import asyncio

        msg_type = data.get("type", "")

        if msg_type == "set_lighting_preset" or msg_type == "lighting_set_preset":
            self.engine.set_preset(
                preset_name=data.get("preset", "STUDIO_NEUTRAL"),
                layer=data.get("layer"),
                transition_seconds=data.get("transition", 0.5),
            )
        elif msg_type == "lighting_mix_presets" or msg_type == "mix_lighting_presets":
            self.engine.mix_presets(
                preset_a=data.get("preset_a", "STUDIO_NEUTRAL"),
                preset_b=data.get("preset_b", "SPIELBERG"),
                blend=float(data.get("blend", 0.5)),
                layer=data.get("layer"),
            )
        elif msg_type == "lighting_set_param" or msg_type == "set_lighting_param":
            layer = data.get("layer", "avatar")
            state = self.engine.get_state(layer)
            param = data.get("param")
            value = data.get("value")
            if param and hasattr(state, param):
                setattr(state, param, value)
        elif msg_type == "lighting_flash":
            pass  # flash is broadcast-only, handled below
        else:
            return

        # Fire-and-forget broadcast of new state to all rooms
        if self._hub is not None:
            event = {"type": "lighting_state", "payload": self.engine.serialize()}
            if msg_type == "lighting_flash":
                event = {
                    "type": "lighting_flash",
                    "color": data.get("color", [1, 1, 1]),
                    "decay": data.get("decay", 0.1),
                    "stops": data.get("stops", 1.5),
                }
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._hub.broadcast_system_event(event))
            except RuntimeError:
                pass

    async def handle(
        self,
        ws,
        room: str,
        data: Dict,
        broadcast_fn,  # async fn(room, payload_dict)
    ) -> bool:
        """Returns True if message was consumed."""
        msg_type = data.get('type', '')

        if msg_type == 'set_lighting_preset':
            self.engine.set_preset(
                preset_name=data.get('preset', 'STUDIO_NEUTRAL'),
                layer=data.get('layer'),
                transition_seconds=data.get('transition', 0.5),
            )
            await broadcast_fn(room, {
                'type':   'lighting_state',
                'payload': self.engine.serialize(),
            })
            return True

        elif msg_type == 'mix_lighting_presets':
            self.engine.mix_presets(
                preset_a=data.get('preset_a', 'STUDIO_NEUTRAL'),
                preset_b=data.get('preset_b', 'SPIELBERG'),
                blend=float(data.get('blend', 0.5)),
                layer=data.get('layer'),
            )
            await broadcast_fn(room, {
                'type':   'lighting_state',
                'payload': self.engine.serialize(),
            })
            return True

        elif msg_type == 'set_lighting_param':
            # Fine-grained single-param override
            layer = data.get('layer', 'avatar')
            state = self.engine.get_state(layer)
            param = data.get('param')
            value = data.get('value')
            if param and hasattr(state, param):
                setattr(state, param, value)
                await broadcast_fn(room, {
                    'type':   'lighting_param',
                    'layer':  layer,
                    'param':  param,
                    'value':  value,
                })
            return True

        elif msg_type == 'get_lighting_state':
            # Individual client requesting current state (e.g. late joiner)
            await ws.send_text(json.dumps({
                'type':   'lighting_state',
                'payload': self.engine.serialize(),
            }))
            return True

        elif msg_type == 'lighting_flash':
            # Broadcast a one-shot flash event
            await broadcast_fn(room, {
                'type':   'lighting_flash',
                'color':  data.get('color', [1, 1, 1]),
                'decay':  data.get('decay', 0.1),
                'stops':  data.get('stops', 1.5),
            })
            return True

        return False


# ─────────────────────────────────────────────
#  AUDIO-REACTIVE DRIVER  (optional)
# ─────────────────────────────────────────────

class AudioReactiveDriver:
    """
    Thin wrapper that takes raw FFT data from your audio pipeline
    and converts it to the audio_data dict the engine expects.

    Usage:
        driver = AudioReactiveDriver()
        # In your audio processing loop (e.g. from WebAudio API on client, 
        # forwarded over WebSocket):
        audio_data = driver.process(fft_array)
        engine.update(audio_data=audio_data)
    """

    def __init__(self, sample_rate: int = 44100, fft_size: int = 2048):
        self.sample_rate = sample_rate
        self.fft_size    = fft_size
        self._prev_energy = 0.0
        self._beat_threshold = 0.3

    def process(self, fft_magnitudes: List[float]) -> Dict[str, float]:
        n = len(fft_magnitudes)
        if n == 0:
            return {'bass': 0, 'mid': 0, 'high': 0, 'all': 0, 'beat': False}

        # Split into frequency bands
        bass_end  = int(n * 0.05)   # 0–5% = bass (sub + bass)
        mid_end   = int(n * 0.25)   # 5–25% = mid
        # high      = 25–100%

        bass  = sum(fft_magnitudes[:bass_end])  / max(1, bass_end)
        mid   = sum(fft_magnitudes[bass_end:mid_end]) / max(1, mid_end - bass_end)
        high  = sum(fft_magnitudes[mid_end:]) / max(1, n - mid_end)
        total = (bass + mid + high) / 3.0

        # Normalize to 0–1
        norm = max(bass, mid, high, 1e-6)
        bass_n  = min(1.0, bass  / norm)
        mid_n   = min(1.0, mid   / norm)
        high_n  = min(1.0, high  / norm)
        all_n   = min(1.0, total / norm)

        # Beat detection: energy spike in bass band
        beat = (bass_n - self._prev_energy) > self._beat_threshold
        self._prev_energy = bass_n * 0.7 + self._prev_energy * 0.3  # smooth

        return {
            'bass': bass_n,
            'mid':  mid_n,
            'high': high_n,
            'all':  all_n,
            'beat': beat,
        }


# ─────────────────────────────────────────────
#  CONVENIENCE — list all preset names
# ─────────────────────────────────────────────

def list_presets() -> List[str]:
    return sorted(LIGHT_PRESETS.keys())


if __name__ == '__main__':
    # Quick smoke test
    engine = LightingEngine()

    print("Available presets:")
    for name in list_presets():
        print(f"  {name}")

    print("\nSetting SPIELBERG on avatar layer with 1s transition...")
    engine.set_preset('SPIELBERG', layer='avatar', transition_seconds=1.0)

    print("Setting HITCHCOCK on background layer...")
    engine.set_preset('HITCHCOCK', layer='background')

    print("\nSerialized state:")
    state = engine.serialize()
    print(f"  Layers: {list(state['layers'].keys())}")
    print(f"  Avatar key Kelvin: {state['layers']['avatar']['key_kelvin']}")
    print(f"  Background key softness: {state['layers']['background']['key_softness']}")

    print("\nMixing SPIELBERG + FINCHER at 0.4 blend on foreground...")
    engine.mix_presets('SPIELBERG', 'FINCHER', 0.4, layer='foreground')
    fg = engine.get_state('foreground')
    print(f"  Foreground key Kelvin (interpolated): {fg.key_kelvin:.0f}")

    print("\nAll good.")
