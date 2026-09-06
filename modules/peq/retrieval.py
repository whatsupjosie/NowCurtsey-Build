from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, asdict
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from .clinical_evidence import (
    EVIDENCE_SOURCES,
    INSTRUMENT_EVIDENCE,
    INTERVENTION_EVIDENCE,
    POPULATION_DATASETS,
    PATTERNS,
    ClinicalPattern,
    EvidenceItem,
    InterventionEvidence,
    SourceRecord,
)


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'_-]{1,}", re.I)
_STOP = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "into", "than", "then",
    "they", "their", "them", "your", "you", "are", "was", "were", "has", "have",
    "had", "can", "may", "not", "but", "how", "what", "when", "where", "who",
    "why", "use", "used", "using", "more", "most", "less", "very", "one", "two",
})


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    evidence_types: Sequence[str] = ()
    source_types: Sequence[str] = ()
    domains: Sequence[str] = ()
    target_pattern_ids: Sequence[str] = ()
    target_states: Sequence[str] = ()
    top_k: int = 12
    alternatives_k: int = 5
    min_score: float = 0.08

    def __post_init__(self) -> None:
        if len(str(self.query or "")) > 4096:
            raise ValueError("retrieval query exceeds 4096 characters")
        if int(self.top_k) < 1 or int(self.top_k) > 50:
            raise ValueError("top_k must be between 1 and 50")
        if int(self.alternatives_k) < 0 or int(self.alternatives_k) > 20:
            raise ValueError("alternatives_k must be between 0 and 20")
        try:
            score = float(self.min_score)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("min_score must be numeric") from None
        if not 0.0 <= score <= 1.0:
            raise ValueError("min_score must be between 0 and 1")


@dataclass(frozen=True)
class OperationalValue:
    interaction: float = 0.0
    assessment: float = 0.0
    response: float = 0.0
    prediction: float = 0.0
    risk_management: float = 0.0
    test_selection: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def maximum(self) -> float:
        return max(
            self.interaction, self.assessment, self.response,
            self.prediction, self.risk_management, self.test_selection
        )

    @property
    def dimensions_present(self) -> Tuple[str, ...]:
        values = self.to_dict()
        return tuple(k for k, v in values.items() if v > 0.0)



@dataclass(frozen=True)
class RetrievedEvidence:
    evidence_id: str
    kind: str
    title: str
    score: float
    relevance: float
    authority: float
    diversity: float
    recency: float
    operational_value: OperationalValue = OperationalValue()
    source_ids: Sequence[str] = ()
    source_organizations: Sequence[str] = ()
    source_types: Sequence[str] = ()
    claim_or_scope: str = ""
    role: str = ""
    limitations: Sequence[str] = ()
    target_patterns: Sequence[str] = ()
    automation_status: str = "reference_only"
    why_retrieved: Sequence[str] = ()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalAlternative:
    item_id: str
    label: str
    rationale: str
    score: float
    distinct_from_leader: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceBundle:
    query: str
    primary: Sequence[RetrievedEvidence]
    alternatives: Sequence[RetrievalAlternative]
    uncovered_terms: Sequence[str]
    source_families: Sequence[str]
    operational_value: OperationalValue = OperationalValue()
    warnings: Sequence[str] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "primary": [x.to_dict() for x in self.primary],
            "alternatives": [x.to_dict() for x in self.alternatives],
            "uncovered_terms": list(self.uncovered_terms),
            "source_families": list(self.source_families),
            "operational_value": self.operational_value.to_dict(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class _IndexedItem:
    item_id: str
    kind: str
    title: str
    text: str
    source_ids: Tuple[str, ...]
    source_types: Tuple[str, ...]
    source_organizations: Tuple[str, ...]
    claim_or_scope: str
    role: str
    limitations: Tuple[str, ...]
    target_patterns: Tuple[str, ...] = ()
    evidence_type: str = ""
    automation_status: str = "reference_only"
    year: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)


