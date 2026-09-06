"""
modules/evidence_layer.py — Evidence Layer & Theory Engine
===========================================================
Copyright (c) 2024-2025 Rear View Foresight LLC
"Feic Mo Chroí — See My Heart"

The interpretive layer that sits between raw VDI signals and memory.

WHAT THIS IS NOT:
    Not a classifier. Not a sentiment tagger. Not a personality profiler.

WHAT THIS IS:
    A forensic accumulator. It observes events, attaches multiple coexisting
    interpretations with confidence scores, lets them compete over time,
    and builds living hypotheses — theories that strengthen, weaken,
    contradict, and decay based on evidence.

THREE CORE STRUCTURES:

    EvidenceMarker  — A single observation with multiple interpretation
                      candidates. Contradictions are preserved, not resolved.

    EvidenceTheory  — A named hypothesis built from accumulated markers.
                      Supported by evidence. Contradicted by evidence.
                      Carries confidence. Decays when not reinforced.

    EvidenceLayer   — The engine. Receives signals from VDI, Prosody,
                      and MemoryTurns. Emits markers. Builds and maintains
                      theories. Feeds distillation back into UniversalMemorySystem.

DECAY MODEL:
    Evidence is not permanent. Each marker has a decay_rate.
    Unreinforced theories weaken. Contradicted theories destabilize.
    This is not a bug — it's how the system stays honest.

INTEGRATION POINTS:
    - Called from EVOOrchestrator.tick() after VDI update
    - Feeds get_pete_briefing() via EvidenceLayer.get_active_theories()
    - distill_evidence() called alongside UniversalMemorySystem.distill_session()
    - SQLite-backed, same data/ directory as universal_memory_system.py

Public API:
    EvidenceLayer
        .observe(event, source, signals, context)   → EvidenceMarker
        .get_active_theories()                       → List[EvidenceTheory]
        .get_theory_briefing()                       → str
        .distill_evidence()                          → None
        .load_state()                                → None
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DB_PATH = Path("data/pubcast_memory.db")


# ─────────────────────────────────────────────────────────────────────────────
# DECAY RATES
# ─────────────────────────────────────────────────────────────────────────────

class DecayRate(str, Enum):
    """How quickly an evidence marker's weight erodes over time."""
    FAST    = "fast"    # Situational — gone in ~2 sessions if unreinforced
    MEDIUM  = "medium"  # Pattern — survives ~5 sessions
    SLOW    = "slow"    # Deep pattern — survives ~15 sessions
    ANCHOR  = "anchor"  # Foundational — only contradictions weaken it

# Half-life in sessions (exponential decay)
DECAY_HALF_LIFE: Dict[str, float] = {
    DecayRate.FAST:   2.0,
    DecayRate.MEDIUM: 5.0,
    DecayRate.SLOW:   15.0,
    DecayRate.ANCHOR: 60.0,
}


# ─────────────────────────────────────────────────────────────────────────────
# OBSERVABLE EVENTS
# Raw event taxonomy. No interpretation yet.
# ─────────────────────────────────────────────────────────────────────────────

class ObservableEvent(str, Enum):
    # Prosody / speech pattern events
    INTERRUPT_SPIKE         = "interrupt_spike"
    RAPID_TOPIC_SWITCH      = "rapid_topic_switch"
    PACING_ACCELERATION     = "pacing_acceleration"
    PACING_DECELERATION     = "pacing_deceleration"
    SENTIMENT_INVERSION     = "sentiment_inversion"
    PROFANITY_SPIKE         = "profanity_spike"
    SILENCE_EXTENDED        = "silence_extended"
    LAUGHTER_BURST          = "laughter_burst"
    CONTRADICTORY_PHRASING  = "contradictory_phrasing"

    # Audience / VDI events
    AUDIENCE_ENGAGEMENT_DROP    = "audience_engagement_drop"
    AUDIENCE_ENGAGEMENT_SURGE   = "audience_engagement_surge"
    IDENTITY_MOMENT_ENTERED     = "identity_moment_entered"
    IDENTITY_MOMENT_SUSTAINED   = "identity_moment_sustained"
    CONFUSION_SPIKE             = "confusion_spike"
    LAUGHTER_AFTER_TENSION      = "laughter_after_tension"

    # Relational / narrative events
    SELF_DISCLOSURE             = "self_disclosure"
    TOPIC_AVOIDANCE             = "topic_avoidance"
    VULNERABILITY_THEN_PIVOT    = "vulnerability_then_pivot"
    RECURRING_TOPIC_RETURN      = "recurring_topic_return"
    HELP_SEEKING                = "help_seeking"
    CREATIVE_DEFLECTION         = "creative_deflection"

    # Memory / cross-session events
    PATTERN_RECURRENCE          = "pattern_recurrence"
    SELF_REPORT_MISMATCH        = "self_report_mismatch"
    PRIOR_SESSION_ECHO          = "prior_session_echo"


# ─────────────────────────────────────────────────────────────────────────────
# INTERPRETATION CANDIDATE
# One possible meaning of an observation. Confidence is not certainty.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class InterpretationCandidate:
    """
    One possible meaning of an observed event.
    Multiple candidates coexist per marker — they are not resolved.
    """
    hypothesis:     str
    confidence:     float       # 0.0–1.0 — not a probability, a weight
    agent_source:   str         = "vdi"   # which agent generated this reading
    notes:          str         = ""

    def decayed(self, sessions_elapsed: float, decay_rate: str) -> "InterpretationCandidate":
        """Return a copy with confidence decayed by elapsed sessions."""
        half_life = DECAY_HALF_LIFE.get(decay_rate, 5.0)
        factor = math.pow(0.5, sessions_elapsed / half_life)
        return InterpretationCandidate(
            hypothesis   = self.hypothesis,
            confidence   = round(self.confidence * factor, 4),
            agent_source = self.agent_source,
            notes        = self.notes,
        )


