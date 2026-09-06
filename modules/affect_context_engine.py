"""
affect_context_engine.py — Reference implementation of the affect/context model.

Produces the alex_bridge payload consumed by jeremy_whisper.

Design invariants (see AFFECT_CONTEXT_MODEL.md):
  1. Context is integrated (position). Affect is differentiated (derivative).
  2. Affect is measured ONLY as personal z-score. No absolute thresholds anywhere.
  3. confidence = min(maturity, agreement). Both required.
  4. Silence is a valid output. Below the floor we emit nothing.
  5. Escalation needs sustained evidence. De-escalation needs one contrary turn.

Stdlib only. Drops into pubcast/modules/ with no new requirements.

Rear View Foresight LLC - Feic Mo Chroi
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Any, Deque, Dict, List, Optional, Tuple

SCHEMA_VERSION = 1

# ── Tuning constants ─────────────────────────────────────────────────────────
BASELINE_ALPHA        = 0.05   # EW decay; ~20 turns to adapt
MATURITY_FULL_AT      = 12     # turns before maturity reaches 1.0
CONFIDENCE_FLOOR      = 0.35   # below this: observing, emit nothing
ESCALATE_CONFIDENCE   = 0.60   # required to enter a care state
ESCALATE_SUSTAIN      = 3      # turns of concurring evidence to escalate
CONTINUITY_WINDOW     = 6      # turns compared for topic continuity
VOLATILITY_WINDOW     = 5      # turns of z-vectors for volatility
WHISPER_SUPPRESS_N    = 8      # don't repeat a whisper within N turns
CONFIDENCE_DECAY      = 0.88   # per-turn decay when no fresh evidence
Z_CLAMP               = 4.0    # hard clamp on any z-score; anti-domination
SWITCH_MARGIN         = 0.25   # new state must beat incumbent by this to displace it
MIN_MATURITY_FOR_CARE = 0.65   # you must KNOW someone before calling them struggling
ANTECEDENT_WINDOW     = 7      # turns of retrospective looked at on a state switch
PROBE_BUDGET_START    = 3.0    # wrong guesses tolerated before patience is gone
PROBE_REFUND          = 0.6    # partial refund when a probe actually resolved something
IRRITATION_SURCHARGE  = 1.0    # extra cost when a probe visibly annoyed them

_EPS = 1e-6

# ── Lexical markers (structural, not sentiment) ──────────────────────────────
_HEDGES = {
    "maybe", "perhaps", "possibly", "probably", "might", "guess", "sort",
    "kinda", "kind", "somewhat", "think", "suppose", "unsure", "dunno",
}
_SELF_CORRECT = {"actually", "wait", "nevermind", "scratch", "ignore", "meant"}
_NEGATIONS = {"not", "no", "never", "cant", "wont", "dont", "isnt", "nothing", "none"}
_IRREVERSIBLE = {
    "delete", "drop", "deploy", "publish", "overwrite", "migrate", "rm",
    "production", "prod", "live", "irreversible", "permanent", "final",
}
_HELP_SEEKING = {"help", "stuck", "broken", "failing", "wrong", "why", "how"}
_POSITIVE_LEX = {"great", "perfect", "love", "nice", "awesome", "brilliant", "thanks"}
_CONTRAST = {"but", "though", "however", "although", "except", "yet"}

# Finality / dismissal / callousness. These are not sentiment words — they are
# TERMINATION markers. They announce the end of investment in a subject.
_FINALITY = {
    "done", "over", "enough", "finished", "forget", "whatever", "fine",
    "screw", "abandon", "scrap", "quit", "stop", "dead", "moot",
}
_DISMISSIVE = {
    "doesnt", "dont", "care", "matter", "matters", "pointless", "useless",
    "worthless", "irrelevant", "nobody", "whocares", "meh",
}
_ABSOLUTES = {"never", "always", "all", "everything", "nothing", "any", "entire", "whole"}

# Temporal pressure — deadline proximity, scope compression
_TEMPORAL = {
    "deadline", "tomorrow", "tonight", "morning", "hours", "minutes", "late",
    "soon", "quickly", "hurry", "rush", "behind", "overdue", "asap", "today",
}
# Self-directed negative attribution. Distinct from frustration AT a problem —
# this is frustration AT ONESELF, and it is the one that matters most for care.
_SELF_BLAME = {
    "i", "im", "my", "myself", "me",
}
_FAILURE = {
    "cant", "couldnt", "failed", "failing", "stupid", "idiot", "useless",
    "wrong", "shouldve", "should", "fault", "bad", "terrible", "hopeless",
}

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "that", "this",
    "for", "on", "with", "as", "at", "be", "are", "was", "were", "i", "you",
    "we", "they", "he", "she", "my", "your", "our", "so", "if", "do", "does",
    "did", "have", "has", "had", "can", "will", "would", "there", "here",
}

_WORD_RE = re.compile(r"[a-z0-9']+")
_SENT_RE = re.compile(r"[.!?]+")


# ── Feature extraction ───────────────────────────────────────────────────────

@dataclass
class TurnFeatures:
    """Split into paraphrase-invariant (context) and paraphrase-variant (affect)."""
    # Paraphrase-VARIANT — affect channel
    msg_length:      float = 0.0
    punct_density:   float = 0.0
    caps_ratio:      float = 0.0
    hedge_density:   float = 0.0
    negation_density: float = 0.0
    self_correct:    float = 0.0
    fragmentation:   float = 0.0
    repetition:      float = 0.0
    latency:         float = 0.0
    profanity:       float = 0.0
    # Paraphrase-INVARIANT — context channel
    content_tokens:  Tuple[str, ...] = ()
    is_question:     float = 0.0
    is_imperative:   float = 0.0
    irreversibility: float = 0.0
    help_seeking:    float = 0.0
    positive_lex:    float = 0.0
    contrast_marker: float = 0.0
    finality:        float = 0.0
    dismissive:      float = 0.0
    absolutes:       float = 0.0
    temporal:        float = 0.0
    self_blame:      float = 0.0

    def affect_vector(self) -> Dict[str, float]:
        """Only the paraphrase-variant features get z-scored."""
        return {
            "msg_length":       self.msg_length,
            "punct_density":    self.punct_density,
            "caps_ratio":       self.caps_ratio,
            "hedge_density":    self.hedge_density,
            "negation_density": self.negation_density,
            "self_correct":     self.self_correct,
            "fragmentation":    self.fragmentation,
            "repetition":       self.repetition,
            "latency":          self.latency,
            "profanity":        self.profanity,
        }


_PROFANITY_RE = re.compile(
    r"\b(f+u+c+k+|s+h+i+t+|damn|hell|crap|ass|bitch)\w*\b", re.I
)


def extract_features(
    text: str,
    prev_text: str = "",
    latency_s: Optional[float] = None,
) -> TurnFeatures:
    """Pull both channels out of a raw turn. No sentiment model involved."""
    raw = text or ""
    stripped = raw.strip()
    if not stripped:
        return TurnFeatures()

    lower = stripped.lower()
    words = _WORD_RE.findall(lower)
    n_words = max(len(words), 1)

    # ── affect channel: form, not content ──
    n_chars   = len(stripped)
    puncts    = sum(stripped.count(c) for c in "!?")
    ellipsis  = stripped.count("...")
    letters   = [c for c in stripped if c.isalpha()]
    caps      = sum(1 for c in letters if c.isupper())
    sentences = [s for s in _SENT_RE.split(stripped) if s.strip()]
    n_sent    = max(len(sentences), 1)

    hedges     = sum(1 for w in words if w in _HEDGES)
    negations  = sum(1 for w in words if w in _NEGATIONS)
    corrects   = sum(1 for w in words if w in _SELF_CORRECT)
    profanity  = len(_PROFANITY_RE.findall(stripped))

    # repetition = token overlap with previous turn (circling detector)
    prev_words = set(_WORD_RE.findall((prev_text or "").lower())) - _STOPWORDS
    cur_words  = set(words) - _STOPWORDS
    if prev_words and cur_words:
        repetition = len(cur_words & prev_words) / max(len(cur_words | prev_words), 1)
    else:
        repetition = 0.0

    # ── context channel: content, survives paraphrase ──
    content = tuple(w for w in words if w not in _STOPWORDS and len(w) > 2)
    is_q    = 1.0 if stripped.endswith("?") or (words and words[0] in
              {"what", "why", "how", "when", "where", "who", "can", "could",
               "should", "is", "are", "do", "does"}) else 0.0
    is_imp  = 1.0 if words and words[0] in {
        "make", "build", "fix", "run", "check", "add", "remove", "write",
        "show", "give", "do", "start", "stop", "please", "wire", "test",
    } else 0.0

    return TurnFeatures(
        msg_length       = float(n_chars),
        punct_density    = (puncts + ellipsis) / n_words,
        caps_ratio       = caps / max(len(letters), 1),
        hedge_density    = hedges / n_words,
        negation_density = negations / n_words,
        self_correct     = corrects / n_words,
        fragmentation    = n_sent / n_words,
        repetition       = repetition,
        # latency is heavy-tailed; log-compress before z-scoring or it dominates
        latency          = math.log1p(max(0.0, float(latency_s))) if latency_s is not None else 0.0,
        profanity        = profanity / n_words,
        content_tokens   = content,
        is_question      = is_q,
        is_imperative    = is_imp,
        irreversibility  = sum(1 for w in words if w in _IRREVERSIBLE) / n_words,
        help_seeking     = sum(1 for w in words if w in _HELP_SEEKING) / n_words,
        positive_lex     = sum(1 for w in words if w in _POSITIVE_LEX) / n_words,
        contrast_marker  = sum(1 for w in words if w in _CONTRAST) / n_words,
        finality         = sum(1 for w in words if w in _FINALITY) / n_words,
        dismissive       = sum(1 for w in words if w in _DISMISSIVE) / n_words,
        absolutes        = sum(1 for w in words if w in _ABSOLUTES) / n_words,
        temporal         = sum(1 for w in words if w in _TEMPORAL) / n_words,
        # self-blame requires BOTH a first-person marker and a failure marker in
        # the same turn — "I can't" is self-directed, "it can't" is not.
        self_blame       = (
            (1.0 if any(w in _SELF_BLAME for w in words) else 0.0)
            * sum(1 for w in words if w in _FAILURE) / n_words
        ),
    )


# ── Personal baseline: exponentially-weighted moments, per person per feature ─

class PersonalBaseline:
    """
    The non-uniformity mechanism. Holds running mean/variance per feature for
    ONE person. Every measurement is expressed as deviation from THIS person's
    own distribution — never against a generic template.
    """

    def __init__(self, alpha: float = BASELINE_ALPHA):
        self.alpha = alpha
        self.mean: Dict[str, float] = {}
        self.var:  Dict[str, float] = {}
        self.n = 0

    def z(self, features: Dict[str, float]) -> Dict[str, float]:
        """
        Convert raw features to personal z-scores WITHOUT updating.
        Clamped to +/-Z_CLAMP: one wild feature must never dominate the reading.
        Unclamped z is why naive implementations flap.
        """
        out = {}
        for k, x in features.items():
            mu = self.mean.get(k, x)
            sd = math.sqrt(self.var.get(k, 0.0)) + _EPS
            raw = (x - mu) / sd if self.n >= 2 else 0.0
            out[k] = max(-Z_CLAMP, min(Z_CLAMP, raw))
        return out

    def update(self, features: Dict[str, float]) -> None:
        """Fold this turn into the baseline. Call AFTER z()."""
        a = self.alpha
        for k, x in features.items():
            if k not in self.mean:
                self.mean[k] = x
                self.var[k]  = 0.0
            else:
                mu_new = (1 - a) * self.mean[k] + a * x
                self.var[k] = (1 - a) * self.var[k] + a * (x - mu_new) ** 2
                self.mean[k] = mu_new
        self.n += 1

    def feature_reliability(self) -> Dict[str, float]:
        """
        Per-feature confidence in the BASELINE ITSELF, 0..1.

        With an unfamiliar person the doubt does not attach to the conclusion —
        it attaches to the measurement. A z-score of 2.0 computed against six
        observations is not a deviation, it is a guess about what their normal
        is. You cannot distinguish "unusual for them" from "I do not know them
        yet", and treating the first as established when it is the second is how
        you end up confidently wrong about a stranger.

        Standard error of the mean scales as sigma/sqrt(n), so reliability rises
        with observations and falls with the feature's own variability. This is
        the same doubt that, for a well-known person, attaches instead to the
        individual instance — it has simply moved to where the uncertainty
        actually lives.
        """
        out = {}
        for k in self.mean:
            n = max(self.n, 1)
            sd = math.sqrt(self.var.get(k, 0.0))
            mu = abs(self.mean.get(k, 0.0)) + _EPS
            sem = sd / math.sqrt(n)
            # reliability falls when the standard error is large relative to the
            # quantity being measured
            out[k] = round(max(0.0, min(1.0, 1.0 - (sem / mu))), 3) if n >= 3 else 0.0
        return out

    def attenuate(self, zvec: Dict[str, float]) -> Dict[str, float]:
        """Scale z-scores by how much the baseline behind them can be trusted."""
        rel = self.feature_reliability()
        return {k: round(v * (0.25 + 0.75 * rel.get(k, 0.0)), 3)
                for k, v in zvec.items()}

    @property
    def maturity(self) -> float:
        """How well we know this person. Gates confidence at cold start."""
        return min(1.0, self.n / MATURITY_FULL_AT)

    def to_dict(self) -> Dict[str, Any]:
        return {"alpha": self.alpha, "mean": self.mean, "var": self.var, "n": self.n}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PersonalBaseline":
        b = cls(alpha=d.get("alpha", BASELINE_ALPHA))
        b.mean = dict(d.get("mean", {}))
        b.var  = dict(d.get("var", {}))
        b.n    = int(d.get("n", 0))
        return b


# ── Session state: the integrated (context) side ─────────────────────────────

class SessionState:
    """Slow-moving. Accumulates. This is the position, not the derivative."""

    def __init__(self):
        self.turn_index = 0
        self.topic_window: Deque[frozenset] = deque(maxlen=CONTINUITY_WINDOW)
        self.z_window:     Deque[Dict[str, float]] = deque(maxlen=VOLATILITY_WINDOW)
        self.prev_text = ""
        self.prev_ts: Optional[float] = None
        self.last_state = "observing"
        self.sustained = 0
        self.last_confidence = 0.0
        self.whisper_ring: Deque[str] = deque(maxlen=WHISPER_SUPPRESS_N)
        # Lightweight retrospective buffer. The antecedent lives here, not in
        # the turn that trips the state — by the time the flip happens the
        # cause has already stopped being visible in the text.
        self.history: Deque[Dict[str, Any]] = deque(maxlen=ANTECEDENT_WINDOW)
        # Latched antecedent. Diagnosed ONCE on entry to a care state and held
        # for the duration of that episode.
        #
        # This must be latched, not recomputed. The turns that constitute the
        # flip are themselves fast, terse and dismissive — within two or three
        # of them they dominate the retrospective window and every cause
        # collapses to "flat / uninvested". The symptom overwrites its own
        # history. Freezing the reading at the moment of entry is the only way
        # to preserve what the switch was actually a reaction to.
        self.latched_antecedent: Optional[Dict[str, Any]] = None
        # Active falsification watch on the currently held conclusion.
        self.watch: Optional["Falsifier"] = None
        self.revisions: List[Dict[str, Any]] = []
        # Probing is not free and the budget is not renewable on demand. You get
        # two or three wrong guesses before someone stops engaging with you
        # entirely — and at that point you have not gathered information, you
        # have manufactured the very disengagement you were trying to read.
        self.probe_budget: float = PROBE_BUDGET_START
        self.probes: List[Dict[str, Any]] = []
        self.pending_probe: Optional[Dict[str, Any]] = None
        self.prior_tension: float = 0.0

        # ── Session-scale engagement memory ──────────────────────────────────
        # UNCAPPED — unlike topic_window/z_window/history above, this never
        # evicts. The 7-turn ANTECEDENT_WINDOW cannot answer "was this person
        # ever engaged this session" once more than 7 turns have passed since
        # they were — which is exactly the exhaustion-vs-uninvested confusion:
        # someone energetic an hour ago and flat now reads identically to
        # someone who was never engaged at all, if the only evidence kept is
        # the last 7 turns. Genuinely session-scale — kept for the life of
        # this SessionState object, spanning the whole open session, not a
        # rolling window within it. Not cross-session; that would need to
        # persist through MemoryCore instead, and this stays in-process for
        # cost reasons (checked on every turn, no disk round-trip).
        self.peak_arousal_this_session: float = 0.0
        self.peak_arousal_turn: int = 0
        self.peak_arousal_ts: float = 0.0
        self.held_turns: int = 0

    def topic_investment(self, tokens: Tuple[str, ...]) -> float:
        """
        How sustained is attention on THIS subject? 0..1

        This is the prerequisite for detecting investment reversal. Dismissing
        something you just started on is normal triage. Dismissing something you
        have been protecting for hours is a different event entirely, and only
        the second one means anything.
        """
        cur = frozenset(tokens)
        if not cur or not self.topic_window:
            return 0.0
        # Overlap coefficient, not Jaccard. Jaccard divides by the UNION, so it
        # collapses toward zero whenever message lengths differ — which is
        # exactly the case here, since the flip turn is short and the turns it
        # is being compared against are long. Containment is the correct
        # question: does this turn's subject appear in what came before?
        hits = 0
        for past in self.topic_window:
            if not past:
                continue
            overlap = len(cur & past) / max(min(len(cur), len(past)), 1)
            if overlap >= 0.20:
                hits += 1
        return hits / len(self.topic_window)

    def continuity_and_novelty(self, tokens: Tuple[str, ...]) -> Tuple[float, float]:
        """
        continuity = overlap with recent topics (are we on the same subject)
        novelty    = fraction of tokens never seen recently (are we advancing)

        These two together separate flow from friction: both have high
        continuity, but flow has high novelty and friction has low.
        """
        cur = frozenset(tokens)
        if not cur:
            return 0.0, 0.0
        seen = set()
        for s in self.topic_window:
            seen |= s
        if not seen:
            return 0.0, 1.0
        overlap  = len(cur & seen) / max(len(cur), 1)
        novelty  = len(cur - seen) / max(len(cur), 1)
        return overlap, novelty


# ── The interaction: gated product of context frame and affect vector ────────

def _infer_frame(f: TurnFeatures, continuity: float, novelty: float,
                 z: Dict[str, float]) -> Tuple[str, float]:
    """
    Soft context frame. Returns (frame, confidence).
    Never a hard label — downstream carries the alternative.
    """
    scores: Dict[str, float] = {
        "exploratory": 0.0, "blocked": 0.0, "executing": 0.0,
        "social": 0.0, "reflective": 0.0, "transacting": 0.0,
    }
    scores["exploratory"] += novelty * 1.4 + f.is_question * 0.5
    scores["blocked"]     += f.help_seeking * 2.0 + max(0.0, z.get("repetition", 0)) * 0.8
    scores["blocked"]     += continuity * 0.6 * (1.0 - novelty)
    scores["executing"]   += f.is_imperative * 1.8 + f.irreversibility * 1.2
    scores["social"]      += f.positive_lex * 1.5 + max(0.0, z.get("punct_density", 0)) * 0.3
    scores["reflective"]  += f.hedge_density * 1.5 + max(0.0, z.get("msg_length", 0)) * 0.4
    scores["transacting"] += f.is_question * 0.6 + (1.0 - continuity) * 0.5

    total = sum(max(0.0, v) for v in scores.values()) + _EPS
    best  = max(scores.items(), key=lambda kv: kv[1])
    return best[0], min(1.0, max(0.0, best[1]) / total)


def _affect_axes(z: Dict[str, float], vol: float) -> Dict[str, float]:
    """Collapse feature z-scores onto interpretable axes. Still all personal."""
    arousal = (
        0.40 * z.get("punct_density", 0.0)
        + 0.25 * z.get("caps_ratio", 0.0)
        + 0.20 * z.get("profanity", 0.0)
        - 0.15 * z.get("latency", 0.0)
    )
    valence = (
        -0.35 * z.get("negation_density", 0.0)
        - 0.30 * z.get("hedge_density", 0.0)
        - 0.20 * z.get("self_correct", 0.0)
    )
    load = (
        0.35 * z.get("hedge_density", 0.0)
        + 0.30 * z.get("self_correct", 0.0)
        + 0.35 * z.get("fragmentation", 0.0)
    )
    return {
        "arousal_z":    round(arousal, 3),
        "valence_z":    round(valence, 3),
        "volatility_z": round(vol, 3),
        "load_z":       round(load, 3),
    }


def _match_signatures(axes: Dict[str, float], f: TurnFeatures,
                      continuity: float, novelty: float,
                      z: Dict[str, float],
                      investment: float = 0.0) -> List[Tuple[str, float]]:
    """
    Multi-axis soft signature match. NOT keyword lookup.

    The critical separation: creative_chaos and friction BOTH show high arousal
    and high continuity. They differ on novelty and length trajectory.
    Chaos expands (novelty up, length up). Friction circles (novelty down,
    length down, repetition up).
    """
    a   = axes["arousal_z"]
    v   = axes["valence_z"]
    vol = axes["volatility_z"]
    ld  = axes["load_z"]
    len_z  = z.get("msg_length", 0.0)
    rep_z  = z.get("repetition", 0.0)

    sig: Dict[str, float] = {}

    # ── Deliberation collapse ────────────────────────────────────────────────
    # Hedging and self-correction are DELIBERATION markers. Their presence means
    # the person is still evaluating. Both dropping BELOW their own baseline at
    # once — not merely being low, but collapsing — means evaluation has stopped.
    #
    # This is the term that separates flow from "fuck it" acceleration. Both are
    # fast. Flow retains friction: you still hedge, still revise, still ask.
    # Disengagement sheds all of it simultaneously. That is not confidence, it is
    # abandonment of the evaluation step.
    hedge_z  = z.get("hedge_density", 0.0)
    corr_z   = z.get("self_correct", 0.0)
    delib_collapse = max(0.0, -hedge_z) * 0.5 + max(0.0, -corr_z) * 0.5
    speed    = max(0.0, -z.get("latency", 0.0))      # faster than personal baseline

    # flow / creative chaos — energy that is GOING somewhere.
    # Now explicitly penalised when deliberation has vanished: energy without
    # evaluation is not flow, however fast it looks.
    sig["flow"] = (
        max(0.0, a) * 0.5 + novelty * 1.2 + max(0.0, len_z) * 0.4
        - max(0.0, rep_z) * 0.9 - max(0.0, ld) * 0.5
        - delib_collapse * 0.9
    )

    # friction — energy that is CIRCLING
    sig["friction"] = (
        max(0.0, a) * 0.4 + max(0.0, rep_z) * 1.3 + continuity * 0.8
        - novelty * 1.1 + max(0.0, -len_z) * 0.5 + f.help_seeking * 1.4
    )

    # play — high energy, low stakes, no help-seeking
    sig["play"] = (
        max(0.0, a) * 0.7 + f.positive_lex * 1.3
        - f.irreversibility * 1.5 - f.help_seeking * 1.8 - max(0.0, ld) * 0.6
    )

    # depletion — low energy, contracting, high load, AND SLOW.
    #
    # Latency is the load-bearing term here, not brevity. A terse person firing
    # back "yep" in two seconds is efficient, not depleted. The same word after
    # a forty-second gap is a different signal entirely. Brevity alone cannot
    # distinguish them; brevity-with-delay can. Without this term the engine
    # pathologises fast, economical operators — the exact false positive that
    # makes affective systems feel patronising.
    # Require a FULL sigma of slowness before depletion is even on the table.
    # Marginal latency variation is normal working rhythm, not a warning sign.
    lat_z = z.get("latency", 0.0)
    slowness = max(0.0, lat_z - 1.0)
    sig["depletion"] = (
        max(0.0, -a) * 0.5 + max(0.0, -len_z) * 0.5 + max(0.0, ld) * 0.8
        + max(0.0, -v) * 0.5 - novelty * 0.4
        + slowness * 1.1                      # required, not optional
    ) * (0.35 + 0.65 * min(1.0, slowness))    # gated: no slowness, no depletion

    # disengagement — depletion presenting as ACCELERATION.
    #
    # The dangerous twin of depletion. Energy is gone, but instead of slowing
    # down the person stops deliberating and speeds up: "whatever, just ship it."
    # It reads as decisiveness. It is the opposite. Because it looks like flow,
    # a latency-gated depletion model is structurally blind to it — which is
    # exactly when someone does something irreversible they will regret.
    #
    # Signature: accelerating + deliberation collapsed + contracting + stakes up.
    # The stakes term is why this matters operationally: fast and careless is
    # merely fast until it touches something you cannot undo.
    # ── Investment reversal ──────────────────────────────────────────────────
    # The sharpest form of the signal is not general indifference. It is
    # dismissiveness aimed at the exact thing the person has been protecting.
    #
    #   "I have been guarding this behaviour for two days."
    #   "...you know what, I don't care. We're done."
    #
    # Topic continuity stays HIGH while valence inverts. That combination —
    # sustained investment plus termination language about the same subject —
    # is what distinguishes a burnout flip from ordinary triage. Dropping
    # something you just picked up is good judgement. Dropping something you
    # have defended for hours is a different event and should be read as one.
    reversal = investment * (f.finality + f.dismissive) * 3.0
    callous  = (f.finality * 0.8 + f.dismissive * 0.9 + f.absolutes * 0.4)

    sig["disengagement"] = (
        speed * 0.55
        + delib_collapse * 1.1
        + reversal * 1.6                # strongest term: flipping on your own work
        + callous * 1.0                 # the flippant / uncaring register itself
        + f.irreversibility * 1.1
        + max(0.0, -len_z) * 0.35
        + max(0.0, z.get("profanity", 0.0)) * 0.35
        - novelty * 0.35
        - f.is_question * 0.6
    )

    # sarcasm — valence MISMATCH: positive lexemes with negative structure
    sig["sarcasm"] = (
        f.positive_lex * 1.2 * (1.0 if (v < -0.3 or f.contrast_marker > 0) else 0.0)
        + f.contrast_marker * 0.6
    ) * 0.6   # deliberately low weight — weakest signature, often resolves to observing

    # steady — the default; wins when nothing else is moving
    sig["steady"] = 0.55 - (abs(a) + abs(v) + abs(vol) + abs(ld)) * 0.18

    ranked = sorted(sig.items(), key=lambda kv: kv[1], reverse=True)
    return [(k, round(max(0.0, s), 3)) for k, s in ranked]


def _agreement(z: Dict[str, float], top_score: float, runner_up: float) -> float:
    """
    Do independent features concur? Two components:
      - margin between top signature and runner-up
      - how many features actually moved (a lone outlier is noise)
    """
    moved = sum(1 for v in z.values() if abs(v) > 0.8)
    breadth = min(1.0, moved / 3.0)
    margin  = min(1.0, max(0.0, top_score - runner_up) / 0.8)
    return round(min(1.0, 0.5 * breadth + 0.5 * margin), 3)




# ── Antecedent diagnosis ─────────────────────────────────────────────────────
#
# The state is the symptom. The cause is the finding. Two people both arrive at
# disengagement — one ran out of time, one is stuck, one is exhausted, one blames
# themselves, one has something in their life pulling them elsewhere, one was
# never invested. Same reading. Different correct responses, and most of them are
# actively wrong for any given case.
#
# The cause is not visible in the turn that trips the state. By then it has
# resolved into flat dismissal. It is visible in the RUN-UP — the trajectory of
# the preceding turns. So this is a second-order pass over the history ring.
#
# Two axes:
#   cause      — what the switch was a reaction to
#   trajectory — HOW it arrived: spike (sudden) / decay (gradual) /
#                drift (attention moving) / flat (never engaged)

def _trend(vals: List[float]) -> float:
    """Signed slope over a short series. Positive = rising."""
    n = len(vals)
    if n < 3:
        return 0.0
    xs = list(range(n))
    mx, my = sum(xs) / n, sum(vals) / n
    den = sum((x - mx) ** 2 for x in xs) or 1.0
    return sum((xs[i] - mx) * (vals[i] - my) for i in range(n)) / den


def diagnose_antecedent(
    history: List[Dict[str, Any]],
    session_peak_arousal: float = 0.0,
    turns_since_peak: int = 999,
) -> Dict[str, Any]:
    """
    Classify what the switch was a reaction to, from the preceding window.

    session_peak_arousal / turns_since_peak: session-scale signal, uncapped,
    from SessionState.peak_arousal_this_session. Answers a question the
    7-turn `history` window structurally cannot: was this person EVER
    engaged this session, even if that was more than 7 turns ago? Without
    this, someone energetic an hour ago and flat now is indistinguishable
    from someone who was never engaged at all — the window simply can't see
    far enough back. This is exactly the exhaustion-vs-uninvested confusion
    the affect model doc names as unresolved; this closes it.
    """
    if len(history) < 3:
        return {"cause": "unknown", "confidence": 0.0, "window_turns": len(history),
                "evidence": [], "trajectory": "unknown",
                "conclusion_withheld": False, "withheld_reason": ""}

    lat   = [h["latency_z"]  for h in history]
    ln    = [h["len_z"]      for h in history]
    rep   = [h["repetition"] for h in history]
    nov   = [h["novelty"]    for h in history]
    inv   = [h["investment"] for h in history]
    load  = [h["load_z"]     for h in history]
    arous = [h["arousal_z"]  for h in history]

    temporal   = sum(h["temporal"]   for h in history)
    self_blame = sum(h["self_blame"] for h in history)
    helps      = sum(h["help_seek"]  for h in history)
    quests     = sum(h["is_question"] for h in history)

    t_lat, t_len, t_rep = _trend(lat), _trend(ln), _trend(rep)
    t_nov, t_load       = _trend(nov), _trend(load)

    # Real peak, genuinely outside what this window can see (happened before
    # the window started, not just near its edge).
    had_real_peak = session_peak_arousal > 1.0 and turns_since_peak > len(history)

    ev: List[str] = []
    scores: Dict[str, float] = {}

    # TIME PRESSURE — gaps shrinking, deadline language, scope compressing
    scores["time_pressure"] = temporal * 4.0 + max(0.0, -t_lat) * 0.9
    if temporal > 0.02: ev.append("deadline language in run-up")
    if t_lat < -0.25:   ev.append("response gaps shortening")

    # STUCK — circling. repetition rising, novelty collapsing, asking repeatedly
    scores["stuck"] = (max(0.0, t_rep) * 1.6 + max(0.0, -t_nov) * 1.2
                       + helps * 2.5 + quests * 0.35)
    if t_rep > 0.05:  ev.append("repetition climbing")
    if t_nov < -0.05: ev.append("novelty collapsing")
    if helps > 0.02:  ev.append("repeated help-seeking")

    # EXHAUSTION — gradual decay. slowing, contracting, load rising over time.
    # Also fires on a real session-scale peak followed by flatness — decay the
    # 7-turn trend math alone cannot see, because the energetic turns have
    # already scrolled out of the window by the time anyone would ask.
    scores["exhaustion"] = (max(0.0, t_lat) * 1.3 + max(0.0, -t_len) * 1.0
                            + max(0.0, t_load) * 1.1
                            + (1.4 if had_real_peak else 0.0))
    if t_lat > 0.25:  ev.append("gaps lengthening")
    if t_len < -0.15: ev.append("messages contracting over time")
    if had_real_peak:
        ev.append(f"was highly engaged {turns_since_peak} turns ago (arousal {session_peak_arousal:.1f}), flat since")

    # SELF-FAILURE — frustration turned inward. THE ONE THAT MATTERS MOST.
    scores["self_failure"] = self_blame * 6.0 + max(0.0, -sum(arous)/len(arous)) * 0.4
    if self_blame > 0.01: ev.append("self-directed failure attribution")

    # DISPLACED — attention moving elsewhere. novelty rising but investment
    # falling: they are talking about new things that are NOT this task.
    scores["displaced"] = (max(0.0, t_nov) * 1.1
                           + max(0.0, -_trend(inv)) * 1.8
                           + (1.0 if (sum(inv)/len(inv)) < 0.25 else 0.0) * 0.7)
    if _trend(inv) < -0.08: ev.append("investment declining while topic shifts")

    # UNINVESTED — never engaged. flat affect throughout, no questions, no
    # exploration. This is visible from the START, not at the flip.
    # "Never engaged" is the absence of every other explanation, so it must be
    # scored as a residual. Scored as a peer it wins by default whenever affect
    # is quiet — which is most of the time — and swamps the specific causes.
    #
    # A real session-scale peak is DIRECT EVIDENCE against "never engaged" —
    # not just another competing explanation, but a fact that falsifies this
    # one outright. Zeroed, not merely discounted, when had_real_peak is true.
    flat = 1.0 if (max(abs(a) for a in arous) < 0.9 and quests < 0.02) else 0.0
    specificity = min(1.0, (temporal * 3.0 + self_blame * 5.0 + helps * 2.0
                            + max(0.0, t_rep) * 1.5 + abs(t_lat) * 0.6))
    scores["uninvested"] = 0.0 if had_real_peak else (
        (flat * 1.3 + (1.0 - min(1.0, sum(inv)/len(inv))) * 0.4)
        * max(0.0, 1.0 - specificity)
    )
    if flat and not had_real_peak:
        ev.append("flat affect throughout, no exploratory turns")

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top, top_s = ranked[0]
    runner_s = ranked[1][1] if len(ranked) > 1 else 0.0
    conf = min(1.0, max(0.0, (top_s - runner_s) / 0.7)) * min(1.0, len(history) / 5.0)

    if conf < 0.25:
        top, conf = "unknown", round(conf, 3)

    # trajectory — HOW it arrived, independent of WHY
    if flat:                              traj = "flat"
    elif t_lat > 0.3 and t_len < -0.1:    traj = "decay"
    elif _trend(inv) < -0.1 and t_nov > 0: traj = "drift"
    elif abs(t_rep) > 0.08 or abs(t_lat) > 0.4: traj = "spike"
    else:                                  traj = "spike"

    result = {"cause": top, "confidence": round(conf, 3),
              "window_turns": len(history), "evidence": ev[:4], "trajectory": traj}
    result.update(build_hypotheses(scores, ev))
    # Charity may have reordered the primary — keep cause consistent with it
    if result["hypotheses"]:
        result["cause"] = result["hypotheses"][0]["cause"]
    return result


# Cause-specific steerage. The state says WHAT. This says WHAT TO DO ABOUT IT.
_ANTECEDENT_STEERAGE = {
    "time_pressure": (
        "Out of runway, not out of care. Cut scope with them explicitly — name "
        "what can ship broken and what cannot.",
        ["adding options", "suggesting refactors", "asking how they feel"]),
    "stuck": (
        "The flip is a stall that broke, not a decision. Change the approach, "
        "not the effort — a different angle, not another attempt.",
        ["restating", "encouragement", "repeating prior suggestions"]),
    "exhaustion": (
        "Gradual decay, not a decision point. Reduce load: one step, one choice, "
        "and hold the rest until they come back.",
        ["new options", "enthusiasm", "long responses"]),
    "self_failure": (
        "Frustration turned inward — they are blaming themselves, not the "
        "problem. Separate the two out loud. Locate the fault in the system.",
        ["agreeing they failed", "reassurance without evidence", "moving on quickly"]),
    "displaced": (
        "Attention has moved to something they care about more. Not depletion. "
        "Close the loop cleanly so this is resumable, and let them go.",
        ["pulling them back", "urgency", "guilt"]),
    "uninvested": (
        "Never engaged with this — working from obligation, not interest. Do not "
        "manufacture enthusiasm. Make it shorter and finishable.",
        ["motivational framing", "expanding scope", "asking what excites them"]),
    "unknown": ("", []),
}







# ── Personal priors ──────────────────────────────────────────────────────────
#
# "I know this person. I have seen them do this before. Usually when they do
#  this it means X — but there is something funny about this one."
#
# Two mechanisms, and the second is the point:
#
#   1. An EMPIRICAL per-person prior. Not "people who do X mean Y" but "when
#      THIS person does X it has meant Y in 8 of the last 9 instances." Learned
#      from outcomes, including the times the conclusion was overturned.
#
#   2. ANOMALY WITHIN the pattern. Having seen the pattern nine times is
#      precisely what makes it possible to notice that this instance sits
#      outside the usual shape of it. Familiarity is what generates the ability
#      to detect the exception.
#
# The behavioural rule that follows is counter-intuitive and load-bearing:
# a high hit rate combined with high anomaly must WIDEN uncertainty, not narrow
# it. The naive reading is "I have seen this nine times, so I am confident."
# The correct one is "I have seen this nine times, which is how I can tell this
# one is different." A strong prior earns the right to be surprised.

class PersonalPrior:
    """Per-person, per-cause outcome history and signature shape."""

    def __init__(self):
        # cause -> {"n": int, "confirmed": int, "revised_to": {cause: count}}
        self.outcomes: Dict[str, Dict[str, Any]] = {}
        # cause -> running mean z-vector observed when that cause was concluded
        self.centroid: Dict[str, Dict[str, float]] = {}
        self.centroid_n: Dict[str, int] = {}

    def record_conclusion(self, cause: str, zvec: Dict[str, float]) -> None:
        o = self.outcomes.setdefault(cause, {"n": 0, "confirmed": 0, "revised_to": {}})
        o["n"] += 1
        c = self.centroid.setdefault(cause, {})
        n = self.centroid_n.get(cause, 0)
        for k, v in zvec.items():
            c[k] = (c.get(k, v) * n + v) / (n + 1)
        self.centroid_n[cause] = n + 1

    def record_outcome(self, cause: str, revised_to: Optional[str]) -> None:
        o = self.outcomes.setdefault(cause, {"n": 0, "confirmed": 0, "revised_to": {}})
        if revised_to is None:
            o["confirmed"] += 1
        else:
            o["revised_to"][revised_to] = o["revised_to"].get(revised_to, 0) + 1

    def hit_rate(self, cause: str) -> Tuple[float, int]:
        o = self.outcomes.get(cause)
        if not o or o["n"] == 0:
            return 0.0, 0
        resolved = o["confirmed"] + sum(o["revised_to"].values())
        if resolved == 0:
            return 0.0, o["n"]
        return o["confirmed"] / resolved, o["n"]

    def usually_becomes(self, cause: str) -> Optional[str]:
        """When this conclusion has been wrong before, what did it turn out to be?"""
        o = self.outcomes.get(cause)
        if not o or not o["revised_to"]:
            return None
        return max(o["revised_to"].items(), key=lambda kv: kv[1])[0]

    def anomaly(self, cause: str, zvec: Dict[str, float]) -> Tuple[float, List[str]]:
        """
        How far does THIS instance sit from previous instances of the same
        conclusion? Returns (0..1 score, the features that are unusual).

        This is second-order deviation: not distance from the person's baseline,
        but distance from how this particular pattern normally looks for them.
        """
        c = self.centroid.get(cause)
        n = self.centroid_n.get(cause, 0)
        if not c or n < 3:
            return 0.0, []
        diffs = []
        for k, v in zvec.items():
            if k in c:
                d = abs(v - c[k])
                if d > 1.2:
                    diffs.append((k, round(d, 2)))
        if not diffs:
            return 0.0, []
        diffs.sort(key=lambda kv: kv[1], reverse=True)
        score = min(1.0, sum(d for _, d in diffs) / (len(zvec) * 1.5))
        return round(score, 3), [f"{k} unusual for this pattern (Δ{d})" for k, d in diffs[:3]]


def build_prior_note(prior: "PersonalPrior", cause: str,
                     zvec: Dict[str, float]) -> Dict[str, Any]:
    """The 'I know this person' block. Honest about its own base rate."""
    rate, seen = prior.hit_rate(cause)
    anom, odd = prior.anomaly(cause, zvec)
    becomes = prior.usually_becomes(cause)

    if seen < 3:
        return {"seen_before": seen, "hit_rate": None, "anomaly": anom,
                "note": "Not enough history with this person for a prior yet.",
                "widens_uncertainty": False}

    pct = int(round(rate * 100))
    note = f"Seen this pattern {seen} times with this person; held {pct}% of the time"
    if becomes:
        note += f" (when wrong, usually turned out to be '{becomes}')"
    note += "."

    widen = anom >= 0.35 and rate >= 0.6
    if widen:
        note += (f" But this instance sits outside the usual shape of it — "
                 f"{odd[0] if odd else 'the signature is off'}. "
                 f"Knowing the pattern this well is exactly why this one reads as "
                 f"an exception. Might be a different kind of day; holding the "
                 f"conclusion more loosely than the base rate alone would suggest.")

    return {"seen_before": seen, "hit_rate": round(rate, 2), "anomaly": anom,
            "unusual_features": odd, "usually_becomes_when_wrong": becomes,
            "note": note, "widens_uncertainty": widen}

# ── Falsification watch ──────────────────────────────────────────────────────
#
# Doubt that changes no behaviour is not doubt, it is decoration. "I could be
# wrong" appended to a conclusion you continue acting on is the same as
# certainty, and it is worse, because it looks like humility.
#
# Real doubt has three properties this implements:
#
#   1. It is DERIVED, not generic. It comes out of the reasoning chain that
#      produced the conclusion. This is why doubt scales WITH confidence rather
#      than against it: a weak conclusion cannot say what would break it, but a
#      strong one followed a specific line of logic and therefore knows exactly
#      which link is load-bearing.
#
#   2. It is ACTIVE. The falsifier is registered and every subsequent turn is
#      checked against it. Room is left for the counter-evidence to arrive and
#      to function when it does.
#
#   3. It FORCES revision. When the falsifier fires the conclusion is not
#      quietly reweighted — it is explicitly overturned and the reversal is
#      stated. A system that cannot say "I was wrong about that" cannot be
#      trusted when it says anything else.

@dataclass
class Falsifier:
    cause:        str    # the conclusion being held
    load_bearing: str    # WHICH inference carries it
    watch_for:    str    # human-readable description of the counter-evidence
    revises_to:   str    # what the conclusion becomes if falsified
    because:      str    # why that specific observation is decisive
    registered_at: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Each entry names the single inference the conclusion rests on, and the
# observation that would collapse it. Derived from the scoring terms — these are
# not decorative alternatives, they are the actual load-bearing assumptions.
_FALSIFIERS: Dict[str, Dict[str, str]] = {
    "uninvested": {
        "load_bearing": "flat affect throughout with no exploratory turns",
        "watch_for":    "any single turn showing real engagement — arousal above baseline, a genuine question, or novel exploration",
        "revises_to":   "exhaustion",
        "because":      "flat-THROUGHOUT is the only thing separating obligation from decay. One engaged turn proves engagement existed, which makes this a decline from something, not an absence of it.",
    },
    "exhaustion": {
        "load_bearing": "gradual decay — lengthening gaps and contracting messages",
        "watch_for":    "a sharp re-acceleration, or new subject matter appearing with energy",
        "revises_to":   "displaced",
        "because":      "someone genuinely depleted does not accelerate. Energy returning on a DIFFERENT subject means attention moved rather than ran out.",
    },
    "stuck": {
        "load_bearing": "repetition climbing while novelty collapses",
        "watch_for":    "self-directed failure language — first person plus failure attribution",
        "revises_to":   "self_failure",
        "because":      "circling a problem and blaming yourself for it look identical from the outside. The second needs a different response and is the more costly to miss.",
    },
    "time_pressure": {
        "load_bearing": "deadline language with shortening response gaps",
        "watch_for":    "the deadline passing or being dropped with no change in the pattern",
        "revises_to":   "stuck",
        "because":      "if the pressure lifts and the behaviour does not, the deadline was not what was driving it.",
    },
    "displaced": {
        "load_bearing": "investment declining while new subject matter appears",
        "watch_for":    "return to the original subject with sustained attention",
        "revises_to":   "stuck",
        "because":      "coming back means attention did not actually leave — it was a break in a block, not a departure.",
    },
    "self_failure": {
        "load_bearing": "first-person failure attribution in the run-up",
        "watch_for":    "the same failure language redirected outward, at the system or the tool",
        "revises_to":   "stuck",
        "because":      "frustration turned outward is a different state and needs a different response. Do not hold someone in a self-blame reading longer than the evidence supports.",
    },
}


def derive_falsifier(cause: str, turn_index: int) -> Optional[Falsifier]:
    """Extract the load-bearing assumption and what would break it."""
    spec = _FALSIFIERS.get(cause)
    if not spec:
        return None
    return Falsifier(cause=cause, registered_at=turn_index, **spec)


def check_falsifier(f: Falsifier, turn: Dict[str, Any]) -> bool:
    """
    Test the current turn against the registered counter-evidence.
    Each check corresponds directly to the load-bearing claim it would break.
    """
    if f.cause == "uninvested":
        return (abs(turn["arousal_z"]) > 1.0 or turn["is_question"] > 0.0
                or turn["novelty"] > 0.6)
    if f.cause == "exhaustion":
        # Re-engagement, not merely speed. The stated watch is "sharp
        # re-acceleration OR new subject matter appearing with energy" — an OR
        # over engagement markers. Requiring low latency AND novelty was a
        # mistranslation of the claim and made the watch nearly unfireable:
        # a long, exploratory, question-asking turn is re-engagement even if it
        # took a while to write. Length is evidence of effort, not of delay.
        reaccelerated = turn["latency_z"] < -1.0
        re_engaged    = (turn["len_z"] > 1.0 or turn["is_question"] > 0.0) \
                        and turn["novelty"] > 0.4
        return reaccelerated or re_engaged
    if f.cause == "stuck":
        return turn["self_blame"] > 0.01
    if f.cause == "time_pressure":
        return turn["temporal"] == 0.0 and turn["repetition"] > 0.8
    if f.cause == "displaced":
        return turn["investment"] > 0.6
    if f.cause == "self_failure":
        return turn["self_blame"] == 0.0 and turn["help_seek"] > 0.02
    return False

# ── Three-hypothesis abduction ───────────────────────────────────────────────
#
# Emotional inference is detective work, not classification. You cannot observe
# the state directly; you observe traces and reason backward to the explanation
# that best accounts for them. So the engine does not pick a winner — it carries
# three competing explanations and reasons about the difference between them.
#
#   primary    highest-evidence reading
#   alternate  the strongest materially-different rival
#   moonshot   a LOW-probability cause carried deliberately, selected not for
#              likelihood but for CONSEQUENCE — the explanation that, if true,
#              would make the primary's prescribed response most harmful
#
# The moonshot is the discipline. It is the same reason a clinician rules out
# the rare lethal thing before treating the common benign one: you carry the
# hypothesis you cannot afford to be wrong about, not the one you expect.

# Attribution class per cause. Benefit of the doubt is an ORDERING RULE:
# on close calls, prefer explanations that locate the reason in circumstance
# rather than in the person.
_ATTRIBUTION = {
    "time_pressure": "circumstance",
    "displaced":     "circumstance",
    "stuck":         "circumstance",
    "exhaustion":    "condition",      # about their state, not their character
    "self_failure":  "self_directed",  # they are already blaming themselves
    "uninvested":    "character",      # least charitable — never wins a close call
    "unknown":       "circumstance",
}
# Relative, not absolute. Raw scores span an order of magnitude between causes,
# so a fixed margin is meaningless — it fires constantly at the low end and
# never at the high end.
CHARITY_MARGIN = 0.35   # fraction of the leader's score

# Uncharitable readings must clear a HIGHER bar, not an equal one. Concluding
# "they don't care" should require more evidence than "they're struggling",
# because the cost of being wrong is asymmetric: reading circumstance as
# character is insulting when wrong and produces exactly the patronising
# response this model exists to prevent. This is benefit of the doubt expressed
# as a threshold rather than a sentiment.
_ATTRIBUTION_BURDEN = {
    "circumstance":  1.00,   # baseline
    "condition":     1.15,
    "self_directed": 1.30,   # do not confirm someone's self-blame cheaply
    "character":     1.80,   # heaviest burden of proof
}


def _charity_reorder(ranked: List[Tuple[str, float]]) -> Tuple[List[Tuple[str, float]], bool, str]:
    """
    Benefit of the doubt — implemented as WITHHOLDING, not as reweighting.

    The earlier version of this function was wrong in a way worth recording.
    It discounted uncharitable causes until a kinder one outranked them, then
    reported the kinder one as the finding. That is not giving someone the
    benefit of the doubt; it is deciding what you think and then saying
    something nicer while presenting it as your reading. Charitable dishonesty
    is still dishonesty, and it corrupts the evidence trail for everything
    downstream.

    In ordinary use the phrase means: *I am fairly sure I know why, but I am
    going to hold that and let it be resolved.* It terminates in asking, not in
    concluding differently.

    So there are two distinct situations and they are handled differently:

      GENUINE TIE (within CHARITY_MARGIN after burden weighting)
        The evidence really does not separate them. Preferring the charitable
        reading is a legitimate tiebreak, and it is applied.

      CLEAR EVIDENCE for an uncharitable cause
        Do NOT override it. The reading stands and is reported honestly — but
        the conclusion is marked WITHHELD: it must not drive a cause-specific
        response, and the disambiguator is surfaced instead so the next turn
        resolves it. We keep what we think. We just do not act on it yet.

    Returns (ranked, tiebreak_applied, withheld_reason)
    """
    if len(ranked) < 2:
        return ranked, False, ""

    top_cause, top_s = ranked[0]
    second_s = ranked[1][1]
    top_attr = _ATTRIBUTION.get(top_cause, "circumstance")
    order = {"circumstance": 0, "condition": 1, "self_directed": 2, "character": 3}

    # Is this a genuine tie, or clear evidence?
    lead = top_s or 1.0
    is_tie = (lead - second_s) / lead <= CHARITY_MARGIN

    if is_tie:
        # Legitimate tiebreak: evidence does not separate them, prefer the
        # charitable reading. This is the only case where reordering is honest.
        applied = False
        for i, (cause, sc) in enumerate(ranked[1:4], start=1):
            if (lead - sc) / lead <= CHARITY_MARGIN and \
               order.get(_ATTRIBUTION.get(cause, "circumstance"), 0) < \
               order.get(top_attr, 0):
                ranked[0], ranked[i] = ranked[i], ranked[0]
                top_cause, top_s = ranked[0]
                top_attr = _ATTRIBUTION.get(top_cause, "circumstance")
                applied = True
        return ranked, applied, ""

    # Clear evidence. Do not override it — but if the conclusion is an
    # uncharitable one, hold it rather than acting on it.
    if order.get(top_attr, 0) >= 2:      # self_directed or character
        return ranked, False, (
            f"'{top_cause}' leads the evidence, but it attributes to "
            f"{top_attr}. Conclusion held rather than acted on — the cost of "
            f"being wrong here is high and it is not yet distinguishable from "
            f"'{ranked[1][0]}'. Watch for the disambiguator before treating "
            f"this as established."
        )
    return ranked, False, ""


def _pick_moonshot(ranked: List[Tuple[str, float]], primary: str) -> Optional[Tuple[str, float]]:
    """
    Select the carried long shot by CONSEQUENCE, not probability.

    Conflict is measured against the primary's prescribed avoid-list: if the
    primary says "do not slow them down" and a candidate says "slow them down",
    being wrong about which one is true inverts the response. That candidate is
    worth carrying even at low likelihood.
    """
    p_whisper, p_avoid = _ANTECEDENT_STEERAGE.get(primary, ("", []))
    p_avoid_set = set(w.lower() for w in p_avoid)
    best, best_conflict = None, -1.0
    for cause, sc in ranked[1:]:
        if cause == primary:
            continue
        c_whisper, c_avoid = _ANTECEDENT_STEERAGE.get(cause, ("", []))
        if not c_whisper:
            continue
        # conflict = the primary's avoid-list intersecting this cause's advice
        conflict = sum(1 for a in p_avoid_set
                       if any(tok in c_whisper.lower() for tok in a.split()))
        conflict += sum(1 for a in c_avoid
                        if any(tok in p_whisper.lower() for tok in a.lower().split()))
        # prefer genuinely low-probability candidates — that is the point
        conflict += (1.0 - min(1.0, sc)) * 1.5
        if conflict > best_conflict:
            best, best_conflict = (cause, sc), conflict
    return best


# Actions that hold regardless of which hypothesis is true, plus the single
# observation that would separate them. Naming the disambiguator is the detective
# move: not "I know", but "here is what would tell us".
_CONVERGENT = {
    frozenset({"stuck", "exhaustion"}):
        ("Stop adding. Offer one different angle and nothing else.",
         "Do they take the new angle, or go quiet? Uptake = stuck. Silence = spent."),
    frozenset({"stuck", "time_pressure"}):
        ("Name what can ship unfinished. That helps whether they are blocked or out of runway.",
         "Do they engage with scope-cutting, or keep re-attacking the same block?"),
    frozenset({"exhaustion", "uninvested"}):
        ("Shorten it. One finishable step, no new options.",
         "Was there ever a high-energy stretch earlier this session? Decay implies exhaustion; flat throughout implies obligation."),
    frozenset({"self_failure", "stuck"}):
        ("Locate the fault in the system out loud before proposing anything.",
         "Do they accept the external attribution, or restate it as their own failing?"),
    frozenset({"displaced", "exhaustion"}):
        ("Close the loop so it is resumable, then stop.",
         "Is the new topic a different life-domain, or another sub-task?"),
    frozenset({"exhaustion", "displaced"}):
        ("Close the loop so it is resumable, then stop.",
         "Is the new subject a different life-domain, or another sub-task?"),
    frozenset({"uninvested", "displaced"}):
        ("Make it shorter and finishable. Do not pull them back.",
         "Did they ever volunteer anything unprompted about this task?"),
    frozenset({"stuck", "displaced"}):
        ("Offer one different angle, and make the exit clean if they take it.",
         "Does the new topic relate to the block, or replace it?"),
    frozenset({"self_failure", "exhaustion"}):
        ("Attribute the fault to the system, then reduce load. Both hold.",
         "Do they argue with the external attribution?"),
    frozenset({"time_pressure", "stuck"}):
        ("Name what can ship unfinished. Helps whether blocked or out of runway.",
         "Do they engage with scope-cutting, or keep re-attacking the block?"),
    frozenset({"time_pressure", "uninvested"}):
        ("Cut scope to the minimum shippable thing.",
         "Do they push back on what gets cut? Investment shows up as objection."),
}


def build_hypotheses(scores: Dict[str, float], evidence: List[str]) -> Dict[str, Any]:
    """Three competing explanations, compared — rather than one asserted."""
    ranked = sorted(((k, v) for k, v in scores.items() if k != "unknown"),
                    key=lambda kv: kv[1], reverse=True)
    if not ranked:
        return {"hypotheses": [], "convergent_action": "", "disambiguator": "",
                "charity_applied": False}

    ranked, charity, withheld = _charity_reorder(list(ranked))
    primary, p_s = ranked[0]
    alternate, a_s = ranked[1] if len(ranked) > 1 else (None, 0.0)
    moon = _pick_moonshot(ranked, primary)

    hyps = [{"cause": primary, "role": "primary", "score": round(p_s, 3),
             "attribution": _ATTRIBUTION.get(primary, "circumstance")}]
    if alternate:
        hyps.append({"cause": alternate, "role": "alternate", "score": round(a_s, 3),
                     "attribution": _ATTRIBUTION.get(alternate, "circumstance")})
    if moon and moon[0] not in (primary, alternate):
        hyps.append({"cause": moon[0], "role": "moonshot", "score": round(moon[1], 3),
                     "attribution": _ATTRIBUTION.get(moon[0], "circumstance"),
                     "why_carried": "low likelihood, but would invert the correct response"})

    # Action that holds across primary and alternate
    action, disambig = "", ""
    if alternate:
        pair = frozenset({primary, alternate})
        action, disambig = _CONVERGENT.get(pair, ("", ""))
    if not action:
        action = _ANTECEDENT_STEERAGE.get(primary, ("", []))[0]
        disambig = "No convergent action for this pair — acting on the primary reading."

    # A withheld conclusion must not drive a cause-specific response. Fall back
    # to the action that is safe across the contenders, and lead with what would
    # actually resolve it.
    if withheld:
        action = _CONVERGENT.get(frozenset({primary, alternate}), (action, disambig))[0] \
                 if alternate else action
        if not action:
            action = "Hold. Do not act on this reading yet."

    return {"hypotheses": hyps, "convergent_action": action,
            "disambiguator": disambig,
            "charity_tiebreak": charity,
            "conclusion_withheld": bool(withheld),
            "withheld_reason": withheld}











# ── One read, several consumers ──────────────────────────────────────────────
#
# An earlier version of this model presented "care" and "performance" as two
# channels, as though they were separable concerns served by a shared
# measurement. That was an engineering convenience mistaken for a real boundary,
# and it is wrong in a way that matters.
#
# When you deal with people you deal with all of them at once. The read that
# tells a character how to play a line is the same read that says skip the
# preamble because they are moving fast. The subtext detection that catches
# "hedging on something that matters" catches it whether it is a character in a
# scene or a person at four in the morning. It is one faculty.
#
# Splitting it produces a system that is technically correct and unpleasant to
# use — attentive during the hard parts and generic the rest of the time. The
# emotional accuracy is not a layer applied on top of being useful. It is what
# being useful looks like when it is done properly: knowing someone is in a
# hurry is WHY you skip the preamble; knowing they are circling is WHY you offer
# a different angle instead of another attempt.

def route(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    One reading, addressed to whoever needs it. Not a partition — the same
    numbers, surfaced where each consumer can act on them.
    """
    prof = payload["reading"].get("operating_profile")
    return {
        "everyday": {
            # The largest share of the job, and the part most systems skip.
            "meet_them_at": payload["reading"].get("meet_them_at"),
            "pace":         (prof or {}).get("rhythm"),
            "length":       (prof or {}).get("register"),
            "quiet_means":  (prof or {}).get("quiet_is"),
        },
        "dialogue": {
            "register_to_mirror": payload["performance"]["register_to_mirror"],
            "subtext":            payload["performance"]["subtext"],
            "tension":            payload["performance"]["tension"],
        },
        "animation": {
            # Numbers a rig can actually consume — a jaw and a breath rate
            # cannot infer anything, which is why explicit measurement earns
            # its keep here even where a language model might not need it.
            "intensity":  payload["performance"]["dramatic_intensity"],
            "arousal":    payload["affect"]["arousal_z"],
            "load":       payload["affect"]["load_z"],
        },
        "care": {
            "state":      payload["reading"]["state"],
            "steerage":   payload["steerage"].get("whisper", ""),
            "emit":       payload["steerage"].get("emit", False),
        },
        "trust": {
            # Every consumer gets the quality of the foundation, so nobody acts
            # on a confident-looking reading built on a sparse baseline.
            "baseline_quality": payload["baseline"]["quality"],
            "reading_confidence": payload["reading"]["confidence"],
            "capped_by": ("baseline" if payload["baseline"]["quality"] <=
                          payload["reading"]["confidence"] else "evidence"),
        },
    }

