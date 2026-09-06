"""
memory_ingestor.py — Context classification, scoring, and ingestion
==============================================================================
Rear View Foresight LLC · Feic Mo Chroí™
Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
All Rights Reserved

ENHANCED — 4-28-26 pass
────────────────────────
NEW  Deduplication gate     — fingerprint cache blocks near-duplicate blocks from being stored twice
NEW  Decay filter           — expired blocks (decay_hours > 0) are rejected before scoring
NEW  Confidence weighting   — importance score is dampened by block.confidence
NEW  Correction handling    — is_correction blocks bypass the noise floor and get a boost
NEW  Alex routing           — SYSTEM_STATE / ALEX_STATE blocks route to Alex's remember_moment
NEW  IngestionResult.skipped_reason   — richer rejection vocabulary
NEW  IngestionStats         — summary object returned from ingest_many()
NEW  MemoryIngestor.flush_fingerprints() — clear dedup cache (useful between sessions)
NEW  MemoryIngestor.stats   — running counters (accepted/rejected/deduplicated/expired)

The MemoryIngestor is the gatekeeper between raw context (ContextBlocks) and
the existing PubCast memory systems.

It does NOT replace any existing memory system. It sits in front of them:

    ContextBlock
        → check expiry   (decay_hours)
        → check dedup    (fingerprint cache)
        → classify kind  (if caller didn't specify precisely)
        → weight score   (importance × confidence)
        → filter noise   (trivial, too short, below threshold)
        → handle corrections (supersedes prior blocks)
        → route to the right existing system:
              Alex               ← SYSTEM_STATE / care layer (NEW)
              JeremyCricket      ← character-specific persistent memory
              UniversalMemorySystem ← in-session character memory banks
              memory_engine      ← room/session event log

Integration
-----------
    from modules.context_block import ContextBlock, ContextSource, ContextKind
    from modules.memory_ingestor import MemoryIngestor

    ingestor = MemoryIngestor(
        data_dir=Path("data"),
        memory_system=universal_memory_system_instance,  # optional
        cricket_registry={"jeremy": cricket_instance},   # optional
        alex=alex_instance,                               # optional (NEW)
    )

    result = await ingestor.ingest(block)
    # result.accepted        — was the block stored?
    # result.destination     — which system(s) received it?
    # result.importance      — final scored importance
    # result.skipped_reason  — why rejected (if not accepted)

    stats = await ingestor.ingest_many(blocks)
    # stats.accepted / stats.rejected / stats.deduplicated / stats.expired
"""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .context_block import ContextBlock, ContextKind, ContextSource

logger = logging.getLogger("pubcast.memory_ingestor")


# ────────────────────────────────────────────────────────────────────────────
# Ingestion result
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class IngestionResult:
    block_id:       str
    accepted:       bool
    destination:    List[str]         # which systems received the block
    importance:     float
    kind:           str
    skipped_reason: str = ""          # why rejected (empty if accepted)

    # back-compat alias
    @property
    def reason(self) -> str:
        return self.skipped_reason

    def __repr__(self) -> str:
        status = "ACCEPTED" if self.accepted else f"REJECTED({self.skipped_reason})"
        return (
            f"IngestionResult({status}, dest={self.destination}, "
            f"kind={self.kind}, importance={self.importance:.2f})"
        )


# ────────────────────────────────────────────────────────────────────────────
# Batch stats — returned from ingest_many()
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class IngestionStats:
    """Summary of a batch ingest_many() call."""
    total:          int = 0
    accepted:       int = 0
    rejected:       int = 0
    deduplicated:   int = 0    # rejected specifically due to fingerprint match
    expired:        int = 0    # rejected specifically due to decay_hours
    destinations:   Dict[str, int] = field(default_factory=dict)   # dest → count
    results:        List[IngestionResult] = field(default_factory=list)

    def record(self, result: IngestionResult) -> None:
        self.total += 1
        self.results.append(result)
        if result.accepted:
            self.accepted += 1
            for dest in result.destination:
                self.destinations[dest] = self.destinations.get(dest, 0) + 1
        else:
            self.rejected += 1
            if "duplicate" in result.skipped_reason:
                self.deduplicated += 1
            elif "expired" in result.skipped_reason:
                self.expired += 1

    def __repr__(self) -> str:
        return (
            f"IngestionStats(total={self.total}, accepted={self.accepted}, "
            f"rejected={self.rejected}, dedup={self.deduplicated}, "
            f"expired={self.expired}, dest={self.destinations})"
        )


