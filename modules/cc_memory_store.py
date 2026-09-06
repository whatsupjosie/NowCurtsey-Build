"""
cc_memory_store.py — Code Collector Tier 2 persistent memory
==============================================================================
Rear View Foresight LLC · Feic Mo Chroí™

Code Collector's flight recorder.

When you capture code from an AI session, Code Collector stores:
- The raw context (what was the conversation about?)
- Version lineage (how did this code evolve?)
- Importance weights (what matters right now?)
- Telemetry-driven decay (terminal errors bubble up, idle tabs sink)

When you open a new session, /context/resolve surfaces the right slice.

This is NOT character memory (that's jeremy_cricket.py).
This is NOT personal memory (that's alex_memory.py).
This is code session memory — what Code Collector remembers about your work.

Architecture
------------
- SQLite at data/code_collector/cc_memory.db
- Deduplication via content_hash
- Version chains via version_group + parent_hash
- Telemetry-weighted importance scores
- /context/resolve query to surface active memory slice

Integration points
------------------
1. Capture:   await cc.capture(url, title, content, session_id)
2. Resolve:   memories = await cc.resolve_context(current_focus, active_session)
3. Telemetry: await cc.apply_telemetry_weight(content_hash, weight_delta)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Schema — the flight recorder
# ────────────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash TEXT UNIQUE NOT NULL,
    source_url TEXT,
    source_title TEXT,
    content_body TEXT NOT NULL,
    captured_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    session_id TEXT,
    
    -- Versioning & lineage (the diff chain)
    version_group TEXT,
    parent_hash TEXT,
    
    -- Active memory metadata (the sensors)
    importance_score REAL DEFAULT 0.5,
    last_accessed DATETIME,
    access_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_hash ON memory_captures (content_hash);
CREATE INDEX IF NOT EXISTS idx_session ON memory_captures (session_id);
CREATE INDEX IF NOT EXISTS idx_version_group ON memory_captures (version_group);
CREATE INDEX IF NOT EXISTS idx_importance ON memory_captures (importance_score DESC);
CREATE INDEX IF NOT EXISTS idx_accessed ON memory_captures (last_accessed DESC);
"""


# ────────────────────────────────────────────────────────────────────────────
# MemoryCapture dataclass
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class MemoryCapture:
    id: int
    content_hash: str
    source_url: Optional[str]
    source_title: Optional[str]
    content_body: str
    captured_at: str
    session_id: Optional[str]
    version_group: Optional[str]
    parent_hash: Optional[str]
    importance_score: float
    last_accessed: Optional[str]
    access_count: int

    @classmethod
    def from_row(cls, row: tuple) -> "MemoryCapture":
        return cls(
            id=row[0],
            content_hash=row[1],
            source_url=row[2],
            source_title=row[3],
            content_body=row[4],
            captured_at=row[5],
            session_id=row[6],
            version_group=row[7],
            parent_hash=row[8],
            importance_score=row[9],
            last_accessed=row[10],
            access_count=row[11],
        )

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "content_hash": self.content_hash,
            "source_url": self.source_url,
            "source_title": self.source_title,
            "content_body": self.content_body,
            "captured_at": self.captured_at,
            "session_id": self.session_id,
            "version_group": self.version_group,
            "parent_hash": self.parent_hash,
            "importance_score": self.importance_score,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
        }


# ────────────────────────────────────────────────────────────────────────────
# Telemetry weights — the calibration
# ────────────────────────────────────────────────────────────────────────────

class TelemetryWeight:
    """
    Telemetry-driven importance adjustments.
    
    These weights update importance_score based on live behavior:
    - Terminal errors: +0.3 (focus follows the pain)
    - File saves: +0.2 (active creation)
    - Tab idle > 10 min: -0.1 (graceful decay)
    - Context switch: -0.05 (attention moved elsewhere)
    """
    TERMINAL_ERROR = 0.3
    FILE_SAVE = 0.2
    TAB_IDLE = -0.1
    CONTEXT_SWITCH = -0.05


# ────────────────────────────────────────────────────────────────────────────
# CCMemoryStore — the flight recorder
# ────────────────────────────────────────────────────────────────────────────

