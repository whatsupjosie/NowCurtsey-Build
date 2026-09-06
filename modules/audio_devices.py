"""
audio_devices.py — Server-side audio device enumeration and management.

Wraps sounddevice/PortAudio for the server recording pipeline.

Key design decisions (from research):
  - query_devices() caches at PortAudio init time. We must call
    sd._terminate() + sd._initialize() before each enumeration to pick up
    newly plugged devices (hot-plug workaround for PortAudio limitation).
  - Filter virtual/garbage devices: ALSA exposes 128-channel virtual
    devices (sysdefault, dmix, etc.) that look real but aren't.
  - Validate before returning: check_input_settings() confirms the device
    actually accepts a stream at the requested sample rate and channel count.
  - Prefer names over indices: indices shift when devices connect/disconnect.

Routes (mount via FastAPI router):
  GET  /api/audio/devices          — list all valid input devices
  POST /api/audio/devices/refresh  — force hot-plug re-scan
  POST /api/audio/devices/select   — set active input device for recording
  GET  /api/audio/devices/active   — get currently selected device
  POST /api/audio/devices/test     — open a 1-second test stream to verify

Supported connection types detected and labelled:
  USB mic     (Blue Yeti, Rode NT-USB, Samson, AT2020+USB, etc.)
  XLR via interface (Focusrite Scarlett, Universal Audio, MOTU, etc.)
  3.5mm / headset (built-in or external combo jack)
  Bluetooth headset
  Virtual / software (BlackHole, VB-Cable, Loopback, PipeWire virtual)
  Built-in (laptop mic, AirPods built-in, etc.)
"""

from __future__ import annotations

import asyncio
import logging
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audio", tags=["audio-devices"])

# ── Optional sounddevice import ───────────────────────────────────────────────
# Graceful fallback if not installed — routes return helpful error messages
try:
    import sounddevice as _sd
    _SD_AVAILABLE = True
    logger.info("sounddevice available — audio device enumeration enabled")
except (ImportError, OSError) as exc:
    # OSError matters as much as ImportError here. The sounddevice package can
    # be installed and still raise OSError('PortAudio library not found') when
    # the native library is absent — the normal state of a headless server or
    # container. Catching ImportError alone turned an optional audio-device
    # feature into a hard boot failure for the entire PubCast host, because
    # main.py imports this module unconditionally. Every consumer below already
    # branches on _SD_AVAILABLE, so degrading here is sufficient.
    _sd = None
    _SD_AVAILABLE = False
    logger.warning(
        "sounddevice unavailable (%s: %s). Server-side audio device "
        "enumeration disabled; browser-side enumeration is unaffected.",
        type(exc).__name__, exc,
    )

# ── Known interface / device patterns ────────────────────────────────────────

_USB_PATTERNS = [
    "yeti", "rode", "samson", "at2020", "at2035", "fifine",
    "hyperx", "razer seiren", "elgato wave", "blue", "maono",
    "usb audio", "usb mic", "usb microphone", "usb condenser",
    "tonor", "trust gxt", "hollyland",
]
_XLR_INTERFACE_PATTERNS = [
    "scarlett", "focusrite", "universal audio", "ua-", "apollo",
    "motu", "presonus", "steinberg ur", "tascam", "zoom", "behringer",
    "audient", "ssl 2", "volt", "id14", "id22", "id44",
    "mackie", "roland studio-capture", "native instruments",
]
_BLUETOOTH_PATTERNS = [
    "bluetooth", "airpods", "bose", "sony wh", "sennheiser momentum",
    "jabra", "plantronics", "poly ", "beats ", "anker soundcore",
]
_VIRTUAL_PATTERNS = [
    "blackhole", "vb-audio", "vb-cable", "loopback", "soundflower",
    "virtual", "pipewire", "pulse", "jack sink", "jack source",
    "screaming bee", "voicemeeter", "obs virtual",
]
_BUILTIN_PATTERNS = [
    "built-in", "builtin", "internal", "laptop", "macbook",
    "realtek", "conexant", "nvidia hdmi", "intel hda", "amd audio",
]
# ALSA virtual garbage — filter these out on Linux
_ALSA_JUNK = {
    "sysdefault", "default", "front", "surround40", "surround51",
    "surround71", "iec958", "spdif", "hdmi", "dmix", "dsnoop",
    "hw", "plughw", "/dev/dsp",
}
# Minimum channels and sample rates we care about
_MIN_CHANNELS  = 1
_TARGET_RATES  = [48000, 44100, 22050, 16000]


