from __future__ import annotations

from typing import Any, Dict, List, Mapping

from .models import (
    MAX_OPERATIONAL_CONFIDENCE,
    PEQResponseResult,
    PEQStateResult,
    ResponseCandidate,
    ResponseModulation,
)


class PEQResponseEngine:
    """Answer the separate question: what response is most appropriate?"""

    BASE_RESPONSES: Mapping[str, Dict[str, Any]] = {
        "excitement": {
            "response": "celebrate with the user",
            "posture": "energetic, warm, shared",
            "emotion": "joy + pride",
            "base_intensity": 0.78,
        },
        "frustration": {
            "response": "acknowledge the frustration and reduce unnecessary cognitive load",
            "posture": "steady, warm, serious",
            "emotion": "concern + solidarity",
            "base_intensity": 0.68,
        },
        "anger": {
            "response": "acknowledge the intensity without escalating it",
            "posture": "steady, respectful, firm",
            "emotion": "calm solidarity",
            "base_intensity": 0.72,
        },
        "anxiety": {
            "response": "reduce uncertainty and pressure while preserving agency",
            "posture": "calm, steady, reassuring",
            "emotion": "calm concern",
            "base_intensity": 0.64,
        },
        "sadness": {
            "response": "provide presence and avoid over-solving",
            "posture": "quiet, warm, patient",
            "emotion": "tenderness + concern",
            "base_intensity": 0.58,
        },
        "grief": {
            "response": "provide presence and respect the loss",
            "posture": "quiet, gentle, patient",
            "emotion": "tenderness + reverence",
            "base_intensity": 0.54,
        },
        "fatigue": {
            "response": "reduce cognitive demand and keep the interaction low-density",
            "posture": "gentle, low-density, unhurried",
            "emotion": "care + quiet",
            "base_intensity": 0.48,
        },
        "neutral": {
            "response": "continue naturally without inventing an emotional need",
            "posture": "normal, curious, responsive",
            "emotion": "neutral warmth",
            "base_intensity": 0.40,
        },
    }

    def assess(
        self,
        state: PEQStateResult,
        *,
        context: Mapping[str, Any] | None = None,
        relationship: Mapping[str, Any] | None = None,
        stakes: float = 0.5,
    ) -> PEQResponseResult:
        context = dict(context or {})
        relationship = dict(relationship or {})
        confidence = self._finite_unit(state.operational_confidence, default=0.0)
        stakes = self._finite_unit(stakes, default=0.5)
        candidates = self._candidates(state.leading_state, state.candidates, state.operational_confidence, context, relationship, stakes, state.truth_assessment.status.value)
        response_confidence = self._response_confidence(candidates, confidence, stakes)
        modulation = self._modulation(response_confidence, stakes)
        intensity = self._intensity(state.leading_state, response_confidence, stakes)

        goal = context.get("interaction_goal", "support the user appropriately")
        relationship_name = relationship.get("relationship", "the current relationship")
        recommended = candidates[0].response
        rationale = (
            f"PEQ Response is a separate inference from PEQ State. The assessed state is {state.leading_state}; "
            f"the interaction goal is {goal}; relationship context is {relationship_name}. "
            f"Because response-appraisal confidence is {response_confidence:.1%}, response intensity is modulated to {modulation.value}."
        )
        explanation = (
            f"Recommended response: {recommended}. "
            f"This is not an instruction to mirror the user's emotion. It is the response with the highest current appraisal score. "
            f"Error-cost control reduces commitment when confidence is lower and permits stronger expression when confidence is high. "
            f"Operational confidence remains capped at {MAX_OPERATIONAL_CONFIDENCE:.1%}."
        )

        return PEQResponseResult(
            question="Given the assessed state and available context, what response is most likely to be appropriate?",
            recommended_response=recommended,
            operational_confidence=round(min(MAX_OPERATIONAL_CONFIDENCE, response_confidence), 4),
            modulation=modulation,
            intensity=intensity,
            candidates=candidates,
            rationale=rationale,
            explanation=explanation,
        )

    def _candidates(
        self,
        state: str,
        state_candidates: List[Any],
        state_confidence: float,
        context: Mapping[str, Any],
        relationship: Mapping[str, Any],
        stakes: float,
        truth_status: str,
    ) -> List[ResponseCandidate]:
        primary = self.BASE_RESPONSES.get(state, self.BASE_RESPONSES["neutral"])
        candidate_specs = [(
            primary["response"],
            primary["posture"],
            0.0,
            f"Primary response family for the assessed state {state}.",
        )]

        state_prob = next((float(c.posterior_score) for c in state_candidates if c.state == state), 0.0)
        state_confidence = max(0.0, min(MAX_OPERATIONAL_CONFIDENCE, float(state_confidence)))
        goal_text = str(context.get("interaction_goal", "")).casefold()
        relationship_text = str(relationship.get("relationship", "")).casefold()

        def goal_bonus(*terms: str) -> float:
            return 0.12 if any(term in goal_text for term in terms) else 0.0

        primary_score = 0.30 + 0.55 * state_confidence + 0.10 * state_prob + goal_bonus(
            "celebrate", "encourage", "engage", "support"
        )
        if truth_status == "contested":
            primary_score -= 0.42
        elif truth_status == "inconclusive":
            # When the state is not truth-tested to a supported conclusion, a
            # state-specific response must lose substantial ground to reversible,
            # low-assumption alternatives. Uncertainty should change behavior,
            # not merely the displayed confidence number.
            primary_score -= 0.30
        if state in {"anger", "frustration"}:
            primary_score += goal_bonus("de-escalate", "calm", "clarify")
        if state in {"anxiety", "sadness", "grief"}:
            primary_score += goal_bonus("comfort", "reassure", "support", "listen")
        candidate_specs[0] = (primary["response"], primary["posture"], min(1.0, primary_score), candidate_specs[0][3])

        neutral = self.BASE_RESPONSES["neutral"]
        neutral_score = 0.25 + 0.42 * max(0.0, 1.0 - state_confidence) + (0.08 if stakes > 0.75 else 0.0)
        if truth_status == "inconclusive":
            neutral_score += 0.16
        elif truth_status == "contested":
            neutral_score += 0.28
        candidate_specs.append((
            neutral["response"], neutral["posture"], min(1.0, neutral_score),
            "Reversible low-assumption alternative when state or response fit is uncertain.",
        ))

        if truth_status in {"contested", "inconclusive"} and len(state_candidates) >= 2:
            second_state = state_candidates[1].state
            mixed_score = 0.42 + 0.18 * (1.0 - state_confidence)
            candidate_specs.append((
                f"acknowledge the mixed signal without forcing a single emotional interpretation",
                "curious, steady, non-assumptive",
                min(1.0, mixed_score + (0.08 if truth_status == "contested" else 0.0)),
                f"The state evidence leaves {state} and {second_state} insufficiently resolved; preserve both possibilities.",
            ))

        if state in {"anger", "frustration"}:
            clarify_score = 0.18 + 0.42 * max(0.0, 1.0 - state_confidence) + (0.12 if stakes > 0.65 else 0.0)
            if truth_status == "contested":
                clarify_score += 0.16
            elif truth_status == "inconclusive":
                clarify_score += 0.10
            candidate_specs.append((
                "ask one precise clarifying question before escalating commitment",
                "steady, curious, non-assumptive",
                clarify_score,
                "Useful when the emotional state is plausible but the user's desired intervention remains unclear.",
            ))

        if relationship_text in {"new_person", "acquaintance", "stranger", "unknown"}:
            candidate_specs.append((
                "use a respectful low-assumption response and gather more evidence",
                "warm, neutral, observant",
                0.42,
                "New/uncertain relationship context increases the value of reversible interaction.",
            ))

        max_score = max(score for _, _, score, _ in candidate_specs)
        normalized = [
            ResponseCandidate(
                response=response,
                score=round(score / max(1.0, max_score), 4),
                rationale=rationale,
            )
            for response, _, score, rationale in candidate_specs
        ]
        return sorted(normalized, key=lambda c: c.score, reverse=True)

    @staticmethod
    def _response_confidence(candidates: List[ResponseCandidate], state_confidence: float, stakes: float) -> float:
        if not candidates:
            return 0.0
        top = candidates[0].score
        second = candidates[1].score if len(candidates) > 1 else 0.0
        margin = max(0.0, top - second)
        risk_penalty = 0.10 * max(0.0, min(1.0, stakes) - 0.5)
        return round(min(MAX_OPERATIONAL_CONFIDENCE, max(0.0, 0.35 + 0.45 * state_confidence + 0.30 * margin - risk_penalty)), 4)

    @staticmethod
    def _finite_unit(value: Any, *, default: float) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            return default
        if value != value or value in (float("inf"), float("-inf")):
            return default
        return max(0.0, min(1.0, value))

    @staticmethod
    def _modulation(confidence: float, stakes: float) -> ResponseModulation:
        # Stakes raise caution when wrong-response cost is high; confidence still matters most.
        effective = confidence - (max(0.0, min(1.0, stakes)) - 0.5) * 0.20
        if effective >= 0.80:
            return ResponseModulation.FULL
        if effective >= 0.62:
            return ResponseModulation.RESTRAINED
        return ResponseModulation.CONSERVATIVE

    @staticmethod
    def _intensity(state: str, confidence: float, stakes: float) -> float:
        base = PEQResponseEngine.BASE_RESPONSES.get(state, PEQResponseEngine.BASE_RESPONSES["neutral"])["base_intensity"]
        # Confidence determines commitment; stakes softly pull toward reversibility.
        raw = base * (0.45 + 0.55 * confidence) * (1.0 - 0.18 * max(0.0, min(1.0, stakes)))
        return round(max(0.15, min(1.0, raw)), 4)