class CCMemoryStore:
    """
    Code Collector's persistent memory layer.

    Stores code captures with versioning, deduplication, and telemetry-weighted
    importance scoring. Surfaces the right context slice when a new session opens.

    Usage
    -----
        cc = CCMemoryStore(data_dir=Path("data/code_collector"))
        await cc.init()

        # Capture a code session
        await cc.capture(
            source_url="https://claude.ai/chat/abc123",
            source_title="React component refactor",
            content_body=full_conversation_text,
            session_id="session_xyz",
            version_group="react_navbar",
        )

        # Resolve context for a new session
        memories = await cc.resolve_context(
            current_focus="react_navbar",
            active_session="session_xyz",
        )

        # Apply telemetry weight
        await cc.apply_telemetry_weight(
            content_hash="abc...",
            weight_delta=TelemetryWeight.TERMINAL_ERROR,
        )
    """

    def __init__(self, data_dir: Path) -> None:
        self._db_path = data_dir / "cc_memory.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._closed = False
        self._lock = asyncio.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def init(self) -> None:
        """Initialize database and schema."""
        await asyncio.to_thread(self._sync_init)
        logger.info("CCMemoryStore ready at %s", self._db_path)

    def _sync_init(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _require_open(self, op: str) -> bool:
        if self._closed or self._conn is None:
            logger.warning("CCMemoryStore: '%s' called on closed instance", op)
            return False
        return True

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._conn:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    # ── Capture ───────────────────────────────────────────────────────────────

    async def capture(
        self,
        *,
        source_url: Optional[str] = None,
        source_title: Optional[str] = None,
        content_body: str,
        session_id: Optional[str] = None,
        version_group: Optional[str] = None,
        parent_hash: Optional[str] = None,
    ) -> Optional[str]:
        """
        Capture a code session memory.

        Returns the content_hash if stored, None if duplicate.
        """
        if not self._require_open("capture"):
            return None

        content_hash = _compute_hash(content_body)

        async with self._lock:
            # Check for duplicate
            exists = await asyncio.to_thread(
                self._sync_check_hash, content_hash
            )
            if exists:
                logger.debug("CCMemoryStore: duplicate capture skipped (hash=%s)", content_hash[:8])
                return None

            # Insert new capture
            await asyncio.to_thread(
                self._sync_insert_capture,
                content_hash, source_url, source_title, content_body,
                session_id, version_group, parent_hash
            )

        logger.info(
            "CCMemoryStore: captured %s (session=%s, version_group=%s)",
            content_hash[:8], session_id, version_group
        )
        return content_hash

    def _sync_check_hash(self, content_hash: str) -> bool:
        cursor = self._conn.execute(
            "SELECT 1 FROM memory_captures WHERE content_hash=?",
            (content_hash,)
        )
        return cursor.fetchone() is not None

    def _sync_insert_capture(
        self,
        content_hash: str,
        source_url: Optional[str],
        source_title: Optional[str],
        content_body: str,
        session_id: Optional[str],
        version_group: Optional[str],
        parent_hash: Optional[str],
    ) -> None:
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            """INSERT INTO memory_captures
               (content_hash, source_url, source_title, content_body,
                captured_at, session_id, version_group, parent_hash,
                importance_score, last_accessed, access_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.5, ?, 0)""",
            (content_hash, source_url, source_title, content_body,
             now, session_id, version_group, parent_hash, now)
        )
        self._conn.commit()

    # ── Context resolution ────────────────────────────────────────────────────

    async def resolve_context(
        self,
        *,
        current_focus: Optional[str] = None,
        active_session: Optional[str] = None,
        min_importance: float = 0.3,
        limit: int = 5,
    ) -> List[MemoryCapture]:
        """
        Resolve the active memory slice for a new session.

        This is the /context/resolve query — finds the most relevant memories
        based on version_group, session_id, and importance.

        Returns up to *limit* memories, ordered by importance + recency.
        """
        if not self._require_open("resolve_context"):
            return []

        async with self._lock:
            results = await asyncio.to_thread(
                self._sync_resolve,
                current_focus, active_session, min_importance, limit
            )

        # Mark accessed
        if results:
            now = datetime.utcnow().isoformat()
            async with self._lock:
                await asyncio.to_thread(
                    self._sync_mark_accessed,
                    [m.id for m in results],
                    now
                )

        logger.info(
            "CCMemoryStore: resolved %d memories (focus=%s, session=%s)",
            len(results), current_focus, active_session
        )
        return results

    def _sync_resolve(
        self,
        current_focus: Optional[str],
        active_session: Optional[str],
        min_importance: float,
        limit: int,
    ) -> List[MemoryCapture]:
        query = """
            SELECT * FROM memory_captures
            WHERE importance_score >= ?
            AND (version_group = ? OR session_id = ?)
            ORDER BY importance_score DESC, last_accessed DESC
            LIMIT ?
        """
        rows = self._conn.execute(
            query,
            (min_importance, current_focus or "", active_session or "", limit)
        ).fetchall()
        return [MemoryCapture.from_row(r) for r in rows]

    def _sync_mark_accessed(self, ids: List[int], now: str) -> None:
        self._conn.executemany(
            "UPDATE memory_captures SET last_accessed=?, access_count=access_count+1 WHERE id=?",
            [(now, id_) for id_ in ids]
        )
        self._conn.commit()

    # ── Telemetry weights ─────────────────────────────────────────────────────

    async def apply_telemetry_weight(
        self,
        content_hash: str,
        weight_delta: float,
    ) -> None:
        """
        Apply a telemetry-driven importance adjustment.

        Examples:
            await cc.apply_telemetry_weight(hash, TelemetryWeight.TERMINAL_ERROR)
            await cc.apply_telemetry_weight(hash, TelemetryWeight.TAB_IDLE)
        """
        if not self._require_open("apply_telemetry_weight"):
            return

        async with self._lock:
            await asyncio.to_thread(
                self._sync_update_importance,
                content_hash, weight_delta
            )

        logger.debug(
            "CCMemoryStore: applied weight %.2f to %s",
            weight_delta, content_hash[:8]
        )

    def _sync_update_importance(self, content_hash: str, weight_delta: float) -> None:
        # Clamp between 0.0 and 1.0
        self._conn.execute(
            """UPDATE memory_captures
               SET importance_score = MAX(0.0, MIN(1.0, importance_score + ?))
               WHERE content_hash = ?""",
            (weight_delta, content_hash)
        )
        self._conn.commit()

    # ── Version chain queries ─────────────────────────────────────────────────

    async def get_version_chain(self, version_group: str) -> List[MemoryCapture]:
        """
        Retrieve all captures in a version group, ordered chronologically.

        This reconstructs the evolution of a piece of code.
        """
        if not self._require_open("get_version_chain"):
            return []

        async with self._lock:
            rows = await asyncio.to_thread(
                self._sync_fetch_version_group, version_group
            )

        return rows

    def _sync_fetch_version_group(self, version_group: str) -> List[MemoryCapture]:
        rows = self._conn.execute(
            """SELECT * FROM memory_captures
               WHERE version_group = ?
               ORDER BY captured_at ASC""",
            (version_group,)
        ).fetchall()
        return [MemoryCapture.from_row(r) for r in rows]

    # ── Diagnostics ───────────────────────────────────────────────────────────

    async def stats(self) -> Dict:
        """Return storage statistics."""
        if not self._require_open("stats"):
            return {"status": "closed"}

        async with self._lock:
            count_row = await asyncio.to_thread(
                self._conn.execute,
                "SELECT COUNT(*) FROM memory_captures"
            )
            total = count_row.fetchone()[0]

            avg_row = await asyncio.to_thread(
                self._conn.execute,
                "SELECT AVG(importance_score) FROM memory_captures"
            )
            avg_importance = avg_row.fetchone()[0] or 0.0

        return {
            "status": "open",
            "total_captures": total,
            "avg_importance": round(avg_importance, 3),
            "db_path": str(self._db_path),
        }

    async def get_by_hash(self, content_hash: str) -> Optional[MemoryCapture]:
        """Retrieve a specific capture by hash."""
        if not self._require_open("get_by_hash"):
            return None

        async with self._lock:
            row = await asyncio.to_thread(
                self._sync_fetch_by_hash, content_hash
            )

        return MemoryCapture.from_row(row) if row else None

    def _sync_fetch_by_hash(self, content_hash: str) -> Optional[tuple]:
        cursor = self._conn.execute(
            "SELECT * FROM memory_captures WHERE content_hash=?",
            (content_hash,)
        )
        return cursor.fetchone()


# ────────────────────────────────────────────────────────────────────────────
# Utility
# ────────────────────────────────────────────────────────────────────────────

def _compute_hash(content: str) -> str:
    """SHA256 hash of content for deduplication."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


__all__ = [
    "CCMemoryStore",
    "MemoryCapture",
    "TelemetryWeight",
]