# ── Operating profile: normal as a POSITIVE observation ──────────────────────
#
# The engine originally treated "steady" as the null case — what gets reported
# when nothing is moving. That is backwards twice over.
#
#   1. Normal is the measuring instrument. Every deviation means something only
#      because there is a well-understood baseline underneath it. Be sloppy
#      about the ordinary and every reading built on top of it is noise. All the
#      sophistication at the edges is borrowed credibility from how carefully
#      the middle was learned.
#
#   2. Normal is most of a life. If a system is only really present when
#      something is wrong, it is not present — it is on call. Most of a working
#      relationship is ordinary Tuesdays, and being accurate about those is the
#      larger part of the job, not the leftover.
#
# So "steady" is not an absence of signal. It is a positive characterisation of
# how this person works, and it is the thing Alex and Jeremy need most of the
# time: not "what is wrong" but "here is how they operate — meet them there."

@dataclass
class OperatingProfile:
    """How this person works when nothing in particular is happening."""
    rhythm:        str    # brisk | measured | deliberate
    register:      str    # terse | plain | expansive
    engagement:    str    # interrogative | declarative | directive
    energy:        str    # high | even | low
    signals_with:  List[str]          # which channels they actually use
    quiet_is:      str                # what silence means FOR THEM
    confidence:    float
    sample_n:      int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def meet_them_at(self) -> str:
        """The one-line instruction. Positive, behavioural, never about state."""
        r = {"brisk": "Keep it quick.", "measured": "Normal pace.",
             "deliberate": "Give them room to think."}[self.rhythm]
        g = {"terse": "Short answers.", "plain": "Direct answers.",
             "expansive": "They want the reasoning, not just the result."}[self.register]
        e = {"interrogative": "They ask; answer what was asked.",
             "declarative": "They state; confirm or correct.",
             "directive": "They instruct; do it and report."}[self.engagement]
        return f"{r} {g} {e}"


