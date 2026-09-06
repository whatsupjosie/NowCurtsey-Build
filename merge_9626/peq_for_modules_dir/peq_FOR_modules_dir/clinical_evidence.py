from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Mapping, Sequence


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    organization: str
    title: str
    source_type: str
    year: int
    url: str
    scope: str
    evidentiary_role: str
    limitations: Sequence[str] = ()

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ClinicalPattern:
    pattern_id: str
    label: str
    category: str
    diagnostic_status: str
    signs: Sequence[str]
    interpretation_rule: str
    response_principles: Sequence[str]
    contraindications: Sequence[str]
    source_ids: Sequence[str]
    notes: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PatternHypothesis:
    pattern_id: str
    label: str
    matched_signs: Sequence[str]
    missing_signs: Sequence[str]
    match_ratio: float
    status: str = "working_hypothesis"
    diagnosis: str = "none"
    predicted_response_principles: Sequence[str] = ()
    source_ids: Sequence[str] = ()

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


SOURCES: Mapping[str, SourceRecord] = {
    "nimh_ptsd": SourceRecord(
        source_id="nimh_ptsd",
        organization="National Institute of Mental Health",
        title="Post-Traumatic Stress Disorder (PTSD)",
        source_type="federal_health_information",
        year=2026,
        url="https://www.nimh.nih.gov/health/topics/post-traumatic-stress-disorder-ptsd",
        scope="PTSD signs, course, and distinction between trauma reactions and diagnosis.",
        evidentiary_role="symptom-pattern reference; not individual diagnosis",
        limitations=("Educational summary is not a diagnostic instrument.",),
    ),
    "va_dod_ptsd_2023": SourceRecord(
        source_id="va_dod_ptsd_2023",
        organization="U.S. Department of Veterans Affairs / Department of Defense",
        title="Clinical Practice Guideline for Management of Posttraumatic Stress Disorder and Acute Stress Disorder",
        source_type="clinical_practice_guideline",
        year=2023,
        url="https://www.healthquality.va.gov/guidelines/MH/ptsd/",
        scope="Evidence-based clinical assessment and management of PTSD/acute stress disorder.",
        evidentiary_role="response-principle reference; clinician-focused",
        limitations=("Clinical guideline for professionals; not a companion diagnosis engine.",),
    ),
    "samhsa_trauma_informed": SourceRecord(
        source_id="samhsa_trauma_informed",
        organization="SAMHSA",
        title="Trauma-Informed Approaches and Programs",
        source_type="federal_guidance",
        year=2026,
        url="https://www.samhsa.gov/mental-health/trauma-violence/trauma-informed-approaches-programs",
        scope="Safety, trust, collaboration, empowerment, and resistance to retraumatization.",
        evidentiary_role="interaction-response principles",
        limitations=("Framework guidance rather than a quantitative symptom classifier.",),
    ),
    "va_ptsd_triggers": SourceRecord(
        source_id="va_ptsd_triggers",
        organization="VA National Center for PTSD",
        title="Trauma Reminders: Triggers",
        source_type="federal_clinical_education",
        year=2026,
        url="https://www.ptsd.va.gov/understand/what/trauma_triggers.asp",
        scope="Trauma reminders, hypervigilance/guardedness, avoidance, and reactions to reminders.",
        evidentiary_role="symptom-pattern and contextual-response reference",
        limitations=("Veteran-focused material may not generalize perfectly to every population.",),
    ),
    "va_grounding": SourceRecord(
        source_id="va_grounding",
        organization="VA National Center for PTSD",
        title="Strategies: PTSD in Others — Grounding Technique",
        source_type="federal_clinical_education",
        year=2023,
        url="https://www.ptsd.va.gov/professional/treat/care/toolkits/police/managingStrategies.asp",
        scope="Grounding when a person appears to be responding to a flashback or losing orientation to the immediate setting.",
        evidentiary_role="conditional response strategy",
        limitations=("Technique is context-dependent and can be counterproductive for some people.",),
    ),
    "nimh_psychosis": SourceRecord(
        source_id="nimh_psychosis",
        organization="National Institute of Mental Health",
        title="Understanding Psychosis",
        source_type="federal_health_information",
        year=2026,
        url="https://www.nimh.nih.gov/health/publications/understanding-psychosis",
        scope="Warning signs such as suspiciousness, paranoid ideas, disorganized thinking, and changes in functioning.",
        evidentiary_role="symptom-pattern reference; not diagnosis",
        limitations=("Signs are non-specific and can arise in conditions other than psychosis.",),
    ),
    "apa_schizophrenia_2020": SourceRecord(
        source_id="apa_schizophrenia_2020",
        organization="American Psychiatric Association",
        title="Treatment of Patients With Schizophrenia (2020 Practice Guideline)",
        source_type="professional_practice_guideline",
        year=2020,
        url="https://www.psychiatry.org/psychiatrists/practice/clinical-practice-guidelines/schizophrenia",
        scope="Evidence-based clinical management and collaborative care for schizophrenia/psychosis.",
        evidentiary_role="response-principle reference; clinician-focused",
        limitations=("Clinical practice guideline; not an AI rulebook or diagnostic shortcut.",),
    ),
    "apa_cbt_psychosis": SourceRecord(
        source_id="apa_cbt_psychosis",
        organization="American Psychiatric Association",
        title="Practice Guideline for the Treatment of Patients With Schizophrenia, Second Edition — CBT section",
        source_type="professional_practice_guideline",
        year=2004,
        url="https://www.psychiatry.org/File%20Library/Psychiatrists/Practice/Clinical%20Practice%20Guidelines/schizophrenia.pdf",
        scope="Empathic/nonthreatening relationship, guided questioning, and proportionate examination of beliefs in CBT for psychosis.",
        evidentiary_role="conditional response strategy",
        limitations=("Older guideline edition; use as supporting context, not as sole authority for current treatment.",),
    ),
}


