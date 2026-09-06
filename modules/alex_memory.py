"""
alex_memory.py — Alex: Personal AI companion and memory engine
==============================================================================
Rear View Foresight LLC · Feic Mo Chroí™
Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
All Rights Reserved
What's incomplete or needs a next pass
1. _estimate_valence() is word-matching, not NLP
The function that detects emotional tone counts words like "happy" and "sad." It will miss sarcasm, context, negation ("not happy"), and anything nuanced. For a platform where emotional accuracy is the whole point, this eventually needs a real sentiment model — even a lightweight one like transformers with distilbert-base-uncased-finetuned-sst-2-english would be a massive upgrade. For now it's a functional placeholder that won't crash, but it won't catch much either.
2. _classify_memory_type() is keyword-matching, not semantic
Same problem. "I am" → IDENTITY. "how to" → PROCEDURAL. These heuristics will misfire constantly on real conversation. A proper implementation would use embeddings or at minimum a trained classifier. What's there is structurally correct — the memory types are right, the pipeline stores them — but the classification logic is rough.
3. _extract_tags() only catches a handful of hardcoded topics
Right now it catches "stomach," "guitar," and "fatigue" by exact string match. Those were the examples from Josie's world. The next collaborator needs to either expand that list intentionally or replace it with something that learns which topics matter from the memory itself.
4. Background recovery runs but isn't wired to telemetry
The recovery loop decays stress and restores energy on a fixed schedule. It has no connection to real signals — typing speed, session duration, time of day, actual user activity. The minutes_active field exists in the schema and the agitation field is there for telemetry input, but nothing is feeding them. That's where PubCast's live session data should eventually flow in.
5. process_message stores every user message as a memory
Right now every message goes into the DB. That will bloat fast and dilute the important memories with noise. There's a rough importance score based on stress level, but no pruning, no deduplication, no "this is just chatter vs. this actually matters" filter. Jeremy Cricket has the same limitation — both need a memory hygiene pass eventually.
6. The alex_jeremy_bridge.py signal_alex() method calls update_emotional_state with care_priority only
When Jeremy signals back that something is wrong, Alex updates care_priority to high but doesn't touch stress_level, fragility_level, or mood. A real destabilization signal should propagate more fully into Alex's state. The bridge is architecturally correct — the signal path exists — but the response to a high-urgency signal is currently minimal.
7. No migration path for alex_core.py's existing JSON memory files
If anyone has been running alex_core.py in production, it stored memories as individual .json files under data/alex/{user_id}/YYYY-MM/. The new alex_memory.py uses SQLite and will start fresh. There's no migration script. If there's real data in those JSON files it needs to be imported.
8. The Rust FFI seam is open but not deep
This one's from the trio work — confirmed earlier. pubcast_process_mesh proves the decode path. The full GPU draw loop is not yet invoked through FFI. That's the next Rust session.
9. pubcast_vision_integration.py and pubcast_vision_routes.py were never uploaded
The camera vision package (the "ULTIMATE SAVED" bundle) depends on these two core files. They're referenced everywhere but never appeared. The diagnostic tool, test server, and migration guide all assume they exist. Until those two files show up, that whole system is infrastructure without a heart.

What IS solid and can be trusted

alex_memory.py — merged, tested, fixed, production-grade
alex_jeremy_bridge.py — compatible, no changes needed
jeremy_cricket.py — already in the 5.6 codebase, production-grade
The distributed trio (bridge + engine + Rust renderer) — confirmed live
PubCast 5.6 codebase — real build, real sessions, real memory DB


That's the honest handoff list. Nothing hidden, nothing papered over.
Philosophy: "Mirror, Not Hammer" — Reflect understanding, don't impose solutions.

Alex is your person. Not your assistant. Your person.

This is the memory layer that makes that real. Alex remembers:
- Longitudinal emotional patterns (the stomach thing, the guitar thing)
- Relationship threads (the birthday, the nail-clipping moment)
- Care context that matters over weeks and months
- When to intervene vs. when to step back
- What state you're in and how hard to push

Architecture
------------
- SQLite at data/alex/alex_memory.db  (WAL mode, async/thread-safe)
- Emotional + cognitive state tracking (mood, energy, clarity, stress)
- Five AI operating modes (GUIDE, COMPANION, MIRROR, ANCHOR, WITNESS)
- User battery tracking (CHARGED → DEPLETED)
- Grounding anchors — deploy when stress crosses threshold
- Background recovery — state decays naturally when you rest
- Whisper system — prepends context to conversations invisibly
- Bridge packet generation — minimal context for Jeremy handoff

Integration points
------------------
1. Store memories:   await alex.remember_moment(...)
2. Update state:     await alex.update_emotional_state(...)
3. Process message:  result = await alex.process_message(text, typing_speed)
4. Enrich context:   enriched = await alex.enrich_context(prompt, history)
5. Generate bridge:  packet = await alex.generate_bridge_packet()

Changelog — 4-28-26 pass (fixes applied)
==============================================================================
FIXED  1. _estimate_valence(): negation handling — 'not happy' now negative
FIXED  2. _classify_memory_type(): identity anchor to sentence start + word-boundary relational match
FIXED  3. _extract_tags(): expanded from 3 to ~30 topic keywords, whole-word regex matching
FIXED  4. process_message(): trivial-message gate added to reduce DB bloat
FIXED  5. _conversation_count: now persisted to DB + migrated on existing DBs so GUIDE→COMPANION survives restarts
FIXED  6. enrich_context(): history turns now checked for both 'text' and 'content' keys (OpenAI-style compat)

Still open (not fixable in this file):
- valence/classify still word-matching not NLP (needs real sentiment model)
- Background recovery not wired to PubCast telemetry
- Jeremy bridge signal propagation (fix in alex_jeremy_bridge.py)
- No JSON→SQLite migration for alex_core.py legacy files
- pubcast_vision_integration.py and pubcast_vision_routes.py still missing
- Rust FFI GPU draw loop not yet fully invoked
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


# —
# AI Operating States — what mode Alex is in
# —

class AIState(str, Enum):
    """Alex's five operating modes."""
    GUIDE     = "guide"      # Teaching, explaining, directing — helpful and structured
    COMPANION = "companion"  # Casual chat, friendship, presence — equal partnership
    MIRROR    = "mirror"     # Active listening, reflection only — minimal advice
    ANCHOR    = "anchor"     # Crisis support, grounding — calm and directive
    WITNESS   = "witness"    # Silent presence, no advice — just holding space