# ── DeviceInfo dataclass ──────────────────────────────────────────────────────

@dataclass
class AudioDevice:
    index:         int
    name:          str
    host_api:      str
    max_channels:  int
    default_rate:  float
    connection:    str       # usb | xlr | bluetooth | virtual | builtin | unknown
    is_default:    bool
    validated:     bool      # passed check_input_settings()
    platform_note: str = "" # e.g. "Install BlackHole for virtual routing on Mac"

    def to_dict(self) -> Dict:
        return {
            "index":         self.index,
            "name":          self.name,
            "host_api":      self.host_api,
            "max_channels":  self.max_channels,
            "default_rate":  self.default_rate,
            "connection":    self.connection,
            "is_default":    self.is_default,
            "validated":     self.validated,
            "platform_note": self.platform_note,
            "label":         self._label(),
        }

    def _label(self) -> str:
        icons = {
            "usb":       "🎙",
            "xlr":       "🎚",
            "bluetooth": "🎧",
            "virtual":   "💻",
            "builtin":   "📻",
            "unknown":   "🔊",
        }
        icon = icons.get(self.connection, "🔊")
        suffix = " ✓" if self.validated else ""
        return f"{icon} {self.name}{suffix}"


# ── State ─────────────────────────────────────────────────────────────────────

_active_device: Optional[AudioDevice] = None
_device_cache:  List[AudioDevice]     = []
_last_scan:     float                 = 0.0
_CACHE_TTL:     float                 = 10.0   # seconds before auto-rescan


# ── Core functions ────────────────────────────────────────────────────────────

def _classify_connection(name: str) -> str:
    n = name.lower()
    if any(p in n for p in _VIRTUAL_PATTERNS):   return "virtual"
    if any(p in n for p in _BLUETOOTH_PATTERNS): return "bluetooth"
    if any(p in n for p in _XLR_INTERFACE_PATTERNS): return "xlr"
    if any(p in n for p in _USB_PATTERNS):       return "usb"
    if any(p in n for p in _BUILTIN_PATTERNS):   return "builtin"
    return "unknown"


def _is_alsa_junk(name: str) -> bool:
    """Filter out ALSA virtual/system devices that aren't real hardware."""
    n = name.strip().lower()
    for junk in _ALSA_JUNK:
        if n == junk or n.startswith(junk + ",") or n.startswith(junk + " "):
            return True
    return False


def _reinit_portaudio() -> None:
    """
    Hot-plug workaround: reinitialize PortAudio to pick up newly connected
    devices. Must be called before query_devices() to see fresh hardware.
    """
    if not _SD_AVAILABLE:
        return
    try:
        _sd._terminate()
        _sd._initialize()
    except Exception as e:
        logger.warning("PortAudio reinit warning: %s", e)


def _validate_device(index: int, channels: int, rate: float) -> bool:
    """
    Call check_input_settings() to confirm the device actually accepts
    a stream. Returns True if validated, False if any exception is raised.
    """
    if not _SD_AVAILABLE:
        return False
    for test_rate in _TARGET_RATES:
        try:
            _sd.check_input_settings(
                device=index,
                channels=min(channels, 2),
                dtype="float32",
                samplerate=test_rate,
            )
            return True
        except Exception:
            continue
    return False