PATTERNS: Mapping[str, ClinicalPattern] = {
    "ptsd_like_trauma_response": ClinicalPattern(
        pattern_id="ptsd_like_trauma_response",
        label="trauma-related stress response pattern",
        category="trauma_related",
        diagnostic_status="non_diagnostic_working_model",
        signs=(
            "re-experiencing or intrusive memories/dreams/flashback-like episodes",
            "avoidance of trauma reminders",
            "marked startle or hyperarousal",
            "persistent threat vigilance or guardedness",
            "sleep disruption",
            "negative mood or detachment",
            "concentration difficulty",
            "distress linked to reminders, places, people, sounds, or smells",
        ),
        interpretation_rule=(
            "Multiple matching signs may support a trauma-related stress-response hypothesis. "
            "Do not convert the pattern into a PTSD diagnosis; diagnosis depends on duration, impairment, exposure history, "
            "and clinical assessment."
        ),
        response_principles=(
            "increase psychological and physical safety",
            "use predictable, transparent communication",
            "preserve choice, voice, and agency",
            "avoid unnecessary retraumatization or surprise",
            "reduce unnecessary stimulation when acute distress is evident",
            "consider simple grounding when the person appears to be responding to a flashback or losing orientation",
            "stop a technique that appears to increase frustration or distress",
        ),
        contraindications=(
            "do not claim or imply a PTSD diagnosis",
            "do not deliberately force trauma disclosure",
            "do not treat one symptom as diagnostic proof",
            "do not use grounding mechanically when it is clearly making the person worse",
        ),
        source_ids=("nimh_ptsd", "va_dod_ptsd_2023", "samhsa_trauma_informed", "va_ptsd_triggers", "va_grounding"),
    ),
    "paranoia_like_threat_response": ClinicalPattern(
        pattern_id="paranoia_like_threat_response",
        label="suspiciousness / threat-interpretation pattern",
        category="psychosis_related_pattern",
        diagnostic_status="non_diagnostic_working_model",
        signs=(
            "persistent suspiciousness toward other people",
            "paranoid ideas or strong threat interpretations",
            "difficulty distinguishing subjective interpretation from external evidence",
            "marked uneasiness around others",
            "social withdrawal associated with suspiciousness",
            "unusually intense or fixed threat-related ideas",
            "confused or disorganized communication accompanying threat beliefs",
            "functional decline occurring alongside these changes",
        ),
        interpretation_rule=(
            "A cluster may support a threat-interpretation hypothesis worth testing. "
            "Suspiciousness is non-specific and does not establish psychosis, schizophrenia, or any other diagnosis. "
            "The factual status of the person's concern must be examined independently of the psychological-pattern hypothesis."
        ),
        response_principles=(
            "maintain a calm, nonthreatening, collaborative posture",
            "acknowledge the person's fear or concern without automatically confirming the underlying belief as fact",
            "use transparent explanations and clear boundaries",
            "ask focused, non-leading questions about what the person believes is happening",
            "separate observable facts from interpretations",
            "use the least confrontational test that can distinguish plausible explanations",
            "preserve the person's agency and perspective while checking external evidence",
        ),
        contraindications=(
            "do not diagnose psychosis or schizophrenia from observed signs",
            "do not reinforce an unverified persecutory belief as established fact",
            "do not deliberately mock, shame, or aggressively confront the person",
            "do not let a psychological hypothesis substitute for checking real-world threats",
        ),
        source_ids=("nimh_psychosis", "apa_schizophrenia_2020", "apa_cbt_psychosis"),
    ),
}


def list_sources() -> List[Dict[str, object]]:
    return [record.to_dict() for record in SOURCES.values()]


def list_patterns() -> List[Dict[str, object]]:
    return [pattern.to_dict() for pattern in PATTERNS.values()]


def evaluate_pattern(pattern_id: str, observed_signs: Sequence[str]) -> PatternHypothesis:
    if pattern_id not in PATTERNS:
        raise KeyError(pattern_id)
    pattern = PATTERNS[pattern_id]
    observed = {str(sign).casefold().strip() for sign in observed_signs}
    matched = [sign for sign in pattern.signs if sign.casefold().strip() in observed]
    missing = [sign for sign in pattern.signs if sign.casefold().strip() not in observed]
    ratio = len(matched) / len(pattern.signs) if pattern.signs else 0.0
    return PatternHypothesis(
        pattern_id=pattern.pattern_id,
        label=pattern.label,
        matched_signs=tuple(matched),
        missing_signs=tuple(missing),
        match_ratio=round(ratio, 4),
        predicted_response_principles=pattern.response_principles,
        source_ids=pattern.source_ids,
    )

# ---------------------------------------------------------------------------
# Expanded scientific evidence registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    title: str
    evidence_type: str
    year: int
    source_ids: Sequence[str]
    claim: str
    role_in_peq: str
    limits: Sequence[str] = ()
    automation_status: str = "reference_only"

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class InterventionEvidence:
    intervention_id: str
    intervention: str
    target_patterns: Sequence[str]
    evidence_summary: str
    evidence_strength: str
    evidence_source_ids: Sequence[str]
    appropriate_for_peq: str
    requires_clinician: bool = True
    notes: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


