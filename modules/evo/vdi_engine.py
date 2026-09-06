"""
modules/vdi_engine.py — Viewer Dynamics Index (VDI) Engine
===========================================================
Copyright (c) 2024-2025 Rear View Foresight LLC
"Feic Mo Chroí — See My Heart"

The VDI measures the real-time emotional and attentional state of the
audience and maps it to a voice mode. This is the Kennedy mechanism:
the audience state drives the performer's register.

Four VoiceModes:
    CONTENT_CLEAR    — Audience is thinking. Support the thinking.
    MIXED            — Audience is transitioning. Open the dynamic range.
    VOICE_DOMINANT   — Emotion over information. The crack is permitted.
    IDENTITY         — Intimacy register. Not performing — present.

The VDI score [0.0–1.0] is a continuous value:
    0.0–0.30  → CONTENT_CLEAR
    0.30–0.55 → MIXED
    0.55–0.80 → VOICE_DOMINANT
    0.80–1.0  → IDENTITY

Public API:
    VDIEngine
        .update(signals: VDISignals) -> VDIReport
        .get_current_report() -> VDIReport

    VDIReport
        .vdi_score: float
        .voice_mode: VoiceMode
        .dominant_signal: str
        .confidence: float
        .timestamp: float
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# VOICE MODE
# ─────────────────────────────────────────────────────────────────────────────

class VoiceMode(str, Enum):
    CONTENT_CLEAR  = "content_clear"
    MIXED          = "mixed"
    VOICE_DOMINANT = "voice_dominant"
    IDENTITY       = "identity"


# ─────────────────────────────────────────────────────────────────────────────
# VDI SIGNALS — inputs from all sensing systems
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VDISignals:
    """
    All real-time signals that feed the VDI calculation.
    Sources: mocap, DeepFace, audio analysis, session state.
    All values [0.0–1.0] unless noted.
    """
    # ── Audience face signals (from DeepFace / camera analysis) ──────────────
    audience_engagement:    float = 0.5   # Forward lean, eye contact, open posture
    audience_valence:       float = 0.5   # Positive/negative emotional state
    audience_arousal:       float = 0.5   # Calm/activated
    audience_attention:     float = 0.5   # Fixation, reduced blink rate
    smile_intensity:        float = 0.0   # Genuine Duchenne smile score
    frown_intensity:        float = 0.0   # Brow furrow, concern
    surprise_intensity:     float = 0.0   # Eyebrow raise, mouth open
    confusion_intensity:    float = 0.0   # Head tilt, squint

    # ── Audio signals (from room microphones / stream analysis) ──────────────
    audience_silence:       float = 0.5   # 1.0 = total silence (intense attention)
    laughter_detected:      float = 0.0   # Laughter energy
    murmur_detected:        float = 0.0   # Low conversation energy
    applause_detected:      float = 0.0   # Applause energy

    # ── Session signals ───────────────────────────────────────────────────────
    time_in_segment:        float = 0.0   # Seconds in current segment
    topic_emotional_weight: float = 0.5   # Pre-assigned weight for current topic
    call_to_action_pending: bool  = False # Is a CTA moment approaching?

    # ── Performer signals (from mocap) ────────────────────────────────────────
    performer_arousal:      float = 0.5
    performer_valence:      float = 0.5
    performer_forward_lean: float = 0.0
    performer_tension:      float = 0.3

    # ── Meta ──────────────────────────────────────────────────────────────────
    timestamp: float = field(default_factory=time.time)


# ─────────────────────────────────────────────────────────────────────────────
# VDI REPORT — output of one VDI calculation cycle
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VDIReport:
    """
    Output of a VDI calculation cycle.
    Consumed by: ProsodyEngine, SwitchbladeGovernor, AvatarRenderer.
    """
    vdi_score:        float     = 0.5
    voice_mode:       VoiceMode = VoiceMode.MIXED
    dominant_signal:  str       = "baseline"
    confidence:       float     = 1.0

    # Component scores (for debugging / Switchblade)
    audience_score:   float     = 0.5
    audio_score:      float     = 0.5
    session_score:    float     = 0.5
    performer_score:  float     = 0.5

    # Render hints for EVO Switchblade
    render_intensity: float     = 0.5   # 0=minimal, 1=maximum fidelity
    identity_moment:  bool      = False # True = pour everything into this shot
    silence_pressure: float     = 0.0   # Dramatic silence score for Jeremy Cricket

    timestamp:        float     = field(default_factory=time.time)

    def to_switchblade_vector(self) -> dict:
        """
        Emit a compact priority vector for the Switchblade Governor.
        No English. Just numbers.
        """
        return {
            "vdi":        round(self.vdi_score, 3),
            "mode":       self.voice_mode.value,
            "render":     round(self.render_intensity, 3),
            "identity":   int(self.identity_moment),
            "silence_p":  round(self.silence_pressure, 3),
            "audience":   round(self.audience_score, 3),
            "performer":  round(self.performer_score, 3),
            "ts":         self.timestamp,
        }


# ─────────────────────────────────────────────────────────────────────────────
# VDI ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class VDIEngine:
    """
    Calculates the Viewer Dynamics Index from incoming signals.

    Uses a weighted multi-signal fusion approach:
    - Audience engagement signals: 40%
    - Audio/room signals: 25%
    - Session/context signals: 20%
    - Performer state signals: 15%

    Applies temporal smoothing to prevent rapid mode oscillation.
    """

    def __init__(
        self,
        smoothing_window: int = 5,
        mode_hysteresis:  float = 0.05,
    ):
        self.smoothing_window = smoothing_window
        self.mode_hysteresis  = mode_hysteresis

        self._score_history:   List[float]    = []
        self._current_report:  Optional[VDIReport] = None
        self._current_mode:    VoiceMode      = VoiceMode.MIXED
        self._last_mode_score: float          = 0.5

    # ── Public API ────────────────────────────────────────────────────────────

    def update(self, signals: VDISignals) -> VDIReport:
        """
        Consume new signals, calculate VDI, return report.
        Call this every frame or on every significant signal update.
        """
        audience_score  = self._calc_audience_score(signals)
        audio_score     = self._calc_audio_score(signals)
        session_score   = self._calc_session_score(signals)
        performer_score = self._calc_performer_score(signals)

        # Weighted fusion
        raw_score = (
            audience_score  * 0.40 +
            audio_score     * 0.25 +
            session_score   * 0.20 +
            performer_score * 0.15
        )

        # Temporal smoothing
        self._score_history.append(raw_score)
        if len(self._score_history) > self.smoothing_window:
            self._score_history.pop(0)
        smoothed = sum(self._score_history) / len(self._score_history)

        # Mode mapping with hysteresis
        mode = self._map_score_to_mode(smoothed)

        # Dominant signal identification
        component_scores = {
            "audience":  audience_score,
            "audio":     audio_score,
            "session":   session_score,
            "performer": performer_score,
        }
        dominant = max(component_scores, key=lambda k: abs(component_scores[k] - 0.5))

        # Render intensity: identity moments get 1.0, content_clear gets 0.3
        render_intensity = self._calc_render_intensity(mode, smoothed, signals)

        # Silence pressure for Jeremy Cricket
        silence_pressure = self._calc_silence_pressure(signals)

        report = VDIReport(
            vdi_score        = round(smoothed, 4),
            voice_mode       = mode,
            dominant_signal  = dominant,
            confidence       = min(1.0, len(self._score_history) / self.smoothing_window),
            audience_score   = round(audience_score, 4),
            audio_score      = round(audio_score, 4),
            session_score    = round(session_score, 4),
            performer_score  = round(performer_score, 4),
            render_intensity = round(render_intensity, 4),
            identity_moment  = (mode == VoiceMode.IDENTITY),
            silence_pressure = round(silence_pressure, 4),
            timestamp        = signals.timestamp,
        )

        self._current_report = report
        self._current_mode   = mode
        return report

    def get_current_report(self) -> Optional[VDIReport]:
        """Return the most recent VDI report without recalculating."""
        return self._current_report

    # ── Score calculators ─────────────────────────────────────────────────────

    def _calc_audience_score(self, s: VDISignals) -> float:
        """
        Audience face + body signals.
        High engagement + positive valence + attention → higher VDI.
        Confusion → pulls toward CONTENT_CLEAR (lower VDI).
        """
        base = (
            s.audience_engagement * 0.30 +
            s.audience_arousal    * 0.20 +
            s.audience_attention  * 0.25 +
            s.audience_valence    * 0.15 +
            s.smile_intensity     * 0.10
        )
        # Confusion pulls down — audience needs clarity
        base -= s.confusion_intensity * 0.20
        # Surprise pushes toward voice dominant
        base += s.surprise_intensity * 0.10
        return float(max(0.0, min(1.0, base)))

    def _calc_audio_score(self, s: VDISignals) -> float:
        """
        Room audio signals.
        Deep silence = high attention = push toward IDENTITY.
        Laughter = high energy = VOICE_DOMINANT.
        Murmur = distraction = pull toward CONTENT_CLEAR.
        """
        score = s.audience_silence * 0.50  # Silence is the strongest signal
        score += s.laughter_detected  * 0.30
        score += s.applause_detected  * 0.20
        score -= s.murmur_detected    * 0.25  # Murmur = losing them
        return float(max(0.0, min(1.0, score)))

    def _calc_session_score(self, s: VDISignals) -> float:
        """
        Context and session state.
        Emotional topic weight + CTA pressure.
        """
        score = s.topic_emotional_weight * 0.70
        if s.call_to_action_pending:
            score += 0.20  # CTA approaching = push toward presence
        # Fatigue: very long segments slightly reduce engagement ceiling
        fatigue = min(0.15, s.time_in_segment / 600.0)  # Max after 10 min
        score -= fatigue
        return float(max(0.0, min(1.0, score)))

    def _calc_performer_score(self, s: VDISignals) -> float:
        """
        Performer's own state feeds back into the VDI.
        A performer who is activated and leaning in naturally elevates the room.
        """
        score = (
            s.performer_arousal      * 0.40 +
            s.performer_valence      * 0.30 +
            s.performer_forward_lean * 0.20
        )
        score -= s.performer_tension * 0.10
        return float(max(0.0, min(1.0, score)))

    # ── Mode mapping ──────────────────────────────────────────────────────────

    def _map_score_to_mode(self, score: float) -> VoiceMode:
        """
        Map VDI score to VoiceMode with hysteresis to prevent oscillation.
        """
        # Hysteresis: only change mode if we've moved meaningfully past threshold
        h = self.mode_hysteresis

        if score >= (0.80 - h):
            return VoiceMode.IDENTITY
        elif score >= (0.55 - h):
            # Only enter VOICE_DOMINANT from below if score is clearly past threshold
            if self._current_mode == VoiceMode.MIXED and score < (0.55 + h):
                return VoiceMode.MIXED
            return VoiceMode.VOICE_DOMINANT
        elif score >= (0.30 - h):
            if self._current_mode == VoiceMode.CONTENT_CLEAR and score < (0.30 + h):
                return VoiceMode.CONTENT_CLEAR
            return VoiceMode.MIXED
        else:
            return VoiceMode.CONTENT_CLEAR

    def _calc_render_intensity(
        self,
        mode: VoiceMode,
        score: float,
        signals: VDISignals
    ) -> float:
        """
        Calculate render intensity hint for the EVO Switchblade.
        IDENTITY moments get maximum fidelity.
        CONTENT_CLEAR gets minimal — audience is thinking, not watching.
        """
        base_intensity = {
            VoiceMode.IDENTITY:       0.95,
            VoiceMode.VOICE_DOMINANT: 0.75,
            VoiceMode.MIXED:          0.55,
            VoiceMode.CONTENT_CLEAR:  0.30,
        }[mode]

        # Performer forward lean boosts render intensity (they're committing)
        lean_boost = signals.performer_forward_lean * 0.10
        # Silence pressure boosts it (something important is about to happen)
        silence_boost = min(0.10, signals.audience_silence * 0.15)

        return min(1.0, base_intensity + lean_boost + silence_boost)

    def _calc_silence_pressure(self, signals: VDISignals) -> float:
        """
        Calculate dramatic silence pressure for Jeremy Cricket.
        High silence + high audience arousal = something important is happening.
        """
        return float(min(1.0,
            signals.audience_silence * 0.60 +
            signals.audience_arousal * 0.40
        ))
