"""Waiting-room host material for Sir Purfluous.

This module is intentionally small: it loads the structured doorway host
asset and picks state-appropriate scripted lines. It does not implement
Jeremy behavior.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("pubcast.sir_purfluous_waiting_room")

DATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "bots"
    / "sir_purfluous_waiting_room.json"
)

FALLBACK_PROFILE: Dict[str, Any] = {
    "host_id": "sir_purfluous_waiting_room",
    "character_id": "sir_purfluous",
    "display_name": "Sir Purfluous",
    "role": "Visible waiting-room host and admission liaison.",
    "voice_notes": ["Warm, theatrical, concise, and protective of the studio."],
    "host_duties": ["Greet arrivals.", "Explain admission status."],
    "state_lines": {
        "arrival": ["Welcome to the threshold, Sancho."],
        "pending": ["We wait. A noble art, rarely credited and almost always necessary."],
        "approved": ["The door opens. Enter with care."]
    },
    "idle_banter": []
}


def load_profile() -> Dict[str, Any]:
    """Load the structured waiting-room host profile."""
    try:
        with DATA_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        logger.warning("Using fallback Sir Purfluous waiting-room profile: %s", exc)
        return dict(FALLBACK_PROFILE)


def _state_lines(profile: Dict[str, Any], state: str) -> List[str]:
    states = profile.get("state_lines") or {}
    lines = states.get(state) or states.get("pending") or states.get("arrival") or []
    return [line for line in lines if isinstance(line, str) and line.strip()]


def _idle_lines(profile: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for item in profile.get("idle_banter") or []:
        if isinstance(item, dict) and isinstance(item.get("line"), str):
            lines.append(item["line"])
    return lines


def line_for_state(state: str = "pending") -> str:
    """Return a deterministic rotating line for a waiting-room state."""
    profile = load_profile()
    normalized_state = (state or "pending").strip().lower().replace("-", "_")
    lines = _state_lines(profile, normalized_state) or _idle_lines(profile)
    if not lines:
        return "Welcome to the threshold, Sancho."
    index = int(time.time() // 45) % len(lines)
    return lines[index]


def public_context(state: str = "pending") -> Dict[str, Any]:
    """Return UI-safe host context for the airlock."""
    profile = load_profile()
    return {
        "host_id": profile.get("host_id", "sir_purfluous_waiting_room"),
        "character_id": profile.get("character_id", "sir_purfluous"),
        "display_name": profile.get("display_name", "Sir Purfluous"),
        "state": (state or "pending").strip().lower().replace("-", "_"),
        "role": profile.get("role", "Visible waiting-room host."),
        "line": line_for_state(state),
        "voice_notes": profile.get("voice_notes", []),
        "host_duties": profile.get("host_duties", [])
    }


__all__ = ["DATA_PATH", "line_for_state", "load_profile", "public_context"]