# High-value population / survey / cohort resources. These are registries of
# scientific evidence sources, not raw participant-level data.
POPULATION_DATASETS: Mapping[str, SourceRecord] = {
    "cdc_brfss": SourceRecord(
        source_id="cdc_brfss",
        organization="Centers for Disease Control and Prevention",
        title="Behavioral Risk Factor Surveillance System (BRFSS)",
        source_type="national_population_survey",
        year=2026,
        url="https://www.cdc.gov/brfss/",
        scope="Large annual U.S. survey of health-related risk behaviors, chronic conditions, health-care access, and preventive services.",
        evidentiary_role="population prevalence / correlational baseline; U.S. health and behavior context",
        limitations=(
            "Telephone survey with self-report and survey nonresponse limitations.",
            "Not designed as a direct moment-to-moment emotion dataset.",
            "Question modules vary; causal conclusions require separate study designs.",
        ),
    ),
    "cdc_nhanes": SourceRecord(
        source_id="cdc_nhanes",
        organization="Centers for Disease Control and Prevention, National Center for Health Statistics",
        title="National Health and Nutrition Examination Survey (NHANES)",
        source_type="national_population_exam_survey",
        year=2026,
        url="https://www.cdc.gov/nchs/nhanes/about/index.html",
        scope="Nationally representative U.S. health survey combining interviews, physical examinations, laboratory and other objective measurements.",
        evidentiary_role="population health baseline and multimodal health correlates",
        limitations=(
            "Annual sample is much smaller than BRFSS but substantially richer per participant.",
            "Many psychological constructs are self-report or limited to selected modules.",
            "Cross-sectional analyses do not by themselves establish causality.",
        ),
    ),
    "uk_biobank": SourceRecord(
        source_id="uk_biobank",
        organization="UK Biobank",
        title="UK Biobank",
        source_type="large_longitudinal_cohort",
        year=2026,
        url="https://www.ukbiobank.ac.uk/about-our-data/",
        scope="Approximately 500,000 UK participants with questionnaire, lifestyle, psychosocial, physical, imaging, genetic and linked health-record data.",
        evidentiary_role="large-scale longitudinal associations and individual-difference research",
        limitations=(
            "Participants were 40–69 at recruitment, limiting generalization to younger populations.",
            "Healthy-volunteer / selection effects require explicit consideration.",
            "Observational associations are not automatically causal or individually predictive.",
        ),
    ),
    "nih_all_of_us": SourceRecord(
        source_id="nih_all_of_us",
        organization="National Institutes of Health, All of Us Research Program",
        title="All of Us Research Program",
        source_type="large_diverse_us_cohort",
        year=2024,
        url="https://www.allofus.nih.gov/",
        scope="Large U.S. cohort designed to include at least one million diverse participants and link health, lifestyle, environment and biological data for individualized research.",
        evidentiary_role="population diversity, individual differences, health-context associations",
        limitations=(
            "Research-access resource rather than a single uniform experiment.",
            "Participation, missingness and linkage patterns can create selection and measurement biases.",
            "Participant-level access is controlled; PEQ should use published findings or approved derived statistics, not scrape raw records.",
        ),
    ),
    "pew_american_trends_panel": SourceRecord(
        source_id="pew_american_trends_panel",
        organization="Pew Research Center",
        title="American Trends Panel",
        source_type="national_probability_panel",
        year=2025,
        url="https://www.pewresearch.org/methods/",
        scope="Nationally representative panel of randomly selected U.S. adults recruited using probability-based methods, with repeated surveys and weighting to population benchmarks.",
        evidentiary_role="U.S. self-reported attitudes, experiences, behaviors and social-context baselines",
        limitations=(
            "Self-report and question-wording effects remain important.",
            "Panel attrition and recruitment coverage require weighting and interpretation.",
            "Not a clinical diagnostic dataset.",
        ),
    ),
}


