"""
modules/tts_engine.py — Text-to-speech using Coqui XTTS-v2 with voice cloning.

Each PubCast character gets their own voice from a 6-second reference clip.
No API key. No per-minute cost. Runs on Zoidberg's GPU.

Install on Zoidberg:
    pip install TTS torch

Voice reference clips go in:  data/voices/{character_id}.wav
    jeremy.wav      — 6+ seconds of Jeremy Cricket's voice
    pete.wav        — Pete
    sir_purfluous.wav
    sheila.wav
    manny.wav
    default.wav     — fallback

If a character has no voice file, falls back to Piper (CPU, no cloning)
or browser speechSynthesis as last resort.

Feic Mo Chroí — Rear View Foresight LLC 2026
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("pubcast.tts")

_tts_instance   = None
_piper_instance = None
_tts_lock       = asyncio.Lock()

DATA_DIR = Path("data")
VOICES_DIR = DATA_DIR / "voices"


def _load_xtts_sync():
    """Load XTTS-v2 synchronously — runs in thread pool."""
    try:
        from TTS.api import TTS  # type: ignore
        logger.info("[TTS] Loading XTTS-v2…")
        t0 = time.time()
        tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=True)
        logger.info("[TTS] XTTS-v2 ready in %.1fs", time.time() - t0)
        return tts
    except ImportError:
        raise RuntimeError("Coqui TTS not installed. Run: pip install TTS")
    except Exception as exc:
        raise RuntimeError(f"XTTS-v2 load failed: {exc}") from exc


class TTSEngine:
    """
    Async TTS for PubCast characters.
    Tries XTTS-v2 (voice-cloned, GPU) → falls back to system pyttsx3 (CPU).
    """

    def __init__(self, data_dir: Path = DATA_DIR):
        self.voices_dir = data_dir / "voices"
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        self._xtts  = None
        self._ready = False

    async def _ensure_xtts(self) -> bool:
        global _tts_instance
        if _tts_instance is not None:
            self._xtts = _tts_instance
            return True
        async with _tts_lock:
            if _tts_instance is not None:
                self._xtts = _tts_instance
                return True
            try:
                loop = asyncio.get_event_loop()
                _tts_instance = await loop.run_in_executor(None, _load_xtts_sync)
                self._xtts = _tts_instance
                return True
            except Exception as exc:
                logger.warning("[TTS] XTTS-v2 unavailable: %s — using fallback", exc)
                return False

    def _voice_file(self, character_id: str) -> Optional[Path]:
        """Find the voice reference file for a character."""
        for ext in (".wav", ".mp3", ".ogg", ".flac"):
            p = self.voices_dir / f"{character_id}{ext}"
            if p.exists():
                return p
        # Try default
        for ext in (".wav", ".mp3"):
            p = self.voices_dir / f"default{ext}"
            if p.exists():
                return p
        return None

    async def synthesize(
        self,
        text:         str,
        character_id: str = "default",
        language:     str = "en",
        speed:        float = 1.0,
    ) -> Dict[str, Any]:
        """
        Synthesize text → WAV audio bytes.

        Returns:
            {
                "ok":         bool,
                "audio":      bytes,   WAV audio data
                "mime_type":  str,     "audio/wav"
                "duration":   float,   seconds
                "character":  str,
                "engine":     str,     "xtts" | "pyttsx3" | "unavailable"
                "latency_ms": int,
            }
        """
        t0   = time.time()
        text = text.strip()
        if not text:
            return {"ok": False, "error": "Empty text", "audio": b""}

        # Apply prosody hint — speed influenced by character type
        speed = max(0.7, min(1.5, speed))

        voice_file = self._voice_file(character_id)
        xtts_ok    = await self._ensure_xtts()

        if xtts_ok and voice_file:
            result = await self._synth_xtts(text, voice_file, language, speed)
        else:
            logger.info(
                "[TTS] No voice file for %r or XTTS unavailable — using pyttsx3",
                character_id
            )
            result = await self._synth_pyttsx3(text, speed)

        result["character"]  = character_id
        result["latency_ms"] = int((time.time() - t0) * 1000)
        logger.info(
            "[TTS] Synthesized %d chars for %s in %dms via %s",
            len(text), character_id, result["latency_ms"], result.get("engine","?")
        )
        return result

    async def _synth_xtts(
        self, text: str, voice_file: Path, language: str, speed: float
    ) -> Dict[str, Any]:
        """XTTS-v2 voice-cloned synthesis — runs in thread pool."""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            def _run():
                self._xtts.tts_to_file(
                    text          = text,
                    speaker_wav   = str(voice_file),
                    language      = language,
                    file_path     = tmp_path,
                    speed         = speed,
                )
                with open(tmp_path, "rb") as f:
                    return f.read()

            loop  = asyncio.get_event_loop()
            audio = await loop.run_in_executor(None, _run)
            return {"ok": True, "audio": audio, "mime_type": "audio/wav",
                    "duration": len(audio) / 32000, "engine": "xtts"}
        except Exception as exc:
            logger.error("[TTS] XTTS synthesis failed: %s", exc)
            return await self._synth_pyttsx3(text, speed)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    async def _synth_pyttsx3(self, text: str, speed: float) -> Dict[str, Any]:
        """CPU fallback TTS using pyttsx3."""
        try:
            import pyttsx3  # type: ignore

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            def _run():
                engine = pyttsx3.init()
                engine.setProperty("rate", int(175 * speed))
                engine.save_to_file(text, tmp_path)
                engine.runAndWait()
                with open(tmp_path, "rb") as f:
                    return f.read()

            loop  = asyncio.get_event_loop()
            audio = await loop.run_in_executor(None, _run)
            return {"ok": True, "audio": audio, "mime_type": "audio/wav",
                    "duration": len(audio) / 32000, "engine": "pyttsx3"}
        except Exception as exc:
            logger.error("[TTS] pyttsx3 fallback failed: %s", exc)
            return {"ok": False, "audio": b"", "mime_type": "audio/wav",
                    "duration": 0, "engine": "unavailable", "error": str(exc)}

    def list_voices(self) -> Dict[str, Any]:
        """List which characters have voice reference files."""
        voices = {}
        for f in self.voices_dir.iterdir():
            if f.suffix in (".wav", ".mp3", ".ogg", ".flac"):
                voices[f.stem] = {
                    "file": f.name,
                    "size_kb": round(f.stat().st_size / 1024, 1)
                }
        return voices

    def status(self) -> Dict[str, Any]:
        return {
            "xtts_loaded":   self._xtts is not None,
            "voices_dir":    str(self.voices_dir),
            "voices_ready":  self.list_voices(),
            "fallback":      "pyttsx3",
        }