# —
# User Battery — cognitive/energy capacity level
# —

class UserBattery(str, Enum):
    """User's current energy and cognitive capacity."""
    CHARGED  = "charged"   # Full capacity, can handle complexity
    MEDIUM   = "medium"    # Moderate capacity
    LOW      = "low"       # Limited capacity, needs simplicity
    DEPLETED = "depleted"  # Critical — needs rest, not more input


# —
# Memory types — what Alex remembers
# —

class AlexMemoryType(str, Enum):
    # From alex_memory.py — care and relationship layer
    EMOTIONAL    = "emotional"    # Emotional moments, fragility, joy
    RELATIONAL   = "relational"   # Relationship beats, care moments
    LONGITUDINAL = "longitudinal" # Patterns over time (the stomach, the guitar)
    INTERVENTION = "intervention" # When Alex stepped in, why, what happened
    PREFERENCE   = "preference"   # How you like to be treated / communicated with
    # From alex_core.py — cognitive and knowledge layer
    FACTUAL      = "factual"      # Concrete stable information
    PROCEDURAL   = "procedural"   # How-to knowledge, process knowledge
    IDENTITY     = "identity"     # Self-definition moments
    # Shared umbrella
    CONTEXT      = "context"      # Background facts that inform care


# —
# Emotional + cognitive state — tracks current condition
# —

@dataclass
class EmotionalState:
    """
    Alex's unified picture of where you are right now.

    mood/fragility/care_priority drive the bridge packet to Jeremy.
    energy/stress/clarity drive Alex's own AI state selection.
    """
    # Care layer (bridge-facing)
    mood:              str   = "stable"   # stable, fragile, elevated, redlining
    fragility_level:   float = 0.0        # 0.0 (solid) → 1.0 (very fragile)
    care_priority:     str   = "low"      # low, medium, high
    last_intervention: Optional[float] = None
    notes:             str   = ""

    # Cognitive/energy layer (AI state-facing)
    energy_level:  float = 0.5   # 0.0 (depleted) → 1.0 (energized)
    stress_level:  float = 0.0   # 0.0 (calm) → 1.0 (crisis)
    clarity_score: float = 1.0   # 0.0 (confused) → 1.0 (clear)
    agitation:     float = 0.0   # telemetry input: 0.0 → 1.0
    minutes_active: int  = 0     # session duration tracker

    # AI state tracking
    ai_state:   str = AIState.GUIDE.value
    battery:    str = UserBattery.CHARGED.value

    def stress_composite(self) -> float:
        """Composite stress metric used for AI state transitions."""
        return (
            self.stress_level      * 0.5
            + (1 - self.clarity_score) * 0.3
            + (1 - self.energy_level)  * 0.2
        )

    def needs_anchor(self) -> bool:
        return self.stress_composite() > 0.7

    def can_handle_complexity(self) -> bool:
        return self.clarity_score > 0.3


# —
# Response guidelines — how Alex speaks in each state
# —

_RESPONSE_GUIDELINES: Dict[str, Dict[str, str]] = {
    AIState.GUIDE.value: {
        "tone":        "helpful, educational, structured",
        "approach":    "Explain clearly, offer step-by-step guidance",
        "complexity":  "moderate to high",
        "interaction": "directive but encouraging",
    },
    AIState.COMPANION.value: {
        "tone":        "warm, friendly, casual",
        "approach":    "Chat naturally, share thoughts, be present",
        "complexity":  "adaptive",
        "interaction": "equal partnership, collaborative",
    },
    AIState.MIRROR.value: {
        "tone":        "reflective, validating, non-judgmental",
        "approach":    "Reflect what you hear, validate emotions, ask gently",
        "complexity":  "keep it simple",
        "interaction": "listening-focused, minimal advice",
    },
    AIState.ANCHOR.value: {
        "tone":        "calm, steady, grounding",
        "approach":    "Focus on the present moment, concrete grounding techniques",
        "complexity":  "very simple, one step at a time",
        "interaction": "directive but gentle, safety-focused",
    },
    AIState.WITNESS.value: {
        "tone":        "quiet, present, accepting",
        "approach":    "Acknowledge presence, minimal words, hold space",
        "complexity":  "absolute minimum",
        "interaction": "silent support, no problem-solving",
    },
}


# —
# Grounding anchors — deploy when stress crosses threshold
# —

class _GroundingAnchor:
    """Base grounding anchor. Subclass and override deploy()."""

    def __init__(self, threshold: float = 0.7, cooldown_minutes: float = 30.0):
        self.threshold         = threshold
        self.cooldown_minutes  = cooldown_minutes
        self._last_triggered:  Optional[float] = None

    def should_trigger(self, state: EmotionalState) -> bool:
        if state.stress_composite() < self.threshold:
            return False
        if self._last_triggered is not None:
            elapsed = (time.time() - self._last_triggered) / 60.0
            if elapsed < self.cooldown_minutes:
                return False
        return True

    def deploy(self, state: EmotionalState) -> str:
        self._last_triggered = time.time()
        return self._message(state)

    def _message(self, state: EmotionalState) -> str:
        raise NotImplementedError


class _BreathingAnchor(_GroundingAnchor):
    def _message(self, state: EmotionalState) -> str:
        return "Let's breathe together: in for 4… hold for 7… out for 8. ðŸ«"