def build_operating_profile(baseline: "PersonalBaseline",
                            history: List[Dict[str, Any]]) -> Optional[OperatingProfile]:
    """Characterise the ordinary. Requires enough observations to be honest."""
    if baseline.n < 6:
        return None

    m = baseline.mean
    lat  = m.get("latency", 0.0)
    ln   = m.get("msg_length", 0.0)
    hedge = m.get("hedge_density", 0.0)
    frag = m.get("fragmentation", 0.0)
    punct = m.get("punct_density", 0.0)

    rhythm   = "brisk" if lat < 2.2 else ("measured" if lat < 3.4 else "deliberate")
    register = "terse" if ln < 40 else ("plain" if ln < 140 else "expansive")

    q = sum(h.get("is_question", 0.0) for h in history) / max(len(history), 1)
    engagement = ("interrogative" if q > 0.35 else
                  "directive" if frag > 0.20 else "declarative")

    energy = "high" if punct > 0.12 else ("low" if punct < 0.02 else "even")

    signals = []
    if punct > 0.06:  signals.append("punctuation")
    if hedge > 0.04:  signals.append("hedging")
    if frag  > 0.18:  signals.append("fragmentation")
    if m.get("profanity", 0.0) > 0.01: signals.append("profanity")
    if not signals:   signals = ["length"]

    # What silence means for THIS person — a fast writer going quiet is a
    # different event than a deliberate one taking their usual time.
    quiet_is = ("unusual — they normally answer fast" if rhythm == "brisk"
                else "expected — they take their time" if rhythm == "deliberate"
                else "mildly notable")

    rel = baseline.feature_reliability()
    conf = round(sum(rel.values()) / max(len(rel), 1), 3) if rel else 0.0

    return OperatingProfile(rhythm=rhythm, register=register, engagement=engagement,
                            energy=energy, signals_with=signals, quiet_is=quiet_is,
                            confidence=conf, sample_n=baseline.n)