# ─────────────────────────────────────────────────────────────────────────────
# EVIDENCE MARKER
# One observation. Multiple interpretations. Contradictions preserved.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EvidenceMarker:
    """
    A single observed event with multiple coexisting interpretations.

    This is Layer 1 + Layer 2 from the architecture:
        Layer 1: What happened (observation, source, timestamp)
        Layer 2: What it might mean (possible_interpretations — plural, unresolved)

    Contradictions are first-class citizens. A marker that says
    "this could be frustration OR excitement" is more honest than
    one that picks one.
    """
    marker_id:                  str
    observation:                str
    source:                     str             # "prosody_engine" | "vdi_engine" | "pete" | etc.
    timestamp:                  float
    session_id:                 str
    possible_interpretations:   List[InterpretationCandidate]
    linked_context:             List[str]       = field(default_factory=list)
    contradiction_flags:        List[str]       = field(default_factory=list)
    decay_rate:                 str             = DecayRate.MEDIUM
    narrative_weight:           float           = 0.5   # 0=forgettable, 1=critical
    vdi_score_at_time:          float           = 0.5
    voice_mode_at_time:         str             = "mixed"
    sessions_elapsed:           float           = 0.0   # updated on load

    @classmethod
    def create(
        cls,
        observation:            str,
        source:                 str,
        session_id:             str,
        interpretations:        List[Tuple[str, float, str]],   # (hypothesis, confidence, agent)
        linked_context:         Optional[List[str]] = None,
        contradiction_flags:    Optional[List[str]] = None,
        decay_rate:             str = DecayRate.MEDIUM,
        narrative_weight:       float = 0.5,
        vdi_score:              float = 0.5,
        voice_mode:             str = "mixed",
    ) -> "EvidenceMarker":
        candidates = [
            InterpretationCandidate(
                hypothesis   = h,
                confidence   = c,
                agent_source = a,
            )
            for h, c, a in interpretations
        ]
        # Sort descending by confidence so the leading read is first
        candidates.sort(key=lambda x: x.confidence, reverse=True)

        return cls(
            marker_id               = str(uuid.uuid4()),
            observation             = observation,
            source                  = source,
            timestamp               = time.time(),
            session_id              = session_id,
            possible_interpretations = candidates,
            linked_context          = linked_context or [],
            contradiction_flags     = contradiction_flags or [],
            decay_rate              = decay_rate,
            narrative_weight        = narrative_weight,
            vdi_score_at_time       = vdi_score,
            voice_mode_at_time      = voice_mode,
        )

    def leading_hypothesis(self) -> Optional[InterpretationCandidate]:
        """The highest-confidence interpretation. Not necessarily correct."""
        if not self.possible_interpretations:
            return None
        return self.possible_interpretations[0]

    def is_ambiguous(self, threshold: float = 0.15) -> bool:
        """
        True if the top two interpretations are close in confidence.
        Ambiguous markers should not be collapsed into conclusions.
        """
        if len(self.possible_interpretations) < 2:
            return False
        return (
            self.possible_interpretations[0].confidence
            - self.possible_interpretations[1].confidence
        ) < threshold

    def effective_weight(self) -> float:
        """
        Narrative weight after decay. Used by TheoryEngine to score
        how much this marker should move a theory's confidence.
        """
        half_life = DECAY_HALF_LIFE.get(self.decay_rate, 5.0)
        decay_factor = math.pow(0.5, self.sessions_elapsed / half_life)
        return round(self.narrative_weight * decay_factor, 4)

    def to_db_dict(self) -> dict:
        return {
            "marker_id":                self.marker_id,
            "observation":              self.observation,
            "source":                   self.source,
            "timestamp":                self.timestamp,
            "session_id":               self.session_id,
            "possible_interpretations": json.dumps([
                asdict(c) for c in self.possible_interpretations
            ]),
            "linked_context":           json.dumps(self.linked_context),
            "contradiction_flags":      json.dumps(self.contradiction_flags),
            "decay_rate":               self.decay_rate,
            "narrative_weight":         self.narrative_weight,
            "vdi_score_at_time":        self.vdi_score_at_time,
            "voice_mode_at_time":       self.voice_mode_at_time,
        }

    @classmethod
    def from_db_row(cls, row: sqlite3.Row, sessions_elapsed: float = 0.0) -> "EvidenceMarker":
        interpretations = [
            InterpretationCandidate(**c)
            for c in json.loads(row["possible_interpretations"])
        ]
        return cls(
            marker_id               = row["marker_id"],
            observation             = row["observation"],
            source                  = row["source"],
            timestamp               = row["timestamp"],
            session_id              = row["session_id"],
            possible_interpretations = interpretations,
            linked_context          = json.loads(row["linked_context"]),
            contradiction_flags     = json.loads(row["contradiction_flags"]),
            decay_rate              = row["decay_rate"],
            narrative_weight        = row["narrative_weight"],
            vdi_score_at_time       = row["vdi_score_at_time"],
            voice_mode_at_time      = row["voice_mode_at_time"],
            sessions_elapsed        = sessions_elapsed,
        )


