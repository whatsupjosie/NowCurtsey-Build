"""
affect_choreo_bridge.py — Affect Engine → Choreography Bridge
══════════════════════════════════════════════════════════════

Connects two existing, live systems that were never wired to each other:

  AffectContextEngine (in alex_core.py, running per-turn)
    → dramatic_intensity  (payload["animation"]["intensity"], 0.0–1.0)
    → steerage state      (payload["reading"]["state"])

  ChoreoController.cue_action()
    → intensity param     (0.1–3.0, scales animation duration)

  AnimationAuthority.submit()
    → weight param        (0.0–1.0, controls blend strength of emotional layer)

WHAT THIS DOES:
  When the affect engine has enough confidence (>= CONFIDENCE_THRESHOLD),
  it modulates the choreography layer for a named avatar:
    1. Maps dramatic_intensity (0–1) to cue_action intensity (0.1–3.0)
    2. Maps state → an appropriate emotional overlay action
    3. Submits an AnimationAuthority weight for that overlay layer

WHAT THIS DOES NOT DO:
  - Does not replace or override existing choreography cues
  - Does not touch the ANCHOR/WITNESS safety states (handled by alex_core)
  - Does not run without sufficient affect engine confidence
  - Does not create a new selection system — it modulates existing selection

SEAMS:
  Call bridge.apply(alex, choreo_controller) after each AlexCore.process_message().
  That's it. Both systems already exist; this is the wire between them.

Rear View Foresight LLC — Feic Mo Chroí — 2026-08-23
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

from modules.affect_context_engine import route

if TYPE_CHECKING:
    from modules.alex_core import AlexCore
    from modules.choreography_controller import ChoreoController

logger = logging.getLogger("pubcast.affect_choreo_bridge")

# ── Configuration ──────────────────────────────────────────────────────────────

# Minimum confidence before the bridge modulates anything.
# Below this the affect engine is still "observing" — don't steer yet.
CONFIDENCE_THRESHOLD: float = 0.30

# Maps affect engine state → the emotional overlay action to cue.
# These are all real actions in DEFAULT_ACTIONS ("emotional" category).
# Only states that have a natural choreographic expression are mapped.
STATE_TO_ACTION: Dict[str, str] = {
    "flow":       "relaxed_idle",       # engaged, going well
    "steady":     "idle_look_around",   # neutral, alert
    "friction":   "thoughtful_idle",    # working through resistance
    "escalation": "idle_weight_shift",  # rising tension/urgency
    "play":       "relaxed_idle",       # light, playful
    "observing":  None,                 # not enough data yet — no cue
}

# Maps affect dramatic intensity (0.0–1.0) to cue_action intensity (0.1–3.0).
# Linear scale, clamped. At 0.0 → 0.5 (subdued), at 1.0 → 2.5 (heightened).
INTENSITY_MIN: float = 0.5
INTENSITY_MAX: float = 2.5

# AnimationAuthority layer name for affect-driven emotional overlays.
AFFECT_LAYER: str = "affect_emotional"

# Priority of the affect layer in AnimationAuthority arbitration.
# Default actions use priority 50; affect overlay uses 30 — lower priority,
# yields to explicit cues, blends softly rather than overriding.
AFFECT_PRIORITY: int = 30


# ── Bridge ─────────────────────────────────────────────────────────────────────

class AffectChoreoBridge:
    """
    Wire between AffectContextEngine output and ChoreoController/AnimationAuthority.

    Usage:
        bridge = AffectChoreoBridge()
        result = await alex.process_message(text, ...)
        await bridge.apply(alex, choreo_controller, room="main", avatar_id="pete")
    """

    def __init__(self) -> None:
        self._last_state: Optional[str] = None
        self._last_intensity: float = 0.0

    async def apply(
        self,
        alex: "AlexCore",
        choreo: "ChoreoController",
        room: str,
        avatar_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Read the affect engine's current reading from alex._last_affect_reading
        and modulate the choreography layer if confidence is sufficient.

        Returns a dict describing what was applied, or None if nothing fired.
        """
        payload = getattr(alex, "_last_affect_reading", None)
        if payload is None:
            return None

        conf = payload.get("reading", {}).get("confidence", 0.0)
        if conf < CONFIDENCE_THRESHOLD:
            logger.debug(
                f"Affect conf {conf:.2f} < threshold {CONFIDENCE_THRESHOLD} — no choreo modulation"
            )
            return None

        state = payload.get("reading", {}).get("state", "observing")

        # dramatic_intensity lives in payload["performance"], and route() is the
        # function that surfaces it as the animation-facing view. Calling route()
        # is required — the raw evaluate() payload has NO "animation" key at all.
        # (Reading payload["animation"]["intensity"] directly silently yields 0.0.)
        try:
            routed = route(payload)
            drama = routed["animation"]["intensity"]
        except Exception as exc:  # never let a routing change break the bridge
            logger.warning(f"route() failed, falling back to raw performance read: {exc}")
            drama = payload.get("performance", {}).get("dramatic_intensity", 0.0)

        # Map to cue_action intensity
        choreo_intensity = INTENSITY_MIN + drama * (INTENSITY_MAX - INTENSITY_MIN)
        choreo_intensity = max(0.1, min(3.0, choreo_intensity))

        # Select the emotional overlay action for this state
        action = STATE_TO_ACTION.get(state)
        if action is None:
            logger.debug(f"Affect state={state!r} has no mapped action — no choreo modulation")
            return None

        # Cue the emotional overlay
        cue_result = await choreo.cue_action(
            room=room,
            avatar_id=avatar_id,
            action=action,
            intensity=choreo_intensity,
        )

        # Submit to AnimationAuthority if present
        anim_authority = getattr(choreo, "_anim_authority", None)
        if anim_authority is not None:
            # Weight the affect layer by confidence — at 0.30 conf it blends softly,
            # at 1.0 conf it blends fully. Never overrides explicit cues (priority 30 < 50).
            weight = min(1.0, conf)
            anim_authority.submit(
                performer_id=avatar_id,
                layer=AFFECT_LAYER,
                pose={"affect_state": state, "dramatic_intensity": drama},
                priority=AFFECT_PRIORITY,
                weight=weight,
            )

        result = {
            "fired": True,
            "state": state,
            "confidence": conf,
            "dramatic_intensity": drama,
            "choreo_action": action,
            "choreo_intensity": choreo_intensity,
            "authority_weight": min(1.0, conf) if anim_authority else None,
        }

        if state != self._last_state or abs(drama - self._last_intensity) > 0.1:
            logger.info(
                f"Affect choreo: {avatar_id} state={state} drama={drama:.2f} "
                f"→ action={action!r} intensity={choreo_intensity:.2f} "
                f"weight={result['authority_weight']}"
            )
            self._last_state = state
            self._last_intensity = drama

        return result


# Module-level default instance
_bridge: Optional[AffectChoreoBridge] = None


def get_bridge() -> AffectChoreoBridge:
    """Get or create the module-level bridge instance."""
    global _bridge
    if _bridge is None:
        _bridge = AffectChoreoBridge()
    return _bridge