def scan_devices(force: bool = False) -> List[AudioDevice]:
    """
    Enumerate all valid input devices. Reinitializes PortAudio first to
    detect hot-plugged hardware. Results are cached for _CACHE_TTL seconds.
    """
    global _device_cache, _last_scan

    now = time.time()
    if not force and _device_cache and (now - _last_scan) < _CACHE_TTL:
        return _device_cache

    if not _SD_AVAILABLE:
        logger.warning("sounddevice not available — returning empty device list")
        return []

    _reinit_portaudio()

    devices: List[AudioDevice] = []
    try:
        raw_devices = _sd.query_devices()
        default_in  = _sd.default.device[0] if isinstance(_sd.default.device, (list, tuple)) else _sd.default.device

        for idx, dev in enumerate(raw_devices):
            name      = dev.get("name", "").strip()
            max_in    = dev.get("max_input_channels", 0)
            host_api  = dev.get("hostapi", -1)
            rate      = dev.get("default_samplerate", 44100)

            # Skip output-only devices
            if max_in < _MIN_CHANNELS:
                continue

            # Skip ALSA garbage on Linux
            if sys.platform.startswith("linux") and _is_alsa_junk(name):
                continue

            # Classify connection type
            connection = _classify_connection(name)

            # Get host API name
            try:
                api_info  = _sd.query_hostapis(host_api)
                api_name  = api_info.get("name", "Unknown API")
            except Exception:
                api_name  = "Unknown API"

            # Prefer WASAPI over MME/DirectSound on Windows for lowest latency
            if sys.platform == "win32" and "MME" in api_name and max_in <= 2:
                # Check if there's a WASAPI version of this device
                # We'll include it but note the API
                pass

            # Validate device actually works
            validated = _validate_device(idx, max_in, rate)

            device = AudioDevice(
                index        = idx,
                name         = name,
                host_api     = api_name,
                max_channels = max_in,
                default_rate = rate,
                connection   = connection,
                is_default   = (idx == default_in),
                validated    = validated,
            )
            devices.append(device)

    except Exception as e:
        logger.error("Device scan failed: %s", e)

    # Sort: default first, then validated, then by connection quality
    priority = {"xlr": 0, "usb": 1, "builtin": 2, "bluetooth": 3, "virtual": 4, "unknown": 5}
    devices.sort(key=lambda d: (
        not d.is_default,
        not d.validated,
        priority.get(d.connection, 9),
        d.name,
    ))

    _device_cache = devices
    _last_scan    = time.time()

    logger.info(
        "Audio device scan complete: %d input devices found (%d validated)",
        len(devices),
        sum(1 for d in devices if d.validated),
    )
    return devices


def get_platform_recommendations() -> Dict[str, Any]:
    """Return platform-specific routing software recommendations."""
    plat = platform.system()
    if plat == "Darwin":
        return {
            "platform": "macOS",
            "virtual_routing": {
                "name": "BlackHole",
                "url": "https://existential.audio/blackhole/",
                "license": "Open Source (MIT)",
                "description": "Zero-latency virtual audio driver. Routes audio between apps without a cable.",
                "install": "brew install blackhole-2ch  OR  download from existential.audio",
            },
            "notes": [
                "Core Audio is your host API — lowest latency, best quality.",
                "XLR interfaces (Focusrite, Universal Audio) appear as Core Audio devices automatically.",
                "BlackHole lets you route system audio into PubCast without a physical loopback cable.",
            ],
        }
    elif plat == "Windows":
        return {
            "platform": "Windows",
            "virtual_routing": {
                "name": "VB-Audio CABLE",
                "url": "https://vb-audio.com/Cable/",
                "license": "Freeware (donationware)",
                "description": "Virtual audio cable for routing audio between Windows apps.",
                "install": "Download from vb-audio.com — install, reboot, appears as audio device",
            },
            "mixer": {
                "name": "VoiceMeeter Banana",
                "url": "https://vb-audio.com/Voicemeeter/banana.htm",
                "license": "Freeware (donationware)",
                "description": "Virtual mixing board — combine mic, desktop audio, multiple sources.",
            },
            "notes": [
                "Prefer WASAPI over MME or DirectSound for lowest latency.",
                "Focusrite/Universal Audio interfaces appear automatically after driver install.",
                "For ASIO support (professional interfaces): sounddevice supports ASIO but needs a special PortAudio build.",
            ],
        }
    elif plat == "Linux":
        return {
            "platform": "Linux",
            "virtual_routing": {
                "name": "PipeWire",
                "url": "https://pipewire.org/",
                "license": "Open Source (MIT/LGPL)",
                "description": "Modern Linux audio framework — handles JACK, PulseAudio, and ALSA simultaneously.",
                "install": "Already installed on most modern distros (Ubuntu 22.04+, Fedora 34+, etc.)",
            },
            "notes": [
                "PipeWire is the recommended audio backend — check with: pw-cli info all",
                "USB mics appear automatically when plugged in under PipeWire.",
                "XLR interfaces via ALSA: check with arecord -l to confirm detection.",
                "If using ALSA directly: avoid virtual devices (sysdefault, dmix) — use hw:X,0 for hardware.",
            ],
        }
    else:
        return {"platform": plat, "notes": ["Platform-specific recommendations not available."]}


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/devices")
async def list_audio_devices(refresh: bool = False):
    """
    List all valid audio input devices.
    Pass ?refresh=true to force a hot-plug rescan.
    """
    devices = await asyncio.to_thread(scan_devices, refresh)
    recs    = get_platform_recommendations()
    return JSONResponse({
        "devices":         [d.to_dict() for d in devices],
        "count":           len(devices),
        "sd_available":    _SD_AVAILABLE,
        "platform":        recs,
        "active_device":   _active_device.to_dict() if _active_device else None,
        "scanned_at":      _last_scan,
    })


