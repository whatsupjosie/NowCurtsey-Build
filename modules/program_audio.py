"""Program audio contract helpers for PubCast.

This is a dependency-free server-side companion for the browser program audio
runtime. It validates audio events and produces a small status/action model for
menus, recovery, and the Pub Manager.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Literal

AudioBus = Literal["dialogue", "music", "sfx", "ui", "vtr", "room"]
VALID_BUSES = {"dialogue", "music", "sfx", "ui", "vtr", "room"}
VALID_ACTIONS = {"play", "stop", "stop_all", "set_volume", "mute", "unmute", "status"}


@dataclass
class ProgramAudioState:
    bus_volumes: Dict[str, float] = field(default_factory=lambda: {bus: 1.0 for bus in VALID_BUSES})
    muted_buses: set[str] = field(default_factory=set)
    active_sources: Dict[str, int] = field(default_factory=lambda: {bus: 0 for bus in VALID_BUSES})
    dialogue_active: int = 0

    def status(self) -> Dict[str, Any]:
        return {
            "buses": {
                bus: {
                    "volume": self.bus_volumes.get(bus, 1.0),
                    "muted": bus in self.muted_buses,
                    "active_sources": self.active_sources.get(bus, 0),
                }
                for bus in sorted(VALID_BUSES)
            },
            "dialogue_active": self.dialogue_active,
        }


def clamp_volume(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 1.0
    if number != number:
        return 1.0
    return max(0.0, min(1.0, number))


def validate_audio_event(event: Dict[str, Any]) -> Dict[str, Any]:
    action = str(event.get("action") or "status")
    if action not in VALID_ACTIONS:
        raise ValueError(f"unsupported audio action: {action}")
    bus = str(event.get("bus") or "sfx")
    if action not in {"stop_all", "status"} and bus not in VALID_BUSES:
        raise ValueError(f"unsupported audio bus: {bus}")
    out = dict(event)
    out["action"] = action
    out["bus"] = bus
    if "volume" in out:
        out["volume"] = clamp_volume(out["volume"])
    if "position" in out and not isinstance(out["position"], dict):
        out.pop("position", None)
    return out


def apply_audio_event(state: ProgramAudioState, event: Dict[str, Any]) -> Dict[str, Any]:
    event = validate_audio_event(event)
    action = event["action"]
    bus = event.get("bus", "sfx")
    if action == "set_volume":
        state.bus_volumes[bus] = clamp_volume(event.get("volume", 1.0))
    elif action == "mute":
        state.muted_buses.add(bus)
    elif action == "unmute":
        state.muted_buses.discard(bus)
    elif action == "play":
        state.active_sources[bus] = state.active_sources.get(bus, 0) + 1
        if bus == "dialogue":
            state.dialogue_active += 1
    elif action == "stop":
        state.active_sources[bus] = max(0, state.active_sources.get(bus, 0) - 1)
        if bus == "dialogue":
            state.dialogue_active = max(0, state.dialogue_active - 1)
    elif action == "stop_all":
        for key in list(state.active_sources):
            state.active_sources[key] = 0
        state.dialogue_active = 0
    return state.status()


def issue_recovery_actions() -> list[Dict[str, str]]:
    return [
        {"id": "program_audio.stop_all", "label": "Stop all sounds", "safety": "safe"},
        {"id": "program_audio.clear_dialogue", "label": "Clear dialogue queue", "safety": "safe"},
        {"id": "program_audio.disable_tts_autoplay", "label": "Disable TTS autoplay", "safety": "safe"},
    ]


__all__ = [
    "ProgramAudioState", "VALID_ACTIONS", "VALID_BUSES", "apply_audio_event", "clamp_volume",
    "issue_recovery_actions", "validate_audio_event",
]
