from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class EvidenceKind(str, Enum):
    DIRECT_REPORT = "direct_report"
    OBSERVATION = "observation"
    DERIVED = "derived"
    CONTEXT = "context"
    PROFILE = "profile"
    PRIOR = "prior"
    TEST_RESULT = "test_result"


class DeterminationStatus(str, Enum):
    COGENT = "cogent"
    INCONCLUSIVE = "inconclusive"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class Baseline:
    typing_wpm: Optional[float] = None
    response_latency_s: Optional[float] = None
    typo_rate: Optional[float] = None
    avg_message_words: Optional[float] = None
    punctuation_intensity: Optional[float] = None
    capitalization_ratio: Optional[float] = None
    verbosity_score: Optional[float] = None
    notes: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ObservationPacket:
    subject_id: str
    is_primary_user: Optional[bool]
    text: str = ""
    recent_text: List[str] = field(default_factory=list)
    typing: Dict[str, float] = field(default_factory=dict)
    audio: Dict[str, float] = field(default_factory=dict)
    vision: Dict[str, float] = field(default_factory=dict)
    explicit_report: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    baseline: Optional[Baseline] = None
    profile_facts: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    kind: EvidenceKind
    label: str
    value: Any
    strength: float
    direction: Dict[str, float] = field(default_factory=dict)
    provenance: str = ""


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    label: str
    score: float
    supporting_evidence: List[str] = field(default_factory=list)
    contradicting_evidence: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    unresolved_questions: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class TestSpec:
    __test__ = False
    test_id: str
    name: str
    purpose: str
    assumption_ids: List[str]
    expected_if: Dict[str, str]
    procedure: str


@dataclass(frozen=True)
class TestResult:
    __test__ = False
    test_id: str
    result: str
    observation: str
    supports: List[str]
    weakens: List[str]
    materiality: float
    notes: str = ""


@dataclass(frozen=True)
class Assumption:
    assumption_id: str
    statement: str
    source: str
    confidence: float
    tested: bool = False
    status: str = "active"


@dataclass
class ReasoningTrace:
    proposition: str
    observations: List[Evidence] = field(default_factory=list)
    assumptions: List[Assumption] = field(default_factory=list)
    hypotheses: List[Hypothesis] = field(default_factory=list)
    tests: List[TestSpec] = field(default_factory=list)
    test_results: List[TestResult] = field(default_factory=list)
    divergences: List[Dict[str, Any]] = field(default_factory=list)
    replication: Dict[str, Any] = field(default_factory=dict)
    unresolved_questions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResponseAppraisal:
    objective: str
    desired_posture: str
    expressive_emotion: str
    intensity: float
    confidence: float
    rationale: str


@dataclass(frozen=True)
class AffectAssessment:
    formal_determination: str
    status: DeterminationStatus
    leading_state: str
    confidence: float
    uncertainty: float
    interpretive_assessment: str
    alternatives: List[Dict[str, Any]]
    response_appraisal: ResponseAppraisal
    trace: ReasoningTrace
    run_id: str = ""
    method_id: str = "deterministic_heuristic_v1"
    confidence_type: str = "uncalibrated_assessed_confidence"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