@router.post("/devices/refresh")
async def refresh_audio_devices():
    """Force a hot-plug rescan — call when the user plugs in new hardware."""
    before = len(_device_cache)
    devices = await asyncio.to_thread(scan_devices, True)
    after   = len(devices)
    new     = after - before

    return JSONResponse({
        "ok":      True,
        "before":  before,
        "after":   after,
        "new":     new,
        "devices": [d.to_dict() for d in devices],
        "message": f"Found {after} device(s). {new} new since last scan." if new >= 0
                   else f"Found {after} device(s).",
    })


class SelectDeviceRequest(BaseModel):
    index:        Optional[int]  = None
    name:         Optional[str]  = None   # substring match — more stable than index
    profile_id:   Optional[str]  = None   # associate with a mic profile


@router.post("/devices/select")
async def select_audio_device(request: Request, payload: SelectDeviceRequest):
    """
    Set the active input device for the server recording pipeline.
    Prefer name matching over index — indices shift when devices change.
    """
    global _active_device

    devices = await asyncio.to_thread(scan_devices, False)

    selected: Optional[AudioDevice] = None

    if payload.name:
        # Substring match, case-insensitive
        name_lower = payload.name.lower()
        selected = next(
            (d for d in devices if name_lower in d.name.lower()),
            None
        )
        if not selected:
            return JSONResponse(
                {"ok": False, "error": f"No device matching '{payload.name}' found"},
                status_code=404,
            )
    elif payload.index is not None:
        selected = next((d for d in devices if d.index == payload.index), None)
        if not selected:
            return JSONResponse(
                {"ok": False, "error": f"Device index {payload.index} not found"},
                status_code=404,
            )
    else:
        # Select system default
        selected = next((d for d in devices if d.is_default), devices[0] if devices else None)
        if not selected:
            return JSONResponse(
                {"ok": False, "error": "No input devices found"},
                status_code=503,
            )

    _active_device = selected

    # Persist to disk
    data_dir = getattr(request.app.state, "data_dir", Path("data"))
    pref_path = Path(data_dir) / "audio_device_pref.json"
    import json
    pref_path.write_text(
        json.dumps({
            "name":       selected.name,
            "index":      selected.index,
            "connection": selected.connection,
            "profile_id": payload.profile_id,
            "set_at":     time.time(),
        }),
        encoding="utf-8",
    )

    logger.info("Active audio device set: %s (index=%d)", selected.name, selected.index)
    return JSONResponse({
        "ok":     True,
        "device": selected.to_dict(),
    })


@router.get("/devices/active")
async def get_active_device():
    """Return the currently selected input device."""
    if not _active_device:
        return JSONResponse({"ok": False, "device": None, "message": "No device selected"})
    return JSONResponse({"ok": True, "device": _active_device.to_dict()})


