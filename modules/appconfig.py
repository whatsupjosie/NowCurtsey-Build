# PubCast AI — appconfig.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
modules/appconfig.py — Application configuration via environment variables.

Usage:
    from modules.appconfig import settings
    url = f"http://{settings.larynx_host}:{settings.larynx_port}/api/tts"
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    # ── TTS (Larynx / Piper) ────────────────────────────────────────────────
    larynx_host: str = field(default_factory=lambda: os.environ.get("PUBCAST_LARYNX_HOST", "127.0.0.1"))
    larynx_port: int = field(default_factory=lambda: int(os.environ.get("PUBCAST_LARYNX_PORT", "5002")))
    piper_model: str = field(default_factory=lambda: os.environ.get("PUBCAST_PIPER_MODEL", "en_US-lessac-medium"))

    # ── Server ───────────────────────────────────────────────────────────────
    host: str = field(default_factory=lambda: os.environ.get("PUBCAST_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.environ.get("PUBCAST_PORT", "8000")))
    debug: bool = field(default_factory=lambda: os.environ.get("PUBCAST_DEBUG", "0") == "1")

    # ── Storage paths ────────────────────────────────────────────────────────
    data_dir: str = field(default_factory=lambda: os.environ.get("PUBCAST_DATA_DIR", "data"))
    assets_dir: str = field(default_factory=lambda: os.environ.get("PUBCAST_ASSETS_DIR", "assets"))
    static_dir: str = field(default_factory=lambda: os.environ.get("PUBCAST_STATIC_DIR", "static"))

    # ── AI providers ─────────────────────────────────────────────────────────
    openai_key: str = field(default_factory=lambda: os.environ.get("PUBCAST_OPENAI_KEY", ""))
    anthropic_key: str = field(default_factory=lambda: os.environ.get("PUBCAST_ANTHROPIC_KEY", ""))
    google_key: str = field(default_factory=lambda: os.environ.get("PUBCAST_GOOGLE_KEY", ""))

    # Two-brain local model policy
    studio_model: str = field(default_factory=lambda: os.environ.get("STUDIO_MODEL", "ministral-pubcast:3b"))
    architect_model: str = field(default_factory=lambda: os.environ.get("ARCHITECT_MODEL", "gemma4-compute-q5:e2b"))
    studio_ctx: int = field(default_factory=lambda: int(os.environ.get("STUDIO_CTX", "2048")))
    architect_ctx: int = field(default_factory=lambda: int(os.environ.get("ARCHITECT_CTX", "2048")))
    studio_keepalive: str = field(default_factory=lambda: os.environ.get("STUDIO_KEEPALIVE", "10m"))
    architect_keepalive: str = field(default_factory=lambda: os.environ.get("ARCHITECT_KEEPALIVE", "0"))

    # ── Recording ────────────────────────────────────────────────────────────
    max_recording_hours: float = field(
        default_factory=lambda: float(os.environ.get("PUBCAST_MAX_RECORDING_HOURS", "4"))
    )


# Single shared instance — imported by name throughout the app
settings = Settings()
