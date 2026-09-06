from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .core import OrderEvent, OrderEventType, SpatialObject, Vec3


class ConsequenceType(str, Enum):
    IMPACT = "impact"
    TOUCH = "touch"
    REACH = "reach"
    FALL_OR_STUMBLE = "fall_or_stumble"
    PROP_INTERACTION = "prop_interaction"
    CAMERA_ATTENTION = "camera_attention"
    SPEECH_OR_EMOTION = "speech_or_emotion"
    REORDER = "structural_reorder"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class KineticEstimate:
    """Approximate physics-informed reading of an event.

    This is not a full rigid-body solver. It is the bridge between raw motion
    and performance continuity: direction, intensity, contact, mass proxy, and
    likely affected body/object chain.
    """
    force_vector: Tuple[float, float, float]
    joule_load: float
    contact_point: Optional[Tuple[float, float, float]] = None
    estimated_mass: float = 1.0
    confidence: float = 0.5


@dataclass(slots=True)
class MotionCorrection:
    """A performance-preserving correction request for choreography/mocap."""
    body_region: str
    correction: str
    direction: Tuple[float, float, float]
    timing_offset_seconds: float = 0.0
    strength: float = 0.5
    preserve_actor_intent: bool = True


@dataclass(slots=True)
class PerformanceConsequence:
    """Bubble Stack output for EVO/choreography.

    Bubble Stack predicts consequence. EVO interprets dramatically.
    Choreography constrains. Motion capture / animation stitches the correction
    back into the actor or prop performance.
    """
    event_id: str
    consequence_type: ConsequenceType
    source_id: Optional[str]
    target_id: Optional[str]
    kinetic_estimate: KineticEstimate
    affected_chain: List[str]
    body_instructions: List[str]
    voice_instructions: List[str]
    sound_instructions: List[str]
    camera_instructions: List[str]
    motion_corrections: List[MotionCorrection]
    summary: str
    confidence: float = 0.5
    metadata: Dict[str, object] = field(default_factory=dict)


def _vec_tuple(v: Vec3) -> Tuple[float, float, float]:
    return (round(v.x, 5), round(v.y, 5), round(v.z, 5))


def _dominant_axis_name(direction: Vec3) -> str:
    comps = [(abs(direction.x), "x"), (abs(direction.y), "y"), (abs(direction.z), "z")]
    return max(comps, key=lambda item: item[0])[1]


def classify_consequence(event: OrderEvent) -> ConsequenceType:
    if event.event_type == OrderEventType.SURFACE_CONTACT:
        if event.intensity >= 1.0:
            return ConsequenceType.IMPACT
        return ConsequenceType.TOUCH
    if event.event_type in {OrderEventType.VOLATILE_MOTION, OrderEventType.VELOCITY_CHANGE}:
        return ConsequenceType.REACH
    if event.event_type == OrderEventType.BOUNDARY_CROSSING:
        return ConsequenceType.FALL_OR_STUMBLE
    if event.event_type == OrderEventType.CAMERA_ATTENTION:
        return ConsequenceType.CAMERA_ATTENTION
    if event.event_type == OrderEventType.SPEECH:
        return ConsequenceType.SPEECH_OR_EMOTION
    if event.event_type == OrderEventType.STRUCTURAL_REORDER:
        return ConsequenceType.REORDER
    return ConsequenceType.UNKNOWN


def build_performance_consequence(
    event: OrderEvent,
    *,
    event_index: int,
    applied_joules: float,
    objects: Dict[str, SpatialObject],
) -> Optional[PerformanceConsequence]:
    """Convert an OrderEvent into a first-pass EVO/choreography instruction.

    This intentionally uses simple, inspectable heuristics. The point is to make
    the kinetic interpretation path real now, while leaving clear hooks for
    advanced mass/material/skeleton solvers later.
    """
    ctype = classify_consequence(event)
    if ctype == ConsequenceType.UNKNOWN and event.intensity < 0.25:
        return None

    source = objects.get(event.source_id or "")
    mass = _mass_proxy(source)
    force_vector = event.direction.normalized() * max(0.0, applied_joules)
    estimate = KineticEstimate(
        force_vector=_vec_tuple(force_vector),
        joule_load=round(applied_joules, 5),
        contact_point=_vec_tuple(event.origin),
        estimated_mass=round(mass, 4),
        confidence=min(0.95, 0.35 + min(0.6, applied_joules / 4.0)),
    )

    affected_chain = _affected_chain(event, source, ctype)
    body, voice, sound, camera, corrections = _instructions(event, estimate, affected_chain, ctype)
    summary = _summary(event, ctype, affected_chain, estimate)
    return PerformanceConsequence(
        event_id=f"evt_{event_index:05d}_{event.event_type.value}",
        consequence_type=ctype,
        source_id=event.source_id,
        target_id=event.target_id,
        kinetic_estimate=estimate,
        affected_chain=affected_chain,
        body_instructions=body,
        voice_instructions=voice,
        sound_instructions=sound,
        camera_instructions=camera,
        motion_corrections=corrections,
        summary=summary,
        confidence=estimate.confidence,
        metadata={"order_event_type": event.event_type.value, "raw_intensity": round(event.intensity, 5)},
    )


