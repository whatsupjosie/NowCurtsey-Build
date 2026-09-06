"""
universal_memory_system.py — Shared character memory for PubCast AI
==============================================================================
Rear View Foresight LLC · Feic Mo Chroí™

Provides the per-character memory banks that RoomConductor (Jeremy Cricket)
uses to remember what each character knows, feels, and has experienced.

Interface contract (consumed by room_conductor.py):
    - UniversalMemorySystem._banks       : Dict[str, CharacterMemoryBank]
    - UniversalMemorySystem._profiles    : Dict[str, CharacterProfile]
    - UniversalMemorySystem.get_or_create_bank(char_id) -> CharacterMemoryBank
    - CharacterMemoryBank.add(entry: MemoryEntry)
    - CharacterMemoryBank.search(query: str, limit: int) -> List[MemoryEntry]
    - MemoryEntry.content       : str
    - MemoryEntry.memory_type   : MemoryType
    - MemoryEntry.importance    : float
    - MemoryEntry.tags          : List[str]
    - MemoryEntry.source        : str
    - MemoryType.EPISODIC, .EMOTIONAL, .FACT, .RELATIONSHIP, .PREFERENCE
"""

from __future__ import annotations

import logging
import uuid
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pubcast.universal_memory")


# ────────────────────────────────────────────────────────────────────────────
# MemoryType — superset of values used across room_conductor & jeremy_cricket
# ────────────────────────────────────────────────────────────────────────────

class MemoryType(str, Enum):
    FACT         = "fact"
    EVENT        = "event"
    EPISODIC     = "episodic"
    PREFERENCE   = "preference"
    RELATIONSHIP = "relationship"
    EMOTION      = "emotion"
    EMOTIONAL    = "emotional"
    INSTRUCTION  = "instruction"


# ────────────────────────────────────────────────────────────────────────────
# MemoryEntry — lightweight data object for a single memory
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class MemoryEntry:
    content: str
    memory_type: MemoryType = MemoryType.FACT
    importance: float = 0.5
    tags: List[str] = field(default_factory=list)
    source: str = "system"
    created_at: float = field(default_factory=time.time)
    accessed_at: float = field(default_factory=time.time)
    access_count: int = 0

    def touch(self) -> None:
        """Mark this memory as recently accessed."""
        self.accessed_at = time.time()
        self.access_count += 1


# ────────────────────────────────────────────────────────────────────────────
# CharacterProfile — minimal profile stub for memory-system registration
#
# The full CharacterProfile lives in character_profiles.py; this is a
# compatible subset so room_conductor can reference it without pulling
# the entire character_profiles module.
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class CharacterProfile:
    character_id: str
    display_name: str = ""
    role: str = ""
    voice_notes: str = ""
    system_prompt: str = ""


# ────────────────────────────────────────────────────────────────────────────
# CharacterMemoryBank — per-character memory store
# ────────────────────────────────────────────────────────────────────────────

