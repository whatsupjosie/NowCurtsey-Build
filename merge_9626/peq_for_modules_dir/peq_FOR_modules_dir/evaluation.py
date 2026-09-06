from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class CalibrationCase:
    """A labeled evaluation case with a known or distributional target.

    ``expected_state`` is appropriate when the evaluation protocol establishes a
    single gold state. ``gold_distribution`` or ``acceptable_states`` is preferred
    for inherently ambiguous affect where multiple states are defensible.
    """
    case_id: str
    packet: Any
    expected_state: str | None = None
    gold_distribution: Mapping[str, float] | None = None
    acceptable_states: Sequence[str] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        supplied = int(self.expected_state is not None) + int(self.gold_distribution is not None) + int(bool(self.acceptable_states))
        if supplied != 1:
            raise ValueError("provide exactly one of expected_state, gold_distribution, or acceptable_states")
        if self.gold_distribution is not None:
            clean = {}
            for state, value in self.gold_distribution.items():
                v = float(value)
                if not math.isfinite(v) or v < 0:
                    raise ValueError("gold_distribution values must be finite and nonnegative")
                clean[str(state)] = v
            total = sum(clean.values())
            if total <= 0:
                raise ValueError("gold_distribution must contain positive mass")
            object.__setattr__(self, "gold_distribution", {k: v / total for k, v in clean.items()})


@dataclass(frozen=True)
class CalibrationReport:
    case_count: int
    hard_case_count: int
    soft_case_count: int
    acceptable_range_case_count: int
    accuracy: float
    target_alignment: float
    brier_score: float
    multiclass_log_loss: float
    expected_calibration_error: float
    max_wrong_confidence: float
    wrong_high_confidence_cases: Sequence[str] = ()
    warnings: Sequence[str] = ()
    calibrated_probability_status: str = "not_calibrated"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_count": self.case_count,
            "accuracy": self.accuracy,
            "brier_score": self.brier_score,
            "multiclass_log_loss": self.multiclass_log_loss,
            "expected_calibration_error": self.expected_calibration_error,
            "max_wrong_confidence": self.max_wrong_confidence,
            "wrong_high_confidence_cases": list(self.wrong_high_confidence_cases),
            "warnings": list(self.warnings),
            "calibrated_probability_status": self.calibrated_probability_status,
        }


def evaluate_calibration(
    cases: Iterable[CalibrationCase],
    assessor,
    *,
    bins: int = 10,
) -> CalibrationReport:
    """Evaluate posterior-score behavior against labeled cases.

    The report deliberately evaluates *posterior_score*, not operational
    confidence. Operational confidence is a bounded action-commitment metric,
    not a calibrated probability.
    """
    rows = list(cases)
    if not rows:
        raise ValueError("at least one calibration case is required")
    bins = max(2, min(50, int(bins)))

    brier = 0.0
    logloss = 0.0
    correct = 0
    alignment = 0.0
    hard_count = 0
    soft_count = 0
    acceptable_count = 0
    confidences: list[float] = []
    wrong_high: list[str] = []
    scored: list[tuple[float, bool]] = []
    eps = 1e-12

    for case in rows:
        result = assessor(case.packet)
        probs = {str(k): max(0.0, min(1.0, float(v))) for k, v in result.state.posterior_distribution.items()}
        predicted = result.state.leading_state
        if case.expected_state is not None:
            hard_count += 1
            expected = str(case.expected_state)
            target = {state: (1.0 if state == expected else 0.0) for state in probs}
            if expected not in probs:
                raise ValueError(f"calibration case {case.case_id} uses unknown state {expected!r}")
            is_correct = predicted == expected
            p_target = probs.get(expected, 0.0)
        elif case.gold_distribution is not None:
            soft_count += 1
            target = {state: float(case.gold_distribution.get(state, 0.0)) for state in probs}
            p_target = sum(probs.get(state, 0.0) * mass for state, mass in case.gold_distribution.items())
            is_correct = predicted == max(case.gold_distribution, key=case.gold_distribution.get)
        else:
            acceptable_count += 1
            allowed = set(case.acceptable_states)
            if not allowed:
                raise ValueError(f"calibration case {case.case_id} has no acceptable states")
            if not allowed.issubset(probs):
                raise ValueError(f"calibration case {case.case_id} uses unknown acceptable state")
            p_target = max((probs.get(state, 0.0) for state in allowed), default=0.0)
            target = {state: (1.0 / len(allowed) if state in allowed else 0.0) for state in probs}
            is_correct = predicted in allowed
        if is_correct:
            correct += 1
        else:
            wrong_high.append(case.case_id) if result.state.operational_confidence >= 0.80 else None
        scored.append((float(result.state.operational_confidence), is_correct))
        confidences.append(float(result.state.operational_confidence))
        alignment += p_target

        per_case_brier = sum((p - target.get(state, 0.0)) ** 2 for state, p in probs.items())
        brier += per_case_brier
        logloss -= math.log(max(eps, min(1.0, p_target)))

    # Reliability diagram bins over operational confidence, with explicit warning
    # that this is a commitment metric rather than calibrated probability.
    ece = 0.0
    for i in range(bins):
        lo = i / bins
        hi = (i + 1) / bins
        members = [pair for pair in scored if (lo <= pair[0] < hi) or (i == bins - 1 and pair[0] <= hi)]
        if not members:
            continue
        avg_conf = sum(c for c, _ in members) / len(members)
        avg_acc = sum(1.0 if ok else 0.0 for _, ok in members) / len(members)
        ece += (len(members) / len(scored)) * abs(avg_conf - avg_acc)

    max_wrong = max((conf for conf, ok in scored if not ok), default=0.0)
    warnings = [
        "This report does not establish real-world probability calibration.",
        "Labeled cases are only as valid as their annotation/ground-truth protocol.",
        "Operational confidence is measured separately from posterior_distribution and must not be described as calibrated probability.",
        "Brier score and log loss evaluate the engine posterior; ECE evaluates operational confidence as a commitment metric, not a probability estimate.",
    ]
    if wrong_high:
        warnings.append("At least one incorrect case exceeded 80% operational confidence; investigate before raising commitment thresholds.")

    return CalibrationReport(
        case_count=len(rows),
        hard_case_count=hard_count,
        soft_case_count=soft_count,
        acceptable_range_case_count=acceptable_count,
        accuracy=round(correct / len(rows), 4),
        target_alignment=round(alignment / len(rows), 4),
        brier_score=round(brier / len(rows), 4),
        multiclass_log_loss=round(logloss / len(rows), 4),
        expected_calibration_error=round(ece, 4),
        max_wrong_confidence=round(max_wrong, 4),
        wrong_high_confidence_cases=tuple(wrong_high),
        warnings=tuple(warnings),
    )