# ────────────────────────────────────────────────────────────────────────────
# Scoring — importance heuristics
# ────────────────────────────────────────────────────────────────────────────

_HIGH_SIGNAL = frozenset({
    "i prefer", "i like", "i don't like", "i hate", "i love",
    "please don't", "always", "never", "my favorite",
    "i am", "i'm a", "my name is", "i work", "my job",
    "i feel", "overwhelmed", "anxious", "exhausted", "struggling",
    "panic", "crisis", "fragile", "not okay",
    "means a lot", "important to me", "i care", "remember when",
    "please remember", "don't forget", "make sure", "always remember",
    "note that", "important:",
})

_NOISE_PATTERNS = frozenset({
    "ok", "okay", "k", "lol", "haha", "heh", "yeah", "yep", "nope",
    "sure", "got it", "thanks", "thank you", "thx", "ty", "np",
    "sounds good", "cool", "nice", "great", "awesome", "perfect",
})


def _score_importance(block: ContextBlock) -> float:
    """
    Produce a 0.0→1.0 importance score, dampened by block.confidence.

    Starts from caller's hint and adjusts based on content signals.
    Corrections always score at least 0.65 — they exist to fix something.
    Confidence < 1.0 proportionally dampens the final score:
        final = raw_score × (0.5 + 0.5 × confidence)
    So a block with confidence=0.5 can score at most 0.75 of its raw value.
    """
    score = block.importance

    # Correction boost — overrides the caller hint floor
    if block.is_correction:
        score = max(score, 0.65)

    text = block.content.lower().strip()

    # Source-based adjustments
    if block.source in (ContextSource.CODE_COLLECTOR, ContextSource.PERSONAL_AI):
        score = max(score, 0.6)
    if block.source == ContextSource.MANUAL:
        score = max(score, 0.7)
    if block.source == ContextSource.ALEX_STATE:
        score = max(score, 0.4)   # state snapshots are supporting context

    # Kind-based adjustments
    if block.kind in (ContextKind.PREFERENCE, ContextKind.INSTRUCTION):
        score = max(score, 0.7)
    if block.kind == ContextKind.EMOTIONAL:
        score = max(score, 0.65)
    if block.kind == ContextKind.SYSTEM_STATE:
        score = max(score, 0.35)

    # Content signals
    for signal in _HIGH_SIGNAL:
        if signal in text:
            score = min(1.0, score + 0.15)
            break  # one boost per block

    # Length penalty
    if len(text) < 15:
        score = max(0.0, score - 0.2)

    raw = round(min(1.0, max(0.0, score)), 3)

    # Confidence dampening — uncertain blocks can't score as high
    confidence_factor = 0.5 + 0.5 * max(0.0, min(1.0, block.confidence))
    return round(raw * confidence_factor, 3)


def _is_noise(block: ContextBlock, min_importance: float = 0.2) -> tuple[bool, str]:
    """Return (is_noise, reason). Corrections always pass."""
    if block.is_correction:
        return False, ""    # corrections are never filtered as noise

    if block.is_noise:
        return True, "caller flagged as noise"

    text = block.content.strip()
    if not text:
        return True, "empty content"

    if len(text) < 5:
        return True, "too short"

    if text.lower() in _NOISE_PATTERNS:
        return True, "trivial response"

    scored = _score_importance(block)
    if scored < min_importance:
        return True, f"importance {scored:.2f} < threshold {min_importance:.2f}"

    return False, ""


def _classify_kind(block: ContextBlock) -> ContextKind:
    """
    Refine ContextKind if caller used CONVERSATION (the generic fallback).
    Does not override explicit kinds.
    """
    if block.kind != ContextKind.CONVERSATION:
        return block.kind

    text = block.content.lower()

    if any(p in text for p in ("i prefer", "i like", "i don't like", "my favorite", "please don't")):
        return ContextKind.PREFERENCE

    if any(p in text for p in ("please remember", "don't forget", "make sure", "always", "note that")):
        return ContextKind.INSTRUCTION

    if any(p in text for p in ("i feel", "overwhelmed", "anxious", "exhausted", "panic", "fragile")):
        return ContextKind.EMOTIONAL

    if re.search(r"\b(we|us|our|together|relationship)\b", text):
        return ContextKind.RELATIONAL

    if re.match(r"^.{0,5}(i am|i'm|my name|i work)", text):
        return ContextKind.FACT

    return ContextKind.CONVERSATION