class CharacterMemoryBank:
    """In-memory bank of MemoryEntry objects for a single character."""

    __slots__ = ("character_id", "_entries", "_max_entries", "_data_dir", "_persist")

    def __init__(
        self,
        character_id: str,
        max_entries: int = 500,
        *,
        data_dir: Optional[Path] = None,
        persist: bool = True,
    ) -> None:
        self.character_id = character_id
        self._entries: List[MemoryEntry] = []
        self._max_entries = max_entries
        self._data_dir = Path(data_dir) if data_dir else None
        self._persist = persist

    # ── write ──────────────────────────────────────────────────────────────

    def add(self, entry: MemoryEntry) -> None:
        """Store a memory entry, evicting the least-important if at capacity."""
        self._entries.append(entry)
        self._persist_entry(entry)
        if len(self._entries) > self._max_entries:
            # Evict lowest importance, oldest first
            self._entries.sort(
                key=lambda e: (e.importance, e.accessed_at), reverse=True
            )
            self._entries = self._entries[: self._max_entries]

    def add_loaded(self, entry: MemoryEntry) -> None:
        """Load a persisted memory without writing it back to SQLite."""
        was_persisting = self._persist
        self._persist = False
        try:
            self.add(entry)
        finally:
            self._persist = was_persisting

    def _persist_entry(self, entry: MemoryEntry) -> None:
        """Best-effort write-through to the shared SQLite memory log."""
        if not self._persist or self._data_dir is None:
            return
        try:
            from . import memory_engine

            memory_engine.record_event(
                self._data_dir,
                session_id="persistent",
                project_id="pubcast",
                user_id=self.character_id,
                room_id=f"character_{self.character_id}",
                feature_id=entry.source,
                event_type=entry.memory_type.value,
                summary=entry.content,
                payload={
                    "importance": entry.importance,
                    "tags": entry.tags,
                    "source": entry.source,
                    "created_at": entry.created_at,
                },
            )
        except Exception:
            logger.exception("Could not persist memory for %s", self.character_id)

    # ── read ───────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 5) -> List[MemoryEntry]:
        """Return the most relevant memories matching *query*.

        Relevance scoring:
          - keyword overlap between query tokens and entry content/tags
          - importance weight
          - recency boost
        """
        if not query or not self._entries:
            return []

        tokens = query.lower().split()
        now = time.time()
        scored: List[tuple] = []

        for entry in self._entries:
            text = (entry.content + " " + " ".join(entry.tags)).lower()
            overlap = sum(1 for t in tokens if t in text)
            if overlap == 0:
                continue

            age_days = max(0.001, (now - entry.accessed_at) / 86400)
            recency = max(0.05, 1.0 - (age_days / 90) ** 0.5)
            score = overlap * entry.importance * recency
            scored.append((score, entry))

        scored.sort(key=lambda pair: pair[0], reverse=True)

        results = []
        for _score, entry in scored[:limit]:
            entry.touch()
            results.append(entry)
        return results

    def recent(self, limit: int = 10) -> List[MemoryEntry]:
        """Return the *limit* most recently created entries."""
        by_time = sorted(self._entries, key=lambda e: e.created_at, reverse=True)
        return by_time[:limit]

    def all(self) -> List[MemoryEntry]:
        """Return all stored entries (read-only snapshot)."""
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


# ────────────────────────────────────────────────────────────────────────────
# UniversalMemorySystem — container that manages all character banks
# ────────────────────────────────────────────────────────────────────────────

