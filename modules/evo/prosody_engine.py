# PubCast AI — prosody_engine.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
modules/prosody_engine.py — Prosody Conditioning Engine
========================================================
Converts VDI score + performer emotional state into concrete
voice synthesis parameters and SSML markup instructions.

This is the Kennedy mechanism in code. The VDI tells us what state
the audience is in. The emotional state tells us what the performer
is feeling. Together they determine exactly how every sentence
should sound.

The four voice registers:

  CONTENT_CLEAR    — Clarity mode. Crisp consonants. Logical stress.
                     Pauses at argument boundaries. No performance.
                     The audience is thinking. Support the thinking.

  MIXED            — Prosody carries the argument structure.
                     Stress on logical connectors. Dynamic range opens.
                     Breath becomes deliberate.

  VOICE_DOMINANT   — Emotional truth over information delivery.
                     Dynamic range fully open. Breath audible.
                     Micro-pauses before important words.
                     The crack is permitted.
                     "You" over "everyone."

  IDENTITY         — Intimacy register. Late-night radio.
                     Slower. Warmer. Personal.
                     Proximity simulation. Direct address.
                     Not performing — present.

Public API:
    ProsodyEngine
        .get_synthesis_params(
            vdi_report: VDIReport,
            emotional_state: Optional[EmotionalState],
            text: str
        ) -> SynthesisParams

    SSMLBuilder
        .build(text: str, params: SynthesisParams) -> str
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .vdi_engine import VDIReport, VoiceMode


# ─────────────────────────────────────────────────────────────────────────────
# EMOTIONAL STATE INPUT (from mocap + face systems)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EmotionalState:
    """
    Emotional state of the performer, read from the mocap system.
    All values [0.0–1.0] unless noted.
    Consumed from DeepFaceExpressionOutput and BodyAttitude.
    """
    valence:            float = 0.5   # 0=negative, 1=positive
    arousal:            float = 0.5   # 0=calm, 1=activated
    dominance:          float = 0.5   # 0=overwhelmed, 1=in-control
    # Body signals
    breathing_rate_bpm: float = 15.0
    breathing_depth:    float = 0.3
    breathing_phase:    float = 0.0   # 0=inhale peak, 0.5=exhale peak
    tension_score:      float = 0.3
    forward_lean:       float = 0.0   # engagement
    # Expression signals
    expression_velocity: float = 0.0  # how fast face is moving
    micro_expression_active: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# SYNTHESIS PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SynthesisParams:
    """
    Complete parameter set for voice synthesis.
    These map directly to ElevenLabs, Cartesia, or Kokoro API parameters.
    Also used to generate SSML for providers that support it.
    """
    # ── Timing ───────────────────────────────────────────────────────────────
    speech_rate:         float = 1.00  # multiplier (0.7=slow, 1.3=fast)
    pause_before_key:    float = 0.25  # seconds of silence before key words
    pause_after_sentence: float = 0.4  # seconds after sentence end

    # ── Pitch ────────────────────────────────────────────────────────────────
    pitch_shift_st:      float = 0.0   # semitones from neutral (-3 to +3)
    pitch_range:         float = 0.6   # 0=monotone, 1=full range (expressiveness)
    sentence_final_drop: bool  = True  # drop pitch at sentence end (authority)

    # ── Dynamics ─────────────────────────────────────────────────────────────
    stability:           float = 0.65  # ElevenLabs stability (lower=more expressive)
    similarity_boost:    float = 0.80  # ElevenLabs voice consistency
    style_exaggeration:  float = 0.35  # ElevenLabs style (0=neutral, 1=exaggerated)

    # ── Breath ───────────────────────────────────────────────────────────────
    breath_mode:         str   = "minimal"  # minimal | structural | emotional | intimate
    breath_before_key:   bool  = False
    breath_audibility:   float = 0.0    # 0=silent, 1=audible breath sounds

    # ── Character ────────────────────────────────────────────────────────────
    crack_permission:    bool  = False  # allow emotional vocal breaks
    crack_probability:   float = 0.0   # chance of crack on vulnerable syllables
    proximity_sim:       bool  = False  # boost low-mids for intimacy
    direct_address:      bool  = False  # prefer "you" framing

    # ── Post-processing ──────────────────────────────────────────────────────
    warmth_boost_db:     float = 0.0   # shelf boost at 200Hz
    presence_boost_db:   float = 2.0   # EQ boost at 3kHz
    harmonic_exciter:    float = 0.0   # subtle harmonic saturation

    # ── SSML hints ───────────────────────────────────────────────────────────
    emphasis_words:      List[str] = field(default_factory=list)
    whisper_phrases:     List[str] = field(default_factory=list)

    # ── Metadata ─────────────────────────────────────────────────────────────
    voice_mode:          str   = "content_clear"
    vdi_at_generation:   float = 0.0
    timestamp:           float = field(default_factory=time.time)

    def to_elevenlabs(self) -> dict:
        """Convert to ElevenLabs API voice_settings format."""
        return {
            "stability":         round(self.stability, 3),
            "similarity_boost":  round(self.similarity_boost, 3),
            "style":             round(self.style_exaggeration, 3),
            "use_speaker_boost": self.proximity_sim,
        }

    def to_cartesia(self) -> dict:
        """Convert to Cartesia API parameters (speed + emotion)."""
        # Cartesia uses speed [-1,1] and emotion vector
        speed = (self.speech_rate - 1.0) * 2.0   # remap [0.5,1.5] → [-1,1]
        return {
            "speed":       round(max(-1.0, min(1.0, speed)), 3),
            "emotion":     self._cartesia_emotion(),
        }

    def _cartesia_emotion(self) -> list:
        """Build Cartesia emotion vector from params."""
        emotions = []
        if self.style_exaggeration > 0.5:
            emotions.append({"name": "positivity", "level": "medium"})
        if self.crack_permission:
            emotions.append({"name": "sadness", "level": "low"})
        if self.pitch_range > 0.7:
            emotions.append({"name": "curiosity", "level": "medium"})
        return emotions


