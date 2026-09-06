from __future__ import annotations

import math
import re
import json
import os
import statistics
from pathlib import Path
import uuid
from collections import Counter
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from .models import (
    AffectAssessment,
    Assumption,
    Baseline,
    DeterminationStatus,
    Evidence,
    EvidenceKind,
    Hypothesis,
    ObservationPacket,
    ReasoningTrace,
    ResponseAppraisal,
    TestResult,
    TestSpec,
)


class ObservationExtractor:
    """Turns raw multimodal inputs into structured observations.

    It does not infer emotion. It measures signals and deviations only.
    """

    def extract(self, packet: ObservationPacket) -> List[Evidence]:
        evidence: List[Evidence] = []
        text = packet.text or ""

        if packet.explicit_report:
            evidence.append(Evidence(
                evidence_id=self._id("direct"),
                kind=EvidenceKind.DIRECT_REPORT,
                label="explicit_user_report",
                value=packet.explicit_report,
                strength=0.95,
                provenance="user-provided in current interaction",
            ))

        words = text.split()
        caps_ratio = self._caps_ratio(text)
        punctuation = self._punctuation_intensity(text)
        avg_words = len(words)
        repeats = len(re.findall(r"\b(\w+)\s+\1\b", text.lower()))

        evidence.extend([
            Evidence(self._id("obs"), EvidenceKind.OBSERVATION, "message_word_count", avg_words, 0.25),
            Evidence(self._id("obs"), EvidenceKind.OBSERVATION, "capitalization_ratio", round(caps_ratio, 4), 0.45),
            Evidence(self._id("obs"), EvidenceKind.OBSERVATION, "punctuation_intensity", round(punctuation, 4), 0.35),
            Evidence(self._id("obs"), EvidenceKind.OBSERVATION, "repeated_token_count", repeats, 0.2),
        ])

        self._add_numeric_feature(evidence, packet.typing, "typing_wpm")
        self._add_numeric_feature(evidence, packet.typing, "response_latency_s")
        self._add_numeric_feature(evidence, packet.typing, "typo_rate")
        self._add_numeric_feature(evidence, packet.audio, "pitch_mean_hz")
        self._add_numeric_feature(evidence, packet.audio, "pitch_variance")
        self._add_numeric_feature(evidence, packet.audio, "speech_rate_wpm")
        self._add_numeric_feature(evidence, packet.audio, "pause_ratio")
        self._add_numeric_feature(evidence, packet.audio, "disfluency_rate")
        self._add_numeric_feature(evidence, packet.audio, "laughter_signal")
        self._add_numeric_feature(evidence, packet.audio, "crying_signal")
        self._add_numeric_feature(evidence, packet.vision, "face_valence")
        self._add_numeric_feature(evidence, packet.vision, "face_arousal")
        self._add_numeric_feature(evidence, packet.vision, "gaze_aversion")

        baseline = packet.baseline
        if baseline:
            for feature_name, current in self._current_features(evidence).items():
                baseline_value = self._baseline_value(baseline, feature_name)
                if baseline_value is None:
                    continue
                scale = max(abs(baseline_value), 1.0)
                deviation = (current - baseline_value) / scale
                evidence.append(Evidence(
                    evidence_id=self._id("dev"),
                    kind=EvidenceKind.DERIVED,
                    label=f"baseline_deviation:{feature_name}",
                    value=round(deviation, 4),
                    strength=min(1.0, abs(deviation)),
                    provenance="current observation compared with person-specific baseline",
                ))

        for key, value in packet.profile_facts.items():
            evidence.append(Evidence(
                evidence_id=self._id("profile"),
                kind=EvidenceKind.PROFILE,
                label=f"profile:{key}",
                value=value,
                strength=0.55,
                provenance="authorized persistent user/person profile",
            ))

        return evidence

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _caps_ratio(text: str) -> float:
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return 0.0
        return sum(c.isupper() for c in letters) / len(letters)

    @staticmethod
    def _punctuation_intensity(text: str) -> float:
        if not text:
            return 0.0
        punctuation = sum(c in "!?" for c in text)
        return min(1.0, punctuation / max(len(text.split()), 1))

    @staticmethod
    def _add_numeric_feature(target: List[Evidence], mapping: Mapping[str, float], key: str) -> None:
        if key not in mapping:
            return
        try:
            value = float(mapping[key])
        except (TypeError, ValueError, OverflowError):
            return
        if not math.isfinite(value):
            return
        target.append(Evidence(
            evidence_id=f"obs_{uuid.uuid4().hex[:8]}",
            kind=EvidenceKind.OBSERVATION,
            label=key,
            value=value,
            strength=0.5,
            provenance="provided multimodal measurement",
        ))

    @staticmethod
    def _current_features(evidence: Sequence[Evidence]) -> Dict[str, float]:
        return {
            e.label: float(e.value)
            for e in evidence
            if e.kind == EvidenceKind.OBSERVATION and isinstance(e.value, (int, float))
        }

    @staticmethod
    def _baseline_value(baseline: Baseline, feature_name: str) -> float | None:
        return getattr(baseline, feature_name, None)