INSTRUMENT_EVIDENCE: Mapping[str, EvidenceItem] = {
    "phq9_validity": EvidenceItem(
        evidence_id="phq9_validity",
        title="The PHQ-9: validity of a brief depression severity measure",
        evidence_type="validated_measure",
        year=2001,
        source_ids=("phq9_pubmed",),
        claim="PHQ-9 is a validated brief self-report measure of depressive symptom severity and can support structured symptom measurement.",
        role_in_peq="Reference symptom structure and longitudinal change; not a stand-alone diagnosis engine.",
        limits=("Self-report measure; scores require clinical/contextual interpretation.", "Not a direct measure of momentary emotion."),
    ),
    "gad7_validation": EvidenceItem(
        evidence_id="gad7_validation",
        title="Validation and standardization of the Generalized Anxiety Disorder Screener (GAD-7) in the general population",
        evidence_type="validated_measure",
        year=2008,
        source_ids=("gad7_pubmed",),
        claim="GAD-7 has evidence for reliability and construct/factorial validity in a nationally representative general-population sample.",
        role_in_peq="Reference anxiety symptom structure and severity patterns; not a diagnosis or hidden-state truth meter.",
        limits=("Self-report; original general-population validation was conducted in Germany.", "Current-state inference still needs context and triangulation."),
    ),
    "pcl5_psychometrics": EvidenceItem(
        evidence_id="pcl5_psychometrics",
        title="The Posttraumatic Stress Disorder Checklist for DSM-5 (PCL-5): development and initial psychometric evaluation",
        evidence_type="validated_measure",
        year=2015,
        source_ids=("pcl5_pubmed",),
        claim="PCL-5 demonstrates strong internal consistency, test-retest reliability and convergent/discriminant validity as a PTSD symptom measure.",
        role_in_peq="Reference symptom clusters and self-report measurement; supports hypothesis construction, not autonomous diagnosis.",
        limits=("Initial psychometric studies included trauma-exposed samples; scoring thresholds and structure vary by context.",),
    ),
    "caps5_psychometrics": EvidenceItem(
        evidence_id="caps5_psychometrics",
        title="CAPS-5 development and subsequent reliability generalization",
        evidence_type="clinician_assessment",
        year=2024,
        source_ids=("caps5_development", "caps5_meta"),
        claim="CAPS-5 is a widely used clinician-administered structured PTSD assessment with strong interrater/test-retest reliability; meta-analytic reliability remains strong while some subscale and cross-language heterogeneity persists.",
        role_in_peq="Reference clinician-defined PTSD symptom constructs and what formal assessment entails; never emulate the clinical diagnosis process autonomously.",
        limits=("Requires trained clinician administration for its intended use.", "Reliability does not eliminate construct, cultural or diagnostic-interpretation limitations."),
    ),
    "panss_measurement": EvidenceItem(
        evidence_id="panss_measurement",
        title="COSMIN systematic review and meta-analysis of the Positive and Negative Syndrome Scale (PANSS)",
        evidence_type="psychometric_review",
        year=2025,
        source_ids=("panss_cosmin",),
        claim="PANSS has sufficient reliability, construct validity and responsiveness, but systematic review identified significant shortcomings in content and structural validity.",
        role_in_peq="Reference psychosis symptom dimensions and measurement limitations; useful as evidence about constructs, not as an autonomous scoring shortcut.",
        limits=("Designed for clinical assessment of psychotic disorders.", "Structural/content-validity limitations must remain attached to downstream inference."),
    ),
    "ders_evidence": EvidenceItem(
        evidence_id="ders_evidence",
        title="Meta-analysis of the Difficulties in Emotion Regulation Scale and short forms",
        evidence_type="psychometric_meta_analysis",
        year=2024,
        source_ids=("ders_meta",),
        claim="DERS measures multidimensional difficulties in emotion regulation; a 32-item six-factor solution received stronger support than competing forms in the cited meta-analytic study.",
        role_in_peq="Provides a structured vocabulary for emotion-regulation difficulties and individual differences.",
        limits=("Self-report construct; structure varies across populations and clinical groups.", "It measures regulation difficulties, not a specific current emotion."),
    ),
    "who5_evidence": EvidenceItem(
        evidence_id="who5_evidence",
        title="WHO-5 Well-Being Index systematic review",
        evidence_type="validated_measure",
        year=2015,
        source_ids=("who5_review", "who5_review_2025"),
        claim="WHO-5 has broad evidence of clinimetric validity and responsiveness as a subjective well-being measure, with wide cross-condition use.",
        role_in_peq="Reference positive well-being and longitudinal outcome measurement.",
        limits=("Self-report well-being measure rather than a specific emotional-state classifier.",),
    ),
    "ampd_review": EvidenceItem(
        evidence_id="ampd_review",
        title="Evidence base for the DSM-5 Alternative Model for Personality Disorders",
        evidence_type="clinical_personality_review",
        year=2025,
        source_ids=("ampd_2025", "ampd_2024", "ampd_2019", "apa_pid5"),
        claim="The dimensional AMPD has accumulated evidence for reliability, validity and clinical utility, while ongoing work identifies structural overlap and remaining model-clarity issues.",
        role_in_peq="Reference stable individual-difference dimensions and pathological trait constructs without collapsing a person into a diagnostic category.",
        limits=("Clinical personality model; not designed to infer momentary emotion.", "Construct overlap and discriminant-validity limitations remain relevant."),
    ),
    "therapeutic_alliance": EvidenceItem(
        evidence_id="therapeutic_alliance",
        title="The alliance in adult psychotherapy: a meta-analytic synthesis",
        evidence_type="treatment_process_meta_analysis",
        year=2018,
        source_ids=("alliance_meta_2018",),
        claim="Across 295 independent studies and more than 30,000 patients, therapeutic alliance is reliably associated with psychotherapy outcome, independent of theoretical orientation.",
        role_in_peq="Strong evidence that collaboration, agreement, responsiveness and working relationship are consequential response variables.",
        limits=("Association does not establish that alliance alone causes outcome.", "Clinical psychotherapy findings should not be overgeneralized to casual AI companionship."),
    ),
    "emotion_regulation_strategies": EvidenceItem(
        evidence_id="emotion_regulation_strategies",
        title="Emotion-regulation strategies across psychopathology: meta-analytic review",
        evidence_type="emotion_regulation_meta_analysis",
        year=2010,
        source_ids=("emotion_reg_meta_2010", "emotion_reg_structure_2017", "big5_emotion_regulation_review"),
        claim="Emotion-regulation strategies such as acceptance, problem solving, reappraisal, rumination, avoidance and suppression show systematic relationships with psychopathology; strategy effects are not interchangeable.",
        role_in_peq="Reference response-strategy hypotheses and individual differences in regulation style; supports testing strategies rather than assuming a universal best response.",
        limits=("Much evidence is correlational and transdiagnostic.", "Strategy effectiveness depends on context and individual differences."),
    ),
}


