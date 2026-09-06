# PubCast AI — bubble_jeremy_adapter.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rear View Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
"""
Small adapter from Bubble Stack spatial summaries to Jeremy-safe shoulder prompts.

This module does not replace Jeremy, SystemMemory, CricketKeeper, RoomConductor,
or any LLM path. It only formats BubbleStat data as optional room context.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional


class BubbleJeremyAdapter:
    """Format Bubble Stack room summaries for Jeremy / RoomConductor."""

    def __init__(self, summary_provider: Callable[[str], Dict[str, Any]]):
        self._summary_provider = summary_provider

    def get_summary(self, room_id: str) -> Dict[str, Any]:
        return self._summary_provider(room_id)

    def shoulder_prompt(self, room_id: str) -> str:
        summary = self.get_summary(room_id)
        return format_bubble_summary_for_jeremy(summary)


def format_bubble_summary_for_jeremy(summary: Optional[Dict[str, Any]]) -> str:
    """Create a short, non-command room-context line from BubbleStat data."""
    if not summary:
        return ""

    state = str(summary.get("state") or "UNKNOWN")
    if state in {"AI_BLIND", "BLIND", "UNCONFIGURED"}:
        return "Bubble Stack: AI spatial awareness is blind/unconfigured for this room."

    active = summary.get("active_bubble_count", 0)
    total = summary.get("bubble_count", 0)
    actors = summary.get("actors_seen") or []
    postures = summary.get("postures") or {}
    nearby = summary.get("nearby") or {}
    events = summary.get("meaningful_events") or []
    engine_summary = summary.get("engine_summary") or {}
    engine_name = engine_summary.get("engine") or summary.get("engine_version") or "v0.1-safe"

    parts = [f"Bubble Stack: state={state}, active={active}/{total}, engine={engine_name}"]
    if actors:
        parts.append("actors=" + ", ".join(map(str, actors[:5])))
    if postures:
        posture_text = ", ".join(f"{k}:{v}" for k, v in list(postures.items())[:5])
        parts.append("postures=" + posture_text)
    if nearby:
        near_text = ", ".join(f"{k} near {', '.join(map(str, v[:3]))}" for k, v in list(nearby.items())[:3])
        parts.append("nearby=" + near_text)
    if engine_summary:
        pikpc_active = engine_summary.get("active_bubble_count")
        order_events = engine_summary.get("recent_order_events") or []
        continuity = engine_summary.get("performance_continuity") or []
        if pikpc_active is not None:
            parts.append(f"pikpc_active={pikpc_active}")
        if order_events:
            parts.append(f"pikpc_events={len(order_events)}")
        if continuity:
            parts.append(f"performance_continuity={len(continuity)}")
    if events:
        parts.append(f"events={len(events)} recent")
    return "; ".join(parts) + "."