# ────────────────────────────────────────────────────────────────────────────
# MemoryIngestor
# ────────────────────────────────────────────────────────────────────────────

class MemoryIngestor:
    """
    Accepts ContextBlocks, scores them, filters noise, and routes accepted
    blocks to the appropriate existing PubCast memory system.

    Parameters
    ----------
    data_dir
        Root data directory — passed to memory_engine.record_event().
    memory_system
        Optional UniversalMemorySystem instance for in-session character banks.
    cricket_registry
        Optional dict of {character_id: JeremyCricket} for persistent
        per-character memory.
    alex
        Optional Alex instance — receives SYSTEM_STATE and EMOTIONAL blocks. (NEW)
    min_importance
        Blocks scoring below this are rejected as noise. Default 0.2.
    project_id
        Default project ID used when the block doesn't specify one.
    dedup_window
        Max number of fingerprints held in the rolling dedup cache. (NEW)
        Older fingerprints age out automatically. Default 500.
    """

    def __init__(
        self,
        data_dir: Path,
        *,
        memory_system:    Any = None,
        cricket_registry: Optional[Dict[str, Any]] = None,
        alex:             Any = None,
        min_importance:   float = 0.2,
        project_id:       str = "default",
        dedup_window:     int = 500,
    ) -> None:
        self._data_dir         = Path(data_dir)
        self._memory_system    = memory_system
        self._cricket_registry = cricket_registry or {}
        self._alex             = alex
        self._min_importance   = min_importance
        self._project_id       = project_id

        # Deduplication: rolling cache of fingerprints
        # deque with maxlen evicts oldest automatically
        self._seen_fingerprints: Set[str] = set()
        self._fingerprint_order: deque = deque(maxlen=dedup_window)

        # Running stats counters
        self._stats = {"accepted": 0, "rejected": 0, "deduplicated": 0, "expired": 0}

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, int]:
        """Running lifetime counters for this ingestor instance."""
        return dict(self._stats)

    def flush_fingerprints(self) -> None:
        """NEW: Clear the dedup cache. Call between sessions if needed."""
        self._seen_fingerprints.clear()
        self._fingerprint_order.clear()
        logger.info("Ingestor: fingerprint cache cleared")

    async def ingest(self, block: ContextBlock) -> IngestionResult:
        """
        Main entry point. Process one ContextBlock.

        Gate order:
          1. Empty check
          2. Expiry check    (decay_hours)
          3. Dedup check     (fingerprint)
          4. Classify kind
          5. Score importance
          6. Noise filter
          7. Route to systems
        """
        if block.is_empty():
            return self._reject(block, "empty content", 0.0, block.kind.value, "expired" if False else "noise")

        # 2. Expiry gate — NEW
        if block.is_expired():
            self._stats["expired"] += 1
            self._stats["rejected"] += 1
            logger.debug("Ingestor: block %s expired (decay_hours=%.1f)", block.block_id[:8], block.decay_hours)
            return self._reject(block, "expired", 0.0, block.kind.value, "expired")

        # 3. Dedup gate — NEW (corrections always bypass)
        if not block.is_correction:
            fp = block.fingerprint()
            if fp in self._seen_fingerprints:
                self._stats["deduplicated"] += 1
                self._stats["rejected"] += 1
                logger.debug("Ingestor: block %s deduplicated (fp=%s)", block.block_id[:8], fp)
                return self._reject(block, "duplicate fingerprint", 0.0, block.kind.value, "duplicate")

        # 4. Classify kind
        kind = _classify_kind(block)

        # 5. Score importance (confidence-weighted)
        importance = _score_importance(block)

        # 6. Noise filter
        noisy, reason = _is_noise(block, self._min_importance)
        if noisy:
            self._stats["rejected"] += 1
            logger.debug("Ingestor: rejected block %s — %s", block.block_id[:8], reason)
            return self._reject(block, reason, importance, kind.value, "noise")

        # Register fingerprint AFTER passing all gates
        fp = block.fingerprint()
        if fp not in self._seen_fingerprints:
            if len(self._fingerprint_order) == self._fingerprint_order.maxlen:
                # Evict oldest
                oldest = self._fingerprint_order[0]
                self._seen_fingerprints.discard(oldest)
            self._seen_fingerprints.add(fp)
            self._fingerprint_order.append(fp)

        # 7. Route to systems
        destinations: List[str] = []

        # A. Alex — receives EMOTIONAL and SYSTEM_STATE blocks (NEW)
        if self._alex is not None and kind in (ContextKind.EMOTIONAL, ContextKind.SYSTEM_STATE):
            try:
                await self._write_to_alex(block, kind, importance)
                destinations.append("alex")
            except Exception:
                logger.exception("Ingestor: Alex write failed for block %s", block.block_id[:8])

        # B. JeremyCricket
        cricket = self._resolve_cricket(block)
        if cricket is not None:
            try:
                await self._write_to_cricket(cricket, block, kind, importance)
                destinations.append("jeremy_cricket")
            except Exception:
                logger.exception("Ingestor: JeremyCricket write failed for block %s", block.block_id[:8])

        # C. UniversalMemorySystem
        if self._memory_system is not None and block.author_id:
            try:
                self._write_to_universal(block, kind, importance)
                destinations.append("universal_memory")
            except Exception:
                logger.exception("Ingestor: UniversalMemory write failed for block %s", block.block_id[:8])

        # D. memory_engine — room/session event log
        if block.session_id and kind != ContextKind.CODE:
            try:
                self._write_to_engine(block, kind, importance)
                destinations.append("memory_engine")
            except Exception:
                logger.exception("Ingestor: memory_engine write failed for block %s", block.block_id[:8])

        if not destinations:
            logger.info(
                "Ingestor: block %s accepted (importance=%.2f kind=%s) but no memory destination configured",
                block.block_id[:8], importance, kind.value,
            )

        self._stats["accepted"] += 1
        logger.info(
            "Ingestor: block %s → %s (importance=%.2f confidence=%.2f kind=%s source=%s%s)",
            block.block_id[:8], destinations or ["none"], importance,
            block.confidence, kind.value, block.source.value,
            " [CORRECTION]" if block.is_correction else "",
        )

        return IngestionResult(
            block_id    = block.block_id,
            accepted    = True,
            destination = destinations,
            importance  = importance,
            kind        = kind.value,
        )

    async def ingest_many(self, blocks: List[ContextBlock]) -> IngestionStats:
        """
        Ingest multiple blocks. Returns an IngestionStats summary. (ENHANCED)

        Previously returned List[IngestionResult] — now returns IngestionStats
        which contains .results for the full list if needed.
        """
        stats = IngestionStats()
        for block in blocks:
            result = await self.ingest(block)
            stats.record(result)
        return stats

    def register_cricket(self, character_id: str, cricket: Any) -> None:
        """Register a JeremyCricket instance for a character."""
        self._cricket_registry[character_id] = cricket

    def register_alex(self, alex: Any) -> None:
        """NEW: Register an Alex instance to receive emotional and state blocks."""
        self._alex = alex

    # ── Internal writers ──────────────────────────────────────────────────────

    def _resolve_cricket(self, block: ContextBlock) -> Optional[Any]:
        """Find a JeremyCricket for this block's author, if registered."""
        if not block.author_id:
            return None
        return self._cricket_registry.get(block.author_id)

    async def _write_to_alex(
        self,
        block: ContextBlock,
        kind: ContextKind,
        importance: float,
    ) -> None:
        """
        NEW: Write EMOTIONAL or SYSTEM_STATE blocks to Alex's remember_moment().

        Alex implementations vary across local PubCast builds. Prefer the
        newer remember_moment() API when present, and fall back to the current
        AlexCore memory.store() API so this public module does not require the
        private alex_memory.py implementation.
        """
        remember = getattr(self._alex, "remember_moment", None)
        if callable(remember):
            from .alex_core import MemoryType

            kind_to_alex = {
                ContextKind.EMOTIONAL:    MemoryType.EMOTIONAL,
                ContextKind.SYSTEM_STATE: MemoryType.CONTEXT,
                ContextKind.RELATIONAL:   MemoryType.RELATIONSHIP,
                ContextKind.PREFERENCE:   MemoryType.PREFERENCE,
                ContextKind.FACT:         MemoryType.FACTUAL,
                ContextKind.INSTRUCTION:  MemoryType.PROCEDURAL,
            }
            mem_type = kind_to_alex.get(kind, MemoryType.CONTEXT)
            try:
                from .alex_memory import AlexMemoryType

                private_kind_to_alex = {
                    ContextKind.EMOTIONAL:    AlexMemoryType.EMOTIONAL,
                    ContextKind.SYSTEM_STATE: AlexMemoryType.CONTEXT,
                    ContextKind.RELATIONAL:   AlexMemoryType.RELATIONAL,
                    ContextKind.PREFERENCE:   AlexMemoryType.PREFERENCE,
                    ContextKind.FACT:         AlexMemoryType.FACTUAL,
                    ContextKind.INSTRUCTION:  AlexMemoryType.PROCEDURAL,
                }
                mem_type = private_kind_to_alex.get(kind, AlexMemoryType.CONTEXT)
            except Exception:
                pass

            alex_imp = max(1, min(9, round(importance * 9)))
            await remember(
                block.truncated(800),
                memory_type = mem_type,
                importance  = alex_imp,
                tags        = block.tags,
                source      = block.source.value,
            )
            return

        memory = getattr(self._alex, "memory", None)
        store = getattr(memory, "store", None)
        if callable(store):
            emotional_state = {
                "valence": -0.2 if kind == ContextKind.EMOTIONAL else 0.0,
                "intensity": max(0.05, min(1.0, importance)),
            }
            store(block.truncated(800), emotional_state)
            return

        raise AttributeError("Registered Alex instance has no compatible memory writer")

    async def _write_to_cricket(
        self,
        cricket: Any,
        block: ContextBlock,
        kind: ContextKind,
        importance: float,
    ) -> None:
        """Write to JeremyCricket using its existing remember() API."""
        cricket_importance = max(1, min(10, round(importance * 10)))

        _KIND_TO_CRICKET = {
            ContextKind.FACT:         "fact",
            ContextKind.EVENT:        "event",
            ContextKind.PREFERENCE:   "preference",
            ContextKind.INSTRUCTION:  "instruction",
            ContextKind.EMOTIONAL:    "emotion",
            ContextKind.RELATIONAL:   "relationship",
            ContextKind.CODE:         "fact",
            ContextKind.CONVERSATION: "fact",
            ContextKind.SYSTEM_STATE: "fact",
        }
        memory_type_str = _KIND_TO_CRICKET.get(kind, "fact")

        await cricket.remember(
            block.truncated(800),
            memory_type = memory_type_str,
            importance  = cricket_importance,
            tags        = block.tags,
            source      = block.source.value,
        )

    def _write_to_universal(
        self,
        block: ContextBlock,
        kind: ContextKind,
        importance: float,
    ) -> None:
        """Write to UniversalMemorySystem using its existing add() API."""
        from .universal_memory_system import MemoryEntry, MemoryType

        _KIND_TO_UMS = {
            ContextKind.FACT:         MemoryType.FACT,
            ContextKind.EVENT:        MemoryType.EPISODIC,
            ContextKind.PREFERENCE:   MemoryType.PREFERENCE,
            ContextKind.INSTRUCTION:  MemoryType.INSTRUCTION,
            ContextKind.EMOTIONAL:    MemoryType.EMOTIONAL,
            ContextKind.RELATIONAL:   MemoryType.RELATIONSHIP,
            ContextKind.CODE:         MemoryType.FACT,
            ContextKind.CONVERSATION: MemoryType.EPISODIC,
            ContextKind.SYSTEM_STATE: MemoryType.FACT,
        }
        mem_type = _KIND_TO_UMS.get(kind, MemoryType.FACT)

        entry = MemoryEntry(
            content     = block.truncated(800),
            memory_type = mem_type,
            importance  = importance,
            tags        = block.tags,
            source      = block.source.value,
        )
        bank = self._memory_system.get_or_create_bank(block.author_id)
        bank.add(entry)

    def _write_to_engine(
        self,
        block: ContextBlock,
        kind: ContextKind,
        importance: float,
    ) -> None:
        """Write to memory_engine event log using its existing record_event() API."""
        from . import memory_engine

        memory_engine.record_event(
            self._data_dir,
            session_id  = block.session_id or "unknown",
            project_id  = block.project_id or self._project_id,
            user_id     = block.author_id or "system",
            room_id     = block.room_id or "unknown",
            event_type  = f"context.{kind.value}",
            summary     = block.truncated(300),
            mood_trace  = "",
            payload     = {
                "block_id":        block.block_id,
                "source":          block.source.value,
                "kind":            kind.value,
                "importance":      importance,
                "confidence":      block.confidence,
                "tags":            block.tags,
                "is_correction":   block.is_correction,
                "parent_block_id": block.parent_block_id,
            },
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _reject(
        block: ContextBlock,
        reason: str,
        importance: float,
        kind: str,
        category: str = "noise",
    ) -> IngestionResult:
        return IngestionResult(
            block_id       = block.block_id,
            accepted       = False,
            destination    = [],
            importance     = importance,
            kind           = kind,
            skipped_reason = reason,
        )
