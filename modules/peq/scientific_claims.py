from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, Sequence, Tuple

from .clinical_evidence import SourceRecord


_HIGH_AUTHORITY_TYPES = {
    "peer_reviewed_meta_analysis",
    "peer_reviewed_network_meta_analysis",
    "peer_reviewed_umbrella_review",
    "clinical_practice_guideline",
    "professional_practice_guideline",
    "international_clinical_guideline",
    "psychometric_meta_analysis",
    "peer_reviewed_systematic_review",
    "peer_reviewed_review",
    "large_longitudinal_cohort",
    "national_probability_panel",
    "national_population_exam_survey",
    "national_population_survey",
    "large_diverse_us_cohort",
    "federal_clinical_education",
    "federal_health_information",
    "federal_guidance",
}


@dataclass(frozen=True)
class ClaimEvidence:
    """A source's relationship to a specific proposition.

    This records *how* a source bears on the claim rather than treating every
    source as a vote. Independence is explicit because multiple papers can reuse
    the same underlying cohort or evidence base.
    """

    source_id: str
    role: str  # support | replication | dissent | null | methodological_critique
    effect: float = 0.0  # signed directional effect on the proposition [-1, 1]
    quality: float = 0.5
    independent_group: str = ""
    peer_reviewed: bool = False
    directly_tests_claim: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        role = str(self.role).strip().lower()
        if role not in {"support", "replication", "dissent", "null", "methodological_critique"}:
            raise ValueError(f"unsupported claim-evidence role: {self.role}")
        if not self.source_id.strip():
            raise ValueError("source_id is required")
        for name in ("effect", "quality"):
            value = float(getattr(self, name))
            if not value == value or value in (float("inf"), float("-inf")):
                raise ValueError(f"{name} must be finite")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "effect", max(-1.0, min(1.0, float(self.effect))))
        object.__setattr__(self, "quality", max(0.0, min(1.0, float(self.quality))))

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ScientificClaim:
    """A proposition plus its independently characterized evidence base."""

    claim_id: str
    proposition: str
    evidence: Tuple[ClaimEvidence, ...] = ()
    scope: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.claim_id.strip():
            raise ValueError("claim_id is required")
        if not self.proposition.strip():
            raise ValueError("proposition is required")

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ScientificClaimAssessment:
    """Evidence-base assessment; it is not a determination that the proposition is true."""
    source_id: str = ""
    proposition: str = ""
    evidence_quality: float = 0.0
    operational_readiness: float = 0.0
    status: str = "reference_only"
    strengths: Sequence[str] = ()
    limitations: Sequence[str] = ()
    warnings: Sequence[str] = ()
    claim_id: str = ""
    support_strength: float = 0.0
    dissent_strength: float = 0.0
    replication_strength: float = 0.0
    contradiction_strength: float = 0.0
    independent_support_groups: int = 0
    independent_dissent_groups: int = 0
    evidence_count: int = 0
    evidence_summary: Sequence[str] = ()

    def to_dict(self):
        return asdict(self)


def _source_authority(source: SourceRecord) -> float:
    return {
        "peer_reviewed_meta_analysis": 1.0,
        "peer_reviewed_network_meta_analysis": 1.0,
        "peer_reviewed_umbrella_review": 1.0,
        "clinical_practice_guideline": 0.98,
        "professional_practice_guideline": 0.98,
        "international_clinical_guideline": 0.97,
        "psychometric_meta_analysis": 0.96,
        "psychometric_review": 0.95,
        "peer_reviewed_systematic_review": 0.96,
        "peer_reviewed_review": 0.92,
        "validated_measure": 0.90,
        "large_longitudinal_cohort": 0.90,
        "large_diverse_us_cohort": 0.89,
        "national_probability_panel": 0.88,
        "national_population_exam_survey": 0.87,
        "national_population_survey": 0.86,
        "federal_clinical_education": 0.83,
        "federal_health_information": 0.82,
        "federal_guidance": 0.82,
    }.get(source.source_type, 0.50)


def _quality_for_evidence(source: SourceRecord, item: ClaimEvidence) -> float:
    base = _source_authority(source)
    if source.limitations:
        base -= min(0.45, 0.04 * len(source.limitations))
    if item.peer_reviewed:
        base = min(1.0, base + 0.03)
    if not item.directly_tests_claim:
        base *= 0.65
    return max(0.0, min(1.0, min(base, item.quality if item.quality > 0 else base)))