class UniversalMemorySystem:
    """Registry of per-character memory banks.

    Public attributes consumed by room_conductor:
        _banks    : Dict[str, CharacterMemoryBank]
        _profiles : Dict[str, CharacterProfile]
    """

    def __init__(
        self,
        max_entries_per_bank: int = 500,
        *,
        data_dir: Optional[Path] = None,
    ) -> None:
        self._banks: Dict[str, CharacterMemoryBank] = {}
        self._profiles: Dict[str, CharacterProfile] = {}
        self._max_entries = max_entries_per_bank
        self._data_dir = Path(data_dir) if data_dir else None
        logger.info("UniversalMemorySystem initialised")

    # ── registration ───────────────────────────────────────────────────────

    def register(
        self,
        character_id: str,
        profile: Optional[CharacterProfile] = None,
    ) -> CharacterMemoryBank:
        """Register a character and return its bank (creates if needed)."""
        if character_id not in self._banks:
            self._banks[character_id] = CharacterMemoryBank(
                character_id,
                self._max_entries,
                data_dir=self._data_dir,
            )
            logger.info("Registered memory bank for %s", character_id)
        if profile is not None:
            self._profiles[character_id] = profile
        return self._banks[character_id]

    def get_or_create_bank(self, character_id: str) -> CharacterMemoryBank:
        """Return existing bank or create a new one."""
        if character_id not in self._banks:
            return self.register(character_id)
        return self._banks[character_id]

    # ── queries ────────────────────────────────────────────────────────────

    def get_bank(self, character_id: str) -> Optional[CharacterMemoryBank]:
        """Return bank if it exists, else None."""
        return self._banks.get(character_id)

    def get_profile(self, character_id: str) -> Optional[CharacterProfile]:
        return self._profiles.get(character_id)

    def character_ids(self) -> List[str]:
        return list(self._banks.keys())

    # -- API adapters -----------------------------------------------------

    def store(
        self,
        character_id: str,
        content: str,
        memory_type: str = "fact",
        importance: float = 0.5,
    ) -> str:
        """Create and store a MemoryEntry, returning a generated entry ID."""
        mem_type = MemoryType(memory_type) if memory_type in MemoryType._value2member_map_ else MemoryType.FACT
        entry = MemoryEntry(
            content=content,
            memory_type=mem_type,
            importance=max(0.0, min(1.0, float(importance))),
            source="api",
        )
        self.get_or_create_bank(character_id).add(entry)
        return uuid.uuid4().hex[:16]

    def get_recent(self, character_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent memories for a character as serializable dictionaries."""
        return [self._entry_to_dict(entry) for entry in self.get_or_create_bank(character_id).recent(limit)]

    def search(self, character_id: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search a character bank and return serializable dictionaries."""
        return [self._entry_to_dict(entry) for entry in self.get_or_create_bank(character_id).search(query, limit)]

    def load_from_db(self, data_dir: Optional[Path] = None, *, limit: int = 500) -> int:
        """Reload known character memories from the shared SQLite memory log."""
        db_dir = Path(data_dir) if data_dir else self._data_dir
        if db_dir is None:
            return 0

        loaded = 0
        try:
            from . import memory_engine
        except Exception:
            logger.exception("Could not import memory_engine for memory reload")
            return 0

        character_ids = set(self._banks.keys())
        if not character_ids:
            character_ids.update(("pete", "repeat", "sir_purfluous", "jeremy", "default"))

        for character_id in sorted(character_ids):
            try:
                rows = memory_engine.recent_for_user(db_dir, user_id=character_id, limit=limit)
            except Exception:
                logger.exception("Could not load persisted memories for %s", character_id)
                continue

            bank = self.get_or_create_bank(character_id)
            existing = {entry.content for entry in bank.all()}
            for row in reversed(rows):
                content = str(row.get("summary") or "").strip()
                if not content or content in existing:
                    continue
                payload = row.get("payload") or {}
                raw_type = str(row.get("event_type") or "fact")
                mem_type = MemoryType(raw_type) if raw_type in MemoryType._value2member_map_ else MemoryType.FACT
                entry = MemoryEntry(
                    content=content,
                    memory_type=mem_type,
                    importance=float(payload.get("importance", 0.5)),
                    tags=list(payload.get("tags") or []),
                    source=str(payload.get("source") or row.get("feature_id") or "memory_engine"),
                    created_at=float(payload.get("created_at") or row.get("ts") or time.time()),
                )
                bank.add_loaded(entry)
                existing.add(content)
                loaded += 1

        logger.info("Loaded %d persisted character memories", loaded)
        return loaded

    @staticmethod
    def _entry_to_dict(entry: MemoryEntry) -> Dict[str, Any]:
        return {
            "content": entry.content,
            "memory_type": entry.memory_type.value,
            "importance": entry.importance,
            "tags": entry.tags,
            "source": entry.source,
            "created_at": entry.created_at,
        }

    # ── bulk ops ───────────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        """Diagnostic snapshot for the doctor/status endpoint."""
        return {
            "characters": len(self._banks),
            "banks": {
                cid: {
                    "entries": len(bank),
                    "profile_registered": cid in self._profiles,
                }
                for cid, bank in self._banks.items()
            },
        }

    def clear(self, character_id: Optional[str] = None) -> None:
        """Clear memories. If character_id given, only that bank; else all."""
        if character_id:
            if character_id in self._banks:
                self._banks[character_id] = CharacterMemoryBank(
                    character_id,
                    self._max_entries,
                    data_dir=self._data_dir,
                )
                logger.info("Cleared memory bank for %s", character_id)
        else:
            for cid in list(self._banks):
                self._banks[cid] = CharacterMemoryBank(cid, self._max_entries, data_dir=self._data_dir)
            logger.info("Cleared all memory banks")
