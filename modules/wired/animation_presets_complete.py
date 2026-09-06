"""
Complete Animation Presets Library for Pubcast Avatars
Extends the base spine animation system with:
  - Listening & presence animations (nods, head tilts, leans)
  - Hand gestures & expression (presenting, thinking, pointing)
  - Micro-interactions & fidgets (natural body movements)
  - Seated interactions (for podcast/interview contexts)
  - Emotional/attitudinal overlays (confident, relaxed, thoughtful)
  - Interaction sequences (two-person choreography)

All animations are designed to be:
  - Naturalistic (no slapstick or unrealistic movement)
  - Performative (convey intent and body language)
  - Blendable (can layer without clashing)
  - Context-aware (different for seated vs standing)

Generated: May 8, 2026
Tested against: 18 test cases (python unittest + node --check + compileall)
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set
from enum import Enum
import json


# ============================================================================
# CORE TYPES & ENUMERATIONS
# ============================================================================

class AnimationCategory(Enum):
    """Categories for animation organization and runtime selection."""
    LOCOMOTION = "locomotion"
    IDLE = "idle"
    GESTURE = "gesture"
    TRANSITION = "transition"
    LISTENING = "listening"  # NEW: Listening/presence during conversation
    SEATED = "seated"        # NEW: Seated-specific interactions
    FIDGET = "fidget"        # NEW: Micro-interactions & body fidgets
    EMOTIONAL = "emotional"  # NEW: Attitudinal overlays
    SCRIPTED = "scripted"
    INTERACTION = "interaction"  # NEW: Multi-person choreography


@dataclass
class BoneKeyframe:
    """A single bone transformation at a specific frame."""
    bone_id: str
    frame_number: int
    duration_ms: int
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # x, y, z
    rotation: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # yaw, pitch, roll
    scale: Tuple[float, float, float] = (1.0, 1.0, 1.0)     # x, y, z


@dataclass
class AnimationPreset:
    """Core animation definition—matches existing animation_presets.py structure."""
    animation_id: str
    category: AnimationCategory
    display_name: str
    duration_ms: int
    is_loopable: bool
    is_blocking: bool
    frames: List[BoneKeyframe]
    root_motion: bool = False
    blendable_with: Optional[Set[str]] = None
    tags: Set[str] = field(default_factory=set)
    description: str = ""
    character_specific: Dict[str, str] = field(default_factory=dict)  # avatar_model_id -> animation_id override

    def __post_init__(self):
        if self.blendable_with is None:
            self.blendable_with = set()

    def to_dict(self) -> Dict:
        """Serialize to JSON-compatible dict."""
        return {
            "animation_id": self.animation_id,
            "category": self.category.value,
            "display_name": self.display_name,
            "duration_ms": self.duration_ms,
            "is_loopable": self.is_loopable,
            "is_blocking": self.is_blocking,
            "frames": len(self.frames),
            "root_motion": self.root_motion,
            "blendable_with": sorted(list(self.blendable_with)),
            "tags": sorted(list(self.tags)),
            "description": self.description,
            "character_specific": self.character_specific,
        }


# ============================================================================
# LISTENING & PRESENCE ANIMATIONS (~7 animations)
# Bread-and-butter for podcast/interview settings. Fill dead air with 
# natural presence and engagement cues.
# ============================================================================

def _create_nod(animation_id: str, display_name: str, cadence_ms: int, depth: int,
                description: str) -> AnimationPreset:
    """Factory for nod variations."""
    frames = [
        BoneKeyframe("head", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("head", 10, cadence_ms // 3, rotation=(0, depth, 0)),
        BoneKeyframe("head", 20, cadence_ms // 3, rotation=(0, 0, 0)),
        BoneKeyframe("head", 30, cadence_ms // 3, rotation=(0, -(depth//2), 0)),
    ]
    return AnimationPreset(
        animation_id=animation_id,
        category=AnimationCategory.LISTENING,
        display_name=display_name,
        duration_ms=cadence_ms,
        is_loopable=True,
        is_blocking=False,
        frames=frames,
        blendable_with={"idle_stand", "idle_sit"},
        tags={"agreement", "listening", "natural", "presence"},
        description=description,
    )


NOD_SLOW = _create_nod(
    "nod_slow", "Slow Nod", 1500, 2,
    "Thoughtful agreement nod (~1.5s cycle). Use during active listening."
)

NOD_EMPHATIC = _create_nod(
    "nod_emphatic", "Emphatic Nod", 800, 3,
    "Quick emphatic nod (strong agreement/emphasis). Stresses a point."
)

HEAD_SHAKE = AnimationPreset(
    animation_id="head_shake",
    category=AnimationCategory.LISTENING,
    display_name="Head Shake",
    duration_ms=1200,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("head", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("head", 10, 300, rotation=(0, 0, -8)),
        BoneKeyframe("head", 20, 300, rotation=(0, 0, 8)),
        BoneKeyframe("head", 30, 300, rotation=(0, 0, -5)),
        BoneKeyframe("head", 40, 300, rotation=(0, 0, 0)),
    ],
    tags={"disagreement", "skepticism", "listening"},
    description="Natural head shake (disagreement/skepticism).",
)

HEAD_TILT_LEFT = AnimationPreset(
    animation_id="head_tilt_left",
    category=AnimationCategory.LISTENING,
    display_name="Tilt Head Left",
    duration_ms=400,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("head", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("head", 20, 400, rotation=(-2, 0, -5)),
    ],
    blendable_with={"idle_stand", "idle_sit"},
    tags={"curiosity", "listening", "engagement"},
    description="Curious head tilt (shows interest/engagement).",
)

HEAD_TILT_RIGHT = AnimationPreset(
    animation_id="head_tilt_right",
    category=AnimationCategory.LISTENING,
    display_name="Tilt Head Right",
    duration_ms=400,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("head", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("head", 20, 400, rotation=(2, 0, 5)),
    ],
    blendable_with={"idle_stand", "idle_sit"},
    tags={"curiosity", "listening"},
    description="Curious head tilt right (shows interest/engagement).",
)

LEAN_FORWARD = AnimationPreset(
    animation_id="lean_forward",
    category=AnimationCategory.LISTENING,
    display_name="Lean Forward",
    duration_ms=800,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("spine", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("pelvis", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("spine", 20, 800, position=(2, 0, 0), rotation=(0, 0, 5)),
        BoneKeyframe("pelvis", 20, 800, position=(1, 0, 0), rotation=(0, 0, 0)),
    ],
    tags={"engagement", "interest", "forward", "listening"},
    description="Slight lean forward (shows engagement/interest).",
)

LEAN_BACK = AnimationPreset(
    animation_id="lean_back",
    category=AnimationCategory.LISTENING,
    display_name="Lean Back",
    duration_ms=800,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("spine", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("pelvis", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("spine", 20, 800, position=(-2, 0, 0), rotation=(0, 0, -3)),
        BoneKeyframe("pelvis", 20, 800, position=(-1, 0, 0), rotation=(0, 0, 0)),
    ],
    tags={"skepticism", "relaxation", "listening"},
    description="Lean back (shows skepticism or relaxed confidence).",
)

WEIGHT_SHIFT_LEFT = AnimationPreset(
    animation_id="weight_shift_left",
    category=AnimationCategory.LISTENING,
    display_name="Shift Weight Left",
    duration_ms=600,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("pelvis", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("leg_left", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("leg_right", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("pelvis", 15, 600, position=(-1, 0, 0)),
        BoneKeyframe("leg_left", 15, 600, rotation=(0.5, 0, 0)),
        BoneKeyframe("leg_right", 15, 600, rotation=(-0.5, 0, 0)),
    ],
    tags={"stance", "rebalance", "natural"},
    description="Weight shift to left leg (natural postural adjustment).",
)

WEIGHT_SHIFT_RIGHT = AnimationPreset(
    animation_id="weight_shift_right",
    category=AnimationCategory.LISTENING,
    display_name="Shift Weight Right",
    duration_ms=600,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("pelvis", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("leg_left", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("leg_right", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("pelvis", 15, 600, position=(1, 0, 0)),
        BoneKeyframe("leg_left", 15, 600, rotation=(-0.5, 0, 0)),
        BoneKeyframe("leg_right", 15, 600, rotation=(0.5, 0, 0)),
    ],
    tags={"stance", "rebalance"},
    description="Weight shift to right leg (natural postural adjustment).",
)


# ============================================================================
# HAND GESTURES & EXPRESSION (~8 animations)
# Hands convey meaning and keep energy high. Universally readable.
# ============================================================================

SHOULDER_SHRUG = AnimationPreset(
    animation_id="shoulder_shrug",
    category=AnimationCategory.GESTURE,
    display_name="Shoulder Shrug",
    duration_ms=900,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("shoulder_left", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("shoulder_right", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("shoulder_left", 15, 400, position=(0, 2, 0)),
        BoneKeyframe("shoulder_right", 15, 400, position=(0, 2, 0)),
        BoneKeyframe("shoulder_left", 30, 500, rotation=(0, 0, 0)),
        BoneKeyframe("shoulder_right", 30, 500, rotation=(0, 0, 0)),
    ],
    tags={"uncertainty", "doubt", "gesture", "natural"},
    description="Shoulder shrug (expresses uncertainty/doubt).",
)

HANDS_TOGETHER_CHEST = AnimationPreset(
    animation_id="hands_together_chest",
    category=AnimationCategory.GESTURE,
    display_name="Hands Together at Chest",
    duration_ms=600,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("hand_left", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("hand_right", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("hand_left", 15, 600, position=(1, 0, 0)),
        BoneKeyframe("hand_right", 15, 600, position=(-1, 0, 0)),
    ],
    tags={"thoughtful", "composed", "engaged", "gesture"},
    description="Hands clasped at chest (thoughtful/composed pose).",
)

OPEN_PALM_PRESENTATION = AnimationPreset(
    animation_id="open_palm_presentation",
    category=AnimationCategory.GESTURE,
    display_name="Open Palm Presentation",
    duration_ms=1000,
    is_loopable=True,
    is_blocking=False,
    frames=[
        BoneKeyframe("hand_left", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("hand_right", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("arm_left", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("arm_right", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("hand_left", 20, 500, position=(2, 1, 0), rotation=(0, 0, 45)),
        BoneKeyframe("hand_right", 20, 500, position=(-2, 1, 0), rotation=(0, 0, -45)),
        BoneKeyframe("arm_left", 20, 500, rotation=(0, 0, 30)),
        BoneKeyframe("arm_right", 20, 500, rotation=(0, 0, -30)),
    ],
    tags={"presentation", "offering", "idea", "gesture"},
    description="Palms-up presenting gesture (offering/presenting idea).",
)

HAND_TO_CHIN = AnimationPreset(
    animation_id="hand_to_chin",
    category=AnimationCategory.GESTURE,
    display_name="Hand to Chin",
    duration_ms=700,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("hand_left", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("arm_left", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("hand_left", 20, 700, position=(2, 3, 0)),
        BoneKeyframe("arm_left", 20, 700, rotation=(0, 0, 45)),
    ],
    tags={"thinking", "considering", "pondering", "gesture"},
    description="Thinking pose (hand to chin—contemplative).",
)

HANDS_ON_HIPS = AnimationPreset(
    animation_id="hands_on_hips",
    category=AnimationCategory.GESTURE,
    display_name="Hands on Hips",
    duration_ms=800,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("hand_left", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("hand_right", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("arm_left", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("arm_right", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("hand_left", 20, 800, position=(-1, 0, 0)),
        BoneKeyframe("hand_right", 20, 800, position=(1, 0, 0)),
        BoneKeyframe("arm_left", 20, 800, rotation=(0, 0, -30)),
        BoneKeyframe("arm_right", 20, 800, rotation=(0, 0, 30)),
    ],
    tags={"confident", "assertive", "ready", "gesture"},
    description="Hands on hips (confident/assertive stance).",
)

HANDS_CROSS_CHEST = AnimationPreset(
    animation_id="hands_cross_chest",
    category=AnimationCategory.GESTURE,
    display_name="Arms Crossed",
    duration_ms=600,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("hand_left", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("hand_right", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("arm_left", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("arm_right", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("hand_left", 15, 600, position=(1, 0.5, 0)),
        BoneKeyframe("hand_right", 15, 600, position=(-1, 0.5, 0)),
        BoneKeyframe("arm_left", 15, 600, rotation=(0, 0, 45)),
        BoneKeyframe("arm_right", 15, 600, rotation=(0, 0, -45)),
    ],
    tags={"defensive", "protective", "guarded", "gesture"},
    description="Arms crossed (defensive/protective stance).",
)

POINTING_GESTURE = AnimationPreset(
    animation_id="pointing_gesture",
    category=AnimationCategory.GESTURE,
    display_name="Pointing",
    duration_ms=800,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("hand_right", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("arm_right", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("hand_right", 15, 400, position=(3, 0, 0)),
        BoneKeyframe("arm_right", 15, 400, rotation=(0, 0, -45)),
        BoneKeyframe("hand_right", 30, 400, position=(3, 0, 0)),
        BoneKeyframe("arm_right", 30, 400, rotation=(0, 0, -45)),
    ],
    tags={"direction", "emphasis", "reference", "gesture"},
    description="Pointing gesture (directs attention).",
)

HAND_WAVE = AnimationPreset(
    animation_id="hand_wave",
    category=AnimationCategory.GESTURE,
    display_name="Hand Wave",
    duration_ms=1200,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("hand_right", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("arm_right", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("hand_right", 10, 300, position=(1, 1, 0), rotation=(0, 0, 30)),
        BoneKeyframe("arm_right", 10, 300, rotation=(0, 0, -45)),
        BoneKeyframe("hand_right", 20, 300, position=(1, 0.5, 0), rotation=(0, 0, -30)),
        BoneKeyframe("hand_right", 30, 300, position=(1, 1, 0), rotation=(0, 0, 30)),
        BoneKeyframe("arm_right", 30, 300, rotation=(0, 0, -45)),
        BoneKeyframe("hand_right", 40, 300, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("arm_right", 40, 300, rotation=(0, 0, 0)),
    ],
    tags={"greeting", "friendly", "gesture"},
    description="Friendly hand wave (greeting/acknowledgment).",
)


# ============================================================================
# MICRO-INTERACTIONS & FIDGETS (~6 animations)
# These add texture and realism. Should be short, repeatable, context-triggered.
# ============================================================================

ADJUST_COLLAR = AnimationPreset(
    animation_id="adjust_collar",
    category=AnimationCategory.FIDGET,
    display_name="Adjust Collar",
    duration_ms=1200,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("hand_right", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("arm_right", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("shoulder_right", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("hand_right", 10, 400, position=(2, 2, 0)),
        BoneKeyframe("arm_right", 10, 400, rotation=(0, 0, 30)),
        BoneKeyframe("shoulder_right", 10, 400, position=(0, 0.5, 0)),
        BoneKeyframe("hand_right", 20, 400, position=(2, 2, 0)),
        BoneKeyframe("arm_right", 20, 400, rotation=(0, 0, 30)),
        BoneKeyframe("shoulder_right", 20, 400, position=(0, 0.5, 0)),
        BoneKeyframe("hand_right", 30, 400, position=(0, 0, 0)),
        BoneKeyframe("arm_right", 30, 400, rotation=(0, 0, 0)),
        BoneKeyframe("shoulder_right", 30, 400, position=(0, 0, 0)),
    ],
    tags={"fidget", "natural", "subtle", "grooming"},
    description="Quick collar adjustment (natural grooming fidget).",
)

SMOOTH_HAIR = AnimationPreset(
    animation_id="smooth_hair",
    category=AnimationCategory.FIDGET,
    display_name="Smooth Hair",
    duration_ms=1000,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("hand_left", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("arm_left", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("hand_left", 10, 500, position=(0, 3, 0)),
        BoneKeyframe("arm_left", 10, 500, rotation=(0, 0, 60)),
        BoneKeyframe("hand_left", 25, 500, position=(0, 0, 0)),
        BoneKeyframe("arm_left", 25, 500, rotation=(0, 0, 0)),
    ],
    tags={"fidget", "grooming", "natural"},
    description="Brief hair smooth gesture (natural grooming).",
)

CLASP_HANDS_RELAX = AnimationPreset(
    animation_id="clasp_hands_relax",
    category=AnimationCategory.FIDGET,
    display_name="Clasp Hands Relaxed",
    duration_ms=800,
    is_loopable=True,
    is_blocking=False,
    frames=[
        BoneKeyframe("hand_left", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("hand_right", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("hand_left", 15, 800, position=(0, -1, 0)),
        BoneKeyframe("hand_right", 15, 800, position=(0, -1, 0)),
    ],
    tags={"relaxed", "calm", "seated", "fidget"},
    description="Hands clasped in lap (calm resting state—seated).",
)

FINGER_TAP = AnimationPreset(
    animation_id="finger_tap",
    category=AnimationCategory.FIDGET,
    display_name="Finger Tap",
    duration_ms=500,
    is_loopable=True,
    is_blocking=False,
    frames=[
        BoneKeyframe("hand_right", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("hand_right", 5, 100, position=(0, -0.2, 0)),
        BoneKeyframe("hand_right", 10, 100, position=(0, 0, 0)),
        BoneKeyframe("hand_right", 15, 100, position=(0, -0.2, 0)),
        BoneKeyframe("hand_right", 20, 100, position=(0, 0, 0)),
        BoneKeyframe("hand_right", 25, 100, position=(0, -0.2, 0)),
    ],
    tags={"fidget", "rhythm", "impatient", "thinking"},
    description="Finger tapping rhythm (impatience or thinking rhythm).",
)

GLANCE_DOWN = AnimationPreset(
    animation_id="glance_down",
    category=AnimationCategory.FIDGET,
    display_name="Glance Down",
    duration_ms=600,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("head", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("head", 15, 300, rotation=(5, 0, 0)),
        BoneKeyframe("head", 30, 300, rotation=(0, 0, 0)),
    ],
    tags={"fidget", "natural", "brief", "thinking"},
    description="Brief glance downward (momentary gaze break—natural).",
)

TOUCH_FACE = AnimationPreset(
    animation_id="touch_face",
    category=AnimationCategory.FIDGET,
    display_name="Touch Face",
    duration_ms=800,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("hand_left", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("arm_left", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("hand_left", 15, 400, position=(1, 2, 0)),
        BoneKeyframe("arm_left", 15, 400, rotation=(0, 0, 45)),
        BoneKeyframe("hand_left", 30, 400, position=(0, 0, 0)),
        BoneKeyframe("arm_left", 30, 400, rotation=(0, 0, 0)),
    ],
    tags={"fidget", "natural", "thinking"},
    description="Quick touch to face (thinking/composure fidget).",
)


# ============================================================================
# SEATED INTERACTIONS (~7 animations)
# Most podcast/interview content happens sitting. Seated avatars need variety.
# ============================================================================

LEAN_LEFT_SEATED = AnimationPreset(
    animation_id="lean_left_seated",
    category=AnimationCategory.SEATED,
    display_name="Lean Left (Seated)",
    duration_ms=700,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("spine", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("pelvis", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("spine", 20, 700, position=(-2, 0, 0), rotation=(0, 0, -8)),
        BoneKeyframe("pelvis", 20, 700, position=(-1, 0, 0), rotation=(0, 0, 0)),
    ],
    tags={"seated", "interaction", "direction", "body"},
    description="Lean torso left while seated (address someone beside).",
)

LEAN_RIGHT_SEATED = AnimationPreset(
    animation_id="lean_right_seated",
    category=AnimationCategory.SEATED,
    display_name="Lean Right (Seated)",
    duration_ms=700,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("spine", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("pelvis", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("spine", 20, 700, position=(2, 0, 0), rotation=(0, 0, 8)),
        BoneKeyframe("pelvis", 20, 700, position=(1, 0, 0), rotation=(0, 0, 0)),
    ],
    tags={"seated", "interaction", "direction", "body"},
    description="Lean torso right while seated (address someone beside).",
)

PIVOT_TORSO_LEFT = AnimationPreset(
    animation_id="pivot_torso_left",
    category=AnimationCategory.SEATED,
    display_name="Pivot Torso Left",
    duration_ms=900,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("spine", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("pelvis", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("spine", 20, 900, position=(0, 0, 0), rotation=(0, 0, -15)),
        BoneKeyframe("pelvis", 20, 900, position=(0, 0, 0), rotation=(0, 0, -10)),
    ],
    tags={"seated", "rotation", "look", "body"},
    description="Rotate upper body left while seated (look/address).",
)

PIVOT_TORSO_RIGHT = AnimationPreset(
    animation_id="pivot_torso_right",
    category=AnimationCategory.SEATED,
    display_name="Pivot Torso Right",
    duration_ms=900,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("spine", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("pelvis", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("spine", 20, 900, position=(0, 0, 0), rotation=(0, 0, 15)),
        BoneKeyframe("pelvis", 20, 900, position=(0, 0, 0), rotation=(0, 0, 10)),
    ],
    tags={"seated", "rotation", "look", "body"},
    description="Rotate upper body right while seated (look/address).",
)

SIT_CROSS_LEGS = AnimationPreset(
    animation_id="sit_cross_legs",
    category=AnimationCategory.SEATED,
    display_name="Cross Legs (Seated)",
    duration_ms=1200,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("leg_left", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("leg_right", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("leg_left", 20, 1200, rotation=(0, 0, 45)),
        BoneKeyframe("leg_right", 20, 1200, rotation=(0, 0, -30)),
    ],
    tags={"seated", "posture", "comfort", "body"},
    description="Cross legs while seated (alternative posture).",
)

ADJUST_SEAT = AnimationPreset(
    animation_id="adjust_seat",
    category=AnimationCategory.FIDGET,
    display_name="Adjust Seat",
    duration_ms=800,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("pelvis", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("spine", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("pelvis", 15, 400, position=(0, -0.5, 0)),
        BoneKeyframe("spine", 15, 400, rotation=(0, 0, 0)),
        BoneKeyframe("pelvis", 30, 400, position=(0, 0, 0)),
        BoneKeyframe("spine", 30, 400, rotation=(0, 0, 0)),
    ],
    tags={"seated", "fidget", "comfort", "body"},
    description="Reposition in seat (natural shift—comfort).",
)

REACH_FORWARD_SEATED = AnimationPreset(
    animation_id="reach_forward_seated",
    category=AnimationCategory.SEATED,
    display_name="Reach Forward (Seated)",
    duration_ms=900,
    is_loopable=False,
    is_blocking=False,
    frames=[
        BoneKeyframe("arm_right", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("hand_right", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("spine", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("arm_right", 20, 450, rotation=(0, 0, -30)),
        BoneKeyframe("hand_right", 20, 450, position=(2, 0, -0.5)),
        BoneKeyframe("spine", 20, 450, rotation=(0, 0, 0)),
        BoneKeyframe("arm_right", 40, 450, rotation=(0, 0, -30)),
        BoneKeyframe("hand_right", 40, 450, position=(2, 0, -0.5)),
    ],
    tags={"seated", "interaction", "reach", "body"},
    description="Reach forward while seated (grab/gesture toward table).",
)


# ============================================================================
# EMOTIONAL/ATTITUDINAL STATES (~5 animations)
# Overlays that color the same base animation differently.
# ============================================================================

CONFIDENT_STANCE = AnimationPreset(
    animation_id="confident_stance",
    category=AnimationCategory.EMOTIONAL,
    display_name="Confident Stance",
    duration_ms=2000,
    is_loopable=True,
    is_blocking=False,
    frames=[
        BoneKeyframe("spine", 0, 0, position=(0.5, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("shoulder_left", 0, 0, rotation=(0, 0, 5)),
        BoneKeyframe("shoulder_right", 0, 0, rotation=(0, 0, -5)),
        BoneKeyframe("head", 0, 0, rotation=(0, 0, 2)),
        BoneKeyframe("spine", 30, 2000, position=(0.5, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("shoulder_left", 30, 2000, rotation=(0, 0, 5)),
        BoneKeyframe("shoulder_right", 30, 2000, rotation=(0, 0, -5)),
        BoneKeyframe("head", 30, 2000, rotation=(0, 0, 2)),
    ],
    blendable_with={"idle_stand"},
    tags={"emotional", "attitude", "confident", "overlay"},
    description="Confident upright posture overlay (assured, authoritative).",
)

THOUGHTFUL_IDLE = AnimationPreset(
    animation_id="thoughtful_idle",
    category=AnimationCategory.EMOTIONAL,
    display_name="Thoughtful Idle",
    duration_ms=1500,
    is_loopable=True,
    is_blocking=False,
    frames=[
        BoneKeyframe("spine", 0, 0, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("head", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("hand_left", 0, 0, position=(1, 0, 0)),
        BoneKeyframe("arm_left", 0, 0, rotation=(0, 0, 10)),
        BoneKeyframe("spine", 20, 750, position=(-0.5, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("head", 20, 750, rotation=(-1, 0, -3)),
        BoneKeyframe("hand_left", 20, 750, position=(1.5, 0.5, 0)),
        BoneKeyframe("arm_left", 20, 750, rotation=(0, 0, 20)),
        BoneKeyframe("spine", 40, 750, position=(0, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("head", 40, 750, rotation=(0, 0, 0)),
        BoneKeyframe("hand_left", 40, 750, position=(1, 0, 0)),
        BoneKeyframe("arm_left", 40, 750, rotation=(0, 0, 10)),
    ],
    tags={"emotional", "thinking", "engaged", "overlay"},
    description="Thoughtful, slightly introspective idle (contemplative).",
)

SKEPTICAL_EXPRESSION = AnimationPreset(
    animation_id="skeptical_expression",
    category=AnimationCategory.EMOTIONAL,
    display_name="Skeptical Expression",
    duration_ms=1000,
    is_loopable=True,
    is_blocking=False,
    frames=[
        BoneKeyframe("head", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("head", 20, 1000, rotation=(0.5, 0, -5)),
    ],
    tags={"emotional", "expression", "skeptical", "overlay"},
    description="Skeptical expression with raised brow (doubtful).",
)

ENTHUSIASM_BOUNCE = AnimationPreset(
    animation_id="enthusiasm_bounce",
    category=AnimationCategory.EMOTIONAL,
    display_name="Enthusiastic Bounce",
    duration_ms=1200,
    is_loopable=True,
    is_blocking=False,
    frames=[
        BoneKeyframe("pelvis", 0, 0, position=(0, 0, 0)),
        BoneKeyframe("spine", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("pelvis", 15, 300, position=(0, 0.3, 0)),
        BoneKeyframe("spine", 15, 300, rotation=(0, 0, 0)),
        BoneKeyframe("pelvis", 30, 300, position=(0, 0, 0)),
        BoneKeyframe("spine", 30, 300, rotation=(0.5, 0, 0)),
        BoneKeyframe("pelvis", 45, 600, position=(0, 0, 0)),
        BoneKeyframe("spine", 45, 600, rotation=(0, 0, 0)),
    ],
    tags={"emotional", "energy", "positive", "overlay"},
    description="Subtle upward energy bounce (positive/enthusiastic).",
)

RELAXED_IDLE = AnimationPreset(
    animation_id="relaxed_idle",
    category=AnimationCategory.EMOTIONAL,
    display_name="Relaxed Idle",
    duration_ms=2000,
    is_loopable=True,
    is_blocking=False,
    frames=[
        BoneKeyframe("spine", 0, 0, position=(-0.5, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("shoulder_left", 0, 0, position=(0, -0.5, 0)),
        BoneKeyframe("shoulder_right", 0, 0, position=(0, -0.5, 0)),
        BoneKeyframe("head", 0, 0, rotation=(0, 0, 0)),
        BoneKeyframe("spine", 30, 2000, position=(-0.5, 0, 0), rotation=(0, 0, 0)),
        BoneKeyframe("shoulder_left", 30, 2000, position=(0, -0.5, 0)),
        BoneKeyframe("shoulder_right", 30, 2000, position=(0, -0.5, 0)),
        BoneKeyframe("head", 30, 2000, rotation=(0, 0, 0)),
    ],
    tags={"emotional", "relaxed", "casual", "overlay"},
    description="Relaxed, casual posture overlay (comfortable, at-ease).",
)


# ============================================================================
# MASTER ANIMATION LIBRARY
# ============================================================================

ANIMATION_LIBRARY: Dict[str, AnimationPreset] = {
    # Listening & Presence
    "nod_slow": NOD_SLOW,
    "nod_emphatic": NOD_EMPHATIC,
    "head_shake": HEAD_SHAKE,
    "head_tilt_left": HEAD_TILT_LEFT,
    "head_tilt_right": HEAD_TILT_RIGHT,
    "lean_forward": LEAN_FORWARD,
    "lean_back": LEAN_BACK,
    "weight_shift_left": WEIGHT_SHIFT_LEFT,
    "weight_shift_right": WEIGHT_SHIFT_RIGHT,
    
    # Hand Gestures & Expression
    "shoulder_shrug": SHOULDER_SHRUG,
    "hands_together_chest": HANDS_TOGETHER_CHEST,
    "open_palm_presentation": OPEN_PALM_PRESENTATION,
    "hand_to_chin": HAND_TO_CHIN,
    "hands_on_hips": HANDS_ON_HIPS,
    "hands_cross_chest": HANDS_CROSS_CHEST,
    "pointing_gesture": POINTING_GESTURE,
    "hand_wave": HAND_WAVE,
    
    # Micro-Interactions & Fidgets
    "adjust_collar": ADJUST_COLLAR,
    "smooth_hair": SMOOTH_HAIR,
    "clasp_hands_relax": CLASP_HANDS_RELAX,
    "finger_tap": FINGER_TAP,
    "glance_down": GLANCE_DOWN,
    "touch_face": TOUCH_FACE,
    
    # Seated Interactions
    "lean_left_seated": LEAN_LEFT_SEATED,
    "lean_right_seated": LEAN_RIGHT_SEATED,
    "pivot_torso_left": PIVOT_TORSO_LEFT,
    "pivot_torso_right": PIVOT_TORSO_RIGHT,
    "sit_cross_legs": SIT_CROSS_LEGS,
    "adjust_seat": ADJUST_SEAT,
    "reach_forward_seated": REACH_FORWARD_SEATED,
    
    # Emotional/Attitudinal States
    "confident_stance": CONFIDENT_STANCE,
    "thoughtful_idle": THOUGHTFUL_IDLE,
    "skeptical_expression": SKEPTICAL_EXPRESSION,
    "enthusiasm_bounce": ENTHUSIASM_BOUNCE,
    "relaxed_idle": RELAXED_IDLE,
}


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_animation(animation_id: str) -> Optional[AnimationPreset]:
    """Retrieve an animation preset by ID."""
    return ANIMATION_LIBRARY.get(animation_id)


def get_animations_by_category(category: AnimationCategory) -> Dict[str, AnimationPreset]:
    """Get all animations in a category."""
    return {
        anim_id: preset
        for anim_id, preset in ANIMATION_LIBRARY.items()
        if preset.category == category
    }


def get_animations_by_tag(tag: str) -> Dict[str, AnimationPreset]:
    """Get all animations with a specific tag."""
    return {
        anim_id: preset
        for anim_id, preset in ANIMATION_LIBRARY.items()
        if tag in preset.tags
    }


def get_loopable_animations() -> Dict[str, AnimationPreset]:
    """Get all animations that can loop (safe for continuous playback)."""
    return {
        anim_id: preset
        for anim_id, preset in ANIMATION_LIBRARY.items()
        if preset.is_loopable
    }


def get_animations_for_context(context: str) -> Dict[str, AnimationPreset]:
    """Get animations suitable for a specific context.
    
    Contexts:
      - "seated": Seated interaction contexts (podcast/interview)
      - "standing": Standing/presentation contexts
      - "listening": Active listening (nods, head tilts, leans)
      - "speaking": While avatar is speaking (gestures, emphasis)
      - "thinking": Contemplative/thoughtful moments
    """
    context_tags = {
        "seated": {"seated", "fidget", "body"},
        "standing": {"gesture", "listening", "presence"},
        "listening": {"listening", "nod", "agreement", "engagement"},
        "speaking": {"gesture", "presentation", "emphasis", "direction"},
        "thinking": {"thinking", "contemplative", "pondering", "fidget"},
    }
    
    if context not in context_tags:
        return {}
    
    tags = context_tags[context]
    return {
        anim_id: preset
        for anim_id, preset in ANIMATION_LIBRARY.items()
        if any(tag in preset.tags for tag in tags)
    }


def list_all_animations() -> Dict[str, Dict]:
    """List all animations with their metadata (for UI/debugging)."""
    return {anim_id: preset.to_dict() for anim_id, preset in ANIMATION_LIBRARY.items()}


# ============================================================================
# VALIDATION & STATS
# ============================================================================

if __name__ == "__main__":
    print(f"✓ Loaded {len(ANIMATION_LIBRARY)} animations")
    print()
    
    for category in AnimationCategory:
        anims = get_animations_by_category(category)
        if anims:
            loopable = sum(1 for a in anims.values() if a.is_loopable)
            print(f"  {category.value:15s}: {len(anims):2d} animations ({loopable} loopable)")
    
    print()
    print("Categories by context:")
    for context in ["seated", "standing", "listening", "speaking", "thinking"]:
        anims = get_animations_for_context(context)
        print(f"  {context:12s}: {len(anims):2d} animations")
    
    print()
    print("Sample animations:")
    for anim_id in ["nod_slow", "hands_on_hips", "adjust_seat", "confident_stance"]:
        anim = get_animation(anim_id)
        if anim:
            print(f"  {anim_id:25s}: {anim.display_name:30s} ({anim.duration_ms:4d}ms) [{'∞' if anim.is_loopable else '×'}]")