# ─────────────────────────────────────────────────────────────────────────────
# PROSODY PARAMETER TABLES
# Per VoiceMode, baseline parameters before emotional state modulation.
# ─────────────────────────────────────────────────────────────────────────────

_BASE_PARAMS: Dict[VoiceMode, dict] = {
    VoiceMode.CONTENT_CLEAR: {
        "speech_rate":          1.00,
        "pause_before_key":     0.15,
        "pause_after_sentence": 0.50,
        "pitch_shift_st":       0.0,
        "pitch_range":          0.40,
        "sentence_final_drop":  True,
        "stability":            0.80,   # stable = clear = consistent
        "similarity_boost":     0.85,
        "style_exaggeration":   0.15,
        "breath_mode":          "minimal",
        "breath_before_key":    False,
        "breath_audibility":    0.0,
        "crack_permission":     False,
        "crack_probability":    0.0,
        "proximity_sim":        False,
        "direct_address":       False,
        "warmth_boost_db":      0.0,
        "presence_boost_db":    2.5,    # clarity in the mix
        "harmonic_exciter":     0.0,
    },
    VoiceMode.MIXED: {
        "speech_rate":          1.00,
        "pause_before_key":     0.20,
        "pause_after_sentence": 0.45,
        "pitch_shift_st":       0.0,
        "pitch_range":          0.55,
        "sentence_final_drop":  True,
        "stability":            0.70,
        "similarity_boost":     0.82,
        "style_exaggeration":   0.30,
        "breath_mode":          "structural",
        "breath_before_key":    True,
        "breath_audibility":    0.15,
        "crack_permission":     False,
        "crack_probability":    0.0,
        "proximity_sim":        False,
        "direct_address":       False,
        "warmth_boost_db":      0.5,
        "presence_boost_db":    2.0,
        "harmonic_exciter":     0.05,
    },
    VoiceMode.VOICE_DOMINANT: {
        "speech_rate":          0.95,   # slightly slower — give it weight
        "pause_before_key":     0.30,   # the pause before the payoff word
        "pause_after_sentence": 0.55,   # let it land
        "pitch_shift_st":       -0.5,   # slightly lower = gravitas
        "pitch_range":          0.75,
        "sentence_final_drop":  True,
        "stability":            0.55,   # less stable = more expressive
        "similarity_boost":     0.78,
        "style_exaggeration":   0.55,
        "breath_mode":          "emotional",
        "breath_before_key":    True,
        "breath_audibility":    0.35,
        "crack_permission":     True,
        "crack_probability":    0.15,
        "proximity_sim":        False,
        "direct_address":       True,   # "you" not "everyone"
        "warmth_boost_db":      1.0,
        "presence_boost_db":    1.5,
        "harmonic_exciter":     0.12,
    },
    VoiceMode.IDENTITY: {
        "speech_rate":          0.88,   # late night register — unhurried
        "pause_before_key":     0.35,
        "pause_after_sentence": 0.65,
        "pitch_shift_st":       -1.0,   # lower and warmer
        "pitch_range":          0.60,   # not performing — present
        "sentence_final_drop":  True,
        "stability":            0.50,   # maximum expression
        "similarity_boost":     0.75,
        "style_exaggeration":   0.45,
        "breath_mode":          "intimate",
        "breath_before_key":    True,
        "breath_audibility":    0.50,   # audible breathing = alive
        "crack_permission":     True,
        "crack_probability":    0.20,
        "proximity_sim":        True,   # close-mic simulation
        "direct_address":       True,
        "warmth_boost_db":      2.0,    # chest resonance
        "presence_boost_db":    1.0,
        "harmonic_exciter":     0.18,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# PROSODY ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class ProsodyEngine:
    """
    Converts VDI + emotional state into SynthesisParams.

    The base parameters come from the mode table above.
    The emotional state applies a continuous modulation on top.
    The text itself influences emphasis word selection.
    """

    # Emotional modulation ranges — how much the emotional state
    # can shift each parameter from the mode baseline.
    _EMOTIONAL_MODULATION = {
        "speech_rate":          (-0.15, +0.20),  # arousal pushes fast, dominance slows
        "pitch_shift_st":       (-1.0,  +1.5),   # valence lifts pitch
        "pitch_range":          (-0.10, +0.20),  # arousal opens range
        "stability":            (-0.20, +0.10),  # tension reduces stability
        "style_exaggeration":   (-0.10, +0.25),  # arousal + valence add style
        "breath_audibility":    (-0.05, +0.30),  # arousal makes breath audible
        "warmth_boost_db":      (-0.5,  +1.5),   # valence adds warmth
        "crack_probability":    (0.0,   +0.20),  # low dominance + high arousal = crack
    }

    def get_synthesis_params(
        self,
        vdi_report: VDIReport,
        emotional_state: Optional[EmotionalState] = None,
        text: str = "",
    ) -> SynthesisParams:
        """
        Main entry point. Returns fully-conditioned SynthesisParams.
        """
        mode = vdi_report.voice_mode
        base = dict(_BASE_PARAMS[mode])

        # Apply emotional modulation
        if emotional_state is not None:
            base = self._apply_emotional_modulation(base, emotional_state, vdi_report.vdi_score)

        # Extract emphasis words from text
        emphasis = self._extract_emphasis_words(text, mode)

        # Build params object
        params = SynthesisParams(
            speech_rate=          float(base["speech_rate"]),
            pause_before_key=     float(base["pause_before_key"]),
            pause_after_sentence= float(base["pause_after_sentence"]),
            pitch_shift_st=       float(base["pitch_shift_st"]),
            pitch_range=          float(base["pitch_range"]),
            sentence_final_drop=  bool(base["sentence_final_drop"]),
            stability=            float(base["stability"]),
            similarity_boost=     float(base["similarity_boost"]),
            style_exaggeration=   float(base["style_exaggeration"]),
            breath_mode=          str(base["breath_mode"]),
            breath_before_key=    bool(base["breath_before_key"]),
            breath_audibility=    float(base["breath_audibility"]),
            crack_permission=     bool(base["crack_permission"]),
            crack_probability=    float(base["crack_probability"]),
            proximity_sim=        bool(base["proximity_sim"]),
            direct_address=       bool(base["direct_address"]),
            warmth_boost_db=      float(base["warmth_boost_db"]),
            presence_boost_db=    float(base["presence_boost_db"]),
            harmonic_exciter=     float(base["harmonic_exciter"]),
            emphasis_words=       emphasis,
            voice_mode=           mode.value,
            vdi_at_generation=    vdi_report.vdi_score,
        )

        # Micro-expression override: if one just fired, spike expressiveness
        if emotional_state and emotional_state.micro_expression_active:
            params.stability = max(0.30, params.stability - 0.15)
            params.style_exaggeration = min(1.0, params.style_exaggeration + 0.15)
            params.crack_probability  = min(0.35, params.crack_probability + 0.10)

        return params

    def _apply_emotional_modulation(
        self,
        base: dict,
        es: EmotionalState,
        vdi: float,
    ) -> dict:
        """
        Modulate base params using the performer's emotional state.
        The strength of modulation scales with VDI — at low VDI,
        emotional state has less effect on synthesis (content dominates).
        """
        result = dict(base)
        modulation_strength = vdi  # emotional modulation follows VDI

        # Speech rate: arousal speeds up, dominance slows (control)
        rate_delta = (es.arousal - 0.5) * 0.30 + (0.5 - es.dominance) * 0.10
        rate_range = self._EMOTIONAL_MODULATION["speech_rate"]
        result["speech_rate"] = float(max(0.70, min(1.40,
            base["speech_rate"] + rate_delta * modulation_strength
        )))

        # Pitch: valence lifts, tension lowers
        pitch_delta = (es.valence - 0.5) * 1.5 - es.tension_score * 0.5
        result["pitch_shift_st"] = float(max(-3.0, min(3.0,
            base["pitch_shift_st"] + pitch_delta * modulation_strength
        )))

        # Pitch range: arousal opens range
        range_delta = (es.arousal - 0.5) * 0.20
        result["pitch_range"] = float(max(0.2, min(1.0,
            base["pitch_range"] + range_delta * modulation_strength
        )))

        # Stability: tension reduces it (less stable = more expressive/unpredictable)
        stab_delta = -es.tension_score * 0.20 - es.expression_velocity * 0.10
        result["stability"] = float(max(0.25, min(0.95,
            base["stability"] + stab_delta * modulation_strength
        )))

        # Style exaggeration: arousal + positive valence increase it
        style_delta = (es.arousal - 0.5) * 0.20 + (es.valence - 0.5) * 0.10
        result["style_exaggeration"] = float(max(0.0, min(1.0,
            base["style_exaggeration"] + style_delta * modulation_strength
        )))

        # Breath: breathing rate and depth condition audibility
        breath_from_rate = max(0.0, (es.breathing_rate_bpm - 12.0) / 20.0) * 0.25
        breath_from_depth = (es.breathing_depth - 0.3) * 0.30
        result["breath_audibility"] = float(max(0.0, min(0.80,
            base["breath_audibility"] + (breath_from_rate + breath_from_depth) * modulation_strength
        )))

        # Crack probability: low dominance + high arousal + not positive
        crack_delta = (0.5 - es.dominance) * (es.arousal) * (1.0 - es.valence) * 0.30
        result["crack_probability"] = float(max(0.0, min(0.40,
            base["crack_probability"] + crack_delta * modulation_strength
        )))

        # Warmth: positive valence + engagement (forward lean) adds warmth
        warmth_delta = (es.valence - 0.5) * 1.5 + es.forward_lean * 0.5
        result["warmth_boost_db"] = float(max(0.0, min(3.0,
            base["warmth_boost_db"] + warmth_delta * modulation_strength
        )))

        return result

    def _extract_emphasis_words(self, text: str, mode: VoiceMode) -> List[str]:
        """
        Identify words that should receive prosodic emphasis.
        Strategy differs by mode.
        """
        if not text:
            return []

        words = re.findall(r'\b[a-zA-Z]+\b', text)
        if not words:
            return []

        if mode in (VoiceMode.CONTENT_CLEAR, VoiceMode.MIXED):
            # Logical connectors and causal words get emphasis
            emphasis_seeds = {
                "because", "therefore", "however", "but", "not",
                "never", "always", "every", "only", "exactly",
                "first", "second", "finally", "most", "least",
            }
        else:
            # Emotional and personal words get emphasis
            emphasis_seeds = {
                "you", "your", "we", "us", "real", "truth", "feel",
                "know", "love", "believe", "need", "want", "heart",
                "never", "always", "only", "moment", "together",
            }

        return [w for w in words if w.lower() in emphasis_seeds]


# ─────────────────────────────────────────────────────────────────────────────
# SSML BUILDER
# ─────────────────────────────────────────────────────────────────────────────

class SSMLBuilder:
    """
    Converts text + SynthesisParams into SSML markup.
    Compatible with ElevenLabs SSML, Google TTS, and Amazon Polly.
    Gracefully degrades to plain text for providers that don't support SSML.
    """

    def build(self, text: str, params: SynthesisParams) -> str:
        """
        Generate SSML from text and params.
        Returns full SSML document string.
        """
        if not text.strip():
            return "<speak></speak>"

        # Process the text
        processed = self._apply_pauses(text, params)
        processed = self._apply_emphasis(processed, params)
        processed = self._apply_breath(processed, params)
        processed = self._apply_rate_and_pitch(processed, params)

        return f"<speak>{processed}</speak>"

    def _apply_pauses(self, text: str, params: SynthesisParams) -> str:
        """Insert strategic pauses at sentence boundaries and before key words."""
        # Sentence boundary pauses
        pause_ms = int(params.pause_after_sentence * 1000)
        text = re.sub(
            r'([.!?])\s+',
            lambda m: f'{m.group(1)}<break time="{pause_ms}ms"/> ',
            text
        )

        # Pre-key-word pauses (before emphasis words)
        if params.pause_before_key > 0.05 and params.emphasis_words:
            key_pause_ms = int(params.pause_before_key * 1000)
            for word in params.emphasis_words:
                # Case-insensitive replacement
                pattern = re.compile(r'\b(' + re.escape(word) + r')\b', re.IGNORECASE)
                text = pattern.sub(
                    f'<break time="{key_pause_ms}ms"/>\\1',
                    text,
                    count=1
                )

        return text

    def _apply_emphasis(self, text: str, params: SynthesisParams) -> str:
        """Wrap emphasis words in SSML emphasis tags."""
        if not params.emphasis_words:
            return text

        # Map pitch_range to SSML emphasis level
        if params.pitch_range > 0.7:
            level = "strong"
        elif params.pitch_range > 0.5:
            level = "moderate"
        else:
            level = "reduced"

        for word in params.emphasis_words[:5]:   # limit to 5 emphases per sentence
            pattern = re.compile(r'\b(' + re.escape(word) + r')\b', re.IGNORECASE)
            text = pattern.sub(f'<emphasis level="{level}">\\1</emphasis>', text, count=1)

        return text

    def _apply_breath(self, text: str, params: SynthesisParams) -> str:
        """Insert breath sounds based on breath mode."""
        if params.breath_mode == "minimal" or params.breath_audibility < 0.05:
            return text

        # Breath before first word if breath_before_key
        if params.breath_before_key:
            # ElevenLabs breath tag
            text = '<break time="100ms"/>' + text

        # Emotional/intimate modes: add breathing at natural pause points
        if params.breath_mode in ("emotional", "intimate") and params.breath_audibility > 0.3:
            # Insert after commas in long sentences
            sentences = text.split('. ')
            processed = []
            for sentence in sentences:
                parts = sentence.split(', ')
                if len(parts) > 2:
                    # Insert subtle breath at middle comma
                    mid = len(parts) // 2
                    parts[mid] = '<break time="150ms"/>' + parts[mid]
                processed.append(', '.join(parts))
            text = '. '.join(processed)

        return text

    def _apply_rate_and_pitch(self, text: str, params: SynthesisParams) -> str:
        """Wrap text in prosody tags for rate and pitch."""
        rate_pct = int(params.speech_rate * 100)
        pitch_st = params.pitch_shift_st

        # Only add prosody tag if it differs meaningfully from neutral
        needs_rate  = abs(params.speech_rate - 1.0) > 0.05
        needs_pitch = abs(pitch_st) > 0.3

        if not needs_rate and not needs_pitch:
            return text

        attrs = []
        if needs_rate:
            attrs.append(f'rate="{rate_pct}%"')
        if needs_pitch:
            # Convert semitones to Hz-relative string (approximate)
            pitch_pct = int(pitch_st * 5.5)   # ~5.5% per semitone
            sign = "+" if pitch_pct >= 0 else ""
            attrs.append(f'pitch="{sign}{pitch_pct}%"')

        attr_str = " ".join(attrs)
        return f'<prosody {attr_str}>{text}</prosody>'

    def plain_text(self, ssml: str) -> str:
        """Strip SSML tags — for providers that don't support markup."""
        return re.sub(r'<[^>]+>', '', ssml).strip()