# ── Baseline health: the foundation is the primary output ────────────────────
#
# A wrong baseline does not produce one wrong answer. It produces a confident
# chain of them — z-scores, axes, signatures, cause, action, each step inheriting
# the error and adding certainty to it. So the health of the foundation is
# reported alongside everything built on it, and confidence PROPAGATES: no
# conclusion may be more confident than the measurement it rests on.

def baseline_health(baseline: "PersonalBaseline",
                    recent_z: List[Dict[str, float]]) -> Dict[str, Any]:
    """Coverage, stability, drift and contamination of the baseline itself."""
    rel = baseline.feature_reliability()
    n = baseline.n

    covered = [k for k, v in rel.items() if v >= 0.6]
    coverage = round(len(covered) / max(len(rel), 1), 3) if rel else 0.0

    # Stability: has the baseline settled, or is it still moving?
    stability = round(min(1.0, n / 25.0), 3)

    # Drift: are recent observations consistently on one side of the mean?
    # That is a person changing, not noise — and the baseline should follow it
    # rather than treat them as permanently anomalous.
    drift, drifting = 0.0, []
    if len(recent_z) >= 5:
        for k in rel:
            vals = [zz.get(k, 0.0) for zz in recent_z[-5:]]
            if all(v > 0.5 for v in vals) or all(v < -0.5 for v in vals):
                drifting.append(k)
        drift = round(len(drifting) / max(len(rel), 1), 3)

    # Contamination: an unusually variable baseline suggests it absorbed an
    # abnormal stretch. Someone's bad week becomes their "normal" and every
    # subsequent reading is measured against a distorted reference.
    variances = [baseline.var.get(k, 0.0) for k in baseline.mean]
    mean_var = sum(variances) / max(len(variances), 1)
    contaminated = mean_var > 0 and stability > 0.5 and drift > 0.4

    quality = round(min(coverage, stability) * (0.6 if contaminated else 1.0), 3)

    notes = []
    if n < 8:            notes.append("cold — too few observations to trust deviations")
    if coverage < 0.5:   notes.append("sparse — several features have no usable baseline")
    if drift > 0.4:      notes.append(f"drifting on {', '.join(drifting[:3])} — their normal may be changing")
    if contaminated:     notes.append("possibly contaminated — an abnormal stretch may have entered the baseline")
    if not notes:        notes.append("healthy")

    return {"quality": quality, "coverage": coverage, "stability": stability,
            "drift": drift, "drifting_features": drifting[:4],
            "contaminated": contaminated, "sample_n": n, "notes": notes}


