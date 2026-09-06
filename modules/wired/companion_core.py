"""
companion_core.py

The unified entry point. Everything wired together.

This is the layer you call. It runs all four modules
in sequence and produces clean, safe, non-parroting,
meaning-aware responses.

Architecture:
    incoming user message
        → SafeguardLayer.analyze_incoming()   (state + safety)
        → KnownVsNovel.ingest_user_turn()     (self-knowledge tracking)
        → AntiParrotingMonitor.suggest_next() (contribution type)
        → [your LLM generates a response draft]
        → AntiParrotingMonitor.check()        (parroting check)
        → SafeguardLayer.check_outgoing()     (agency check)
        → MeaningMaker.ingest_session()       (end-of-session meaning)
        → clean, safe response

The system optimizes for being useful, not for being correct.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from anti_parroting import (
    AntiParrotingMonitor,
    UserTurn,
    ResponseDraft,
    ContributionType,
    ParrotingRisk,
    create_monitor,
)
from meaning_maker import (
    MeaningMaker,
    MeaningCategory,
    NarrativePhase,
    GrowthSignal,
    create_meaning_maker,
)
from safeguards import (
    SafeguardLayer,
    SafeguardReport,
    EmotionalState,
    DependencySignal,
    create_safeguard_layer,
)
from known_vs_novel import (
    KnownVsNovel,
    InsightCandidate,
    InsightStatus,
    create_novelty_tracker,
)
from contradiction_tracker import (
    ContradictionTracker,
    create_contradiction_tracker,
)


# ─────────────────────────────────────────────
# The Companion Turn
# ─────────────────────────────────────────────

@dataclass
class CompanionTurn:
    """Everything the system knows after processing a single exchange."""
    user_text: str
    response_text: str
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # What the safeguard layer found
    emotional_state: EmotionalState = EmotionalState.PROCESSING
    dependency_signal: DependencySignal = DependencySignal.NONE
    adventure_mode: bool = False

    # What the anti-parroting layer found
    contribution_type: ContributionType = ContributionType.UNKNOWN
    parroting_risk: ParrotingRisk = ParrotingRisk.NONE
    response_approved: bool = True

    # What the novelty layer found
    known_patterns_detected: int = 0
    insights_suppressed: int = 0

    # Guidance for next turn
    suggested_next_contribution: ContributionType = ContributionType.ADVANCE
    warnings: list[str] = field(default_factory=list)
    guidance: list[str] = field(default_factory=list)


@dataclass
class SessionSummary:
    """What the session meant."""
    session_id: str
    turn_count: int
    meaning_summary: dict
    growth_trajectory: str
    session_health: dict
    narrative_update: str
    warnings: list[str]


# ─────────────────────────────────────────────
# Companion Core
# ─────────────────────────────────────────────

class CompanionCore:
    """
    The companion. Everything wired together.

    Not a chatbot memory system.
    Not an emotion detector.
    Not a therapist.

    A good friend with an unusually good memory,
    a curious mind,
    a willingness to challenge you,
    a willingness to support you,
    and a habit of helping you make sense of your own story.

    And above all: an understanding that
    whatever happened, we work with reality as it is now,
    and we make the best of what's next.
    """

    def __init__(self, user_id: str, session_id: str = ""):
        self.user_id = user_id
        self.session_id = session_id or f"session_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        # The four subsystems
        self.safeguards = create_safeguard_layer()
        self.anti_parroting = create_monitor()
        self.meaning = create_meaning_maker(user_id)
        self.novelty = create_novelty_tracker(user_id)
        self.contradictions = create_contradiction_tracker(user_id)

        # Session state
        self.turns: list[CompanionTurn] = []
        self.session_transcript: list[str] = []
        self.session_started = datetime.utcnow()

    # ── Main Processing Loop ───────────────────

    def process_incoming(self, user_text: str) -> dict:
        """
        Process an incoming user message.

        Returns guidance for how the response should be shaped.
        Call this before generating a response.
        """
        self.session_transcript.append(f"USER: {user_text}")

        # 1. Safeguard analysis
        safeguard_report = self.safeguards.analyze_incoming(user_text)

        # 2. Self-knowledge tracking
        self.novelty.ingest_user_turn(user_text)
        self.contradictions.ingest(user_text, self.session_id)

        # 3. Contribution suggestion
        suggested_type = self.anti_parroting.suggest_next_type(user_text)

        return {
            "emotional_state": safeguard_report.emotional_state.value,
            "dependency_signal": safeguard_report.dependency_signal.value,
            "adventure_mode": safeguard_report.adventure_allowed,
            "ready_for_help": self.safeguards.momentum.is_ready_for_help(),
            "is_venting": self.safeguards.momentum.is_venting(),
            "suggested_contribution": suggested_type.value,
            "response_guidance": safeguard_report.response_guidance,
            "blocked_patterns": safeguard_report.blocked_patterns,
            "warnings": safeguard_report.warnings,
            "known_patterns": self.novelty.summary()["known_patterns"],
        }

    def process_outgoing(
        self,
        user_text: str,
        response_text: str,
        intended_contribution: ContributionType = ContributionType.UNKNOWN,
    ) -> CompanionTurn:
        """
        Process an outgoing response.

        Call this after generating a response.
        Returns a CompanionTurn with full analysis.
        """
        self.session_transcript.append(f"COMPANION: {response_text}")

        # Anti-parroting check
        user_turn = UserTurn(text=user_text)
        response_draft = ResponseDraft(
            text=response_text,
            intended_contribution=intended_contribution,
        )
        parroting_report = self.anti_parroting.check(user_turn, response_draft)

        # Agency check + cleanup
        cleaned_response, agency_warnings = self.safeguards.check_outgoing(response_text)

        # Build the turn record
        turn = CompanionTurn(
            user_text=user_text,
            response_text=cleaned_response,
            emotional_state=self.safeguards.momentum.current_state,
            dependency_signal=self.safeguards.independence.dependency_history[-1][0]
                if self.safeguards.independence.dependency_history else DependencySignal.NONE,
            adventure_mode=self.safeguards.adventure.adventures_taken > 0,
            contribution_type=parroting_report.contribution_type,
            parroting_risk=parroting_report.risk,
            response_approved=parroting_report.approved,
            suggested_next_contribution=self.anti_parroting.suggest_next_type(user_text),
            warnings=agency_warnings + parroting_report.violations,
            guidance=parroting_report.suggestions,
        )

        self.turns.append(turn)
        return turn

    def check_insight_before_sharing(self, insight_content: str) -> dict:
        """
        Before surfacing an insight, check if it's actually new.

        Returns whether to share it and how to frame it.
        """
        candidate = InsightCandidate(content=insight_content)
        report = self.novelty.check_insight(candidate)

        result = {
            "should_share": report.should_share,
            "status": report.status.value,
            "caution": report.caution,
            "alternative_frame": report.alternative_frame,
        }

        if report.matching_known and report.status != InsightStatus.NOVEL:
            result["reframe"] = self.novelty.reframe_known_insight(report.matching_known)

        return result

    # ── Meaning Layer ──────────────────────────

    def add_meaning(
        self,
        category: MeaningCategory,
        content: str,
        confidence: float = 0.7,
    ):
        """Manually add a meaning unit — from observation, not just text parsing."""
        self.meaning.add_meaning(category, content, confidence)

    def add_narrative_moment(self, phase: NarrativePhase, description: str):
        self.meaning.add_narrative_moment(phase, description)

    def add_turning_point(self, description: str):
        self.meaning.add_turning_point(description)

    def contrast_with_baseline(self, current_description: str) -> Optional[str]:
        """Generate a 'six months ago' observation if one is warranted."""
        return self.meaning.contrast_with_baseline(current_description)

    # ── Session Lifecycle ──────────────────────

    def end_session(
        self,
        growth_signal: Optional[GrowthSignal] = None,
        growth_description: str = "",
    ) -> SessionSummary:
        """
        Close out the session.
        Extract meaning from the full transcript.
        Return a summary of what happened.
        """
        full_transcript = "\n".join(self.session_transcript)

        meaning_result = self.meaning.ingest_session(
            session_transcript=full_transcript,
            session_id=self.session_id,
            growth_signal=growth_signal,
            growth_description=growth_description,
        )

        session_health = self.anti_parroting.session_health()
        narrative = self.meaning.get_narrative()
        growth = self.meaning.get_growth()

        warnings = []
        if session_health.get("warnings"):
            warnings += session_health["warnings"]

        return SessionSummary(
            session_id=self.session_id,
            turn_count=len(self.turns),
            meaning_summary=meaning_result,
            growth_trajectory=growth.trajectory_summary(),
            session_health=session_health,
            narrative_update=narrative.describe(),
            warnings=warnings,
        )

    def generate_reflection(self) -> str:
        """What has this journey meant so far?"""
        return self.meaning.generate_reflection()

    def full_portrait(self) -> dict:
        """The complete picture — meaning, narrative, and contradictions."""
        portrait = self.meaning.full_meaning_portrait()
        portrait["growth_observation"] = self.contradictions.generate_growth_observation()
        portrait["open_contradictions"] = [
            c.claim_a.text for c in self.contradictions.open_contradictions()[:3]
        ]
        portrait["contradiction_summary"] = self.contradictions.summary()
        return portrait

    def new_session(self, new_session_id: str = "") -> "CompanionCore":
        """
        Start a new session while preserving accumulated meaning and known patterns.
        Returns a new CompanionCore with memory carried forward.
        """
        next_session = CompanionCore(
            user_id=self.user_id,
            session_id=new_session_id or f"session_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
        )
        # Carry forward accumulated meaning and known patterns
        next_session.meaning = self.meaning
        next_session.novelty = self.novelty
        next_session.safeguards.new_session()
        return next_session

    # ── Export / Import ────────────────────────

    def export(self) -> dict:
        """Export full state for persistence."""
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "session_count": self.meaning.session_count,
            "meaning": self.meaning.export(),
            "known_patterns": self.novelty.summary(),
            "turn_count": len(self.turns),
        }

    # ── Diagnostics ───────────────────────────

    def status(self) -> dict:
        """Quick health check of the full system."""
        health = self.anti_parroting.session_health()
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "turns_this_session": len(self.turns),
            "emotional_state": self.safeguards.momentum.current_state.value,
            "dependency_level": self.safeguards.independence.dependency_history[-1][0].value
                if self.safeguards.independence.dependency_history else "none",
            "contribution_health": health.get("approved_rate", "n/a"),
            "parroting_risk": health.get("high_risk_rate", "n/a"),
            "known_patterns": len(self.novelty.known_patterns),
            "meaning_units": len(self.meaning.meaning_units),
            "narrative": self.meaning.narrative.describe(),
        }


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def create_companion(user_id: str, session_id: str = "") -> CompanionCore:
    """Create a new companion instance."""
    return CompanionCore(user_id=user_id, session_id=session_id)


# ─────────────────────────────────────────────
# Demo — Full Session
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("COMPANION CORE — FULL SESSION DEMO")
    print("=" * 60)

    companion = create_companion("user_pete", "demo_session_01")

    exchanges = [
        (
            "Everything is falling apart. My launch failed, nobody showed up, I feel like an idiot.",
            "That's a rough place to be. What felt worst about it — the numbers, or the silence?",
            ContributionType.CLARIFY,
        ),
        (
            "I guess the silence. I thought people cared. Apparently not.",
            "Is this the first time you've put something out and heard nothing back?",
            ContributionType.CHALLENGE,
        ),
        (
            "No, it happens every time. I know I have this pattern of overestimating interest.",
            "You already named it. So the question isn't whether the pattern exists — it's what's different this time.",
            ContributionType.ADVANCE,
        ),
        (
            "I want to try one more time. Build something smaller and actually ship it.",
            "Okay. Let's think through what 'smaller' actually means here. What would you cut first?",
            ContributionType.ADVANCE,
        ),
    ]

    print("\n--- PROCESSING EXCHANGES ---")
    for user_text, response_text, contribution_type in exchanges:
        # Process incoming
        guidance = companion.process_incoming(user_text)
        print(f"\nUser: '{user_text[:60]}...'")
        print(f"  State: {guidance['emotional_state']}")
        print(f"  Suggested contribution: {guidance['suggested_contribution']}")
        if guidance['blocked_patterns']:
            print(f"  BLOCKED: {guidance['blocked_patterns']}")

        # Check if any insight is novel before sharing
        # (In practice, your LLM would generate the response here)
        if "pattern" in response_text:
            insight_check = companion.check_insight_before_sharing(
                "You tend to overestimate interest in your work"
            )
            if not insight_check["should_share"]:
                print(f"  Insight suppressed: {insight_check['caution'][:60]}")
            elif insight_check.get("reframe"):
                print(f"  Insight reframed: {insight_check['reframe'][:60]}")

        # Process outgoing
        turn = companion.process_outgoing(user_text, response_text, contribution_type)
        print(f"  Response: '{response_text[:60]}...'")
        print(f"  Contribution: {turn.contribution_type.value} / Risk: {turn.parroting_risk.value}")
        if turn.warnings:
            print(f"  Warnings: {turn.warnings}")

    # Add some meaning manually
    companion.add_meaning(MeaningCategory.LOST, "Belief that audience would show up without promotion")
    companion.add_meaning(MeaningCategory.LEARNED, "Smaller scope ships more reliably than large vision")
    companion.add_narrative_moment(NarrativePhase.DIRECTION, "Planning a smaller, shippable build")
    companion.add_turning_point("Acknowledged the pattern instead of defending against it")

    print("\n--- SESSION SUMMARY ---")
    summary = companion.end_session(
        growth_signal=GrowthSignal.INCREMENTAL,
        growth_description="acknowledged failure pattern and chose to iterate rather than abandon"
    )
    print(f"Turns: {summary.turn_count}")
    print(f"Meaning extracted: {summary.meaning_summary}")
    print(f"Growth: {summary.growth_trajectory}")
    print(f"Narrative: {summary.narrative_update}")
    if summary.warnings:
        print(f"Warnings: {summary.warnings}")

    print("\n--- REFLECTION ---")
    print(companion.generate_reflection())

    print("\n--- STATUS ---")
    status = companion.status()
    for k, v in status.items():
        print(f"  {k}: {v}")

    print("\n--- WHAT'S NEXT ---")
    print(
        "Whatever happened.\n"
        "Whatever was lost.\n"
        "Whatever was gained.\n"
        "We work with reality as it is now.\n"
        "And we make the best of what's next."
    )
