"""
evo_integration.py — EVO Protocol Integration Layer
====================================================
Copyright (c) 2024-2025 Rear View Foresight LLC
"Feic Mo Chroí — See My Heart"

THE WIRE.

This file connects every system in the EVO protocol into a single
coherent runtime. It is the answer to the question: "How does the
audience's face affect how much compute we spend on subsurface
scattering?"

THE SACRED CHAIN (complete):

    ┌─────────────────────────────────────────────────────────────────┐
    │  AUDIENCE CAMERA                    PERFORMER CAMERA            │
    │       ↓                                    ↓                    │
    │  AudienceFacialAnalyzer         PerformerFacialAnalyzer         │
    │       ↓                                    ↓                    │
    │  VDI Signals ──────────────────────→ Emotional State           │
    │       ↓                                    ↓                    │
    │  VDI Engine                        Prosody Engine               │
    │       ↓                                    ↓                    │
    │  VDI Report ───────────────────────→ Synthesis Params          │
    │       ↓                                    ↓                    │
    │  Switchblade Governor              Voice Synthesis (TTS)        │
    │       ↓                                                          │
    │  Priority Vector                                                 │
    │       ↓                                                          │
    │  DistributedEngineNode                                           │
    │  ┌─────────────────────────────────────────────────────────┐    │
    │  │  Engine 3 (Program Camera)  ← Full fidelity on face     │    │
    │  │  Engine 4 (Elastic Reserve) ← Sacrifice preview if needed│   │
    │  │  Twin Engine (Simulation)   ← World stays alive         │    │
    │  │  Camera Nodes               ← Assist under load         │    │
    │  └─────────────────────────────────────────────────────────┘    │
    └─────────────────────────────────────────────────────────────────┘

RESOURCE DISTRIBUTION LOGIC:

    Identity Moment (VDI ≥ 0.80):
        Engine 3: SSS=1.0, 4K textures, ray shadows
        Engine 4: 25% fidelity, assist=True (gives cycles to E3)
        Background: physics=OFF, crowd=skeleton only
        Primary character: LOD 0 (full identity layer)
        Batch: 8000 primary / 500 secondary

    Voice Dominant (VDI 0.55–0.80):
        Engine 3: SSS=0.85, 90% textures
        Engine 4: 35% fidelity, assist=True
        Background: physics=OFF, crowd=LOD 3
        Batch: 5000 / 800

    Mixed (VDI 0.30–0.55):
        Engine 3: SSS=0.60, 70% textures
        Engine 4: 50% fidelity, assist=False
        Background: physics=ON, crowd=LOD 2
        Batch: 3500 / 1200

    Content Clear (VDI < 0.30):
        Engine 3: SSS=0.30, 50% textures (audience is thinking, not watching)
        Engine 4: 50% fidelity, assist=False
        Background: physics=ON, crowd=LOD 1 (world is alive and present)
        Batch: 2500 / 2000 (balanced — spend the found time on the world)

AUDIO NEVER SACRIFICED:
    Audio processing is always priority=1 in the WorkUnit queue.
    The Switchblade never touches audio batch sizing.
    Voice synthesis always gets its cycles regardless of render state.

Usage:
    orchestrator = EVOOrchestrator()
    await orchestrator.start(engine_node, camera_manager)

    # In your frame loop:
    tick = await orchestrator.tick(
        performer_frame=frame,
        audience_frame=audience_frame,
        scene_state=scene_state,
    )
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Internal imports ──────────────────────────────────────────────────────────
from .vdi_engine          import VDIEngine, VDIReport, VDISignals
from .prosody_engine      import ProsodyEngine, SynthesisParams, EmotionalState
from .voice_characters    import get_character_profile
from .facial_performance  import FacialPerformanceOrchestrator, FacialPerformanceTick
from .switchblade_governor import SwitchbladeGovernor, SceneState, PriorityVector
from .epete               import EPete, InferenceTask, TaskType
from .pete                import PeteCharacter


# ─────────────────────────────────────────────────────────────────────────────
# EVO TICK — output of one complete integration cycle
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EVOTick:
    """
    Complete output of one EVO integration cycle.
    Contains everything every downstream system needs.
    """
    # ── Voice pipeline outputs ────────────────────────────────────────────────
    vdi_report:        VDIReport
    synthesis_params:  SynthesisParams
    ssml_text:         str = ""

    # ── Render pipeline outputs ───────────────────────────────────────────────
    priority_vector:   Optional[PriorityVector] = None

    # ── Facial analysis ───────────────────────────────────────────────────────
    facial_tick:       Optional[FacialPerformanceTick] = None

    # ── Performance ───────────────────────────────────────────────────────────
    total_ms:          float = 0.0
    timestamp:         float = field(default_factory=time.time)

    def to_pete_shoulder(self) -> dict:
        """
        Format as Pete's shoulder context for the orchestrator LLM.
        This is what Pete sees when deciding how to speak.
        Compact. No English prose.
        """
        return {
            "vdi":      round(self.vdi_report.vdi_score, 3),
            "mode":     self.vdi_report.voice_mode.value,
            "identity": self.vdi_report.identity_moment,
            "silence":  round(self.vdi_report.silence_pressure, 3),
            "render":   round(self.vdi_report.render_intensity, 3),
            "audience": round(self.vdi_report.audience_score, 3),
            "ts":       self.timestamp,
        }

    def to_switchblade_wire(self) -> Optional[dict]:
        """Wire format for the distributed engine."""
        if self.priority_vector:
            return self.priority_vector.to_wire_format()
        return None


# ─────────────────────────────────────────────────────────────────────────────
# EVO ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

class EVOOrchestrator:
    """
    The EVO Protocol runtime.

    Coordinates:
        - Facial performance analysis (performer + audience)
        - VDI calculation
        - Prosody parameter generation
        - Switchblade resource allocation
        - Application to the distributed engine

    This is the thing that makes the whole system breathe.
    """

    def __init__(
        self,
        active_character:   str = "pete",
        llm_backend:        Optional[Any] = None,
        studio_model_id:    str = "gemma-studio",
        architect_model_id: str = "gemma-architect",
    ):
        self.active_character    = active_character
        self.vdi_engine          = VDIEngine(smoothing_window=5, mode_hysteresis=0.05)
        self.prosody_engine      = ProsodyEngine()
        self.facial_orchestrator = FacialPerformanceOrchestrator()
        self.switchblade         = SwitchbladeGovernor()

        # ── E-Pete: inference router and system governor ───────────────────────
        self.epete = EPete(
            studio_model_id    = studio_model_id,
            architect_model_id = architect_model_id,
            llm_backend        = llm_backend,
        )

        # ── Pete: character layer ─────────────────────────────────────────────
        self.pete = PeteCharacter(epete=self.epete)

        # Register EVO state with E-Pete so she can monitor VDI
        self.epete.register_evo(self)

        # Runtime references (set on start)
        self._engine_node: Optional[Any]     = None  # DistributedEngineNode
        self._camera_manager: Optional[Any]  = None  # AdvancedCameraManager

        # State
        self._running        = False
        self._tick_count     = 0
        self._last_tick_time = 0.0

        logger.info(f"[EVO] Orchestrator initialized — character: {active_character}")

    async def start(
        self,
        engine_node: Any,          # DistributedEngineNode
        camera_manager: Any,       # AdvancedCameraManager
    ) -> None:
        """
        Start the EVO runtime.
        Boots E-Pete, registers all system components, starts the Sacred Chain.
        """
        self._engine_node    = engine_node
        self._camera_manager = camera_manager

        # Register system components with E-Pete
        self.epete.register_engine(engine_node)
        self.epete.register_switchblade(self.switchblade)

        # Start E-Pete's background worker
        await self.epete.start()

        self._running = True
        logger.info("[EVO] Orchestrator started — E-Pete online, Pete ready")

    async def stop(self) -> None:
        """Stop the EVO runtime."""
        self._running = False
        await self.epete.stop()
        logger.info("[EVO] Orchestrator stopped")

    async def tick(
        self,
        text: str,
        performer_frame: Optional[np.ndarray] = None,
        audience_frame: Optional[np.ndarray]  = None,
        scene_state: Optional[SceneState]     = None,
        additional_signals: Optional[VDISignals] = None,
    ) -> EVOTick:
        """
        Run one complete EVO cycle.

        Args:
            text:               The text about to be synthesized/spoken
            performer_frame:    Current performer camera frame (optional)
            audience_frame:     Current audience camera frame (optional)
            scene_state:        Current scene state (optional — will use defaults)
            additional_signals: Any extra VDI signals to merge in

        Returns:
            EVOTick with all downstream data
        """
        start_time = time.time()

        # ── Step 1: Facial analysis ───────────────────────────────────────────
        facial_tick = None
        emotional_state = EmotionalState()
        vdi_signals = VDISignals(timestamp=time.time())

        if performer_frame is not None:
            facial_tick = self.facial_orchestrator.tick(
                performer_frame=performer_frame,
                audience_frame=audience_frame,
            )
            emotional_state = facial_tick.performer_state
            vdi_signals     = facial_tick.audience_signals

        # Merge any additional signals
        if additional_signals:
            vdi_signals = self._merge_signals(vdi_signals, additional_signals)

        # ── Step 2: VDI calculation ───────────────────────────────────────────
        vdi_report = self.vdi_engine.update(vdi_signals)

        # ── Step 3: Prosody parameter generation ─────────────────────────────
        character_profile = get_character_profile(self.active_character)
        synthesis_params  = self.prosody_engine.get_synthesis_params(
            vdi_report      = vdi_report,
            emotional_state = emotional_state,
            text            = text,
        )

        # Apply character constraints
        if character_profile:
            synthesis_params = self._apply_character_constraints(
                synthesis_params, character_profile
            )

        # ── Step 4: SSML generation ───────────────────────────────────────────
        from .prosody_engine import SSMLBuilder
        ssml_builder = SSMLBuilder()
        ssml_text = ssml_builder.build(text, synthesis_params)

        # ── Step 5: Switchblade priority vector ───────────────────────────────
        if scene_state is None:
            scene_state = SceneState(
                primary_character    = self.active_character,
                characters_in_frame  = [self.active_character],
            )

        priority_vector = self.switchblade.tick(vdi_report, scene_state)

        # ── Step 6: Apply to engine ───────────────────────────────────────────
        if self._engine_node is not None:
            self.switchblade.apply(priority_vector, self._engine_node)

        # ── Step 7: Update camera manager auto-switch rules ───────────────────
        if self._camera_manager is not None:
            self._update_camera_manager(priority_vector, vdi_report)

        # ── Compile tick ──────────────────────────────────────────────────────
        total_ms = (time.time() - start_time) * 1000
        self._tick_count += 1
        self._last_tick_time = time.time()

        tick = EVOTick(
            vdi_report       = vdi_report,
            synthesis_params = synthesis_params,
            ssml_text        = ssml_text,
            priority_vector  = priority_vector,
            facial_tick      = facial_tick,
            total_ms         = total_ms,
            timestamp        = time.time(),
        )

        if self._tick_count % 30 == 0:  # Log every ~1 second at 30fps
            logger.debug(
                f"[EVO] Tick #{self._tick_count} | "
                f"VDI={vdi_report.vdi_score:.3f} "
                f"mode={vdi_report.voice_mode.value} "
                f"identity={vdi_report.identity_moment} "
                f"e3_sss={priority_vector.e3_sss:.2f} "
                f"e4_assist={priority_vector.e4_assist} "
                f"ms={total_ms:.1f}"
            )

        return tick

    def set_active_character(self, character: str) -> None:
        """Switch the active character."""
        self.active_character = character
        logger.info(f"[EVO] Active character: {character}")

    def inject_signals(self, signals: VDISignals) -> VDIReport:
        """
        Inject VDI signals directly (no camera frame required).
        Useful for testing, scripted sequences, or manual override.
        """
        return self.vdi_engine.update(signals)

    def get_current_state(self) -> dict:
        """Return current EVO state summary."""
        report = self.vdi_engine.get_current_report()
        vector = self.switchblade.get_last_vector()
        return {
            "character":      self.active_character,
            "vdi_score":      report.vdi_score if report else 0.5,
            "voice_mode":     report.voice_mode.value if report else "mixed",
            "identity_moment": report.identity_moment if report else False,
            "render_intensity": report.render_intensity if report else 0.5,
            "e3_sss":         vector.e3_sss if vector else 0.5,
            "e4_assist":      vector.e4_assist if vector else False,
            "bg_physics":     vector.bg_physics if vector else True,
            "tick_count":     self._tick_count,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _merge_signals(
        self,
        base: VDISignals,
        additional: VDISignals,
    ) -> VDISignals:
        """Merge two VDISignals, averaging non-zero values."""
        # Simple average where additional has non-default values
        return VDISignals(
            audience_engagement = (base.audience_engagement + additional.audience_engagement) / 2,
            audience_valence    = (base.audience_valence    + additional.audience_valence)    / 2,
            audience_arousal    = (base.audience_arousal    + additional.audience_arousal)    / 2,
            audience_attention  = (base.audience_attention  + additional.audience_attention)  / 2,
            audience_silence    = max(base.audience_silence, additional.audience_silence),
            laughter_detected   = max(base.laughter_detected, additional.laughter_detected),
            topic_emotional_weight = max(
                base.topic_emotional_weight,
                additional.topic_emotional_weight
            ),
            performer_arousal   = (base.performer_arousal  + additional.performer_arousal)   / 2,
            performer_valence   = (base.performer_valence  + additional.performer_valence)   / 2,
            timestamp           = time.time(),
        )

    def _apply_character_constraints(
        self,
        params: SynthesisParams,
        profile: Any,  # CharacterVoiceProfile
    ) -> SynthesisParams:
        """Apply character-specific constraints to synthesis params."""
        # Enforce character ceilings
        params.style_exaggeration = min(
            params.style_exaggeration,
            profile.max_expressiveness
        )
        params.stability = max(params.stability, profile.min_stability)

        # Crack permission based on character
        if not profile.crack_allowed:
            params.crack_permission  = False
            params.crack_probability = 0.0

        # Apply character's EQ signature on top of mode EQ
        params.warmth_boost_db  += profile.warmth_signature
        params.presence_boost_db = max(
            params.presence_boost_db,
            profile.presence_signature
        )

        return params

    def _update_camera_manager(
        self,
        vector: PriorityVector,
        vdi_report: VDIReport,
    ) -> None:
        """
        Update camera manager with Switchblade decisions.
        This is where _check_auto_switch_rules gets filled in.
        """
        try:
            if not self._camera_manager:
                return

            # Identity moments: lock the program camera (don't auto-switch)
            if vdi_report.identity_moment:
                self._camera_manager.auto_switching_enabled = False
            else:
                self._camera_manager.auto_switching_enabled = True

            # Pass priority vector to camera manager for its own use
            if hasattr(self._camera_manager, '_switchblade_vector'):
                self._camera_manager._switchblade_vector = vector

        except Exception as e:
            logger.debug(f"[EVO] Camera manager update error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# CONVENIENCE: STANDALONE VOICE SYNTHESIS
# ─────────────────────────────────────────────────────────────────────────────

def synthesize_with_evo(
    text: str,
    vdi_score: float = 0.5,
    character: str = "pete",
    emotional_state: Optional[EmotionalState] = None,
) -> SynthesisParams:
    """
    Quick synthesis params without camera input.
    For testing or scripted sequences.

    Example:
        params = synthesize_with_evo(
            "You already know the answer.",
            vdi_score=0.85,    # Identity moment
            character="pete",
        )
        elevenlabs_settings = params.to_elevenlabs()
    """
    from .vdi_engine import VDIEngine, VDISignals

    engine   = VDIEngine()
    prosody  = ProsodyEngine()

    # Build signals from vdi_score directly
    signals = VDISignals(
        audience_engagement    = vdi_score,
        audience_arousal       = vdi_score,
        topic_emotional_weight = vdi_score,
        timestamp              = time.time(),
    )
    report = engine.update(signals)

    params = prosody.get_synthesis_params(
        vdi_report      = report,
        emotional_state = emotional_state or EmotionalState(),
        text            = text,
    )

    # Apply character
    profile = get_character_profile(character)
    if profile:
        params.stability          = max(params.stability, profile.min_stability)
        params.style_exaggeration = min(params.style_exaggeration, profile.max_expressiveness)
        if not profile.crack_allowed:
            params.crack_permission  = False
            params.crack_probability = 0.0

    return params