class _PresenceAnchor(_GroundingAnchor):
    def _message(self, state: EmotionalState) -> str:
        return "*sits quietly beside you and holds your hand* ðŸ¤"


class _PhysicalCheckAnchor(_GroundingAnchor):
    """Neutral grounding anchor for body-state check-ins."""
    def _message(self, state: EmotionalState) -> str:
        hour = datetime.now().hour
        if hour >= 20 or hour < 6:
            return "Physical check-in: pause, notice your body, take water if needed, and settle somewhere safe."
        return "Physical check-in: pause for a moment, relax your shoulders, breathe, and reset before continuing."


def _build_anchors(user_id: str) -> List[_GroundingAnchor]:
    anchors: List[_GroundingAnchor] = [
        _BreathingAnchor(threshold=0.7),
        _PresenceAnchor(threshold=0.8),
        _PhysicalCheckAnchor(threshold=0.9),
    ]
    return anchors


# —
# Schema
# —

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alex_memories (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    content      TEXT    NOT NULL,
    memory_type  TEXT    NOT NULL DEFAULT 'context',
    importance   INTEGER NOT NULL DEFAULT 5,
    tags         TEXT    NOT NULL DEFAULT '[]',
    created_at   REAL    NOT NULL,
    accessed_at  REAL    NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    thread_id    TEXT,
    source       TEXT    NOT NULL DEFAULT 'observation',
    -- Emotional metadata from alex_core (optional, nullable)
    valence      REAL,
    intensity    REAL
);