def _mass_proxy(obj: Optional[SpatialObject]) -> float:
    if obj is None:
        return 1.0
    tags = set(obj.semantic_tags)
    if "human" in tags or "actor" in tags or "body" in tags:
        return 70.0
    if "hand" in tags or "limb" in tags:
        return 4.0
    if "prop" in tags:
        return max(0.5, min(15.0, obj.bounds.volume * 20.0))
    return max(0.2, min(80.0, obj.bounds.volume * 35.0))


def _affected_chain(event: OrderEvent, source: Optional[SpatialObject], ctype: ConsequenceType) -> List[str]:
    tags = set(source.semantic_tags) if source else set()
    if ctype == ConsequenceType.IMPACT:
        if "head" in tags or "face" in tags or "jaw" in tags:
            return ["contact point", "head", "neck", "shoulders", "torso", "balance"]
        if "hand" in tags or "arm" in tags:
            return ["contact point", "hand", "forearm", "elbow", "shoulder", "torso"]
        return ["contact point", "target body/object", "support chain", "balance"]
    if ctype == ConsequenceType.TOUCH:
        return ["contact point", "local surface", "posture", "attention/gaze"]
    if ctype == ConsequenceType.REACH:
        return ["moving part", "nearest object", "shoulder/torso compensation", "camera interest"]
    if ctype == ConsequenceType.FALL_OR_STUMBLE:
        return ["center of mass", "hips", "knees", "feet", "ground/contact surface"]
    if ctype == ConsequenceType.CAMERA_ATTENTION:
        return ["camera target", "face/hands", "foreground composition"]
    return ["changed region", "connected regions"]


def _instructions(event: OrderEvent, estimate: KineticEstimate, chain: List[str], ctype: ConsequenceType):
    d = event.direction.normalized()
    axis = _dominant_axis_name(d)
    strength = min(1.0, estimate.joule_load / 3.0)
    dir_tuple = estimate.force_vector
    body: List[str] = []
    voice: List[str] = []
    sound: List[str] = []
    camera: List[str] = []
    corrections: List[MotionCorrection] = []

    if ctype == ConsequenceType.IMPACT:
        body = [
            "Preserve actor intent, then correct affected chain along force vector.",
            "Apply immediate local reaction at contact point.",
            "Delay connected body regions progressively down the affected chain.",
        ]
        voice = ["Cut or compress vocalization during the impact frame if mouth/breath are affected."]
        sound = ["Layer contact sound, cloth shift, and support/balance sound according to Joule Load."]
        camera = ["Prioritize the contact point and first visible reaction if this is the active action beat."]
        for i, region in enumerate(chain[:5]):
            corrections.append(MotionCorrection(region, f"kinetic reaction along {axis}-dominant force path", dir_tuple, i * 0.055, max(0.15, strength * (1.0 - i * 0.12))))
    elif ctype == ConsequenceType.TOUCH:
        body = ["Apply subtle local compression or posture acknowledgment without overriding performance."]
        voice = ["Allow a small pause, breath, or attention shift if dramatically relevant."]
        sound = ["Use low-intensity contact/cloth sound only if audible in scene context."]
        camera = ["Maintain relationship framing unless the touch is the story beat."]
        corrections.append(MotionCorrection(chain[0], "subtle contact acknowledgment", dir_tuple, 0.0, min(0.35, strength)))
    elif ctype == ConsequenceType.REACH:
        body = ["Preserve reaching intent while aligning limb, shoulder, and torso continuity."]
        camera = ["Pre-warm focus toward likely interaction target."]
        corrections.append(MotionCorrection("moving limb", "directional reach continuity", dir_tuple, 0.0, max(0.2, strength)))
    elif ctype == ConsequenceType.FALL_OR_STUMBLE:
        body = ["Correct center-of-mass path and foot compensation before allowing fall/stumble."]
        voice = ["Add breath disruption only if balance loss is significant."]
        sound = ["Foot scrape, floor impact, or prop rattle if contact follows."]
        camera = ["Protect readability of balance failure and recovery path."]
        corrections.append(MotionCorrection("center of mass", "balance correction/fall continuity", dir_tuple, 0.0, max(0.25, strength)))
    else:
        body = ["Treat as contextual change; preserve performance unless connected systems request correction."]

    return body, voice, sound, camera, corrections


def _summary(event: OrderEvent, ctype: ConsequenceType, chain: List[str], estimate: KineticEstimate) -> str:
    src = event.source_id or "unknown source"
    tgt = event.target_id or "context/world"
    return (
        f"{ctype.value} consequence from {src} toward {tgt}; "
        f"Joule Load {estimate.joule_load:.2f}; affected chain: {', '.join(chain)}."
    )

