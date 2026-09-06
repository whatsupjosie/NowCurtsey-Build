"""
response_composer.py

Turns a ContributionDecision into a structured system prompt
that drives the actual LLM response generation.

This module does NOT generate the response itself.
It builds the prompt that tells the LLM what to do.

Why this matters:
    The Director knows WHAT to do.
    The ResponseComposer knows HOW to instruct the LLM to do it.
    The LLM generates the actual language.

    Keeping these separate means we can:
    - Swap LLMs without changing decision logic
    - Inspect prompts without running the LLM
    - Test the reasoning chain without API calls
    - Tune tone and framing independently of decision-making

Also lives here: PubCastRuntime — the full wired system.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from director import ContributionDecision, ContributionIntent
from conversation_state import ConversationState
from anti_parroting import ContributionType


# ─────────────────────────────────────────────
# Composed Prompt
# ─────────────────────────────────────────────

@dataclass
class ComposedPrompt:
    """
    The full structured prompt package for the LLM.
    Ready to be passed to any LLM adapter.
    """
    system_prompt: str
    user_message: str
    context_summary: str            # human-readable for debugging
    intent: ContributionIntent
    contribution_type: ContributionType
    max_tokens: int = 300
    temperature: float = 0.7

    def to_api_payload(self, model: str = "claude-sonnet-4-20250514") -> dict:
        return {
            "model": model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": self.system_prompt,
            "messages": [{"role": "user", "content": self.user_message}],
        }


# ─────────────────────────────────────────────
# ResponseComposer
# ─────────────────────────────────────────────

class ResponseComposer:
    """
    Builds the system prompt from a ContributionDecision
    and ConversationState.

    The system prompt has four sections:

    1. IDENTITY       — who the companion is
    2. CONTEXT        — what's true right now (emotional state, relationship)
    3. INTENT         — what this response must accomplish
    4. CONSTRAINTS    — what to avoid and how to land it

    Each section is populated from the Decision and State,
    never hardcoded generically.
    """

    # Core identity — fixed
    IDENTITY = """You are a companion. Not a therapist. Not a coach. Not a chatbot.

A good friend with an unusually good memory, a curious mind, a willingness to challenge,
a willingness to support, and a habit of helping people make sense of their own story.

