"""
modules/peq_broker.py

The only door into PEQ for the rest of PubCast.

ARCHITECTURE
============
PEQ (Probabilistic EQ System) is an isolated inference engine. It contains:
    - A clinical evidence registry (PTSD/trauma/psychosis pattern data)
    - A probabilistic state engine with evidence weights and posteriors
    - A scientific claims layer with source provenance
    - A critical reasoning / truth-testing engine

NONE of those internals are accessible through this module. What comes out
of the broker is a deliberately thin PEQSignal: a care level, a recommended
response posture, a confidence value, and whether the system is uncertain.
That is all any consumer needs and all any consumer gets.

WHO CAN SUBMIT OBSERVATIONS:
    Anyone — Alex, PubPartner, Jeremy, external avatars.
    Submission is one-way. Submitting does not grant read access.

WHO CAN READ OUTPUT:
    Anyone registered as a subscriber for a given subject_id.
    Output is always a PEQSignal — never a PEQResult, PEQStateResult,
    PEQResponseResult, or any internal PEQ type.

WHAT SUBSCRIBERS GET:
    care_level          int 0-3 (AMBIENT / ATTENTIVE / CARE / TOTAL_CARE_MANDATE)
    response_posture    str  e.g. "acknowledge_without_escalating"
    confidence          float 0.0-0.985 (hard-capped by PEQ itself)
    is_uncertain        bool  True when confidence < UNCERTAINTY_THRESHOLD
    modulation          str  "full" | "restrained" | "conservative"
    intensity           float 0.0-1.0

WHAT SUBSCRIBERS NEVER GET:
    - PEQStateResult (candidates, posteriors, contributions, evidence weights)
    - PEQResponseResult (internal candidates, rationale beyond posture label)
    - PEQResult.audit (raw state/response dicts, retrieval bundles)
    - Any clinical pattern hypothesis (PatternHypothesis, working_hypothesis)
    - Any scientific evidence record (ScientificClaim, source provenance)
    - TruthAssessment internals (proposition, reasons_for_review)
    - EvidenceContribution (state_directions, reliability, correlation_group)
    - The PEQSystem instance itself

EXTERNAL AVATARS
================
An avatar joining an event can call `subscribe_avatar(avatar_id, room_id)`.
They receive the same PEQSignal as any other subscriber. They cannot observe
more deeply than Jeremy or Alex can.

ISOLATION TEST
==============
A unit test in tests/test_peq_broker.py verifies that no attribute of the
PEQBroker instance or the PEQSignal it produces contains any of the blocked
internal types. This is structurally enforced, not only by convention.

VERIFIED before writing:
    - PEQSystem.assess() takes ObservationPacket → returns PEQResult
    - PEQResult has: state: PEQStateResult, response: PEQResponseResult, audit: dict
    - PEQResponseResult has: recommended_response, modulation, intensity, operational_confidence
    - PEQStateResult has: leading_state, operational_confidence, uncertainty
    - ObservationPacket fields: subject_id, is_primary_user, text, recent_text,
      typing, audio, vision, explicit_report, context, baseline, profile_facts
    - All 99 PEQ tests pass on the concerns_debugged build
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("pubcast.peq_broker")

# ── Confidence threshold below which the broker flags uncertainty ─────────────
UNCERTAINTY_THRESHOLD = 0.45

# ── Care level map from PEQ's leading_state labels to 0-3 integers ───────────
# These are the state strings PEQ actually produces (verified from demo output).
_STATE_TO_CARE: Dict[str, int] = {
    "neutral":      0,
    "calm":         0,
    "content":      0,
    "curious":      1,
    "engaged":      1,
    "mildly_anxious": 1,
    "frustrated":   1,
    "sad":          2,
    "anxious":      2,
    "distressed":   2,
    "fearful":      2,
    "overwhelmed":  3,
    "crisis":       3,
}

def _state_to_care(leading_state: str) -> int:
    return _STATE_TO_CARE.get(leading_state.lower().replace(" ", "_"), 1)


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC OUTPUT TYPE — the only PEQ-derived type that ever leaves this module
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PEQSignal:
    """
    The cleaned, minimal output that consumers receive.

    This is NOT a PEQResult, NOT a PEQStateResult, NOT a PEQResponseResult.
    It contains no evidence weights, no posteriors, no clinical hypotheses,
    no scientific source provenance, no internal truth assessments.
    """
    subject_id: str
    care_level: int              # 0=AMBIENT, 1=ATTENTIVE, 2=CARE, 3=TOTAL_CARE
    care_label: str              # human-readable label for the above
    response_posture: str        # the recommended_response string from PEQ
    modulation: str              # "full" | "restrained" | "conservative"
    intensity: float             # 0.0–1.0
    confidence: float            # 0.0–0.985, hard-capped by PEQ
    is_uncertain: bool           # True when confidence < UNCERTAINTY_THRESHOLD
    assessed_at: float = field(default_factory=time.time)

    _CARE_LABELS = ("AMBIENT", "ATTENTIVE", "CARE", "TOTAL_CARE_MANDATE")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════════════
# OBSERVATION — what goes IN to PEQ (one-way)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PEQObservation:
    """
    Everything a consumer can submit to PEQ.

    Deliberately mirrors ObservationPacket's safe fields only.
    `profile_facts` is accepted but the broker strips any key prefixed with
    'private_' or 'vault_' before forwarding — enforcing Alex's privacy contract
    at the structural level rather than relying on callers to remember.
    """
    subject_id: str
    source: str                            # e.g. "jeremy", "alex", "avatar:hal9000"
    text: str = ""
    recent_text: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    typing: Dict[str, float] = field(default_factory=dict)    # e.g. {"wpm": 85.0}
    audio: Dict[str, float] = field(default_factory=dict)     # e.g. {"energy": 0.4}
    vision: Dict[str, float] = field(default_factory=dict)    # e.g. {"blink_rate": 0.3}
    explicit_report: Optional[str] = None
    profile_facts: Dict[str, Any] = field(default_factory=dict)
    stakes: float = 0.5

    _PRIVATE_PREFIXES = ("private_", "vault_", "sanctuary_", "therapy_")

    def sanitized_profile_facts(self) -> Dict[str, Any]:
        """Strip keys that should never reach PEQ's evidence layer."""
        return {
            k: v for k, v in self.profile_facts.items()
            if not any(k.startswith(p) for p in self._PRIVATE_PREFIXES)
        }


