# PubCast AI — orchestrator_raw.py
# Copyright © 2024–2026 Josie Curtsey Cobbley (Joshua Cobbley)
# Rearview Foresight LLC — All Rights Reserved
# Feic Mo Chroí — See My Heart
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Iterable, List, Sequence, Tuple, Optional

try:
    from .agents.base import AgentRegistry, AgentRuntime, Delta
except ImportError:
    AgentRegistry = AgentRuntime = Delta = None  # agents subpackage not present
from .rooms import Participant, Room, RoomManager
from .schemas import DoneEvent, ErrorEvent, ParticipantRole, RoomSnapshot, SayEvent, StreamChunkEvent

logger = logging.getLogger(__name__)

ConversationTurn = Dict[str, str]


class ConversationOrchestrator:
    """Coordinates human and agent turns inside a room."""

    def __init__(
        self,
        room_manager: RoomManager,
        agent_registry: AgentRegistry,
        *,
        max_agents_per_turn: int = 2,
        max_context_messages: int = 20,
        agent_timeout: float = 30.0,
        max_concurrent_agents: int = 6,
    ):
        self._room_manager = room_manager
        self._agent_registry = agent_registry
        self._max_agents_per_turn = max_agents_per_turn
        self._max_context_messages = max_context_messages
        self._agent_timeout = agent_timeout
        self._agent_semaphore = asyncio.Semaphore(max_concurrent_agents)

        self._room_histories: Dict[str, Deque[ConversationTurn]] = defaultdict(lambda: deque(maxlen=max_context_messages))
        self._room_agents: Dict[str, Dict[str, AgentRuntime]] = defaultdict(dict)
        self._room_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def create_room(
        self,
        room_id: str,
        room_name: str,
        *,
        voice_out_enabled: bool = False,
        avatar_id: str | None = None,
    ) -> Room:
        room = await self._room_manager.create_room(
            room_id,
            room_name,
            voice_out_enabled=voice_out_enabled,
            avatar_id=avatar_id,
        )
        _ = self._room_locks[room_id]
        _ = self._room_histories[room_id]
        return room

    async def add_agents(
        self,
        room_id: str,
        agent_ids: Iterable[str],
        *,
        prepared: Optional[Dict[str, AgentRuntime]] = None,
    ) -> List[str]:
        room = await self._room_manager.require_room(room_id)
        async with self._room_locks[room_id]:
            runtime_map = self._room_agents[room_id]
            attached: List[str] = []
            prepared = prepared or {}
            for agent_id in agent_ids:
                if agent_id in runtime_map:
                    attached.append(agent_id)
                    continue
                runtime = prepared.get(agent_id)
                if runtime is None:
                    try:
                        runtime = self._agent_registry.instantiate(agent_id)
                    except KeyError:
                        logger.warning("Agent %s not configured; skipping", agent_id)
                        continue
                runtime_map[agent_id] = runtime
                attached.append(agent_id)
            if attached:
                event = await room.attach_agents(attached)
                await room.broadcast_event(event)
            return attached

    async def list_rooms(self) -> List[RoomSnapshot]:
        return await self._room_manager.list_rooms()

    async def handle_human_message(self, room_id: str, sender_id: str, text: str) -> None:
        room = await self._room_manager.require_room(room_id)
        say_event = SayEvent(room_id=room_id, sender_id=sender_id, text=text)
        await room.broadcast_event(say_event)
        history = self._room_histories[room_id]
        history.append({"role": "user", "sender_id": sender_id, "text": text})
        await self._schedule_agents(room_id, source_event=say_event)

    async def join_room(self, room_id: str, participant_id: str, display_name: str, websocket) -> None:
        room = await self._room_manager.require_room(room_id)
        participant = Participant(
            participant_id=participant_id,
            display_name=display_name,
            role=ParticipantRole.HUMAN,
            websocket=websocket,
        )
        events = await room.add_participant(participant)
        for event in events:
            await room.broadcast_event(event)
        await room.send_to(participant_id, room.state_event())

    async def leave_room(self, room_id: str, participant_id: str) -> None:
        room = await self._room_manager.require_room(room_id)
        events = await room.remove_participant(participant_id)
        for event in events:
            await room.broadcast_event(event)

    async def _schedule_agents(self, room_id: str, source_event: SayEvent) -> None:
        async with self._room_locks[room_id]:
            runtime_map = self._room_agents.get(room_id)
            if not runtime_map:
                return
            ready_agents = [runtime for runtime in runtime_map.values() if runtime.ready()]
            if not ready_agents:
                return
            selected = self._select_agents(ready_agents)
            if not selected:
                return
            for runtime in selected:
                runtime.mark_invocation()
                asyncio.create_task(self._run_agent_turn(room_id, runtime, source_event))

    def _select_agents(self, runtimes: Sequence[AgentRuntime]) -> List[AgentRuntime]:
        now_ms = time.time() * 1000
        scored: List[Tuple[float, AgentRuntime]] = []
        for runtime in runtimes:
            cfg = runtime.config
            recency = (now_ms - runtime.last_invoked) / max(cfg.cooldown_ms, 1)
            failure_penalty = (1 + runtime.failures) ** 2
            score = (cfg.priority - recency) / failure_penalty
            scored.append((score, runtime))
        scored.sort(key=lambda item: item[0], reverse=True)
        limit = min(self._max_agents_per_turn, len(scored))
        return [runtime for _, runtime in scored[:limit]]

    async def _run_agent_turn(self, room_id: str, runtime: AgentRuntime, source_event: SayEvent) -> None:
        room = await self._room_manager.require_room(room_id)
        adapter = runtime.adapter
        agent_config = runtime.config
        sender_id = f"agent:{agent_config.agent_id}"
        history = list(self._room_histories[room_id])
        prompt = source_event.text
        try:
            async with self._agent_semaphore:
                await asyncio.wait_for(
                    self._stream_agent_output(room, sender_id, adapter, prompt, history, runtime),
                    timeout=self._agent_timeout,
                )
        except asyncio.TimeoutError:
            runtime.mark_failure()
            error_event = ErrorEvent(room_id=room_id, sender_id=sender_id, message="timeout")
            logger.warning("Agent %s timed out in room %s", agent_config.agent_id, room_id)
            await room.broadcast_event(error_event)
        except Exception as exc:  # noqa: BLE001
            runtime.mark_failure()
            logger.exception("Agent %s failed: %s", agent_config.agent_id, exc)
            error_event = ErrorEvent(room_id=room_id, sender_id=sender_id, message=str(exc))
            await room.broadcast_event(error_event)
        else:
            runtime.mark_success()

    async def _stream_agent_output(
        self,
        room: Room,
        sender_id: str,
        adapter,
        prompt: str,
        history: Sequence[ConversationTurn],
        runtime: AgentRuntime,
    ) -> None:
        buffer: List[str] = []
        stream = adapter.stream_reply(prompt=prompt, context=history, metadata={"room_id": room.room_id})
        if not hasattr(stream, "__aiter__"):
            await stream
            return

        async for delta in stream:
            if not isinstance(delta, Delta):
                continue
            if delta.text:
                buffer.append(delta.text)
                chunk = StreamChunkEvent(room_id=room.room_id, sender_id=sender_id, delta=delta.text)
                await room.broadcast_event(chunk)
            if delta.is_final:
                done = DoneEvent(room_id=room.room_id, sender_id=sender_id, usage=delta.usage)
                await room.broadcast_event(done)
        final_text = "".join(buffer).strip()
        if final_text:
            say_event = SayEvent(room_id=room.room_id, sender_id=sender_id, text=final_text)
            await room.broadcast_event(say_event)
            self._room_histories[room.room_id].append(
                {"role": "assistant", "sender_id": sender_id, "text": final_text}
            )

    async def shutdown(self) -> None:
        """Close any adapter clients to avoid leaking sockets."""
        tasks = []
        for runtime_map in self._room_agents.values():
            for runtime in runtime_map.values():
                closer = getattr(runtime.adapter, "aclose", None)
                if callable(closer):
                    tasks.append(closer())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

__all__ = ["ConversationOrchestrator"]