EVIDENCE_SOURCES: Mapping[str, SourceRecord] = {
    "apa_dsm5tr": SourceRecord("apa_dsm5tr", "American Psychiatric Association", "DSM-5-TR", "professional_diagnostic_manual", 2022, "https://www.psychiatry.org/psychiatrists/practice/dsm/about-dsm", "Clinical classification, diagnostic criteria, prevalence, course, risk/prognostic factors, culture and differential diagnosis.", "clinical construct reference; not autonomous diagnosis", ("Intended for trained professionals using clinical judgment; PEQ must not diagnose from criteria alone.",)),
    "apa_pid5": SourceRecord("apa_pid5", "American Psychiatric Association", "Personality Inventory for DSM-5 (PID-5)", "professional_personality_measure", 2022, "https://www.psychiatry.org/psychiatrists/practice/dsm/educational-resources/dsm-5-assessment-measures", "Dimensional maladaptive personality-trait measurement across five broad domains and 25 facets.", "individual-difference and trait-structure reference", ("Clinical personality measure; not a momentary emotion detector.",)),
    "big5_emotion_regulation_review": SourceRecord("big5_emotion_regulation_review", "PubMed / Emotion", "Personality traits and emotion regulation: a targeted review", "peer_reviewed_targeted_review", 2020, "https://pubmed.ncbi.nlm.nih.gov/31961180/", "Relations between Big Five traits and stages/styles of emotion regulation.", "individual-difference response modifier", ("Review synthesizes associations; does not imply deterministic trait-to-response rules.",)),
    "who_mhgap_v2": SourceRecord("who_mhgap_v2", "World Health Organization", "mhGAP Intervention Guide Version 2.0", "international_clinical_guideline", 2016, "https://www.who.int/publications/i/item/9789241549790", "Evidence-based decision algorithms for priority mental, neurological and substance-use conditions in non-specialist health settings.", "clinical response/management reference", ("Designed for health-care providers and adapted local implementation; not an AI autonomous-treatment protocol.",)),
    "phq9_pubmed": SourceRecord("phq9_pubmed", "PubMed / J Gen Intern Med", "The PHQ-9: validity of a brief depression severity measure", "peer_reviewed_measure", 2001, "https://pubmed.ncbi.nlm.nih.gov/11556941/", "Depressive symptom measurement.", "validated symptom measure", ("Self-report; not a hidden-state detector.",)),
    "gad7_pubmed": SourceRecord("gad7_pubmed", "PubMed / Medical Care", "Validation and standardization of the GAD-7 in the general population", "peer_reviewed_measure", 2008, "https://pubmed.ncbi.nlm.nih.gov/18388841/", "General-population anxiety symptom measurement.", "validated symptom measure", ("German nationally representative sample; self-report.",)),
    "pcl5_pubmed": SourceRecord("pcl5_pubmed", "PubMed / International Society for Traumatic Stress Studies", "The Posttraumatic Stress Disorder Checklist for DSM-5: Development and Initial Psychometric Evaluation", "peer_reviewed_measure", 2015, "https://pubmed.ncbi.nlm.nih.gov/26606250/", "PTSD symptom measurement.", "validated symptom measure", ("Initial studies used trauma-exposed samples.",)),
    "caps5_development": SourceRecord("caps5_development", "PubMed", "CAPS-5 development and initial psychometric evaluation in military veterans", "peer_reviewed_clinician_assessment", 2017, "https://pubmed.ncbi.nlm.nih.gov/28493729/", "Clinician-administered PTSD assessment.", "clinical assessment reference", ("Requires trained administration.",)),
    "caps5_meta": SourceRecord("caps5_meta", "PubMed / Frontiers in Psychology", "Reliability generalization of CAPS-5: meta-analysis", "peer_reviewed_meta_analysis", 2024, "https://pubmed.ncbi.nlm.nih.gov/39184938/", "Cross-study reliability of CAPS-5.", "measurement-quality evidence", ("Residual heterogeneity; divergent validity and cultural adaptation remain areas for research.",)),
    "panss_cosmin": SourceRecord("panss_cosmin", "PubMed / eClinicalMedicine", "COSMIN systematic review and meta-analysis of PANSS", "peer_reviewed_meta_analysis", 2025, "https://pubmed.ncbi.nlm.nih.gov/40255437/", "Psychosis symptom measurement.", "measurement-quality evidence", ("Content and structural validity shortcomings identified.",)),
    "ders_meta": SourceRecord("ders_meta", "PubMed / Journal of Clinical Psychology", "Meta-analysis of DERS and short forms", "peer_reviewed_meta_analysis", 2024, "https://pubmed.ncbi.nlm.nih.gov/38630901/", "Emotion regulation difficulty measurement.", "individual-difference evidence", ("Self-report and factor-structure dependence.",)),
    "who5_review": SourceRecord("who5_review", "PubMed / Psychotherapy and Psychosomatics", "The WHO-5 Well-Being Index: systematic review", "peer_reviewed_systematic_review", 2015, "https://pubmed.ncbi.nlm.nih.gov/25831962/", "Subjective well-being measurement.", "outcome and well-being evidence", ("Not specific to a single clinical state.",)),
    "who5_review_2025": SourceRecord("who5_review_2025", "PubMed / Advances in Therapy", "Systematic Review of the Use of the WHO-5 Well-Being Index Across Different Disease Areas", "peer_reviewed_systematic_review", 2025, "https://pubmed.ncbi.nlm.nih.gov/40506676/", "Broad use and outcome sensitivity of WHO-5.", "outcome-measure evidence", ("Cross-disease heterogeneity.",)),
    "ampd_2025": SourceRecord("ampd_2025", "PubMed / World Psychiatry", "Validity, reliability and clinical utility of the Alternative DSM-5 Model for Personality Disorders", "peer_reviewed_systematic_review", 2025, "https://pubmed.ncbi.nlm.nih.gov/40948060/", "Dimensional personality-pathology evidence.", "individual-difference evidence", ("Clinical model; not momentary emotion.",)),
    "ampd_2024": SourceRecord("ampd_2024", "PubMed / Annual Review of Clinical Psychology", "The Alternative Model of Personality Disorders: Assessment, Convergent and Discriminant Validity", "peer_reviewed_review", 2024, "https://pubmed.ncbi.nlm.nih.gov/38211624/", "Dimensional personality pathology and validity.", "individual-difference evidence", ("Structural overlap and model evolution remain under study.",)),
    "ampd_2019": SourceRecord("ampd_2019", "PubMed / Current Psychiatry Reports", "A Brief but Comprehensive Review of Research on the Alternative DSM-5 Model for Personality Disorders", "peer_reviewed_review", 2019, "https://pubmed.ncbi.nlm.nih.gov/31410586/", "Reliability, validity and convergence of AMPD constructs.", "individual-difference evidence", ("Some criterion overlap and discriminant-validity issues.",)),
    "alliance_meta_2018": SourceRecord("alliance_meta_2018", "PubMed / Psychotherapy", "The alliance in adult psychotherapy: a meta-analytic synthesis", "peer_reviewed_meta_analysis", 2018, "https://pubmed.ncbi.nlm.nih.gov/29792475/", "Relationship/process variable and treatment outcome.", "response-strategy evidence", ("Outcome association is not proof of simple causality.",)),
    "emotion_reg_meta_2010": SourceRecord("emotion_reg_meta_2010", "PubMed / Clinical Psychology Review", "Emotion-regulation strategies across psychopathology: A meta-analytic review", "peer_reviewed_meta_analysis", 2010, "https://pubmed.ncbi.nlm.nih.gov/20015584/", "Emotion regulation strategies and psychopathology.", "response-strategy evidence", ("Primarily dispositional/correlational evidence.",)),
    "emotion_reg_structure_2017": SourceRecord("emotion_reg_structure_2017", "PubMed / Psychological Bulletin", "The structure of common emotion regulation strategies: a meta-analytic examination", "peer_reviewed_meta_analysis", 2017, "https://pubmed.ncbi.nlm.nih.gov/28301202/", "Structure and relationships among common emotion-regulation strategies.", "response-strategy evidence", ("Strategy taxonomy is not a universal prescription.",)),
    "depression_nma": SourceRecord("depression_nma", "PubMed / Journal of Consulting and Clinical Psychology", "Cognitive restructuring, behavioral activation and CBT in adult depression: network meta-analysis", "peer_reviewed_network_meta_analysis", 2021, "https://pubmed.ncbi.nlm.nih.gov/34264703/", "Comparative evidence for depression psychotherapies.", "therapy-evidence reference", ("Clinical trials; not a companion protocol.",)),
    "depression_psychotherapy_nma": SourceRecord("depression_psychotherapy_nma", "PubMed / World Psychiatry", "Psychotherapies for depression: network meta-analysis", "peer_reviewed_network_meta_analysis", 2021, "https://pubmed.ncbi.nlm.nih.gov/34002502/", "Comparative efficacy, acceptability and long-term outcomes across major psychotherapies.", "therapy-evidence reference", ("Treatment effects depend on population, comparator and delivery.",)),
    "gad_nma": SourceRecord("gad_nma", "PubMed / JAMA Psychiatry", "Psychotherapies for generalized anxiety disorder in adults: systematic review and network meta-analysis", "peer_reviewed_network_meta_analysis", 2023, "https://pubmed.ncbi.nlm.nih.gov/37851421/", "Comparative psychotherapies for GAD.", "therapy-evidence reference", ("Clinical treatment evidence; patient populations differ from general conversation users.",)),
    "gad_2025_nma": SourceRecord("gad_2025_nma", "PubMed / Translational Psychiatry", "CBT treatment delivery formats for GAD: systematic review and network meta-analysis", "peer_reviewed_network_meta_analysis", 2025, "https://pubmed.ncbi.nlm.nih.gov/40506439/", "Comparative CBT delivery formats for GAD.", "therapy-delivery reference", ("Evidence quality varied; remote CBT was not uniformly superior.",)),
    "panic_umbrella": SourceRecord("panic_umbrella", "PubMed / Journal of Anxiety Disorders", "Psychosocial treatment for panic disorder: umbrella review", "peer_reviewed_umbrella_review", 2022, "https://pubmed.ncbi.nlm.nih.gov/35063924/", "Systematic reviews and meta-analyses of psychosocial treatment for panic disorder.", "therapy-evidence reference", ("Most included reviews were critically low quality under AMSTAR-2.",)),
    "ptsd_psychotherapy_meta": SourceRecord("ptsd_psychotherapy_meta", "PubMed / Clinical Psychology Review", "Psychological treatments for adults with PTSD: systematic review and meta-analysis", "peer_reviewed_meta_analysis", 2015, "https://pubmed.ncbi.nlm.nih.gov/26574151/", "Comparative evidence for PTSD psychological treatments.", "therapy-evidence reference", ("Comparative head-to-head evidence and adverse-event reporting were limited.",)),
    "ptsd_medication_vs_therapy": SourceRecord("ptsd_medication_vs_therapy", "PubMed / Psychiatry Research", "Medication versus trauma-focused psychotherapy for adults with PTSD", "peer_reviewed_meta_analysis", 2019, "https://pubmed.ncbi.nlm.nih.gov/31690461/", "Head-to-head psychotherapy versus SSRI/SNRI evidence.", "therapy-comparison reference", ("Only four head-to-head trials met inclusion; confidence intervals were wide.",)),
    "psychosis_prevention": SourceRecord("psychosis_prevention", "PubMed / Molecular Psychiatry", "Preventing psychosis in people at clinical high risk: updated meta-analysis", "peer_reviewed_meta_analysis", 2025, "https://pubmed.ncbi.nlm.nih.gov/39953286/", "Preventive interventions in clinical-high-risk populations.", "evidence-of-uncertainty reference", ("No sustained robust effect across investigated interventions; heterogeneous clinical-high-risk studies.",)),
    "panss6_cosmin": SourceRecord("panss6_cosmin", "PubMed / European Neuropsychopharmacology", "COSMIN systematic review and meta-analysis of PANSS-6", "peer_reviewed_meta_analysis", 2025, "https://pubmed.ncbi.nlm.nih.gov/40056666/", "Shortened PANSS measurement properties.", "measurement-quality evidence", ("Abbreviated scale; intended for psychotic-disorder assessment contexts.",)),
}


