from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

from .models import EvidenceContribution, EvidenceDomain
from .retrieval import RetrievedEvidence


@dataclass(frozen=True)
class ScientificClaimPromotion:
    """Explicit, auditable promotion of a retrieved scientific source into PEQ evidence.

    Retrieval alone never becomes state evidence. A caller must supply a proposition,
    a state-specific direction map, and an explicit verification flag. The default
    path therefore remains reference-only.
    """

    evidence: RetrievedEvidence
    proposition: str
    verified_claim: bool
    state_directions: Mapping[str, float]
    strength: float
    reliability: float
    rationale: str
    provenance: str

    def promote(self) -> EvidenceContribution:
        if not self.verified_claim:
            raise ValueError("Scientific evidence cannot be promoted without an explicitly verified claim.")
        if not self.proposition.strip():
            raise ValueError("A non-empty proposition is required for scientific evidence promotion.")
        if not self.state_directions:
            raise ValueError("state-specific directions are required; retrieval cannot infer them implicitly.")

        clean = {}
        for state, direction in self.state_directions.items():
            try:
                value = float(direction)
            except (TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(value):
                clean[str(state)] = max(-1.0, min(1.0, value))
        if not clean:
            raise ValueError("No finite state-specific evidence directions were supplied.")

        return EvidenceContribution(
            source_id=self.evidence.evidence_id,
            domain=EvidenceDomain.GENERAL_KNOWLEDGE,
            statement=self.proposition,
            direction=0.0,
            strength=max(0.0, min(1.0, float(self.strength))),
            reliability=max(0.0, min(1.0, float(self.reliability))),
            provenance=self.provenance or self.evidence.claim_or_scope,
            state_directions=clean,
        )


def promote_scientific_evidence(
    evidence: RetrievedEvidence,
    *,
    proposition: str,
    state_directions: Mapping[str, float],
    verified_claim: bool = False,
    strength: float = 0.5,
    reliability: float = 0.5,
    rationale: str = "Explicitly promoted from retrieved scientific evidence.",
) -> EvidenceContribution:
    """Promote a retrieved source into PEQ state evidence only by explicit request."""
    promotion = ScientificClaimPromotion(
        evidence=evidence,
        proposition=proposition,
        verified_claim=verified_claim,
        state_directions=state_directions,
        strength=strength,
        reliability=reliability,
        rationale=rationale,
        provenance=(
            f"{evidence.evidence_id}; source_types={','.join(evidence.source_types)}; "
            f"automation_status={evidence.automation_status}"
        ),
    )
    return promotion.promote()
