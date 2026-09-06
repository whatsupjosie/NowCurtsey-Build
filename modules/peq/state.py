from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from cre_eq.engine import CriticalReasoningEngine, ObservationExtractor
from cre_eq.models import ObservationPacket

from .models import (
    EvidenceContribution,
    EvidenceDomain,
    MAX_OPERATIONAL_CONFIDENCE,
    PEQStateResult,
    StateCandidate,
    TruthAssessment,
    TruthStatus,
)


class PEQStateEngine:
    """Estimate the most probable emotional state from separated evidence domains.

    This is an operational probabilistic model, not a calibrated statistical model.
    It uses additive log-odds-style evidence accumulation and a bounded mapping to
    operational confidence. Replacing the scorer with a calibrated model later does
    not change the public contract.
    """

    STATES = (
        "excitement",
        "frustration",
        "anger",
        "anxiety",
        "sadness",
        "grief",
        "fatigue",
        "neutral",
    )

    KEYWORDS: Mapping[str, Sequence[str]] = {
        "excitement": ("excited", "thrilled", "amazing", "fantastic", "ecstatic", "elated", "joy", "happy", "celebrating", "great", "awesome", "yes"),
        "frustration": ("frustrated", "annoyed", "pissed", "bullshit", "broken", "irritated", "fed up", "sick of"),
        "anger": ("angry", "furious", "rage", "enraged", "mad", "livid"),
        "anxiety": ("worried", "nervous", "scared", "terrified", "fearful", "panic", "overwhelmed", "anxious", "afraid"),
        "sadness": ("sad", "hurt", "lonely", "miserable", "down", "crying", "heartbroken"),
        "grief": ("grief", "grieving", "mourning", "bereaved", "lost them", "miss them"),
        "fatigue": ("tired", "exhausted", "sleepy", "drained", "can't think", "worn out"),
        "neutral": ("calm", "calmness", "fine", "okay", "ok", "neutral", "relaxed"),
    }
    ALIASES = {
        "happiness": "excitement",
        "happy": "excitement",
        "joy": "excitement",
        "elated": "excitement",
        "angry": "anger",
        "furious": "anger",
        "mad": "anger",
        "anxious": "anxiety",
        "fear": "anxiety",
        "sad": "sadness",
        "mourning": "grief",
    }

    def __init__(self, truth_engine: CriticalReasoningEngine | None = None) -> None:
        self.observation_extractor = ObservationExtractor()
        self.truth_engine = truth_engine or CriticalReasoningEngine()

    @classmethod
    def _recognized_explicit_state(cls, explicit_report: str | None) -> str:
        value = (explicit_report or "").casefold().strip()
        if not value:
            return ""
        normalized = cls.ALIASES.get(value, value)
        if normalized in cls.STATES:
            return normalized
        candidates = []
        for state, terms in cls.KEYWORDS.items():
            for term in terms:
                if cls._contains_term(value, term):
                    candidates.append((len(term), state, term))
        candidates.sort(reverse=True)
        for _, state, term in candidates:
            if not re.search(rf"\b(?:not|no|never)\s+(?:\w+\s+){{0,2}}{re.escape(term)}\b", value):
                return state
        return ""
    def assess(
        self,
        packet: ObservationPacket,
        *,
        truth_assessment: TruthAssessment | None = None,
        additional_contributions: Sequence[EvidenceContribution] = (),
    ) -> PEQStateResult:
        truth = truth_assessment or self._derive_truth_assessment(packet)
        contributions = self._build_contributions(packet, truth)
        contributions.extend(additional_contributions)

        priors = self._priors(packet)
        raw = {state: self._logit(priors[state]) for state in self.STATES}
        supports: Dict[str, List[str]] = defaultdict(list)
        weakens: Dict[str, List[str]] = defaultdict(list)

        # Prevent correlated observations from pretending to be independent votes.
        # Contributions sharing a correlation_group are summed with a bounded group
        # cap per state; distinct groups remain independently additive.
        grouped: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for contribution in contributions:
            if contribution.correlation_group:
                group = contribution.correlation_group
            else:
                normalized_statement = re.sub(r"\s+", " ", contribution.statement.casefold().strip())
                direction_fingerprint = ",".join(
                    f"{state}:{self._direction_for_state(contribution, state):+.4f}"
                    for state in self.STATES
                    if self._direction_for_state(contribution, state) != 0.0
                )
                group = f"statement:{normalized_statement}|{direction_fingerprint}"
            for state in self.STATES:
                direction = self._direction_for_state(contribution, state)
                if direction == 0.0:
                    continue
                amount = contribution.strength * contribution.reliability * direction
                grouped[group][state] += amount

        evidence_mass = 0.0
        for contribution in contributions:
            evidence_mass += abs(contribution.effective_weight())
        max_group_contribution = 0.85
        for group, state_amounts in grouped.items():
            for state, total_amount in state_amounts.items():
                amount = max(-max_group_contribution, min(max_group_contribution, total_amount))
                raw[state] += amount
                evidence_mass += 0.0
                if amount > 0:
                    supports[state].append(f"[{group}] aggregated evidence")
                elif amount < 0:
                    weakens[state].append(f"[{group}] aggregated evidence")

        probs = self._softmax(raw)
        ordered = sorted(self.STATES, key=lambda state: probs[state], reverse=True)
        leading, second = ordered[0], ordered[1]
        direct_report_present = bool(self._recognized_explicit_state(packet.explicit_report))
        confidence = self._bounded_operational_confidence(
            probs[leading], probs[second], truth.reliability, direct_report_present, truth.status
        )
        # No meaningful evidence must not look like a confident emotional read.
        informative = sum(
            1
            for c in contributions
            if c.domain not in {EvidenceDomain.GENERAL_KNOWLEDGE, EvidenceDomain.POPULATION_BASELINE}
            and max((abs(c.effective_weight(state)) for state in self.STATES), default=0.0) > 1e-9
        )
        if informative == 0 and not direct_report_present:
            confidence = min(confidence, 0.35)
        uncertainty = round(1.0 - confidence, 4)

        if confidence < 0.45 and probs[leading] - probs[second] < 0.05 and informative == 0:
            leading = "neutral"
            confidence = min(confidence, 0.35)
            uncertainty = round(1.0 - confidence, 4)

        candidates = [
            StateCandidate(
                state=state,
                prior=round(priors[state], 4),
                posterior_score=round(probs[state], 4),
                operational_confidence=round(confidence if state == leading else probs[state] * confidence, 4),
                supporting=supports[state][:8],
                weakening=weakens[state][:8],
            )
            for state in ordered[:5]
        ]

        assumptions = [
            "Emotional state is latent; observable signals are evidence rather than direct access to inner state.",
            "General emotional knowledge supplies priors and signal relationships, not certainty.",
            "Population baseline is different from this individual's baseline.",
            "Individual modifiers can move the likelihood away from population expectations.",
            "Current statements may be highly informative but may still require reliability checking when incongruity appears.",
            f"Operational confidence is capped at {MAX_OPERATIONAL_CONFIDENCE:.1%}; it is not a claim of metaphysical certainty.",
        ]

        unresolved = list(truth.unresolved_questions)
        if probs[second] > 0.20:
            unresolved.append(f"What observation would most efficiently distinguish {leading} from {second}?")

        explanation = self._explain(leading, confidence, priors, contributions, truth, candidates)
        formal = (
            f"According to the available evidence and PEQ assessment, the most probable emotional state is {leading}. "
            f"Operational confidence: {confidence:.1%}."
        )

        return PEQStateResult(
            proposition=f"What is the most probable emotional state of subject {packet.subject_id}?",
            leading_state=leading,
            formal_determination=formal,
            operational_confidence=round(confidence, 4),
            uncertainty=uncertainty,
            confidence_note="Operational confidence, not calibrated probability; hard-capped at 98.5%.",
            candidates=candidates,
            posterior_distribution={state: round(prob, 6) for state, prob in probs.items()},
            contributions=contributions,
            truth_assessment=truth,
            assumptions=assumptions,
            unresolved_questions=unresolved,
            explanation=explanation,
        )

    def _derive_truth_assessment(self, packet: ObservationPacket) -> TruthAssessment:
        # The existing CRE is used as a truth-testing backplane. PEQ does not call
        # its emotion conclusion truth; it only uses the truth/reliability signals
        # exposed by the reasoning trace.
        try:
            assessment = self.truth_engine.assess(packet)
        except Exception as exc:  # Defensive: PEQ can still run with degraded truth context.
            return TruthAssessment(
                status=TruthStatus.INCONCLUSIVE,
                proposition=packet.explicit_report or packet.text[:200],
                reliability=0.50,
                reasons_for_review=[f"Truth engine unavailable: {type(exc).__name__}: {exc}"],
                unresolved_questions=["Truth-testing could not be completed."],
            )

        contradictions = [d for d in assessment.trace.divergences if d.get("is_contradiction")]
        explicit_conflict = self._explicit_report_conflict(packet)
        if explicit_conflict:
            contradictions = list(contradictions) + [{"is_contradiction": True, "reason": explicit_conflict}]
        incongruity_flags = [
            str(a.statement).casefold()
            for a in assessment.trace.assumptions
            if any(term in str(a.statement).casefold() for term in ("sarcas", "incongruity"))
        ]
        recognized_report = self._recognized_explicit_state(packet.explicit_report)
        if contradictions:
            status = TruthStatus.CONTESTED
        elif incongruity_flags:
            # A direct self-report is strong evidence about what the subject says
            # they are feeling, but an independent cue to sarcasm/incongruity means
            # that report should not be treated as settled literal affect.
            status = TruthStatus.INCONCLUSIVE
        elif packet.explicit_report and not recognized_report:
            # An unrecognized structured report must not manufacture a high-confidence
            # truth result merely because the underlying proposition is internally cogent.
            status = TruthStatus.INCONCLUSIVE
        elif assessment.status.value == "cogent":
            status = TruthStatus.SUPPORTED
        else:
            status = TruthStatus.INCONCLUSIVE

        reasons: List[str] = []
        if assessment.trace.assumptions:
            for a in assessment.trace.assumptions:
                if not a.tested:
                    reasons.append(f"Untested assumption: {a.statement}")
        if contradictions:
            reasons.append("Material contradiction detected by the reasoning layer.")
        if explicit_conflict:
            reasons.append(explicit_conflict)
        if incongruity_flags:
            reasons.append("Sarcasm/incongruity indicator detected; direct report retained as evidence but not treated as settled literal affect.")

        reliability = max(0.35, min(1.0, 0.55 + assessment.confidence * 0.35 - 0.15 * len(contradictions)))
        if incongruity_flags:
            reliability = min(reliability, 0.58)
        return TruthAssessment(
            status=status,
            proposition=packet.explicit_report or packet.text[:200],
            reliability=round(reliability, 4),
            reasons_for_review=reasons,
            tests_run=[r.__dict__ for r in assessment.trace.test_results],
            unresolved_questions=list(assessment.trace.unresolved_questions),
            source_summary=assessment.interpretive_assessment,
        )

    def _build_contributions(self, packet: ObservationPacket, truth: TruthAssessment) -> List[EvidenceContribution]:
        evidence = self.observation_extractor.extract(packet)
        contributions: List[EvidenceContribution] = []

        for item in evidence:
            if item.kind.value == "direct_report":
                reported = str(item.value or "").casefold().strip()
                normalized = self._recognized_explicit_state(reported)
                if normalized:
                    state_directions = {state: (-0.12 if state != normalized else 1.0) for state in self.STATES}
                    contributions.append(EvidenceContribution(
                        source_id=item.evidence_id,
                        domain=EvidenceDomain.CURRENT,
                        statement=f"Direct report: {item.value}",
                        direction=0.0,
                        strength=0.95,
                        reliability=truth.reliability,
                        provenance=item.provenance,
                        state_directions=state_directions,
                        correlation_group=f"direct_report:{normalized}",
                    ))
                else:
                    contributions.append(EvidenceContribution(
                        source_id=item.evidence_id,
                        domain=EvidenceDomain.CURRENT,
                        statement=f"Unrecognized direct report: {item.value}",
                        direction=0.0,
                        strength=0.0,
                        reliability=0.40,
                        provenance=item.provenance,
                        state_directions={},
                        correlation_group="direct_report:unrecognized",
                    ))
                continue

            if item.kind.value in {"profile", "prior"}:
                domain = EvidenceDomain.HISTORY
                value = str(item.value).casefold()
                directions = {state: 0.0 for state in self.STATES}
                if "typical_emotional_state" in item.label:
                    normalized = self.ALIASES.get(value, value)
                    if normalized in directions:
                        directions[normalized] = 0.35
                        for state in directions:
                            if state != normalized:
                                directions[state] = -0.04
                contributions.append(EvidenceContribution(
                    source_id=item.evidence_id,
                    domain=domain,
                    statement=f"{item.label}={item.value}",
                    direction=0.0,
                    strength=0.60 if any(directions.values()) else 0.0,
                    reliability=0.82,
                    provenance=item.provenance,
                    state_directions=directions,
                    correlation_group="person:profile",
                ))
                continue

            if item.kind.value == "derived" and item.label.startswith("baseline_deviation:"):
                feature = item.label.split(":", 1)[1]
                deviation = float(item.value)
                contributions.extend(self._baseline_contributions(item.evidence_id, feature, deviation))
                continue

            if item.label in {"message_word_count", "capitalization_ratio", "punctuation_intensity", "repeated_token_count"}:
                contributions.extend(self._text_feature_contributions(item.evidence_id, item.label, float(item.value), packet))
                continue

            contributions.extend(self._measurement_contributions(item.evidence_id, item.label, float(item.value)))

        contributions.extend(self._lexical_contributions(packet.text, packet.explicit_report))
        contributions.extend(self._general_knowledge_contributions())
        contributions.extend(self._population_baseline_contributions(packet))
        contributions.extend(self._context_contributions(packet))
        if packet.recent_text:
            contributions.extend(self._history_contributions(packet.recent_text))
        # Feed the actual discriminating test outcomes into PEQ as directional
        # evidence. A test result saying it supports state A and weakens state B
        # must affect those states specifically; reliability alone is not enough.
        for test in truth.tests_run:
            test_id = str(test.get("test_id") or "unknown_test")
            observation = str(test.get("observation") or test.get("result") or "")
            supports = [self.ALIASES.get(str(x).casefold(), str(x).casefold()) for x in (test.get("supports") or [])]
            weakens = [self.ALIASES.get(str(x).casefold(), str(x).casefold()) for x in (test.get("weakens") or [])]
            directions = {state: 0.0 for state in self.STATES}
            for state in supports:
                if state in directions:
                    directions[state] += 1.0
            for state in weakens:
                if state in directions:
                    directions[state] -= 1.0
            if any(directions.values()) or supports or weakens:
                materiality = max(0.0, min(1.0, float(test.get("materiality", 0.5))))
                mixed = sorted(set(supports) & set(weakens))
                statement = f"Executed truth test {test_id}: {observation}"
                if mixed:
                    statement += f"; mixed evidence for {', '.join(mixed)}"
                contributions.append(EvidenceContribution(
                    source_id=f"truth_test:{test_id}",
                    domain=EvidenceDomain.TRUTH_TEST,
                    statement=statement,
                    direction=0.0,
                    strength=materiality,
                    reliability=min(truth.reliability, 0.55) if mixed else truth.reliability,
                    provenance="CriticalReasoningEngine.test_result",
                    state_directions=directions,
                    correlation_group=f"truth_test:{test_id}",
                ))

        if truth.status == TruthStatus.CONTESTED:
            contributions.append(EvidenceContribution(
                source_id="truth:contested",
                domain=EvidenceDomain.TRUTH_TEST,
                statement="Current proposition is contested by the logical reasoning layer.",
                direction=-0.35,
                strength=0.75,
                reliability=truth.reliability,
                provenance="CriticalReasoningEngine",
            ))
        elif truth.status == TruthStatus.SUPPORTED:
            contributions.append(EvidenceContribution(
                source_id="truth:supported",
                domain=EvidenceDomain.TRUTH_TEST,
                statement="Current proposition is supported by the logical reasoning layer.",
                direction=0.25,
                strength=0.65,
                reliability=truth.reliability,
                provenance="CriticalReasoningEngine",
            ))
        return contributions

    def _baseline_contributions(self, source_id: str, feature: str, deviation: float) -> List[EvidenceContribution]:
        magnitude = min(1.0, abs(deviation))
        direction = 1.0 if deviation > 0 else -1.0
        if feature in {"typing_wpm", "speech_rate_wpm", "punctuation_intensity", "capitalization_ratio"}:
            return [
                EvidenceContribution(source_id, EvidenceDomain.INDIVIDUAL_BASELINE,
                                     f"{feature} deviates {deviation:+.2f} from individual baseline; this is an arousal/expressivity change, not a direct emotion label.",
                                     0.0, magnitude, 1.0,
                                     state_directions={
                                         "excitement": 0.25 if deviation > 0 else 0.0,
                                         "frustration": 0.25 if deviation > 0 else 0.0,
                                         "anger": 0.20 if deviation > 0 else 0.0,
                                         "anxiety": 0.20 if deviation > 0 else 0.0,
                                         "fatigue": -0.10 if deviation > 0 else 0.12,
                                         "sadness": 0.08 if deviation < 0 else 0.0,
                                     }),
            ]
        if feature == "typo_rate" and direction > 0:
            return [
                EvidenceContribution(source_id, EvidenceDomain.INDIVIDUAL_BASELINE,
                                     "Typo rate is above individual baseline; this can accompany fatigue, haste, stress, or high arousal.",
                                     -0.05, magnitude, 0.85),
            ]
        return []

    def _text_feature_contributions(self, source_id: str, label: str, value: float, packet: ObservationPacket) -> List[EvidenceContribution]:
        text = packet.text.casefold()
        out: List[EvidenceContribution] = []
        if label == "capitalization_ratio" and value > 0.25:
            out.append(EvidenceContribution(source_id, EvidenceDomain.CURRENT,
                                             "High capitalization is evidence of elevated expressivity/arousal, not proof of a specific emotion.",
                                             0.0, min(1.0, value), 0.90))
        elif label == "punctuation_intensity" and value > 0.35:
            out.append(EvidenceContribution(source_id, EvidenceDomain.CURRENT,
                                             "High !/? punctuation indicates elevated expressivity/arousal.", 0.0, min(1.0, value), 0.88))
        elif label == "message_word_count" and value > 0 and len(text) < 40:
            out.append(EvidenceContribution(source_id, EvidenceDomain.CURRENT,
                                             "Short current message; weak evidence only because brevity has many causes.", 0.0, 0.12, 0.70))
        return out

    def _measurement_contributions(self, source_id: str, label: str, value: float) -> List[EvidenceContribution]:
        out: List[EvidenceContribution] = []
        if label == "crying_signal" and value >= 0.6:
            out.append(EvidenceContribution(source_id, EvidenceDomain.CURRENT, "Elevated crying signal supports sadness/grief and can also accompany anxiety.", 0.0, value, 0.90))
        elif label == "laughter_signal" and value >= 0.6:
            out.append(EvidenceContribution(source_id, EvidenceDomain.CURRENT, "Elevated laughter signal supports positive/high-arousal states.", 0.0, value, 0.82))
        elif label == "face_valence":
            out.append(EvidenceContribution(source_id, EvidenceDomain.CURRENT, f"Observed face valence={value:+.2f}.", 0.0, min(1.0, abs(value)), 0.65))
        elif label == "face_arousal" and value >= 0.7:
            out.append(EvidenceContribution(source_id, EvidenceDomain.CURRENT, "Observed facial arousal is elevated; this is non-specific across excitement, anger, anxiety, and frustration.", 0.0, value, 0.65))
        return out

    def _lexical_contributions(self, text: str, explicit_report: str | None) -> List[EvidenceContribution]:
        text = (text or "").casefold()
        explicit = (explicit_report or "").casefold()
        explicit_state = self.ALIASES.get(explicit, explicit) if explicit else ""
        out: List[EvidenceContribution] = []
        for state, terms in self.KEYWORDS.items():
            hits = []
            for term in terms:
                text_hit = self._contains_term_unnegated(text, term)
                explicit_hit = self._contains_term(explicit, term)
                # A structured explicit_report is already represented by its own
                # high-quality evidence contribution. Do not count current-text
                # lexical cues for that same reported state a second time.
                if text_hit and explicit_state == state:
                    continue
                if text_hit and not explicit_hit:
                    hits.append(term)
                elif text_hit and explicit_hit:
                    continue
            if not hits:
                continue
            strength = min(0.95, 0.55 + 0.12 * len(hits))
            if explicit and any(self._contains_term(explicit, term) for term in terms):
                strength = min(0.92, strength + 0.12)
            directions = {candidate: (-0.15 if candidate != state else 1.0) for candidate in self.STATES}
            out.append(EvidenceContribution(
                source_id=f"lexical:{state}",
                domain=EvidenceDomain.CURRENT,
                statement=f"Current lexical signal associated with {state}: {', '.join(hits)}",
                direction=0.0,
                strength=strength,
                reliability=0.88 if not explicit else 0.96,
                provenance="current text lexical evidence",
                state_directions=directions,
                correlation_group=f"lexical:{state}",
            ))
        # Explicitly preserve the absence of a recognized emotional lexeme as evidence of uncertainty, not neutrality.
        return out

    def _general_knowledge_contributions(self) -> List[EvidenceContribution]:
        return [
            EvidenceContribution(
                source_id="knowledge:emotion-baselines",
                domain=EvidenceDomain.GENERAL_KNOWLEDGE,
                statement="General emotional knowledge defines cue relationships and keeps interpretation probabilistic; it is not a direct observation of the subject.",
                direction=0.0,
                strength=0.0,
                reliability=1.0,
                provenance="PEQ evidence model",
                correlation_group="meta:general_knowledge",
            )
        ]

    def _population_baseline_contributions(self, packet: ObservationPacket) -> List[EvidenceContribution]:
        baseline_text = str(packet.context.get("population_baseline", "")).casefold()
        if not baseline_text:
            return [EvidenceContribution(
                source_id="baseline:population",
                domain=EvidenceDomain.POPULATION_BASELINE,
                statement="Population baseline is used as a prior context; individual deviation can override generic expectations.",
                direction=0.0,
                strength=0.0,
                reliability=0.85,
                provenance="PEQ population prior contract",
                correlation_group="meta:population_baseline",
            )]
        directions = {state: 0.0 for state in self.STATES}
        if "fatigue" in baseline_text or "tired" in baseline_text:
            directions["fatigue"] = 0.30
        if "anxiety" in baseline_text or "anxious" in baseline_text:
            directions["anxiety"] = 0.30
        if "positive" in baseline_text or "excited" in baseline_text:
            directions["excitement"] = 0.25
        if "negative" in baseline_text or "distress" in baseline_text:
            directions["frustration"] = 0.20
            directions["anxiety"] = 0.15
        return [EvidenceContribution(
            source_id="baseline:population",
            domain=EvidenceDomain.POPULATION_BASELINE,
            statement=f"Population baseline context: {baseline_text}",
            direction=0.0,
            strength=0.55,
            reliability=0.72,
            provenance="caller-provided population baseline context",
            state_directions=directions,
            correlation_group="population:baseline",
        )]

    def _context_contributions(self, packet: ObservationPacket) -> List[EvidenceContribution]:
        out: List[EvidenceContribution] = []
        for key, value in packet.context.items():
            text = str(value).casefold()
            if key not in {"situation", "recent_event", "interaction_goal"}:
                continue
            statement = f"Situation/context: {key}={value}"
            if any(term in text for term in ("succeed", "succeeded", "success", "fixed", "worked", "won", "good news", "celebration")):
                out.append(EvidenceContribution(
                    source_id=f"context:{key}:positive", domain=EvidenceDomain.SITUATION,
                    statement=statement + "; context strongly favors a positive outcome.",
                    direction=0.0, strength=0.48, reliability=0.88,
                    provenance="caller-provided context",
                    correlation_group="situation:context",
                    state_directions={
                        "excitement": 1.0, "frustration": -0.25, "anger": -0.25,
                        "sadness": -0.25, "grief": -0.20
                    },
                ))
            elif any(term in text for term in ("failed", "failure", "broke", "broken", "blocked", "rejected", "bad news")):
                directions = {
                    "excitement": -0.70, "frustration": 0.85, "anger": 0.80,
                    "sadness": 0.20, "grief": 0.10
                }
                out.append(EvidenceContribution(
                    source_id=f"context:{key}:negative", domain=EvidenceDomain.SITUATION,
                    statement=statement + "; context strongly favors a blocked/negative outcome.",
                    direction=0.0, strength=0.62, reliability=0.88,
                    provenance="caller-provided context",
                    correlation_group="situation:context",
                    state_directions=directions,
                ))
            else:
                out.append(EvidenceContribution(
                    source_id=f"context:{key}", domain=EvidenceDomain.SITUATION,
                    statement=statement,
                    direction=0.0, strength=0.30, reliability=0.85,
                    provenance="caller-provided context",
                ))
        return out

    def _history_contributions(self, recent_text: Sequence[str]) -> List[EvidenceContribution]:
        joined = " ".join(recent_text).casefold()
        out: List[EvidenceContribution] = []
        if "i'm fine" in joined or "im fine" in joined:
            out.append(EvidenceContribution(
                source_id="history:fine_pattern",
                domain=EvidenceDomain.HISTORY,
                statement="Recent conversation contains repeated 'I'm fine' wording; this may be pragmatic, literal, or defensive and requires individual-specific evidence.",
                direction=0.0,
                strength=0.25,
                reliability=0.55,
            ))
        return out

    def _priors(self, packet: ObservationPacket) -> Dict[str, float]:
        priors = {state: 1.0 / len(self.STATES) for state in self.STATES}
        priors["neutral"] = 0.18
        total = sum(priors.values())
        priors = {k: v / total for k, v in priors.items()}

        profile_state = str(packet.profile_facts.get("typical_emotional_state", "")).casefold()
        if profile_state in self.STATES:
            priors[profile_state] += 0.12
            total = sum(priors.values())
            priors = {k: v / total for k, v in priors.items()}
        return priors

    def _direction_for_state(self, contribution: EvidenceContribution, state: str) -> float:
        if contribution.state_directions:
            return contribution.state_directions.get(state, contribution.direction)
        text = contribution.statement.casefold()
        if "direct report:" in text:
            reported = text.split("direct report:", 1)[1].strip()
            normalized = self.ALIASES.get(reported, reported)
            return 1.0 if normalized == state else -0.15
        if contribution.domain == EvidenceDomain.CURRENT:
            for term in self.KEYWORDS.get(state, ()):
                if self._contains_term(text, term):
                    return 1.0
            # Generic positive/negative tone is weak evidence only.
            if state == "excitement" and any(word in text for word in ("yes", "great", "awesome")):
                return 0.4
            if state == "frustration" and any(word in text for word in ("bullshit", "broken", "annoyed")):
                return 0.9
            if state == "anger" and any(word in text for word in ("furious", "rage", "livid")):
                return 0.95
        if contribution.domain == EvidenceDomain.INDIVIDUAL_BASELINE and "deviates +" in text:
            if state in {"excitement", "frustration", "anger", "anxiety"}:
                return 0.25
            if state == "fatigue":
                return -0.10
        if contribution.domain == EvidenceDomain.INDIVIDUAL_BASELINE and "deviates -" in text:
            if state in {"fatigue", "sadness"}:
                return 0.18
        if contribution.domain == EvidenceDomain.SITUATION:
            if "strongly favors a positive outcome" in text:
                return 1.0 if state == "excitement" else -0.25 if state in {"frustration", "anger", "sadness", "grief"} else 0.0
            if "strongly favors a blocked/negative outcome" in text:
                return 1.0 if state in {"frustration", "anger"} else -0.25 if state == "excitement" else 0.0
        if contribution.domain == EvidenceDomain.HISTORY:
            if "fine" in text and state in {"frustration", "sadness"}:
                return 0.25
        return 0.0

    def _explicit_report_conflict(self, packet: ObservationPacket) -> str:
        report = str(packet.explicit_report or "").casefold().strip()
        text = str(packet.text or "").casefold()
        if not report or not text:
            return ""
        state = self.ALIASES.get(report, report)
        if state not in self.STATES:
            return ""
        for term in self.KEYWORDS.get(state, ()):
            if self._contains_term(text, term) and not self._contains_term_unnegated(text, term):
                return f"Structured explicit report '{report}' conflicts with negated current text around '{term}'."
        return ""

    @staticmethod
    def _contains_term(text: str, term: str) -> bool:
        if " " in term:
            return term in text
        return re.search(rf"\b{re.escape(term)}\b", text) is not None

    @classmethod
    def _contains_term_unnegated(cls, text: str, term: str) -> bool:
        if not cls._contains_term(text, term):
            return False
        if " " in term:
            pattern = rf"\b(?:not|never|no|dont|don't|isn't|isnt|wasn't|wasnt|didn't|didnt|cannot|can't|cant|without)\b\s+(?:\w+\s+){{0,3}}{re.escape(term)}\b"
            return re.search(pattern, text) is None
        pattern = rf"\b(?:not|never|no|dont|don't|isn't|isnt|wasn't|wasnt|didn't|didnt|cannot|can't|cant|without)\b\s+(?:\w+\s+){{0,3}}{re.escape(term)}\b"
        return re.search(pattern, text) is None

    @staticmethod
    def _logit(probability: float) -> float:
        p = min(0.999, max(0.001, probability))
        return math.log(p / (1.0 - p))

    @staticmethod
    def _softmax(scores: Mapping[str, float]) -> Dict[str, float]:
        maximum = max(scores.values())
        exps = {key: math.exp(value - maximum) for key, value in scores.items()}
        total = sum(exps.values())
        return {key: value / total for key, value in exps.items()}

    @staticmethod
    def _bounded_operational_confidence(
        leading: float,
        second: float,
        truth_reliability: float,
        direct_report_present: bool,
        truth_status: TruthStatus,
    ) -> float:
        margin = max(0.0, leading - second)
        raw = 0.38 + 1.55 * margin
        raw += 0.30 * max(0.0, truth_reliability - 0.5)
        if direct_report_present and truth_status == TruthStatus.SUPPORTED:
            raw += 0.18
        # A structured self-report that independently survived truth/reliability
        # review is high-quality evidence. It earns a confidence floor without
        # duplicating the same lexical signal from the source text. This remains
        # capped at the PEQ 98.5% operational ceiling.
        if direct_report_present and truth_status == TruthStatus.SUPPORTED and truth_reliability >= 0.80:
            verified_floor = 0.86 + 0.13 * min(1.0, max(0.0, (truth_reliability - 0.50) / 0.50))
            raw = max(raw, verified_floor)
        if truth_status == TruthStatus.CONTESTED:
            raw -= 0.18
        return round(min(MAX_OPERATIONAL_CONFIDENCE, max(0.0, raw)), 4)

    @staticmethod
    def _explain(
        leading: str,
        confidence: float,
        priors: Mapping[str, float],
        contributions: Sequence[EvidenceContribution],
        truth: TruthAssessment,
        candidates: Sequence[StateCandidate],
    ) -> str:
        domains = ", ".join(sorted({c.domain.value for c in contributions})) or "none"
        strongest = sorted(contributions, key=lambda c: abs(c.effective_weight()), reverse=True)[:5]
        snippets = "; ".join(c.statement for c in strongest if c.statement)
        alt = candidates[1].state if len(candidates) > 1 else "no strong alternative"
        return (
            f"PEQ considered general priors, available baseline/context/history/current evidence, and the logical truth-testing reliability assessment. "
            f"The leading state is {leading} at {confidence:.1%} operational confidence, with {alt} as the strongest alternative. "
            f"Evidence domains used: {domains}. Truth status: {truth.status.value}. "
            f"Strongest contributing observations: {snippets}"
        )
