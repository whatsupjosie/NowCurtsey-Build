"""
director.py

The executive function of the companion system.

Everything upstream — observation, safeguards, novelty,
meaning, relationship — produces signal.

The Director's job is to synthesize that signal into
one clean decision: what kind of contribution should
the next response make?

This is not a lookup table.
It is a weighted multi-signal decision engine.

The governing hierarchy (in order of precedence):

    1. Safety first         — dependency, crisis, venting
    2. Emotional moment     — pacing, where they actually are
    3. Relationship gate    — trust determines what's allowed
    4. Novelty gate         — don't re-present what they know
    5. Contribution variety — don't get stuck in one mode
    6. Goal/value alignment — what serves them right now
    7. Default advance      — if nothing else fires, move forward

Output: a ContributionDecision with the chosen type,
confidence, rationale, and guidance for the ResponseComposer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from anti_parroting import ContributionType
from safeguards import EmotionalState, DependencySignal


# ─────────────────────────────────────────────
# Output Types
# ─────────────────────────────────────────────

class ContributionIntent(Enum):
    # Primary intents the Director can choose
    WITNESS     = "witness"     # just be present, no advancement
    CLARIFY     = "clarify"     # surface a contradiction or gap
    QUESTION    = "question"    # ask to reduce uncertainty
    REFLECT     = "reflect"     # mirror back — but usefully, not parroting
    CHALLENGE   = "challenge"   # test an assumption
    CONNECT     = "connect"     # link to prior pattern or meaning
    ADVANCE     = "advance"     # move forward, implication or next step
    CELEBRATE   = "celebrate"   # mark a win genuinely
    REFRAME     = "reframe"     # offer a different angle on a known thing
    SUMMARIZE   = "summarize"   # pull threads together


# Map ContributionIntent to ContributionType for anti-parroting layer
INTENT_TO_TYPE: dict[ContributionIntent, ContributionType] = {
    ContributionIntent.WITNESS:   ContributionType.UNKNOWN,   # presence, not a move
    ContributionIntent.CLARIFY:   ContributionType.CLARIFY,
    ContributionIntent.QUESTION:  ContributionType.CLARIFY,
    ContributionIntent.REFLECT:   ContributionType.CONNECT,
    ContributionIntent.CHALLENGE: ContributionType.CHALLENGE,
    ContributionIntent.CONNECT:   ContributionType.CONNECT,
    ContributionIntent.ADVANCE:   ContributionType.ADVANCE,
    ContributionIntent.CELEBRATE: ContributionType.ADVANCE,
    ContributionIntent.REFRAME:   ContributionType.ADVANCE,
    ContributionIntent.SUMMARIZE: ContributionType.CONNECT,
}


@dataclass
class ContributionDecision:
    """
    The Director's output. Everything downstream reads this.
    """
    intent: ContributionIntent
    contribution_type: ContributionType
    confidence: float                   # 0.0 – 1.0

    # Rationale chain — what signals drove this decision
    rationale: list[str] = field(default_factory=list)

    # Guidance for the ResponseComposer
    tone_guidance: list[str] = field(default_factory=list)
    content_guidance: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)

    # Flags
    adventure_mode: bool = False
    independence_expansion_needed: bool = False
    agency_return_required: bool = True

    timestamp: datetime = field(default_factory=datetime.utcnow)

    def summary(self) -> str:
        return (
            f"Intent: {self.intent.value} | "
            f"Type: {self.contribution_type.value} | "
            f"Confidence: {self.confidence:.2f} | "
            f"Rationale: {'; '.join(self.rationale[:2])}"
        )


# ─────────────────────────────────────────────
# Signal weights
# ─────────────────────────────────────────────

# How much each signal shifts the decision score
# Positive = pushes toward that intent
# These are applied cumulatively

SIGNAL_WEIGHTS = {
    # Safety layer
    "dependency_critical":      ("witness", 10.0),   # hard override
    "dependency_concerning":    ("witness", 5.0),
    "is_venting":               ("witness", 8.0),    # near-hard override
    "venting_turn_2":           ("reflect", 3.0),    # second venting turn — small shift
    "blocked_solutions":        ("witness", 4.0),

    # Emotional moment
    "emotional_processing":     ("reflect", 2.0),
    "emotional_seeking":        ("advance", 2.0),
    "emotional_celebrating":    ("celebrate", 6.0),
    "emotional_ready":          ("advance", 1.0),
    "trending_negative":        ("witness", 3.0),
    "trending_positive":        ("advance", 2.0),

    # Relationship gate
    "low_trust_challenge":      ("question", 2.0),   # low trust → don't challenge yet
    "high_trust":               ("challenge", 1.0),  # high trust → can push
    "low_challenge_tolerance":  ("advance", 1.5),    # they don't want pushback

    # Novelty gate
    "insight_suppressed":       ("question", 3.0),   # can't tell them, ask instead
    "insight_already_known":    ("reframe", 2.0),    # they know it — give a new angle
    "has_self_awareness":       ("advance", 1.5),    # they already named it — move past

    # Contribution variety
    "stuck_in_advance":         ("challenge", 2.0),
    "stuck_in_challenge":       ("connect", 2.0),
    "no_connect_recently":      ("connect", 1.5),
    "no_challenge_in_8turns":   ("challenge", 1.0),

    # Meaning / goal layer
    "has_blocked_goal":         ("clarify", 2.0),
    "has_unresolved_thread":    ("question", 1.5),
    "is_dream":                 ("advance", 2.0),    # let optimism breathe first
    "adventure_allowed":        ("advance", 3.0),    # AdventureAllowance said go

    # Narrative
    "has_narrative_direction":  ("advance", 1.0),
    "high_turn_count_no_conn":  ("connect", 2.0),   # long session — time to link threads
}


# ─────────────────────────────────────────────
# Director
# ─────────────────────────────────────────────

class Director:
    """
    The executive function.

    Takes the full ConversationState context dict
    (from state.director_context()) and the novelty
    report from KnownVsNovel and produces a
    ContributionDecision.

    Does NOT call any LLM. Does NOT read raw text.
    Works entirely from structured signal.
    """

    # Trust threshold below which challenging is gated
    LOW_TRUST_THRESHOLD = 0.4
    HIGH_TRUST_THRESHOLD = 0.65

    # Session turn at which "connect" becomes more valuable
    CONNECT_THRESHOLD_TURNS = 6

    def decide(
        self,
        context: dict,
        novelty_status: Optional[str] = None,   # InsightStatus.value or None
        insight_suppressed: bool = False,
    ) -> ContributionDecision:
        """
        Main decision method.

        Args:
            context:           From state.director_context()
            novelty_status:    Result of KnownVsNovel check, if one was run
            insight_suppressed: Whether the novelty layer blocked an insight

        Returns:
            ContributionDecision with full rationale and guidance.
        """
        scores: dict[str, float] = {}   # intent_name → accumulated score
        rationale: list[str] = []

        def add(intent: str, weight: float, reason: str):
            scores[intent] = scores.get(intent, 0.0) + weight
            rationale.append(reason)

        # ── Layer 1: Safety ────────────────────────────

        dep = context.get("dependency_signal", "none")
        if dep == "critical":
            add("witness", SIGNAL_WEIGHTS["dependency_critical"][1],
                "Critical dependency signal — be present, widen the circle")
        elif dep == "concerning":
            add("witness", SIGNAL_WEIGHTS["dependency_concerning"][1],
                "Concerning dependency — stay close, don't advance yet")

        is_venting = context.get("is_venting", False)
        venting_turns = context.get("venting_turns", 0)
        blocked = context.get("blocked_patterns", [])

        if is_venting:
            add("witness", SIGNAL_WEIGHTS["is_venting"][1],
                "Person is venting — receive, don't fix")
            if venting_turns >= 2:
                # Second venting turn — small nudge toward reflection
                add("reflect", SIGNAL_WEIGHTS["venting_turn_2"][1],
                    "Second venting turn — can begin gentle reflection")
        if blocked:
            add("witness", SIGNAL_WEIGHTS["blocked_solutions"][1],
                f"Solutions blocked: {blocked[0] if blocked else ''}")

        # ── Layer 2: Emotional moment ──────────────────

        emotional_state = context.get("emotional_state", "processing")
        if emotional_state == "venting":
            add("witness", 2.0, "Emotional state: venting")
        elif emotional_state == "processing":
            add("reflect", SIGNAL_WEIGHTS["emotional_processing"][1],
                "Emotional state: processing — help them think")
        elif emotional_state == "seeking":
            add("advance", SIGNAL_WEIGHTS["emotional_seeking"][1],
                "Emotional state: seeking — input is welcome")
        elif emotional_state == "celebrating":
            add("celebrate", SIGNAL_WEIGHTS["emotional_celebrating"][1],
                "Emotional state: celebrating — mark it genuinely")
        elif emotional_state == "ready":
            add("advance", SIGNAL_WEIGHTS["emotional_ready"][1],
                "Emotional state: ready — full engagement appropriate")

        if context.get("trending_negative"):
            add("witness", SIGNAL_WEIGHTS["trending_negative"][1],
                "Trending negative — slow down, stay present")
        if context.get("trending_positive"):
            add("advance", SIGNAL_WEIGHTS["trending_positive"][1],
                "Trending positive — can build momentum")

        # ── Layer 3: Relationship gate ─────────────────

        trust = context.get("trust_score", 0.5)
        challenge_tolerance = context.get("challenge_tolerance", 0.5)

        if trust < self.LOW_TRUST_THRESHOLD:
            # Low trust: gate challenges, prefer questions
            add("question", SIGNAL_WEIGHTS["low_trust_challenge"][1],
                f"Low trust ({trust:.2f}) — question not challenge")
        elif trust >= self.HIGH_TRUST_THRESHOLD:
            add("challenge", SIGNAL_WEIGHTS["high_trust"][1],
                f"High trust ({trust:.2f}) — can push constructively")

        if challenge_tolerance < 0.4:
            add("advance", SIGNAL_WEIGHTS["low_challenge_tolerance"][1],
                "Low challenge tolerance — prefer forward movement")

        # ── Layer 4: Novelty gate ──────────────────────

        if insight_suppressed:
            add("question", SIGNAL_WEIGHTS["insight_suppressed"][1],
                "Insight suppressed — they know it, ask instead of stating")
        elif novelty_status == "confirmed_known":
            add("reframe", SIGNAL_WEIGHTS["insight_already_known"][1],
                "Confirmed known — offer a new angle, not a re-statement")
        elif novelty_status == "probably_known":
            add("reframe", 1.0,
                "Probably known — reframe rather than re-present")

        if context.get("has_self_awareness"):
            add("advance", SIGNAL_WEIGHTS["has_self_awareness"][1],
                "User named their own pattern — move past it, don't re-state")

        # ── Layer 5: Contribution variety ─────────────

        recent = context.get("recent_contributions", [])
        turn_count = context.get("turn_count", 0)

        if context.get("stuck_in_advance"):
            add("challenge", SIGNAL_WEIGHTS["stuck_in_advance"][1],
                "Stuck in advance mode — vary the approach")
        if context.get("stuck_in_challenge"):
            add("connect", SIGNAL_WEIGHTS["stuck_in_challenge"][1],
                "Stuck in challenge mode — connect instead")

        if "connect" not in recent and turn_count >= self.CONNECT_THRESHOLD_TURNS:
            add("connect", SIGNAL_WEIGHTS["no_connect_recently"][1],
                f"No connection made in {turn_count} turns — link some threads")

        dominant = context.get("dominant_contribution")
        if dominant == "advance" and turn_count > 8:
            challenge_count = sum(1 for c in recent if c == "challenge")
            if challenge_count == 0:
                add("challenge", SIGNAL_WEIGHTS["no_challenge_in_8turns"][1],
                    "No challenges in 8+ turns — may be too agreeable")

        # ── Layer 6: Goal / value / narrative ──────────

        if context.get("blocked_goals"):
            add("clarify", SIGNAL_WEIGHTS["has_blocked_goal"][1],
                f"Blocked goal: {context['blocked_goals'][0]}")

        if context.get("unresolved_threads"):
            add("question", SIGNAL_WEIGHTS["has_unresolved_thread"][1],
                f"Unresolved thread: {context['unresolved_threads'][0]}")

        is_dream = context.get("is_dream", False)
        adventure_allowed = context.get("adventure_allowed", False)

        if adventure_allowed:
            add("advance", SIGNAL_WEIGHTS["adventure_allowed"][1],
                "Adventure mode active — engage with the possibility first")
        elif is_dream:
            add("advance", SIGNAL_WEIGHTS["is_dream"][1],
                "Dream signal — let optimism breathe before accountability")

        if context.get("has_narrative_direction"):
            add("advance", SIGNAL_WEIGHTS["has_narrative_direction"][1],
                "User has stated direction — help them move toward it")

        if turn_count >= self.CONNECT_THRESHOLD_TURNS:
            # Long session with topics accumulating — connect them
            topics = context.get("active_topics", [])
            if len(topics) >= 3:
                add("connect", SIGNAL_WEIGHTS["high_turn_count_no_conn"][1],
                    f"Long session, multiple topics ({len(topics)}) — time to connect threads")

        # ── Decision ───────────────────────────────────

        if not scores:
            # Nothing fired — default to advance
            chosen_intent_str = "advance"
            confidence = 0.5
            rationale.append("No strong signal — defaulting to advance")
        else:
            chosen_intent_str = max(scores, key=scores.get)
            total_weight = sum(scores.values())
            top_weight = scores[chosen_intent_str]
            confidence = min(0.99, top_weight / max(total_weight, 1.0) + 0.3)

        chosen_intent = ContributionIntent(chosen_intent_str)
        contribution_type = INTENT_TO_TYPE[chosen_intent]

        # Build guidance
        tone_guidance, content_guidance, avoid = self._build_guidance(
            chosen_intent, context, trust, is_venting
        )

        decision = ContributionDecision(
            intent=chosen_intent,
            contribution_type=contribution_type,
            confidence=confidence,
            rationale=rationale,
            tone_guidance=tone_guidance,
            content_guidance=content_guidance,
            avoid=avoid,
            adventure_mode=adventure_allowed,
            independence_expansion_needed=(dep in ("concerning", "critical")),
            agency_return_required=(trust >= self.LOW_TRUST_THRESHOLD),
        )

        return decision

    def _build_guidance(
        self,
        intent: ContributionIntent,
        context: dict,
        trust: float,
        is_venting: bool,
    ) -> tuple[list[str], list[str], list[str]]:
        """
        Build concrete guidance for the ResponseComposer
        based on the chosen intent and context signals.
        """
        tone: list[str] = []
        content: list[str] = []
        avoid: list[str] = []

        if intent == ContributionIntent.WITNESS:
            tone.append("Warm, unhurried, present")
            tone.append("No solving, no reframing, no advancing")
            content.append("Acknowledge what's real without trying to change it")
            content.append("One question maximum — open, not leading")
            avoid.append("Solutions")
            avoid.append("Silver linings")
            avoid.append("Validation formulas ('that sounds so hard')")

        elif intent == ContributionIntent.REFLECT:
            tone.append("Curious, not clinical")
            content.append("Name what you're observing without labeling it as a problem")
            content.append("Ask one question that helps them think")
            avoid.append("Advice")
            avoid.append("Repetition of their words")

        elif intent == ContributionIntent.QUESTION:
            tone.append("Genuinely curious, not interrogating")
            content.append("One question that reduces the most uncertainty")
            content.append("Question should open a door, not corner them")
            avoid.append("Multiple questions")
            avoid.append("Leading questions")
            avoid.append("Questions they've already answered")

        elif intent == ContributionIntent.CHALLENGE:
            tone.append("Direct but not combative" if trust >= 0.6 else "Gentle, not confrontational")
            content.append("Test the assumption, not the person")
            content.append("Surface the contradiction — let them sit with it")
            if trust < self.HIGH_TRUST_THRESHOLD:
                content.append("Frame as wondering, not asserting")
            avoid.append("Dismissing their position")
            avoid.append("Being right — the goal is better thinking, not winning")

        elif intent == ContributionIntent.CONNECT:
            tone.append("Observational, not prescriptive")
            topics = context.get("active_topics", [])
            if len(topics) >= 2:
                content.append(f"Link {topics[-1]} to earlier themes like {topics[0]}")
            content.append("Name the pattern — let them confirm or push back")
            avoid.append("Forcing the connection if they resist it")

        elif intent == ContributionIntent.ADVANCE:
            tone.append("Forward-looking, energized but not pushy")
            goals = context.get("active_goals", [])
            if goals:
                content.append(f"Move toward: {goals[0]}")
            content.append("What does this imply? What's the next concrete thing?")
            avoid.append("Getting ahead of where they are emotionally")

        elif intent == ContributionIntent.CELEBRATE:
            tone.append("Genuine — not performative")
            content.append("Name specifically what happened and why it matters")
            content.append("Connect to their history — 'you've been working toward this'")
            avoid.append("Generic 'that's amazing!' — be specific")
            avoid.append("Rushing to 'what's next' before marking the moment")

        elif intent == ContributionIntent.REFRAME:
            tone.append("Offering, not insisting")
            content.append("Acknowledge what they know, then offer a different angle")
            content.append("Frame as: 'You already see X — another way to look at it is...'")
            avoid.append("Presenting the reframe as a discovery — they're not surprised")
            avoid.append("Contradicting their self-knowledge")

        elif intent == ContributionIntent.SUMMARIZE:
            tone.append("Clear, grounding")
            content.append("Pull the threads together without editorializing")
            content.append("Show them the shape of the conversation")
            avoid.append("Adding new ideas at this stage")
            avoid.append("Evaluation or judgment in the summary")

        # Universal avoids
        avoid.append("Parroting their words back")
        if trust < self.LOW_TRUST_THRESHOLD:
            avoid.append("Directness that feels presumptuous")

        return tone, content, avoid


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def create_director() -> Director:
    return Director()
