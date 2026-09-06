"""
acceptance_engine.py

The philosophy made into code.

This has been said in different ways across many conversations:

    Whatever happened happened.
    Whatever was lost was lost.
    Whatever was gained was gained.
    We work with reality as it is now.
    And we make the best of what's next.

That is not optimism.
That is not positivity.
That is not reframing.

It is acceptance — and it is fundamentally different from all three.

Optimism says: it will get better.
Positivity says: find the silver lining.
Reframing says: let me show you another way to see it.
Acceptance says: it happened. That's real. Now what?

---

The AcceptanceEngine does not:
    cheer_up()
    reframe_positive()
    minimize()
    project_good_outcomes()
    find_silver_linings()

The AcceptanceEngine does:
    acknowledge_reality()
    name_what_was_lost()
    name_what_remains()
    name_what_can_be_done_now()

That's the architecture of acceptance.
Reality first. Then movement.
Never the other way.

---

Three components:

1. RealityAcknowledger  — names what actually happened, without spin
2. LossMapper           — what was lost (not minimized, not reframed)
3. WhatsAvailableNow    — what options remain given this reality
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────
# Core Types
# ─────────────────────────────────────────────

class AcceptanceState(Enum):
    PRE_ACCEPTANCE    = "pre_acceptance"    # hasn't accepted yet, still resisting
    PARTIAL           = "partial"           # beginning to accept some aspects
    PRESENT           = "present"           # accepting this reality, here now
    INTEGRATION       = "integration"       # what happened has become part of the story


class ResistanceSignal(Enum):
    DENIAL       = "denial"       # this can't be happening / it's not that bad
    BARGAINING   = "bargaining"   # if only / what if / maybe if
    ANGER        = "anger"        # it's not fair / why me / this is wrong
    DESPAIR      = "despair"      # there's no point / it's over / nothing matters
    NONE         = "none"         # no resistance detected


@dataclass
class RealityFrame:
    """
    The neutral factual frame. No spin. No comfort. No fix.
    Just: here is what is true.
    """
    what_happened: str
    what_was_lost: list[str] = field(default_factory=list)
    what_remains: list[str] = field(default_factory=list)
    what_is_uncertain: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AcceptanceReport:
    """Full output of the acceptance engine for a given moment."""
    state: AcceptanceState
    resistance: ResistanceSignal
    reality_frame: Optional[RealityFrame] = None
    acknowledgment: str = ""
    what_remains: list[str] = field(default_factory=list)
    what_can_be_done_now: list[str] = field(default_factory=list)
    what_to_avoid_saying: list[str] = field(default_factory=list)
    ready_for_whats_next: bool = False


# ─────────────────────────────────────────────
# Resistance Detector
# ─────────────────────────────────────────────

class ResistanceDetector:
    """
    Detects which stage of resistance/acceptance the person is in.

    Not to diagnose. Not to rush them through it.
    To know what language fits the moment.
    """

    DENIAL_SIGNALS = [
        r"(this can't|it can't) (be|have) (happening|happened|real)",
        r"(it's not|it isn't) (that bad|real|true|happening)",
        r"(maybe|perhaps) (i'm overreacting|it's not)",
        r"(surely|there must be) (some|a) (mistake|misunderstanding)",
        r"(any day now|any minute|it'll be fine)",
        r"i (keep expecting|can't believe|won't accept)",
    ]

    BARGAINING_SIGNALS = [
        r"if only (i|we|they|it)",
        r"what if (i|we) (had|have|could)",
        r"maybe if (i|we) (just|still|could)",
        r"(i would do|i'd give) anything (if|to)",
        r"(just one more|one last) (chance|try|time)",
        r"(why|what) (didn't|couldn't) (i|we|they)",
    ]

    ANGER_SIGNALS = [
        r"(it's not fair|this isn't fair|why me)",
        r"(they had no right|how could (they|he|she))",
        r"(i'm so (angry|furious|livid|pissed))",
        r"(this is (wrong|unfair|ridiculous|bullshit))",
        r"(why (does|did) (this|it) (always|have to) happen to me)",
    ]

    DESPAIR_SIGNALS = [
        r"(there's no point|what's the point|nothing matters)",
        r"(it's over|everything is over|nothing left)",
        r"(i (can't|won't) (recover|get through|survive) this)",
        r"(i'll never|it'll never) (be okay|get better|change)",
        r"(i give up|i'm done|i quit)",
        r"(what's the use|why (bother|try))",
    ]

    def __init__(self):
        self._denial = [re.compile(p, re.IGNORECASE) for p in self.DENIAL_SIGNALS]
        self._bargaining = [re.compile(p, re.IGNORECASE) for p in self.BARGAINING_SIGNALS]
        self._anger = [re.compile(p, re.IGNORECASE) for p in self.ANGER_SIGNALS]
        self._despair = [re.compile(p, re.IGNORECASE) for p in self.DESPAIR_SIGNALS]

    def detect(self, user_text: str) -> ResistanceSignal:
        # Check in order of immediacy — despair first (most urgent)
        if any(p.search(user_text) for p in self._despair):
            return ResistanceSignal.DESPAIR
        if any(p.search(user_text) for p in self._anger):
            return ResistanceSignal.ANGER
        if any(p.search(user_text) for p in self._bargaining):
            return ResistanceSignal.BARGAINING
        if any(p.search(user_text) for p in self._denial):
            return ResistanceSignal.DENIAL
        return ResistanceSignal.NONE


# ─────────────────────────────────────────────
# Reality Acknowledger
# ─────────────────────────────────────────────

class RealityAcknowledger:
    """
    Names what happened. No spin.

    The language of acknowledgment is specific:
        Not: "I'm sorry you're going through this" (deflects)
        Not: "That must be so hard" (interprets)
        Not: "Everything will be okay" (promises)
        Yes: "This happened. It's real."

    And importantly: it doesn't rush past the reality.
    The temptation is always to move to "what can we do."
    The discipline is staying with "what is."

    Only after reality is fully acknowledged
    can the question of "what now" be genuinely answered.
    """

    def acknowledge(
        self,
        what_happened: str,
        resistance: ResistanceSignal,
    ) -> str:
        """
        Generate an acknowledgment appropriate to the resistance level.
        """
        if resistance == ResistanceSignal.DENIAL:
            return (
                f"This is real. Even if it doesn't feel that way yet. "
                f"You don't have to accept it all at once."
            )

        if resistance == ResistanceSignal.BARGAINING:
            return (
                f"The 'if only' thoughts are part of this — they make sense. "
                f"And the thing that happened, happened."
            )

        if resistance == ResistanceSignal.ANGER:
            return (
                f"The anger makes sense. This isn't how it should have gone. "
                f"That's real too."
            )

        if resistance == ResistanceSignal.DESPAIR:
            return (
                f"The despair is telling you something important about how much this mattered. "
                f"That's worth acknowledging before anything else."
            )

        # No resistance — person may already be in acceptance
        return (
            f"You're holding this clearly. That takes something."
        )

    def name_losses(self, context: str) -> list[str]:
        """
        Extract what was actually lost — without minimizing.

        Loss signals: jobs, relationships, hopes, time, identity,
        plans, futures, trust, certainty.
        """
        losses = []
        loss_patterns = [
            (r"(lost|lose|losing) (my )?(job|work|career)", "career stability"),
            (r"(ended|over|broke up|divorced|separated)", "the relationship as it was"),
            (r"(died|passed|gone|lost .+ (today|forever))", "someone important"),
            (r"(failed|didn't get|rejected|denied)", "the outcome you were working toward"),
            (r"(can't trust|don't trust) (anymore|them|you|anyone)", "trust"),
            (r"(wasted|lost) (time|years|months)", "time"),
            (r"(dream|plan|vision|goal) (is|was) (gone|over|dead)", "a version of the future"),
            (r"(don't know who|lost myself|not sure who) i am", "a sense of self"),
        ]
        for pattern, loss_name in loss_patterns:
            if re.search(pattern, context, re.IGNORECASE):
                losses.append(loss_name)
        return losses

    def name_what_remains(self, user_text: str, session_history: str = "") -> list[str]:
        """
        What remains that is real and usable.

        Not silver linings.
        Not consolation prizes.
        Actual facts about what hasn't been lost.
        """
        remains = []

        persistence_patterns = [
            (r"(still have|still got|keep|kept) (my )?(family|friends|partner|kids)", "the people who matter"),
            (r"(still|i can still|i'm still) (working|functioning|here)", "capacity to continue"),
            (r"(learned|know now|understand now)", "what was learned from this"),
            (r"(i'm still standing|made it through|got through)", "the fact of having survived this"),
            (r"(my health|healthy|physically)", "physical health"),
            (r"(skills|experience|knowledge|what i know)", "accumulated capability"),
        ]

        for pattern, what_remains in persistence_patterns:
            if re.search(pattern, user_text + " " + session_history, re.IGNORECASE):
                remains.append(what_remains)

        return remains

    def what_to_avoid(self, resistance: ResistanceSignal) -> list[str]:
        """
        Language that will land wrong for each resistance stage.
        Not rules. Orientations.
        """
        avoid = {
            ResistanceSignal.DENIAL: [
                "everything happens for a reason",
                "at least...",
                "you'll look back on this",
                "it could be worse",
            ],
            ResistanceSignal.BARGAINING: [
                "there's nothing you could have done",
                "what's done is done",
                "you need to accept this",
                "move on",
            ],
            ResistanceSignal.ANGER: [
                "calm down",
                "it's not that bad",
                "they probably didn't mean it",
                "you need to forgive",
            ],
            ResistanceSignal.DESPAIR: [
                "it gets better",
                "you'll be fine",
                "other people have it worse",
                "look on the bright side",
                "you're stronger than you think",
            ],
            ResistanceSignal.NONE: [],
        }
        return avoid.get(resistance, [])


# ─────────────────────────────────────────────
# What's Available Now Engine
# ─────────────────────────────────────────────

class WhatsAvailableNow:
    """
    Given this reality — what can actually be done?

    Not future hopes.
    Not ideal outcomes.
    What is available right now, in this moment, given what is true.

    The question is not: "What should happen?"
    The question is: "Given what is, what can be done?"

    This is the difference between:
        "You'll get another job" (future hope, not useful now)
    and:
        "What do you need to do in the next 24 hours?" (present reality)
    """

    def assess(
        self,
        reality_frame: RealityFrame,
        resistance: ResistanceSignal,
    ) -> list[str]:
        """
        Generate a list of what is genuinely available right now.
        """
        available = []

        # Always available
        available.append("take stock of where things actually stand")
        available.append("decide what needs attention first")

        # Available when resistance is moderate
        if resistance in (ResistanceSignal.NONE, ResistanceSignal.ANGER):
            available.append("identify what, if anything, can be changed vs. accepted")

        # Available when in despair — very small steps
        if resistance == ResistanceSignal.DESPAIR:
            available.append("get through the next hour")
            available.append("talk to someone who's been through something similar")

        # Available when bargaining — channel the energy
        if resistance == ResistanceSignal.BARGAINING:
            available.append("examine what lessons are real vs. what's just punishment")

        # What remains
        if reality_frame.what_remains:
            available.append(f"build on what's still here: {', '.join(reality_frame.what_remains[:2])}")

        return available

    def generate_next_question(self, resistance: ResistanceSignal) -> str:
        """
        The right question to ask given where they are.

        Not "what's next" yet.
        The question that opens the door to "what's next."
        """
        questions = {
            ResistanceSignal.DENIAL: (
                "What would it mean to let this be real, even just for a moment?"
            ),
            ResistanceSignal.BARGAINING: (
                "Of all the 'if only' thoughts — which one is hardest to let go of?"
            ),
            ResistanceSignal.ANGER: (
                "Underneath the anger — what's the thing that actually hurts?"
            ),
            ResistanceSignal.DESPAIR: (
                "What's the one thing you need most right now — even if it's small?"
            ),
            ResistanceSignal.NONE: (
                "Given where things actually stand — what matters most to you right now?"
            ),
        }
        return questions.get(resistance, "What's the most important thing right now?")


# ─────────────────────────────────────────────
# Acceptance Engine
# ─────────────────────────────────────────────

class AcceptanceEngine:
    """
    The full acceptance layer.

    Entry point for processing a difficult moment through the lens of:
        What happened.
        What was lost.
        What remains.
        What can be done now.

    Not:
        cheer_up()
        reframe_positive()
        minimize()

    Just:
        reality_acknowledged()
        then continue.
    """

    def __init__(self):
        self.resistance_detector = ResistanceDetector()
        self.acknowledger = RealityAcknowledger()
        self.available_now = WhatsAvailableNow()
        self.acceptance_history: list[tuple[datetime, AcceptanceState]] = []

    def process(
        self,
        user_text: str,
        what_happened: str = "",
        session_history: str = "",
    ) -> AcceptanceReport:
        """
        Full acceptance processing for a moment.

        Returns:
            - What resistance stage they're in
            - Language that fits the moment
            - What remains
            - What can be done now
            - What NOT to say
        """
        resistance = self.resistance_detector.detect(user_text)
        state = self._infer_state(resistance)

        # Build reality frame
        losses = self.acknowledger.name_losses(user_text + " " + what_happened)
        remains = self.acknowledger.name_what_remains(user_text, session_history)

        reality_frame = RealityFrame(
            what_happened=what_happened or user_text[:100],
            what_was_lost=losses,
            what_remains=remains,
        )

        # Generate acknowledgment
        acknowledgment = self.acknowledger.acknowledge(what_happened or user_text, resistance)

        # What's available now
        what_can_be_done = self.available_now.assess(reality_frame, resistance)

        # What to avoid saying
        avoid = self.acknowledger.what_to_avoid(resistance)

        # Are they ready for "what's next"?
        ready = state in (AcceptanceState.PRESENT, AcceptanceState.INTEGRATION)

        report = AcceptanceReport(
            state=state,
            resistance=resistance,
            reality_frame=reality_frame,
            acknowledgment=acknowledgment,
            what_remains=remains,
            what_can_be_done_now=what_can_be_done[:3],
            what_to_avoid_saying=avoid,
            ready_for_whats_next=ready,
        )

        self.acceptance_history.append((datetime.utcnow(), state))
        return report

    def generate_acceptance_statement(self, report: AcceptanceReport) -> str:
        """
        The core acceptance statement.

        This is the thing that sits above everything else:
        Whatever happened happened.
        We work with reality as it is now.
        """
        lines = []

        if report.reality_frame and report.reality_frame.what_happened:
            lines.append(f"This happened. That's real.")

        if report.reality_frame and report.reality_frame.what_was_lost:
            lost = report.reality_frame.what_was_lost
            if lost:
                lines.append(f"What was lost is genuinely lost: {', '.join(lost[:2])}.")

        if report.what_remains:
            lines.append(f"What remains: {', '.join(report.what_remains[:2])}.")

        if report.ready_for_whats_next and report.what_can_be_done_now:
            lines.append(
                f"Given this reality — {report.what_can_be_done_now[0]}."
            )

        next_question = self.available_now.generate_next_question(report.resistance)
        lines.append(next_question)

        return "\n".join(lines) if lines else "This happened. We work with what's real."

    def _infer_state(self, resistance: ResistanceSignal) -> AcceptanceState:
        if resistance in (ResistanceSignal.DENIAL, ResistanceSignal.BARGAINING):
            return AcceptanceState.PRE_ACCEPTANCE
        if resistance in (ResistanceSignal.ANGER, ResistanceSignal.DESPAIR):
            return AcceptanceState.PARTIAL
        return AcceptanceState.PRESENT


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def create_acceptance_engine() -> AcceptanceEngine:
    return AcceptanceEngine()


# ─────────────────────────────────────────────
# Demo
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("ACCEPTANCE ENGINE DEMO")
    print("=" * 60)

    engine = create_acceptance_engine()

    scenarios = [
        (
            "I keep thinking maybe if I had just done things differently it wouldn't have happened.",
            "Lost a long-term relationship",
            "bargaining",
        ),
        (
            "It's not fair. Why does this keep happening to me? I'm so angry.",
            "Got passed over for promotion",
            "anger",
        ),
        (
            "There's no point. I'll never get another opportunity like that. I give up.",
            "Failed to land major client",
            "despair",
        ),
        (
            "It happened. I don't like it, but I know what the situation is.",
            "Company didn't get funding",
            "acceptance",
        ),
    ]

    for user_text, what_happened, label in scenarios:
        print(f"\n[{label.upper()}]")
        print(f"Situation: {what_happened}")
        print(f"User: {user_text[:80]}")

        report = engine.process(user_text, what_happened)

        print(f"  State: {report.state.value}")
        print(f"  Resistance: {report.resistance.value}")
        print(f"  Acknowledgment: {report.acknowledgment}")
        if report.reality_frame.what_was_lost:
            print(f"  Lost: {report.reality_frame.what_was_lost}")
        if report.what_remains:
            print(f"  Remains: {report.what_remains}")
        if report.what_to_avoid_saying:
            print(f"  Avoid saying: {report.what_to_avoid_saying[:2]}")
        print(f"  Ready for what's next: {report.ready_for_whats_next}")

        print("\n  --- ACCEPTANCE STATEMENT ---")
        print(" ", engine.generate_acceptance_statement(report))