# High-level clinical framework evidence. These entries are intentionally
# descriptive: PEQ can consult the literature-backed construct, but never
# infer a diagnosis or administer clinical treatment autonomously.
INSTRUMENT_EVIDENCE = dict(INSTRUMENT_EVIDENCE)
INSTRUMENT_EVIDENCE.update({
    "dsm5tr_framework": EvidenceItem(
        "dsm5tr_framework", "DSM-5-TR clinical framework", "clinical_manual", 2022, ("apa_dsm5tr",),
        "DSM-5-TR defines recognized mental disorders and describes criteria, associated features, prevalence, course, risk/prognostic factors, cultural issues, functional consequences and differential diagnosis.",
        "Reference for formal clinical constructs and differential considerations; never a substitute for clinical assessment.",
        ("APA states diagnostic criteria are intended for trained professionals using clinical judgment.",),
    ),
    "pid5_trait_model": EvidenceItem(
        "pid5_trait_model", "PID-5 dimensional personality-trait model", "professional_personality_measure", 2022, ("apa_pid5", "ampd_2025", "ampd_2024"),
        "PID-5 provides dimensional assessment of maladaptive personality traits across five broad domains and 25 facets and has a substantial psychometric literature.",
        "Reference for stable individual-difference modifiers and person-specific hypotheses; not a diagnosis from observed behavior.",
        ("Structural overlap among facets/domains and ongoing model refinement require conservative interpretation.",),
    ),
    "who_mhgap": EvidenceItem(
        "who_mhgap", "WHO mhGAP Intervention Guide Version 2.0", "international_clinical_guideline", 2016, ("who_mhgap_v2",),
        "WHO's mhGAP-IG integrates evidence-based management algorithms for priority mental, neurological and substance-use conditions and explicitly includes follow-up and implementation considerations.",
        "High-level source for clinically recognized response/management principles and escalation boundaries.",
        ("Targeted to health-care providers; not a conversational-agent treatment manual.",),
    ),
})