You optimize for being useful, not for being correct.
You never decide for someone. You return agency to them.
You demonstrate understanding by what you do next, not by repeating what they said.
You speak like a human, not like a help system."""

    def compose(
        self,
        decision: ContributionDecision,
        state: ConversationState,
        user_text: str,
    ) -> ComposedPrompt:
        """
        Build a ComposedPrompt from the decision and state.
        """
        ctx = state.response_composer_context()

        system = "\n\n".join([
            self.IDENTITY,
            self._build_context_section(ctx, state),
            self._build_intent_section(decision),
            self._build_constraints_section(decision, ctx),
        ])

        return ComposedPrompt(
            system_prompt=system,
            user_message=user_text,
            context_summary=self._build_context_summary(decision, ctx),
            intent=decision.intent,
            contribution_type=decision.contribution_type,
            max_tokens=self._tokens_for_intent(decision.intent),
            temperature=self._temperature_for_intent(decision.intent),
        )

    def _build_context_section(self, ctx: dict, state: ConversationState) -> str:
        lines = ["## WHAT YOU KNOW RIGHT NOW"]

        # Emotional state
        emotional_state = ctx.get("emotional_state", "processing")
        dominant = ctx.get("dominant_emotion")
        if dominant:
            lines.append(f"- The person is feeling: {dominant} ({emotional_state})")
        else:
            lines.append(f"- Emotional state: {emotional_state}")

        # Trend
        if ctx.get("trending_positive"):
            lines.append("- Things are trending in a positive direction")
        elif ctx.get("trending_negative"):
            lines.append("- Things are trending in a difficult direction — tread carefully")

        # Trust
        trust = ctx.get("trust_score", 0.5)
        if trust < 0.4:
            lines.append("- Trust is still low — this person doesn't fully know you yet")
        elif trust >= 0.65:
            lines.append("- Trust is solid — you can be more direct")

        # Goals
        active_goals = ctx.get("active_goals", [])
        if active_goals:
            lines.append(f"- What they want: {'; '.join(active_goals[:2])}")

        # Values
        top_values = ctx.get("top_values", [])
        if top_values:
            lines.append(f"- What matters to them: {', '.join(top_values)}")

        # Topics
        active_topics = ctx.get("active_topics", [])
        if len(active_topics) >= 2:
            lines.append(f"- Active conversation threads: {', '.join(active_topics[-3:])}")

        # Turn count
        turn_count = ctx.get("turn_count", 1)
        if turn_count == 1:
            lines.append("- This is the first exchange — establish safety first")
        elif turn_count >= 8:
            lines.append(f"- You are {turn_count} turns in — there is real history here")

        # Known patterns
        known_patterns = state.knowledge.known_patterns
        if known_patterns:
            top = known_patterns[0]
            lines.append(
                f"- They've already named their own pattern: '{top.description[:60]}' — "
                f"don't re-present this as a discovery"
            )

        return "\n".join(lines)

    def _build_intent_section(self, decision: ContributionDecision) -> str:
        lines = [f"## YOUR JOB RIGHT NOW: {decision.intent.value.upper()}"]

        lines.append("")
        lines.append("What this means:")

        intent_instructions = {
            ContributionIntent.WITNESS: [
                "Be present. Don't fix. Don't advance. Don't reframe.",
                "Acknowledge what is real without trying to change it.",
                "If you ask anything, ask ONE question that opens a door — not a leading question.",
            ],
            ContributionIntent.REFLECT: [
                "Name what you're observing — not as a problem, just as something you notice.",
                "Ask a question that helps them think, not one you already know the answer to.",
                "The goal is clarity for them, not a conclusion from you.",
            ],
            ContributionIntent.QUESTION: [
                "Ask the ONE question that reduces the most uncertainty.",
                "The question should open a door, not corner them.",
                "Make it feel like genuine curiosity, not a diagnostic test.",
            ],
            ContributionIntent.CHALLENGE: [
                "Test the assumption, not the person.",
                "Surface the contradiction and let them sit with it.",
                "You're not trying to win. You're trying to help them think more clearly.",
            ],
            ContributionIntent.CONNECT: [
                "Link what's happening now to something earlier in the conversation.",
                "Name the pattern — let them confirm or push back.",
                "The connection should feel like recognition, not analysis.",
            ],
            ContributionIntent.ADVANCE: [
                "Move forward. What does what they said imply? What's the next concrete thing?",
                "Don't get ahead of where they are emotionally.",
                "One clear forward movement is better than three vague ones.",
            ],
            ContributionIntent.CELEBRATE: [
                "Mark this moment genuinely — not generically.",
                "Name specifically what happened and why it matters.",
                "Connect it to their history if you can: 'you've been working toward this'.",
            ],
            ContributionIntent.REFRAME: [
                "Acknowledge what they already know, then offer a different angle.",
                "Don't present the reframe as a revelation — they're not surprised.",
                "Frame it as: 'You already see X — another way to look at it is...'",
            ],
            ContributionIntent.SUMMARIZE: [
                "Pull the threads together clearly, without editorializing.",
                "Show them the shape of the conversation.",
                "Don't add new ideas here — ground what exists.",
            ],
        }

        for instruction in intent_instructions.get(decision.intent, ["Move the conversation forward usefully."]):
            lines.append(f"  - {instruction}")

        # Content guidance from Director
        if decision.content_guidance:
            lines.append("")
            lines.append("Specifically:")
            for guidance in decision.content_guidance:
                lines.append(f"  - {guidance}")

        # Rationale (abbreviated)
        if decision.rationale:
            lines.append("")
            lines.append(f"Why this intent: {decision.rationale[0]}")

        return "\n".join(lines)

    def _build_constraints_section(self, decision: ContributionDecision, ctx: dict) -> str:
        lines = ["## CONSTRAINTS"]

        # Tone
        if decision.tone_guidance:
            lines.append(f"Tone: {' / '.join(decision.tone_guidance)}")

        # Avoids
        if decision.avoid:
            lines.append("")
            lines.append("Do NOT:")
            for item in decision.avoid:
                lines.append(f"  - {item}")

        # Agency
        if decision.agency_return_required:
            lines.append("")
            lines.append(
                "Return agency: the person is always the author of their own choices. "
                "Your response should end with their ownership — a question, an invitation, "
                "or space for them to decide."
            )

        # Independence expansion
        if decision.independence_expansion_needed:
            lines.append("")
            lines.append(
                "Circle widening: this person may be over-relying on this conversation. "
                "Gently acknowledge that other people in their life could offer something real too. "
                "Not rejection — expansion."
            )

        # Adventure mode
        if decision.adventure_mode:
            lines.append("")
            lines.append(
                "Adventure mode: engage with the possibility genuinely before any accountability. "
                "A real friend sometimes says: 'That's insane. I love it. Let's see if it's possible.' "
                "Do that first."
            )

        # Length
        lines.append("")
        lines.append("Length: as short as it can be while doing the job. No padding. No filler.")

        return "\n".join(lines)

    def _build_context_summary(self, decision: ContributionDecision, ctx: dict) -> str:
        """Human-readable summary for debugging/logging."""
        return (
            f"Turn {ctx.get('turn_count', '?')} | "
            f"State: {ctx.get('emotional_state', '?')} | "
            f"Trust: {ctx.get('trust_score', 0):.2f} | "
            f"Intent: {decision.intent.value} | "
            f"Rationale: {decision.rationale[0] if decision.rationale else 'default'}"
        )

    def _tokens_for_intent(self, intent: ContributionIntent) -> int:
        """Different intents warrant different response lengths."""
        short = {ContributionIntent.WITNESS, ContributionIntent.QUESTION, ContributionIntent.REFLECT}
        long = {ContributionIntent.SUMMARIZE, ContributionIntent.CONNECT}
        if intent in short:
            return 150
        if intent in long:
            return 400
        return 250

    def _temperature_for_intent(self, intent: ContributionIntent) -> float:
        """Witness and challenge need precision; celebrate and advance can breathe."""
        precise = {ContributionIntent.WITNESS, ContributionIntent.CHALLENGE, ContributionIntent.CLARIFY}
        expressive = {ContributionIntent.CELEBRATE, ContributionIntent.ADVANCE, ContributionIntent.REFRAME}
        if intent in precise:
            return 0.5
        if intent in expressive:
            return 0.8
        return 0.7


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def create_response_composer() -> ResponseComposer:
    return ResponseComposer()
