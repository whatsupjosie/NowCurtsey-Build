"""
PubCast AI — EVO Protocol (modules.evo)
========================================
Elastic Voxel Orchestration with E-Pete governance layer.

Copyright (c) 2024-2025 Rear View Foresight LLC
"Feic Mo Chroí — See My Heart"

Graceful degradation: if optional evo dependencies (numpy, deepface, mediapipe)
are unavailable, the individual sub-modules degrade internally. This __init__
does NOT raise on import failure — it surfaces what's available.
"""
from __future__ import annotations

__version__ = "1.0.0"

# ── Core EVO pipeline (always safe to import) ────────────────────────────────
try:
    from .vdi_engine          import VDIEngine, VDIReport, VDISignals, VoiceMode
    from .prosody_engine      import ProsodyEngine, SynthesisParams, EmotionalState
    from .voice_characters    import get_character_profile, list_characters
    from .switchblade_governor import SwitchbladeGovernor, SceneState, PriorityVector
    from .epete               import EPete, InferenceTask, TaskType, InferenceModel
    from .pete                import PeteCharacter
    from .evo_integration     import EVOOrchestrator, EVOTick
    _EVO_CORE_AVAILABLE = True
except Exception as _evo_exc:
    import logging as _logging
    _logging.getLogger("pubcast.evo").warning(
        "EVO Protocol core import partial: %s — some features unavailable", _evo_exc
    )
    _EVO_CORE_AVAILABLE = False
    EVOOrchestrator = None   # type: ignore[assignment,misc]
    EVOTick         = None   # type: ignore[assignment,misc]
    EPete           = None   # type: ignore[assignment,misc]
    PeteCharacter   = None   # type: ignore[assignment,misc]
    VDIEngine       = None   # type: ignore[assignment,misc]
    ProsodyEngine   = None   # type: ignore[assignment,misc]
    SwitchbladeGovernor = None  # type: ignore[assignment,misc]

__all__ = [
    "_EVO_CORE_AVAILABLE",
    "EVOOrchestrator", "EVOTick",
    "EPete", "InferenceTask", "TaskType", "InferenceModel",
    "PeteCharacter",
    "VDIEngine", "VDIReport", "VDISignals", "VoiceMode",
    "ProsodyEngine", "SynthesisParams", "EmotionalState",
    "SwitchbladeGovernor", "SceneState", "PriorityVector",
    "get_character_profile", "list_characters",
]
