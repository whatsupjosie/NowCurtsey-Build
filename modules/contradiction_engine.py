"""
contradiction_engine.py — Contradiction Memory & Instability Detection
=======================================================================
Copyright (c) 2024-2025 Rear View Foresight LLC
"Feic Mo Chroí — See My Heart"

WHAT THIS IS:

    Humans contradict themselves. Not because they lie —
    because emotional truth is unstable around certain topics.

    "I'm fine." / "I'm terrified." / "I'm fine." / "I'm terrified."

    That oscillation IS the signal. The contradiction is the data.
    Most systems store both statements and move on.
    This system notices the pattern and names it.

CORE STRUCTURES:

    ContradictionRecord — A detected conflict between two claims
                          about the same topic across sessions.
                          Tracks frequency, emotional weight,
                          and oscillation pattern.

    ContradictionEngine — Watches the marker stream for semantic
                          conflicts. When it finds them, it creates
                          records. When records repeat, it escalates
                          them to the theory graph as instability signals.

    InstabilitySignal   — Emitted when a topic shows repeated
                          contradiction. Not "person is lying" —
                          "this topic contains unresolved tension."

DESIGN PRINCIPLE:

    Contradictions are not errors to be resolved.
    They are evidence of emotional complexity.
    The system preserves them, names them, and treats the
    oscillation frequency itself as meaningful data.

PUBLIC API:

    ContradictionEngine
        .ingest_marker(marker)              → List[ContradictionRecord]
        .ingest_statement(topic, claim,
                          session_id,
                          emotional_weight) → Optional[ContradictionRecord]
        .get_instability_signals()          → List[InstabilitySignal]
        .get_contradiction_briefing()       → str
        .distill()                          → None
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DB_PATH = Path("data/pubcast_memory.db")


# ─────────────────────────────────────────────────────────────────────────────
# INSTABILITY LEVELS
# ─────────────────────────────────────────────────────────────────────────────

class InstabilityLevel(str, Enum):
    """How unresolved a topic appears based on contradiction frequency."""
    NOTED       = "noted"       # 1 contradiction — flag for attention
    RECURRING   = "recurring"   # 2-3 — pattern forming
    VOLATILE    = "volatile"    # 4-6 — active instability
    CORE        = "core"        # 7+  — deep unresolved tension


INSTABILITY_THRESHOLDS = {
    InstabilityLevel.NOTED:     1,
    InstabilityLevel.RECURRING: 2,
    InstabilityLevel.VOLATILE:  4,
    InstabilityLevel.CORE:      7,
}


# ─────────────────────────────────────────────────────────────────────────────
# TOPIC CLUSTERS
# Semantic groupings so "I'm overwhelmed" and "everything is too much"
# map to the same topic rather than being treated as separate claims.
# ─────────────────────────────────────────────────────────────────────────────

TOPIC_CLUSTERS: Dict[str, List[str]] = {
    "emotional_state":      ["fine", "okay", "good", "great", "overwhelmed", "struggling",
                             "terrified", "anxious", "scared", "happy", "sad", "angry",
                             "frustrated", "excited", "depressed", "numb", "exhausted"],
    "creative_confidence":  ["confident", "proud", "doubt", "insecure", "uncertain",
                             "talented", "failing", "blocked", "flowing", "stuck"],
    "relationship_safety":  ["trust", "safe", "comfortable", "close", "distant",
                             "alone", "supported", "abandoned", "connected", "isolated"],
    "workload":             ["busy", "overwhelmed", "manageable", "behind", "ahead",
                             "productive", "stuck", "flowing", "drowning", "fine"],
    "self_worth":           ["worthy", "enough", "failure", "successful", "proud",
                             "ashamed", "capable", "useless", "valuable", "burden"],
    "health":               ["well", "sick", "tired", "energized", "pain", "fine",
                             "exhausted", "strong", "weak", "recovering"],
    "project_state":        ["working", "broken", "progress", "stuck", "done",
                             "failing", "succeeding", "blocked", "moving", "finished"],
}

def _cluster_for_text(text: str) -> Optional[str]:
    """Find the topic cluster a text fragment most likely belongs to."""
    text_lower = text.lower()
    best_cluster = None
    best_hits = 0
    for cluster, keywords in TOPIC_CLUSTERS.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits > best_hits:
            best_hits = hits
            best_cluster = cluster
    return best_cluster if best_hits > 0 else None


# ─────────────────────────────────────────────────────────────────────────────
# CONTRADICTION RECORD
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ContradictionRecord:
    """
    A detected conflict between two claims about the same topic.

    Not evidence of lying. Evidence of emotional complexity.
    The oscillation_count is the most important field —
    a topic contradicted once is interesting.
    A topic contradicted seven times across sessions is core tension.
    """
    record_id:          str
    topic_cluster:      str         # Which semantic domain
    claim_a:            str         # First observed position
    claim_b:            str         # Contradicting position
    first_session:      str
    last_session:       str
    oscillation_count:  int         = 1
    emotional_weight:   float       = 0.5   # avg emotional intensity of contradictions
    instability_level:  str         = InstabilityLevel.NOTED
    sessions_involved:  List[str]   = field(default_factory=list)
    notes:              str         = ""

    @property
    def instability_label(self) -> str:
        return self.instability_level

    def add_oscillation(self, session_id: str, emotional_weight: float) -> None:
        """Record another contradiction on this topic."""
        self.oscillation_count += 1
        # Running average of emotional weight
        self.emotional_weight = round(
            (self.emotional_weight * (self.oscillation_count - 1) + emotional_weight)
            / self.oscillation_count,
            4
        )
        self.last_session = session_id
        if session_id not in self.sessions_involved:
            self.sessions_involved.append(session_id)
        # Update instability level
        for level in [InstabilityLevel.CORE, InstabilityLevel.VOLATILE,
                      InstabilityLevel.RECURRING, InstabilityLevel.NOTED]:
            if self.oscillation_count >= INSTABILITY_THRESHOLDS[level]:
                self.instability_level = level
                break

    def to_db_dict(self) -> dict:
        return {
            "record_id":        self.record_id,
            "topic_cluster":    self.topic_cluster,
            "claim_a":          self.claim_a,
            "claim_b":          self.claim_b,
            "first_session":    self.first_session,
            "last_session":     self.last_session,
            "oscillation_count": self.oscillation_count,
            "emotional_weight": self.emotional_weight,
            "instability_level": self.instability_level,
            "sessions_involved": json.dumps(self.sessions_involved),
            "notes":            self.notes,
        }

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "ContradictionRecord":
        return cls(
            record_id       = row["record_id"],
            topic_cluster   = row["topic_cluster"],
            claim_a         = row["claim_a"],
            claim_b         = row["claim_b"],
            first_session   = row["first_session"],
            last_session    = row["last_session"],
            oscillation_count = row["oscillation_count"],
            emotional_weight = row["emotional_weight"],
            instability_level = row["instability_level"],
            sessions_involved = json.loads(row["sessions_involved"]),
            notes           = row["notes"] or "",
        )

    def to_briefing_line(self) -> str:
        return (
            f"INSTABILITY [{self.instability_level.upper()}] — {self.topic_cluster}: "
            f"oscillates {self.oscillation_count}× across sessions "
            f"(weight={self.emotional_weight:.2f})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# INSTABILITY SIGNAL
# Emitted when a topic crosses a threshold — feeds into TheoryGraph
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class InstabilitySignal:
    """
    Emitted when a ContradictionRecord crosses an instability threshold.
    Fed into the TheoryGraph to influence theory confidence.

    This is how contradictions become theory-level evidence:
    not "person said X and Y" but "this topic is unresolved at depth N."
    """
    signal_id:          str
    topic_cluster:      str
    instability_level:  str
    oscillation_count:  int
    emotional_weight:   float
    record_id:          str
    session_id:         str
    timestamp:          float = field(default_factory=time.time)


# ─────────────────────────────────────────────────────────────────────────────
# CLAIM STORE
# Tracks the most recent claim per topic per user session
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ClaimRecord:
    """A single stated position on a topic."""
    claim_id:       str
    topic_cluster:  str
    claim_text:     str
    session_id:     str
    timestamp:      float
    emotional_weight: float = 0.5
    polarity:       float   = 0.0   # -1=negative, 0=neutral, +1=positive

    def to_db_dict(self) -> dict:
        return {
            "claim_id":         self.claim_id,
            "topic_cluster":    self.topic_cluster,
            "claim_text":       self.claim_text,
            "session_id":       self.session_id,
            "timestamp":        self.timestamp,
            "emotional_weight": self.emotional_weight,
            "polarity":         self.polarity,
        }

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "ClaimRecord":
        return cls(
            claim_id        = row["claim_id"],
            topic_cluster   = row["topic_cluster"],
            claim_text      = row["claim_text"],
            session_id      = row["session_id"],
            timestamp       = row["timestamp"],
            emotional_weight = row["emotional_weight"],
            polarity        = row["polarity"],
        )


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA
# ─────────────────────────────────────────────────────────────────────────────

CONTRADICTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS contradiction_records (
    record_id           TEXT PRIMARY KEY,
    topic_cluster       TEXT NOT NULL,
    claim_a             TEXT NOT NULL,
    claim_b             TEXT NOT NULL,
    first_session       TEXT NOT NULL,
    last_session        TEXT NOT NULL,
    oscillation_count   INTEGER DEFAULT 1,
    emotional_weight    REAL DEFAULT 0.5,
    instability_level   TEXT DEFAULT 'noted',
    sessions_involved   TEXT DEFAULT '[]',
    notes               TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS claim_records (
    claim_id            TEXT PRIMARY KEY,
    topic_cluster       TEXT NOT NULL,
    claim_text          TEXT NOT NULL,
    session_id          TEXT NOT NULL,
    timestamp           REAL NOT NULL,
    emotional_weight    REAL DEFAULT 0.5,
    polarity            REAL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_claims_topic   ON claim_records(topic_cluster);
CREATE INDEX IF NOT EXISTS idx_claims_session ON claim_records(session_id);
CREATE INDEX IF NOT EXISTS idx_contra_topic   ON contradiction_records(topic_cluster);
CREATE INDEX IF NOT EXISTS idx_contra_level   ON contradiction_records(instability_level);
"""