def propagate(*confidences: float) -> float:
    """
    A conclusion may be no more confident than the weakest measurement beneath
    it. Using the minimum rather than a product avoids compounding penalties
    while still refusing to let a shaky foundation yield a certain answer.
    """
    vals = [c for c in confidences if c is not None]
    return round(min(vals), 3) if vals else 0.0

# ── Performance channel ──────────────────────────────────────────────────────
#
# The care channel is not the only consumer, and arguably not the primary one.
# PubCast is a virtual production system. Characters have to READ emotion in
# order to PERFORM it, and a scene has to understand its own build well enough
# to know which release is true.
#
# The same evaluation feeds both. What differs is what is done with it:
#
#   care channel         adjust pacing, load, and what is offered
#   performance channel  mirror register, play subtext, land the beat
#
# The affect/context split maps directly onto text and subtext: context is what
# the line is ABOUT, affect is what is happening UNDERNEATH it. That is not an
# analogy — it is the same measurement, which is why one engine serves both.

# Where a build can go. The obvious release is rarely the truest one — a scene
# coiled toward violence that resolves into someone quietly sitting down and
# crying is the take that works, but only when the subversion is chosen rather
# than stumbled into.
_RELEASES = {
    "escalation":  "the build pays off as expected — the confrontation lands",
    "collapse":    "the build inverts — it comes out as grief instead of force",
    "withdrawal":  "the build is refused — they go quiet and leave the room",
    "deflection":  "the build is punctured — a joke, and the pressure stays",
    "rupture":     "the build breaks sideways — something unrelated comes out",
}


def dramatic_intensity(text: str, f: TurnFeatures, axes: Dict[str, float]) -> float:
    """
    Intensity as it appears in DIALOGUE, which is not how it appears in chat.

    The chat-facing arousal measure keys on punctuation, capitals and profanity.
    Dramatic writing uses almost none of that. "I counted it twice. Twice." has
    no exclamation mark and is one of the most charged lines a person can say.
    Intensity on the page is carried by:

        repetition for emphasis      "dont. dont say her name"
        fragmentation                short declaratives stacked
        direct address               "you took", second person accusation
        imperatives under pressure   commands rather than requests
        specificity                  concrete detail replacing generality

    Measuring a scene with the chat proxy reports calm during the tensest
    moment in the script. The two channels genuinely need different instruments.
    """
    low = (text or "").lower()
    words = _WORD_RE.findall(low)
    if not words:
        return 0.0
    n = len(words)

    sentences = [x.strip() for x in _SENT_RE.split(text or "") if x.strip()]
    frag = (len(sentences) / max(6, min(n, 12))) if n else 0.0   # short stacked declaratives

    # immediate lexical repetition — the emphasis device
    rep = sum(1 for i in range(1, len(words)) if words[i] == words[i-1]) / n
    # repetition across the line, not just adjacent
    counts: Dict[str, int] = {}
    for w in words:
        if w not in _STOPWORDS and len(w) > 2:
            counts[w] = counts.get(w, 0) + 1
    # Count repeats against a floor rather than the full line length. Dividing
    # by word count penalises long intense lines: "after everything. after all
    # of it." is doing the same work as "twice. twice." but gets a third of the
    # credit purely for being longer.
    echo = sum(c - 1 for c in counts.values() if c > 1) / max(6, min(n, 12))

    second_person = sum(1 for w in words if w in {"you", "your", "youre", "yours"}) / n
    imperative    = f.is_imperative
    negation      = f.negation_density

    return round(min(1.0,
        frag * 1.6 + rep * 3.0 + echo * 2.2
        + second_person * 1.4 + imperative * 0.5 + negation * 0.8
        + max(0.0, axes["arousal_z"]) * 0.15), 3)