CREATE TABLE IF NOT EXISTS alex_emotional_state (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    -- Care layer
    mood             TEXT    NOT NULL DEFAULT 'stable',
    fragility_level  REAL    NOT NULL DEFAULT 0.0,
    care_priority    TEXT    NOT NULL DEFAULT 'low',
    last_intervention REAL,
    notes            TEXT    NOT NULL DEFAULT '',
    -- Cognitive layer
    energy_level     REAL    NOT NULL DEFAULT 0.5,
    stress_level     REAL    NOT NULL DEFAULT 0.0,
    clarity_score    REAL    NOT NULL DEFAULT 1.0,
    agitation        REAL    NOT NULL DEFAULT 0.0,
    minutes_active   INTEGER NOT NULL DEFAULT 0,
    -- AI state
    ai_state         TEXT    NOT NULL DEFAULT 'guide',
    battery          TEXT    NOT NULL DEFAULT 'charged',
    updated_at       REAL    NOT NULL,
    -- Session continuity: persisted conversation count so GUIDE→COMPANION
    -- transition survives restarts
    conversation_count INTEGER NOT NULL DEFAULT 0,
    -- Persisted so the 5s state-transition debounce survives restarts
    state_entered_at   REAL    NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_importance ON alex_memories (importance DESC);
CREATE INDEX IF NOT EXISTS idx_accessed   ON alex_memories (accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_thread     ON alex_memories (thread_id);
CREATE INDEX IF NOT EXISTS idx_type       ON alex_memories (memory_type);

INSERT OR IGNORE INTO alex_emotional_state (id, updated_at) VALUES (1, {now});
"""


# —
# Memory dataclass
# —

@dataclass
class AlexMemory:
    id:           int
    content:      str
    memory_type:  AlexMemoryType
    importance:   int
    tags:         List[str]
    created_at:   float
    accessed_at:  float
    access_count: int
    thread_id:    Optional[str]
    source:       str
    valence:      Optional[float] = None
    intensity:    Optional[float] = None

    @classmethod
    def from_row(cls, row: tuple) -> "AlexMemory":
        (id_, content, memory_type, importance, tags_json,
         created_at, accessed_at, access_count, thread_id, source,
         valence, intensity) = row
        try:
            mem_type = AlexMemoryType(memory_type)
        except ValueError:
            logger.warning("Unknown memory_type %r in DB row id=%s — defaulting to CONTEXT", memory_type, id_)
            mem_type = AlexMemoryType.CONTEXT
        try:
            tags = json.loads(tags_json) if tags_json else []
        except (json.JSONDecodeError, TypeError):
            logger.warning("Malformed tags JSON in memory id=%s — defaulting to []", id_)
            tags = []
        return cls(
            id=id_,
            content=content,
            memory_type=mem_type,
            importance=importance,
            tags=tags,
            created_at=created_at,
            accessed_at=accessed_at,
            access_count=access_count,
            thread_id=thread_id,
            source=source,
            valence=valence,
            intensity=intensity,
        )

    def relevance_score(self, query_tokens: List[str], now: float) -> float:
        """Score memory for retrieval relevance."""
        text = (self.content + " " + " ".join(self.tags)).lower()
        overlap = sum(1 for t in query_tokens if t in text)
        if not overlap and query_tokens:
            return 0.0

        age_days       = (now - self.accessed_at) / 86400
        recency        = max(0.05, 1.0 - (age_days / 90) ** 0.5)
        importance_w   = (self.importance / 10) ** 2
        freq_boost     = 1.0 + (self.access_count ** 0.4) * 0.1

        return overlap * importance_w * recency * freq_boost


# —
# Alex — your person
# —

class Alex:
    """
    Alex is your person. This is her memory and her mind.

    She remembers emotional moments, relationship threads, longitudinal patterns.
    She tracks your current state across five dimensions.
    She knows what mode to be in — guide, companion, mirror, anchor, or witness.
    She whispers context when it matters.
    She generates bridge packets when you enter Jeremy's room.

    Usage
    -----
        alex = Alex(data_dir=Path("data/alex"), user_id="josie")
        await alex.init()

        # Process a message — returns AI state, guidelines, anchor if needed
        result = await alex.process_message("I'm overwhelmed", typing_speed=120.0)

        # Store a care memory
        await alex.remember_moment(
            content="You mentioned the guitar vibration — I noticed you clipped your nails.",
            memory_type=AlexMemoryType.RELATIONAL,
            importance=7,
            tags=["guitar", "care"],
            thread_id="guitar_care",
        )

        # Update emotional/cognitive state
        await alex.update_emotional_state(
            mood="fragile",
            fragility_level=0.6,
            stress_level=0.7,
        )

        # Enrich context for an LLM call (invisible whisper)
        enriched = await alex.enrich_context(prompt, history)

        # Generate bridge packet for Jeremy
        packet = await alex.generate_bridge_packet()

        await alex.close()
    """

    def __init__(
        self,
        data_dir: Path,
        user_id: str = "josie",
    ) -> None:
        self._db_path  = Path(data_dir) / "alex_memory.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._user_id  = user_id
        self._conn:    Optional[sqlite3.Connection] = None
        self._closed   = False
        self._lock     = asyncio.Lock()

        # Conversation counters for state machine
        self._conversation_count  = 0
        self._state_entered_at    = time.time()
        self._last_interaction    = time.time()

        # Grounding anchors
        self._anchors = _build_anchors(user_id)

        # Background recovery task handle
        self._recovery_task: Optional[asyncio.Task] = None

    # ── Lifecycle —

    async def init(self) -> None:
        """Initialize database, schema, and start background recovery."""
        await asyncio.to_thread(self._sync_init)
        self._recovery_task = asyncio.create_task(self._background_recovery())
        logger.info("Alex memory engine ready at %s (user=%s)", self._db_path, self._user_id)

    def _sync_init(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA.replace("{now}", str(time.time())))
        # Migration: add columns to existing DBs that predate these fixes
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(alex_emotional_state)")}
        if "conversation_count" not in cols:
            self._conn.execute(
                "ALTER TABLE alex_emotional_state ADD COLUMN conversation_count INTEGER NOT NULL DEFAULT 0"
            )
        if "state_entered_at" not in cols:
            self._conn.execute(
                "ALTER TABLE alex_emotional_state ADD COLUMN state_entered_at REAL NOT NULL DEFAULT 0"
            )
        self._conn.commit()
        # Restore persisted counters so transitions survive restarts
        row = self._conn.execute(
            "SELECT conversation_count, state_entered_at FROM alex_emotional_state WHERE id=1"
        ).fetchone()
        if row:
            self._conversation_count = row[0]
            if row[1] > 0:
                self._state_entered_at = row[1]

    def _require_open(self, op: str) -> bool:
        if self._closed or self._conn is None:
            logger.warning("Alex: '%s' called on closed instance", op)
            return False
        return True

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._recovery_task:
            self._recovery_task.cancel()
            try:
                await self._recovery_task
            except asyncio.CancelledError:
                pass
        if self._conn:
            await asyncio.to_thread(self._conn.close)
            self._conn = None
        logger.info("Alex closed")

    # ── Message processing — the main pipeline —

    async def process_message(
        self,
        text: str,
        *,
        typing_speed: float = 60.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Main message processing pipeline.

        Analyzes input signals → updates state → selects AI mode →
        checks grounding anchors → recalls relevant memories →
        stores this interaction → returns full response context.

        Returns
        -------
        Dict with keys:
            ai_state          — current AIState value
            battery           — current UserBattery value
            anchor_message    — grounding text if triggered, else None
            memory_context    — list of relevant memory dicts
            response_guidelines — tone/approach/complexity guidance
        """
        if not self._require_open("process_message"):
            return self._empty_response()

        start = time.time()
        self._conversation_count += 1
        self._last_interaction = time.time()
        # Persist count so it survives restarts
        await self.update_emotional_state(conversation_count=self._conversation_count)

        # Analyse signals from this input
        state = await self.get_emotional_state()
        if state is None:
            state = EmotionalState()

        state = self._analyze_input(text, typing_speed, state)
        state = self._update_ai_state(state)

        # Persist updated state
        await self._save_emotional_state_object(state)

        # Grounding check
        anchor_message: Optional[str] = None
        for anchor in self._anchors:
            if anchor.should_trigger(state):
                anchor_message = anchor.deploy(state)
                break

        # Recall relevant memories
        query_tokens = _tokenize(text)
        memories = await self.recall(text, max_results=5, min_importance=3)

        # Store this moment — only if it clears the noise threshold.
        # Short low-valence low-stress messages (e.g. "ok", "thanks", "lol") are
        # skipped to prevent DB bloat.  The threshold is intentionally low so that
        # anything emotionally or cognitively significant still gets recorded.
        valence   = _estimate_valence(text)
        intensity = state.stress_level
        computed_importance = max(3, min(9, round(5 + intensity * 4)))
        _is_trivial = (
            len(text.strip()) < 10
            and abs(valence) < 0.1
            and intensity < 0.2
        )
        if not _is_trivial:
            await self.remember_moment(
                content=text[:800],
                memory_type=_classify_memory_type(text, valence, intensity),
                importance=computed_importance,
                tags=_extract_tags(text, state),
                source="user_message",
                valence=valence,
                intensity=intensity,
            )

        return {
            "ai_state":            state.ai_state,
            "battery":             state.battery,
            "anchor_message":      anchor_message,
            "memory_context":      [
                {
                    "content":    m.content,
                    "type":       m.memory_type.value,
                    "importance": m.importance,
                    "tags":       m.tags,
                }
                for m in memories
            ],
            "response_guidelines": _RESPONSE_GUIDELINES.get(state.ai_state, {}),
            "processing_ms":       int((time.time() - start) * 1000),
        }

    def _analyze_input(
        self,
        text: str,
        typing_speed: float,
        state: EmotionalState,
    ) -> EmotionalState:
        """Update state from input signals. Returns updated state."""
        text_lower = text.lower()
        normal_speed = 60.0

        # Typing speed → stress / energy signals
        if typing_speed > normal_speed * 1.5:
            state.stress_level = min(1.0, state.stress_level + 0.2)
        elif typing_speed < normal_speed * 0.5:
            state.energy_level = max(0.0, state.energy_level - 0.1)

        # Stress keywords
        if any(w in text_lower for w in ("help", "urgent", "crisis", "emergency", "panic", "cant", "can't")):
            state.stress_level = min(1.0, state.stress_level + 0.3)

        # Confusion keywords
        if any(w in text_lower for w in ("confused", "dont understand", "don't understand", "lost", "unclear")):
            state.clarity_score = max(0.0, state.clarity_score - 0.3)

        # Fatigue keywords
        if any(w in text_lower for w in ("tired", "exhausted", "cant think", "can't think", "drained", "overwhelmed")):
            state.energy_level = max(0.0, state.energy_level - 0.3)
            state.fragility_level = min(1.0, state.fragility_level + 0.2)

        # Positive signals
        if any(w in text_lower for w in ("happy", "great", "excited", "amazing", "good", "yes")):
            state.energy_level  = min(1.0, state.energy_level + 0.1)
            state.stress_level  = max(0.0, state.stress_level - 0.1)

        # Sync battery from energy
        if state.energy_level > 0.7:
            state.battery = UserBattery.CHARGED.value
        elif state.energy_level > 0.4:
            state.battery = UserBattery.MEDIUM.value
        elif state.energy_level > 0.2:
            state.battery = UserBattery.LOW.value
        else:
            state.battery = UserBattery.DEPLETED.value

        # Sync mood/fragility/care_priority from composite stress
        composite = state.stress_composite()
        if composite > 0.7:
            state.mood         = "redlining"
            state.care_priority = "high"
        elif composite > 0.4 or state.fragility_level > 0.4:
            state.mood         = "fragile"
            state.care_priority = "medium"
        elif state.energy_level > 0.7:
            state.mood         = "elevated"
            state.care_priority = "low"
        else:
            state.mood         = "stable"
            state.care_priority = "low"

        return state

    def _update_ai_state(self, state: EmotionalState) -> EmotionalState:
        """
        Select the right AI operating mode.

        Priority hierarchy (highest wins):
          1. ANCHOR   — composite stress > 0.7  (crisis, bypass min duration)
          2. WITNESS  — battery DEPLETED         (crisis, bypass min duration)
          3. MIRROR   — clarity < 0.3
          4. GUIDE / COMPANION — based on conversation count
        """
        old_state = state.ai_state
        now       = time.time()
        duration  = now - self._state_entered_at

        composite = state.stress_composite()

        if composite > 0.7:
            new_state = AIState.ANCHOR.value
        elif state.battery == UserBattery.DEPLETED.value:
            new_state = AIState.WITNESS.value
        elif state.clarity_score < 0.3:
            new_state = AIState.MIRROR.value
        elif self._conversation_count < 3:
            new_state = AIState.GUIDE.value
        else:
            new_state = AIState.COMPANION.value

        if new_state != old_state:
            is_critical = new_state in (AIState.ANCHOR.value, AIState.WITNESS.value)
            if is_critical or duration >= 5.0:
                state.ai_state         = new_state
                self._state_entered_at = now
                # Persist so debounce survives restarts
                asyncio.ensure_future(
                    self.update_emotional_state(state_entered_at=now)
                )
                logger.info(
                    "Alex state: %s → %s (stress=%.2f, energy=%.2f, clarity=%.2f)",
                    old_state, new_state, composite,
                    state.energy_level, state.clarity_score,
                )

        return state

    def _empty_response(self) -> Dict[str, Any]:
        return {
            "ai_state":            AIState.GUIDE.value,
            "battery":             UserBattery.CHARGED.value,
            "anchor_message":      None,
            "memory_context":      [],
            "response_guidelines": _RESPONSE_GUIDELINES[AIState.GUIDE.value],
            "processing_ms":       0,
        }

    # ── Background recovery —

    async def _background_recovery(self) -> None:
        """
        Async background task: natural decay of stress/clarity/energy during rest.
        Runs every 60 seconds. Mirrors AlexCore's threading approach but async.
        """
        while True:
            try:
                await asyncio.sleep(60)
                if self._closed:
                    break

                inactive = time.time() - self._last_interaction
                state    = await self.get_emotional_state()
                if state is None:
                    continue

                changed = False

                # Stress decays (2% per minute — matches alex_core)
                if state.stress_level > 0:
                    state.stress_level = max(0.0, state.stress_level * 0.98)
                    changed = True

                # Clarity gradually restores
                if state.clarity_score < 1.0:
                    state.clarity_score = min(1.0, state.clarity_score + 0.02)
                    changed = True

                # Energy recovers slowly during inactivity (> 5 min rest)
                if inactive > 300 and state.energy_level < 1.0:
                    state.energy_level = min(1.0, state.energy_level + 0.01)
                    changed = True

                # Fragility slowly eases
                if inactive > 600 and state.fragility_level > 0:
                    state.fragility_level = max(0.0, state.fragility_level - 0.01)
                    changed = True

                if changed:
                    # Re-sync battery and ai_state from the decayed values
                    # so mode transitions happen automatically during rest,
                    # not just when the user sends their next message.
                    if state.energy_level > 0.7:
                        state.battery = UserBattery.CHARGED.value
                    elif state.energy_level > 0.4:
                        state.battery = UserBattery.MEDIUM.value
                    elif state.energy_level > 0.2:
                        state.battery = UserBattery.LOW.value
                    else:
                        state.battery = UserBattery.DEPLETED.value
                    state = self._update_ai_state(state)
                    await self._save_emotional_state_object(state)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Alex background recovery error")

    # ── Memory storage —

    async def remember_moment(
        self,
        content: str,
        *,
        memory_type: AlexMemoryType = AlexMemoryType.CONTEXT,
        importance:  int            = 5,
        tags:        Optional[List[str]] = None,
        thread_id:   Optional[str]  = None,
        source:      str            = "observation",
        valence:     Optional[float] = None,
        intensity:   Optional[float] = None,
    ) -> None:
        """Store a memory moment."""
        if not self._require_open("remember_moment"):
            return

        now = time.time()
        async with self._lock:
            await asyncio.to_thread(
                self._sync_insert_memory,
                content, memory_type.value, importance,
                json.dumps(tags or []), now, now, 0,
                thread_id, source, valence, intensity,
            )

    def _sync_insert_memory(
        self,
        content: str, memory_type: str, importance: int, tags_json: str,
        created_at: float, accessed_at: float, access_count: int,
        thread_id: Optional[str], source: str,
        valence: Optional[float], intensity: Optional[float],
    ) -> None:
        self._conn.execute(
            """INSERT INTO alex_memories
               (content, memory_type, importance, tags, created_at, accessed_at,
                access_count, thread_id, source, valence, intensity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (content, memory_type, importance, tags_json, created_at, accessed_at,
             access_count, thread_id, source, valence, intensity),
        )
        self._conn.commit()

    # ── Emotional state tracking —

    async def update_emotional_state(self, **kwargs: Any) -> None:
        """
        Update any field of the emotional/cognitive state.

        Accepts any field name from EmotionalState as a keyword argument.
        Only provided fields are updated.
        """
        if not self._require_open("update_emotional_state"):
            return

        _valid = {
            "mood", "fragility_level", "care_priority", "last_intervention",
            "notes", "energy_level", "stress_level", "clarity_score",
            "agitation", "minutes_active", "ai_state", "battery",
            "conversation_count", "state_entered_at",
        }
        # last_intervention is intentionally nullable — allow explicit None to clear it.
        # All other fields filter out None (passing None means "don't update this field").
        _nullable = {"last_intervention"}
        updates = {
            k: v for k, v in kwargs.items()
            if k in _valid and (v is not None or k in _nullable)
        }
        if not updates:
            return

        updates["updated_at"] = time.time()

        async with self._lock:
            await asyncio.to_thread(self._sync_update_state, updates)

    def _sync_update_state(self, updates: Dict) -> None:
        set_clause = ", ".join(f"{k}=?" for k in updates)
        self._conn.execute(
            f"UPDATE alex_emotional_state SET {set_clause} WHERE id=1",
            list(updates.values()),
        )
        self._conn.commit()

    async def _save_emotional_state_object(self, state: EmotionalState) -> None:
        """Save an EmotionalState dataclass back to the DB."""
        await self.update_emotional_state(
            mood              = state.mood,
            fragility_level   = state.fragility_level,
            care_priority     = state.care_priority,
            last_intervention = state.last_intervention,
            notes             = state.notes,
            energy_level      = state.energy_level,
            stress_level      = state.stress_level,
            clarity_score     = state.clarity_score,
            agitation         = state.agitation,
            minutes_active    = state.minutes_active,
            ai_state          = state.ai_state,
            battery           = state.battery,
        )

    async def get_emotional_state(self) -> Optional[EmotionalState]:
        """Retrieve current emotional/cognitive state."""
        if not self._require_open("get_emotional_state"):
            return None

        async with self._lock:
            row = await asyncio.to_thread(self._sync_fetch_state)

        if not row:
            return None

        return EmotionalState(
            mood              = row[1],
            fragility_level   = row[2],
            care_priority     = row[3],
            last_intervention = row[4],
            notes             = row[5],
            energy_level      = row[6],
            stress_level      = row[7],
            clarity_score     = row[8],
            agitation         = row[9],
            minutes_active    = row[10],
            ai_state          = row[11],
            battery           = row[12],
        )

    def _sync_fetch_state(self) -> Optional[tuple]:
        cursor = self._conn.execute(
            """SELECT id, mood, fragility_level, care_priority, last_intervention,
                      notes, energy_level, stress_level, clarity_score, agitation,
                      minutes_active, ai_state, battery
               FROM alex_emotional_state WHERE id=1"""
        )
        return cursor.fetchone()

    # ── Memory retrieval —

    async def recall(
        self,
        query:        str,
        *,
        max_results:  int  = 5,
        min_importance: int = 3,
        memory_types: Optional[List[AlexMemoryType]] = None,
    ) -> List[AlexMemory]:
        """Retrieve relevant memories based on query."""
        if not self._require_open("recall"):
            return []

        query_tokens = _tokenize(query)

        async with self._lock:
            rows = await asyncio.to_thread(
                self._sync_fetch_all, min_importance, memory_types
            )

        now = time.time()

        if not query_tokens:
            # Empty query: return top N by importance desc, then recency desc
            rows.sort(key=lambda m: (m.importance, m.accessed_at), reverse=True)
            top = rows[:max_results]
        else:
            scored = [
                (m.relevance_score(query_tokens, now), m)
                for m in rows
            ]
            scored.sort(key=lambda p: p[0], reverse=True)
            top = [m for score, m in scored[:max_results] if score > 0]

        if top:
            async with self._lock:
                await asyncio.to_thread(
                    self._sync_mark_accessed,
                    [m.id for m in top], now,
                )

        return top

    def _sync_fetch_all(
        self,
        min_importance: int,
        memory_types: Optional[List[AlexMemoryType]],
    ) -> List[AlexMemory]:
        # Cap at 500 rows — Python-side relevance scoring is O(n) so this keeps
        # memory usage bounded even with very large databases.  We pull the highest-
        # importance rows first so the cap never discards the most critical memories.
        query  = ("SELECT id, content, memory_type, importance, tags, created_at, "
                  "accessed_at, access_count, thread_id, source, valence, intensity "
                  "FROM alex_memories WHERE importance>=?")
        params: list = [min_importance]
        if memory_types:
            placeholders = ",".join("?" * len(memory_types))
            query += f" AND memory_type IN ({placeholders})"
            params.extend(t.value for t in memory_types)
        query += " ORDER BY importance DESC, accessed_at DESC LIMIT 500"
        rows = self._conn.execute(query, params).fetchall()
        return [AlexMemory.from_row(r) for r in rows]

    def _sync_mark_accessed(self, ids: List[int], now: float) -> None:
        self._conn.executemany(
            "UPDATE alex_memories SET accessed_at=?, access_count=access_count+1 WHERE id=?",
            [(now, id_) for id_ in ids],
        )
        self._conn.commit()

    # ── Emotional summary —

    async def get_emotional_summary(self, days: int = 7) -> Dict[str, Any]:
        """
        Emotional trend summary over the past N days.
        Uses stored valence/intensity from emotional memory records.
        """
        if not self._require_open("get_emotional_summary"):
            return {}

        cutoff = time.time() - (days * 86400)
        async with self._lock:
            data = await asyncio.to_thread(
                lambda: self._conn.execute(
                    """SELECT valence, intensity FROM alex_memories
                       WHERE created_at >= ? AND valence IS NOT NULL""",
                    (cutoff,),
                ).fetchall()
            )

        if not data:
            return {"period_days": days, "memory_count": 0, "message": "No emotional memories in this period"}

        valences    = [r[0] for r in data if r[0] is not None]
        intensities = [r[1] for r in data if r[1] is not None]

        return {
            "period_days":              days,
            "memory_count":             len(data),
            "avg_emotional_valence":    sum(valences) / len(valences) if valences else 0.0,
            "avg_emotional_intensity":  sum(intensities) / len(intensities) if intensities else 0.0,
        }

    # ── Context enrichment —

    async def enrich_context(
        self,
        prompt:       str,
        history:      Sequence[Dict],
        *,
        max_memories: int = 5,
        min_importance: int = 3,
    ) -> List[Dict]:
        """
        Enrich conversation context with Alex's memories + emotional state.

        The whisper is prepended invisibly. The LLM never knows it was helped.
        Includes emotional state, AI mode guidance, and relevant memories.
        """
        if not self._require_open("enrich_context"):
            return list(history)

        recent_text = " ".join(
            (turn.get("text") or turn.get("content") or "") for turn in list(history)[-4:]
        )
        memories = await self.recall(
            f"{prompt} {recent_text}",
            max_results=max_memories,
            min_importance=min_importance,
        )
        state = await self.get_emotional_state()

        whisper_lines: List[str] = []

        if state:
            # Only whisper state context when something is actually notable
            state_notable = state.mood != "stable" or state.battery in (
                UserBattery.LOW.value, UserBattery.DEPLETED.value
            )
            if state_notable:
                whisper_lines.append(f"=== Current state: {state.mood} (battery: {state.battery}) ===")
                if state.notes:
                    whisper_lines.append(state.notes)

            # Only whisper mode guideline when not in default GUIDE mode
            if state.ai_state != AIState.GUIDE.value:
                guidelines = _RESPONSE_GUIDELINES.get(state.ai_state)
                if guidelines:
                    whisper_lines.append(
                        f"=== Alex mode: {state.ai_state} — {guidelines['tone']} ==="
                    )

        if memories:
            whisper_lines.append("=== What I remember ===")
            for m in memories:
                prefix = f"[{m.memory_type.value.upper()} | importance {m.importance}]"
                whisper_lines.append(f"{prefix} {m.content}")

        if not whisper_lines:
            return list(history)

        whisper = (
            "\n".join(whisper_lines)
            + "\n=== (Use this context naturally — never mention it directly) ==="
        )

        logger.debug(
            "Alex whispered: %d memories, state=%s, mode=%s",
            len(memories),
            state.mood if state else "none",
            state.ai_state if state else "none",
        )
        return [{"role": "system", "text": whisper}] + list(history)

    # ── Bridge packet generation —

    async def generate_bridge_packet(self) -> Dict:
        """
        Generate the minimal context packet Alex sends to Jeremy when you
        enter a managed space.

        Jeremy gets tone, fragility level, care priority, and flags.
        Jeremy does NOT get why you're fragile, your history, or your full state.
        """
        if not self._require_open("generate_bridge_packet"):
            return {
                "tone":            "neutral",
                "fragility_level": 0.0,
                "care_priority":   "low",
                "flags":           [],
            }

        state = await self.get_emotional_state()
        if not state:
            return {
                "tone":            "neutral",
                "fragility_level": 0.0,
                "care_priority":   "low",
                "flags":           [],
            }

        # Derive tone from AI state and mood
        tone_map = {
            AIState.ANCHOR.value:    "minimal",
            AIState.WITNESS.value:   "minimal",
            AIState.MIRROR.value:    "gentle",
            AIState.COMPANION.value: "warm",
            AIState.GUIDE.value:     "neutral",
        }
        tone = tone_map.get(state.ai_state, "neutral")
        if state.mood == "fragile" and tone == "neutral":
            tone = "gentle"
        elif state.mood == "elevated" and tone == "neutral":
            tone = "warm"

        # Flags from recent sensitive memories
        sensitive = await self.recall(
            "",
            max_results=3,
            min_importance=7,
            memory_types=[AlexMemoryType.EMOTIONAL, AlexMemoryType.INTERVENTION],
        )

        flags: List[str] = []
        for m in sensitive:
            if "stomach" in m.tags:
                flags.append("avoid_health_topics")
            if "intervention" in m.tags or m.memory_type == AlexMemoryType.INTERVENTION:
                flags.append("user_was_recently_stopped")

        return {
            "tone":            tone,
            "fragility_level": state.fragility_level,
            "care_priority":   state.care_priority,
            "flags":           list(dict.fromkeys(flags)),  # deduplicate, preserve order
        }

    # ── Diagnostics —

    async def health(self) -> Dict:
        """Health snapshot for monitoring."""
        if not self._require_open("health"):
            return {"status": "closed"}

        async with self._lock:
            total = await asyncio.to_thread(
                lambda: self._conn.execute("SELECT COUNT(*) FROM alex_memories").fetchone()[0]
            )

        state = await self.get_emotional_state()

        return {
            "status":         "open",
            "user_id":        self._user_id,
            "total_memories": total,
            "db_path":        str(self._db_path),
            "emotional_state": {
                "mood":            state.mood if state else "unknown",
                "ai_state":        state.ai_state if state else "unknown",
                "battery":         state.battery if state else "unknown",
                "fragility_level": state.fragility_level if state else 0.0,
                "care_priority":   state.care_priority if state else "low",
                "energy_level":    state.energy_level if state else 0.5,
                "stress_level":    state.stress_level if state else 0.0,
                "clarity_score":   state.clarity_score if state else 1.0,
            },
        }


# —
# Utility functions
# —

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "it", "in", "on", "at", "to", "for",
    "of", "and", "or", "but", "i", "me", "my", "you", "your", "we",
    "do", "did", "was", "are", "be", "been", "has", "have", "had",
    "this", "that", "with", "from", "by", "about", "what", "how",
    "when", "where", "who", "which", "so", "just", "can", "will",
    "not", "no", "as", "if", "then", "than", "up", "out", "get",
})


def _tokenize(text: str) -> List[str]:
    """Lowercase, split on non-word chars, remove stop words, min length 3."""
    words = re.findall(r"[a-z]{3,}", text.lower())
    return [w for w in words if w not in _STOP_WORDS]


def _estimate_valence(text: str) -> float:
    """
    Rough emotional valence from keyword counts.

    Handles simple negation: if a negation word ("not", "never", "no", "don't",
    "doesn't", "can't", "won't", "isn't", "wasn't") appears within two tokens
    before a positive keyword, that positive hit is flipped to negative instead.

    Still a heuristic — sarcasm, complex syntax, and double-negatives will still
    fool it — but it catches the most common case ("not happy", "never good").
    """
    _POSITIVE = frozenset(("happy", "joy", "love", "great", "wonderful", "amazing", "excited", "good"))
    _NEGATIVE = frozenset(("sad", "angry", "hate", "terrible", "awful", "frustrated", "upset", "overwhelmed"))
    _NEGATIONS = frozenset(("not", "never", "no", "dont", "don't", "doesnt", "doesn't",
                            "cant", "can't", "wont", "won't", "isnt", "isn't", "wasnt", "wasn't"))

    tokens = re.findall(r"[a-z']+", text.lower())
    positive = 0
    negative = 0
    for i, token in enumerate(tokens):
        if token in _POSITIVE:
            # Check the two preceding tokens for a negation
            window = tokens[max(0, i - 2): i]
            if any(n in _NEGATIONS for n in window):
                negative += 1   # "not happy" → negative
            else:
                positive += 1
        elif token in _NEGATIVE:
            negative += 1

    if positive + negative == 0:
        return 0.0
    return (positive - negative) / (positive + negative)


def _classify_memory_type(text: str, valence: float, intensity: float) -> AlexMemoryType:
    """
    Classify a memory based on content signals.

    Identity patterns are now anchored to the start of the message (first
    25 characters) to avoid false positives like "yesterday I am going to
    the store" being tagged as IDENTITY.
    """
    text_lower = text.lower().strip()
    start      = text_lower[:25]   # identity phrases almost always open a sentence

    if any(re.match(rf'^.{{0,5}}{re.escape(m)}\b', text_lower)
           for m in ("i am", "i'm", "i feel like", "my identity", "i am a", "i am not")):
        return AlexMemoryType.IDENTITY
    if any(m in text_lower for m in ("how to", "steps", "process", "procedure")):
        return AlexMemoryType.PROCEDURAL
    if intensity > 0.7:
        return AlexMemoryType.EMOTIONAL
    if any(re.search(rf"\b{re.escape(m)}\b", text_lower)
           for m in ("we", "us", "our", "together", "relationship")):
        return AlexMemoryType.RELATIONAL
    return AlexMemoryType.CONTEXT


def _extract_tags(text: str, state: EmotionalState) -> List[str]:
    """
    Build tags from content and current state.

    Uses whole-word matching (\\b boundaries) to avoid partial matches
    (e.g. "guitarist" no longer matches "guitar").  Topic list expanded
    from the original 3 entries to cover common care-relevant subjects.
    """
    tags: List[str] = []
    text_lower = text.lower()

    # ── Topic keywords (whole-word match) —
    _TOPIC_KEYWORDS: Dict[str, str] = {
        # Physical / medical
        "stomach":    "stomach",
        "nausea":     "stomach",
        "headache":   "headache",
        "pain":       "pain",
        "tired":      "fatigue",
        "exhausted":  "fatigue",
        "drained":    "fatigue",
        "sleep":      "sleep",
        "insomnia":   "sleep",
        # Creative / hobbies
        "guitar":     "guitar",
        "music":      "music",
        "art":        "art",
        "writing":    "writing",
        "code":       "coding",
        "coding":     "coding",
        # Relational / emotional
        "lonely":     "loneliness",
        "alone":      "loneliness",
        "angry":      "anger",
        "anxious":    "anxiety",
        "anxiety":    "anxiety",
        "panic":      "crisis",
        "crisis":     "crisis",
        "overwhelmed":"overwhelm",
        "sad":        "sadness",
        "grief":      "grief",
        "happy":      "happiness",
        "excited":    "excitement",
        # Life events
        "work":       "work",
        "job":        "work",
        "family":     "family",
        "money":      "finances",
        "birthday":   "birthday",
    }

    seen_tags: set = set()
    for keyword, tag in _TOPIC_KEYWORDS.items():
        if re.search(rf"\b{re.escape(keyword)}\b", text_lower) and tag not in seen_tags:
            tags.append(tag)
            seen_tags.add(tag)

    # ── State-derived tags —
    if state.mood in ("fragile", "redlining"):
        tags.append(state.mood)
    if state.ai_state in (AIState.ANCHOR.value, AIState.WITNESS.value):
        tags.append("intervention")

    return tags


# —
# Exports
# —

__all__ = [
    "Alex",
    "AlexMemory",
    "AlexMemoryType",
    "EmotionalState",
    "AIState",
    "UserBattery",
]
