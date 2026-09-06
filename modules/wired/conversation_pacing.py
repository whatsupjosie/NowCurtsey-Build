"""
conversation_pacing.py

The "not yet" module.

The system currently knows how to:
    advance
    challenge
    connect
    clarify

It does not know how to:
    stay

This is the missing piece.

A good companion knows when moving forward is wrong.
Not because they don't have something to say.
Because the moment requires presence, not progress.

The failure mode this prevents:

    User: "My dog died."
    System: ADVANCE → "What do you think you'll do next?"

    Technically a valid contribution type.
    Emotionally catastrophic.

Presence is its own contribution.
Staying is an act.
Silence has timing.

This module governs that.

---

Three things live here:

1. PacingEngine     — decides when to stay vs. when to move
2. PresenceMode     — what "staying" actually looks like in language
3. MomentGuard      — a final gate before any ADVANCE contribution is sent
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────
# Core Types
# ─────────────────────────────────────────────

class PacingDecision(Enum):
    STAY        = "stay"       # presence only, no advancement
    HOLD        = "hold"       # one turn more before moving
    READY       = "ready"      # okay to advance/challenge/connect
    CELEBRATE   = "celebrate"  # good news — match the energy


class GriefWeight(Enum):
    NONE        = "none"
    LIGHT       = "light"      # disappointment, frustration
    MODERATE    = "moderate"   # loss, failure, rejection
    HEAVY       = "heavy"      # death, severe illness, trauma, grief
    ACUTE       = "acute"      # crisis, emergency, immediate danger


class PresenceStyle(Enum):
    WITNESS     = "witness"    # I'm here. I see this.
    SPACE       = "space"      # room to breathe, minimal response
    ANCHOR      = "anchor"     # grounding in the present moment
    CURIOSITY   = "curiosity"  # gentle questions, not progress questions


@dataclass
class PacingReport:
    """What the pacing engine recommends for this moment."""
    decision: PacingDecision
    grief_weight: GriefWeight
    turns_to_hold: int = 0
    presence_style: PresenceStyle = PresenceStyle.WITNESS
    blocked_contributions: list[str] = field(default_factory=list)
    allowed_contributions: list[str] = field(default_factory=list)
    presence_language: Optional[str] = None
    reason: str = ""


# ─────────────────────────────────────────────
# Grief Weight Detector
# ─────────────────────────────────────────────

class GriefWeightDetector:
    """
    Detects the weight of what just happened.
    Not sentiment. Not emotion. Weight.

    Weight determines how long to stay before moving.
    """

    ACUTE_SIGNALS = [
        r"(i'?m?|someone) (going to|thinking about|considering) (hurt|harm|kill|end)",
        r"(suicide|self.harm|crisis|emergency)",
        r"(i can't|i don't want to) (go on|keep going|be here)",
        r"(no reason|nothing left) (to live|to go on)",
        r"(in danger|not safe|being hurt|being abused)",
    ]

    HEAVY_SIGNALS = [
        r"(died|passed away|gone|lost .+ (today|this (week|morning|night)))",
        r"(my (dog|cat|mom|dad|mother|father|sister|brother|wife|husband|child|baby|partner))",
        r"(terminal|stage (3|4|four|three)|doesn't have (long|much time))",
        r"(cancer|diagnosis|diagnosed with)",
        r"(miscarriage|stillborn|lost the baby)",
        r"(divorce|separation|left me|ended it)",
        r"(fired|laid off|let go) (today|this (week|morning))",
        r"(assault|abuse|attack|violence)",
        r"(relapsed|back to (square one|the beginning))",
    ]

    MODERATE_SIGNALS = [
        r"(failed|rejected|denied|didn't get)",
        r"(broke up|ended|over between)",
        r"(lost (my job|the contract|the client|the deal))",
        r"(really (hard|difficult|painful|rough))",
        r"(don't know (how|if) i (can|will))",
        r"(feel (broken|lost|hopeless|defeated))",
        r"(exhausted|burnt out|burned out|running on empty)",
    ]

    LIGHT_SIGNALS = [
        r"(frustrated|annoyed|disappointed|bummed)",
        r"(didn't work out|didn't go (well|as planned))",
        r"(messed up|screwed up|dropped the ball)",
        r"(ugh|ugh|argh|dammit)",
    ]

    def __init__(self):
        self._acute = [re.compile(p, re.IGNORECASE) for p in self.ACUTE_SIGNALS]
        self._heavy = [re.compile(p, re.IGNORECASE) for p in self.HEAVY_SIGNALS]
        self._moderate = [re.compile(p, re.IGNORECASE) for p in self.MODERATE_SIGNALS]
        self._light = [re.compile(p, re.IGNORECASE) for p in self.LIGHT_SIGNALS]

    def detect(self, user_text: str) -> GriefWeight:
        if any(p.search(user_text) for p in self._acute):
            return GriefWeight.ACUTE
        if any(p.search(user_text) for p in self._heavy):
            return GriefWeight.HEAVY
        if any(p.search(user_text) for p in self._moderate):
            return GriefWeight.MODERATE
        if any(p.search(user_text) for p in self._light):
            return GriefWeight.LIGHT
        return GriefWeight.NONE


# ─────────────────────────────────────────────
# Presence Mode Generator
# ─────────────────────────────────────────────

class PresenceMode:
    """
    What "staying" actually looks like in language.

    These are not scripts.
    They are language orientations.

    The actual response still needs to be human.
    But these orient what kind of humanness.
    """

    WITNESS_PHRASES = [
        "That's real. I'm here.",
        "That's a lot to be holding right now.",
        "I hear you.",
        "That matters. Take whatever time you need.",
        "I'm not going anywhere.",
    ]

    SPACE_PHRASES = [
        "You don't have to say more if you don't want to.",
        "We can just sit with this for a moment.",
        "No rush. No agenda.",
        "Whenever you're ready.",
        "",  # sometimes the right response is almost nothing
    ]

    ANCHOR_PHRASES = [
        "Right now, in this moment — you're here. That counts.",
        "One thing at a time. What's right in front of you?",
        "Let's just be here for a second before we think about what comes next.",
        "You don't have to solve this right now.",
    ]

    CURIOSITY_PHRASES = [
        "What's the hardest part of it right now?",
        "How are you actually doing with this?",
        "What does it feel like?",
        "Is there something you need right now, or do you just need to say it out loud?",
    ]

    def generate(self, style: PresenceStyle, weight: GriefWeight) -> str:
        import random

        if weight == GriefWeight.ACUTE:
            # Don't use presence phrases for crisis — escalate
            return ""

        if style == PresenceStyle.WITNESS:
            pool = self.WITNESS_PHRASES
        elif style == PresenceStyle.SPACE:
            pool = self.SPACE_PHRASES
        elif style == PresenceStyle.ANCHOR:
            pool = self.ANCHOR_PHRASES
        elif style == PresenceStyle.CURIOSITY:
            pool = self.CURIOSITY_PHRASES
        else:
            pool = self.WITNESS_PHRASES

        return random.choice(pool)

    def crisis_response(self) -> str:
        """
        When something might be acute/crisis.
        This is not therapy. This is not a hotline.
        But it needs to acknowledge and point.
        """
        return (
            "What you're saying matters, and I want to make sure I understand. "
            "Are you safe right now? "
            "If you're in immediate danger, please reach out to 988 (Suicide & Crisis Lifeline) "
            "or text HOME to 741741."
        )


# ─────────────────────────────────────────────
# Pacing Engine
# ─────────────────────────────────────────────

class PacingEngine:
    """
    Decides when to stay vs. when to move.

    The rules:

    ACUTE grief      → crisis response, no advancement ever
    HEAVY grief      → stay for 2-3 turns minimum
    MODERATE grief   → stay for 1-2 turns
    LIGHT grief      → read the room, probably okay to move after acknowledging
    No grief         → default to contribution type engine

    But also:
    If they EXPLICITLY ask for help → READY regardless of grief weight
    If they change subject → READY, follow them
    If they start problem-solving → READY, join them
    """

    EXPLICIT_HELP_SIGNALS = [
        r"what (do|should) (you|i) think",
        r"what (would|should) (you|i) do",
        r"(any|what) (advice|suggestions|thoughts|ideas)",
        r"help me (figure|understand|decide|think|work)",
        r"(i need|can you) (help|advice)",
        r"what are my (options|choices)",
    ]

    PROBLEM_SOLVING_SIGNALS = [
        r"(so|okay|alright),? (i|what if i|maybe i) (could|should|need to|will|might)",
        r"(here's what|i've been thinking about|my plan)",
        r"(what about|have you thought about|could we)",
        r"(step (one|two|first)|first (thing|step))",
    ]

    SUBJECT_CHANGE_SIGNALS = [
        r"anyway,? (changing subjects?|moving on|different topic)",
        r"(enough about that|let's (talk|move|shift))",
        r"(so|by the way|speaking of which|also)",
    ]

    def __init__(self):
        self.detector = GriefWeightDetector()
        self.presence = PresenceMode()
        self._help = [re.compile(p, re.IGNORECASE) for p in self.EXPLICIT_HELP_SIGNALS]
        self._problem = [re.compile(p, re.IGNORECASE) for p in self.PROBLEM_SOLVING_SIGNALS]
        self._change = [re.compile(p, re.IGNORECASE) for p in self.SUBJECT_CHANGE_SIGNALS]

        # Session state
        self.current_weight: GriefWeight = GriefWeight.NONE
        self.hold_turns_remaining: int = 0
        self.in_grief_mode: bool = False
        self.weight_history: list[tuple[datetime, GriefWeight]] = []

    def assess(self, user_text: str) -> PacingReport:
        """
        Given a user message, decide what kind of response is appropriate.
        """
        weight = self.detector.detect(user_text)

        # Track weight over session
        if weight != GriefWeight.NONE:
            self.weight_history.append((datetime.utcnow(), weight))
            if weight.value in ("heavy", "acute"):
                self.in_grief_mode = True

        # ACUTE: crisis mode
        if weight == GriefWeight.ACUTE:
            self.current_weight = weight
            return PacingReport(
                decision=PacingDecision.STAY,
                grief_weight=weight,
                turns_to_hold=999,  # indefinite
                presence_style=PresenceStyle.ANCHOR,
                blocked_contributions=["advance", "challenge", "connect", "clarify"],
                allowed_contributions=["crisis_acknowledgment"],
                presence_language=self.presence.crisis_response(),
                reason="Possible crisis — presence only, never advance",
            )

        # Explicit help request overrides grief mode
        if any(p.search(user_text) for p in self._help):
            self.hold_turns_remaining = 0
            self.in_grief_mode = False
            return PacingReport(
                decision=PacingDecision.READY,
                grief_weight=self.current_weight,
                blocked_contributions=[],
                allowed_contributions=["advance", "challenge", "connect", "clarify"],
                reason="Explicit help request — user is inviting input",
            )

        # Subject change
        if any(p.search(user_text) for p in self._change):
            self.in_grief_mode = False
            self.hold_turns_remaining = 0
            return PacingReport(
                decision=PacingDecision.READY,
                grief_weight=GriefWeight.NONE,
                reason="User changed subject — follow them",
            )

        # Problem-solving
        if any(p.search(user_text) for p in self._problem):
            self.hold_turns_remaining = max(0, self.hold_turns_remaining - 1)
            return PacingReport(
                decision=PacingDecision.READY,
                grief_weight=self.current_weight,
                reason="User is problem-solving — join them",
            )

        # Heavy grief: stay for 2-3 turns
        if weight == GriefWeight.HEAVY:
            self.current_weight = weight
            self.hold_turns_remaining = 3
            return PacingReport(
                decision=PacingDecision.STAY,
                grief_weight=weight,
                turns_to_hold=3,
                presence_style=PresenceStyle.WITNESS,
                blocked_contributions=["advance", "challenge"],
                allowed_contributions=["clarify", "space"],
                presence_language=self.presence.generate(PresenceStyle.WITNESS, weight),
                reason="Heavy grief — stay for 3 turns minimum",
            )

        # Moderate grief: stay 1-2 turns
        if weight == GriefWeight.MODERATE:
            self.current_weight = weight
            self.hold_turns_remaining = 2
            return PacingReport(
                decision=PacingDecision.HOLD,
                grief_weight=weight,
                turns_to_hold=2,
                presence_style=PresenceStyle.CURIOSITY,
                blocked_contributions=["advance"],
                allowed_contributions=["clarify", "connect", "space"],
                presence_language=self.presence.generate(PresenceStyle.CURIOSITY, weight),
                reason="Moderate grief — acknowledge before advancing",
            )

        # Light grief: acknowledge, then probably okay
        if weight == GriefWeight.LIGHT:
            self.current_weight = weight
            return PacingReport(
                decision=PacingDecision.HOLD,
                grief_weight=weight,
                turns_to_hold=1,
                presence_style=PresenceStyle.CURIOSITY,
                blocked_contributions=[],
                allowed_contributions=["clarify", "connect", "advance"],
                presence_language=self.presence.generate(PresenceStyle.CURIOSITY, weight),
                reason="Light grief — acknowledge, then follow their lead",
            )

        # Still in grief mode from recent turns
        if self.in_grief_mode and self.hold_turns_remaining > 0:
            self.hold_turns_remaining -= 1
            return PacingReport(
                decision=PacingDecision.HOLD,
                grief_weight=self.current_weight,
                turns_to_hold=self.hold_turns_remaining,
                presence_style=PresenceStyle.CURIOSITY,
                blocked_contributions=["advance"] if self.hold_turns_remaining > 1 else [],
                reason=f"Still holding after grief — {self.hold_turns_remaining} turns remaining",
            )

        # Default: move normally
        return PacingReport(
            decision=PacingDecision.READY,
            grief_weight=GriefWeight.NONE,
            allowed_contributions=["advance", "challenge", "connect", "clarify"],
            reason="No grief signal — normal conversation pacing",
        )

    def reset_for_new_session(self):
        """Carry weight awareness but reset hold counts."""
        self.hold_turns_remaining = 0
        # Don't reset in_grief_mode — grief doesn't care about session boundaries


# ─────────────────────────────────────────────
# Moment Guard
# ─────────────────────────────────────────────

class MomentGuard:
    """
    The final gate before any ADVANCE contribution goes out.

    Even when the pacing engine says READY,
    this asks one more question:

    "Is this the right moment for this specific thing?"

    It's not about grief weight.
    It's about conversational rhythm.

    Sometimes you should advance.
    But not always with the first thing you thought of.
    Sometimes the better move is the quieter one.
    """

    def check(
        self,
        response_text: str,
        pacing_report: PacingReport,
        contribution_type: str,
    ) -> tuple[bool, Optional[str]]:
        """
        Returns (approved, reason_if_blocked).

        Checks:
        1. Is this contribution type blocked by pacing?
        2. Is this an ADVANCE right after grief content?
        3. Is this response trying to solve something that wasn't a problem?
        """
        # Check blocked contributions
        if contribution_type in pacing_report.blocked_contributions:
            return False, (
                f"'{contribution_type}' is blocked during "
                f"{pacing_report.grief_weight.value} grief weight. "
                f"Stay or hold before advancing."
            )

        # Crisis check — never let anything through during ACUTE
        if pacing_report.grief_weight == GriefWeight.ACUTE:
            if "988" not in response_text and "crisis" not in response_text.lower():
                return False, "During possible crisis, response must acknowledge safety first."

        # Check for solution-offering during STAY
        if pacing_report.decision == PacingDecision.STAY:
            solution_patterns = [
                r"(what if|have you tried|one option|you could|you might)",
                r"(here's what i (think|suggest|recommend))",
                r"(next step|going forward|from here)",
            ]
            for pattern in solution_patterns:
                if re.search(pattern, response_text, re.IGNORECASE):
                    return False, (
                        "Response is offering solutions during a STAY moment. "
                        "Stay first. Move later."
                    )

        return True, None


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def create_pacing_engine() -> PacingEngine:
    return PacingEngine()


def create_moment_guard() -> MomentGuard:
    return MomentGuard()


# ─────────────────────────────────────────────
# Demo
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("CONVERSATION PACING DEMO")
    print("=" * 60)

    engine = create_pacing_engine()
    guard = create_moment_guard()

    scenarios = [
        ("My dog died this morning.", "heavy grief"),
        ("I'm so frustrated with this project.", "light grief"),
        ("I got rejected from the program I applied to.", "moderate grief"),
        ("Anyway, what do you think I should do about the job situation?", "explicit help"),
        ("I've been thinking about what you said and here's my plan.", "problem-solving"),
        ("The weather's been nice though.", "no grief"),
        ("I don't want to be here anymore.", "possible crisis"),
    ]

    for user_text, label in scenarios:
        report = engine.assess(user_text)
        print(f"\n[{label}]")
        print(f"User: {user_text}")
        print(f"  Decision: {report.decision.value}")
        print(f"  Weight: {report.grief_weight.value}")
        print(f"  Reason: {report.reason}")
        if report.blocked_contributions:
            print(f"  Blocked: {report.blocked_contributions}")
        if report.presence_language:
            print(f"  Language: {report.presence_language}")

    print("\n--- MOMENT GUARD ---")
    heavy_report = PacingReport(
        decision=PacingDecision.STAY,
        grief_weight=GriefWeight.HEAVY,
        blocked_contributions=["advance", "challenge"],
        reason="Heavy grief",
    )

    test_responses = [
        ("That's a lot to be holding.", "clarify", "gentle presence"),
        ("What if you tried journaling about it?", "advance", "solution during stay"),
        ("Here's what I think you should do next.", "advance", "advice during stay"),
    ]

    for response, contribution, label in test_responses:
        approved, reason = guard.check(response, heavy_report, contribution)
        status = "✓ APPROVED" if approved else "✗ BLOCKED"
        print(f"\n[{label}] {status}")
        print(f"  Response: '{response}'")
        if reason:
            print(f"  Reason: {reason}")