# Polarity word lists — used to detect claim direction
POSITIVE_WORDS = {
    "fine", "good", "great", "okay", "confident", "well", "ready",
    "happy", "excited", "proud", "capable", "strong", "safe", "trust",
    "comfortable", "supported", "connected", "successful", "worthy",
    "productive", "flowing", "working", "done", "ahead", "enough",
}
NEGATIVE_WORDS = {
    "overwhelmed", "struggling", "terrified", "anxious", "scared",
    "sad", "angry", "frustrated", "depressed", "numb", "exhausted",
    "doubt", "insecure", "uncertain", "failing", "blocked", "stuck",
    "distant", "alone", "abandoned", "isolated", "ashamed", "useless",
    "burden", "sick", "tired", "broken", "behind", "drowning", "weak",
}

def _polarity(text: str) -> float:
    """Rough polarity score: -1.0 to +1.0."""
    words = set(text.lower().split())
    pos = len(words & POSITIVE_WORDS)
    neg = len(words & NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 3)

def _claims_contradict(a: ClaimRecord, b: ClaimRecord) -> bool:
    """
    Do two claims on the same topic contradict each other?
    Uses polarity distance — claims on opposite ends of the
    positive/negative spectrum about the same topic are contradictory.
    Same-session claims are never contradictory (context shifts are normal).
    """
    if a.session_id == b.session_id:
        return False
    # Polarity must be meaningfully opposite
    if abs(a.polarity - b.polarity) < 0.4:
        return False
    # And they must be on opposite sides of neutral
    if (a.polarity > 0 and b.polarity > 0) or (a.polarity < 0 and b.polarity < 0):
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# CONTRADICTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class ContradictionEngine:
    """
    Watches the stream of claims and markers for contradictions.

    Two modes of input:
        1. ingest_marker() — from the EvidenceLayer marker stream.
           Extracts topic cluster and polarity from the marker observation.

        2. ingest_statement() — direct text claim from conversation.
           Called when Jeremy Cricket or the UAI layer detects a
           clear self-report ("I'm fine", "I'm terrified").

    Contradictions are not deleted. They accumulate.
    The oscillation count is the signal.
    """

    def __init__(
        self,
        db_path:    Path = DB_PATH,
        session_id: str  = "",
    ):
        self.db_path    = db_path
        self.session_id = session_id or f"session_{int(time.time())}"

        self._contradictions:   Dict[str, ContradictionRecord] = {}  # topic → record
        self._recent_claims:    Dict[str, ClaimRecord]         = {}  # topic → latest claim
        self._instability_signals: List[InstabilitySignal]    = []

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._load_state()

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def ingest_marker(self, marker) -> List[ContradictionRecord]:
        """
        Ingest an EvidenceMarker from the evidence layer.
        Extracts self-report signals from contradiction_flags and
        leading hypothesis to detect topic claims.
        Returns list of contradiction records created or updated.
        """
        triggered = []

        # Extract topic from marker observation and context
        all_text = marker.observation + " " + " ".join(marker.linked_context)
        cluster = _cluster_for_text(all_text)
        if not cluster:
            return triggered

        # Check for self-report mismatch flag — this is an explicit contradiction signal
        has_mismatch = "self-report mismatch" in " ".join(marker.contradiction_flags).lower()
        if not has_mismatch and marker.observation not in (
            "self_report_mismatch", "sentiment_inversion", "contradictory_phrasing"
        ):
            return triggered

        # Synthesize a claim from the leading hypothesis
        lead = marker.leading_hypothesis()
        if not lead:
            return triggered

        pol = -0.5 if any(k in lead.hypothesis for k in [
            "frustration", "anxiety", "avoidance", "suppressed", "conflict", "mismatch"
        ]) else 0.5

        record = self.ingest_statement(
            topic           = cluster,
            claim           = f"{marker.observation} → {lead.hypothesis}",
            session_id      = marker.session_id,
            emotional_weight = marker.narrative_weight,
            polarity        = pol,
        )
        if record:
            triggered.append(record)

        return triggered

    def ingest_statement(
        self,
        topic:          str,
        claim:          str,
        session_id:     str,
        emotional_weight: float = 0.5,
        polarity:       Optional[float] = None,
    ) -> Optional[ContradictionRecord]:
        """
        Ingest a direct claim about a topic.

        topic:   semantic cluster (or raw text — will auto-cluster)
        claim:   the actual statement
        polarity: -1.0 to +1.0, or None to auto-detect

        Returns a ContradictionRecord if a contradiction was detected,
        None if this is the first claim on this topic or consistent.
        """
        # Resolve cluster
        cluster = topic if topic in TOPIC_CLUSTERS else _cluster_for_text(claim) or topic

        pol = polarity if polarity is not None else _polarity(claim)

        new_claim = ClaimRecord(
            claim_id        = str(uuid.uuid4()),
            topic_cluster   = cluster,
            claim_text      = claim,
            session_id      = session_id,
            timestamp       = time.time(),
            emotional_weight = emotional_weight,
            polarity        = pol,
        )

        # Persist the claim
        self._persist_claim(new_claim)

        # Check against prior claim on same topic
        prior = self._recent_claims.get(cluster)
        contradiction = None

        if prior and _claims_contradict(prior, new_claim):
            contradiction = self._record_contradiction(prior, new_claim, cluster, emotional_weight)

        # Update most recent claim
        self._recent_claims[cluster] = new_claim

        return contradiction

    def get_instability_signals(
        self,
        min_level: str = InstabilityLevel.RECURRING
    ) -> List[InstabilitySignal]:
        """
        Return instability signals at or above the given level.
        Used by TheoryGraph to influence theory confidence.
        """
        level_order = [
            InstabilityLevel.NOTED,
            InstabilityLevel.RECURRING,
            InstabilityLevel.VOLATILE,
            InstabilityLevel.CORE,
        ]
        min_idx = level_order.index(min_level)
        return [
            s for s in self._instability_signals
            if level_order.index(s.instability_level) >= min_idx
        ]

    def get_all_contradictions(self) -> List[ContradictionRecord]:
        """All tracked contradictions, sorted by oscillation count."""
        records = list(self._contradictions.values())
        records.sort(key=lambda r: r.oscillation_count, reverse=True)
        return records

    def get_contradiction_briefing(self, max_items: int = 3) -> str:
        """
        Compact briefing for Pete/partner system prompt.
        Shows topics with active instability — not raw contradictions.
        """
        volatile = [
            r for r in self._contradictions.values()
            if r.instability_level in (InstabilityLevel.VOLATILE, InstabilityLevel.CORE)
        ]
        recurring = [
            r for r in self._contradictions.values()
            if r.instability_level == InstabilityLevel.RECURRING
        ]

        if not volatile and not recurring:
            return ""

        lines = ["[INSTABILITY PATTERNS]"]
        shown = 0
        for record in sorted(volatile + recurring,
                              key=lambda r: r.oscillation_count, reverse=True):
            if shown >= max_items:
                break
            lines.append(f"  {record.to_briefing_line()}")
            shown += 1

        return "\n".join(lines)

    def distill(self) -> None:
        """Persist current contradiction state. Called at session end."""
        self._persist_all_contradictions()
        logger.info(
            f"[Contradiction] Distilled — "
            f"{len(self._contradictions)} active contradiction records"
        )

    # =========================================================================
    # INTERNAL
    # =========================================================================

    def _record_contradiction(
        self,
        prior:          ClaimRecord,
        new:            ClaimRecord,
        cluster:        str,
        emotional_weight: float,
    ) -> ContradictionRecord:
        """Create or update a contradiction record for this topic."""
        if cluster in self._contradictions:
            record = self._contradictions[cluster]
            record.add_oscillation(new.session_id, emotional_weight)
            logger.info(
                f"[Contradiction] Oscillation #{record.oscillation_count} "
                f"on '{cluster}' — level={record.instability_level}"
            )
        else:
            record = ContradictionRecord(
                record_id       = str(uuid.uuid4()),
                topic_cluster   = cluster,
                claim_a         = prior.claim_text,
                claim_b         = new.claim_text,
                first_session   = prior.session_id,
                last_session    = new.session_id,
                oscillation_count = 1,
                emotional_weight = emotional_weight,
                instability_level = InstabilityLevel.NOTED,
                sessions_involved = [prior.session_id, new.session_id],
            )
            self._contradictions[cluster] = record
            logger.info(f"[Contradiction] New contradiction on '{cluster}'")

        # Emit instability signal if threshold crossed
        if record.instability_level in (
            InstabilityLevel.RECURRING,
            InstabilityLevel.VOLATILE,
            InstabilityLevel.CORE,
        ):
            signal = InstabilitySignal(
                signal_id       = str(uuid.uuid4()),
                topic_cluster   = cluster,
                instability_level = record.instability_level,
                oscillation_count = record.oscillation_count,
                emotional_weight  = record.emotional_weight,
                record_id       = record.record_id,
                session_id      = new.session_id,
            )
            self._instability_signals.append(signal)

        self._persist_contradiction(record)
        return record

    def _load_state(self) -> None:
        """Load contradiction records and recent claims from DB."""
        with self._db() as conn:
            # Load contradiction records
            rows = conn.execute(
                "SELECT * FROM contradiction_records"
            ).fetchall()
            for row in rows:
                rec = ContradictionRecord.from_db_row(row)
                self._contradictions[rec.topic_cluster] = rec

            # Load most recent claim per topic cluster
            rows = conn.execute("""
                SELECT * FROM claim_records cr1
                WHERE timestamp = (
                    SELECT MAX(cr2.timestamp)
                    FROM claim_records cr2
                    WHERE cr2.topic_cluster = cr1.topic_cluster
                )
            """).fetchall()
            for row in rows:
                claim = ClaimRecord.from_db_row(row)
                self._recent_claims[claim.topic_cluster] = claim

        logger.debug(
            f"[Contradiction] Loaded {len(self._contradictions)} contradiction records, "
            f"{len(self._recent_claims)} recent claims"
        )

    # ── DB helpers ────────────────────────────────────────────────────────────

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"[Contradiction] DB error: {e}")
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._db() as conn:
            conn.executescript(CONTRADICTION_SCHEMA)

    def _persist_claim(self, claim: ClaimRecord) -> None:
        with self._db() as conn:
            d = claim.to_db_dict()
            conn.execute("""
                INSERT OR REPLACE INTO claim_records
                    (claim_id, topic_cluster, claim_text, session_id,
                     timestamp, emotional_weight, polarity)
                VALUES
                    (:claim_id, :topic_cluster, :claim_text, :session_id,
                     :timestamp, :emotional_weight, :polarity)
            """, d)

    def _persist_contradiction(self, record: ContradictionRecord) -> None:
        with self._db() as conn:
            d = record.to_db_dict()
            conn.execute("""
                INSERT OR REPLACE INTO contradiction_records
                    (record_id, topic_cluster, claim_a, claim_b,
                     first_session, last_session, oscillation_count,
                     emotional_weight, instability_level, sessions_involved, notes)
                VALUES
                    (:record_id, :topic_cluster, :claim_a, :claim_b,
                     :first_session, :last_session, :oscillation_count,
                     :emotional_weight, :instability_level, :sessions_involved, :notes)
            """, d)

    def _persist_all_contradictions(self) -> None:
        for record in self._contradictions.values():
            self._persist_contradiction(record)