# ─────────────────────────────────────────────────────────────────────────────
# EVIDENCE THEORY
# A named hypothesis built from accumulated markers.
# Not a conclusion. A living interpretation under revision.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EvidenceTheory:
    """
    A named hypothesis about a person or dynamic.

    Theories are built from evidence, not asserted.
    They are supported by markers. Contradicted by markers.
    They carry confidence — not as probability, but as epistemic weight.
    They decay when unreinforced.

    Example:
        theory_name:   "humor_as_defense_mechanism"
        statement:     "Humor may be used defensively during vulnerability"
        confidence:    0.61   (moderate)
        support_count: 14
        contradiction_count: 2
    """
    theory_id:          str
    theory_name:        str         # machine-readable slug
    statement:          str         # human-readable hypothesis
    confidence:         float       # 0.0–1.0 epistemic weight
    support_count:      int         = 0     # markers that strengthen this
    contradiction_count: int        = 0     # markers that weaken this
    last_reinforced_session: str    = ""
    first_observed_session:  str    = ""
    decay_rate:         str         = DecayRate.SLOW
    sessions_since_reinforcement: float = 0.0
    supporting_marker_ids:   List[str] = field(default_factory=list)
    contradicting_marker_ids: List[str] = field(default_factory=list)
    notes:              str         = ""

    # Confidence bands — read by Pete briefing
    @property
    def confidence_label(self) -> str:
        if self.confidence >= 0.75:
            return "strong"
        if self.confidence >= 0.50:
            return "moderate"
        if self.confidence >= 0.25:
            return "weak"
        return "speculative"

    def effective_confidence(self) -> float:
        """Confidence after time-based decay."""
        half_life = DECAY_HALF_LIFE.get(self.decay_rate, 15.0)
        decay_factor = math.pow(0.5, self.sessions_since_reinforcement / half_life)
        return round(self.confidence * decay_factor, 4)

    def reinforce(self, marker: EvidenceMarker, weight: float) -> None:
        """
        A new marker supports this theory. Strengthen confidence.
        Uses asymptotic strengthening — confidence approaches 1.0 but
        never reaches it from evidence alone.
        """
        gain = weight * (1.0 - self.confidence) * 0.35
        self.confidence = min(0.97, self.confidence + gain)
        self.support_count += 1
        self.sessions_since_reinforcement = 0.0
        if marker.marker_id not in self.supporting_marker_ids:
            self.supporting_marker_ids.append(marker.marker_id)
        self.last_reinforced_session = marker.session_id

    def contradict(self, marker: EvidenceMarker, weight: float) -> None:
        """
        A new marker contradicts this theory. Destabilize confidence.
        Contradictions are stronger than reinforcement — easier to weaken
        than to strengthen. This keeps theories honest.
        """
        loss = weight * self.confidence * 0.45
        self.confidence = max(0.0, self.confidence - loss)
        self.contradiction_count += 1
        if marker.marker_id not in self.contradicting_marker_ids:
            self.contradicting_marker_ids.append(marker.marker_id)

    def apply_session_decay(self) -> None:
        """Called once per session. Theories weaken when not reinforced."""
        self.sessions_since_reinforcement += 1.0
        self.confidence = self.effective_confidence()

    def to_db_dict(self) -> dict:
        return {
            "theory_id":                    self.theory_id,
            "theory_name":                  self.theory_name,
            "statement":                    self.statement,
            "confidence":                   self.confidence,
            "support_count":                self.support_count,
            "contradiction_count":          self.contradiction_count,
            "last_reinforced_session":      self.last_reinforced_session,
            "first_observed_session":       self.first_observed_session,
            "decay_rate":                   self.decay_rate,
            "sessions_since_reinforcement": self.sessions_since_reinforcement,
            "supporting_marker_ids":        json.dumps(self.supporting_marker_ids),
            "contradicting_marker_ids":     json.dumps(self.contradicting_marker_ids),
            "notes":                        self.notes,
        }

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "EvidenceTheory":
        return cls(
            theory_id                   = row["theory_id"],
            theory_name                 = row["theory_name"],
            statement                   = row["statement"],
            confidence                  = row["confidence"],
            support_count               = row["support_count"],
            contradiction_count         = row["contradiction_count"],
            last_reinforced_session     = row["last_reinforced_session"] or "",
            first_observed_session      = row["first_observed_session"] or "",
            decay_rate                  = row["decay_rate"],
            sessions_since_reinforcement = row["sessions_since_reinforcement"],
            supporting_marker_ids       = json.loads(row["supporting_marker_ids"]),
            contradicting_marker_ids    = json.loads(row["contradicting_marker_ids"]),
            notes                       = row["notes"] or "",
        )

    def to_briefing_block(self) -> str:
        """
        Format this theory for Pete's briefing. Compact. Honest.
        Includes confidence, support/contradiction counts, and last reinforcement.
        """
        lines = [
            f"THEORY: {self.statement}",
            f"CONFIDENCE: {self.confidence_label} ({self.confidence:.2f})",
            f"SUPPORTED BY: {self.support_count} marker(s)",
        ]
        if self.contradiction_count > 0:
            lines.append(f"CONTRADICTED BY: {self.contradiction_count} marker(s)")
        if self.last_reinforced_session:
            lines.append(f"LAST REINFORCED: {self.last_reinforced_session}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# THEORY TEMPLATES
# Seed hypotheses. The system generates these; evidence evaluates them.
# New theories emerge from distillation when marker clusters form.
# ─────────────────────────────────────────────────────────────────────────────

THEORY_TEMPLATES: List[Dict[str, Any]] = [
    {
        "theory_name":  "humor_as_defense_mechanism",
        "statement":    "Humor may be used defensively during moments of vulnerability",
        "decay_rate":   DecayRate.SLOW,
        "trigger_events": [
            ObservableEvent.LAUGHTER_AFTER_TENSION,
            ObservableEvent.VULNERABILITY_THEN_PIVOT,
            ObservableEvent.CREATIVE_DEFLECTION,
        ],
        "contradiction_events": [
            ObservableEvent.SELF_DISCLOSURE,
        ],
    },
    {
        "theory_name":  "frustration_escalation_pattern",
        "statement":    "Escalating interruptions signal frustration rather than excitement when paired with topic emotional weight",
        "decay_rate":   DecayRate.MEDIUM,
        "trigger_events": [
            ObservableEvent.INTERRUPT_SPIKE,
            ObservableEvent.PACING_ACCELERATION,
            ObservableEvent.PROFANITY_SPIKE,
        ],
        "contradiction_events": [
            ObservableEvent.IDENTITY_MOMENT_ENTERED,
            ObservableEvent.LAUGHTER_BURST,
        ],
    },
    {
        "theory_name":  "creative_insecurity_recurrence",
        "statement":    "Creative work discussions trigger underlying insecurity signals even when surface affect is confident",
        "decay_rate":   DecayRate.SLOW,
        "trigger_events": [
            ObservableEvent.SENTIMENT_INVERSION,
            ObservableEvent.SELF_REPORT_MISMATCH,
            ObservableEvent.RAPID_TOPIC_SWITCH,
        ],
        "contradiction_events": [
            ObservableEvent.IDENTITY_MOMENT_SUSTAINED,
            ObservableEvent.SELF_DISCLOSURE,
        ],
    },
    {
        "theory_name":  "intimacy_threshold_exists",
        "statement":    "There is a consistent VDI threshold at which this person allows genuine intimacy rather than performance",
        "decay_rate":   DecayRate.ANCHOR,
        "trigger_events": [
            ObservableEvent.IDENTITY_MOMENT_SUSTAINED,
            ObservableEvent.SELF_DISCLOSURE,
        ],
        "contradiction_events": [
            ObservableEvent.TOPIC_AVOIDANCE,
            ObservableEvent.VULNERABILITY_THEN_PIVOT,
        ],
    },
    {
        "theory_name":  "topic_avoidance_signature",
        "statement":    "Certain topics consistently trigger avoidance — rapid pivots, humor, or sudden silence",
        "decay_rate":   DecayRate.SLOW,
        "trigger_events": [
            ObservableEvent.TOPIC_AVOIDANCE,
            ObservableEvent.RAPID_TOPIC_SWITCH,
            ObservableEvent.SILENCE_EXTENDED,
        ],
        "contradiction_events": [
            ObservableEvent.SELF_DISCLOSURE,
            ObservableEvent.RECURRING_TOPIC_RETURN,
        ],
    },
    {
        "theory_name":  "high_analytical_engagement",
        "statement":    "This person reaches peak engagement during analytical or technical content, not emotional content",
        "decay_rate":   DecayRate.MEDIUM,
        "trigger_events": [
            ObservableEvent.AUDIENCE_ENGAGEMENT_SURGE,
            ObservableEvent.AUDIENCE_ENGAGEMENT_DROP,    # during emotional segments
        ],
        "contradiction_events": [
            ObservableEvent.IDENTITY_MOMENT_ENTERED,
            ObservableEvent.SELF_DISCLOSURE,
        ],
    },
]

# Minimum marker count before a seeded theory becomes active
THEORY_ACTIVATION_THRESHOLD = 3

# Theories below this confidence are archived, not deleted
THEORY_ARCHIVE_THRESHOLD = 0.08


# ─────────────────────────────────────────────────────────────────────────────
# DATABASE SCHEMA EXTENSION
# Adds evidence tables to the existing pubcast_memory.db
# ─────────────────────────────────────────────────────────────────────────────

EVIDENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence_markers (
    marker_id               TEXT    PRIMARY KEY,
    observation             TEXT    NOT NULL,
    source                  TEXT    NOT NULL,
    timestamp               REAL    NOT NULL,
    session_id              TEXT    NOT NULL,
    possible_interpretations TEXT   NOT NULL,   -- JSON
    linked_context          TEXT    NOT NULL,   -- JSON array
    contradiction_flags     TEXT    NOT NULL,   -- JSON array
    decay_rate              TEXT    NOT NULL    DEFAULT 'medium',
    narrative_weight        REAL    NOT NULL    DEFAULT 0.5,
    vdi_score_at_time       REAL    DEFAULT 0.5,
    voice_mode_at_time      TEXT    DEFAULT 'mixed'
);

CREATE TABLE IF NOT EXISTS evidence_theories (
    theory_id                   TEXT    PRIMARY KEY,
    theory_name                 TEXT    UNIQUE NOT NULL,
    statement                   TEXT    NOT NULL,
    confidence                  REAL    NOT NULL DEFAULT 0.0,
    support_count               INTEGER DEFAULT 0,
    contradiction_count         INTEGER DEFAULT 0,
    last_reinforced_session     TEXT    DEFAULT '',
    first_observed_session      TEXT    DEFAULT '',
    decay_rate                  TEXT    DEFAULT 'slow',
    sessions_since_reinforcement REAL   DEFAULT 0.0,
    supporting_marker_ids       TEXT    DEFAULT '[]',   -- JSON
    contradicting_marker_ids    TEXT    DEFAULT '[]',   -- JSON
    notes                       TEXT    DEFAULT '',
    archived                    INTEGER DEFAULT 0       -- soft delete
);

CREATE INDEX IF NOT EXISTS idx_markers_session   ON evidence_markers(session_id);
CREATE INDEX IF NOT EXISTS idx_markers_source    ON evidence_markers(source);
CREATE INDEX IF NOT EXISTS idx_markers_timestamp ON evidence_markers(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_theories_active   ON evidence_theories(archived, confidence DESC);
"""


# ─────────────────────────────────────────────────────────────────────────────
# EVIDENCE LAYER — THE ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class EvidenceLayer:
    """
    The interpretive accumulator.

    Observes events from VDI, Prosody, and Pete.
    Emits EvidenceMarkers with multiple coexisting interpretations.
    Maintains EvidenceTheories that evolve across sessions.
    Feeds a theory briefing into Pete's context each session.

    This is NOT a real-time inference engine.
    Marker generation is fast. Theory evaluation is session-scoped.
    Deep synthesis happens in distill_evidence() — not on the hot path.
    """

    def __init__(
        self,
        db_path:    Path    = DB_PATH,
        session_id: str     = "",
    ):
        self.db_path    = db_path
        self.session_id = session_id or f"session_{int(time.time())}"

        # In-session working state
        self._session_markers:  List[EvidenceMarker] = []
        self._active_theories:  Dict[str, EvidenceTheory] = {}

        # Event → theory slug mapping (built from THEORY_TEMPLATES)
        self._event_theory_support:       Dict[str, List[str]] = {}
        self._event_theory_contradiction: Dict[str, List[str]] = {}

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._build_event_maps()
        self.load_state()

        logger.info(f"[Evidence] Layer initialized — session {self.session_id}")

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def observe(
        self,
        event:                  str,                        # ObservableEvent value
        source:                 str,                        # originating module
        vdi_score:              float           = 0.5,
        voice_mode:             str             = "mixed",
        linked_context:         Optional[List[str]] = None,
        contradiction_flags:    Optional[List[str]] = None,
        narrative_weight:       float           = 0.5,
        decay_rate:             str             = DecayRate.MEDIUM,
    ) -> EvidenceMarker:
        """
        Primary ingestion point.

        Receives a raw observable event, generates interpretation candidates
        from the event taxonomy, creates an EvidenceMarker, and evaluates
        it against active theories.

        Call this from EVOOrchestrator.tick() after VDI signals are available.
        Does NOT block the hot path — theory updates are lightweight in-memory ops.
        Heavy synthesis stays in distill_evidence().
        """
        interpretations = self._generate_interpretations(event, vdi_score, voice_mode)

        marker = EvidenceMarker.create(
            observation         = event,
            source              = source,
            session_id          = self.session_id,
            interpretations     = interpretations,
            linked_context      = linked_context or [],
            contradiction_flags = contradiction_flags or [],
            decay_rate          = decay_rate,
            narrative_weight    = narrative_weight,
            vdi_score           = vdi_score,
            voice_mode          = voice_mode,
        )

        self._session_markers.append(marker)
        self._persist_marker(marker)
        self._evaluate_theories(marker)

        logger.debug(
            f"[Evidence] Marker: {event} | "
            f"lead={marker.leading_hypothesis().hypothesis if marker.leading_hypothesis() else 'none'} "
            f"({marker.leading_hypothesis().confidence:.2f})"
            if marker.leading_hypothesis() else f"[Evidence] Marker: {event} | no interpretations"
        )

        return marker

    def get_active_theories(self, min_confidence: float = 0.15) -> List[EvidenceTheory]:
        """
        Return active theories above the confidence floor,
        sorted by effective confidence descending.
        Excludes archived theories.
        """
        active = [
            t for t in self._active_theories.values()
            if t.effective_confidence() >= min_confidence
            and t.support_count >= THEORY_ACTIVATION_THRESHOLD
        ]
        active.sort(key=lambda t: t.effective_confidence(), reverse=True)
        return active

    def get_theory_briefing(self, max_theories: int = 4) -> str:
        """
        Build a compact theory briefing for Pete's system prompt.
        Honest about confidence. Includes contradictions.
        Returns empty string if no active theories yet.
        """
        theories = self.get_active_theories()[:max_theories]
        if not theories:
            return ""

        lines = ["[EVIDENCE THEORIES]"]
        for theory in theories:
            lines.append("")
            lines.append(theory.to_briefing_block())

        # Append recent session marker summary
        if self._session_markers:
            dominant = self._dominant_event_this_session()
            if dominant:
                lines.append("")
                lines.append(f"THIS SESSION: {dominant}")

        return "\n".join(lines)

    def get_session_markers(self) -> List[EvidenceMarker]:
        """All markers observed in the current session."""
        return list(self._session_markers)

    def distill_evidence(self) -> None:
        """
        End-of-session synthesis. The reflective runtime.

        Does NOT run on the hot path. Called alongside
        UniversalMemorySystem.distill_session() at session end.

        Steps:
          1. Apply decay to all active theories (unreinforced = weakens)
          2. Check for theory cluster emergence (new theories from marker patterns)
          3. Archive theories below confidence floor
          4. Persist updated theory state
        """
        if not self._session_markers and not self._active_theories:
            return

        logger.info(f"[Evidence] Distilling session {self.session_id}")

        # Step 1: Decay all theories not reinforced this session
        for theory in self._active_theories.values():
            if theory.last_reinforced_session != self.session_id:
                theory.apply_session_decay()

        # Step 2: Check for emergent theory clusters
        self._check_theory_emergence()

        # Step 3: Archive theories that have faded below threshold
        archived_count = 0
        for theory in self._active_theories.values():
            if theory.effective_confidence() < THEORY_ARCHIVE_THRESHOLD:
                self._archive_theory(theory.theory_id)
                archived_count += 1

        # Step 4: Persist
        self._persist_all_theories()

        active_count = len(self.get_active_theories())
        logger.info(
            f"[Evidence] Distillation complete — "
            f"{active_count} active theories, {archived_count} archived"
        )

    def load_state(self) -> None:
        """
        Load persisted theories from DB into memory.
        Called at init. Safe to call again (re-syncs).
        """
        self._active_theories = {}

        # Load seeded theories first (upsert — won't overwrite existing)
        self._seed_theories()

        # Load all non-archived from DB
        with self._db() as conn:
            rows = conn.execute("""
                SELECT * FROM evidence_theories WHERE archived = 0
            """).fetchall()

        for row in rows:
            theory = EvidenceTheory.from_db_row(row)
            self._active_theories[theory.theory_name] = theory

        logger.debug(f"[Evidence] Loaded {len(self._active_theories)} theories from DB")

    # =========================================================================
    # INTERPRETATION GENERATION
    # Maps raw events to interpretation candidates.
    # Multiple candidates per event — ambiguity is preserved.
    # =========================================================================

    def _generate_interpretations(
        self,
        event:      str,
        vdi_score:  float,
        voice_mode: str,
    ) -> List[Tuple[str, float, str]]:
        """
        Generate interpretation candidates for a raw event.

        Returns: List of (hypothesis, confidence, agent_source) tuples.

        Confidence is influenced by VDI score and voice mode context —
        the same event means different things in different emotional weather.
        """
        # Core interpretation map — the system's vocabulary of meaning
        # Format: event → [(hypothesis, base_confidence, agent), ...]
        # Note: base confidences are intentionally sub-0.5 to preserve ambiguity
        interp_map: Dict[str, List[Tuple[str, float, str]]] = {
            ObservableEvent.INTERRUPT_SPIKE: [
                ("frustration_escalation",      0.40, "eq_agent"),
                ("excitement_overflow",         0.33, "eq_agent"),
                ("anxiety_response",            0.22, "eq_agent"),
                ("performative_intensity",      0.18, "performer_agent"),
            ],
            ObservableEvent.LAUGHTER_AFTER_TENSION: [
                ("defensive_humor_release",     0.44, "eq_agent"),
                ("genuine_relief",              0.35, "eq_agent"),
                ("social_bonding_signal",       0.28, "social_agent"),
                ("comedic_deflection",          0.26, "performer_agent"),
            ],
            ObservableEvent.RAPID_TOPIC_SWITCH: [
                ("avoidance_response",          0.38, "narrative_agent"),
                ("high_associative_thinking",   0.30, "eq_agent"),
                ("discomfort_with_topic",       0.35, "eq_agent"),
                ("creative_flow_state",         0.22, "performer_agent"),
            ],
            ObservableEvent.SENTIMENT_INVERSION: [
                ("suppressed_contrary_feeling", 0.41, "eq_agent"),
                ("social_performance_slip",     0.30, "social_agent"),
                ("cognitive_dissonance",        0.28, "narrative_agent"),
                ("ironic_register",             0.18, "performer_agent"),
            ],
            ObservableEvent.SILENCE_EXTENDED: [
                ("deep_processing",             0.42, "eq_agent"),
                ("emotional_overwhelm",         0.30, "eq_agent"),
                ("resistance_or_refusal",       0.25, "social_agent"),
                ("identity_moment_forming",     0.35, "vdi_agent"),
            ],
            ObservableEvent.VULNERABILITY_THEN_PIVOT: [
                ("self_protection_reflex",      0.48, "eq_agent"),
                ("trust_threshold_reached",     0.30, "social_agent"),
                ("defensive_humor_pattern",     0.38, "narrative_agent"),
                ("calibrating_safety",          0.25, "eq_agent"),
            ],
            ObservableEvent.SELF_DISCLOSURE: [
                ("trust_signal",                0.52, "social_agent"),
                ("intimacy_threshold_crossed",  0.45, "eq_agent"),
                ("need_for_validation",         0.28, "eq_agent"),
                ("narrative_processing",        0.22, "narrative_agent"),
            ],
            ObservableEvent.PACING_ACCELERATION: [
                ("anxiety_building",            0.38, "eq_agent"),
                ("excitement_escalation",       0.34, "eq_agent"),
                ("urgency_signal",              0.30, "narrative_agent"),
                ("stimulation_seeking",         0.20, "performer_agent"),
            ],
            ObservableEvent.LAUGHTER_BURST: [
                ("genuine_amusement",           0.45, "eq_agent"),
                ("tension_relief",              0.35, "eq_agent"),
                ("social_bonding",              0.30, "social_agent"),
                ("performed_response",          0.15, "performer_agent"),
            ],
            ObservableEvent.TOPIC_AVOIDANCE: [
                ("emotional_sensitivity",       0.42, "eq_agent"),
                ("boundary_signal",             0.38, "social_agent"),
                ("unresolved_thread",           0.35, "narrative_agent"),
                ("disinterest",                 0.18, "eq_agent"),
            ],
            ObservableEvent.IDENTITY_MOMENT_ENTERED: [
                ("genuine_intimacy_available",  0.55, "vdi_agent"),
                ("peak_receptivity",            0.48, "vdi_agent"),
                ("performative_intensity",      0.20, "performer_agent"),
            ],
            ObservableEvent.SELF_REPORT_MISMATCH: [
                ("suppressed_true_state",       0.44, "eq_agent"),
                ("social_performance",          0.38, "social_agent"),
                ("internal_conflict",           0.30, "narrative_agent"),
                ("misread_signal",              0.22, "eq_agent"),
            ],
            ObservableEvent.CREATIVE_DEFLECTION: [
                ("vulnerability_avoidance",     0.40, "narrative_agent"),
                ("preferred_register",          0.35, "performer_agent"),
                ("discomfort_signal",           0.30, "eq_agent"),
                ("genuine_creative_joy",        0.25, "performer_agent"),
            ],
            ObservableEvent.PROFANITY_SPIKE: [
                ("emotional_intensity_peak",    0.42, "eq_agent"),
                ("frustration_signal",          0.38, "eq_agent"),
                ("comfort_and_familiarity",     0.30, "social_agent"),
                ("performative_register",       0.22, "performer_agent"),
            ],
            ObservableEvent.AUDIENCE_ENGAGEMENT_SURGE: [
                ("content_resonance",           0.50, "vdi_agent"),
                ("performer_connection",        0.40, "social_agent"),
                ("novelty_response",            0.25, "vdi_agent"),
            ],
            ObservableEvent.RECURRING_TOPIC_RETURN: [
                ("unresolved_emotional_thread", 0.45, "narrative_agent"),
                ("strong_interest",             0.35, "eq_agent"),
                ("identity_relevant_material",  0.38, "narrative_agent"),
                ("habit_pattern",               0.18, "eq_agent"),
            ],
            ObservableEvent.PATTERN_RECURRENCE: [
                ("established_behavioral_mode", 0.50, "narrative_agent"),
                ("learned_coping_strategy",     0.40, "eq_agent"),
                ("identity_expression",         0.35, "narrative_agent"),
            ],
        }

        base_candidates = interp_map.get(event, [
            ("undifferentiated_signal", 0.20, "eq_agent"),
        ])

        # Contextual modulation — same event, different weather, different meaning
        modulated = []
        for hypothesis, base_conf, agent in base_candidates:
            adjusted = base_conf

            # High VDI: emotional register active — weight emotional interpretations up
            if vdi_score > 0.65:
                if any(k in hypothesis for k in ["frustration", "vulnerability", "intimacy", "emotional", "trust"]):
                    adjusted = min(0.85, adjusted * 1.25)

            # Low VDI: analytical mode — weight cognitive interpretations up
            if vdi_score < 0.30:
                if any(k in hypothesis for k in ["cognitive", "processing", "analytical", "disinterest"]):
                    adjusted = min(0.85, adjusted * 1.20)

            # Identity mode: trust signals more credible
            if voice_mode == "identity":
                if any(k in hypothesis for k in ["trust", "intimacy", "genuine", "disclosure"]):
                    adjusted = min(0.85, adjusted * 1.30)
                if any(k in hypothesis for k in ["performative", "social_performance"]):
                    adjusted = max(0.05, adjusted * 0.70)

            modulated.append((hypothesis, round(adjusted, 3), agent))

        # Sort by adjusted confidence descending
        modulated.sort(key=lambda x: x[1], reverse=True)
        return modulated

    # =========================================================================
    # THEORY EVALUATION
    # Called per marker — fast, in-memory only.
    # =========================================================================

    def _evaluate_theories(self, marker: EvidenceMarker) -> None:
        """
        Evaluate a new marker against all active theories.
        Reinforces theories aligned with the marker's event.
        Contradicts theories that the marker's event opposes.
        """
        event = marker.observation

        # Reinforce
        supporting_theories = self._event_theory_support.get(event, [])
        for theory_name in supporting_theories:
            if theory_name in self._active_theories:
                theory = self._active_theories[theory_name]
                theory.reinforce(marker, marker.effective_weight())

        # Contradict
        contradicting_theories = self._event_theory_contradiction.get(event, [])
        for theory_name in contradicting_theories:
            if theory_name in self._active_theories:
                theory = self._active_theories[theory_name]
                theory.contradict(marker, marker.effective_weight())

    def _build_event_maps(self) -> None:
        """Build event→theory lookup tables from THEORY_TEMPLATES."""
        for template in THEORY_TEMPLATES:
            name = template["theory_name"]
            for event in template.get("trigger_events", []):
                self._event_theory_support.setdefault(event, []).append(name)
            for event in template.get("contradiction_events", []):
                self._event_theory_contradiction.setdefault(event, []).append(name)

    # =========================================================================
    # THEORY EMERGENCE
    # New theories crystallize from marker cluster patterns.
    # Only runs during distillation — not on hot path.
    # =========================================================================

    def _check_theory_emergence(self) -> None:
        """
        Scan this session's markers for clusters that suggest
        a new unnamed theory. Generates an emergent theory if
        a pattern exceeds the cluster threshold.

        Currently checks for:
        - Repeated VULNERABILITY_THEN_PIVOT (≥3) not covered by existing theory
        - Repeated SELF_REPORT_MISMATCH (≥2) cross-referenced with TOPIC_AVOIDANCE
        - High narrative_weight markers with RECURRING_TOPIC_RETURN
        """
        event_counts: Dict[str, int] = {}
        for marker in self._session_markers:
            event_counts[marker.observation] = event_counts.get(marker.observation, 0) + 1

        # Pattern: repeated vulnerability pivot → new "emotional_guardedness" theory
        pivot_count = event_counts.get(ObservableEvent.VULNERABILITY_THEN_PIVOT, 0)
        mismatch_count = event_counts.get(ObservableEvent.SELF_REPORT_MISMATCH, 0)

        if pivot_count >= 3 and "emotional_guardedness_pattern" not in self._active_theories:
            self._create_emergent_theory(
                theory_name = "emotional_guardedness_pattern",
                statement   = "A consistent pattern of approaching vulnerability then retreating suggests active emotional self-protection",
                decay_rate  = DecayRate.SLOW,
                initial_confidence = 0.25,
                trigger_events = [
                    ObservableEvent.VULNERABILITY_THEN_PIVOT,
                    ObservableEvent.TOPIC_AVOIDANCE,
                ],
                contradiction_events = [
                    ObservableEvent.SELF_DISCLOSURE,
                    ObservableEvent.IDENTITY_MOMENT_SUSTAINED,
                ],
            )

        if mismatch_count >= 2 and event_counts.get(ObservableEvent.TOPIC_AVOIDANCE, 0) >= 2:
            if "internal_external_state_divergence" not in self._active_theories:
                self._create_emergent_theory(
                    theory_name = "internal_external_state_divergence",
                    statement   = "Reported emotional state and observed signals diverge — something is being managed or concealed",
                    decay_rate  = DecayRate.MEDIUM,
                    initial_confidence = 0.22,
                    trigger_events = [
                        ObservableEvent.SELF_REPORT_MISMATCH,
                        ObservableEvent.TOPIC_AVOIDANCE,
                    ],
                    contradiction_events = [
                        ObservableEvent.SELF_DISCLOSURE,
                        ObservableEvent.IDENTITY_MOMENT_ENTERED,
                    ],
                )

    def _create_emergent_theory(
        self,
        theory_name:            str,
        statement:              str,
        decay_rate:             str,
        initial_confidence:     float,
        trigger_events:         List[str],
        contradiction_events:   List[str],
    ) -> None:
        """Create a new theory that emerged from observed patterns."""
        theory = EvidenceTheory(
            theory_id               = str(uuid.uuid4()),
            theory_name             = theory_name,
            statement               = statement,
            confidence              = initial_confidence,
            first_observed_session  = self.session_id,
            last_reinforced_session = self.session_id,
            decay_rate              = decay_rate,
        )

        self._active_theories[theory_name] = theory

        # Register its events in the lookup maps
        for event in trigger_events:
            self._event_theory_support.setdefault(event, []).append(theory_name)
        for event in contradiction_events:
            self._event_theory_contradiction.setdefault(event, []).append(theory_name)

        logger.info(f"[Evidence] Emergent theory crystallized: {theory_name} ({initial_confidence:.2f})")

    # =========================================================================
    # SEED THEORIES
    # =========================================================================

    def _seed_theories(self) -> None:
        """
        Ensure all template theories exist in the DB.
        INSERT OR IGNORE — does not overwrite evolved theories.
        """
        with self._db() as conn:
            for template in THEORY_TEMPLATES:
                theory_name = template["theory_name"]
                existing = conn.execute(
                    "SELECT theory_id FROM evidence_theories WHERE theory_name = ?",
                    (theory_name,)
                ).fetchone()
                if existing:
                    continue

                theory = EvidenceTheory(
                    theory_id              = str(uuid.uuid4()),
                    theory_name            = theory_name,
                    statement              = template["statement"],
                    confidence             = 0.0,
                    decay_rate             = template.get("decay_rate", DecayRate.SLOW),
                    first_observed_session = "",
                )
                d = theory.to_db_dict()
                conn.execute("""
                    INSERT OR IGNORE INTO evidence_theories
                        (theory_id, theory_name, statement, confidence, support_count,
                         contradiction_count, last_reinforced_session, first_observed_session,
                         decay_rate, sessions_since_reinforcement,
                         supporting_marker_ids, contradicting_marker_ids, notes, archived)
                    VALUES
                        (:theory_id, :theory_name, :statement, :confidence, :support_count,
                         :contradiction_count, :last_reinforced_session, :first_observed_session,
                         :decay_rate, :sessions_since_reinforcement,
                         :supporting_marker_ids, :contradicting_marker_ids, :notes, 0)
                """, d)

    # =========================================================================
    # SESSION INTROSPECTION
    # =========================================================================

    def _dominant_event_this_session(self) -> Optional[str]:
        """Return the most frequently observed event this session, if notable."""
        counts: Dict[str, int] = {}
        for marker in self._session_markers:
            counts[marker.observation] = counts.get(marker.observation, 0) + 1

        if not counts:
            return None

        top_event, top_count = max(counts.items(), key=lambda x: x[1])
        if top_count < 2:
            return None

        return f"{top_event} × {top_count}"

    # =========================================================================
    # DATABASE
    # =========================================================================

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"[Evidence] DB error: {e}")
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._db() as conn:
            conn.executescript(EVIDENCE_SCHEMA)

    def _persist_marker(self, marker: EvidenceMarker) -> None:
        with self._db() as conn:
            d = marker.to_db_dict()
            conn.execute("""
                INSERT OR REPLACE INTO evidence_markers
                    (marker_id, observation, source, timestamp, session_id,
                     possible_interpretations, linked_context, contradiction_flags,
                     decay_rate, narrative_weight, vdi_score_at_time, voice_mode_at_time)
                VALUES
                    (:marker_id, :observation, :source, :timestamp, :session_id,
                     :possible_interpretations, :linked_context, :contradiction_flags,
                     :decay_rate, :narrative_weight, :vdi_score_at_time, :voice_mode_at_time)
            """, d)

    def _persist_all_theories(self) -> None:
        with self._db() as conn:
            for theory in self._active_theories.values():
                d = theory.to_db_dict()
                conn.execute("""
                    INSERT OR REPLACE INTO evidence_theories
                        (theory_id, theory_name, statement, confidence, support_count,
                         contradiction_count, last_reinforced_session, first_observed_session,
                         decay_rate, sessions_since_reinforcement,
                         supporting_marker_ids, contradicting_marker_ids, notes, archived)
                    VALUES
                        (:theory_id, :theory_name, :statement, :confidence, :support_count,
                         :contradiction_count, :last_reinforced_session, :first_observed_session,
                         :decay_rate, :sessions_since_reinforcement,
                         :supporting_marker_ids, :contradicting_marker_ids, :notes, 0)
                """, d)

    def _archive_theory(self, theory_id: str) -> None:
        with self._db() as conn:
            conn.execute(
                "UPDATE evidence_theories SET archived = 1 WHERE theory_id = ?",
                (theory_id,)
            )


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL ADAPTER
# Bridges VDIReport + EmotionalState → EvidenceLayer.observe() calls.
# Keeps the evidence layer decoupled from VDI internals.
# ─────────────────────────────────────────────────────────────────────────────

class SignalAdapter:
    """
    Translates VDI and Prosody signals into ObservableEvents.

    Called from EVOOrchestrator.tick() after VDI update.
    Compares current tick to previous tick to detect transitions.
    Only emits events when thresholds are crossed — not every tick.
    """

    # Thresholds for event detection
    INTERRUPT_DELTA_THRESHOLD       = 0.20  # VDI signal drop (audience disengages = interrupt context)
    ENGAGEMENT_SURGE_THRESHOLD      = 0.72
    ENGAGEMENT_DROP_THRESHOLD       = 0.30
    SILENCE_PRESSURE_THRESHOLD      = 0.65
    IDENTITY_MOMENT_THRESHOLD       = 0.78
    LAUGHTER_THRESHOLD              = 0.40
    CONFUSION_THRESHOLD             = 0.45

    def __init__(self, evidence_layer: EvidenceLayer):
        self.evidence   = evidence_layer
        self._prev_vdi  = 0.5
        self._prev_mode = "mixed"
        self._identity_sustained_ticks = 0
        self._tension_this_tick = False

    def process_tick(
        self,
        vdi_report:         Any,    # VDIReport
        emotional_state:    Any,    # EmotionalState from ProsodyEngine
        current_topic:      str     = "",
        session_topics:     Optional[List[str]] = None,
    ) -> List[EvidenceMarker]:
        """
        Process one VDI tick and emit evidence markers for notable events.
        Returns list of markers emitted this tick (may be empty).
        """
        emitted: List[EvidenceMarker] = []
        vdi_score   = getattr(vdi_report, "vdi_score", 0.5)
        voice_mode  = str(getattr(vdi_report, "voice_mode", "mixed"))
        laughter    = getattr(vdi_report, "audio_score", 0.5)   # proxy
        silence_p   = getattr(vdi_report, "silence_pressure", 0.0)

        # ── IDENTITY MOMENT TRACKING ──────────────────────────────────────────
        if vdi_score >= self.IDENTITY_MOMENT_THRESHOLD:
            self._identity_sustained_ticks += 1
            if self._identity_sustained_ticks == 1:
                m = self.evidence.observe(
                    event            = ObservableEvent.IDENTITY_MOMENT_ENTERED,
                    source           = "vdi_engine",
                    vdi_score        = vdi_score,
                    voice_mode       = voice_mode,
                    linked_context   = [f"topic:{current_topic}"] if current_topic else [],
                    narrative_weight = 0.80,
                    decay_rate       = DecayRate.SLOW,
                )
                emitted.append(m)
            elif self._identity_sustained_ticks >= 5:
                m = self.evidence.observe(
                    event            = ObservableEvent.IDENTITY_MOMENT_SUSTAINED,
                    source           = "vdi_engine",
                    vdi_score        = vdi_score,
                    voice_mode       = voice_mode,
                    narrative_weight = 0.85,
                    decay_rate       = DecayRate.ANCHOR,
                )
                emitted.append(m)
        else:
            self._identity_sustained_ticks = 0

        # ── ENGAGEMENT SURGE ──────────────────────────────────────────────────
        if vdi_score >= self.ENGAGEMENT_SURGE_THRESHOLD and self._prev_vdi < self.ENGAGEMENT_SURGE_THRESHOLD:
            m = self.evidence.observe(
                event            = ObservableEvent.AUDIENCE_ENGAGEMENT_SURGE,
                source           = "vdi_engine",
                vdi_score        = vdi_score,
                voice_mode       = voice_mode,
                linked_context   = [f"topic:{current_topic}"] if current_topic else [],
                narrative_weight = 0.60,
                decay_rate       = DecayRate.FAST,
            )
            emitted.append(m)

        # ── ENGAGEMENT DROP ───────────────────────────────────────────────────
        if vdi_score <= self.ENGAGEMENT_DROP_THRESHOLD and self._prev_vdi > self.ENGAGEMENT_DROP_THRESHOLD:
            m = self.evidence.observe(
                event            = ObservableEvent.AUDIENCE_ENGAGEMENT_DROP,
                source           = "vdi_engine",
                vdi_score        = vdi_score,
                voice_mode       = voice_mode,
                linked_context   = [f"topic:{current_topic}"] if current_topic else [],
                narrative_weight = 0.55,
                decay_rate       = DecayRate.FAST,
            )
            emitted.append(m)

        # ── LAUGHTER AFTER TENSION ────────────────────────────────────────────
        if self._tension_this_tick and laughter >= self.LAUGHTER_THRESHOLD:
            m = self.evidence.observe(
                event            = ObservableEvent.LAUGHTER_AFTER_TENSION,
                source           = "vdi_engine",
                vdi_score        = vdi_score,
                voice_mode       = voice_mode,
                narrative_weight = 0.72,
                decay_rate       = DecayRate.MEDIUM,
            )
            emitted.append(m)
            self._tension_this_tick = False

        # ── EXTENDED SILENCE ──────────────────────────────────────────────────
        if silence_p >= self.SILENCE_PRESSURE_THRESHOLD:
            m = self.evidence.observe(
                event            = ObservableEvent.SILENCE_EXTENDED,
                source           = "vdi_engine",
                vdi_score        = vdi_score,
                voice_mode       = voice_mode,
                narrative_weight = 0.65,
                decay_rate       = DecayRate.MEDIUM,
            )
            emitted.append(m)
            self._tension_this_tick = True  # silence → tension → watch for laughter

        # ── PERFORMER TENSION (from EmotionalState) ───────────────────────────
        if emotional_state is not None:
            performer_tension = getattr(emotional_state, "tension", 0.0)
            performer_arousal = getattr(emotional_state, "arousal", 0.5)

            if performer_tension > 0.65 and performer_arousal > 0.60:
                # Tension + arousal = either frustration or excitement
                m = self.evidence.observe(
                    event            = ObservableEvent.INTERRUPT_SPIKE,
                    source           = "prosody_engine",
                    vdi_score        = vdi_score,
                    voice_mode       = voice_mode,
                    linked_context   = [f"tension:{performer_tension:.2f}", f"arousal:{performer_arousal:.2f}"],
                    narrative_weight = 0.68,
                    decay_rate       = DecayRate.MEDIUM,
                )
                emitted.append(m)

        # ── STATE UPDATE ──────────────────────────────────────────────────────
        self._prev_vdi  = vdi_score
        self._prev_mode = voice_mode

        return emitted


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATION HELPER
# Drop-in function for EVOOrchestrator.tick()
# ─────────────────────────────────────────────────────────────────────────────

def create_evidence_layer(
    session_id: str,
    db_path:    Path = DB_PATH,
) -> Tuple[EvidenceLayer, SignalAdapter]:
    """
    Factory. Returns a wired (EvidenceLayer, SignalAdapter) pair.

    Usage in EVOOrchestrator:
        evidence, adapter = create_evidence_layer(session_id)

        # In tick():
        markers = adapter.process_tick(vdi_report, emotional_state, current_topic)

        # In Pete's speak():
        theory_briefing = evidence.get_theory_briefing()

        # On session end:
        evidence.distill_evidence()
    """
    layer   = EvidenceLayer(db_path=db_path, session_id=session_id)
    adapter = SignalAdapter(layer)
    return layer, adapter
