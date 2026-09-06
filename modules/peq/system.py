from __future__ import annotations

import uuid
from typing import Any, Dict, Mapping, Sequence

from cre_eq.engine import CriticalReasoningEngine
from cre_eq.models import ObservationPacket, TestResult, TestSpec

from .evaluation import CalibrationCase, CalibrationReport, evaluate_calibration
from .clinical_evidence import (
    PatternHypothesis, evaluate_pattern, list_patterns, list_sources,
    list_population_datasets, list_evidence_items, list_intervention_evidence, all_scientific_sources,
)
from .models import EvidenceContribution, PEQResult, TruthAssessment
from .response import PEQResponseEngine
from .scientific_claims import ScientificClaim, ScientificClaimAssessment, assess_scientific_claim, assess_scientific_claim_set
from .retrieval import PEQEvidenceRetriever, RetrievalRequest
from .state import PEQStateEngine


class PEQSystem:
    """Formal Probabilistic EQ system.

    Question 1: What emotional state is most probable?
    Question 2: Given that state, what response is most appropriate?
    """

    def __init__(self, truth_engine: CriticalReasoningEngine | None = None) -> None:
        self.truth_engine = truth_engine or CriticalReasoningEngine()
        self.state_engine = PEQStateEngine(self.truth_engine)
        self.response_engine = PEQResponseEngine()
        self.evidence_retriever = PEQEvidenceRetriever()

    def available_clinical_sources(self):
        """Return source metadata for the non-diagnostic clinical evidence registry."""
        return list_sources()

    def available_clinical_patterns(self):
        """Return non-diagnostic clinical pattern definitions."""
        return list_patterns()

    def evaluate_clinical_pattern(self, pattern_id: str, observed_signs):
        """Evaluate a clinical-pattern hypothesis without issuing a diagnosis."""
        return evaluate_pattern(pattern_id, observed_signs)

    def available_population_datasets(self):
        """Return curated population/cohort source metadata."""
        return list_population_datasets()

    def available_evidence_items(self):
        """Return validated measurement and peer-reviewed evidence records."""
        return list_evidence_items()

    def available_intervention_evidence(self):
        """Return clinician-level intervention evidence and safe PEQ usage scope."""
        return list_intervention_evidence()

    def all_scientific_sources(self):
        """Return all registered scientific/public-health source records."""
        return all_scientific_sources()

    def retrieve_evidence(self, query: str, *, top_k: int = 12, alternatives_k: int = 5,
                          evidence_types: Sequence[str] = (), source_types: Sequence[str] = (),
                          target_states: Sequence[str] = (), target_pattern_ids: Sequence[str] = ()):
        """Retrieve a diverse evidence bundle without collapsing it into one answer."""
        request = RetrievalRequest(
            query=query, top_k=top_k, alternatives_k=alternatives_k,
            evidence_types=evidence_types, source_types=source_types,
            target_states=target_states, target_pattern_ids=target_pattern_ids,
        )
        return self.evidence_retriever.retrieve(request)

    def retrieve_for_packet(self, packet: ObservationPacket, *, top_k: int = 12, alternatives_k: int = 5):
        """Retrieve source-backed context for a live PEQ observation packet."""
        return self.evidence_retriever.retrieve_for_packet(packet, top_k=top_k, alternatives_k=alternatives_k)


    def assess_scientific_claim(self, source_id: str, *, proposition: str, actionable: bool = False, dangerous_if_wrong: bool = False) -> ScientificClaimAssessment:
        """Assess source quality/readiness without asserting the claim is true or promoting it."""
        sources = {row["source_id"]: row for row in self.all_scientific_sources()}
        if source_id not in sources:
            raise KeyError(source_id)
        from .clinical_evidence import SourceRecord
        return assess_scientific_claim(SourceRecord(**sources[source_id]), proposition=proposition, actionable=actionable, dangerous_if_wrong=dangerous_if_wrong)

    def assess_scientific_claim_set(self, claim: ScientificClaim, *, actionable: bool = False, dangerous_if_wrong: bool = False) -> ScientificClaimAssessment:
        """Assess a multi-source scientific claim while preserving replication and dissent."""
        from .clinical_evidence import SourceRecord
        sources = {row["source_id"]: SourceRecord(**row) for row in self.all_scientific_sources()}
        return assess_scientific_claim_set(
            claim,
            sources,
            actionable=actionable,
            dangerous_if_wrong=dangerous_if_wrong,
        )

    def promote_scientific_evidence(self, evidence, *, proposition: str, state_directions: Mapping[str, float], verified_claim: bool = False, strength: float = 0.5, reliability: float = 0.5):
        """Explicitly promote a retrieved scientific source into PEQ evidence.

        Retrieval remains reference-only until the caller supplies and verifies a
        proposition plus state-specific evidence directions.
        """
        from .scientific_bridge import promote_scientific_evidence
        return promote_scientific_evidence(
            evidence,
            proposition=proposition,
            state_directions=state_directions,
            verified_claim=verified_claim,
            strength=strength,
            reliability=reliability,
        )

    def evidence_operational_value(self, query: str, *, top_k: int = 12, alternatives_k: int = 5) -> Dict[str, Any]:
        """Return the six-way operational utility profile for retrieved evidence."""
        return self.retrieve_evidence(query, top_k=top_k, alternatives_k=alternatives_k).operational_value.to_dict()

    def rank_working_patterns(self, observed_signs: Sequence[str], *, top_k: int = 5):
        """Rank multiple non-diagnostic working hypotheses from observed signs."""
        return self.evidence_retriever.rank_working_patterns(observed_signs, top_k=top_k)

    def evaluate_calibration(self, cases: Sequence[CalibrationCase], *, bins: int = 10) -> CalibrationReport:
        """Evaluate posterior behavior on explicitly labeled cases.

        This is a validation tool, not a claim that PEQ confidence is calibrated.
        The labels must come from a documented annotation or outcome protocol.
        """
        return evaluate_calibration(cases, self.assess, bins=bins)

    def assess(
        self,
        packet: ObservationPacket,
        *,
        truth_assessment: TruthAssessment | None = None,
        contributions: Sequence[EvidenceContribution] = (),
        extra_tests: Sequence[tuple[TestSpec, TestResult]] = (),
        response_context: Mapping[str, Any] | None = None,
        relationship: Mapping[str, Any] | None = None,
        stakes: float = 0.5,
    ) -> PEQResult:
        validated_truth = truth_assessment
        if extra_tests:
            # Run the existing truth engine with supplied discriminating tests first,
            # then feed the resulting reliability context into PEQ State.
            truth_engine_result = self.truth_engine.assess(packet, extra_tests=extra_tests)
            validated_truth = self.state_engine._derive_truth_assessment(packet)
            tests_run = [r.__dict__ for r in truth_engine_result.trace.test_results]
            mixed_tests = []
            for row in tests_run:
                overlap = {str(x).casefold() for x in (row.get("supports") or [])} & {str(x).casefold() for x in (row.get("weakens") or [])}
                if overlap:
                    mixed_tests.append((str(row.get("test_id") or "unknown"), sorted(overlap)))
            reasons = list(validated_truth.reasons_for_review)
            if mixed_tests:
                reasons.extend(
                    f"Truth test {test_id} produced internally mixed evidence for: {', '.join(states)}."
                    for test_id, states in mixed_tests
                )
            reliability = max(validated_truth.reliability, min(1.0, truth_engine_result.confidence))
            if mixed_tests:
                reliability = min(reliability, 0.55)
            status = validated_truth.status
            if mixed_tests and status == validated_truth.status.SUPPORTED:
                status = validated_truth.status.CONTESTED
            validated_truth = TruthAssessment(
                status=status,
                proposition=validated_truth.proposition,
                reliability=round(reliability, 4),
                reasons_for_review=reasons,
                tests_run=tests_run,
                unresolved_questions=list(dict.fromkeys([*truth_engine_result.trace.unresolved_questions, *[f"Resolve mixed test evidence: {test_id}" for test_id, _ in mixed_tests]])),
                source_summary=truth_engine_result.interpretive_assessment,
            )

        retrieval = self.retrieve_for_packet(packet, top_k=10, alternatives_k=5)

        state = self.state_engine.assess(
            packet,
            truth_assessment=validated_truth,
            additional_contributions=contributions,
        )
        response = self.response_engine.assess(
            state,
            context=response_context or packet.context,
            relationship=relationship,
            stakes=stakes,
        )
        audit = {
            "system": "PEQ",
            "run_id": f"peq_{uuid.uuid4().hex[:12]}",
            "subject_id": packet.subject_id,
            "blackbox_access": False,
            "questions": {
                "state": state.proposition,
                "response": response.question,
            },
            "state": state.to_dict(),
            "response": response.to_dict(),
            "evidence_retrieval": retrieval.to_dict(),
            "operational_value": retrieval.operational_value.to_dict(),
        }
        return PEQResult(state=state, response=response, audit=audit)