class AffectiveHypothesisEngine:
    """Builds competing state hypotheses from observations.

    This is intentionally conservative and rule-transparent for the prototype.
    It is the replaceable deterministic layer beneath future learned detectors.
    """

    STATES = ("excitement", "frustration", "anger", "anxiety", "sadness", "grief", "fatigue", "neutral")

    def generate(self, packet: ObservationPacket, evidence: Sequence[Evidence]) -> List[Hypothesis]:
        scores = Counter({s: 0.16 for s in self.STATES})
        scores["neutral"] = 0.20
        support: Dict[str, List[str]] = {s: [] for s in self.STATES}
        contradict: Dict[str, List[str]] = {s: [] for s in self.STATES}
        assumptions: List[str] = []

        text = packet.text.lower()
        direct = packet.explicit_report.lower() if packet.explicit_report else ""

        keyword_sets = {
            "excitement": {"excited", "thrilled", "amazing", "fantastic", "great", "love", "yes", "did it", "holy shit", "elated", "ecstatic", "happy", "joy"},
            "frustration": {"frustrated", "annoyed", "pissed", "fuck this", "bullshit", "broken", "irritated"},
            "anger": {"angry", "furious", "rage", "enraged", "mad"},
            "anxiety": {"worried", "nervous", "scared", "panic", "overwhelmed", "what if", "anxious"},
            "sadness": {"sad", "hurt", "crying", "lonely", "down", "miserable"},
            "grief": {"grief", "mourning", "grieving", "miss them", "bereaved"},
            "fatigue": {"tired", "exhausted", "sleepy", "can't think", "done", "worn out"},
        }
        for state, terms in keyword_sets.items():
            hits = [term for term in terms if self._contains_term(text, term) or self._contains_term(direct, term)]
            if hits:
                scores[state] += min(0.35, 0.12 * len(hits))
                support[state].append(f"lexical signal(s): {', '.join(hits)}")

        feature = {e.label: e.value for e in evidence}
        if float(feature.get("typing_wpm", 0.0) or 0.0) > 70:
            scores["excitement"] += 0.10
            scores["anxiety"] += 0.06
        if float(feature.get("typo_rate", 0.0) or 0.0) > 0.08:
            scores["fatigue"] += 0.08
            scores["frustration"] += 0.05
        if float(feature.get("crying_signal", 0.0) or 0.0) > 0.6:
            scores["sadness"] += 0.25
            scores["anxiety"] += 0.08
        if float(feature.get("laughter_signal", 0.0) or 0.0) > 0.6:
            scores["excitement"] += 0.18
        if float(feature.get("face_arousal", 0.0) or 0.0) > 0.7:
            scores["excitement"] += 0.08
            scores["frustration"] += 0.08
            scores["anxiety"] += 0.08

        baseline_caps = [e for e in evidence if e.label == "baseline_deviation:capitalization_ratio"]
        if baseline_caps and float(baseline_caps[0].value) > 0.25:
            # Deviation is meaningful, but not emotion-specific.
            scores["excitement"] += 0.03
            scores["frustration"] += 0.03
            assumptions.append("capitalization deviation is treated as an arousal/expressivity signal, not a direct emotion marker")

        if packet.recent_text:
            recent = " ".join(packet.recent_text).lower()
            if "i'm fine" in recent or "im fine" in recent:
                scores["frustration"] += 0.06
                scores["sadness"] += 0.04
                support["frustration"].append("historical 'fine' language may be pragmatic rather than literal")

        if direct:
            aliases = {
                "happy": "excitement", "happiness": "excitement", "joy": "excitement", "elated": "excitement",
                "angry": "anger", "mad": "anger", "furious": "anger",
                "anxious": "anxiety", "fear": "anxiety",
                "sad": "sadness", "grief": "grief", "mourning": "grief",
            }
            mentioned = [state for state in self.STATES if self._contains_term(direct, state)]
            for alias, state in aliases.items():
                if self._contains_term(direct, alias):
                    mentioned.append(state)
            mentioned = list(dict.fromkeys(mentioned))
            if mentioned:
                for state in mentioned:
                    scores[state] += 0.70
                    support[state].append("direct current self-report")
                for state in self.STATES:
                    if state not in mentioned and state != "neutral":
                        contradict[state].append("direct self-report names another state")

        # Sarcasm-like incongruity remains an alternate explanation rather than a state.
        positive_terms = {"great", "fantastic", "amazing", "wonderful"}
        negative_context = any(t in text for t in {"didn't want", "hate when", "terrible", "failed", "broken", "breaks"})
        exaggerated = bool(re.search(r"[A-Z]{4,}|!{2,}", packet.text))
        if positive_terms.intersection(set(re.findall(r"[a-zA-Z']+", text))) and negative_context and exaggerated:
            scores["excitement"] -= 0.08
            scores["frustration"] += 0.10
            assumptions.append("positive wording may be sarcastic because literal semantics conflict with immediate context")
            support["frustration"].append("semantic/prosodic incongruity compatible with sarcasm")

        total = sum(max(v, 0.01) for v in scores.values())
        hypotheses = []
        for state, raw in scores.items():
            score = max(0.01, raw) / total
            hypotheses.append(Hypothesis(
                hypothesis_id=f"h_{state}",
                label=state,
                score=round(score, 4),
                supporting_evidence=support[state],
                contradicting_evidence=contradict[state],
                assumptions=assumptions.copy(),
                unresolved_questions=[],
            ))
        hypotheses.sort(key=lambda h: h.score, reverse=True)
        return hypotheses


    @staticmethod
    def _contains_term(text: str, term: str) -> bool:
        if not text or not term:
            return False
        if " " in term or "'" in term:
            return term in text
        return re.search(r"\b" + re.escape(term) + r"\b", text) is not None


