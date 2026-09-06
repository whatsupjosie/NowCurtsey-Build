"""
conversation_state.py

The single source of truth for an entire conversation.

Every module reads from this.
Every module writes to this.
Nothing operates on raw text after the ObservationEngine runs.

This is not a simple dataclass. It is a living document
that accumulates signal across turns and exposes
structured views of that signal to the Director.

Design rules:
    - All fields are typed. No raw dicts floating around.
    - Writes go through methods, not direct field assignment.
      This ensures history is always preserved.
    - The state is exportable and importable for persistence.
    - Nothing in here calls an LLM. It is pure data management.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional, Any

from observation_engine import ObservationBundle, ExtractedEmotion, ExtractedGoal
from safeguards import EmotionalState, DependencySignal
from anti_parroting import ContributionType
from known_vs_novel import KnownPattern, InsightStatus
from meaning_maker import MeaningUnit, MeaningCategory, NarrativePhase, GrowthSignal


# ─────────────────────────────────────────────
# Sub-state types
# ─────────────────────────────────────────────

@dataclass
class TurnRecord:
    """Everything that happened in one exchange."""
    turn_index: int
    timestamp: datetime
    user_text: str

    # Observation layer output
    dominant_emotion: Optional[str] = None
    dominant_goal: Optional[str] = None
    primary_topic: str = ""
    is_venting: bool = False
    is_dream: bool = False
    is_seeking_help: bool = False
    is_celebrating: bool = False
    has_self_awareness: bool = False
    values_detected: list[str] = field(default_factory=list)

    # Safeguard layer output
    emotional_state: EmotionalState = EmotionalState.PROCESSING
    dependency_signal: DependencySignal = DependencySignal.NONE
    adventure_allowed: bool = False
    blocked_patterns: list[str] = field(default_factory=list)

    # Director decision
    intended_contribution: ContributionType = ContributionType.ADVANCE
    response_text: str = ""

    # Quality signals
    parroting_risk: str = "none"
    response_approved: bool = True
    warnings: list[str] = field(default_factory=list)


@dataclass
class EmotionalProfile:
    """
    Accumulated emotional picture across the session.
    Not a snapshot — a trajectory.
    """
    current_state: EmotionalState = EmotionalState.PROCESSING
    dominant_emotion: Optional[str] = None
    emotion_history: list[tuple[datetime, str, float]] = field(default_factory=list)
    # (timestamp, emotion_label, intensity)

    dependency_signal: DependencySignal = DependencySignal.NONE
    dependency_history: list[tuple[datetime, DependencySignal]] = field(default_factory=list)

    venting_turns: int = 0
    seeking_turns: int = 0
    celebrating_turns: int = 0

    def update(self, bundle: ObservationBundle, state: EmotionalState, dep: DependencySignal):
        self.current_state = state
        self.dependency_signal = dep
        self.dependency_history.append((datetime.utcnow(), dep))

        if bundle.emotions:
            top = max(bundle.emotions, key=lambda e: e.intensity)
            self.dominant_emotion = top.label
            self.emotion_history.append((datetime.utcnow(), top.label, top.intensity))

        if bundle.is_venting:
            self.venting_turns += 1
        if bundle.is_seeking_help:
            self.seeking_turns += 1
        if bundle.is_celebrating:
            self.celebrating_turns += 1

    def emotion_trend(self, n: int = 5) -> list[str]:
        return [label for _, label, _ in self.emotion_history[-n:]]

    def is_trending_positive(self) -> bool:
        positive = {"happy", "hopeful", "proud", "excited"}
        recent = self.emotion_trend(3)
        return sum(1 for e in recent if e in positive) >= 2

    def is_trending_negative(self) -> bool:
        negative = {"devastated", "hopeless", "ashamed", "heartbroken", "exhausted"}
        recent = self.emotion_trend(3)
        return sum(1 for e in recent if e in negative) >= 2


@dataclass
class GoalProfile:
    """What the user is trying to do — stated and implied."""
    active_goals: list[str] = field(default_factory=list)
    blocked_goals: list[str] = field(default_factory=list)
    completed_goals: list[str] = field(default_factory=list)
    goal_history: list[tuple[datetime, str, bool]] = field(default_factory=list)
    # (timestamp, goal_text, stated)

    def update(self, goals: list[ExtractedGoal]):
        for g in goals:
            if g.description not in self.active_goals:
                self.active_goals.append(g.description)
                self.goal_history.append((datetime.utcnow(), g.description, g.stated))
            if g.blocked and g.description not in self.blocked_goals:
                self.blocked_goals.append(g.description)


@dataclass
class ValueProfile:
    """What matters to them, accumulated across the session."""
    detected_values: dict[str, int] = field(default_factory=dict)
    # value_label → mention_count

    def update(self, values: list[str]):
        for v in values:
            self.detected_values[v] = self.detected_values.get(v, 0) + 1

    def top_values(self, n: int = 3) -> list[str]:
        sorted_vals = sorted(
            self.detected_values.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return [v for v, _ in sorted_vals[:n]]


@dataclass
class NarrativeProfile:
    """The story structure accumulating across turns."""
    before: list[str] = field(default_factory=list)    # where they came from
    after: list[str] = field(default_factory=list)     # where they are now
    direction: list[str] = field(default_factory=list) # where they're going
    active_topics: list[str] = field(default_factory=list)
    unresolved_threads: list[str] = field(default_factory=list)
    turning_points: list[str] = field(default_factory=list)

    def update(self, bundle: ObservationBundle):
        for item in bundle.narrative_before:
            if item not in self.before:
                self.before.append(item)
        for item in bundle.narrative_after:
            if item not in self.after:
                self.after.append(item)
        for item in bundle.narrative_direction:
            if item not in self.direction:
                self.direction.append(item)
        if bundle.primary_topic and bundle.primary_topic not in self.active_topics:
            self.active_topics.append(bundle.primary_topic)
        # Keep active_topics to last 10
        if len(self.active_topics) > 10:
            self.active_topics = self.active_topics[-10:]


@dataclass
class KnowledgeProfile:
    """What the system knows about what the user already knows."""
    known_patterns: list[KnownPattern] = field(default_factory=list)
    suppressed_insights: int = 0
    reframed_insights: int = 0

    def update(self, patterns: list[KnownPattern], suppressed: int = 0, reframed: int = 0):
        # Merge patterns without duplicating
        existing_ids = {p.id for p in self.known_patterns}
        for p in patterns:
            if p.id not in existing_ids:
                self.known_patterns.append(p)
        self.suppressed_insights += suppressed
        self.reframed_insights += reframed


@dataclass
class RelationshipProfile:
    """
    The trust and dynamic between the system and user.
    Updated based on how interactions land.
    """
    trust_score: float = 0.5            # 0.0 = no trust, 1.0 = full trust
    challenge_tolerance: float = 0.5    # how much pushback they welcome
    directness_tolerance: float = 0.5   # how direct they want responses
    repair_score: float = 1.0           # no ruptures yet
    session_count: int = 0

    def update_from_turn(self, turn: TurnRecord):
        # Trust rises slowly with clean turns, drops with warnings
        if turn.response_approved and not turn.warnings:
            self.trust_score = min(1.0, self.trust_score + 0.02)
        elif turn.warnings:
            self.trust_score = max(0.0, self.trust_score - 0.05)

        # If they're seeking help, they're tolerating directness
        if turn.is_seeking_help:
            self.directness_tolerance = min(1.0, self.directness_tolerance + 0.03)

        # If adventure mode fired, they're open to exploration
        if turn.adventure_allowed:
            self.challenge_tolerance = min(1.0, self.challenge_tolerance + 0.03)


@dataclass
class ContributionHistory:
    """Track what kinds of contributions have been made."""
    counts: dict[str, int] = field(default_factory=dict)
    recent: list[str] = field(default_factory=list)  # last 5

    def record(self, contribution_type: ContributionType):
        key = contribution_type.value
        self.counts[key] = self.counts.get(key, 0) + 1
        self.recent.append(key)
        if len(self.recent) > 5:
            self.recent = self.recent[-5:]

    def dominant(self) -> Optional[str]:
        if not self.counts:
            return None
        return max(self.counts, key=self.counts.get)

    def is_stuck_in(self, contribution_type: str, threshold: int = 3) -> bool:
        if len(self.recent) < threshold:
            return False
        return all(c == contribution_type for c in self.recent[-threshold:])


# ─────────────────────────────────────────────
# ConversationState — the unified truth
# ─────────────────────────────────────────────

class ConversationState:
    """
    The living document of a conversation.

    Every module reads from this.
    Every module writes to this.

    It is never passed as a raw dict. It exposes
    structured views so modules don't have to
    know about each other's internals.

    Lifecycle:
        created once per session
        updated after every turn
        exported at session end for persistence
        restored from export at session start
    """

    def __init__(self, user_id: str, session_id: str = ""):
        self.user_id = user_id
        self.session_id = session_id or f"session_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        self.created_at = datetime.utcnow()
        self.turn_count = 0

        # Sub-states — all typed, all structured
        self.emotional = EmotionalProfile()
        self.goals = GoalProfile()
        self.values = ValueProfile()
        self.narrative = NarrativeProfile()
        self.knowledge = KnowledgeProfile()
        self.relationship = RelationshipProfile()
        self.contributions = ContributionHistory()

        # Turn history
        self.turns: list[TurnRecord] = []

        # Reasoning trace — every significant decision recorded
        self.reasoning_trace: list[dict] = []

        # Raw session transcript for meaning extraction
        self._transcript_lines: list[str] = []

    # ── Turn lifecycle ─────────────────────────

    def begin_turn(self, user_text: str) -> TurnRecord:
        """Open a new turn. Returns a TurnRecord to be filled in."""
        self.turn_count += 1
        self._transcript_lines.append(f"USER: {user_text}")
        turn = TurnRecord(
            turn_index=self.turn_count,
            timestamp=datetime.utcnow(),
            user_text=user_text,
        )
        return turn

    def apply_observation(self, turn: TurnRecord, bundle: ObservationBundle):
        """Write ObservationBundle signal into the turn and state."""
        turn.dominant_emotion = bundle.dominant_emotion
        turn.dominant_goal = bundle.dominant_goal
        turn.primary_topic = bundle.primary_topic
        turn.is_venting = bundle.is_venting
        turn.is_dream = bundle.is_dream
        turn.is_seeking_help = bundle.is_seeking_help
        turn.is_celebrating = bundle.is_celebrating
        turn.has_self_awareness = bundle.has_self_awareness
        turn.values_detected = list(bundle.values)

        # Update sub-states
        self.goals.update(bundle.goals)
        self.values.update(bundle.values)
        self.narrative.update(bundle)

        self._trace("observation", {
            "dominant_emotion": bundle.dominant_emotion,
            "is_venting": bundle.is_venting,
            "is_dream": bundle.is_dream,
            "topic": bundle.primary_topic,
            "confidence": bundle.confidence.value,
        })

    def apply_safeguards(
        self,
        turn: TurnRecord,
        emotional_state: EmotionalState,
        dependency_signal: DependencySignal,
        adventure_allowed: bool,
        blocked_patterns: list[str],
    ):
        """Write SafeguardLayer output into the turn and state."""
        turn.emotional_state = emotional_state
        turn.dependency_signal = dependency_signal
        turn.adventure_allowed = adventure_allowed
        turn.blocked_patterns = blocked_patterns

        self.emotional.update(
            bundle=self._last_bundle_placeholder(turn),
            state=emotional_state,
            dep=dependency_signal,
        )

        self._trace("safeguards", {
            "emotional_state": emotional_state.value,
            "dependency": dependency_signal.value,
            "adventure": adventure_allowed,
            "blocked": blocked_patterns,
        })

    def apply_contribution(
        self,
        turn: TurnRecord,
        contribution_type: ContributionType,
        response_text: str,
        parroting_risk: str,
        approved: bool,
        warnings: list[str],
    ):
        """Write contribution decision into turn and state."""
        turn.intended_contribution = contribution_type
        turn.response_text = response_text
        turn.parroting_risk = parroting_risk
        turn.response_approved = approved
        turn.warnings = warnings

        self.contributions.record(contribution_type)
        self._transcript_lines.append(f"COMPANION: {response_text}")

        self._trace("contribution", {
            "type": contribution_type.value,
            "approved": approved,
            "risk": parroting_risk,
            "warnings": warnings,
        })

    def close_turn(self, turn: TurnRecord):
        """Finalize the turn. Update relationship profile."""
        self.turns.append(turn)
        self.relationship.update_from_turn(turn)

    # ── Structured views for Director ─────────

    def director_context(self) -> dict:
        """
        Everything the Director needs to make a decision.
        Structured, typed, no raw text.
        """
        return {
            # Current moment
            "turn_count": self.turn_count,
            "emotional_state": self.emotional.current_state.value,
            "dominant_emotion": self.emotional.dominant_emotion,
            "dependency_signal": self.emotional.dependency_signal.value,
            "is_venting": self.turns[-1].is_venting if self.turns else False,
            "is_dream": self.turns[-1].is_dream if self.turns else False,
            "is_seeking_help": self.turns[-1].is_seeking_help if self.turns else False,
            "is_celebrating": self.turns[-1].is_celebrating if self.turns else False,
            "has_self_awareness": self.turns[-1].has_self_awareness if self.turns else False,
            "adventure_allowed": self.turns[-1].adventure_allowed if self.turns else False,
            "blocked_patterns": self.turns[-1].blocked_patterns if self.turns else [],

            # Trajectory
            "emotion_trend": self.emotional.emotion_trend(3),
            "trending_positive": self.emotional.is_trending_positive(),
            "trending_negative": self.emotional.is_trending_negative(),
            "venting_turns": self.emotional.venting_turns,
            "seeking_turns": self.emotional.seeking_turns,

            # What they care about
            "active_goals": self.goals.active_goals[-3:],
            "blocked_goals": self.goals.blocked_goals,
            "top_values": self.values.top_values(3),

            # Narrative
            "active_topics": self.narrative.active_topics[-5:],
            "unresolved_threads": self.narrative.unresolved_threads,
            "has_narrative_before": bool(self.narrative.before),
            "has_narrative_direction": bool(self.narrative.direction),

            # Self-knowledge
            "known_pattern_count": len(self.knowledge.known_patterns),
            "suppressed_insights": self.knowledge.suppressed_insights,

            # Relationship
            "trust_score": self.relationship.trust_score,
            "challenge_tolerance": self.relationship.challenge_tolerance,
            "directness_tolerance": self.relationship.directness_tolerance,

            # Contribution history
            "recent_contributions": self.contributions.recent,
            "dominant_contribution": self.contributions.dominant(),
            "stuck_in_advance": self.contributions.is_stuck_in("advance"),
            "stuck_in_challenge": self.contributions.is_stuck_in("challenge"),
        }

    def response_composer_context(self) -> dict:
        """What the ResponseComposer needs to shape the final response."""
        return {
            "trust_score": self.relationship.trust_score,
            "challenge_tolerance": self.relationship.challenge_tolerance,
            "directness_tolerance": self.relationship.directness_tolerance,
            "emotional_state": self.emotional.current_state.value,
            "trending_positive": self.emotional.is_trending_positive(),
            "top_values": self.values.top_values(3),
            "active_topics": self.narrative.active_topics[-3:],
            "turn_count": self.turn_count,
        }

    # ── Transcript ─────────────────────────────

    def transcript(self) -> str:
        return "\n".join(self._transcript_lines)

    def add_unresolved_thread(self, thread: str):
        if thread not in self.narrative.unresolved_threads:
            self.narrative.unresolved_threads.append(thread)

    def resolve_thread(self, thread: str):
        self.narrative.unresolved_threads = [
            t for t in self.narrative.unresolved_threads if t != thread
        ]

    # ── Export / Import ────────────────────────

    def export(self) -> dict:
        """Serialize full state for persistence."""
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "turn_count": self.turn_count,
            "emotional": {
                "current_state": self.emotional.current_state.value,
                "dominant_emotion": self.emotional.dominant_emotion,
                "venting_turns": self.emotional.venting_turns,
                "seeking_turns": self.emotional.seeking_turns,
                "celebrating_turns": self.emotional.celebrating_turns,
                "trust_score": self.relationship.trust_score,
                "challenge_tolerance": self.relationship.challenge_tolerance,
            },
            "goals": {
                "active": self.goals.active_goals,
                "blocked": self.goals.blocked_goals,
                "completed": self.goals.completed_goals,
            },
            "values": self.values.detected_values,
            "narrative": {
                "before": self.narrative.before,
                "after": self.narrative.after,
                "direction": self.narrative.direction,
                "active_topics": self.narrative.active_topics,
                "unresolved_threads": self.narrative.unresolved_threads,
                "turning_points": self.narrative.turning_points,
            },
            "knowledge": {
                "known_pattern_count": len(self.knowledge.known_patterns),
                "suppressed_insights": self.knowledge.suppressed_insights,
            },
            "contributions": {
                "counts": self.contributions.counts,
                "recent": self.contributions.recent,
            },
            "reasoning_trace": self.reasoning_trace[-50:],  # last 50 entries
        }

    @classmethod
    def from_export(cls, data: dict) -> "ConversationState":
        """Restore state from a previous export."""
        state = cls(
            user_id=data["user_id"],
            session_id=data.get("session_id", ""),
        )
        state.turn_count = data.get("turn_count", 0)

        em = data.get("emotional", {})
        if em.get("current_state"):
            state.emotional.current_state = EmotionalState(em["current_state"])
        state.emotional.dominant_emotion = em.get("dominant_emotion")
        state.emotional.venting_turns = em.get("venting_turns", 0)
        state.emotional.seeking_turns = em.get("seeking_turns", 0)
        state.emotional.celebrating_turns = em.get("celebrating_turns", 0)
        state.relationship.trust_score = em.get("trust_score", 0.5)
        state.relationship.challenge_tolerance = em.get("challenge_tolerance", 0.5)

        goals = data.get("goals", {})
        state.goals.active_goals = goals.get("active", [])
        state.goals.blocked_goals = goals.get("blocked", [])
        state.goals.completed_goals = goals.get("completed", [])

        state.values.detected_values = data.get("values", {})

        nav = data.get("narrative", {})
        state.narrative.before = nav.get("before", [])
        state.narrative.after = nav.get("after", [])
        state.narrative.direction = nav.get("direction", [])
        state.narrative.active_topics = nav.get("active_topics", [])
        state.narrative.unresolved_threads = nav.get("unresolved_threads", [])
        state.narrative.turning_points = nav.get("turning_points", [])

        contribs = data.get("contributions", {})
        state.contributions.counts = contribs.get("counts", {})
        state.contributions.recent = contribs.get("recent", [])

        state.reasoning_trace = data.get("reasoning_trace", [])

        return state

    # ── Diagnostics ───────────────────────────

    def snapshot(self) -> dict:
        """Quick human-readable snapshot of current state."""
        return {
            "session": self.session_id,
            "turns": self.turn_count,
            "emotional_state": self.emotional.current_state.value,
            "dominant_emotion": self.emotional.dominant_emotion,
            "trust": round(self.relationship.trust_score, 2),
            "top_values": self.values.top_values(3),
            "active_goals": self.goals.active_goals[-2:],
            "active_topics": self.narrative.active_topics[-3:],
            "recent_contributions": self.contributions.recent,
            "known_patterns": len(self.knowledge.known_patterns),
            "unresolved_threads": self.narrative.unresolved_threads,
        }

    # ── Internal ──────────────────────────────

    def _trace(self, module: str, data: dict):
        self.reasoning_trace.append({
            "turn": self.turn_count,
            "timestamp": datetime.utcnow().isoformat(),
            "module": module,
            **data,
        })

    def _last_bundle_placeholder(self, turn: TurnRecord):
        """
        EmotionalProfile.update() needs a bundle for emotion history.
        We reconstruct a minimal one from the turn record.
        """
        from observation_engine import ObservationBundle, ExtractedEmotion
        bundle = ObservationBundle(raw_text=turn.user_text)
        if turn.dominant_emotion:
            bundle.emotions = [ExtractedEmotion(
                label=turn.dominant_emotion,
                intensity=0.7,
            )]
            bundle.dominant_emotion = turn.dominant_emotion
        bundle.is_venting = turn.is_venting
        bundle.is_seeking_help = turn.is_seeking_help
        bundle.is_celebrating = turn.is_celebrating
        return bundle


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def create_conversation_state(user_id: str, session_id: str = "") -> ConversationState:
    return ConversationState(user_id=user_id, session_id=session_id)
