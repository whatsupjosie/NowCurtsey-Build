"""
pubcast_runtime.py

The full wired system. Every module connected. Nothing missing.

This is the single entry point for a complete conversation turn:

    user_text
        → ObservationEngine         (structured extraction)
        → ConversationState         (unified shared truth)
        → SafeguardLayer            (safety, pacing, adventure)
        → KnownVsNovel              (novelty check)
        → Director                  (weighted decision)
        → ResponseComposer          (prompt construction)
        → [LLM generates response]  (external call)
        → AntiParrotingMonitor      (quality check)
        → ConversationState         (write result)
        → MeaningMaker              (end of session)
        → CompanionTurn             (full record)

Two modes:
    AUTONOMOUS  — calls the Anthropic API, returns a real response
    GUIDED      — returns a ComposedPrompt so your own LLM call
                  (GPT, Gemini, local model) drives the generation

This is production architecture.
No placeholders. No stubs.
Every module is real and wired.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# ── Core modules ──────────────────────────────
from observation_engine import ObservationEngine, create_observation_engine
from conversation_state import ConversationState, create_conversation_state
from safeguards import SafeguardLayer, create_safeguard_layer, EmotionalState, DependencySignal
from known_vs_novel import KnownVsNovel, InsightCandidate, InsightStatus, create_novelty_tracker
from anti_parroting import (
    AntiParrotingMonitor, UserTurn, ResponseDraft,
    ContributionType, create_monitor,
)
from meaning_maker import MeaningMaker, GrowthSignal, MeaningCategory, NarrativePhase, create_meaning_maker
from director import Director, ContributionDecision, ContributionIntent, create_director
from response_composer import ResponseComposer, ComposedPrompt, create_response_composer
from companion_core import CompanionCore, CompanionTurn, SessionSummary


# ─────────────────────────────────────────────
# Runtime output types
# ─────────────────────────────────────────────

@dataclass
class RuntimeTurn:
    """
    The full record of one processed turn.
    Everything that happened, every decision that was made.
    """
    turn_index: int
    user_text: str
    response_text: str
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Decision chain
    emotional_state: str = ""
    dependency_signal: str = ""
    director_intent: str = ""
    contribution_type: str = ""
    director_confidence: float = 0.0
    director_rationale: list[str] = field(default_factory=list)

    # Quality signals
    parroting_risk: str = "none"
    response_approved: bool = True
    novelty_status: Optional[str] = None
    insight_suppressed: bool = False

    # Guidance (for debugging / logging)
    tone_guidance: list[str] = field(default_factory=list)
    content_guidance: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # State snapshot after this turn
    state_snapshot: dict = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"Turn {self.turn_index} | "
            f"State: {self.emotional_state} | "
            f"Intent: {self.director_intent} | "
            f"Risk: {self.parroting_risk} | "
            f"Approved: {self.response_approved}"
        )


@dataclass
class RuntimeSession:
    """What the session produced."""
    session_id: str
    user_id: str
    turn_count: int
    meaning_summary: dict
    growth_trajectory: str
    narrative_update: str
    state_export: dict
    warnings: list[str]
    turns: list[RuntimeTurn]


# ─────────────────────────────────────────────
# PubCastRuntime
# ─────────────────────────────────────────────

class PubCastRuntime:
    """
    The full wired companion system.

    Usage — autonomous mode (calls Anthropic API):
        runtime = create_runtime("user_id", autonomous=True)
        turn = runtime.process("I want to quit my job and build a game studio.")
        print(turn.response_text)

    Usage — guided mode (you call the LLM):
        runtime = create_runtime("user_id", autonomous=False)
        prompt = runtime.process_to_prompt("I want to quit my job...")
        response = your_llm(prompt.system_prompt, prompt.user_message)
        turn = runtime.record_response(prompt, response)
        print(turn.summary())
    """

    def __init__(
        self,
        user_id: str,
        session_id: str = "",
        autonomous: bool = False,
        auto_deep_observation: bool = False,
    ):
        self.user_id = user_id
        self.session_id = session_id or f"session_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        self.autonomous = autonomous

        # ── All modules ──────────────────────────
        self.observation = create_observation_engine(auto_deep=auto_deep_observation)
        self.state = create_conversation_state(user_id, self.session_id)
        self.safeguards = create_safeguard_layer()
        self.novelty = create_novelty_tracker(user_id)
        self.anti_parroting = create_monitor()
        self.meaning = create_meaning_maker(user_id)
        self.director = create_director()
        self.composer = create_response_composer()

        # ── Session tracking ─────────────────────
        self.turns: list[RuntimeTurn] = []
        self._pending_prompt: Optional[ComposedPrompt] = None
        self._pending_turn: Optional[object] = None  # ConversationState TurnRecord

    # ── Main pipeline ──────────────────────────

    def process(self, user_text: str, use_deep_observation: bool = False) -> RuntimeTurn:
        """
        Autonomous mode: process a user message end to end.
        Calls the Anthropic API to generate the response.
        Returns a complete RuntimeTurn.

        Raises RuntimeError if autonomous=False — use process_to_prompt() instead.
        """
        if not self.autonomous:
            raise RuntimeError(
                "Runtime is in guided mode. "
                "Use process_to_prompt() then record_response()."
            )

        prompt = self.process_to_prompt(user_text, use_deep_observation)
        response_text = self._call_llm(prompt)
        return self.record_response(prompt, response_text)

    def process_to_prompt(
        self,
        user_text: str,
        use_deep_observation: bool = False,
    ) -> ComposedPrompt:
        """
        Run the full pipeline up to LLM call.
        Returns a ComposedPrompt ready to pass to any LLM.

        Call record_response() after you get the LLM's output.
        """
        # ── 1. Observation ───────────────────────
        bundle = self.observation.observe(user_text, use_llm=use_deep_observation)

        # ── 2. Open turn in state ────────────────
        turn_record = self.state.begin_turn(user_text)
        self.state.apply_observation(turn_record, bundle)

        # ── 3. Safeguards ────────────────────────
        safeguard_report = self.safeguards.analyze_incoming(user_text)
        self.state.apply_safeguards(
            turn_record,
            emotional_state=safeguard_report.emotional_state,
            dependency_signal=safeguard_report.dependency_signal,
            adventure_allowed=safeguard_report.adventure_allowed,
            blocked_patterns=safeguard_report.blocked_patterns,
        )

        # ── 4. Novelty check ─────────────────────
        self.novelty.ingest_user_turn(user_text)

        # Check if we'd want to surface an insight
        novelty_status = None
        insight_suppressed = False
        if bundle.dominant_emotion or bundle.dominant_goal:
            candidate_insight = InsightCandidate(
                content=f"{bundle.dominant_goal or bundle.dominant_emotion or bundle.primary_topic}"
            )
            novelty_report = self.novelty.check_insight(candidate_insight)
            novelty_status = novelty_report.status.value
            if not novelty_report.should_share:
                insight_suppressed = True

        # Update state knowledge profile
        self.state.knowledge.update(
            patterns=self.novelty.known_patterns,
            suppressed=1 if insight_suppressed else 0,
        )

        # ── 5. Director ──────────────────────────
        director_context = self.state.director_context()
        decision = self.director.decide(
            context=director_context,
            novelty_status=novelty_status,
            insight_suppressed=insight_suppressed,
        )

        # ── 6. Compose prompt ────────────────────
        prompt = self.composer.compose(decision, self.state, user_text)

        # Store for record_response()
        self._pending_prompt = prompt
        self._pending_turn = turn_record
        self._pending_decision = decision
        self._pending_novelty = novelty_status
        self._pending_suppressed = insight_suppressed

        return prompt

    def record_response(
        self,
        prompt: ComposedPrompt,
        response_text: str,
    ) -> RuntimeTurn:
        """
        Record the LLM's response and close out the turn.
        Call this after you get the LLM's output.
        """
        turn_record = self._pending_turn
        decision = self._pending_decision
        novelty_status = self._pending_novelty
        insight_suppressed = self._pending_suppressed

        # ── 7. Agency check ──────────────────────
        cleaned_response, agency_warnings = self.safeguards.check_outgoing(response_text)

        # ── 8. Anti-parroting check ──────────────
        user_turn = UserTurn(text=turn_record.user_text)
        response_draft = ResponseDraft(
            text=cleaned_response,
            intended_contribution=decision.contribution_type,
        )
        parroting_report = self.anti_parroting.check(user_turn, response_draft)

        # ── 9. Write to state ────────────────────
        self.state.apply_contribution(
            turn_record,
            contribution_type=decision.contribution_type,
            response_text=cleaned_response,
            parroting_risk=parroting_report.risk.value,
            approved=parroting_report.approved,
            warnings=agency_warnings + parroting_report.violations,
        )
        self.state.close_turn(turn_record)

        # ── 10. Build RuntimeTurn ─────────────────
        runtime_turn = RuntimeTurn(
            turn_index=self.state.turn_count,
            user_text=turn_record.user_text,
            response_text=cleaned_response,
            emotional_state=turn_record.emotional_state.value,
            dependency_signal=turn_record.dependency_signal.value,
            director_intent=decision.intent.value,
            contribution_type=decision.contribution_type.value,
            director_confidence=decision.confidence,
            director_rationale=decision.rationale,
            parroting_risk=parroting_report.risk.value,
            response_approved=parroting_report.approved,
            novelty_status=novelty_status,
            insight_suppressed=insight_suppressed,
            tone_guidance=decision.tone_guidance,
            content_guidance=decision.content_guidance,
            avoid=decision.avoid,
            warnings=agency_warnings + parroting_report.violations,
            state_snapshot=self.state.snapshot(),
        )

        self.turns.append(runtime_turn)
        return runtime_turn

    # ── Meaning layer ─────────────────────────

    def add_meaning(self, category: MeaningCategory, content: str, confidence: float = 0.7):
        self.meaning.add_meaning(category, content, confidence)

    def add_narrative_moment(self, phase: NarrativePhase, description: str):
        self.meaning.add_narrative_moment(phase, description)

    def add_turning_point(self, description: str):
        self.meaning.add_turning_point(description)
        self.state.narrative.turning_points.append(description)

    def add_unresolved_thread(self, thread: str):
        self.state.add_unresolved_thread(thread)

    def resolve_thread(self, thread: str):
        self.state.resolve_thread(thread)

    def contrast_with_baseline(self, current_description: str) -> Optional[str]:
        return self.meaning.contrast_with_baseline(current_description)

    # ── Session lifecycle ──────────────────────

    def end_session(
        self,
        growth_signal: Optional[GrowthSignal] = None,
        growth_description: str = "",
    ) -> RuntimeSession:
        """
        Close the session. Extract meaning. Return full summary.
        """
        transcript = self.state.transcript()

        meaning_result = self.meaning.ingest_session(
            session_transcript=transcript,
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

        return RuntimeSession(
            session_id=self.session_id,
            user_id=self.user_id,
            turn_count=self.state.turn_count,
            meaning_summary=meaning_result,
            growth_trajectory=growth.trajectory_summary(),
            narrative_update=narrative.describe(),
            state_export=self.state.export(),
            warnings=warnings,
            turns=self.turns,
        )

    def new_session(self, new_session_id: str = "") -> "PubCastRuntime":
        """
        Start a new session carrying forward accumulated memory.
        Meaning and known patterns persist. Safeguards reset.
        """
        next_session = PubCastRuntime(
            user_id=self.user_id,
            session_id=new_session_id,
            autonomous=self.autonomous,
        )
        # Carry forward
        next_session.meaning = self.meaning
        next_session.novelty = self.novelty
        next_session.state = ConversationState.from_export(self.state.export())
        next_session.state.session_id = next_session.session_id
        next_session.safeguards.new_session()
        return next_session

    # ── Diagnostics ───────────────────────────

    def status(self) -> dict:
        health = self.anti_parroting.session_health()
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "turns": self.state.turn_count,
            "state": self.state.snapshot(),
            "session_health": health,
            "meaning_units": len(self.meaning.meaning_units),
            "known_patterns": len(self.novelty.known_patterns),
            "mode": "autonomous" if self.autonomous else "guided",
        }

    # ── Internal LLM call ─────────────────────

    def _call_llm(self, prompt: ComposedPrompt) -> str:
        """
        Call the Anthropic API.
        Only runs in autonomous mode.
        """
        payload = json.dumps(prompt.to_api_payload()).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            return data["content"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise RuntimeError(f"Anthropic API error {e.code}: {body}")
        except Exception as e:
            raise RuntimeError(f"LLM call failed: {e}")


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def create_runtime(
    user_id: str,
    session_id: str = "",
    autonomous: bool = False,
    auto_deep_observation: bool = False,
) -> PubCastRuntime:
    """
    Create a PubCastRuntime.

    Args:
        user_id:               The user identifier.
        session_id:            Optional — auto-generated if not provided.
        autonomous:            If True, calls Anthropic API automatically.
                               If False, use process_to_prompt() + record_response().
        auto_deep_observation: If True, escalates to LLM observation when confidence is LOW.
    """
    return PubCastRuntime(
        user_id=user_id,
        session_id=session_id,
        autonomous=autonomous,
        auto_deep_observation=auto_deep_observation,
    )


# ─────────────────────────────────────────────
# Demo — guided mode (no API key needed)
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 65)
    print("PUBCAST RUNTIME — GUIDED MODE DEMO")
    print("=" * 65)

    runtime = create_runtime("user_josie", autonomous=False)

    # Simulate a real conversation
    exchanges = [
        (
            "Everything is falling apart. My launch failed, nobody showed up, I feel like an idiot.",
            "That's a rough place to land. What felt worst about it — the numbers, or the silence?",
        ),
        (
            "I guess the silence. I thought people cared. Apparently not.",
            "Is this the first time you put something out and heard nothing back?",
        ),
        (
            "No, it happens every time. I know I have this pattern of overestimating interest.",
            "You already named it. So the question isn't whether the pattern exists — it's what's different this time.",
        ),
        (
            "What do you think I should do? I want to try again but smaller.",
            "Okay. What would 'smaller' actually look like? What's the first thing you'd cut?",
        ),
        (
            "I did it! I shipped the small version and got 50 signups. First day.",
            "Fifty on day one of something built to actually ship. That's different from before.",
        ),
    ]

    print("\n--- PROCESSING TURNS ---\n")

    for user_text, simulated_response in exchanges:
        # Step 1: get the prompt
        prompt = runtime.process_to_prompt(user_text)

        # Step 2: in real use, your LLM generates a response from prompt
        # Here we use the simulated response to test the pipeline
        turn = runtime.record_response(prompt, simulated_response)

        print(f"User:     {user_text[:70]}")
        print(f"Response: {simulated_response[:70]}")
        print(f"  → {turn.summary()}")
        if turn.warnings:
            print(f"  ⚠ Warnings: {turn.warnings}")
        if turn.insight_suppressed:
            print(f"  ○ Insight suppressed (novelty check)")
        print()

    # Meaning annotations
    from meaning_maker import MeaningCategory, NarrativePhase, GrowthSignal
    runtime.add_meaning(MeaningCategory.LOST, "Belief that audience shows up without promotion")
    runtime.add_meaning(MeaningCategory.LEARNED, "Smaller scope ships more reliably")
    runtime.add_narrative_moment(NarrativePhase.BEFORE, "Overestimating interest, launching too big")
    runtime.add_narrative_moment(NarrativePhase.AFTER, "Shipped small, got real signal")
    runtime.add_turning_point("Acknowledged the overestimation pattern and chose to iterate")

    print("--- SESSION SUMMARY ---\n")
    summary = runtime.end_session(
        growth_signal=GrowthSignal.BREAKTHROUGH,
        growth_description="shipped something real after acknowledging the pattern"
    )
    print(f"Turns:     {summary.turn_count}")
    print(f"Growth:    {summary.growth_trajectory}")
    print(f"Narrative: {summary.narrative_update}")
    if summary.warnings:
        print(f"Warnings:  {summary.warnings}")

    print("\n--- FINAL STATUS ---\n")
    status = runtime.status()
    snapshot = status["state"]
    for k, v in snapshot.items():
        if v:
            print(f"  {k}: {v}")

    print("\n--- REFLECTION ---")
    print(runtime.meaning.generate_reflection())