def performance_read(axes: Dict[str, float], f: TurnFeatures,
                     context: Dict[str, Any], reading: Dict[str, Any],
                     sustained: int, text: str = "",
                     prior_tension: float = 0.0) -> Dict[str, Any]:
    """
    The same evaluation, framed for performance rather than for care.

    Produces what a character needs to play the moment: the register to mirror,
    the subtext under the line, and — when tension is accumulating — the
    candidate releases ranked, with the note that the expected one is usually
    the weakest choice.
    """
    a, v, ld = axes["arousal_z"], axes["valence_z"], axes["load_z"]
    dram = dramatic_intensity(text, f, axes)

    # Register to mirror. Feeling seen comes from being MATCHED, not from being
    # described. This is the single most useful output for a character.
    if dram > 0.55 and f.negation_density > 0.05:
        register = "clipped"
    elif dram > 0.55:                      register = "pressed"
    elif abs(a) < 0.6 and abs(ld) < 0.6 and dram < 0.3:
        register = "level"
    elif a > 1.0 and f.finality > 0:      register = "clipped"
    elif a > 1.0:                          register = "quick"
    elif ld > 1.0:                         register = "halting"
    elif a < -0.8:                         register = "flat"
    else:                                  register = "measured"

    # Subtext: what is under the line rather than in it.
    subtext = []
    if f.hedge_density > 0.05 and context["stakes"] > 0.3:
        subtext.append("hedging on something that matters — not indecision, protection")
    if f.finality > 0 and context.get("investment", 0) > 0.4:
        subtext.append("dismissing something they care about — the opposite of indifference")
    if v < -0.5 and f.positive_lex > 0:
        subtext.append("saying the agreeable thing while meaning the other one")
    if f.self_blame > 0:
        subtext.append("the accusation is pointed inward")
    if abs(a) > 1.2 and f.is_question > 0:
        subtext.append("the question is not really a question")

    # Tension accounting — is this scene coiling?
    # Dramatic intensity carries the weight here, not chat arousal.
    instant = (0.45 * dram + 0.22 * context["stakes"]
               + 0.13 * min(1.0, sustained / 5.0) + 0.10 * max(0.0, -v)
               + 0.10 * max(0.0, a))
    # Tension RATCHETS. A scene accumulates — a quieter line after a charged one
    # does not reset the room, it sits inside what was already built. Decay is
    # slow and deliberate; release is what discharges it, not the next sentence.
    tension = round(min(1.0, max(instant, prior_tension * 0.88)), 3)

    out = {
        "register_to_mirror": register,
        "subtext": subtext,
        "tension": tension,
        "dramatic_intensity": dram,
        "playable_note": "",
        "releases": [],
    }

    if tension >= 0.55:
        # Rank the releases, then flag the subversion. The expected payoff is
        # the least interesting available choice and usually the least true.
        expected = "escalation"
        ranked = ["escalation", "collapse", "withdrawal", "deflection", "rupture"]
        if ld > 0.8:              ranked = ["collapse", "withdrawal", "escalation", "rupture", "deflection"]
        elif f.finality > 0:      ranked = ["withdrawal", "collapse", "rupture", "escalation", "deflection"]
        elif f.positive_lex > 0:  ranked = ["deflection", "escalation", "rupture", "collapse", "withdrawal"]

        out["releases"] = [{"release": r, "what_it_is": _RELEASES[r],
                            "expected": r == expected} for r in ranked[:3]]
        out["playable_note"] = (
            f"Tension at {tension:.2f} and still climbing. The build points at "
            f"'{expected}'. Consider '{ranked[0]}' — a scene coiled toward one "
            f"payoff that delivers another is the take that works, provided the "
            f"turn is chosen rather than fallen into. The build has to be real "
            f"for the subversion to mean anything."
        )
    else:
        out["playable_note"] = f"Play it {register}. Match, do not comment."

    return out

# ── Surfacing constraint ─────────────────────────────────────────────────────
#
# THE HARD RULE: never tell someone what they are feeling.
#
# Every reading in this engine is an inference from indirect evidence about the
# least observable thing there is. Saying it out loud — "you seem exhausted",
# "you're frustrated" — fails in both directions:
#
#   Wrong: you have announced that you have no idea what you are talking about,
#          while being confident enough to say something intimate unprompted.
#   Right: it is still presumptuous, and to someone already upset it is
#          infuriating rather than comforting.
#
# And the damage is not local. A single bad emotional attribution does not just
# discredit that statement; it retroactively discredits everything the system
# has said and will say. Faith is expensive to earn and is lost in one sentence.
#
# So the entire output of this engine is INTERNAL. It changes how the system
# behaves. It never announces what the system believes about the person. The
# distinction is not stylistic — it is the difference between a system that
# adapts and one that diagnoses people to their face.
#
# Because a downstream model can paraphrase an internal note into a user-facing
# statement without meaning to, the prohibition is carried explicitly in the
# payload rather than left as a convention.

_ATTRIBUTION_PATTERNS = [
    "you seem", "you're feeling", "you are feeling", "you sound",
    "you appear", "you must be", "i can tell you", "sensing that you",
    "you seem to be", "it seems like you", "you're clearly", "you look",
]

# Phrases that describe a state rather than prescribe a behaviour. Safe in an
# internal note, dangerous the moment they are echoed toward the person.
_STATE_WORDS = [
    "exhausted", "depleted", "burnt out", "burned out", "frustrated",
    "struggling", "overwhelmed", "running on empty", "giving up",
    "checked out", "disengaged", "upset", "angry", "tired", "spent",
]


def surfacing_guard(whisper: str) -> Dict[str, Any]:
    """
    Mark internal steerage with an explicit surfacing contract.

    Returns the note plus the constraints a consumer must honour. This is
    deliberately verbose in the payload: a downstream model that paraphrases an
    internal observation into a user-facing statement will not have meant to,
    and a convention it was never shown will not stop it.
    """
    low = whisper.lower()
    contains_state = [w for w in _STATE_WORDS if w in low]
    return {
        "internal_only": True,
        "surface_verbatim": False,
        "contains_state_language": contains_state,
        "never_say": [
            "any sentence naming what the person is feeling",
            "any paraphrase of this note directed at the person",
            "any check-in framed around their emotional state",
        ],
        "instead": (
            "Change behaviour, do not describe the person. Adjust pacing, "
            "length, and what is offered. The adaptation should be felt, "
            "not announced."
        ),
        "contract": (
            "SHAPE the response with this; do not ANNOUNCE it. The prohibition "
            "is narrow and specific: do not state the diagnosis at the person. "
            "It is not a prohibition on using the understanding — the "
            "understanding is the entire point. Reading it correctly is what "
            "lets you match someone's register so they feel seen, and knowing "
            "WHY is what makes them feel understood. Neither requires saying "
            "it out loud, and both require getting it right."
        ),
        "use_it_to": [
            "mirror their register — length, pace, formality, directness",
            "account for the cause without naming it",
            "choose what to offer and what to leave alone",
            "decide how much to say and how fast to say it",
        ],
    }


def validate_user_facing(text: str) -> Tuple[bool, str]:
    """
    Check a candidate user-facing string for emotional attribution.
    Returns (safe, reason). Intended as a downstream guard before anything
    reaches the person.
    """
    low = text.lower()
    for pat in _ATTRIBUTION_PATTERNS:
        if pat in low:
            for w in _STATE_WORDS:
                if w in low:
                    return False, (
                        f"Names the person's state ('{pat} ... {w}'). This is the "
                        f"one thing the engine must never do — wrong destroys "
                        f"credibility, right is presumptuous, and either way it "
                        f"is not recoverable."
                    )
    return True, ""

# ── Probing: acting to learn ─────────────────────────────────────────────────
#
# Every other mechanism in this engine withholds. Confidence floors, maturity
# gates, withheld conclusions, anomaly widening, falsifier watches — all of them
# are brakes. Nothing forces commitment, and a system that only ever brakes does
# not fail safely, it fails silently. Holding a conclusion for twelve turns
# because you are not certain has not protected anyone; it has abandoned them
# carefully.
#
# The resolution is that ACTING IS AN INFORMATION-GATHERING MOVE. A wrong guess
# is not purely cost — it is yield. Offer someone a different angle and if they
# are not stuck they will say so, and that single correction resolves an
# ambiguity that no amount of further watching would have settled. The error
# cuts through the problem and makes it moot.
#
# So probes are selected on the OPPOSITE criterion from moonshots:
#
#   moonshot  the hypothesis you cannot afford to be wrong about  (consequence)
#   probe     the hypothesis where being wrong is cheap and LEGIBLE (yield)
#
# And the phrasing carries weight, because a probe only works if correction is
# easy. "Here is a different angle" invites "no, that is not it." "You seem
# exhausted" is far harder to push back on without friction — it is a worse
# probe even when it is a better guess.

# reversibility: what does it cost to be wrong about this?  1.0 = free
# legibility:    how clearly would a wrong guess be corrected? 1.0 = unmistakable
_PROBE_PROFILE = {
    "stuck":         {"reversibility": 0.90, "legibility": 0.85,
                      "reveals": "if not stuck, they will name what is actually blocking them"},
    "time_pressure": {"reversibility": 0.85, "legibility": 0.90,
                      "reveals": "scope-cutting gets accepted or refused, and the refusal names the real constraint"},
    "displaced":     {"reversibility": 0.75, "legibility": 0.70,
                      "reveals": "offering a clean exit gets taken or declined"},
    "exhaustion":    {"reversibility": 0.45, "legibility": 0.40,
                      "reveals": "hard to correct without conceding the premise"},
    "uninvested":    {"reversibility": 0.20, "legibility": 0.35,
                      "reveals": "insulting if wrong, and awkward to deny"},
    "self_failure":  {"reversibility": 0.30, "legibility": 0.50,
                      "reveals": "risks confirming a self-blame that may not be there"},
}

# Probe phrasing is written so that being wrong is easy to correct. Each offers
# something concrete and refusable rather than naming the person's state.
_PROBE_ACTION = {
    "stuck":         "Offer one specific different angle. Concrete enough to refuse.",
    "time_pressure": "Name one thing that could ship unfinished. See if they take it.",
    "displaced":     "Offer a clean stopping point. See if they take the exit.",
    "exhaustion":    "Make the next step smaller without naming why.",
    "uninvested":    "Shorten it and make it finishable. Do not name the reason.",
    "self_failure":  "Attribute the fault to the system, concretely. See if they accept it.",
}


def select_probe(hypotheses: List[Dict[str, Any]],
                 turns_held: int) -> Optional[Dict[str, Any]]:
    """
    Choose a hypothesis to ACT on in order to learn, rather than waiting.

    Selected for yield, not likelihood: reversibility (cheap to be wrong) times
    legibility (a wrong guess gets corrected clearly), weighted by plausibility.
    Pressure to commit rises the longer a conclusion has been held, so that
    waiting has a cost instead of being the free default.
    """
    if not hypotheses:
        return None
    scores = [h["score"] for h in hypotheses] or [1.0]
    top = max(scores) or 1.0
    best, best_v = None, 0.0
    for h in hypotheses:
        prof = _PROBE_PROFILE.get(h["cause"])
        if not prof:
            continue
        plaus = (h["score"] / top) if top else 0.0
        value = prof["reversibility"] * prof["legibility"] * (0.4 + 0.6 * plaus)
        if value > best_v:
            best, best_v = h, value
    if not best:
        return None

    prof = _PROBE_PROFILE[best["cause"]]
    # Waiting is not free. The longer a conclusion sits unresolved, the lower the
    # bar for acting on it.
    threshold = max(0.20, 0.45 - 0.05 * turns_held)
    if best_v < threshold:
        return None

    return {
        "probe_cause":   best["cause"],
        "action":        _PROBE_ACTION.get(best["cause"], ""),
        "probe_value":   round(best_v, 3),
        "reversibility": prof["reversibility"],
        "if_wrong":      prof["reveals"],
        "framing": (
            f"Acting on '{best['cause']}' to learn, not because it is settled. "
            f"Cheap to be wrong about, and being wrong here is informative: "
            f"{prof['reveals']}."
        ),
    }

# ── Steerage generation ──────────────────────────────────────────────────────

_WHISPER_TABLE = {
    "flow": (
        "Moving well and covering new ground. Stay out of the way — answer, don't redirect.",
        "match", 0.85, ["interrupting", "summarizing", "checking in"],
    ),
    "friction": (
        "Circling the same block. Offer a different angle, don't restate what's been said.",
        "step_back", 0.60, ["cheerleading", "restating", "adding steps"],
    ),
    "play": (
        "Light and low-stakes right now. Match the register, keep it short.",
        "match", 0.70, ["over-explaining", "formality"],
    ),
    "depletion": (
        "Energy is dropping and messages are contracting. Reduce load — smaller steps, fewer choices.",
        "slow_down", 0.35, ["long responses", "new options", "enthusiasm"],
    ),
    "disengagement": (
        "Flipped on something they were protecting — running-on-empty, not a "
        "considered call. Don't slow them down or ask how they are; guard the "
        "irreversible step and hold the abandoned thing so it survives the mood.",
        "guard", 0.50,
        ["checking in", "asking how they feel", "slowing them down", "enthusiasm"],
    ),
    "sarcasm": (
        "Read may be ironic. Take the content, not the surface tone.",
        "hold", 0.60, ["literal agreement"],
    ),
    "steady": (
        "", "none", 0.75, [],
    ),
}