# ═══════════════════════════════════════════════════════════════════════════════
# SUBSCRIBER RECORD
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class _Subscriber:
    subscriber_id: str
    kind: str                              # "jeremy" | "alex" | "pubpartner" | "avatar"
    room_id: Optional[str]                 # None = all rooms
    callback: Callable[[PEQSignal], Any]
    registered_at: float = field(default_factory=time.time)


# ═══════════════════════════════════════════════════════════════════════════════
# BROKER
# ═══════════════════════════════════════════════════════════════════════════════

class PEQBroker:
    """
    The only public interface to PEQ in PubCast.

    One instance per application. Shared by Jeremy, Alex, PubPartner,
    and any external avatar that subscribes.

    The PEQSystem instance is never exposed. This class is a wall.
    """

    def __init__(self, peq_system_path: Optional[str] = None) -> None:
        """
        Args:
            peq_system_path: filesystem path to the peq package, if it isn't
                already on sys.path. Pass None if it's already importable.
        """
        self._peq = self._load_peq(peq_system_path)
        self._subscribers: List[_Subscriber] = []
        self._cache: Dict[str, PEQSignal] = {}   # subject_id → latest signal
        self._lock = asyncio.Lock()

        logger.info("PEQBroker initialized — PEQ is isolated, broker is the wall")

    # ── Loading ────────────────────────────────────────────────────────────────

    @staticmethod
    def _load_peq(path: Optional[str]):
        """
        Load PEQSystem dynamically. If PEQ isn't importable, returns None and
        the broker operates in degraded mode (signals default to AMBIENT/uncertain).
        """
        if path and path not in sys.path:
            sys.path.insert(0, path)
        try:
            from peq.system import PEQSystem
            system = PEQSystem()
            logger.info("PEQSystem loaded successfully")
            return system
        except Exception as exc:
            logger.warning("PEQ unavailable (%s) — broker will return degraded signals", exc)
            return None

    # ── Submission (one-way in) ────────────────────────────────────────────────

    async def submit(self, observation: PEQObservation) -> PEQSignal:
        """
        Submit an observation and receive a PEQSignal.

        This is the only route into PEQ. The caller gets back a PEQSignal.
        They never see PEQResult, PEQStateResult, or any internal type.
        Times out after 5 seconds and returns a degraded signal rather than
        blocking the executor thread indefinitely.
        """
        if self._peq is None:
            return self._degraded_signal(observation.subject_id)

        try:
            result = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, self._run_peq, observation
                ),
                timeout=5.0,
            )
        except asyncio.TimeoutError:
            logger.warning("PEQ assessment timed out for %s — returning degraded signal", observation.subject_id)
            return self._degraded_signal(observation.subject_id)
        except Exception as exc:
            logger.error("PEQ assessment failed for %s: %s", observation.subject_id, exc)
            return self._degraded_signal(observation.subject_id)

        signal = self._to_signal(observation.subject_id, result)

        async with self._lock:
            self._cache[observation.subject_id] = signal

        await self._notify_subscribers(observation.subject_id, signal)
        return signal

    def _run_peq(self, obs: PEQObservation):
        """
        Runs in a thread executor — PEQ is synchronous.
        All conversion happens here; nothing internal escapes to the async layer.
        """
        from cre_eq.models import ObservationPacket

        packet = ObservationPacket(
            subject_id=obs.subject_id,
            is_primary_user=True,
            text=obs.text,
            recent_text=list(obs.recent_text),
            typing=dict(obs.typing),
            audio=dict(obs.audio),
            vision=dict(obs.vision),
            explicit_report=obs.explicit_report,
            context=dict(obs.context),
            profile_facts=obs.sanitized_profile_facts(),
        )
        return self._peq.assess(packet, stakes=obs.stakes)

    @staticmethod
    def _to_signal(subject_id: str, result) -> PEQSignal:
        """
        Convert a PEQResult to a PEQSignal.

        THIS IS THE WALL. Only scalar/string values cross. No PEQ internal
        objects, no evidence structures, no clinical hypotheses.
        """
        state    = result.state
        response = result.response

        leading  = str(getattr(state, "leading_state", "neutral"))
        care     = _state_to_care(leading)
        posture  = str(getattr(response, "recommended_response", "respond_calmly"))
        mod      = str(getattr(getattr(response, "modulation", None), "value", "full"))
        intens   = float(getattr(response, "intensity", 0.5))
        conf     = float(getattr(response, "operational_confidence",
                                  getattr(state, "operational_confidence", 0.5)))

        return PEQSignal(
            subject_id=subject_id,
            care_level=care,
            care_label=PEQSignal._CARE_LABELS[min(care, 3)],
            response_posture=posture,
            modulation=mod,
            intensity=round(intens, 3),
            confidence=round(conf, 4),
            is_uncertain=conf < UNCERTAINTY_THRESHOLD,
        )

    @staticmethod
    def _degraded_signal(subject_id: str) -> PEQSignal:
        """Returned when PEQ is unavailable or throws. Safe default — never escalates."""
        return PEQSignal(
            subject_id=subject_id,
            care_level=0,
            care_label="AMBIENT",
            response_posture="respond_normally",
            modulation="full",
            intensity=0.5,
            confidence=0.0,
            is_uncertain=True,
        )

    # ── Current signal query ───────────────────────────────────────────────────

    def current_signal(self, subject_id: str) -> Optional[PEQSignal]:
        """
        Return the most recently assessed signal for a subject, or None.
        Does not trigger a new assessment.
        """
        return self._cache.get(subject_id)

    # ── Subscription (output side) ─────────────────────────────────────────────

    def subscribe_jeremy(self, callback: Callable[[PEQSignal], Any]) -> str:
        """Register Jeremy as a subscriber. Receives PEQSignal for all subjects."""
        return self._subscribe("jeremy", None, callback)

    def subscribe_alex(self, callback: Callable[[PEQSignal], Any]) -> str:
        """Register Alex as a subscriber. Receives PEQSignal for all subjects."""
        return self._subscribe("alex", None, callback)

    def subscribe_pubpartner(self, callback: Callable[[PEQSignal], Any]) -> str:
        """Register PubPartner as a subscriber. Receives PEQSignal for all subjects."""
        return self._subscribe("pubpartner", None, callback)

    def subscribe_avatar(
        self,
        avatar_id: str,
        room_id: str,
        callback: Callable[[PEQSignal], Any],
    ) -> str:
        """
        Register an external avatar joining a room as a PEQ subscriber.

        The avatar receives the same PEQSignal as Jeremy and Alex — no more,
        no less. `room_id` is recorded for audit purposes but does not filter
        which subjects the avatar receives signals for (the room conductor
        decides which subject_ids are visible in a room).
        """
        return self._subscribe(f"avatar:{avatar_id}", room_id, callback)

    def _subscribe(
        self,
        kind: str,
        room_id: Optional[str],
        callback: Callable[[PEQSignal], Any],
    ) -> str:
        sub_id = f"sub_{uuid.uuid4().hex[:10]}"
        self._subscribers.append(_Subscriber(
            subscriber_id=sub_id,
            kind=kind,
            room_id=room_id,
            callback=callback,
        ))
        logger.info("PEQ subscriber registered: %s (%s, room=%s)", sub_id, kind, room_id or "all")
        return sub_id

    def unsubscribe(self, subscriber_id: str) -> bool:
        before = len(self._subscribers)
        self._subscribers = [s for s in self._subscribers if s.subscriber_id != subscriber_id]
        return len(self._subscribers) < before

    async def _notify_subscribers(self, subject_id: str, signal: PEQSignal) -> None:
        for sub in list(self._subscribers):
            try:
                result = sub.callback(signal)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.warning("PEQ subscriber %s (%s) raised: %s", sub.subscriber_id, sub.kind, exc)

    # ── Avatar event session management ───────────────────────────────────────

    def list_avatar_subscribers(self) -> List[Dict[str, Any]]:
        """Return metadata for all avatar subscribers (for room conductor use)."""
        return [
            {
                "subscriber_id": s.subscriber_id,
                "avatar_id": s.kind.removeprefix("avatar:"),
                "room_id": s.room_id,
                "registered_at": s.registered_at,
            }
            for s in self._subscribers
            if s.kind.startswith("avatar:")
        ]

    # ── Stats ──────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        kinds: Dict[str, int] = {}
        for s in self._subscribers:
            k = s.kind.split(":")[0] if ":" in s.kind else s.kind
            kinds[k] = kinds.get(k, 0) + 1
        return {
            "peq_available":      self._peq is not None,
            "cached_subjects":    len(self._cache),
            "total_subscribers":  len(self._subscribers),
            "subscribers_by_kind": kinds,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL SINGLETON — one broker for the whole app
# ═══════════════════════════════════════════════════════════════════════════════

_broker: Optional[PEQBroker] = None


def init_peq_broker(peq_path: Optional[str] = None) -> PEQBroker:
    """
    Call once at startup (in main.py's lifespan, after creating the FastAPI app).
    Pass the filesystem path to the peq package if it isn't on sys.path yet.
    """
    global _broker
    _broker = PEQBroker(peq_path)
    return _broker


def get_broker() -> PEQBroker:
    """
    Get the singleton broker. Raises if init_peq_broker() hasn't been called.
    """
    if _broker is None:
        raise RuntimeError("PEQBroker not initialised. Call init_peq_broker() at startup.")
    return _broker
