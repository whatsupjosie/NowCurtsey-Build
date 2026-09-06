from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import math
from typing import Any, Dict, List, Optional


MAX_OPERATIONAL_CONFIDENCE = 0.985


class EvidenceDomain(str, Enum):
    GENERAL_KNOWLEDGE = "general_knowledge"
    POPULATION_BASELINE = "population_baseline"
    INDIVIDUAL_BASELINE = "individual_baseline"
    SITUATION = "situation"
    HISTORY = "history"
    CURRENT = "current"
    TRUTH_TEST = "truth_test"


class TruthStatus(str, Enum):
    NOT_EVALUATED = "not_evaluated"
    SUPPORTED = "supported"
    CONTESTED = "contested"
    INCONCLUSIVE = "inconclusive"


class ResponseModulation(str, Enum):
    FULL = "full"
    RESTRAINED = "restrained"
    CONSERVATIVE = "conservative"


@dataclass(frozen=True)
class EvidenceContribution:
    source_id: str
    domain: EvidenceDomain
    statement: str
    direction: float
    strength: float
    reliability: float = 1.0
    provenance: str = ""
    state_directions: Dict[str, float] = field(default_factory=dict)
    correlation_group: str = ""

    def effective_weight(self, state: str | None = None) -> float:
        selected = self.direction if state is None else self.state_directions.get(state, self.direction)
        try:
            selected = float(selected)
            strength = float(self.strength)
            reliability = float(self.reliability)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        if not all(math.isfinite(v) for v in (selected, strength, reliability)):
            return 0.0
        selected = max(-1.0, min(1.0, selected))
        strength = max(0.0, min(1.0, strength))
        reliability = max(0.0, min(1.0, reliability))
        return selected * strength * reliability


@dataclass(frozen=True)
class TruthAssessment:
    status: TruthStatus
    proposition: str
    reliability: float
    reasons_for_review: List[str] = field(default_factory=list)
    tests_run: List[Dict[str, Any]] = field(default_factory=list)
    unresolved_questions: List[str] = field(default_factory=list)
    source_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StateCandidate:
    state: str
    prior: float
    posterior_score: float
    operational_confidence: float
    supporting: List[str] = field(default_factory=list)
    weakening: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PEQStateResult:
    proposition: str
    leading_state: str
    formal_determination: str
    operational_confidence: float
    uncertainty: float
    confidence_note: str
    candidates: List[StateCandidate]
    contributions: List[EvidenceContribution]
    truth_assessment: TruthAssessment
    assumptions: List[str]
    unresolved_questions: List[str]
    explanation: str
    posterior_distribution: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResponseCandidate:
    response: str
    score: float
    rationale: str


@dataclass(frozen=True)
class PEQResponseResult:
    question: str
    recommended_response: str
    operational_confidence: float
    modulation: ResponseModulation
    intensity: float
    candidates: List[ResponseCandidate]
    rationale: str
    explanation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PEQResult:
    state: PEQStateResult
    response: PEQResponseResult
    audit: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
