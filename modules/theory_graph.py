"""
theory_graph.py — Theory Graph, Meta-Theory Engine & Presence Mode
===================================================================
Copyright (c) 2024-2025 Rear View Foresight LLC
"Feic Mo Chroí — See My Heart"

WHAT THIS IS:

    The connective tissue between isolated theories and genuine understanding.

    Individual EvidenceTheories are observations about a person.
    The TheoryGraph is the network that makes them reason together.

    When creative_insecurity_recurrence strengthens, it pulls on
    humor_as_defense_mechanism. When humor_as_defense_mechanism
    strengthens, it pulls on topic_avoidance_signature. When enough
    theories converge on the same underlying pattern, the graph
    generates a MetaTheory — a higher-order insight that none of
    the individual theories could produce alone.

    That's the detective moment. That's the cake.

PRESENCE MODE:

    The system behaves differently in front of people than in private.
    Not because it's less honest publicly — because social context is real
    and the appropriate register shifts with it.

    Presence mode is computed from VDI signals already in the Sacred Chain:
        audience_size + vdi_score + voice_mode + identity_moment
        → PUBLIC | INTIMATE_GROUP | PRIVATE

    Theories are surfaced differently per presence mode.
    Some things you'd surface privately you'd never surface publicly.
    The AI is more delicate in a crowd.

THREE CONNECTION TYPES:

    SUPPORTS      — when A strengthens, B becomes more likely
    WEAKENS       — when A strengthens, B becomes less likely
    DESTABILIZES  — contradiction instability spreads uncertainty

META-THEORY FORMATION:

    When a cluster of mutually reinforcing theories crosses a convergence
    threshold, the graph names the pattern underneath them.
    Not because any single event said so.
    Because the whole network pointed the same direction.

PUBLIC API:

    TheoryGraph
        .add_theory(theory)
        .connect(theory_a, theory_b, connection_type, weight)
        .propagate(theory_name, delta)
        .detect_clusters()
        .get_meta_theories()
        .get_briefing(presence_mode)
        .distill()

    PresenceModeEngine
        .compute(vdi_report, audience_size)  → PresenceMode

    MetaTheory
        .to_briefing_block(presence_mode)
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
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

DB_PATH = Path("data/pubcast_memory.db")


# ─────────────────────────────────────────────────────────────────────────────
# PRESENCE MODE
# Computed from EVO/VDI layer. Travels with everything.
# ─────────────────────────────────────────────────────────────────────────────

class PresenceMode(str, Enum):
    """
    The social context the system is operating in.
    Feeds from VDI — not just headcount, emotional density of the room.
    """
    PRIVATE         = "private"         # Just the person and the system
    INTIMATE_GROUP  = "intimate_group"  # Small trusted room, high VDI
    PUBLIC          = "public"          # Audience present
    BROADCAST       = "broadcast"       # Live audience, broadcast active


# How much to surface per presence mode
# 1.0 = surface everything, 0.0 = surface nothing
PRESENCE_SURFACE_WEIGHTS: Dict[str, float] = {
    PresenceMode.PRIVATE:           1.0,    # Full depth — nothing to protect
    PresenceMode.INTIMATE_GROUP:    0.75,   # Most things — high trust
    PresenceMode.PUBLIC:            0.35,   # Careful — social exposure
    PresenceMode.BROADCAST:         0.20,   # Most delicate — on the record
}

# Theories that should NEVER be surfaced publicly regardless of confidence
PRIVATE_ONLY_THEORY_TAGS = {
    "vulnerability",
    "trauma",
    "self_worth",
    "shame",
    "intimacy_threshold",
    "emotional_guardedness",
    "internal_external_divergence",
}


@dataclass
class PresenceModeEngine:
    """
    Computes presence mode from VDI signals.
    Called once per tick from EVOOrchestrator.
    Output travels through Sacred Chain alongside voice_mode.

    Presence mode is NOT just headcount.
    A small room at identity-moment threshold is more intimate
    than a private session that never got there.
    A packed house that's gone cold is PUBLIC not BROADCAST.
    """

    _current_mode:      str     = PresenceMode.PRIVATE
    _audience_size:     int     = 0
    _identity_ticks:    int     = 0

    def compute(
        self,
        audience_size:  int,
        vdi_score:      float,
        voice_mode:     str,
        is_live_broadcast: bool = False,
        identity_moment_active: bool = False,
    ) -> str:
        """
        Compute presence mode from EVO signals.
        Returns PresenceMode value.
        """
        self._audience_size = audience_size

        # Track identity moment duration
        if identity_moment_active:
            self._identity_ticks += 1
        else:
            self._identity_ticks = 0

        # Live broadcast always at least PUBLIC
        if is_live_broadcast:
            if audience_size > 50:
                self._current_mode = PresenceMode.BROADCAST
            else:
                self._current_mode = PresenceMode.PUBLIC
            return self._current_mode

        # No audience — private or intimate based on emotional depth
        if audience_size == 0:
            # Even alone, identity moment sustained = intimate register
            if self._identity_ticks >= 5 or voice_mode == "identity":
                self._current_mode = PresenceMode.INTIMATE_GROUP
            else:
                self._current_mode = PresenceMode.PRIVATE
            return self._current_mode

        # Small room
        if audience_size <= 6:
            # High VDI + identity moment = intimate regardless of size
            if vdi_score >= 0.72 and self._identity_ticks >= 3:
                self._current_mode = PresenceMode.INTIMATE_GROUP
            else:
                self._current_mode = PresenceMode.PUBLIC
            return self._current_mode

        # Larger audience
        self._current_mode = PresenceMode.PUBLIC
        return self._current_mode

    @property
    def current(self) -> str:
        return self._current_mode


# ─────────────────────────────────────────────────────────────────────────────
# THEORY CONNECTION
# The edges in the graph
# ─────────────────────────────────────────────────────────────────────────────

class ConnectionType(str, Enum):
    SUPPORTS        = "supports"        # A rising pulls B up
    WEAKENS         = "weakens"         # A rising pulls B down
    DESTABILIZES    = "destabilizes"    # A's contradiction spreads to B


@dataclass
class TheoryConnection:
    """
    A directed edge between two theories.
    When the source theory moves, it influences the target theory.

    weight: 0.0–1.0 — how strongly the connection propagates
    directional: True means A→B only, False means A↔B
    """
    connection_id:  str
    source_name:    str
    target_name:    str
    connection_type: str
    weight:         float   = 0.5
    directional:    bool    = True
    notes:          str     = ""

    def propagation_delta(self, source_delta: float) -> float:
        """
        How much confidence change to apply to the target
        given a delta in the source.
        """
        if self.connection_type == ConnectionType.SUPPORTS:
            return source_delta * self.weight
        elif self.connection_type == ConnectionType.WEAKENS:
            return -source_delta * self.weight * 0.7   # Weakening is slightly less potent
        elif self.connection_type == ConnectionType.DESTABILIZES:
            # Destabilization spreads uncertainty — reduces confidence
            # toward 0.5 (maximum uncertainty) rather than toward 0
            return -abs(source_delta) * self.weight * 0.5
        return 0.0

    def to_db_dict(self) -> dict:
        return {
            "connection_id":    self.connection_id,
            "source_name":      self.source_name,
            "target_name":      self.target_name,
            "connection_type":  self.connection_type,
            "weight":           self.weight,
            "directional":      int(self.directional),
            "notes":            self.notes,
        }

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "TheoryConnection":
        return cls(
            connection_id   = row["connection_id"],
            source_name     = row["source_name"],
            target_name     = row["target_name"],
            connection_type = row["connection_type"],
            weight          = row["weight"],
            directional     = bool(row["directional"]),
            notes           = row["notes"] or "",
        )


# ─────────────────────────────────────────────────────────────────────────────
# META-THEORY
# Emerges from clusters. Not asserted — discovered.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MetaTheory:
    """
    A higher-order pattern that emerges when multiple theories
    converge on the same underlying truth.

    Not because any single event said so.
    Because the whole network pointed the same direction.

    MetaTheories are surfaced carefully — only in appropriate
    presence modes, only above confidence threshold.
    They are the most powerful and most delicate outputs
    of the entire system.
    """
    meta_id:            str
    name:               str
    statement:          str
    constituent_theories: List[str]     # Theory names that formed this
    confidence:         float
    convergence_score:  float           # How strongly the cluster agrees
    first_emerged:      str             # session_id
    last_reinforced:    str             # session_id
    presence_floor:     str             = PresenceMode.PRIVATE  # Minimum privacy to surface
    decay_sessions:     float           = 0.0
    notes:              str             = ""

    @property
    def confidence_label(self) -> str:
        if self.confidence >= 0.75:   return "strong"
        if self.confidence >= 0.50:   return "moderate"
        if self.confidence >= 0.30:   return "emerging"
        return "speculative"

    def should_surface(self, presence_mode: str) -> bool:
        """
        Should this meta-theory be included in a briefing
        given the current presence mode?
        """
        mode_order = [
            PresenceMode.BROADCAST,
            PresenceMode.PUBLIC,
            PresenceMode.INTIMATE_GROUP,
            PresenceMode.PRIVATE,
        ]
        current_idx = mode_order.index(presence_mode) if presence_mode in mode_order else 0
        floor_idx   = mode_order.index(self.presence_floor) if self.presence_floor in mode_order else 0
        # Higher index = more private. Must be at least as private as floor.
        return current_idx >= floor_idx

    def effective_confidence(self) -> float:
        """Confidence after decay."""
        half_life = 10.0
        factor = math.pow(0.5, self.decay_sessions / half_life)
        return round(self.confidence * factor, 4)

    def apply_decay(self) -> None:
        self.decay_sessions += 1.0
        self.confidence = self.effective_confidence()

    def to_briefing_block(self, presence_mode: str) -> str:
        if not self.should_surface(presence_mode):
            return ""
        surface_weight = PRESENCE_SURFACE_WEIGHTS.get(presence_mode, 0.5)
        # Only include if surface weight supports the confidence level
        if self.confidence * surface_weight < 0.15:
            return ""
        lines = [
            f"META-PATTERN: {self.statement}",
            f"CONFIDENCE: {self.confidence_label} ({self.confidence:.2f})",
            f"FORMED FROM: {', '.join(self.constituent_theories[:3])}",
        ]
        if len(self.constituent_theories) > 3:
            lines[-1] += f" +{len(self.constituent_theories) - 3} more"
        return "\n".join(lines)

    def to_db_dict(self) -> dict:
        return {
            "meta_id":              self.meta_id,
            "name":                 self.name,
            "statement":            self.statement,
            "constituent_theories": json.dumps(self.constituent_theories),
            "confidence":           self.confidence,
            "convergence_score":    self.convergence_score,
            "first_emerged":        self.first_emerged,
            "last_reinforced":      self.last_reinforced,
            "presence_floor":       self.presence_floor,
            "decay_sessions":       self.decay_sessions,
            "notes":                self.notes,
        }

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "MetaTheory":
        return cls(
            meta_id             = row["meta_id"],
            name                = row["name"],
            statement           = row["statement"],
            constituent_theories = json.loads(row["constituent_theories"]),
            confidence          = row["confidence"],
            convergence_score   = row["convergence_score"],
            first_emerged       = row["first_emerged"],
            last_reinforced     = row["last_reinforced"],
            presence_floor      = row["presence_floor"],
            decay_sessions      = row["decay_sessions"],
            notes               = row["notes"] or "",
        )


# ─────────────────────────────────────────────────────────────────────────────
# META-THEORY TEMPLATES
# Patterns the graph watches for. Emerge from theory clusters.
# ─────────────────────────────────────────────────────────────────────────────

META_THEORY_TEMPLATES = [
    {
        "name":         "creative_identity_emotionally_loaded",
        "statement":    "Creative identity is emotionally significant — creative discussions consistently activate deeper emotional patterns",
        "requires":     ["creative_insecurity_recurrence", "humor_as_defense_mechanism", "topic_avoidance_signature"],
        "min_confidence": 0.40,     # avg confidence of constituents required
        "presence_floor": PresenceMode.INTIMATE_GROUP,
    },
    {
        "name":         "vulnerability_is_managed",
        "statement":    "Vulnerability is actively managed rather than naturally expressed — a consistent pattern of approach and retreat",
        "requires":     ["humor_as_defense_mechanism", "topic_avoidance_signature", "intimacy_threshold_exists"],
        "min_confidence": 0.45,
        "presence_floor": PresenceMode.PRIVATE,
    },
    {
        "name":         "high_internal_external_gap",
        "statement":    "There is a significant and consistent gap between presented state and internal state",
        "requires":     ["creative_insecurity_recurrence", "humor_as_defense_mechanism"],
        "also_requires_contradiction_topic": "emotional_state",
        "min_confidence": 0.40,
        "presence_floor": PresenceMode.PRIVATE,
    },
    {
        "name":         "analytical_anchor",
        "statement":    "Analytical and technical engagement serves as emotional anchor — peak stability occurs during intellectual content",
        "requires":     ["high_analytical_engagement", "frustration_escalation_pattern"],
        "min_confidence": 0.45,
        "presence_floor": PresenceMode.INTIMATE_GROUP,
    },
    {
        "name":         "trust_is_earned_slowly",
        "statement":    "Trust builds slowly and non-linearly — intimacy advances in steps with retreats between them",
        "requires":     ["intimacy_threshold_exists", "topic_avoidance_signature"],
        "min_confidence": 0.50,
        "presence_floor": PresenceMode.PRIVATE,
    },
    {
        "name":         "performer_and_person_in_tension",
        "statement":    "The performed self and the private self are in active tension — the performance is partly protective",
        "requires":     ["humor_as_defense_mechanism", "frustration_escalation_pattern", "intimacy_threshold_exists"],
        "min_confidence": 0.42,
        "presence_floor": PresenceMode.PRIVATE,
    },
]

# Minimum number of constituent theories with sufficient confidence
META_CLUSTER_THRESHOLD = 3
META_CONFIDENCE_FLOOR   = 0.20     # MetaTheories below this are archived


# ─────────────────────────────────────────────────────────────────────────────
# DEFAULT THEORY CONNECTIONS
# The wiring that comes pre-loaded.
# New connections emerge from distillation.
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_CONNECTIONS = [
    # Creative insecurity → humor defense (supports)
    ("creative_insecurity_recurrence",  "humor_as_defense_mechanism",
     ConnectionType.SUPPORTS, 0.65, True),

    # Humor defense → topic avoidance (supports)
    ("humor_as_defense_mechanism",      "topic_avoidance_signature",
     ConnectionType.SUPPORTS, 0.55, True),

    # Topic avoidance weakens intimacy threshold theory
    ("topic_avoidance_signature",       "intimacy_threshold_exists",
     ConnectionType.WEAKENS, 0.45, True),

    # Frustration escalation → creative insecurity (supports when co-present)
    ("frustration_escalation_pattern",  "creative_insecurity_recurrence",
     ConnectionType.SUPPORTS, 0.40, True),

    # High analytical engagement weakens frustration escalation
    ("high_analytical_engagement",      "frustration_escalation_pattern",
     ConnectionType.WEAKENS, 0.50, True),

    # Intimacy threshold ↔ humor defense (bidirectional, weakens)
    # When genuine intimacy is confirmed, humor-as-defense weakens
    ("intimacy_threshold_exists",       "humor_as_defense_mechanism",
     ConnectionType.WEAKENS, 0.55, False),  # bidirectional

    # Emotional guardedness supports topic avoidance
    ("emotional_guardedness_pattern",   "topic_avoidance_signature",
     ConnectionType.SUPPORTS, 0.70, True),

    # Internal/external divergence destabilizes all self-report adjacent theories
    ("internal_external_state_divergence", "creative_insecurity_recurrence",
     ConnectionType.DESTABILIZES, 0.40, True),

    ("internal_external_state_divergence", "humor_as_defense_mechanism",
     ConnectionType.DESTABILIZES, 0.35, True),
]


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA
# ─────────────────────────────────────────────────────────────────────────────

THEORY_GRAPH_SCHEMA = """
CREATE TABLE IF NOT EXISTS theory_connections (
    connection_id   TEXT PRIMARY KEY,
    source_name     TEXT NOT NULL,
    target_name     TEXT NOT NULL,
    connection_type TEXT NOT NULL,
    weight          REAL DEFAULT 0.5,
    directional     INTEGER DEFAULT 1,
    notes           TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS meta_theories (
    meta_id                 TEXT PRIMARY KEY,
    name                    TEXT UNIQUE NOT NULL,
    statement               TEXT NOT NULL,
    constituent_theories    TEXT NOT NULL,
    confidence              REAL DEFAULT 0.0,
    convergence_score       REAL DEFAULT 0.0,
    first_emerged           TEXT DEFAULT '',
    last_reinforced         TEXT DEFAULT '',
    presence_floor          TEXT DEFAULT 'private',
    decay_sessions          REAL DEFAULT 0.0,
    notes                   TEXT DEFAULT '',
    archived                INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_connections_source ON theory_connections(source_name);
CREATE INDEX IF NOT EXISTS idx_connections_target ON theory_connections(target_name);
CREATE INDEX IF NOT EXISTS idx_meta_active        ON meta_theories(archived, confidence DESC);
"""


# ─────────────────────────────────────────────────────────────────────────────
# THEORY GRAPH
# ─────────────────────────────────────────────────────────────────────────────

class TheoryGraph:
    """
    The network that makes theories reason together.

    Theories are nodes. Connections are edges.
    When one theory moves, its neighbors feel it.
    When clusters converge, meta-theories emerge.

    The graph doesn't override the EvidenceLayer —
    it amplifies and connects what the EvidenceLayer produces.

    Presence mode shapes what gets surfaced, not what gets computed.
    The full picture is always maintained internally.
    What the crew sees depends on who's in the room.
    """

    def __init__(
        self,
        db_path:        Path = DB_PATH,
        session_id:     str  = "",
    ):
        self.db_path        = db_path
        self.session_id     = session_id or f"session_{int(time.time())}"

        # Live state — loaded from DB + updated in session
        self._theories:     Dict[str, Any]              = {}    # name → EvidenceTheory
        self._connections:  Dict[str, List[TheoryConnection]] = {}  # source → connections
        self._meta_theories: Dict[str, MetaTheory]      = {}

        # Propagation damping — prevents infinite loops
        self._propagation_depth_limit = 3

        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._load_connections()
        self._load_meta_theories()

        logger.info(f"[TheoryGraph] Initialized — session {self.session_id}")

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def register_theories(self, theories: Dict[str, Any]) -> None:
        """
        Register the active EvidenceTheory objects from EvidenceLayer.
        Called after EvidenceLayer.load_state().
        The graph doesn't own theories — it references them.
        """
        self._theories = theories
        logger.debug(f"[TheoryGraph] Registered {len(theories)} theories")

    def connect(
        self,
        source_name:        str,
        target_name:        str,
        connection_type:    str,
        weight:             float   = 0.5,
        directional:        bool    = True,
        notes:              str     = "",
    ) -> TheoryConnection:
        """
        Create a connection between two theories.
        If bidirectional, creates both directions.
        """
        conn = TheoryConnection(
            connection_id   = str(uuid.uuid4()),
            source_name     = source_name,
            target_name     = target_name,
            connection_type = connection_type,
            weight          = weight,
            directional     = directional,
            notes           = notes,
        )

        if source_name not in self._connections:
            self._connections[source_name] = []
        self._connections[source_name].append(conn)

        if not directional:
            reverse = TheoryConnection(
                connection_id   = str(uuid.uuid4()),
                source_name     = target_name,
                target_name     = source_name,
                connection_type = connection_type,
                weight          = weight,
                directional     = True,
                notes           = f"reverse of {conn.connection_id}",
            )
            if target_name not in self._connections:
                self._connections[target_name] = []
            self._connections[target_name].append(reverse)
            self._persist_connection(reverse)

        self._persist_connection(conn)
        return conn

    def propagate(
        self,
        theory_name:    str,
        delta:          float,
        depth:          int = 0,
        visited:        Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """
        Propagate a confidence change through the graph.

        When theory A changes by delta, its connected theories
        receive a proportional influence.

        Uses depth limiting and visited set to prevent loops.
        Returns dict of {theory_name: applied_delta} for logging.
        """
        if depth >= self._propagation_depth_limit:
            return {}
        if visited is None:
            visited = set()
        if theory_name in visited:
            return {}

        visited.add(theory_name)
        applied: Dict[str, float] = {}

        connections = self._connections.get(theory_name, [])
        for conn in connections:
            target_name = conn.target_name
            if target_name in visited:
                continue

            target = self._theories.get(target_name)
            if not target:
                continue

            prop_delta = conn.propagation_delta(delta)
            if abs(prop_delta) < 0.005:
                continue    # Too small to matter — don't propagate noise

            # Apply to target theory
            old_confidence = target.confidence
            if prop_delta > 0:
                # Strengthening — asymptotic
                gain = prop_delta * (1.0 - target.confidence) * 0.5
                target.confidence = min(0.97, target.confidence + gain)
            else:
                # Weakening
                loss = abs(prop_delta) * target.confidence * 0.4
                target.confidence = max(0.0, target.confidence - loss)

            actual_delta = target.confidence - old_confidence
            applied[target_name] = round(actual_delta, 4)

            logger.debug(
                f"[TheoryGraph] Propagate: {theory_name} → {target_name} "
                f"({conn.connection_type}) Δ={actual_delta:+.3f}"
            )

            # Recurse with damped delta
            if abs(actual_delta) > 0.01:
                sub_applied = self.propagate(
                    target_name,
                    actual_delta * 0.6,   # damping factor
                    depth + 1,
                    visited,
                )
                applied.update(sub_applied)

        return applied

    def detect_clusters(self) -> List[List[str]]:
        """
        Find clusters of mutually reinforcing theories.
        A cluster is a set of theories where each pair has
        a SUPPORTS connection (direct or transitive) and
        all have confidence above a minimum threshold.

        Returns list of clusters (each cluster = list of theory names).
        """
        MIN_CLUSTER_CONFIDENCE = 0.25
        MIN_CLUSTER_SIZE = 2

        # Build adjacency from SUPPORTS connections only
        supports_graph: Dict[str, Set[str]] = {}
        for source, conns in self._connections.items():
            for conn in conns:
                if conn.connection_type == ConnectionType.SUPPORTS:
                    if source not in supports_graph:
                        supports_graph[source] = set()
                    supports_graph[source].add(conn.target_name)

        # Find connected components above confidence threshold
        active_theories = {
            name for name, theory in self._theories.items()
            if theory.confidence >= MIN_CLUSTER_CONFIDENCE
        }

        visited: Set[str] = set()
        clusters: List[List[str]] = []

        def dfs(node: str, cluster: List[str]) -> None:
            if node in visited or node not in active_theories:
                return
            visited.add(node)
            cluster.append(node)
            for neighbor in supports_graph.get(node, set()):
                dfs(neighbor, cluster)

        for theory_name in active_theories:
            if theory_name not in visited:
                cluster: List[str] = []
                dfs(theory_name, cluster)
                if len(cluster) >= MIN_CLUSTER_SIZE:
                    clusters.append(cluster)

        clusters.sort(key=len, reverse=True)
        return clusters

    def evaluate_meta_theories(self, session_id: str) -> List[MetaTheory]:
        """
        Check if any meta-theory templates are satisfied by
        current theory confidence levels.

        Called during distillation — not on hot path.
        Returns list of newly formed or reinforced meta-theories.
        """
        formed: List[MetaTheory] = []

        for template in META_THEORY_TEMPLATES:
            name        = template["name"]
            requires    = template["requires"]
            min_conf    = template["min_confidence"]

            # Check all required theories exist and meet confidence
            qualifying = []
            for theory_name in requires:
                theory = self._theories.get(theory_name)
                if theory and theory.confidence >= min_conf:
                    qualifying.append(theory_name)

            if len(qualifying) < min(META_CLUSTER_THRESHOLD, len(requires)):
                continue

            # Check optional contradiction requirement
            if "also_requires_contradiction_topic" in template:
                # This would be checked against ContradictionEngine
                # For now we proceed — contradiction check is advisory
                pass

            # Compute convergence score — avg confidence of constituents
            avg_conf = sum(
                self._theories[t].confidence
                for t in qualifying
                if t in self._theories
            ) / len(qualifying)

            convergence = round(avg_conf * (len(qualifying) / len(requires)), 4)

            if name in self._meta_theories:
                # Reinforce existing
                mt = self._meta_theories[name]
                mt.confidence = min(0.95, mt.confidence + convergence * 0.2)
                mt.convergence_score = convergence
                mt.last_reinforced = session_id
                mt.decay_sessions = 0.0
                formed.append(mt)
                logger.info(
                    f"[TheoryGraph] MetaTheory reinforced: {name} "
                    f"({mt.confidence:.2f})"
                )
            else:
                # New meta-theory emerging
                mt = MetaTheory(
                    meta_id             = str(uuid.uuid4()),
                    name                = name,
                    statement           = template["statement"],
                    constituent_theories = qualifying,
                    confidence          = min(0.40, convergence),
                    convergence_score   = convergence,
                    first_emerged       = session_id,
                    last_reinforced     = session_id,
                    presence_floor      = template.get(
                        "presence_floor", PresenceMode.PRIVATE
                    ),
                )
                self._meta_theories[name] = mt
                formed.append(mt)
                logger.info(
                    f"[TheoryGraph] MetaTheory emerged: {name} "
                    f"({mt.confidence:.2f}) from {qualifying}"
                )

        return formed

    def get_meta_theories(
        self,
        presence_mode:  str = PresenceMode.PRIVATE,
        min_confidence: float = 0.20,
    ) -> List[MetaTheory]:
        """
        Return active meta-theories appropriate for the presence mode.
        Filtered by both confidence and presence floor.
        """
        result = [
            mt for mt in self._meta_theories.values()
            if mt.effective_confidence() >= min_confidence
            and mt.should_surface(presence_mode)
        ]
        result.sort(key=lambda m: m.effective_confidence(), reverse=True)
        return result

    def get_briefing(
        self,
        presence_mode:  str     = PresenceMode.PRIVATE,
        max_theories:   int     = 3,
        max_meta:       int     = 2,
    ) -> str:
        """
        Build a complete theory briefing for the crew.
        Presence mode shapes what's included.
        More delicate in public. Full depth in private.
        """
        surface_weight = PRESENCE_SURFACE_WEIGHTS.get(presence_mode, 0.5)
        lines: List[str] = []

        # Meta-theories first — they're the most powerful insight
        meta = self.get_meta_theories(presence_mode)[:max_meta]
        if meta:
            lines.append("[DEEP PATTERNS]")
            for mt in meta:
                block = mt.to_briefing_block(presence_mode)
                if block:
                    lines.append("")
                    lines.append(block)

        # Active theory clusters
        clusters = self.detect_clusters()
        if clusters and clusters[0]:
            dominant_cluster = clusters[0]
            lines.append("")
            lines.append(f"[ACTIVE CLUSTER: {len(dominant_cluster)} theories converging]")
            for theory_name in dominant_cluster[:3]:
                theory = self._theories.get(theory_name)
                if theory:
                    # Suppress private theories in public contexts
                    if any(tag in theory_name for tag in PRIVATE_ONLY_THEORY_TAGS):
                        if surface_weight < 0.6:
                            continue
                    if theory.confidence >= 0.20:
                        lines.append(
                            f"  {theory.statement} "
                            f"({theory.confidence_label}, {theory.confidence:.2f})"
                        )

        # Presence mode note for crew
        if presence_mode in (PresenceMode.PUBLIC, PresenceMode.BROADCAST):
            lines.append("")
            lines.append(
                f"[PRESENCE: {presence_mode.upper()} — "
                f"deep emotional content withheld from briefing]"
            )

        return "\n".join(lines) if lines else ""

    def distill(self, session_id: str) -> None:
        """
        End-of-session graph maintenance.
        Evaluate meta-theories, apply decay, archive weak ones, persist.
        """
        logger.info(f"[TheoryGraph] Distilling session {session_id}")

        # Evaluate meta-theory templates
        self.evaluate_meta_theories(session_id)

        # Apply decay to meta-theories not reinforced this session
        for mt in self._meta_theories.values():
            if mt.last_reinforced != session_id:
                mt.apply_decay()

        # Archive weak meta-theories
        archived = 0
        for mt in self._meta_theories.values():
            if mt.effective_confidence() < META_CONFIDENCE_FLOOR:
                self._archive_meta_theory(mt.meta_id)
                archived += 1

        # Persist
        self._persist_all_meta_theories()

        active_meta = len(self.get_meta_theories())
        active_clusters = len(self.detect_clusters())
        logger.info(
            f"[TheoryGraph] Distillation complete — "
            f"{active_meta} meta-theories, "
            f"{active_clusters} clusters, "
            f"{archived} archived"
        )

    # =========================================================================
    # INITIALIZATION
    # =========================================================================

    def _seed_connections(self) -> None:
        """Load default connections if not already in DB."""
        with self._db() as conn:
            for src, tgt, ctype, weight, directional in DEFAULT_CONNECTIONS:
                existing = conn.execute("""
                    SELECT connection_id FROM theory_connections
                    WHERE source_name = ? AND target_name = ?
                """, (src, tgt)).fetchone()

                if not existing:
                    self.connect(src, tgt, ctype, weight, directional)

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    def _load_connections(self) -> None:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM theory_connections"
            ).fetchall()

        for row in rows:
            c = TheoryConnection.from_db_row(row)
            if c.source_name not in self._connections:
                self._connections[c.source_name] = []
            self._connections[c.source_name].append(c)

        if not self._connections:
            self._seed_connections()

        logger.debug(
            f"[TheoryGraph] Loaded connections for "
            f"{len(self._connections)} source theories"
        )

    def _load_meta_theories(self) -> None:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT * FROM meta_theories WHERE archived = 0"
            ).fetchall()

        for row in rows:
            mt = MetaTheory.from_db_row(row)
            self._meta_theories[mt.name] = mt

        logger.debug(
            f"[TheoryGraph] Loaded {len(self._meta_theories)} meta-theories"
        )

    def _persist_connection(self, conn: TheoryConnection) -> None:
        with self._db() as db:
            d = conn.to_db_dict()
            db.execute("""
                INSERT OR REPLACE INTO theory_connections
                    (connection_id, source_name, target_name,
                     connection_type, weight, directional, notes)
                VALUES
                    (:connection_id, :source_name, :target_name,
                     :connection_type, :weight, :directional, :notes)
            """, d)

    def _persist_all_meta_theories(self) -> None:
        for mt in self._meta_theories.values():
            self._persist_meta_theory(mt)

    def _persist_meta_theory(self, mt: MetaTheory) -> None:
        with self._db() as conn:
            d = mt.to_db_dict()
            conn.execute("""
                INSERT OR REPLACE INTO meta_theories
                    (meta_id, name, statement, constituent_theories,
                     confidence, convergence_score, first_emerged,
                     last_reinforced, presence_floor, decay_sessions,
                     notes, archived)
                VALUES
                    (:meta_id, :name, :statement, :constituent_theories,
                     :confidence, :convergence_score, :first_emerged,
                     :last_reinforced, :presence_floor, :decay_sessions,
                     :notes, 0)
            """, d)

    def _archive_meta_theory(self, meta_id: str) -> None:
        with self._db() as conn:
            conn.execute(
                "UPDATE meta_theories SET archived = 1 WHERE meta_id = ?",
                (meta_id,)
            )

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"[TheoryGraph] DB error: {e}")
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._db() as conn:
            conn.executescript(THEORY_GRAPH_SCHEMA)


# ─────────────────────────────────────────────────────────────────────────────
# FACTORY
# ─────────────────────────────────────────────────────────────────────────────

def create_theory_graph(
    session_id: str,
    db_path:    Path = DB_PATH,
) -> Tuple[TheoryGraph, PresenceModeEngine]:
    """
    Factory. Returns wired (TheoryGraph, PresenceModeEngine) pair.

    Usage in EVOOrchestrator:

        graph, presence_engine = create_theory_graph(session_id)
        graph.register_theories(evidence_layer._active_theories)

        # In tick():
        presence_mode = presence_engine.compute(
            audience_size, vdi_score, voice_mode,
            is_live_broadcast, identity_moment_active
        )

        # After evidence layer propagates a theory change:
        graph.propagate(changed_theory_name, confidence_delta)

        # In crew briefing:
        briefing = graph.get_briefing(presence_mode)

        # On session end:
        graph.distill(session_id)
    """
    graph   = TheoryGraph(db_path=db_path, session_id=session_id)
    engine  = PresenceModeEngine()
    return graph, engine