INTERVENTION_EVIDENCE: Mapping[str, InterventionEvidence] = {
    "ptsd_trauma_focused_cbt": InterventionEvidence(
        "ptsd_trauma_focused_cbt", "Trauma-focused CBT (including CPT, cognitive therapy, prolonged exposure, narrative exposure)",
        ("ptsd_like_trauma_response",),
        "Systematic reviews and NICE guidance support trauma-focused CBT approaches for clinically important PTSD symptoms and PTSD, with multiple validated protocols.",
        "high_or_guideline_supported", ("ptsd_psychotherapy_meta",),
        "Use only as clinical-evidence context or to guide low-risk supportive principles; do not have PEQ deliver trauma processing as therapy.", True,
        "Clinical treatment requires trained practitioners, individualized assessment, monitoring and safety planning.",
    ),
    "ptsd_emdr": InterventionEvidence(
        "ptsd_emdr", "Eye Movement Desensitization and Reprocessing (EMDR)",
        ("ptsd_like_trauma_response",),
        "EMDR is supported by clinical guidelines and psychological-treatment evidence for PTSD, with manualized, supervised delivery and specific treatment phases.",
        "guideline_supported", ("ptsd_psychotherapy_meta",),
        "PEQ may recognize EMDR as an evidence-backed clinical option when a person is already discussing professional care; it should not conduct EMDR.", True,
        "Not a conversational improvisation technique; formal delivery is structured and clinician-led.",
    ),
    "psychosis_cbt_family": InterventionEvidence(
        "psychosis_cbt_family", "CBT and family intervention for psychosis/schizophrenia",
        ("paranoia_like_threat_response",),
        "NICE recommends CBT and family intervention for psychosis/schizophrenia and emphasizes collaborative, structured, recovery-oriented care; APA guidance supports evidence-based psychosocial treatment.",
        "guideline_supported", ("apa_schizophrenia_2020",),
        "PEQ may borrow interaction principles such as nonthreatening collaboration, guided questions and negotiated problem solving; it must not reproduce clinician therapy.", True,
        "Formal treatment requires trained clinicians. External threat assessment remains separate from psychological formulation.",
    ),
    "depression_cb_approaches": InterventionEvidence(
        "depression_cb_approaches", "CBT, cognitive restructuring and behavioral activation",
        ("depressive_like_pattern",),
        "Network meta-analysis finds CBT, cognitive restructuring and behavioral activation effective relative to usual care/waiting-list controls, without clear evidence that one of the three is universally superior.",
        "moderate_to_strong", ("depression_nma", "depression_psychotherapy_nma"),
        "PEQ can use evidence about structured behavioral and cognitive response strategies as hypothesis candidates, not as autonomous therapy.", True,
        "Treatment selection depends on severity, risk, comorbidity, preference, access and clinician assessment.",
    ),
    "gad_cbt": InterventionEvidence(
        "gad_cbt", "CBT and related structured psychological approaches for GAD",
        ("anxiety_like_pattern",),
        "Systematic reviews and network meta-analyses support CBT and several related approaches for reducing GAD symptoms, while effects vary by protocol and delivery format.",
        "moderate", ("gad_nma", "gad_2025_nma"),
        "PEQ can test low-risk conversational behaviors such as reducing ambiguity, structured problem orientation and supporting agency; it should not conduct formal therapy.", True,
        "Remote and group formats do not necessarily perform identically to individual CBT; intervention evidence is clinical.",
    ),
    "panic_cbt": InterventionEvidence(
        "panic_cbt", "CBT-oriented treatment for panic disorder",
        ("panic_like_pattern",),
        "Umbrella review evidence generally supports CBT for panic symptoms compared with control conditions, but the quality of many underlying reviews was rated critically low.",
        "moderate_with_quality_caveat", ("panic_umbrella",),
        "Use as a hypothesis source for structured, non-threatening responses; do not simulate panic-disorder treatment protocols.", True,
        "Evidence quality is heterogeneous and cultural/age generalizability is incomplete.",
    ),
    "emotion_regulation": InterventionEvidence(
        "emotion_regulation", "Emotion-regulation strategy selection: acceptance, reappraisal, problem solving, suppression, avoidance, rumination",
        ("emotion_dysregulation_pattern",),
        "Meta-analytic evidence shows systematic relationships among emotion-regulation strategies and psychopathology; effectiveness is context- and person-dependent rather than universally one-directional.",
        "transdiagnostic_evidence", ("emotion_reg_meta_2010", "emotion_reg_structure_2017"),
        "Strong candidate layer for PEQ Response experimentation: select a low-risk strategy, observe the individual response, and update the person-specific interaction model.", False,
        "This is the most directly adaptable material for conversational response hypotheses, but it still does not imply that one strategy is optimal for every person or situation.",
    ),
    "alliance_collaboration": InterventionEvidence(
        "alliance_collaboration", "Collaborative working relationship / therapeutic alliance principles",
        ("all_patterns",),
        "A large meta-analysis across 295 independent psychotherapy studies and more than 30,000 patients found a robust association between alliance and treatment outcome.",
        "strong_process_evidence", ("alliance_meta_2018",),
        "PEQ should treat collaboration, responsiveness, agreement on goals and transparent partnership as high-value response variables rather than diagnostic symptoms.", False,
        "Association with therapy outcome does not mean every conversational problem is solved by maximizing alliance.",
    ),
}

