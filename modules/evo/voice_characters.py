"""
modules/voice_characters.py — Character Voice Profiles
=======================================================
Copyright (c) 2024-2025 Rear View Foresight LLC
"Feic Mo Chroí — See My Heart"

Defines the voice identity for each Belle Époque Studios character.
Each character has a base voice profile that is modulated by the
ProsodyEngine based on VDI state and emotional input from mocap.

Characters:
    PETE        — The floor. Classically beautiful, sovereign, unsentimental.
                  Draws from hard-won industry experience. The ring on her
                  middle finger that nobody asks about. She is the authority
                  in the room, not because she demands it, but because she
                  earned it. Voice: warm contralto, precise, never performs.

    RE_PETE     — Young man. Babyface. Jimmy Stewart energy. Socially nervous
                  around Pete specifically. Kind. Will be something else entirely
                  in five years. Voice: lighter tenor, slightly breathless,
                  genuine warmth over polish.

    PETE_ENHANCED — Pete as orchestrator. The version of Pete that runs the
                  room from the inside. Not more emotional — more precise.
                  Same voice, tighter control.

Public API:
    CharacterVoiceProfile
    get_character_profile(character: str) -> CharacterVoiceProfile
    list_characters() -> List[str]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# CHARACTER VOICE PROFILE
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CharacterVoiceProfile:
    """
    Base voice identity for a character.
    These are the neutral-state parameters — ProsodyEngine modulates them
    based on VDI and emotional state. The character's identity is the floor,
    not the ceiling.
    """
    character_id:       str

    # ── Voice synthesis identity ──────────────────────────────────────────────
    elevenlabs_voice_id: str   = ""       # ElevenLabs voice ID
    cartesia_voice_id:   str   = ""       # Cartesia voice ID
    kokoro_voice:        str   = ""       # Kokoro local voice

    # ── Base prosody parameters ───────────────────────────────────────────────
    base_speech_rate:    float = 1.00     # Neutral speaking rate
    base_pitch_shift:    float = 0.0      # Semitones from model neutral
    base_stability:      float = 0.70     # ElevenLabs stability
    base_similarity:     float = 0.82     # ElevenLabs similarity boost
    base_style:          float = 0.25     # ElevenLabs style exaggeration

    # ── Character constraints ─────────────────────────────────────────────────
    crack_allowed:       bool  = False    # Can emotional cracks occur?
    crack_threshold:     float = 0.85     # VDI score required before crack permitted
    max_expressiveness:  float = 0.80     # Hard ceiling on style exaggeration
    min_stability:       float = 0.40     # Hard floor on stability

    # ── Register preferences ──────────────────────────────────────────────────
    # Which VoiceModes this character naturally gravitates toward
    preferred_modes:     List[str] = field(default_factory=list)
    # How strongly they resist moving away from preferred modes [0=fluid, 1=locked]
    mode_resistance:     float = 0.20

    # ── Breath and intimacy ───────────────────────────────────────────────────
    breath_personality:  str   = "minimal"   # minimal | structural | emotional | intimate
    proximity_capable:   bool  = False        # Can simulate closeness
    direct_address:      bool  = True         # Uses "you" framing

    # ── EQ character ─────────────────────────────────────────────────────────
    warmth_signature:    float = 0.0     # Base warmth boost (dB)
    presence_signature:  float = 2.0     # Base presence boost (dB)
    harmonic_character:  float = 0.0     # Harmonic saturation signature

    # ── Identity notes (for humans reading this) ─────────────────────────────
    character_note:      str   = ""


# ─────────────────────────────────────────────────────────────────────────────
# CHARACTER REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

_CHARACTER_REGISTRY: Dict[str, CharacterVoiceProfile] = {

    "pete": CharacterVoiceProfile(
        character_id        = "pete",
        base_speech_rate    = 0.95,    # Slightly measured — she chooses her words
        base_pitch_shift    = -0.5,    # Grounded, warm contralto register
        base_stability      = 0.72,    # Stable but not stiff
        base_similarity     = 0.85,
        base_style          = 0.20,    # Understated — performance is for amateurs
        crack_allowed       = True,
        crack_threshold     = 0.88,    # Very high threshold — cracks are rare and real
        max_expressiveness  = 0.65,    # She doesn't perform. Ever.
        min_stability       = 0.50,
        preferred_modes     = ["mixed", "voice_dominant"],
        mode_resistance     = 0.30,    # She resists being pushed into pure content mode
        breath_personality  = "structural",
        proximity_capable   = True,    # She can get close when she means it
        direct_address      = True,
        warmth_signature    = 1.5,
        presence_signature  = 2.5,
        harmonic_character  = 0.15,
        character_note      = (
            "Classically beautiful. Wears work clothes because that's what you "
            "wear on a production floor. The ring on her middle finger — a man's "
            "wedding ring — that nobody asks about. Sovereignty over identity. "
            "She carries the room without demanding it."
        ),
    ),

    "re_pete": CharacterVoiceProfile(
        character_id        = "re_pete",
        base_speech_rate    = 1.05,    # Slightly faster — youth, enthusiasm
        base_pitch_shift    = 1.5,     # Lighter tenor register
        base_stability      = 0.62,    # Less stable — genuine, not polished
        base_similarity     = 0.78,
        base_style          = 0.35,    # More expressive — he hasn't learned to hide it yet
        crack_allowed       = True,
        crack_threshold     = 0.70,    # Lower threshold — his emotions are closer to the surface
        max_expressiveness  = 0.85,
        min_stability       = 0.30,
        preferred_modes     = ["mixed", "voice_dominant"],
        mode_resistance     = 0.10,    # Fluid — he follows the room
        breath_personality  = "emotional",
        proximity_capable   = False,   # Not yet — still finding his footing
        direct_address      = True,
        warmth_signature    = 2.0,     # Warm — he means well and it shows
        presence_signature  = 1.8,
        harmonic_character  = 0.05,
        character_note      = (
            "Young man. Babyface. Slim. Kind. Socially nervous around Pete "
            "specifically — not in a bad way, in the way where you know someone "
            "is better than you and you're glad they exist. Jimmy Stewart energy. "
            "Will be something else entirely in five years."
        ),
    ),

    "pete_enhanced": CharacterVoiceProfile(
        character_id        = "pete_enhanced",
        base_speech_rate    = 0.93,    # Slightly slower than Pete — more deliberate
        base_pitch_shift    = -0.5,    # Same register as Pete
        base_stability      = 0.80,    # More stable — she's in control mode
        base_similarity     = 0.88,
        base_style          = 0.15,    # Even more stripped — pure signal
        crack_allowed       = False,   # Pete Enhanced doesn't crack. Not in this mode.
        crack_threshold     = 1.00,
        max_expressiveness  = 0.50,    # Hard ceiling — orchestrator mode
        min_stability       = 0.60,
        preferred_modes     = ["content_clear", "mixed"],
        mode_resistance     = 0.50,    # Strong resistance — she's anchoring the room
        breath_personality  = "minimal",
        proximity_capable   = True,
        direct_address      = True,
        warmth_signature    = 1.0,
        presence_signature  = 3.0,     # High presence — she cuts through everything
        harmonic_character  = 0.10,
        character_note      = (
            "Pete as master orchestrator. Not more emotional — more precise. "
            "She runs the room from the inside. Same person, different function. "
            "When Pete Enhanced speaks, the room listens because she has already "
            "thought of everything you were about to say."
        ),
    ),

    "sir_purfluous": CharacterVoiceProfile(
        character_id        = "sir_purfluous",
        base_speech_rate    = 0.92,
        base_pitch_shift    = -1.0,
        base_stability      = 0.76,
        base_similarity     = 0.84,
        base_style          = 0.42,
        crack_allowed       = True,
        crack_threshold     = 0.82,
        max_expressiveness  = 0.92,
        min_stability       = 0.44,
        preferred_modes     = ["voice_dominant", "mixed"],
        mode_resistance     = 0.35,
        breath_personality  = "intimate",
        proximity_capable   = True,
        direct_address      = True,
        warmth_signature    = 1.8,
        presence_signature  = 2.8,
        harmonic_character  = 0.22,
        character_note      = (
            "Tall, lean, angular, theatrical and slightly ridiculous, but still "
            "impressive. Burgundy velvet jacket, brass buttons, cream cravat, "
            "silver hair, deep voice with Shakespearean pauses and real warmth beneath pride."
        ),
    ),
}


_CHARACTER_ALIASES: Dict[str, str] = {
    "repeat": "re_pete",
    "repete": "re_pete",
    "re-pete": "re_pete",
    "re_pete": "re_pete",
    "sir_purfluous": "sir_purfluous",
    "sir-purfluous": "sir_purfluous",
    "purfluous": "sir_purfluous",
    "pete": "pete",
    "pete_enhanced": "pete_enhanced",
}


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def get_character_profile(character: str) -> Optional[CharacterVoiceProfile]:
    """
    Retrieve a character's voice profile by ID.
    Returns None if character not found.
    """
    key = _CHARACTER_ALIASES.get(str(character or "").lower(), str(character or "").lower())
    return _CHARACTER_REGISTRY.get(key)


def list_characters() -> List[str]:
    """Return all registered character IDs."""
    return ["pete", "re_pete", "sir_purfluous", "pete_enhanced"]


def register_character(profile: CharacterVoiceProfile) -> None:
    """Register a new character profile."""
    _CHARACTER_REGISTRY[profile.character_id.lower()] = profile
