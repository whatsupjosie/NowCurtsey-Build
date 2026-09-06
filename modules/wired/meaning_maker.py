"""
meaning_maker.py

People don't experience life as facts. They experience life as story.

The MeaningMaker doesn't track what happened.
It tracks what it meant.

Questions it answers:
    - What was learned?
    - What was gained?
    - What was lost?
    - What endures?
    - Where was this person? Where are they now? Where do they think they're going?

This is the layer that makes the system feel like it *understands*
rather than just *processes*.

NarrativeContinuity lives here too — the thread that connects
who someone was to who they're becoming.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────
# Core Types
# ─────────────────────────────────────────────

class MeaningCategory(Enum):
    LEARNED    = "learned"    # insight or understanding gained
    GAINED     = "gained"     # something new: capability, relationship, clarity
    LOST       = "lost"       # something released: assumption, hope, relationship
    ENDURES    = "endures"    # what remains true regardless of outcome
    DIRECTION  = "direction"  # where they're heading next
    SHIFT      = "shift"      # a perspective that changed
    UNRESOLVED = "unresolved" # still open, still alive


class NarrativePhase(Enum):
    BEFORE    = "before"    # where they were
    DURING    = "during"    # what the experience was
    AFTER     = "after"     # where they are now
    DIRECTION = "direction" # where they think they're going


class GrowthSignal(Enum):
    REGRESSION   = "regression"   # going backward (temporarily normal)
    PLATEAU      = "plateau"       # holding steady
    INCREMENTAL  = "incremental"   # small forward movement
    BREAKTHROUGH = "breakthrough"  # meaningful shift
    INTEGRATION  = "integration"   # old struggle becomes new strength


@dataclass
class MeaningUnit:
    """A single unit of extracted meaning."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    category: MeaningCategory = MeaningCategory.LEARNED
    content: str = ""
    confidence: float = 0.5       # 0.0 to 1.0
    session_id: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source_text: str = ""         # the user utterance that generated this
    reinforced_count: int = 1     # how many times this has come up
    last_reinforced: Optional[datetime] = None

    def reinforce(self, new_source: str = ""):
        self.reinforced_count += 1
        self.last_reinforced = datetime.utcnow()
        self.confidence = min(1.0, self.confidence + 0.1)
        if new_source:
            self.source_text = new_source


@dataclass
class NarrativeArc:
    """
    The story spine.

    Not events. The meaning of those events over time.
    """
    user_id: str
    before: list[str] = field(default_factory=list)     # where they came from
    during: list[str] = field(default_factory=list)     # what the experience was
    after: list[str] = field(default_factory=list)      # where they are now
    direction: list[str] = field(default_factory=list)  # where they're going
    turning_points: list[str] = field(default_factory=list)  # moments that changed things
    current_chapter: str = ""

    def describe(self) -> str:
        parts = []
        if self.before:
            parts.append("Started from: " + "; ".join(self.before[-2:]))
        if self.after:
            parts.append("Has arrived at: " + "; ".join(self.after[-2:]))
        if self.direction:
            parts.append("Moving toward: " + "; ".join(self.direction[-1:]))
        if self.turning_points:
            parts.append("Turning point: " + self.turning_points[-1])
        return " / ".join(parts) if parts else "Narrative still forming."


