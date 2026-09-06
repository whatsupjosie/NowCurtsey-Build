"""
modules/switchblade_governor.py — EVO Switchblade Governor
===========================================================
Copyright (c) 2024-2025 Rear View Foresight LLC
"Feic Mo Chroí — See My Heart"

The Switchblade is the semantic compute scheduler for the PubCast
distributed engine stack. It bridges the voice/emotion pipeline
with the render/resource pipeline.

WHAT IT DOES:
    The Switchblade reads the VDI report (what is emotionally happening
    right now) and emits a priority vector to the DistributedEngineNode.
    It tells the engines what to render, at what fidelity, and in what order —
    based on MEANING, not just load metrics.

    A traditional OS scheduler asks: "What is the CPU at?"
    The Switchblade asks: "Is this a close-up? Is this an identity moment?
    Is this character even in frame?"

    The answer to those questions determines resource allocation.

THE LANGUAGE:
    The Switchblade does not communicate in English.
    It emits compact JSON priority vectors.
    Fast. Dense. No grammar overhead.

    Example output:
    {
        "e3_sss": 1.0,       # Engine 3 subsurface scattering: full
        "e3_tex": 1.0,       # Engine 3 texture quality: full
        "e4_fid": 0.4,       # Engine 4 fidelity: 40% (crew preview)
        "bg_phys": 0,        # Background physics: off
        "c_pete_lod": 0,     # Pete LOD: highest (0=best)
        "c_repete_lod": 3,   # Re-Pete LOD: reduced (offscreen)
        "mode": "identity",  # Current voice mode
        "ts": 1234567890.123 # Timestamp
    }

INTEGRATION:
    Switchblade sits between:
        VDIEngine → Switchblade → DistributedEngineNode
                              ↘ CameraManager._check_auto_switch_rules()

Public API:
    SwitchbladeGovernor
        .tick(vdi_report: VDIReport, scene_state: SceneState) -> PriorityVector
        .apply(vector: PriorityVector, engine: DistributedEngineNode) -> None
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# SCENE STATE — what's actually happening on the floor right now
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SceneState:
    """
    Current state of the virtual production scene.
    Fed by the camera manager and character tracking system.
    """
    # ── Camera state ──────────────────────────────────────────────────────────
    program_camera:     str   = "cam_1"      # Currently live camera ID
    preview_camera:     str   = "cam_2"      # Next camera
    shot_type:          str   = "medium"     # close_up | medium | wide | extreme_close

    # ── Characters in frame ───────────────────────────────────────────────────
    # Characters currently visible in the program camera frustum
    characters_in_frame: List[str] = field(default_factory=list)
    # Primary character (closest to lens / most screen real estate)
    primary_character:   str   = "pete"
    # Characters completely offscreen
    characters_offscreen: List[str] = field(default_factory=list)

    # ── Scene complexity ──────────────────────────────────────────────────────
    active_effects:     List[str] = field(default_factory=list)  # fog, particles, etc.
    crowd_count:        int   = 0        # Number of crowd entities
    prop_count:         int   = 0        # Number of active props

    # ── Timing ────────────────────────────────────────────────────────────────
    timestamp:          float = field(default_factory=time.time)


# ─────────────────────────────────────────────────────────────────────────────
# PRIORITY VECTOR — the Switchblade's output language
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PriorityVector:
    """
    The compact command payload the Switchblade emits.
    This is what gets sent to engines — not English, not descriptions.
    Just numbers and flags.

    Consumed by:
        - DistributedEngineNode (render resource allocation)
        - CameraManager (auto-switch decisions)
        - AvatarRenderer (LOD and fidelity per character)
    """
    # ── Engine 3 (Program Camera) directives ─────────────────────────────────
    e3_sss:         float = 0.5    # Subsurface scattering intensity [0-1]
    e3_tex_quality: float = 0.5    # Texture quality [0=lowest, 1=4K]
    e3_shadow:      float = 0.5    # Ray-traced shadow quality [0-1]
    e3_target_fps:  int   = 30     # Target FPS for Engine 3

    # ── Engine 4 (Elastic Reserve) directives ────────────────────────────────
    e4_fidelity:    float = 0.5    # Preview fidelity [0-1]
    e4_assist:      bool  = False  # True = sacrifice preview to assist Engine 3

    # ── Background/environment directives ────────────────────────────────────
    bg_physics:     bool  = True   # Run background physics?
    bg_crowd_lod:   int   = 2      # Crowd LOD level [0=best, 4=skeleton only]
    bg_prop_shadow: bool  = False  # Cast shadows from background props?

    # ── Per-character LOD directives (keyed by character_id) ─────────────────
    # LOD levels: 0=full identity, 1=high, 2=medium, 3=low, 4=skeleton only
    character_lod:  Dict[str, int] = field(default_factory=dict)

    # ── Batch size directives ─────────────────────────────────────────────────
    voxel_batch_primary:   int = 2500   # Batch size for primary rendering
    voxel_batch_secondary: int = 1000   # Batch size for secondary nodes

    # ── Meta ──────────────────────────────────────────────────────────────────
    voice_mode:     str   = "mixed"
    vdi_score:      float = 0.5
    identity_moment: bool = False
    timestamp:      float = field(default_factory=time.time)

    def to_wire_format(self) -> dict:
        """
        Serialize to compact wire format for inter-engine communication.
        No English. Minimum bytes.
        """
        return {
            "e3_s": round(self.e3_sss, 2),
            "e3_t": round(self.e3_tex_quality, 2),
            "e3_sh": round(self.e3_shadow, 2),
            "e3_fps": self.e3_target_fps,
            "e4_f": round(self.e4_fidelity, 2),
            "e4_a": int(self.e4_assist),
            "bg_p": int(self.bg_physics),
            "bg_cl": self.bg_crowd_lod,
            "bg_ps": int(self.bg_prop_shadow),
            "c_lod": self.character_lod,
            "vb_p": self.voxel_batch_primary,
            "vb_s": self.voxel_batch_secondary,
            "mode": self.voice_mode,
            "vdi": round(self.vdi_score, 3),
            "id": int(self.identity_moment),
            "ts": self.timestamp,
        }

    def to_irm_adjustment(self) -> Dict[str, Any]:
        """
        Format as IRM actuator adjustment for the twin engine bridge.
        """
        return {
            "batch_size":    self.voxel_batch_primary,
            "quality_level": int(self.e3_tex_quality * 100),
            "emergency":     self.e4_assist,
        }


# ─────────────────────────────────────────────────────────────────────────────
# SWITCHBLADE GOVERNOR
# ─────────────────────────────────────────────────────────────────────────────

class SwitchbladeGovernor:
    """
    The semantic compute scheduler for PubCast's distributed engine stack.

    Reads VDI state (what is emotionally happening) and scene state
    (what is spatially happening) and emits priority vectors that tell
    the engine where to spend its cycles.

    This is how we get cinematic 30fps fidelity on a GTX 960M:
    we only render what matters, at the fidelity it deserves,
    at the moment it needs it.

    Core principle: Audio Never Sacrificed. Identity moments get everything.
    """

    def __init__(self):
        self._last_vector: Optional[PriorityVector] = None
        self._vector_history: List[PriorityVector] = []
        self._history_limit = 30  # 1 second at 30fps

        # Thresholds
        self.IDENTITY_THRESHOLD    = 0.80
        self.VOICE_DOM_THRESHOLD   = 0.55
        self.MIXED_THRESHOLD       = 0.30

        # LOD definitions by character state
        self.LOD_PROGRAM_IDENTITY  = 0   # Full: SSS, 4K, ray shadow
        self.LOD_PROGRAM_NORMAL    = 1   # High: good textures, baked shadow
        self.LOD_PREVIEW           = 2   # Medium: compressed textures
        self.LOD_STANDBY           = 3   # Low: diffuse only
        self.LOD_OFFSCREEN         = 4   # Skeleton only — just keep them alive

    def tick(
        self,
        vdi_report: "VDIReport",       # from vdi_engine.py
        scene_state: SceneState,
    ) -> PriorityVector:
        """
        Calculate and return a priority vector for this frame.
        Call this every frame (33ms at 30fps).
        """
        vector = PriorityVector(
            voice_mode    = vdi_report.voice_mode.value,
            vdi_score     = vdi_report.vdi_score,
            identity_moment = vdi_report.identity_moment,
            timestamp     = vdi_report.timestamp,
        )

        # ── Engine 3 (Program Camera) ─────────────────────────────────────────
        self._configure_engine3(vector, vdi_report, scene_state)

        # ── Engine 4 (Elastic Reserve) ────────────────────────────────────────
        self._configure_engine4(vector, vdi_report)

        # ── Background ────────────────────────────────────────────────────────
        self._configure_background(vector, vdi_report, scene_state)

        # ── Per-character LOD ─────────────────────────────────────────────────
        self._configure_character_lod(vector, vdi_report, scene_state)

        # ── Batch sizes ───────────────────────────────────────────────────────
        self._configure_batch_sizes(vector, vdi_report)

        self._last_vector = vector
        self._vector_history.append(vector)
        if len(self._vector_history) > self._history_limit:
            self._vector_history.pop(0)

        return vector

    def apply(
        self,
        vector: PriorityVector,
        engine: Any,  # DistributedEngineNode
    ) -> None:
        """
        Apply a priority vector to a DistributedEngineNode.
        Translates semantic render decisions into IRM adjustments.
        """
        try:
            irm_adj = vector.to_irm_adjustment()

            # Adjust batch size via IRM actuator
            if hasattr(engine, 'irm') and engine.irm:
                # Directly set batch size based on Switchblade decision
                engine.irm.actuator.current_batch_size = irm_adj["batch_size"]
                engine.irm.actuator.emergency_mode = irm_adj["emergency"]

            # Set quality level
            if hasattr(engine, 'config'):
                engine.config.quality_level = irm_adj["quality_level"]

            # E4 assist mode
            if vector.e4_assist and hasattr(engine, '_transition_to_state'):
                # This triggers the distributed engine's ELEVATED state
                logger.info("[Switchblade] E4 assist engaged — sacrificing preview")

            logger.debug(
                f"[Switchblade] Applied: mode={vector.voice_mode} "
                f"vdi={vector.vdi_score:.3f} "
                f"e3_sss={vector.e3_sss:.2f} "
                f"e4_assist={vector.e4_assist}"
            )

        except Exception as e:
            logger.error(f"[Switchblade] Apply failed: {e}")

    def get_last_vector(self) -> Optional[PriorityVector]:
        """Return the most recent priority vector."""
        return self._last_vector

    def get_wire_payload(self) -> Optional[dict]:
        """Return wire-format payload for the most recent vector."""
        if self._last_vector:
            return self._last_vector.to_wire_format()
        return None

    # ── Private configuration methods ─────────────────────────────────────────

    def _configure_engine3(
        self,
        vector: PriorityVector,
        vdi: "VDIReport",
        scene: SceneState,
    ) -> None:
        """
        Engine 3 is the program camera. It gets what the moment deserves.
        """
        ri = vdi.render_intensity  # 0.3 to 1.0

        if vdi.identity_moment:
            # Identity moment: pour everything in
            vector.e3_sss         = 1.0
            vector.e3_tex_quality = 1.0
            vector.e3_shadow      = 1.0
            vector.e3_target_fps  = 30
        elif vdi.voice_mode.value == "voice_dominant":
            # Emotional peak: high fidelity on the face
            vector.e3_sss         = 0.85
            vector.e3_tex_quality = 0.90
            vector.e3_shadow      = 0.70
            vector.e3_target_fps  = 30
        elif vdi.voice_mode.value == "mixed":
            # Balanced
            vector.e3_sss         = 0.60
            vector.e3_tex_quality = 0.70
            vector.e3_shadow      = 0.50
            vector.e3_target_fps  = 30
        else:  # content_clear
            # Audience is thinking, not watching the face closely
            # Save cycles — boost when they look back up
            vector.e3_sss         = 0.30
            vector.e3_tex_quality = 0.50
            vector.e3_shadow      = 0.25
            vector.e3_target_fps  = 30

        # Close-up shot always gets identity-level SSS regardless of mode
        if scene.shot_type == "close_up" or scene.shot_type == "extreme_close":
            vector.e3_sss = max(vector.e3_sss, 0.90)
            vector.e3_tex_quality = max(vector.e3_tex_quality, 0.95)

    def _configure_engine4(
        self,
        vector: PriorityVector,
        vdi: "VDIReport",
    ) -> None:
        """
        Engine 4 is the elastic reserve. It renders crew preview at 50%
        fidelity normally. Under pressure, it sacrifices itself for E3.
        """
        if vdi.identity_moment:
            # Identity moment: E4 gives up preview cycles to E3
            vector.e4_fidelity = 0.25
            vector.e4_assist   = True
        elif vdi.render_intensity > 0.80:
            # High demand: partial sacrifice
            vector.e4_fidelity = 0.35
            vector.e4_assist   = True
        else:
            # Normal: E4 runs its own preview
            vector.e4_fidelity = 0.50
            vector.e4_assist   = False

    def _configure_background(
        self,
        vector: PriorityVector,
        vdi: "VDIReport",
        scene: SceneState,
    ) -> None:
        """
        Background physics, crowd LOD, prop shadows.
        If it's not in frame, it doesn't need to be real.
        """
        if vdi.identity_moment:
            # Kill background physics — every cycle goes to the face
            vector.bg_physics    = False
            vector.bg_crowd_lod  = 4   # Skeleton only
            vector.bg_prop_shadow = False
        elif vdi.render_intensity > 0.70:
            vector.bg_physics    = False
            vector.bg_crowd_lod  = 3
            vector.bg_prop_shadow = False
        elif vdi.render_intensity > 0.50:
            vector.bg_physics    = True
            vector.bg_crowd_lod  = 2
            vector.bg_prop_shadow = False
        else:
            # content_clear: we have budget, run the world
            vector.bg_physics    = True
            vector.bg_crowd_lod  = 1
            vector.bg_prop_shadow = True

    def _configure_character_lod(
        self,
        vector: PriorityVector,
        vdi: "VDIReport",
        scene: SceneState,
    ) -> None:
        """
        Per-character LOD. Offscreen characters get skeleton only.
        The primary in-frame character gets the mode's appropriate fidelity.
        """
        lod: Dict[str, int] = {}

        # Primary character in program camera
        if scene.primary_character:
            if vdi.identity_moment:
                lod[scene.primary_character] = self.LOD_PROGRAM_IDENTITY
            elif vdi.render_intensity > 0.60:
                lod[scene.primary_character] = self.LOD_PROGRAM_NORMAL
            else:
                lod[scene.primary_character] = self.LOD_PREVIEW

        # Other characters in frame (not primary)
        for char in scene.characters_in_frame:
            if char != scene.primary_character:
                lod[char] = self.LOD_PREVIEW

        # Preview camera character gets one level above offscreen
        # (they may cut to them soon)
        # (we don't know who preview camera character is here,
        #  but the camera manager knows)

        # Offscreen characters: skeleton only
        for char in scene.characters_offscreen:
            lod[char] = self.LOD_OFFSCREEN

        vector.character_lod = lod

    def _configure_batch_sizes(
        self,
        vector: PriorityVector,
        vdi: "VDIReport",
    ) -> None:
        """
        Voxel batch sizes for primary and secondary engine nodes.
        Identity moments concentrate batch budget on primary.
        """
        if vdi.identity_moment:
            vector.voxel_batch_primary   = 8000
            vector.voxel_batch_secondary = 500   # Secondary is in assist mode
        elif vdi.render_intensity > 0.70:
            vector.voxel_batch_primary   = 5000
            vector.voxel_batch_secondary = 800
        elif vdi.render_intensity > 0.50:
            vector.voxel_batch_primary   = 3500
            vector.voxel_batch_secondary = 1200
        else:
            # content_clear: balanced — world needs to stay alive
            vector.voxel_batch_primary   = 2500
            vector.voxel_batch_secondary = 2000