@router.post("/devices/test")
async def test_audio_device(payload: SelectDeviceRequest):
    """
    Attempt to open a brief input stream on the specified device.
    Returns latency info and confirms the device is actually working.
    """
    if not _SD_AVAILABLE:
        return JSONResponse(
            {"ok": False, "error": "sounddevice not installed — pip install sounddevice"},
            status_code=503,
        )

    devices = await asyncio.to_thread(scan_devices, False)

    target: Optional[AudioDevice] = None
    if payload.index is not None:
        target = next((d for d in devices if d.index == payload.index), None)
    elif payload.name:
        name_lower = payload.name.lower()
        target = next((d for d in devices if name_lower in d.name.lower()), None)
    elif _active_device:
        target = _active_device

    if not target:
        return JSONResponse({"ok": False, "error": "No device to test"}, status_code=400)

    def _run_test():
        import numpy as np
        try:
            # Open stream, capture 0.5 seconds, measure RMS
            frames = []
            channels = min(target.max_channels, 2)

            with _sd.InputStream(
                device=target.index,
                channels=channels,
                samplerate=48000,
                dtype="float32",
                latency="low",
            ) as stream:
                t0 = time.time()
                data, overflowed = stream.read(int(48000 * 0.5))
                elapsed = time.time() - t0

            rms = float(np.sqrt(np.mean(data ** 2))) if len(data) else 0.0
            return {
                "ok":           True,
                "device":       target.to_dict(),
                "rms":          round(rms, 6),
                "signal_dbfs":  round(20 * (np.log10(rms + 1e-10)), 1),
                "overflowed":   overflowed,
                "latency_ms":   round(elapsed * 1000, 1),
                "channels_open": channels,
                "message":      "Device opened successfully",
            }
        except Exception as e:
            return {"ok": False, "device": target.to_dict(), "error": str(e)}

    result = await asyncio.to_thread(_run_test)
    return JSONResponse(result)


@router.get("/devices/install-guide")
async def install_guide():
    """Return platform-specific setup instructions for common mic types."""
    recs = get_platform_recommendations()
    return JSONResponse({
        "platform":           recs,
        "connection_types": {
            "usb": {
                "label": "USB Microphone",
                "examples": ["Blue Yeti", "Rode NT-USB", "Audio-Technica AT2020+USB", "Elgato Wave"],
                "setup": "Plug in and go. Should appear in device list automatically. No drivers needed on Mac/Linux.",
                "notes": ["If not detected on Mac: System Settings → Privacy & Security → Microphone",
                          "If not detected on Windows: Device Manager → Sound → check for Unknown Device"],
            },
            "xlr": {
                "label": "XLR Microphone (via audio interface)",
                "examples": ["Focusrite Scarlett", "Universal Audio Apollo", "PreSonus AudioBox", "MOTU M2"],
                "setup": "Install interface driver first, then plug in. XLR mic connects to interface, interface connects to computer via USB/Thunderbolt.",
                "notes": ["Focusrite: download Focusrite Control from focusrite.com",
                          "Universal Audio: download UA Connect from uaudio.com",
                          "Most interfaces are class-compliant — plug in and they work on Mac without drivers"],
            },
            "bluetooth": {
                "label": "Bluetooth Headset / Earbuds",
                "examples": ["AirPods", "Sony WH-1000XM5", "Jabra Evolve2", "Bose QuietComfort"],
                "setup": "Pair via OS Bluetooth settings. Select as input device in PubCast.",
                "notes": ["Bluetooth audio input uses HSP/HFP profile — expect 8kHz or 16kHz quality",
                          "For best quality: use a wired mic for broadcast, Bluetooth for monitoring only",
                          "AirPods in Transparency mode have noticeable latency"],
            },
            "3.5mm": {
                "label": "3.5mm / Headset Mic",
                "examples": ["Gaming headsets", "TRRS headphone+mic combos", "Lavalier clip mics"],
                "setup": "Plug into combo jack (TRRS) or separate mic input. Select 'Built-in Microphone' or device name.",
                "notes": ["TRRS combo jacks support mic + headphone in one plug",
                          "Separate TS mic jacks need a USB audio adapter for best quality"],
            },
        },
        "sd_available":       _SD_AVAILABLE,
        "install_sounddevice": "pip install sounddevice" if not _SD_AVAILABLE else None,
    })