class DiscriminationPlanner:
    """Selects a small, high-value test based on the leading hypotheses."""

    def plan(self, hypotheses: Sequence[Hypothesis], packet: ObservationPacket) -> TestSpec | None:
        if len(hypotheses) < 2:
            return None
        first, second = hypotheses[0], hypotheses[1]
        if first.score - second.score >= 0.35:
            return None
        if first.label == "neutral" and first.score < 0.30 and not packet.explicit_report:
            return None

        assumptions = [
            "The current text/context is an adequate sample of the person's present state.",
            "At least one additional observation can distinguish the leading alternatives.",
        ]
        if packet.explicit_report:
            purpose = f"Resolve tension between direct self-report and inferred state, especially {first.label} vs {second.label}."
        else:
            purpose = f"Discriminate between leading hypotheses {first.label} and {second.label}."

        if {first.label, second.label} == {"excitement", "frustration"}:
            procedure = "Ask or observe a context-specific follow-up that distinguishes positive arousal from negative arousal without presupposing either."
            expected = {
                "excitement": "positive goal/outcome language or celebratory behavior",
                "frustration": "blocked-goal/negative-outcome language or irritation",
            }
        else:
            procedure = "Collect one additional low-cost contextual observation or explicit user clarification targeted at the leading ambiguity."
            expected = {
                first.label: "evidence consistent with the leading hypothesis",
                second.label: "evidence consistent with the competing hypothesis",
            }

        return TestSpec(
            test_id=f"test_{uuid.uuid4().hex[:8]}",
            name="leading-hypothesis discrimination",
            purpose=purpose,
            assumption_ids=["A1", "A2"],
            expected_if=expected,
            procedure=procedure,
        )