def assess_scientific_claim(
    source: SourceRecord,
    *,
    proposition: str,
    actionable: bool = False,
    dangerous_if_wrong: bool = False,
) -> ScientificClaimAssessment:
    """Assess one source's suitability for a proposition.

    This is intentionally source-quality assessment, not proposition truth and not
    a diagnostic determination.
    """
    if not proposition or not proposition.strip():
        raise ValueError("proposition is required")

    authority = _source_authority(source)
    limitation_penalty = min(0.45, 0.06 * len(source.limitations))
    quality = max(0.0, min(1.0, authority - limitation_penalty))
    warnings = []
    strengths = [f"source type: {source.source_type}", f"evidentiary role: {source.evidentiary_role}"]

    if source.limitations:
        warnings.extend(str(x) for x in source.limitations)

    if dangerous_if_wrong:
        readiness = 0.0
        status = "reference_only_high_stakes"
        warnings.append("High-stakes use requires stronger independent verification before operationalization.")
    elif actionable and quality >= 0.85:
        readiness = min(0.85, quality)
        status = "provisional_actionable"
    elif actionable:
        readiness = min(0.60, quality)
        status = "reference_only_insufficient_evidence"
    else:
        readiness = 0.0
        status = "reference_only"

    return ScientificClaimAssessment(
        source_id=source.source_id,
        proposition=proposition.strip(),
        evidence_quality=round(quality, 4),
        operational_readiness=round(readiness, 4),
        status=status,
        strengths=tuple(strengths),
        limitations=tuple(source.limitations),
        warnings=tuple(warnings),
    )


def assess_scientific_claim_set(
    claim: ScientificClaim,
    sources: Dict[str, SourceRecord],
    *,
    actionable: bool = False,
    dangerous_if_wrong: bool = False,
) -> ScientificClaimAssessment:
    """Assess a multi-source claim while preserving support, replication and dissent."""
    if not claim.evidence:
        return ScientificClaimAssessment(
            claim_id=claim.claim_id,
            proposition=claim.proposition,
            status="reference_only_insufficient_evidence" if actionable else "reference_only",
            warnings=("No evidence records supplied for the proposition.",),
        )

    support = 0.0
    dissent = 0.0
    replication = 0.0
    contradiction = 0.0
    support_groups = set()
    dissent_groups = set()
    summaries = []
    strengths = []
    limitations = []

    seen_sources = set()
    for item in claim.evidence:
        if item.source_id in seen_sources:
            summaries.append(f"duplicate source ignored: {item.source_id}")
            continue
        seen_sources.add(item.source_id)
        source = sources.get(item.source_id)
        if source is None:
            summaries.append(f"unresolved source: {item.source_id}")
            continue
        quality = _quality_for_evidence(source, item)
        magnitude = abs(item.effect) * quality
        # Dissent only counts as a meaningful challenge when it has professional/peer-reviewed
        # standing and directly bears on the proposition.
        professionally_valid = item.peer_reviewed or source.source_type in _HIGH_AUTHORITY_TYPES
        if item.role in {"support", "replication"} and item.effect > 0 and professionally_valid:
            support += magnitude
            group = item.independent_group or f"source:{item.source_id}"
            support_groups.add(group)
            if item.role == "replication":
                replication += magnitude
        elif item.role in {"dissent", "methodological_critique"} and item.effect < 0 and professionally_valid:
            dissent += magnitude
            contradiction += magnitude
            group = item.independent_group or f"source:{item.source_id}"
            dissent_groups.add(group)
        elif item.role == "null":
            contradiction += magnitude * 0.75
        elif item.effect < 0 and professionally_valid:
            contradiction += magnitude

        summaries.append(
            f"{item.role}: {item.source_id} quality={quality:.2f} independent_group={item.independent_group or 'unspecified'}"
        )
        strengths.append(f"{source.title} ({source.year})")
        limitations.extend(str(x) for x in source.limitations)

    total_direction = support - contradiction
    evidence_quality = min(1.0, max(0.0, 0.5 + 0.12 * (support + max(0.0, replication) - 0.75 * dissent)))

    if dangerous_if_wrong:
        readiness = 0.0
        status = "reference_only_high_stakes"
    elif support <= 0.0:
        readiness = 0.0 if not actionable else min(0.25, evidence_quality)
        status = "reference_only_insufficient_evidence"
    elif dissent > support * 0.45:
        readiness = 0.0 if dangerous_if_wrong else min(0.55 if actionable else 0.0, evidence_quality)
        status = "provisionally_contested"
    elif len(support_groups) >= 2 and replication > 0.25 and support > contradiction * 1.5:
        readiness = min(0.90, evidence_quality) if actionable else 0.0
        status = "independently_supported"
    elif support > contradiction:
        readiness = min(0.70, evidence_quality) if actionable else 0.0
        status = "supported_with_limitations"
    else:
        readiness = 0.0
        status = "reference_only"

    if dissent:
        warnings = ["Professionally credible dissent or methodological criticism is present and retained."]
    else:
        warnings = []
    if len(support_groups) < 2 and support > 0:
        warnings.append("Support is not independently replicated across multiple evidence groups.")
    if contradiction:
        warnings.append("Contradictory or null evidence materially reduces confidence.")

    return ScientificClaimAssessment(
        claim_id=claim.claim_id,
        proposition=claim.proposition,
        evidence_quality=round(evidence_quality, 4),
        operational_readiness=round(readiness, 4),
        status=status,
        strengths=tuple(dict.fromkeys(strengths)),
        limitations=tuple(dict.fromkeys(limitations)),
        warnings=tuple(dict.fromkeys(warnings)),
        support_strength=round(support, 4),
        dissent_strength=round(dissent, 4),
        replication_strength=round(replication, 4),
        contradiction_strength=round(contradiction, 4),
        independent_support_groups=len(support_groups),
        independent_dissent_groups=len(dissent_groups),
        evidence_count=len(seen_sources),
        evidence_summary=tuple(summaries),
    )