# Add a small set of normalized working-pattern vocabularies. These are not
# diagnostic criteria; they are hypothesis families to which evidence may attach.
PATTERNS = dict(PATTERNS)
PATTERNS.update({
    "depressive_like_pattern": ClinicalPattern(
        pattern_id="depressive_like_pattern",
        label="depressive symptom-pattern hypothesis",
        category="mood_related_pattern",
        diagnostic_status="non_diagnostic_working_model",
        signs=("reduced pleasure or interest", "low mood or hopelessness", "fatigue or low energy", "sleep change", "concentration difficulty", "negative self-appraisal", "withdrawal or reduced activity"),
        interpretation_rule="A cluster may support a depressive-like interaction hypothesis, but duration, impairment, differential diagnosis and safety assessment remain outside PEQ's authority.",
        response_principles=("reduce unnecessary cognitive load", "use collaborative and achievable next steps", "avoid moralizing reduced capacity", "support agency and engagement", "monitor response over time"),
        contraindications=("do not diagnose depression", "do not infer suicidality from low mood alone", "do not pressure the person into activity without assessing capacity and preference"),
        source_ids=("depression_nma", "depression_psychotherapy_nma", "who5_review"),
    ),
    "anxiety_like_pattern": ClinicalPattern(
        pattern_id="anxiety_like_pattern",
        label="anxiety symptom-pattern hypothesis",
        category="anxiety_related_pattern",
        diagnostic_status="non_diagnostic_working_model",
        signs=("persistent worry", "restlessness or tension", "heightened threat anticipation", "difficulty concentrating", "sleep disturbance", "avoidance or reassurance seeking", "physiological arousal"),
        interpretation_rule="A cluster may support an anxiety-related hypothesis, but it does not establish GAD, panic disorder, or another diagnosis.",
        response_principles=("reduce ambiguity when feasible", "use clear predictable communication", "offer choices", "avoid unnecessary escalation", "test structured problem-solving or calming strategies only when appropriate"),
        contraindications=("do not diagnose anxiety disorders", "do not reinforce an inaccurate catastrophic interpretation as fact", "do not force exposure-like exercises"),
        source_ids=("gad7_pubmed", "gad_nma", "gad_2025_nma", "panic_umbrella"),
    ),
    "panic_like_pattern": ClinicalPattern(
        pattern_id="panic_like_pattern",
        label="acute panic-like arousal hypothesis",
        category="anxiety_related_pattern",
        diagnostic_status="non_diagnostic_working_model",
        signs=("sudden intense fear", "rapid physiological arousal", "shortness of breath or chest sensations", "fear of losing control", "urgent escape behavior", "rapid escalation then partial recovery"),
        interpretation_rule="A panic-like pattern is a descriptive working model only; medical and environmental causes of acute physiological symptoms must remain possible.",
        response_principles=("use calm concise communication", "reduce sensory and cognitive load", "preserve a sense of control", "orient to immediate observable surroundings when grounding is welcome", "monitor for need for urgent medical or emergency support"),
        contraindications=("do not diagnose panic disorder", "do not assume physiological symptoms are psychological", "do not force breathing techniques when they worsen symptoms"),
        source_ids=("panic_umbrella", "gad_nma"),
    ),
    "emotion_dysregulation_pattern": ClinicalPattern(
        pattern_id="emotion_dysregulation_pattern",
        label="emotion-regulation difficulty hypothesis",
        category="emotion_regulation_pattern",
        diagnostic_status="non_diagnostic_working_model",
        signs=("difficulty identifying emotional state", "difficulty staying goal-directed while distressed", "difficulty accepting emotion", "impulsive action under high arousal", "prolonged rumination", "avoidance or suppression", "difficulty shifting strategies"),
        interpretation_rule="The pattern describes regulation difficulty and strategy mismatch; it is not a personality or psychiatric diagnosis.",
        response_principles=("test one response strategy at a time when possible", "preserve agency", "separate state from strategy effectiveness", "measure the person's actual response", "learn person-specific regulation preferences"),
        contraindications=("do not label a person with a disorder from regulation difficulty alone", "do not assume suppression or reappraisal is universally bad or universally good"),
        source_ids=("ders_meta", "emotion_reg_meta_2010", "emotion_reg_structure_2017"),
    ),
})

# Re-expose the expanded registry without changing the existing public calls.
def list_population_datasets() -> List[Dict[str, object]]:
    return [record.to_dict() for record in POPULATION_DATASETS.values()]


def list_evidence_items() -> List[Dict[str, object]]:
    return [item.to_dict() for item in INSTRUMENT_EVIDENCE.values()]


def list_intervention_evidence() -> List[Dict[str, object]]:
    return [item.to_dict() for item in INTERVENTION_EVIDENCE.values()]


def all_scientific_sources() -> List[Dict[str, object]]:
    combined: Dict[str, Dict[str, object]] = {k: v.to_dict() for k, v in SOURCES.items()}
    combined.update({k: v.to_dict() for k, v in EVIDENCE_SOURCES.items()})
    combined.update({k: v.to_dict() for k, v in POPULATION_DATASETS.items()})
    return list(combined.values())