class CriticalReasoningEngine:
    """Domain-agnostic CRE logic layer for affective state inference."""

    def __init__(self) -> None:
        self.extractor = ObservationExtractor()
        self.hypotheses = AffectiveHypothesisEngine()
        self.discriminator = DiscriminationPlanner()

    def assess(self, packet: ObservationPacket, extra_tests: Iterable[Tuple[TestSpec, TestResult]] = (), *, method_id: str = "deterministic_heuristic_v1") -> AffectAssessment:
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        evidence = self.extractor.extract(packet)
        assumptions = self._build_assumptions(packet)
        hypotheses = self.hypotheses.generate(packet, evidence)
        trace = ReasoningTrace(
            proposition="What is the person's current affective state, and what response posture is most appropriate?",
            observations=evidence,
            assumptions=assumptions,
            hypotheses=hypotheses,
        )

        test = self.discriminator.plan(hypotheses, packet)
        if test:
            trace.tests.append(test)

        for spec, result in extra_tests:
            trace.tests.append(spec)
            trace.test_results.append(result)
            trace.divergences.extend(self._test_divergence(hypotheses, result))

        hypotheses = self._apply_test_results(hypotheses, trace.test_results)
        trace.hypotheses = hypotheses
        # Hypothesis-local assumptions are also part of the auditable trace.
        for hypothesis in hypotheses:
            for statement in hypothesis.assumptions:
                if not any(a.statement == statement for a in trace.assumptions):
                    trace.assumptions.append(Assumption(
                        assumption_id=f"AH_{uuid.uuid4().hex[:8]}",
                        statement=statement,
                        source=f"hypothesis:{hypothesis.label}",
                        confidence=0.60,
                        tested=False,
                    ))

        leading = hypotheses[0]
        second = hypotheses[1] if len(hypotheses) > 1 else None
        confidence = self._confidence(leading, second, trace.test_results)
        uncertainty = round(1.0 - confidence, 4)

        status = DeterminationStatus.COGENT if confidence >= 0.70 else DeterminationStatus.INCONCLUSIVE
        # High-value evidence is not itself a contradiction. Escalation is reserved
        # for material evidence that directly conflicts with the leading determination.
        if trace.divergences and any(d.get("is_contradiction") and d["materiality"] >= 0.8 for d in trace.divergences):
            status = DeterminationStatus.ESCALATE

        appraisal = self._appraise(leading.label, packet, confidence)
        formal = (
            f"Only God knows for certain. According to our assessment and the available tests, "
            f"the most likely answer is {leading.label}."
        )
        interpretive = self._interpret(leading, second, confidence, trace)
        trace.unresolved_questions = self._unresolved(leading, second, trace)

        return AffectAssessment(
            formal_determination=formal,
            run_id=run_id,
            method_id=method_id,
            confidence_type="uncalibrated_assessed_confidence",
            status=status,
            leading_state=leading.label,
            confidence=confidence,
            uncertainty=uncertainty,
            interpretive_assessment=interpretive,
            alternatives=[
                {"state": h.label, "score": h.score, "support": h.supporting_evidence, "contradictions": h.contradicting_evidence}
                for h in hypotheses[:4]
            ],
            response_appraisal=appraisal,
            trace=trace,
        )

    def best_of_three(self, assessments: Sequence[AffectAssessment]) -> Dict[str, Any]:
        if not assessments:
            raise ValueError("At least one assessment is required")
        if len(assessments) > 3:
            raise ValueError("Best-of-three accepts at most three assessments")

        labels = [a.leading_state for a in assessments]
        method_ids = [a.method_id for a in assessments]

        if len(assessments) == 1:
            return {
                "status": "need_martyr_run_1",
                "winner": None,
                "votes": labels,
                "root_cause_required": False,
                "independence_warning": False,
            }

        # Two agreeing runs are enough. Two disagreeing runs require the third.
        if len(assessments) == 2 and labels[0] != labels[1]:
            return {
                "status": "need_martyr_run_2",
                "winner": None,
                "votes": labels,
                "root_cause_required": True,
                "disagreements": [self._compare_runs(assessments[0], assessments[1])],
                "independence_warning": len(set(method_ids)) < 2,
            }

        counts = Counter(labels)
        winner, count = counts.most_common(1)[0]
        if count >= 2:
            disagreements = [
                self._compare_runs(assessments[0], assessments[i])
                for i in range(1, len(assessments))
                if assessments[i].leading_state != assessments[0].leading_state
            ]
            independent = len(set(method_ids)) >= min(3, len(assessments))
            return {
                "status": "cogent_majority" if independent else "majority_but_not_independent",
                "winner": winner if independent else None,
                "provisional_winner": winner,
                "votes": labels,
                "disagreements": disagreements,
                "root_cause_required": bool(disagreements),
                "independence_warning": len(set(method_ids)) < min(3, len(assessments)),
            }

        return {
            "status": "three_way_disagreement",
            "winner": None,
            "votes": labels,
            "root_cause_required": True,
            "independence_warning": len(set(method_ids)) < len(assessments),
            "reason": "Best-of-three produced no majority; investigate evidence, assumptions, tests, and inference differences.",
        }

    @staticmethod
    def _compare_runs(a: AffectAssessment, b: AffectAssessment) -> Dict[str, Any]:
        a_assumptions = {x.statement for x in a.trace.assumptions}
        b_assumptions = {x.statement for x in b.trace.assumptions}
        a_obs = {x.label for x in a.trace.observations}
        b_obs = {x.label for x in b.trace.observations}
        return {
            "run_a": a.run_id,
            "run_b": b.run_id,
            "method_a": a.method_id,
            "method_b": b.method_id,
            "state_a": a.leading_state,
            "state_b": b.leading_state,
            "confidence_a": a.confidence,
            "confidence_b": b.confidence,
            "shared_assumptions": sorted(a_assumptions & b_assumptions),
            "unique_assumptions_a": sorted(a_assumptions - b_assumptions),
            "unique_assumptions_b": sorted(b_assumptions - a_assumptions),
            "shared_observation_labels": sorted(a_obs & b_obs),
            "unique_observation_labels_a": sorted(a_obs - b_obs),
            "unique_observation_labels_b": sorted(b_obs - a_obs),
        }

    @staticmethod
    def _build_assumptions(packet: ObservationPacket) -> List[Assumption]:
        return [
            Assumption("A1", "Current observations are genuine measurements of the interaction.", "input contract", 0.90, tested=True),
            Assumption("A2", "Person-specific baseline is applicable to this context when supplied.", "profile/baseline", 0.75, tested=packet.baseline is not None),
            Assumption("A3", "Behavioral signals are probabilistic indicators rather than direct proof of emotion.", "CRE core rule", 1.00, tested=True),
            Assumption("A4", "Explicit current self-report is stronger evidence than weak behavioral inference.", "CRE evidence hierarchy", 0.95, tested=True),
        ]

    @staticmethod
    def _apply_test_results(hypotheses: Sequence[Hypothesis], results: Sequence[TestResult]) -> List[Hypothesis]:
        scores = {h.label: h.score for h in hypotheses}
        support = {h.label: list(h.supporting_evidence) for h in hypotheses}
        contradict = {h.label: list(h.contradicting_evidence) for h in hypotheses}
        for result in results:
            for state in result.supports:
                if state in scores:
                    scores[state] += 0.10 * result.materiality
                    support[state].append(f"test {result.test_id}: {result.observation}")
            for state in result.weakens:
                if state in scores:
                    scores[state] -= 0.08 * result.materiality
                    contradict[state].append(f"test {result.test_id}: {result.observation}")
        total = sum(max(v, 0.001) for v in scores.values())
        return sorted([
            replace(
                h,
                score=round(max(scores[h.label], 0.001) / total, 4),
                supporting_evidence=support[h.label],
                contradicting_evidence=contradict[h.label],
            )
            for h in hypotheses
        ], key=lambda h: h.score, reverse=True)

    @staticmethod
    def _test_divergence(hypotheses: Sequence[Hypothesis], result: TestResult) -> List[Dict[str, Any]]:
        leading = hypotheses[0].label if hypotheses else None
        is_contradiction = bool(leading and leading in result.weakens and leading not in result.supports)
        return [{
            "type": "test_result",
            "test_id": result.test_id,
            "materiality": result.materiality,
            "supports": result.supports,
            "weakens": result.weakens,
            "leading_before_test": leading,
            "is_contradiction": is_contradiction,
        }]

    @staticmethod
    def _confidence(leading: Hypothesis, second: Hypothesis | None, results: Sequence[TestResult]) -> float:
        # This is an uncalibrated ranking/confidence heuristic, never a probability.
        margin = leading.score - (second.score if second else 0.0)
        direct_report = any(
            "direct current self-report" in item
            for item in leading.supporting_evidence
        )
        direct_bonus = 0.16 if direct_report else 0.0
        test_bonus = min(0.10, sum(max(0.0, min(1.0, r.materiality)) for r in results) * 0.04)
        cap = 0.88 if direct_report else 0.97
        return round(max(0.0, min(cap, 0.45 + (margin * 1.5) + direct_bonus + test_bonus)), 4)

    @staticmethod
    def _interpret(leading: Hypothesis, second: Hypothesis | None, confidence: float, trace: ReasoningTrace) -> str:
        alt = second.label if second else "no strong alternative"
        caveat = "; additional testing is warranted" if trace.tests and not trace.test_results else ""
        return (
            f"The evidence most strongly supports {leading.label} ({confidence:.0%} assessed confidence), "
            f"with {alt} as the leading alternative. Behavioral evidence is probabilistic, not proof of inner state{caveat}."
        )

    @staticmethod
    def _unresolved(leading: Hypothesis, second: Hypothesis | None, trace: ReasoningTrace) -> List[str]:
        questions = list(leading.unresolved_questions)
        if second and second.score > 0.20:
            questions.append(f"What additional observation would best distinguish {leading.label} from {second.label}?")
        if trace.tests and not trace.test_results:
            questions.append("A planned discrimination test has not yet been executed.")
        return questions

    @staticmethod
    def _appraise(state: str, packet: ObservationPacket, confidence: float) -> ResponseAppraisal:
        context = str(packet.context.get("interaction_goal", "support the user appropriately"))
        # When the state inference is weak, the response strategy must not overcommit
        # to an emotional interpretation. Stay warm, curious, and low-assumption.
        if confidence < 0.65:
            return ResponseAppraisal(
                objective=f"stay responsive while resolving emotional ambiguity; interaction goal: {context}",
                desired_posture="warm, curious, non-assumptive",
                expressive_emotion="neutral warmth + curiosity",
                intensity=0.40,
                confidence=confidence,
                rationale=(
                    f"The leading state hypothesis ({state}) is not sufficiently separated from alternatives, "
                    "so expressive emotion is intentionally conservative."
                ),
            )

        mapping = {
            "excitement": ("celebrate", "energetic, warm, shared", "joy + pride"),
            "frustration": ("validate and reduce unnecessary load", "steady, warm, serious", "concern + solidarity"),
            "anger": ("acknowledge intensity without escalating it", "steady, respectful, firm", "calm solidarity"),
            "anxiety": ("reduce uncertainty and pressure", "calm, steady, reassuring", "calm concern"),
            "sadness": ("provide presence and avoid over-solving", "quiet, warm, patient", "tenderness + concern"),
            "grief": ("provide presence and respect the loss", "quiet, gentle, patient", "tenderness + reverence"),
            "fatigue": ("reduce cognitive demand", "gentle, low-density, unhurried", "care + quiet"),
            "neutral": ("continue naturally", "normal, curious, responsive", "neutral warmth"),
        }
        objective, posture, emotion = mapping[state]
        return ResponseAppraisal(
            objective=f"{objective}; interaction goal: {context}",
            desired_posture=posture,
            expressive_emotion=emotion,
            intensity=round(min(1.0, 0.35 + confidence * 0.5), 4),
            confidence=confidence,
            rationale=f"Response appraisal is based on the leading state hypothesis ({state}) without equating user state with required response emotion.",
        )


class CREStateStore:
    """Small atomic JSON-backed working-state store for context continuity."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path) if path else None
        self._state: Dict[str, Any] = {}
        if self.path and self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._state = loaded
            except (OSError, ValueError):
                self._state = {}

    def save(self, key: str, value: Mapping[str, Any]) -> None:
        self._state[key] = dict(value)
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    def load(self, key: str) -> Dict[str, Any] | None:
        value = self._state.get(key)
        return dict(value) if isinstance(value, dict) else None

    def snapshot(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self._state, ensure_ascii=False))
