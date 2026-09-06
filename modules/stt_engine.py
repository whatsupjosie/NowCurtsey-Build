"""
modules/stt_engine.py — Speech-to-text using faster-whisper.

Drop-in STT for PubCast. Runs locally, no API key, no cost.

Install on Zoidberg:
    pip install faster-whisper

Model sizes vs GTX 960M (4GB VRAM):
    tiny   — very fast,  lower accuracy
    small  — fast,       good accuracy     ← safe choice
    medium — ~2GB VRAM,  excellent         ← what we're using
    large  — tight on 4GB, slowest

Usage:
    engine = STTEngine(model_size="medium", device="cuda")
    result = await engine.transcribe(audio_bytes, mime_type="audio/webm")

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
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pubcast.stt")

# Model cache — load once, reuse forever
_model_instance = None
_model_lock = asyncio.Lock()


def _load_model_sync(model_size: str, device: str, compute_type: str):
    """Load faster-whisper model synchronously (runs in thread pool)."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
        logger.info("[STT] Loading Whisper %s on %s (%s)…", model_size, device, compute_type)
        t0 = time.time()
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        logger.info("[STT] Whisper %s ready in %.1fs", model_size, time.time() - t0)
        return model
    except ImportError:
        raise RuntimeError(
            "faster-whisper not installed. Run: pip install faster-whisper"
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to load Whisper model: {exc}") from exc


class STTEngine:
    """
    Async wrapper around faster-whisper for PubCast.
    Singleton-safe: first call loads the model, all subsequent calls reuse it.
    """

    def __init__(
        self,
        model_size:   str = "medium",
        device:       str = "auto",        # "cuda" | "cpu" | "auto"
        compute_type: str = "auto",        # "float16" | "int8" | "auto"
        language:     Optional[str] = None # None = auto-detect
    ):
        self.model_size   = model_size
        self.language     = language

        # Resolve device
        if device == "auto":
            try:
                import torch
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                self.device = "cpu"
        else:
            self.device = device

        # Resolve compute type
        if compute_type == "auto":
            self.compute_type = "float16" if self.device == "cuda" else "int8"
        else:
            self.compute_type = compute_type

        self._model = None
        logger.info(
            "[STT] Engine configured: %s on %s (%s)",
            model_size, self.device, self.compute_type
        )

    async def _ensure_model(self):
        global _model_instance
        if _model_instance is not None:
            self._model = _model_instance
            return
        async with _model_lock:
            if _model_instance is not None:
                self._model = _model_instance
                return
            loop = asyncio.get_event_loop()
            _model_instance = await loop.run_in_executor(
                None, _load_model_sync,
                self.model_size, self.device, self.compute_type
            )
            self._model = _model_instance

    async def transcribe(
        self,
        audio_data:  bytes,
        mime_type:   str = "audio/webm",
        language:    Optional[str] = None,
        prompt:      Optional[str] = None,   # context hint — improves accuracy
    ) -> Dict[str, Any]:
        """
        Transcribe raw audio bytes → text.

        Returns:
            {
                "text":      str,         full transcript
                "segments":  list,        per-segment timings
                "language":  str,         detected language code
                "duration":  float,       audio length in seconds
                "latency_ms": int,        transcription time
                "ok":        bool,
            }
        """
        await self._ensure_model()

        t0 = time.time()

        # Write to temp file — faster-whisper needs a file path
        suffix = _mime_to_suffix(mime_type)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name

        try:
            loop = asyncio.get_event_loop()
            segments, info = await loop.run_in_executor(
                None, self._run_transcribe, tmp_path, language or self.language, prompt
            )

            text = " ".join(s.text.strip() for s in segments).strip()
            seg_list = [
                {"start": s.start, "end": s.end, "text": s.text.strip()}
                for s in segments
            ]

            latency = int((time.time() - t0) * 1000)
            logger.info(
                "[STT] Transcribed %.1fs audio in %dms: %r",
                info.duration, latency, text[:80]
            )

            return {
                "ok":         True,
                "text":       text,
                "segments":   seg_list,
                "language":   info.language,
                "duration":   info.duration,
                "latency_ms": latency,
            }

        except Exception as exc:
            logger.error("[STT] Transcription failed: %s", exc)
            return {"ok": False, "text": "", "error": str(exc)}
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _run_transcribe(self, path: str, language: Optional[str], prompt: Optional[str]):
        """Blocking transcription — runs in thread pool."""
        kwargs: Dict[str, Any] = {
            "beam_size":          5,
            "vad_filter":         True,      # skip silence automatically
            "vad_parameters":     {"min_silence_duration_ms": 500},
        }
        if language:
            kwargs["language"] = language
        if prompt:
            kwargs["initial_prompt"] = prompt

        segments, info = self._model.transcribe(path, **kwargs)
        return list(segments), info   # materialise generator before returning to event loop

    def status(self) -> Dict[str, Any]:
        return {
            "model":        self.model_size,
            "device":       self.device,
            "compute_type": self.compute_type,
            "loaded":       self._model is not None,
            "language":     self.language or "auto-detect",
        }


def _mime_to_suffix(mime: str) -> str:
    table = {
        "audio/webm":       ".webm",
        "audio/ogg":        ".ogg",
        "audio/wav":        ".wav",
        "audio/mp4":        ".mp4",
        "audio/mpeg":       ".mp3",
        "audio/x-m4a":      ".m4a",
    }
    return table.get(mime.split(";")[0].strip(), ".webm")