def _build_steerage(state: str, confidence: float, sustained: int,
                    session: SessionState) -> Dict[str, Any]:
    """Silence is a valid output. Emit only when confident AND non-duplicative."""
    if state in ("observing", "steady") or confidence < CONFIDENCE_FLOOR:
        return {"emit": False, "whisper": "", "pacing": "none",
                "load_budget": 0.75, "avoid": []}

    whisper, pacing, budget, avoid = _WHISPER_TABLE.get(
        state, ("", "none", 0.75, [])
    )
    if not whisper:
        return {"emit": False, "whisper": "", "pacing": pacing,
                "load_budget": budget, "avoid": avoid}

    # Care states require sustained evidence before they surface at all
    if state in ("depletion", "friction", "disengagement"):
        if confidence < ESCALATE_CONFIDENCE or sustained < ESCALATE_SUSTAIN:
            return {"emit": False, "whisper": "", "pacing": "none",
                    "load_budget": 0.75, "avoid": []}

    # Novelty suppression — don't repeat yourself
    h = hashlib.sha1(whisper.encode()).hexdigest()[:12]
    if h in session.whisper_ring:
        return {"emit": False, "whisper": "", "pacing": pacing,
                "load_budget": budget, "avoid": avoid, "_suppressed": True}
    session.whisper_ring.append(h)

    return {"emit": True, "whisper": whisper, "pacing": pacing,
            "load_budget": budget, "avoid": avoid}




# ── Commitment ───────────────────────────────────────────────────────────────
#
# Every other mechanism in this engine withholds. Confidence floors, maturity
# gates, withheld conclusions, anomaly widening, falsification watches — all of
# them are brakes. A system built only of brakes never moves.
#
# Reading people is irreducibly uncertain. It does not converge; more evidence
# narrows the range but never closes it, because the thing being measured is
# genuinely variable. So waiting for certainty is waiting for something that
# will not arrive, and perpetual suspension is not humility — it is a quieter
# way of failing someone. If a person is spent and the system says nothing for
# twelve turns because it is not sure, it did not protect them. It abandoned
# them carefully.
#
# At some point you commit. The question is not whether but WHEN, and the answer
# is not a fixed number of turns:
#
#   COMMIT EARLY when the action is cheap to undo.
#   HOLD LONGER when it is not.
#
# Reversibility governs the threshold. A quiet whisper costs almost nothing to
# be wrong about, so it should fire on modest evidence. Escalating to a care
# intervention is hard to walk back and treats an adult as fragile, so it should
# require more. This also makes WAITING carry a price rather than being a free
# default, which is what stops the brakes from winning by inertia.
#
# Committing is not concluding. The watch stays live. Being wrong remains
# permitted and expected — commitment simply means acting on the best available
# reading while it is still the best available reading.

HOLD_LIMIT = 6   # absolute ceiling on deliberation, regardless of confidence

# How hard is this action to walk back? Drives the evidence required.
_ACTION_REVERSIBILITY = {
    "none":       1.00,   # saying nothing — perfectly reversible
    "match":      0.95,   # mirroring their register
    "hold":       0.90,
    "guard":      0.75,   # flagging an irreversible step — mild interruption
    "step_back":  0.65,   # suggesting a different approach
    "slow_down":  0.45,   # implies they cannot handle the current pace
}

def _evidence_required(pacing: str) -> float:
    """Less reversible actions demand more evidence before committing."""
    rev = _ACTION_REVERSIBILITY.get(pacing, 0.7)
    return round(0.30 + (1.0 - rev) * 0.75, 3)


def decide_commitment(*, confidence: float, pacing: str, held_turns: int,
                      state: str, withheld: bool) -> Dict[str, Any]:
    """
    Resolve deliberation into action. Returns the commitment record.

    Three ways to commit:
      1. Evidence clears the bar for this action's reversibility — normal case.
      2. The hold limit is reached — forced. Deliberating longer costs more than
         acting on an imperfect reading.
      3. Never: the action is expensive and the evidence has not arrived.
    """
    required = _evidence_required(pacing)
    cost_of_waiting = round(min(1.0, held_turns / HOLD_LIMIT), 3)

    if confidence >= required and not withheld:
        return {
            "committed": True, "basis": "evidence",
            "confidence": confidence, "required": required,
            "reversibility": _ACTION_REVERSIBILITY.get(pacing, 0.7),
            "cost_of_waiting": cost_of_waiting, "still_watching": True,
            "statement": (
                f"Acting on '{state}'. Evidence {confidence:.2f} clears the "
                f"{required:.2f} needed for a '{pacing}' response. Watch stays live."
            ),
        }

    if held_turns >= HOLD_LIMIT:
        return {
            "committed": True, "basis": "forced",
            "confidence": confidence, "required": required,
            "reversibility": _ACTION_REVERSIBILITY.get(pacing, 0.7),
            "cost_of_waiting": 1.0, "still_watching": True,
            "statement": (
                f"Held '{state}' for {held_turns} turns without resolution. "
                f"Committing anyway at {confidence:.2f} confidence — this is a "
                f"decision under uncertainty, not a finding. Continuing to hold "
                f"would cost more than being wrong about a '{pacing}' response, "
                f"which is reversible. Watch stays live."
            ),
        }

    return {
        "committed": False, "basis": "insufficient",
        "confidence": confidence, "required": required,
        "reversibility": _ACTION_REVERSIBILITY.get(pacing, 0.7),
        "cost_of_waiting": cost_of_waiting, "still_watching": True,
        "statement": (
            f"Holding. '{pacing}' needs {required:.2f}, have {confidence:.2f}. "
            f"{HOLD_LIMIT - held_turns} turns before forced commitment."
        ),
    }

# ── The engine ───────────────────────────────────────────────────────────────