@dataclass
class GrowthTrajectory:
    """
    Tracks not just what happened but who they're becoming.

    The most powerful thing the system can say:
    "Six months ago this would have destroyed you.
     Look how differently you're handling it now."
    """
    user_id: str
    signals: list[tuple[datetime, GrowthSignal, str]] = field(default_factory=list)
    baseline_established: bool = False
    baseline_description: str = ""
    notable_contrasts: list[str] = field(default_factory=list)

    def add_signal(self, signal: GrowthSignal, description: str):
        self.signals.append((datetime.utcnow(), signal, description))

    def detect_contrast(self, current_description: str, prior_description: str) -> Optional[str]:
        """
        Generate the "six months ago" observation.
        Only fires when there's a real, meaningful contrast.
        """
        if not self.baseline_description:
            return None

        contrast = (
            f"Earlier, {prior_description}. "
            f"Now, {current_description}. "
            f"That's not small — that's a real shift."
        )
        self.notable_contrasts.append(contrast)
        return contrast

    def latest_signal(self) -> Optional[GrowthSignal]:
        if not self.signals:
            return None
        return self.signals[-1][1]

    def trajectory_summary(self) -> str:
        if not self.signals:
            return "Not enough data to assess trajectory."
        recent = [s for _, s, _ in self.signals[-5:]]
        breakthroughs = recent.count(GrowthSignal.BREAKTHROUGH)
        regressions = recent.count(GrowthSignal.REGRESSION)
        if breakthroughs > regressions:
            return "Trending upward — more breakthroughs than setbacks recently."
        if regressions > breakthroughs:
            return "Difficult stretch — more setbacks than breakthroughs, but the arc continues."
        return "Holding ground — neither retreating nor surging, which is sometimes exactly right."


# ─────────────────────────────────────────────
# Meaning Extraction Engine
# ─────────────────────────────────────────────

class MeaningExtractor:
    """
    Extracts meaning units from session content.

    This is the detective layer for story, not facts.
    It looks for:
        - What the person gained or lost
        - What they learned (even implicitly)
        - What they're letting go of
        - What they're holding onto
        - What they think comes next
    """

    # Signal phrases for each meaning category
    GAIN_SIGNALS = [
        "i realized", "i understand now", "i finally get",
        "i found", "i have", "i now know", "i can see",
        "i'm starting to", "i've figured out", "i discovered"
    ]

    LOSS_SIGNALS = [
        "i lost", "i gave up", "i let go", "it's gone",
        "i stopped", "i don't anymore", "it didn't work",
        "i had to accept", "i had to let go", "i can't anymore"
    ]

    LEARN_SIGNALS = [
        "i learned", "i realized", "i discovered", "i found out",
        "it turns out", "i didn't know", "i was wrong about",
        "i understand now", "it makes sense now", "i see why"
    ]

    ENDURE_SIGNALS = [
        "i still", "no matter what", "regardless", "always",
        "i've always", "that's always been", "fundamentally",
        "at the core", "what remains", "what's true is"
    ]

    DIRECTION_SIGNALS = [
        "i want to", "i'm going to", "my plan is",
        "next i'll", "from here", "going forward",
        "i hope to", "i'm working toward", "eventually"
    ]

    def extract_from_session(
        self,
        session_transcript: str,
        session_id: str = "",
    ) -> list[MeaningUnit]:
        """
        Extract meaning units from a session transcript.
        Returns a list of MeaningUnit objects.
        """
        units = []
        sentences = self._split_sentences(session_transcript)

        for sentence in sentences:
            lower = sentence.lower()

            category = self._classify_sentence(lower)
            if category is None:
                continue

            # Extract the meaningful content
            content = self._extract_content(sentence, category)
            if not content or len(content) < 10:
                continue

            unit = MeaningUnit(
                category=category,
                content=content,
                confidence=self._estimate_confidence(sentence),
                session_id=session_id,
                source_text=sentence.strip(),
            )
            units.append(unit)

        return units

    def _classify_sentence(self, lower: str) -> Optional[MeaningCategory]:
        if any(s in lower for s in self.LEARN_SIGNALS):
            return MeaningCategory.LEARNED
        if any(s in lower for s in self.GAIN_SIGNALS):
            return MeaningCategory.GAINED
        if any(s in lower for s in self.LOSS_SIGNALS):
            return MeaningCategory.LOST
        if any(s in lower for s in self.ENDURE_SIGNALS):
            return MeaningCategory.ENDURES
        if any(s in lower for s in self.DIRECTION_SIGNALS):
            return MeaningCategory.DIRECTION
        return None

    def _extract_content(self, sentence: str, category: MeaningCategory) -> str:
        """
        Extract the actual meaningful content.
        Trim signal phrases, keep the substance.
        """
        content = sentence.strip()
        # Trim leading "I realized that" / "It turns out" etc.
        for signal in self.LEARN_SIGNALS + self.GAIN_SIGNALS + self.LOSS_SIGNALS:
            if content.lower().startswith(signal):
                content = content[len(signal):].lstrip(" ,that")
                break
        return content.strip().capitalize()

    def _estimate_confidence(self, sentence: str) -> float:
        """Higher confidence for declarative statements, lower for tentative ones."""
        hedge_words = ["maybe", "might", "perhaps", "kind of", "sort of", "i think", "not sure"]
        certainty_words = ["definitely", "clearly", "absolutely", "i know", "certain"]

        lower = sentence.lower()
        if any(w in lower for w in certainty_words):
            return 0.85
        if any(w in lower for w in hedge_words):
            return 0.4
        return 0.65

    def _split_sentences(self, text: str) -> list[str]:
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s for s in sentences if len(s.strip()) > 15]