class PEQEvidenceRetriever:
    """Fast, provenance-aware retrieval over the curated PEQ evidence registry.

    Retrieval is a *research navigation* operation. It does not declare any
    retrieved source to be true, nor does it collapse a heterogeneous literature
    into a single answer. Ranking favors semantic term overlap, source quality,
    and coverage while actively diversifying source families.
    """

    OPERATIONAL_TERMS: Mapping[str, Tuple[str, ...]] = {
        "interaction": (
            "communication", "collaboration", "alliance", "rapport", "trust",
            "grounding", "transparency", "agency", "interaction", "relationship",
        ),
        "assessment": (
            "assessment", "measure", "measurement", "validity", "reliability",
            "symptom", "trait", "prevalence", "screening", "construct", "psychometric",
        ),
        "response": (
            "response", "intervention", "therapy", "treatment", "guideline",
            "strategy", "approach", "management", "care", "coping",
        ),
        "prediction": (
            "predict", "prediction", "prospective", "longitudinal", "course",
            "trajectory", "risk factor", "outcome", "forecast",
        ),
        "risk_management": (
            "risk", "safety", "harm", "adverse", "contraindication", "monitor",
            "screen", "warning", "crisis", "retraumatization",
        ),
        "test_selection": (
            "differentiate", "differential", "distinguish", "compare", "discriminate",
            "moderator", "mechanism", "confound", "uncertainty", "hypothesis",
        ),
    }

    AUTHORITY_BY_TYPE: Mapping[str, float] = {
        "peer_reviewed_meta_analysis": 1.00,
        "peer_reviewed_network_meta_analysis": 1.00,
        "peer_reviewed_umbrella_review": 1.00,
        "clinical_practice_guideline": 0.98,
        "professional_practice_guideline": 0.98,
        "international_clinical_guideline": 0.97,
        "psychometric_meta_analysis": 0.96,
        "psychometric_review": 0.95,
        "validated_measure": 0.91,
        "large_longitudinal_cohort": 0.90,
        "large_diverse_us_cohort": 0.90,
        "national_probability_panel": 0.89,
        "national_population_exam_survey": 0.88,
        "national_population_survey": 0.87,
        "federal_clinical_education": 0.86,
        "federal_health_information": 0.84,
        "federal_guidance": 0.84,
        "professional_personality_measure": 0.90,
    }

    RECENCY_HALF_LIFE_YEARS = 12.0

    def __init__(self) -> None:
        self._items: Tuple[_IndexedItem, ...] = self._build_items()
        self._token_index: Dict[str, List[int]] = defaultdict(list)
        self._source_family: Dict[str, str] = {}
        for idx, item in enumerate(self._items):
            for token in _tokenize(item.text):
                self._token_index[token].append(idx)
            for sid in item.source_ids:
                self._source_family[sid] = self._family_for_source(sid)

    @staticmethod
    def _family_for_source(source_id: str) -> str:
        lower = source_id.casefold()
        if lower.startswith(("cdc_", "nih_", "uk_", "pew_")):
            return "population"
        if lower.startswith(("apa_", "who_", "va_", "samhsa_", "nimh_")):
            return "clinical_guidance"
        if "pubmed" in lower or lower.endswith(("_meta", "_nma", "_umbrella")):
            return "peer_reviewed"
        if lower.startswith(("rtds_", "crema", "ravdess", "meld", "emotion")):
            return "behavioral_dataset"
        return "other"

    def _build_items(self) -> Tuple[_IndexedItem, ...]:
        items: List[_IndexedItem] = []

        combined_sources: Dict[str, SourceRecord] = {}
        combined_sources.update(EVIDENCE_SOURCES)
        combined_sources.update(POPULATION_DATASETS)

        # Index the underlying scientific sources themselves so retrieval can land
        # directly on a paper, guideline, dataset, or public-health source rather
        # than only on derived EvidenceItem records.
        for source in combined_sources.values():
            items.append(_IndexedItem(
                item_id=source.source_id,
                kind="scientific_source" if source.source_type not in {"national_population_survey", "national_population_exam_survey", "large_longitudinal_cohort", "large_diverse_us_cohort", "national_probability_panel"} else "population_dataset",
                title=source.title,
                text=" ".join([source.title, source.organization, source.scope, source.evidentiary_role, *source.limitations]),
                source_ids=(source.source_id,),
                source_types=(source.source_type,),
                source_organizations=(source.organization,),
                claim_or_scope=source.scope,
                role=source.evidentiary_role,
                limitations=tuple(source.limitations),
                evidence_type=source.source_type,
                year=source.year,
                automation_status="reference_only",
            ))

        for item in INSTRUMENT_EVIDENCE.values():
            sources = [combined_sources[sid] for sid in item.source_ids if sid in combined_sources]
            source_types = tuple(sorted({s.source_type for s in sources}))
            orgs = tuple(sorted({s.organization for s in sources}))
            scopes = [s.scope for s in sources]
            limitations = tuple(dict.fromkeys([*item.limits, *(lim for s in sources for lim in s.limitations)]))
            items.append(_IndexedItem(
                item_id=item.evidence_id,
                kind="measurement_or_framework",
                title=item.title,
                text=" ".join([item.title, item.claim, item.role_in_peq, *item.limits, *scopes]),
                source_ids=tuple(item.source_ids),
                source_types=source_types,
                source_organizations=orgs,
                claim_or_scope=item.claim,
                role=item.role_in_peq,
                limitations=limitations,
                evidence_type=item.evidence_type,
                automation_status=item.automation_status,
                year=item.year,
            ))

        for item in INTERVENTION_EVIDENCE.values():
            sources = [combined_sources[sid] for sid in item.evidence_source_ids if sid in combined_sources]
            source_types = tuple(sorted({s.source_type for s in sources}))
            orgs = tuple(sorted({s.organization for s in sources}))
            limitations = tuple(dict.fromkeys([item.notes, *(lim for s in sources for lim in s.limitations)]))
            items.append(_IndexedItem(
                item_id=item.intervention_id,
                kind="intervention",
                title=item.intervention,
                text=" ".join([item.intervention, item.evidence_summary, item.evidence_strength, item.appropriate_for_peq, *item.target_patterns, item.notes]),
                source_ids=tuple(item.evidence_source_ids),
                source_types=source_types,
                source_organizations=orgs,
                claim_or_scope=item.evidence_summary,
                role=item.appropriate_for_peq,
                limitations=limitations,
                target_patterns=tuple(item.target_patterns),
                automation_status="reference_only" if item.requires_clinician else "reference_plus_safe_principles",
                year=max((s.year for s in sources), default=0),
            ))

        for pattern in PATTERNS.values():
            sources = [combined_sources[sid] for sid in pattern.source_ids if sid in combined_sources]
            source_types = tuple(sorted({s.source_type for s in sources}))
            orgs = tuple(sorted({s.organization for s in sources}))
            limitations = tuple(dict.fromkeys([*pattern.contraindications, *(lim for s in sources for lim in s.limitations)]))
            items.append(_IndexedItem(
                item_id=pattern.pattern_id,
                kind="working_pattern",
                title=pattern.label,
                text=" ".join([pattern.label, pattern.category, *pattern.signs, pattern.interpretation_rule, *pattern.response_principles, *pattern.contraindications, pattern.notes]),
                source_ids=tuple(pattern.source_ids),
                source_types=source_types,
                source_organizations=orgs,
                claim_or_scope=pattern.interpretation_rule,
                role="non-diagnostic working hypothesis and response-principle reference",
                limitations=limitations,
                target_patterns=(pattern.pattern_id,),
                automation_status="working_hypothesis_only",
                year=max((s.year for s in sources), default=0),
            ))

        return tuple(items)

    def retrieve(self, request: RetrievalRequest) -> EvidenceBundle:
        query_tokens = _tokenize(request.query)
        if not query_tokens:
            return EvidenceBundle(
                query=request.query,
                primary=(),
                alternatives=(),
                uncovered_terms=(),
                source_families=(),
                warnings=("Empty retrieval query; no evidence was selected.",),
            )

        candidate_idxs: set[int] = set()
        # Bound candidate generation so pathological repeated/huge query tokens
        # cannot create an accidental quadratic workload.
        query_tokens = query_tokens[:64]
        for token in query_tokens:
            candidate_idxs.update(self._token_index.get(token, ()))
        if not candidate_idxs:
            # Scan is still bounded because the registry is curated and small; this
            # keeps morphology/phrase changes from producing a false empty result.
            candidate_idxs = set(range(len(self._items)))

        scored: List[Tuple[float, _IndexedItem, Dict[str, float], List[str]]] = []
        for idx in candidate_idxs:
            item = self._items[idx]
            if not self._passes_filters(item, request):
                continue
            score, components, reasons = self._score(item, query_tokens, request)
            if score >= request.min_score:
                scored.append((score, item, components, reasons))

        scored.sort(key=lambda x: (x[0], x[1].year, x[1].item_id), reverse=True)
        primary = self._diversify(scored, max(1, min(50, request.top_k)))

        chosen_ids = {item.item_id for _, item, _, _ in primary}
        alternatives = self._alternatives(scored, chosen_ids, request.alternatives_k)

        covered = set()
        for _, item, _, _ in scored:
            if item.item_id in chosen_ids:
                covered.update(set(_tokenize(item.text)) & set(query_tokens))
        uncovered = [term for term in query_tokens if term not in covered]

        source_families = sorted({family for _, item, _, _ in primary for sid in item.source_ids for family in [self._family_for_source(sid)]})
        primary_rendered = tuple(self._render(item, score, components, reasons) for score, item, components, reasons in primary)
        dim_max = {
            name: max((getattr(item.operational_value, name) for item in primary_rendered), default=0.0)
            for name in OperationalValue().to_dict().keys()
        }
        operational_value = OperationalValue(**dim_max)
        warnings: List[str] = []
        if not primary:
            warnings.append("No high-relevance evidence item met the retrieval threshold.")
        if len(source_families) == 1 and len(primary) > 1:
            warnings.append("Retrieved evidence is concentrated in one source family; seek an independent source family before treating convergence as strong.")
        if uncovered:
            warnings.append("Some query terms were not represented in the selected evidence; absence from the registry is not evidence against the proposition.")

        if operational_value.maximum == 0.0 and primary_rendered:
            warnings.append("Retrieved evidence has low explicit operational value across interaction, assessment, response, prediction, risk management, and test selection.")

        return EvidenceBundle(
            query=request.query,
            primary=primary_rendered,
            alternatives=tuple(alternatives),
            uncovered_terms=tuple(dict.fromkeys(uncovered)),
            source_families=tuple(source_families),
            operational_value=operational_value,
            warnings=tuple(warnings),
        )

    def retrieve_for_packet(self, packet: Any, *, top_k: int = 12, alternatives_k: int = 5) -> EvidenceBundle:
        context_bits: List[str] = []
        if getattr(packet, "explicit_report", None):
            context_bits.append(str(packet.explicit_report))
        if getattr(packet, "text", None):
            context_bits.append(str(packet.text))
        context = getattr(packet, "context", {}) or {}
        for key in ("situation", "interaction_goal", "topic", "task"):
            value = context.get(key)
            if value:
                context_bits.append(str(value))
        profile = getattr(packet, "profile_facts", {}) or {}
        for key, value in list(profile.items())[:12]:
            context_bits.append(f"{key} {value}")
        request = RetrievalRequest(query=" ".join(context_bits), top_k=top_k, alternatives_k=alternatives_k)
        return self.retrieve(request)


    def rank_working_patterns(self, observed_signs: Sequence[str], *, top_k: int = 5) -> List[Dict[str, Any]]:
        """Return a ranked *range* of non-diagnostic working patterns.

        A pattern match is never a diagnosis. The ranking is based only on overlap
        between observed signs and the pattern's documented sign vocabulary.
        Results intentionally retain multiple plausible alternatives.
        """
        observed = {_normalize_phrase(x) for x in observed_signs if str(x).strip()}
        if not observed:
            return []
        rows: List[Tuple[float, ClinicalPattern, List[str], List[str]]] = []
        for pattern in PATTERNS.values():
            sign_map = {_normalize_phrase(x): x for x in pattern.signs}
            matched = [sign_map[x] for x in observed if x in sign_map]
            missing = [x for x in pattern.signs if _normalize_phrase(x) not in observed]
            ratio = len(matched) / max(1, len(pattern.signs))
            # Coverage of what was observed prevents a long pattern with only a
            # tiny denominator from dominating when observations are sparse.
            observation_coverage = len(matched) / max(1, len(observed))
            score = 0.65 * ratio + 0.35 * observation_coverage
            rows.append((score, pattern, matched, missing))
        rows.sort(key=lambda x: (x[0], x[1].pattern_id), reverse=True)
        # Do not pad the range with zero-match patterns. That would create the
        # appearance of a live alternative when the evidence does not actually
        # support it. A shorter, evidence-supported range is more honest.
        positive_rows = [row for row in rows if row[0] > 0.0]
        out: List[Dict[str, Any]] = []
        for score, pattern, matched, missing in positive_rows[: max(1, min(20, top_k))]:
            out.append({
                "pattern_id": pattern.pattern_id,
                "label": pattern.label,
                "status": "working_hypothesis",
                "diagnosis": "none",
                "score": round(score, 4),
                "matched_signs": matched,
                "missing_signs": missing,
                "response_principles": list(pattern.response_principles),
                "source_ids": list(pattern.source_ids),
                "limitations": list(pattern.contraindications),
            })
        return out

    def _passes_filters(self, item: _IndexedItem, request: RetrievalRequest) -> bool:
        if request.evidence_types and item.evidence_type not in set(request.evidence_types):
            return False
        if request.source_types and not (set(item.source_types) & set(request.source_types)):
            return False
        if request.target_pattern_ids and not (set(item.target_patterns) & set(request.target_pattern_ids)):
            return False
        if request.domains:
            haystack = f"{item.kind} {item.claim_or_scope} {item.role}".casefold()
            if not any(domain.casefold() in haystack for domain in request.domains):
                return False
        if request.target_states:
            haystack = item.text.casefold()
            if not any(state.casefold() in haystack for state in request.target_states):
                return False
        return True

    def _operational_value(self, item: _IndexedItem) -> OperationalValue:
        text = " ".join([item.title, item.claim_or_scope, item.role, *item.limitations]).casefold()
        values: Dict[str, float] = {}
        for dimension, terms in self.OPERATIONAL_TERMS.items():
            hits = sum(1 for term in terms if term in text)
            values[dimension] = min(1.0, hits / 3.0)
        # Structural boosts reflect what an evidence record is designed to do,
        # without making source type alone into evidence of content.
        if item.kind == "intervention":
            values["response"] = max(values["response"], 0.9)
            values["interaction"] = max(values["interaction"], 0.35)
        elif item.kind == "measurement_or_framework":
            values["assessment"] = max(values["assessment"], 0.9)
            values["test_selection"] = max(values["test_selection"], 0.35)
        elif item.kind == "working_pattern":
            values["assessment"] = max(values["assessment"], 0.75)
            values["response"] = max(values["response"], 0.65)
            values["risk_management"] = max(values["risk_management"], 0.35)
        elif item.kind == "population_dataset":
            values["assessment"] = max(values["assessment"], 0.8)
            values["prediction"] = max(values["prediction"], 0.45)
        elif item.kind == "scientific_source":
            values["assessment"] = max(values["assessment"], 0.35)
        return OperationalValue(**values)

    def _score(self, item: _IndexedItem, query_tokens: Sequence[str], request: RetrievalRequest) -> Tuple[float, Dict[str, float], List[str]]:
        tokens = set(_tokenize(item.text))
        qset = set(query_tokens)
        overlap = len(qset & tokens) / max(1, len(qset))
        rare_bonus = sum(1.0 for token in qset if token in tokens and len(token) >= 7) / max(1, len(qset))
        title_overlap = len(set(_tokenize(item.title)) & qset) / max(1, len(qset))
        authority = max((self.AUTHORITY_BY_TYPE.get(st, 0.70) for st in item.source_types), default=0.65)
        recency = self._recency(item.year)
        operational = self._operational_value(item)
        utility = operational.maximum
        kind_bonus = 0.08 if item.kind in {"working_pattern", "intervention", "measurement_or_framework"} else 0.0
        score = (
            0.45 * overlap
            + 0.11 * title_overlap
            + 0.07 * rare_bonus
            + 0.19 * authority
            + 0.05 * recency
            + 0.09 * utility
            + kind_bonus
        )
        reasons = []
        if overlap:
            reasons.append(f"query term coverage {overlap:.0%}")
        if title_overlap:
            reasons.append("title directly overlaps query")
        if authority >= 0.95:
            reasons.append("high-authority evidence type")
        if item.source_ids:
            reasons.append(f"provenance attached to {len(item.source_ids)} registered source(s)")
        components = {
            "term_overlap": overlap,
            "title_overlap": title_overlap,
            "authority": authority,
            "recency": recency,
            "operational_value": utility,
        }
        return min(1.0, score), components, reasons

    def _diversify(self, scored: Sequence[Tuple[float, _IndexedItem, Dict[str, float], List[str]]], k: int):
        selected: List[Tuple[float, _IndexedItem, Dict[str, float], List[str]]] = []
        family_counts: Dict[str, int] = defaultdict(int)
        for row in scored:
            if len(selected) >= k:
                break
            score, item, components, reasons = row
            families = {self._family_for_source(sid) for sid in item.source_ids} or {"other"}
            repetition = sum(family_counts[f] for f in families)
            adjusted = score - min(0.16, 0.04 * repetition)
            if adjusted < score * 0.72 and len(selected) >= max(2, k // 3):
                continue
            selected.append((adjusted, item, components, reasons + (["diversified against repeated source family"] if adjusted < score else [])))
            for family in families:
                family_counts[family] += 1
        return selected

    def _alternatives(self, scored: Sequence[Tuple[float, _IndexedItem, Dict[str, float], List[str]]], chosen_ids: set[str], k: int) -> List[RetrievalAlternative]:
        out: List[RetrievalAlternative] = []
        if k <= 0 or not scored:
            return out

        primary_kind = next((item.kind for _, item, _, _ in scored if item.item_id in chosen_ids), None)
        candidates = [row for row in scored if row[1].item_id not in chosen_ids]

        # If top-K consumed the entire distinct ranked set, retain secondary ranked
        # interpretations from the primary set rather than inventing unsupported
        # possibilities. These alternatives are explicitly marked
        # ``distinct_from_leader=False`` so callers cannot mistake them for new evidence.
        if not candidates:
            candidates = list(scored[1:])

        for score, item, _, _ in candidates:
            if len(out) >= k:
                break
            distinct = primary_kind is None or item.kind != primary_kind
            rationale = (
                "Secondary evidence path retained to prevent premature closure."
                if distinct else
                "Secondary ranked interpretation retained because the evidence does not justify collapsing to one answer."
            )
            out.append(RetrievalAlternative(item.item_id, item.title, rationale, round(score, 4), distinct))
        return out

    def _render(self, item: _IndexedItem, score: float, components: Mapping[str, float], reasons: Sequence[str]) -> RetrievedEvidence:
        authority = float(components["authority"])
        recency = float(components["recency"])
        diversity = 1.0 if item.source_ids else 0.5
        return RetrievedEvidence(
            evidence_id=item.item_id,
            kind=item.kind,
            title=item.title,
            score=round(score, 4),
            relevance=round(components["term_overlap"] * 0.7 + components["title_overlap"] * 0.3, 4),
            authority=round(authority, 4),
            diversity=round(diversity, 4),
            recency=round(recency, 4),
            operational_value=self._operational_value(item),
            source_ids=item.source_ids,
            source_organizations=item.source_organizations,
            source_types=item.source_types,
            claim_or_scope=item.claim_or_scope,
            role=item.role,
            limitations=item.limitations,
            target_patterns=item.target_patterns,
            automation_status=item.automation_status,
            why_retrieved=tuple(reasons),
        )

    @classmethod
    def _recency(cls, year: int) -> float:
        if year <= 0:
            return 0.55
        # Keep older landmark evidence relevant; recency is deliberately weak.
        import datetime
        current = datetime.datetime.now(datetime.timezone.utc).year
        age = max(0, current - year)
        return 0.5 ** (age / cls.RECENCY_HALF_LIFE_YEARS)


def _tokenize(text: str) -> List[str]:
    tokens = []
    for raw in _TOKEN_RE.findall((text or "").casefold()):
        token = raw.strip("_-'")
        if len(token) < 3 or token in _STOP:
            continue
        tokens.append(token)
    return tokens


def _normalize_phrase(text: str) -> str:
    return " ".join(_tokenize(text))