class AffectContextEngine:
    """
    Orchestrator. One instance serves many users; state is keyed per user
    and per session so baselines persist across sessions while session
    context does not bleed between them.
    """

    def __init__(self):
        self._baselines: Dict[str, PersonalBaseline] = {}
        self._priors:    Dict[str, PersonalPrior] = {}
        self._sessions:  Dict[str, SessionState] = {}

    # -- persistence hooks (wire to alex_memory) --
    def export_baseline(self, user_id: str) -> Dict[str, Any]:
        b = self._baselines.get(user_id)
        return b.to_dict() if b else {}

    def export_prior(self, user_id: str) -> Dict[str, Any]:
        pr = self._priors.get(user_id)
        if not pr:
            return {}
        return {"outcomes": pr.outcomes, "centroid": pr.centroid,
                "centroid_n": pr.centroid_n}

    def import_prior(self, user_id: str, data: Dict[str, Any]) -> None:
        if not data:
            return
        pr = PersonalPrior()
        pr.outcomes   = dict(data.get("outcomes", {}))
        pr.centroid   = dict(data.get("centroid", {}))
        pr.centroid_n = dict(data.get("centroid_n", {}))
        self._priors[user_id] = pr

    def import_baseline(self, user_id: str, data: Dict[str, Any]) -> None:
        if data:
            self._baselines[user_id] = PersonalBaseline.from_dict(data)

    # -- main entry point --
    def evaluate(
        self,
        text: str,
        user_id: str,
        session_id: str = "default",
        ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        now = ts if ts is not None else time.time()

        baseline = self._baselines.setdefault(user_id, PersonalBaseline())
        skey = f"{user_id}:{session_id}"
        sess = self._sessions.setdefault(skey, SessionState())

        latency = (now - sess.prev_ts) if sess.prev_ts else None

        # 1. Extract both channels
        feats = extract_features(text, sess.prev_text, latency)

        # 2. Personal z-scores (read BEFORE update — never score against self)
        raw = feats.affect_vector()
        z_unattenuated = baseline.z(raw)
        # Doubt attaches to the measurement when the person is unfamiliar.
        z = baseline.attenuate(z_unattenuated)

        # ── FOUNDATION FIRST ──────────────────────────────────────────────
        # Computed before anything is built on top of it, because everything
        # above inherits its quality. A confident conclusion resting on a
        # sparse baseline is the failure mode this ordering exists to prevent.
        health  = baseline_health(baseline, list(sess.z_window))
        # Sustained one-sided drift means their normal is genuinely changing —
        # a new project, a different working rhythm, a different life. The
        # correct response is to re-learn faster, not to keep measuring them
        # against who they used to be and calling the difference anomalous.
        if health["drift"] > 0.4 and health["stability"] > 0.5:
            baseline.alpha = min(0.15, baseline.alpha * 1.6)
        elif health["drift"] < 0.15 and baseline.alpha > BASELINE_ALPHA:
            baseline.alpha = max(BASELINE_ALPHA, baseline.alpha * 0.9)
        profile = build_operating_profile(baseline, list(sess.history))

        # 3. Context: integrated, slow
        continuity, novelty = sess.continuity_and_novelty(feats.content_tokens)
        frame, frame_conf   = _infer_frame(feats, continuity, novelty, z)
        stakes = min(1.0, feats.irreversibility * 3.0 + feats.is_imperative * 0.2)

        # 4. Affect: differentiated, fast
        vol = 0.0
        if len(sess.z_window) >= 2:
            keys = set().union(*(set(d) for d in sess.z_window))
            n_dim = max(len(keys), 1)
            deltas, prev = [], None
            for zz in sess.z_window:
                if prev is not None:
                    # RMS per dimension, not raw euclidean — otherwise volatility
                    # scales with feature count and explodes
                    deltas.append(math.sqrt(sum(
                        (zz.get(k, 0.0) - prev.get(k, 0.0)) ** 2 for k in keys
                    ) / n_dim))
                prev = zz
            vol = (sum(deltas) / len(deltas)) if deltas else 0.0
            vol = min(Z_CLAMP, vol)
        axes = _affect_axes(z, vol)

        # 5. Interaction: gated product
        investment = sess.topic_investment(feats.content_tokens)
        ranked = _match_signatures(axes, feats, continuity, novelty, z, investment)
        top_state, top_score = ranked[0]
        runner_state, runner_score = ranked[1] if len(ranked) > 1 else ("steady", 0.0)

        maturity  = baseline.maturity
        agreement = _agreement(z, top_score, runner_score)
        # The chain: baseline quality -> maturity -> feature agreement.
        # Weakest link caps the result. This is the guard against a single bad
        # measurement propagating into a confident chain of wrong decisions.
        confidence = propagate(health["quality"], maturity, agreement)

        # 6. Hysteresis + switch margin.
        #    Two guards, both needed:
        #      (a) a new state must BEAT the incumbent by SWITCH_MARGIN, not merely tie
        #      (b) entering a care state additionally requires confidence
        #    Without (a) the reading flaps between adjacent signatures on noise.
        care = {"friction", "depletion", "disengagement"}
        if top_state == sess.last_state:
            sess.sustained += 1
        else:
            incumbent_score = dict(ranked).get(sess.last_state, 0.0)
            beats_incumbent = (top_score - incumbent_score) >= SWITCH_MARGIN
            gate_ok = True
            if top_state in care and sess.last_state not in care:
                # Two independent gates. Confidence says "the signal is clear."
                # Maturity says "and I actually know this person's normal."
                # A terse person on turn 5 is not depleted; they are terse.
                gate_ok = (confidence >= ESCALATE_CONFIDENCE
                           and maturity >= MIN_MATURITY_FOR_CARE)

            if beats_incumbent and gate_ok:
                sess.sustained = 1
            else:
                # hold the incumbent; it has not been displaced
                if sess.last_state != "observing":
                    top_state = sess.last_state
                    top_score = incumbent_score
                    sess.sustained += 1
                else:
                    sess.sustained = 1

        # 6b. Cold-start guard. Care states are unavailable until the baseline
        #     is mature enough to know what this person's normal actually is.
        #     A terse person on turn 5 is terse, not depleted. This is the
        #     single most important anti-pathologising rule in the engine.
        if top_state in care and maturity < MIN_MATURITY_FOR_CARE:
            top_state = "steady" if confidence >= CONFIDENCE_FLOOR else "observing"
            sess.sustained = 1

        # 7. Confidence floor → observing, emit nothing
        decayed = False
        if confidence < CONFIDENCE_FLOOR:
            top_state = "observing"
            if sess.last_confidence > 0:
                confidence = round(sess.last_confidence * CONFIDENCE_DECAY, 3)
                decayed = True

        # Antecedent: diagnosed from the window BEFORE this turn. Only meaningful
        # for care states, and only computed on entry or while sustained.
        # ── Falsification check: does THIS turn break the held conclusion? ──
        # Runs before anything else, because a conclusion that has just been
        # falsified must not be allowed to drive one more turn of response.
        revision = None
        if sess.watch is not None:
            probe = {
                "arousal_z":   axes["arousal_z"],
                "len_z":       z.get("msg_length", 0.0),
                "latency_z":   z.get("latency", 0.0),
                "novelty":     novelty,
                "investment":  investment,
                "is_question": feats.is_question,
                "self_blame":  feats.self_blame,
                "temporal":    feats.temporal,
                "help_seek":   feats.help_seeking,
                "repetition":  z.get("repetition", 0.0),
            }
            if check_falsifier(sess.watch, probe):
                w = sess.watch
                revision = {
                    "overturned":   w.cause,
                    "revised_to":   w.revises_to,
                    "held_for":     sess.turn_index - w.registered_at,
                    "broke_on":     w.load_bearing,
                    "because":      w.because,
                    "statement": (
                        f"Read this as '{w.cause}' for "
                        f"{sess.turn_index - w.registered_at} turns. That was wrong. "
                        f"{w.because} Revising to '{w.revises_to}'."
                    ),
                }
                sess.revisions.append(revision)
                self._priors.setdefault(user_id, PersonalPrior()) \
                    .record_outcome(w.cause, w.revises_to)
                # Force the revision through — do not merely note it
                if sess.latched_antecedent:
                    sess.latched_antecedent["cause"] = w.revises_to
                    sess.latched_antecedent["revised"] = True
                sess.watch = derive_falsifier(w.revises_to, sess.turn_index)

        # ── The observer as a possible cause ──────────────────────────────
        # If several probes were recently spent and landed badly, the most
        # probable antecedent is not something in this person's life. It is us.
        # A model that cannot consider itself as the cause of the state it is
        # observing will confidently misattribute its own damage to the person.
        self_inflicted = None
        recent_bad = [pr for pr in sess.probes[-3:]
                      if pr.get("outcome") in ("irritated", "ignored")]
        if len(recent_bad) >= 2 and top_state in care:
            self_inflicted = {
                "cause": "observer_induced",
                "spent_probes": len(sess.probes),
                "recent_outcomes": [pr.get("outcome") for pr in sess.probes[-3:]],
                "note": ("Two or more recent probes landed badly. Before "
                         "attributing this state to the user, consider that we "
                         "produced it. Stop probing; the correct move is to get "
                         "out of the way."),
            }

        antecedent = {"cause": "unknown", "confidence": 0.0,
                      "window_turns": 0, "evidence": [], "trajectory": "unknown"}
        if top_state in care:
            if sess.latched_antecedent is None:
                fresh = diagnose_antecedent(
                    list(sess.history),
                    session_peak_arousal=sess.peak_arousal_this_session,
                    turns_since_peak=sess.turn_index - sess.peak_arousal_turn,
                )
                # Latch ONLY a confident read. A low-confidence care blip early
                # in a session must not freeze a garbage antecedent for the rest
                # of the episode — keep re-reading until the evidence is real.
                if fresh["confidence"] >= 0.45:
                    fresh["latched_at_turn"] = sess.turn_index
                    prior = self._priors.setdefault(user_id, PersonalPrior())
                    fresh["prior"] = build_prior_note(prior, fresh["cause"], z)
                    prior.record_conclusion(fresh["cause"], z)

                    # A familiar pattern behaving unusually is a reason to be LESS
                    # certain, not more. Nine prior sightings are what make the
                    # tenth legible as an exception.
                    if fresh["prior"].get("widens_uncertainty"):
                        fresh["confidence"] = round(fresh["confidence"] * 0.65, 3)
                        fresh["conclusion_withheld"] = True
                        fresh["withheld_reason"] = (
                            fresh.get("withheld_reason", "") + " " +
                            fresh["prior"]["note"]).strip()

                    sess.latched_antecedent = fresh
                    sess.watch = derive_falsifier(fresh["cause"], sess.turn_index)
                antecedent = fresh
            else:
                antecedent = dict(sess.latched_antecedent)
        else:
            # Episode ended without falsification: the conclusion held. Record
            # that as a confirmation so the prior learns from successes too.
            if sess.latched_antecedent and not sess.latched_antecedent.get("revised"):
                self._priors.setdefault(user_id, PersonalPrior()) \
                    .record_outcome(sess.latched_antecedent["cause"], None)
            sess.latched_antecedent = None   # episode over — release the latch
            sess.watch = None

        if antecedent.get("conclusion_withheld") or top_state == "observing":
            sess.held_turns += 1
        else:
            sess.held_turns = 0

        # A withheld conclusion must not mean indefinite silence. If we are not
        # committing, probe: act on the cheapest legible hypothesis to generate
        # the evidence that waiting will not produce.
        # ── Settle the last probe before considering another ──────────────
        # A probe that produced a correction did its job and is partly refunded.
        # A probe that produced irritation costs extra. This is how the budget
        # tracks the person in front of you rather than a fixed allowance.
        probe_outcome = None
        if sess.pending_probe is not None:
            pp = sess.pending_probe
            informative = (feats.is_question > 0 or feats.contrast_marker > 0
                           or z.get("msg_length", 0.0) > 0.8)
            irritated = (z.get("profanity", 0.0) > 1.2
                         or feats.negation_density > 0.15
                         or (z.get("msg_length", 0.0) < -1.2
                             and z.get("latency", 0.0) < -0.5))
            if irritated:
                sess.probe_budget -= IRRITATION_SURCHARGE
                probe_outcome = "irritated"
            elif informative:
                sess.probe_budget += PROBE_REFUND
                probe_outcome = "informative"
            else:
                probe_outcome = "ignored"
            pp["outcome"] = probe_outcome
            sess.probes.append(pp)
            sess.pending_probe = None

        probe = None
        if antecedent.get("conclusion_withheld") or antecedent.get("confidence", 0) < 0.6:
            if sess.probe_budget >= 1.0:
                probe = select_probe(antecedent.get("hypotheses", []), sess.sustained)
            if probe:
                sess.probe_budget -= 1.0
                sess.pending_probe = {"cause": probe["probe_cause"],
                                      "turn": sess.turn_index}
                antecedent["probe"] = probe
                antecedent["mode"] = "probe"
            else:
                antecedent["mode"] = ("out_of_patience" if sess.probe_budget < 1.0
                                      else "hold")
        elif antecedent.get("cause") != "unknown":
            antecedent["mode"] = "commit"

        steerage = _build_steerage(top_state, confidence, sess.sustained, sess)
        # Every note carries its own surfacing contract. Behaviour changes;
        # the reading is never spoken.
        if steerage.get("whisper"):
            steerage["surfacing"] = surfacing_guard(steerage["whisper"])

        # A probe FORCES emission. This is the one place the engine overrides
        # its own brakes, and it has to be — every other mechanism withholds, so
        # without this the system can hold a conclusion indefinitely and call
        # that caution. Silence is a valid output when there is nothing to say;
        # it is not valid as a way of never having to be wrong.
        if probe:
            h = hashlib.sha1(probe["action"].encode()).hexdigest()[:12]
            if h not in sess.whisper_ring:
                sess.whisper_ring.append(h)
                steerage["emit"] = True
        if probe and steerage.get("emit"):
            steerage["whisper"] = probe["action"]
            steerage["probe"]   = True
            steerage["if_wrong"] = probe["if_wrong"]

        # Deliberation must terminate. Commit or state why not.
        commitment = decide_commitment(
            confidence  = confidence,
            pacing      = steerage.get("pacing", "none"),
            held_turns  = sess.held_turns,
            state       = top_state,
            withheld    = bool(antecedent.get("conclusion_withheld")),
        )

        # A forced commitment overrides the brakes — that is its purpose. The
        # falsifier stays registered, so acting is still revisable.
        if commitment["committed"] and commitment["basis"] == "forced" \
                and not steerage.get("emit"):
            fallback = antecedent.get("convergent_action") or \
                       _WHISPER_TABLE.get(top_state, ("", "", 0.0, []))[0]
            if fallback:
                steerage["emit"]    = True
                steerage["whisper"] = fallback
                steerage["forced"]  = True
            sess.held_turns = 0

        # Cause-specific steerage overrides the generic state whisper. The state
        # says what is happening; the antecedent says what to do about it, and
        # that is the more actionable of the two.
        if steerage.get("emit") and antecedent["cause"] != "unknown" \
                and antecedent["confidence"] >= 0.35 \
                and not antecedent.get("conclusion_withheld"):
            cause_w, cause_avoid = _ANTECEDENT_STEERAGE.get(
                antecedent["cause"], ("", []))
            if cause_w:
                steerage["whisper"] = cause_w
                steerage["avoid"]   = cause_avoid
                steerage["cause"]   = antecedent["cause"]
        suppressed = steerage.pop("_suppressed", False)

        # 8. Fold this turn into memory (AFTER scoring)
        baseline.update(raw)
        sess.history.append({
            "latency_z":   z.get("latency", 0.0),
            "len_z":       z.get("msg_length", 0.0),
            "repetition":  z.get("repetition", 0.0),
            "load_z":      axes["load_z"],
            "arousal_z":   axes["arousal_z"],
            "novelty":     novelty,
            "investment":  investment,
            "temporal":    feats.temporal,
            "self_blame":  feats.self_blame,
            "help_seek":   feats.help_seeking,
            "is_question": feats.is_question,
        })
        sess.topic_window.append(frozenset(feats.content_tokens))
        sess.z_window.append(z)

        # Uncapped session-scale peak — never evicts, unlike sess.history above.
        if axes["arousal_z"] > sess.peak_arousal_this_session:
            sess.peak_arousal_this_session = axes["arousal_z"]
            sess.peak_arousal_turn = sess.turn_index
            sess.peak_arousal_ts = now

        sess.prev_text = text
        sess.prev_ts = now
        sess.last_state = top_state
        sess.last_confidence = confidence
        sess.turn_index += 1

        drivers = sorted(
            ({"feature": k, "z": round(v, 2)} for k, v in z.items() if abs(v) > 0.5),
            key=lambda d: abs(d["z"]), reverse=True,
        )[:4]

        _perf = performance_read(
            axes, feats,
            {"stakes": round(stakes, 3), "investment": round(investment, 3)},
            {"state": top_state}, sess.sustained, text, sess.prior_tension)
        sess.prior_tension = _perf["tension"]

        return {
            "v": SCHEMA_VERSION,
            "turn_id": f"t_{int(now)}_{hashlib.sha1((text or '').encode()).hexdigest()[:4]}",
            "user_id": user_id,
            "session_id": session_id,
            "ts": round(now, 2),
            "context": {
                "frame": frame,
                "frame_conf": round(frame_conf, 3),
                "stakes": round(stakes, 3),
                "continuity": round(continuity, 3),
                "novelty": round(novelty, 3),
                "investment": round(investment, 3),
                "turn_index": sess.turn_index,
            },
            "affect": {**axes, "drivers": drivers},
            "reading": {
                "state": top_state,
                # 'steady' is an observation, not an absence. When nothing is
                # deviating, the useful information is how this person normally
                # operates — that is what a character needs most of the time.
                "operating_profile": profile.to_dict() if profile else None,
                "meet_them_at": profile.meet_them_at() if profile else
                                "Not enough history yet — answer plainly and watch.",
                "confidence": confidence,
                "sustained_turns": sess.sustained,
                "alternatives": [{"state": runner_state, "score": runner_score}],
            },
            "baseline": health,
            "performance": _perf,
            "antecedent": {
                **antecedent,
                "falsifier": sess.watch.to_dict() if sess.watch else None,
                "revision": revision,
                "revisions_this_session": len(sess.revisions),
                "probe_budget": round(sess.probe_budget, 2),
                "probes_spent": len(sess.probes),
                "last_probe_outcome": probe_outcome,
                "self_inflicted": self_inflicted,
            },
            "steerage": steerage,
            "commitment": commitment,
            "meta": {
                # Where the uncertainty currently lives. With an unfamiliar
                # person it sits on the baseline; with a familiar one it moves
                # to the individual instance. It is never absent.
                "doubt_attaches_to": (
                    "baseline"  if maturity < 0.6 else
                    "instance"  if antecedent.get("prior", {}).get("anomaly", 0) >= 0.35
                    else "conclusion"
                ),
                "feature_reliability": baseline.feature_reliability(),
                "baseline_maturity": round(maturity, 3),
                "agreement": agreement,
                "decayed": decayed,
                "suppressed_repeat": suppressed,
            },
        }

    # -- legacy bridge --
    @staticmethod
    def to_legacy_battery(payload: Dict[str, Any]) -> Optional[str]:
        """
        Map to UserBattery for alex_core.py. Returns None for 'observing'
        so low-confidence readings NEVER overwrite existing legacy state.
        """
        state = payload["reading"]["state"]
        if state == "observing":
            return None
        sustained = payload["reading"]["sustained_turns"]
        load = payload["affect"]["load_z"]
        if state in ("flow", "play"):
            return "charged"
        if state == "steady":
            return "medium" if load > 1.0 else "charged"
        if state == "friction":
            return "medium"
        if state == "depletion":
            return "depleted" if sustained >= 4 else "low"
        if state == "disengagement":
            # Speed is high but reserves are gone. The legacy enum has no cell
            # for "fast and empty", which is precisely why it was replaced.
            return "low"
        return None


# ── Demo ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    engine = AffectContextEngine()

    script = [
        # Establish a baseline — this person writes tersely, uses profanity casually
        ("ok lets wire the bridge", 0),
        ("yeah run it", 4),
        ("fine. next", 3),
        ("do the thing with the sync", 5),
        ("ok", 2),
        ("k run it again", 4),
        ("still fine", 3),
        ("next piece", 4),
        ("wire the stt endpoint", 6),
        ("ok good", 3),
        ("do tts now", 4),
        ("yep", 2),
        # FLOW — expanding, novel, energetic
        ("ok this is working, now lets add the voice cloning layer and wire "
         "prosody into the tts params so emotional state drives delivery speed", 8),
        ("and then the whisper can modulate breath and pacing per character", 6),
        ("we could route jeremy through a separate voice profile entirely", 5),
        # FRICTION — circling, contracting, repeating
        ("the bridge still isnt connecting", 12),
        ("bridge not connecting", 8),
        ("why is the bridge not connecting", 6),
        ("bridge. not. connecting.", 5),
        # DEPLETION — low energy, fragmenting, hedged
        ("i guess maybe we should stop", 40),
        ("dunno. tired", 60),
    ]

    print(f"{'turn':>4}  {'state':<12} {'conf':>5}  {'frame':<12} "
          f"{'nov':>5} {'cont':>5}  whisper")
    print("-" * 100)
    t0 = time.time()
    clock = t0
    for i, (msg, gap) in enumerate(script):
        clock += gap
        p = engine.evaluate(msg, user_id="josie", session_id="demo", ts=clock)
        r, c, s = p["reading"], p["context"], p["steerage"]
        w = s["whisper"][:44] if s["emit"] else ("—" if not p["meta"]["suppressed_repeat"] else "(suppressed)")
        print(f"{i:>4}  {r['state']:<12} {r['confidence']:>5.2f}  {c['frame']:<12} "
              f"{c['novelty']:>5.2f} {c['continuity']:>5.2f}  {w}")

    print()
    print("Final payload:")
    print(json.dumps(p, indent=2)[:900])