# ─────────────────────────────────────────────
# MeaningMaker — The Full System
# ─────────────────────────────────────────────

class MeaningMaker:
    """
    The layer that answers: what did this mean?

    Not:  What happened?
    But:  What was learned? What was gained? What was lost? What endures?

    And over time:
          Where were you? Where are you now? Where do you think you're going?

    This is NarrativeContinuity. The thread that connects
    who someone was to who they're becoming.
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.extractor = MeaningExtractor()
        self.meaning_units: list[MeaningUnit] = []
        self.narrative = NarrativeArc(user_id=user_id)
        self.growth = GrowthTrajectory(user_id=user_id)
        self.session_count = 0

    # ── Ingestion ──────────────────────────────

    def ingest_session(
        self,
        session_transcript: str,
        session_id: str = "",
        growth_signal: Optional[GrowthSignal] = None,
        growth_description: str = "",
    ) -> dict:
        """
        Process a full session transcript.
        Extract meaning, update narrative, track growth.
        Returns a summary of what was found.
        """
        self.session_count += 1
        if not session_id:
            session_id = f"session_{self.session_count}"

        # Extract raw meaning units
        new_units = self.extractor.extract_from_session(session_transcript, session_id)

        # Merge with existing units (reinforce duplicates)
        for unit in new_units:
            self._merge_or_add(unit)

        # Update narrative arc
        self._update_narrative(session_transcript)

        # Track growth if provided
        if growth_signal:
            self.growth.add_signal(growth_signal, growth_description)
            if not self.growth.baseline_established and self.session_count == 1:
                self.growth.baseline_description = growth_description
                self.growth.baseline_established = True

        return self.session_summary(session_id)

    def add_meaning(
        self,
        category: MeaningCategory,
        content: str,
        confidence: float = 0.7,
        source: str = "",
    ) -> MeaningUnit:
        """
        Manually add a meaning unit (from system observation rather than transcript parsing).
        """
        unit = MeaningUnit(
            category=category,
            content=content,
            confidence=confidence,
            session_id=f"manual_{self.session_count}",
            source_text=source,
        )
        self._merge_or_add(unit)
        return unit

    def add_narrative_moment(self, phase: NarrativePhase, description: str):
        """Add a moment to the narrative arc."""
        if phase == NarrativePhase.BEFORE:
            self.narrative.before.append(description)
        elif phase == NarrativePhase.DURING:
            self.narrative.during.append(description)
        elif phase == NarrativePhase.AFTER:
            self.narrative.after.append(description)
        elif phase == NarrativePhase.DIRECTION:
            self.narrative.direction.append(description)

    def add_turning_point(self, description: str):
        """Record a moment that changed the trajectory."""
        self.narrative.turning_points.append(description)

    # ── Retrieval ─────────────────────────────

    def what_was_learned(self) -> list[MeaningUnit]:
        return self._by_category(MeaningCategory.LEARNED)

    def what_was_gained(self) -> list[MeaningUnit]:
        return self._by_category(MeaningCategory.GAINED)

    def what_was_lost(self) -> list[MeaningUnit]:
        return self._by_category(MeaningCategory.LOST)

    def what_endures(self) -> list[MeaningUnit]:
        return self._by_category(MeaningCategory.ENDURES)

    def where_are_they_going(self) -> list[MeaningUnit]:
        return self._by_category(MeaningCategory.DIRECTION)

    def get_narrative(self) -> NarrativeArc:
        return self.narrative

    def get_growth(self) -> GrowthTrajectory:
        return self.growth

    # ── Synthesis ─────────────────────────────

    def full_meaning_portrait(self) -> dict:
        """
        The complete meaning portrait.
        What the system knows about what this person's journey has meant.
        """
        portrait = {
            "user_id": self.user_id,
            "sessions_processed": self.session_count,
            "narrative": self.narrative.describe(),
            "growth_trajectory": self.growth.trajectory_summary(),
            "learned": [u.content for u in self.what_was_learned()[:5]],
            "gained": [u.content for u in self.what_was_gained()[:5]],
            "lost": [u.content for u in self.what_was_lost()[:5]],
            "endures": [u.content for u in self.what_endures()[:5]],
            "direction": [u.content for u in self.where_are_they_going()[:3]],
            "turning_points": self.narrative.turning_points[-3:],
            "notable_contrasts": self.growth.notable_contrasts[-2:],
            "most_reinforced": self._most_reinforced(),
            "unresolved": [u.content for u in self._by_category(MeaningCategory.UNRESOLVED)[:3]],
        }
        return portrait

    def generate_reflection(self) -> str:
        """
        A natural-language reflection on the meaning portrait.
        This is what the companion would say when looking back.

        Not: "Here are your data points."
        But: "Here's what the story looks like from where we stand."
        """
        lines = []

        if self.narrative.before:
            lines.append(f"You came from: {self.narrative.before[-1]}")

        if self.narrative.after:
            lines.append(f"You've arrived at: {self.narrative.after[-1]}")

        learned = self.what_was_learned()
        if learned:
            top = sorted(learned, key=lambda u: u.confidence, reverse=True)[0]
            lines.append(f"What you learned that seems to matter most: {top.content}")

        endures = self.what_endures()
        if endures:
            lines.append(f"What remains true: {endures[0].content}")

        lost = self.what_was_lost()
        if lost:
            lines.append(f"What you let go of: {lost[0].content}")

        if self.narrative.direction:
            lines.append(f"Where you're heading: {self.narrative.direction[-1]}")

        if self.growth.notable_contrasts:
            lines.append(f"\nWhat's remarkable: {self.growth.notable_contrasts[-1]}")

        if not lines:
            return "Still early. The meaning is still forming."

        return "\n".join(lines)

    def contrast_with_baseline(self, current_description: str) -> Optional[str]:
        """
        Generate a 'six months ago' observation if one is warranted.
        Only fires when there's a real, meaningful contrast.
        """
        if not self.growth.baseline_established:
            return None
        return self.growth.detect_contrast(
            current_description=current_description,
            prior_description=self.growth.baseline_description,
        )

    def session_summary(self, session_id: str) -> dict:
        """What did this specific session mean?"""
        session_units = [u for u in self.meaning_units if u.session_id == session_id]
        return {
            "session_id": session_id,
            "units_extracted": len(session_units),
            "learned": [u.content for u in session_units if u.category == MeaningCategory.LEARNED],
            "gained": [u.content for u in session_units if u.category == MeaningCategory.GAINED],
            "lost": [u.content for u in session_units if u.category == MeaningCategory.LOST],
            "endures": [u.content for u in session_units if u.category == MeaningCategory.ENDURES],
        }

    # ── Persistence ───────────────────────────

    def export(self) -> dict:
        return {
            "user_id": self.user_id,
            "session_count": self.session_count,
            "meaning_units": [
                {
                    "id": u.id,
                    "category": u.category.value,
                    "content": u.content,
                    "confidence": u.confidence,
                    "session_id": u.session_id,
                    "reinforced_count": u.reinforced_count,
                    "timestamp": u.timestamp.isoformat(),
                }
                for u in self.meaning_units
            ],
            "narrative": {
                "before": self.narrative.before,
                "after": self.narrative.after,
                "direction": self.narrative.direction,
                "turning_points": self.narrative.turning_points,
                "current_chapter": self.narrative.current_chapter,
            },
            "growth": {
                "baseline": self.growth.baseline_description,
                "baseline_established": self.growth.baseline_established,
                "signals": [
                    (ts.isoformat(), sig.value, desc)
                    for ts, sig, desc in self.growth.signals
                ],
                "notable_contrasts": self.growth.notable_contrasts,
            },
        }

    @classmethod
    def from_export(cls, data: dict) -> "MeaningMaker":
        maker = cls(user_id=data["user_id"])
        maker.session_count = data["session_count"]

        for ud in data.get("meaning_units", []):
            unit = MeaningUnit(
                id=ud["id"],
                category=MeaningCategory(ud["category"]),
                content=ud["content"],
                confidence=ud["confidence"],
                session_id=ud["session_id"],
                reinforced_count=ud["reinforced_count"],
                timestamp=datetime.fromisoformat(ud["timestamp"]),
            )
            maker.meaning_units.append(unit)

        nav = data.get("narrative", {})
        maker.narrative.before = nav.get("before", [])
        maker.narrative.after = nav.get("after", [])
        maker.narrative.direction = nav.get("direction", [])
        maker.narrative.turning_points = nav.get("turning_points", [])
        maker.narrative.current_chapter = nav.get("current_chapter", "")

        grw = data.get("growth", {})
        maker.growth.baseline_description = grw.get("baseline", "")
        maker.growth.baseline_established = grw.get("baseline_established", False)
        maker.growth.notable_contrasts = grw.get("notable_contrasts", [])
        for ts_str, sig_str, desc in grw.get("signals", []):
            maker.growth.signals.append((
                datetime.fromisoformat(ts_str),
                GrowthSignal(sig_str),
                desc,
            ))

        return maker

    # ── Internal ──────────────────────────────

    def _merge_or_add(self, new_unit: MeaningUnit):
        """
        Check if a meaning unit is substantially similar to an existing one.
        If so, reinforce the existing one instead of adding a duplicate.
        """
        for existing in self.meaning_units:
            if existing.category == new_unit.category:
                if self._substantial_overlap(existing.content, new_unit.content):
                    existing.reinforce(new_unit.source_text)
                    return
        self.meaning_units.append(new_unit)

    def _substantial_overlap(self, a: str, b: str) -> bool:
        """Simple word-overlap check for near-duplicates."""
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return False
        overlap = words_a & words_b
        shorter = min(len(words_a), len(words_b))
        return len(overlap) / shorter > 0.6

    def _by_category(self, cat: MeaningCategory) -> list[MeaningUnit]:
        units = [u for u in self.meaning_units if u.category == cat]
        return sorted(units, key=lambda u: (u.reinforced_count, u.confidence), reverse=True)

    def _most_reinforced(self) -> Optional[str]:
        if not self.meaning_units:
            return None
        top = max(self.meaning_units, key=lambda u: u.reinforced_count)
        return f"{top.content} (mentioned {top.reinforced_count}x)"

    def _update_narrative(self, session_transcript: str):
        """
        Simple heuristic to update the narrative arc from session content.
        More sophisticated versions would use the EQ adaptor to flag arc moments.
        """
        lower = session_transcript.lower()

        before_signals = ["used to", "i was", "back then", "before this", "i used to think"]
        after_signals = ["now i", "i've become", "i can see now", "these days", "at this point"]
        direction_signals = ["i want to", "i'm working on", "my goal", "i hope to", "next step"]
        turning_signals = ["that changed everything", "that was the moment", "i realized then",
                           "after that", "it was a turning point"]

        for signal in before_signals:
            if signal in lower:
                idx = lower.find(signal)
                snippet = session_transcript[idx:idx+80].strip()
                if snippet not in self.narrative.before:
                    self.narrative.before.append(snippet)

        for signal in after_signals:
            if signal in lower:
                idx = lower.find(signal)
                snippet = session_transcript[idx:idx+80].strip()
                if snippet not in self.narrative.after:
                    self.narrative.after.append(snippet)

        for signal in direction_signals:
            if signal in lower:
                idx = lower.find(signal)
                snippet = session_transcript[idx:idx+80].strip()
                if snippet not in self.narrative.direction:
                    self.narrative.direction.append(snippet)

        for signal in turning_signals:
            if signal in lower:
                idx = lower.find(signal)
                snippet = session_transcript[idx:idx+80].strip()
                if snippet not in self.narrative.turning_points:
                    self.narrative.turning_points.append(snippet)


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def create_meaning_maker(user_id: str) -> MeaningMaker:
    return MeaningMaker(user_id=user_id)


# ─────────────────────────────────────────────
# Demo
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("MEANING MAKER DEMO")
    print("=" * 60)

    maker = create_meaning_maker("user_pete")

    # Session 1 — early
    session1 = """
    I used to think I had to have everything figured out before I started.
    I lost a lot of time waiting for the perfect moment.
    I realized now that the waiting was the problem, not the timing.
    I'm starting to just go ahead and build things even when I'm not ready.
    """
    result1 = maker.ingest_session(
        session1,
        session_id="session_1",
        growth_signal=GrowthSignal.INCREMENTAL,
        growth_description="recognizes paralysis pattern but hasn't fully broken it yet"
    )
    print("\nSession 1 extracted:")
    for k, v in result1.items():
        if v:
            print(f"  {k}: {v}")

    # Session 2 — later
    session2 = """
    I launched the first version last week. It's messy but it's out there.
    I learned that done is better than perfect — not as a cliché, as an actual experience.
    I discovered that people responded better than I expected.
    Still, no matter what happens with the product, I know now that I can execute.
    I want to build three more things before the end of the year.
    """
    result2 = maker.ingest_session(
        session2,
        session_id="session_2",
        growth_signal=GrowthSignal.BREAKTHROUGH,
        growth_description="shipped something real and learned they can execute under imperfect conditions"
    )

    maker.add_turning_point("Shipped the first version despite it being incomplete")
    maker.add_narrative_moment(NarrativePhase.BEFORE, "Waiting for perfect conditions before starting")
    maker.add_narrative_moment(NarrativePhase.AFTER, "Has shipped and knows they can execute")
    maker.add_narrative_moment(NarrativePhase.DIRECTION, "Planning three more builds this year")

    print("\n--- FULL MEANING PORTRAIT ---")
    portrait = maker.full_meaning_portrait()
    for k, v in portrait.items():
        if v:
            print(f"  {k}: {v}")

    print("\n--- REFLECTION ---")
    print(maker.generate_reflection())

    print("\n--- CONTRAST ---")
    contrast = maker.contrast_with_baseline(
        "shipping things before they're ready and learning from real feedback"
    )
    if contrast:
        print(contrast)

    print("\n--- EXPORT/IMPORT ROUND-TRIP ---")
    exported = maker.export()
    restored = MeaningMaker.from_export(exported)
    print(f"Restored {len(restored.meaning_units)} meaning units across {restored.session_count} sessions")
    print(f"Narrative: {restored.narrative.describe()}")
