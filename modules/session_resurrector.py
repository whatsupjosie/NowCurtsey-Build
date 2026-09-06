"""
session_resurrector.py - warm boot for persistent memory.

This module bridges the newer Alex SQLite memory design and the current PubCast
AlexCore runtime. It does not replace either system. It reads whatever state is
available, builds a compact opening whisper, and primes Jeremy through the
existing bridge before the first user-facing response.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pubcast.session_resurrector")


@dataclass
class ResurrectionContext:
    """Startup context returned by SessionResurrector.resurrect."""

    whisper: str
    packet: Dict[str, Any]
    state: Any
    memory_count: int
    offline_mins: float
    summary: str


class SessionResurrector:
    """Warm Alex and Jeremy from persisted memory at session startup."""

    def __init__(
        self,
        alex: Any,
        bridge: Any,
        ingestor: Optional[Any] = None,
        memory_engine: Optional[Any] = None,
        *,
        data_dir: Optional[Path] = None,
    ) -> None:
        self.alex = alex
        self.bridge = bridge
        self.ingestor = ingestor
        self.memory_engine = memory_engine
        self.data_dir = Path(data_dir) if data_dir is not None else self._infer_data_dir()

    async def resurrect(
        self,
        user_id: str,
        session_id: str,
        *,
        project_id: str = "default",
        room_id: str = "default",
        display_name: str = "",
        include_episodic: bool = True,
        max_memories: int = 8,
        min_importance: int = 6,
    ) -> ResurrectionContext:
        """Load state, recall memories, prime Jeremy, and return a whisper."""

        state = await self._load_state()
        offline_mins = self._offline_minutes(state)
        state = await self._apply_offline_decay(state, offline_mins)
        memories = await self._recall_memories(max_memories=max_memories, min_importance=min_importance)

        episodic_summary = ""
        if include_episodic:
            episodic_summary = await self._load_recent_episodic(user_id)

        packet = await self._prime_bridge(
            user_id=user_id,
            session_id=session_id,
            project_id=project_id,
            room_id=room_id,
            display_name=display_name,
        )

        await self._prime_jeremy_system_mode(user_id=user_id, offline_mins=offline_mins)
        await self._log_resurrection_event(
            user_id=user_id,
            session_id=session_id,
            state=state,
            memory_count=len(memories),
        )

        whisper = self._build_resurrection_whisper(
            state=state,
            memories=memories,
            episodic_summary=episodic_summary,
            offline_mins=offline_mins,
        )
        summary = self._build_summary(state, memories, offline_mins)

        logger.info("Session resurrection complete: %s", summary)
        return ResurrectionContext(
            whisper=whisper,
            packet=packet,
            state=state,
            memory_count=len(memories),
            offline_mins=offline_mins,
            summary=summary,
        )

    def _infer_data_dir(self) -> Path:
        data_dir = getattr(self.bridge, "data_dir", None) or getattr(self.alex, "data_dir", None)
        return Path(data_dir) if data_dir is not None else Path("data")

    async def _maybe_await(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    async def _load_state(self) -> Any:
        if hasattr(self.alex, "get_emotional_state"):
            return await self._maybe_await(self.alex.get_emotional_state())

        # Current PubCast AlexCore shape.
        if hasattr(self.alex, "_user_state"):
            return self.alex._user_state

        return None

    def _offline_minutes(self, state: Any) -> float:
        updated_at = getattr(state, "updated_at", None)
        if isinstance(updated_at, (int, float)):
            return max(0.0, (time.time() - float(updated_at)) / 60.0)

        last_interaction = getattr(self.alex, "_last_interaction", None)
        if isinstance(last_interaction, datetime):
            return max(0.0, (datetime.now() - last_interaction).total_seconds() / 60.0)

        return 0.0

    async def _apply_offline_decay(self, state: Any, offline_mins: float) -> Any:
        if state is None or offline_mins <= 0:
            return state

        capped_mins = min(offline_mins, 480.0)
        if hasattr(state, "stress_level"):
            state.stress_level = max(0.0, float(state.stress_level) * (0.98 ** capped_mins))
        if hasattr(state, "clarity_score"):
            state.clarity_score = min(1.0, float(state.clarity_score) + 0.02 * capped_mins)
        if hasattr(state, "energy_level"):
            state.energy_level = min(1.0, float(state.energy_level) + 0.01 * capped_mins)
        if hasattr(state, "fragility_level"):
            state.fragility_level = max(0.0, float(state.fragility_level) - 0.01 * capped_mins)
        if hasattr(state, "battery"):
            state.battery = self._compute_battery(getattr(state, "energy_level", 1.0))
        if hasattr(state, "mood"):
            state.mood = self._compute_mood(
                getattr(state, "stress_level", 0.0),
                getattr(state, "fragility_level", 0.0),
            )

        if hasattr(self.alex, "_save_emotional_state_object"):
            await self._maybe_await(self.alex._save_emotional_state_object(state))
        elif hasattr(self.alex, "save_state_snapshot"):
            if hasattr(self.alex, "_cached_stress_score") and hasattr(state, "calculate_stress_score"):
                self.alex._cached_stress_score = state.calculate_stress_score()
            if hasattr(self.alex, "_update_ai_state"):
                self.alex._update_ai_state()
            self.alex.save_state_snapshot()

        return state

    def _compute_battery(self, energy: float) -> str:
        if energy >= 0.7:
            return "charged"
        if energy >= 0.4:
            return "moderate"
        if energy >= 0.2:
            return "low"
        return "depleted"

    def _compute_mood(self, stress: float, fragility: float) -> str:
        if stress > 0.7 or fragility > 0.65:
            return "redlining"
        if stress > 0.5 or fragility > 0.45:
            return "fragile"
        if stress < 0.3 and fragility < 0.25:
            return "stable"
        return "neutral"

    async def _recall_memories(self, *, max_memories: int, min_importance: int) -> List[Any]:
        if hasattr(self.alex, "recall"):
            try:
                memories = await self._maybe_await(
                    self.alex.recall("", max_results=max_memories, min_importance=min_importance)
                )
                return list(memories or [])
            except TypeError:
                pass

        memory = getattr(self.alex, "memory", None)
        if memory and hasattr(memory, "recall"):
            memories = memory.recall(days_back=30, limit=max_memories)
            return list(memories or [])

        return []

    async def _load_recent_episodic(self, user_id: str) -> str:
        if not self.memory_engine:
            return ""

        try:
            if hasattr(self.memory_engine, "recent_for_user"):
                try:
                    events = await asyncio.to_thread(
                        self.memory_engine.recent_for_user,
                        self.data_dir,
                        user_id=user_id,
                        limit=5,
                    )
                except TypeError:
                    events = await asyncio.to_thread(
                        self.memory_engine.recent_for_user,
                        user_id,
                        limit=5,
                    )
            else:
                return ""
        except Exception as exc:
            logger.warning("Could not load episodic memory: %s", exc)
            return ""

        lines = []
        for event in list(events or [])[-3:]:
            if not isinstance(event, dict):
                continue
            summary = event.get("summary") or event.get("text") or event.get("kind") or event.get("event_type")
            if summary:
                lines.append(f"- {str(summary)[:140]}")
        return "\n".join(lines)

    async def _prime_bridge(
        self,
        *,
        user_id: str,
        session_id: str,
        project_id: str,
        room_id: str,
        display_name: str,
    ) -> Dict[str, Any]:
        if hasattr(self.bridge, "handoff_to_jeremy"):
            packet = await self._maybe_await(self.bridge.handoff_to_jeremy(user_id=user_id))
            return dict(packet or {})

        if hasattr(self.bridge, "build_entry_packet"):
            packet = self.bridge.build_entry_packet(
                user_id=user_id,
                session_id=session_id,
                project_id=project_id,
                room_id=room_id,
                display_name=display_name,
            )
            return dict(packet or {})

        if hasattr(self.bridge, "current_packet"):
            packet = self.bridge.current_packet(user_id=user_id, session_id=session_id)
            return dict(packet or {})

        return {}

    async def _prime_jeremy_system_mode(self, *, user_id: str, offline_mins: float) -> None:
        jeremy = getattr(self.bridge, "jeremy", None)
        if not jeremy or not hasattr(jeremy, "remember"):
            return

        tags = [tag for tag in ["system_briefing", user_id, "session_resume"] if tag]
        try:
            memory_type = "instruction"
            try:
                from .jeremy_cricket import MemoryType

                memory_type = MemoryType.INSTRUCTION
            except Exception:
                pass

            await self._maybe_await(
                jeremy.remember(
                    content=(
                        f"User {user_id} session resumed after {offline_mins:.0f} minutes offline. "
                        "Check personal interaction history for context."
                    ),
                    memory_type=memory_type,
                    importance=7,
                    tags=tags,
                    source="resurrector",
                )
            )
        except Exception as exc:
            logger.warning("Could not prime Jeremy system memory: %s", exc)

    async def _log_resurrection_event(
        self,
        *,
        user_id: str,
        session_id: str,
        state: Any,
        memory_count: int,
    ) -> None:
        if not self.ingestor:
            return

        try:
            from .context_block import ContextBlock, ContextKind, ContextSource

            block = ContextBlock.new(
                content=(
                    f"Session resumed. State: {self._state_label(state)}, "
                    f"battery: {self._battery_label(state)}. Loaded {memory_count} memories."
                ),
                source=ContextSource.SYSTEM,
                kind=ContextKind.EVENT,
                author_id=user_id,
                session_id=session_id,
                importance=0.4,
                decay_hours=24.0,
                tags=["session_resume", "resurrection"],
            )
            await self._maybe_await(self.ingestor.ingest(block))
        except Exception as exc:
            logger.warning("Could not log resurrection event: %s", exc)

    def _build_resurrection_whisper(
        self,
        *,
        state: Any,
        memories: List[Any],
        episodic_summary: str,
        offline_mins: float,
    ) -> str:
        lines = ["=== Session resumed ==="]

        if offline_mins > 60:
            lines.append(f"(Last session ended {offline_mins / 60.0:.1f} hours ago)")

        mood = self._state_label(state)
        battery = self._battery_label(state)
        fragility = self._fragility_value(state)
        if mood not in {"", "stable"} or battery in {"low", "depleted"}:
            lines.append(f"Continuing from: mood={mood or 'unknown'}, battery={battery or 'unknown'}")
            if fragility > 0.3:
                lines.append(f"Fragility carried over: {fragility:.2f}; stay gentle")

        if episodic_summary:
            lines.append("")
            lines.append("=== What we did last time ===")
            lines.append(episodic_summary)

        if memories:
            lines.append("")
            lines.append("=== What I remember about you ===")
            for memory in memories:
                lines.append(self._memory_line(memory))

        lines.append("")
        lines.append("=== (Resume naturally; do not announce the memory) ===")
        return "\n".join(lines)

    def _memory_line(self, memory: Any) -> str:
        content = str(getattr(memory, "content", memory))[:120]
        memory_type = getattr(memory, "memory_type", None)
        memory_type = getattr(memory_type, "value", memory_type) or "memory"
        importance = getattr(memory, "importance", None)
        if importance is None:
            intensity = getattr(memory, "emotional_intensity", None)
            importance = f"{float(intensity):.2f}" if isinstance(intensity, (int, float)) else "n/a"
        return f"[{str(memory_type).upper()} | {importance}] {content}"

    def _state_label(self, state: Any) -> str:
        mood = getattr(state, "mood", None)
        if mood:
            return str(mood)
        current_state = getattr(self.alex, "_current_state", None)
        return str(getattr(current_state, "value", current_state) or "")

    def _battery_label(self, state: Any) -> str:
        battery = getattr(state, "battery", None)
        if battery:
            return str(battery)
        user_battery = getattr(self.alex, "_user_battery", None)
        return str(getattr(user_battery, "value", user_battery) or "")

    def _fragility_value(self, state: Any) -> float:
        fragility = getattr(state, "fragility_level", None)
        if isinstance(fragility, (int, float)):
            return max(0.0, min(1.0, float(fragility)))
        if hasattr(state, "calculate_stress_score"):
            return max(0.0, min(1.0, float(state.calculate_stress_score())))
        return 0.0

    def _build_summary(self, state: Any, memories: List[Any], offline_mins: float) -> str:
        return (
            f"{len(memories)} memories loaded, "
            f"offline {offline_mins:.0f}min, "
            f"mood={self._state_label(state) or 'unknown'}, "
            f"battery={self._battery_label(state) or 'unknown'}"
        )


__all__ = ["SessionResurrector", "ResurrectionContext"]
