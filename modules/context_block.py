"""
context_block.py — Universal context capture object for PubCast AI
==============================================================================
Rear View Foresight LLC · Feic Mo Chroí™
Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
All Rights Reserved

ENHANCED — 4-28-26 pass
────────────────────────
NEW  confidence field        — how certain the caller is about this content
NEW  decay_hours field       — how long this block should remain relevant (0 = forever)
NEW  parent_block_id         — lineage tracking: which block spawned this one
NEW  is_correction flag      — marks a block that corrects/supersedes a prior block
NEW  ContextBlock.supersedes()  — returns the block_id this one replaces (from raw_payload)
NEW  ContextBlock.is_expired()  — True if decay_hours set and block has aged out
NEW  ContextBlock.fingerprint() — stable hash for near-duplicate detection
NEW  ContextBlock.similarity()  — rough content similarity ratio to another block (no deps)
NEW  ContextBlock.merge()       — merge two related blocks into one enriched block
NEW  batch_from_chat_turns()    — factory: list[str] → list[ContextBlock] in one call
NEW  from_alex_state()          — factory: build a ContextBlock from Alex's EmotionalState dict
NEW  ContextKind.SYSTEM_STATE   — new kind for Alex/system internal state snapshots

A ContextBlock is the standard input unit for the memory ingestion pipeline.
Everything that enters the memory system — chat turns, Code Collector payloads,
room events, user facts, personal AI contributions, Alex state snapshots —
arrives as a ContextBlock.

Design principles
-----------------
- Source-agnostic: PubCast runtime, Code Collector, external/personal AI, CLI
- Type-tagged: fact, event, preference, instruction, emotional, relational, code, system_state
- Provenance-preserving: origin, author, session, room always travel with the data
- Lineage-aware: blocks know what spawned them and what they supersede
- Decay-aware: ephemeral context expires automatically
- Dedup-ready: fingerprint() lets MemoryIngestor skip near-duplicates cheaply
- Local-first: no cloud requirement, no mandatory vector index
- Model-agnostic: suitable for Anthropic, OpenAI, Gemma/Ollama, any adapter
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence


# ────────────────────────────────────────────────────────────────────────────
# ContextSource — where did this context come from?
# ────────────────────────────────────────────────────────────────────────────

class ContextSource(str, Enum):
    CHAT_TURN      = "chat_turn"       # A message in a PubCast room or session
    CODE_COLLECTOR = "code_collector"  # Code Collector payload
    ROOM_EVENT     = "room_event"      # PubCast room/session event
    USER_FILE      = "user_file"       # User-uploaded file or document
    PERSONAL_AI    = "personal_ai"     # Contribution from a user-owned AI
    SYSTEM         = "system"          # Internal system observation
    MANUAL         = "manual"          # Manually authored fact or note
    ALEX_STATE     = "alex_state"      # Snapshot of Alex's internal emotional state


# ────────────────────────────────────────────────────────────────────────────
# ContextKind — what type of information is this?
# ────────────────────────────────────────────────────────────────────────────

class ContextKind(str, Enum):
    FACT         = "fact"
    EVENT        = "event"
    PREFERENCE   = "preference"
    INSTRUCTION  = "instruction"
    EMOTIONAL    = "emotional"
    RELATIONAL   = "relational"
    CODE         = "code"
    CONVERSATION = "conversation"
    SYSTEM_STATE = "system_state"   # NEW — Alex/system internal state snapshots


# ────────────────────────────────────────────────────────────────────────────
# ContextBlock — the universal context capture unit
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class ContextBlock:
    """
    One unit of captured context.

    The ingestion pipeline receives these and decides what to write into
    the existing PubCast memory systems (UniversalMemorySystem, JeremyCricket,
    memory_engine, Alex).
    """

    # Required identity
    block_id:   str             # Unique ID — auto-generated if not supplied
    content:    str             # The actual text / payload content
    source:     ContextSource   # Where did this come from?
    kind:       ContextKind     # What type of information is this?

    # Provenance — always travel with the block
    author_id:  Optional[str]   # user_id, character_id, or None for system
    session_id: Optional[str]   # PubCast session this came from
    room_id:    Optional[str]   # PubCast room this came from
    project_id: str             # PubCast project / tenant

    # Scoring hints (may be overridden by MemoryIngestor)
    importance:     float = 0.5    # 0.0 → 1.0 — caller hint, ingestor may adjust
    confidence:     float = 1.0    # NEW: 0.0 → 1.0 — how certain is the caller about this content?
    is_noise:       bool  = False  # Caller hint: skip storage if True
    tags:           List[str] = field(default_factory=list)

    # Lineage — NEW
    parent_block_id: Optional[str] = None   # which block spawned this one
    is_correction:   bool = False            # True → this supersedes a prior block

    # Temporal decay — NEW
    # 0 = never expires. Set to e.g. 1.0 for a 1-hour ephemeral context hint.
    decay_hours: float = 0.0

    # Raw payload — original data before text extraction, for traceability
    raw_payload:    Dict[str, Any] = field(default_factory=dict)

    # Timestamps
    captured_at:    float = field(default_factory=time.time)

    # ── Factories ─────────────────────────────────────────────────────────────

    @classmethod
    def new(
        cls,
        content: str,
        source: ContextSource,
        kind: ContextKind,
        *,
        author_id:       Optional[str] = None,
        session_id:      Optional[str] = None,
        room_id:         Optional[str] = None,
        project_id:      str = "default",
        importance:      float = 0.5,
        confidence:      float = 1.0,
        tags:            Optional[List[str]] = None,
        raw_payload:     Optional[Dict[str, Any]] = None,
        parent_block_id: Optional[str] = None,
        is_correction:   bool = False,
        decay_hours:     float = 0.0,
    ) -> "ContextBlock":
        return cls(
            block_id        = uuid.uuid4().hex[:16],
            content         = content,
            source          = source,
            kind            = kind,
            author_id       = author_id,
            session_id      = session_id,
            room_id         = room_id,
            project_id      = project_id,
            importance      = importance,
            confidence      = confidence,
            tags            = tags or [],
            raw_payload     = raw_payload or {},
            parent_block_id = parent_block_id,
            is_correction   = is_correction,
            decay_hours     = decay_hours,
        )

    @classmethod
    def from_chat_turn(
        cls,
        text: str,
        *,
        author_id:  str,
        session_id: str,
        room_id:    Optional[str] = None,
        project_id: str = "default",
        importance: float = 0.5,
        decay_hours: float = 0.0,
    ) -> "ContextBlock":
        """Convenience factory for a standard chat message."""
        return cls.new(
            content     = text,
            source      = ContextSource.CHAT_TURN,
            kind        = ContextKind.CONVERSATION,
            author_id   = author_id,
            session_id  = session_id,
            room_id     = room_id,
            project_id  = project_id,
            importance  = importance,
            decay_hours = decay_hours,
        )

    @classmethod
    def batch_from_chat_turns(
        cls,
        turns: Sequence[str],
        *,
        author_id:  str,
        session_id: str,
        room_id:    Optional[str] = None,
        project_id: str = "default",
        importance: float = 0.5,
    ) -> List["ContextBlock"]:
        """NEW: Convert a list of chat message strings into ContextBlocks in one call."""
        return [
            cls.from_chat_turn(
                text,
                author_id  = author_id,
                session_id = session_id,
                room_id    = room_id,
                project_id = project_id,
                importance = importance,
            )
            for text in turns
            if text and text.strip()
        ]

    @classmethod
    def from_code_collector(cls, payload: Dict[str, Any]) -> "ContextBlock":
        """
        Convert a Code Collector payload into a ContextBlock.

        The Code Collector payload is already a general context container —
        this extracts the text summary and preserves the full payload for
        provenance.
        """
        content = (
            payload.get("summary")
            or payload.get("description")
            or payload.get("content")
            or str(payload)[:2000]
        )
        tags = payload.get("tags") or []
        if payload.get("language"):
            tags.append(payload["language"])

        return cls.new(
            content    = content,
            source     = ContextSource.CODE_COLLECTOR,
            kind       = ContextKind.CODE,
            author_id  = payload.get("author_id") or payload.get("user_id"),
            session_id = payload.get("session_id"),
            room_id    = payload.get("room_id"),
            project_id = payload.get("project_id", "default"),
            importance = float(payload.get("importance", 0.6)),
            tags       = tags,
            raw_payload= payload,
        )

    @classmethod
    def from_room_event(cls, event: Dict[str, Any]) -> "ContextBlock":
        """Convert a memory_engine event dict into a ContextBlock."""
        return cls.new(
            content    = event.get("summary", ""),
            source     = ContextSource.ROOM_EVENT,
            kind       = ContextKind.EVENT,
            author_id  = event.get("user_id"),
            session_id = event.get("session_id"),
            room_id    = event.get("room_id"),
            project_id = event.get("project_id", "default"),
            importance = 0.5,
            raw_payload= event,
        )

    @classmethod
    def from_personal_ai(
        cls,
        content: str,
        kind: ContextKind,
        *,
        author_id:  str,
        session_id: Optional[str] = None,
        project_id: str = "default",
        importance: float = 0.5,
        confidence: float = 0.8,   # personal AIs slightly lower confidence by default
        tags: Optional[List[str]] = None,
    ) -> "ContextBlock":
        """Context contributed by a user-owned AI (Gemma, Ollama, etc.)."""
        return cls.new(
            content    = content,
            source     = ContextSource.PERSONAL_AI,
            kind       = kind,
            author_id  = author_id,
            session_id = session_id,
            project_id = project_id,
            importance = importance,
            confidence = confidence,
            tags       = tags,
        )

    @classmethod
    def from_alex_state(
        cls,
        state_dict: Dict[str, Any],
        *,
        author_id:  str,
        session_id: Optional[str] = None,
        project_id: str = "default",
    ) -> "ContextBlock":
        """
        NEW: Build a SYSTEM_STATE ContextBlock from Alex's process_message() result dict.

        This lets Alex's current emotional/cognitive state flow into the
        MemoryIngestor pipeline the same way any other context does —
        useful for cross-system logging, Jeremy bridge priming, and debugging.

        Usage:
            result = await alex.process_message(text)
            block  = ContextBlock.from_alex_state(result, author_id="josie", session_id=sess_id)
            await ingestor.ingest(block)
        """
        summary = (
            f"[Alex state] mode={state_dict.get('ai_state','?')} "
            f"battery={state_dict.get('battery','?')} "
            f"anchor={'YES' if state_dict.get('anchor_message') else 'no'}"
        )
        return cls.new(
            content     = summary,
            source      = ContextSource.ALEX_STATE,
            kind        = ContextKind.SYSTEM_STATE,
            author_id   = author_id,
            session_id  = session_id,
            project_id  = project_id,
            importance  = 0.4,        # state snapshots are supporting context, not primary
            confidence  = 1.0,
            decay_hours = 4.0,        # state snapshots expire after 4 hours
            raw_payload = state_dict,
        )

    # ── Lineage helpers ───────────────────────────────────────────────────────

    def supersedes(self) -> Optional[str]:
        """
        NEW: Return the block_id that this block replaces, if any.

        Callers signal this by including "supersedes_block_id" in raw_payload,
        or by setting is_correction=True and parent_block_id.
        """
        return (
            self.raw_payload.get("supersedes_block_id")
            or (self.parent_block_id if self.is_correction else None)
        )

    def correction_of(self, original: "ContextBlock") -> "ContextBlock":
        """
        NEW: Factory — return a corrected version of `original` with this block's content.

        Usage:
            corrected = new_block.correction_of(old_block)
            await ingestor.ingest(corrected)
        """
        return ContextBlock.new(
            content         = self.content,
            source          = self.source,
            kind            = self.kind,
            author_id       = self.author_id,
            session_id      = self.session_id,
            room_id         = self.room_id,
            project_id      = self.project_id,
            importance      = max(self.importance, original.importance),
            confidence      = self.confidence,
            tags            = list(set(self.tags + original.tags)),
            parent_block_id = original.block_id,
            is_correction   = True,
            raw_payload     = {**original.raw_payload, **self.raw_payload,
                               "supersedes_block_id": original.block_id},
        )

    # ── Temporal decay ────────────────────────────────────────────────────────

    def is_expired(self, now: Optional[float] = None) -> bool:
        """
        NEW: Return True if this block has aged past its decay_hours window.

        A block with decay_hours=0 never expires.
        """
        if self.decay_hours <= 0:
            return False
        age_hours = ((now or time.time()) - self.captured_at) / 3600.0
        return age_hours > self.decay_hours

    # ── Deduplication ─────────────────────────────────────────────────────────

    def fingerprint(self) -> str:
        """
        NEW: Stable 12-char hash of (author_id, kind, normalized content).

        Used by MemoryIngestor to detect near-duplicate blocks before storage.
        Two blocks with the same fingerprint carry the same semantic signal.
        Case and whitespace are normalized; punctuation is stripped.

        This is intentionally cheap — no embeddings, no NLP. It catches
        exact or near-exact resubmissions, not semantic similarity.
        """
        import re
        normalized = re.sub(r"[^a-z0-9 ]", "", self.content.lower().strip())
        normalized = " ".join(normalized.split())   # collapse whitespace
        key = f"{self.author_id}|{self.kind.value}|{normalized}"
        return hashlib.sha256(key.encode()).hexdigest()[:12]

    def similarity(self, other: "ContextBlock") -> float:
        """
        NEW: Rough word-overlap similarity ratio between this block and another.

        Returns 0.0 (no overlap) → 1.0 (identical vocabulary).
        No external dependencies — purely set intersection on token bags.

        Use this as a fast pre-filter before any expensive semantic comparison.
        """
        import re
        def _tokens(text: str):
            return set(re.findall(r"[a-z]{3,}", text.lower()))

        a = _tokens(self.content)
        b = _tokens(other.content)
        if not a or not b:
            return 0.0
        return len(a & b) / max(len(a), len(b))

    # ── Block merging ─────────────────────────────────────────────────────────

    @classmethod
    def merge(
        cls,
        primary: "ContextBlock",
        secondary: "ContextBlock",
        *,
        separator: str = " | ",
    ) -> "ContextBlock":
        """
        NEW: Merge two related blocks into one enriched block.

        The primary block's provenance wins. Content is concatenated.
        Importance and confidence take the max. Tags are unioned.

        Useful when a Code Collector payload and a chat turn describe the
        same moment and you want one memory entry, not two.
        """
        merged_content = primary.content.rstrip() + separator + secondary.content.strip()
        return cls.new(
            content         = merged_content[:1600],    # hard cap
            source          = primary.source,
            kind            = primary.kind,
            author_id       = primary.author_id,
            session_id      = primary.session_id,
            room_id         = primary.room_id,
            project_id      = primary.project_id,
            importance      = max(primary.importance, secondary.importance),
            confidence      = max(primary.confidence, secondary.confidence),
            tags            = list(set(primary.tags + secondary.tags)),
            parent_block_id = primary.block_id,
            raw_payload     = {
                "merged_from": [primary.block_id, secondary.block_id],
                **primary.raw_payload,
            },
        )

    # ── Utilities ─────────────────────────────────────────────────────────────

    def is_empty(self) -> bool:
        return not self.content or not self.content.strip()

    def truncated(self, max_chars: int = 800) -> str:
        """Return content truncated to max_chars for storage."""
        return self.content[:max_chars]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_id":        self.block_id,
            "content":         self.content,
            "source":          self.source.value,
            "kind":            self.kind.value,
            "author_id":       self.author_id,
            "session_id":      self.session_id,
            "room_id":         self.room_id,
            "project_id":      self.project_id,
            "importance":      self.importance,
            "confidence":      self.confidence,
            "is_noise":        self.is_noise,
            "tags":            self.tags,
            "parent_block_id": self.parent_block_id,
            "is_correction":   self.is_correction,
            "decay_hours":     self.decay_hours,
            "is_expired":      self.is_expired(),
            "fingerprint":     self.fingerprint(),
            "captured_at":     self.captured_at,
        }

    def __repr__(self) -> str:
        preview = self.content[:60].replace("\n", " ")
        expired = " EXPIRED" if self.is_expired() else ""
        correction = " CORRECTION" if self.is_correction else ""
        return (
            f"ContextBlock(id={self.block_id[:8]}, source={self.source.value}, "
            f"kind={self.kind.value}, author={self.author_id!r}, "
            f"importance={self.importance:.2f}, confidence={self.confidence:.2f}, "
            f"content={preview!r}{expired}{correction})"
        )
