#!/usr/bin/env python3
"""
WIRED ORCHESTRATOR
© 2024-2025 Rear View Foresight LLC

Integrates EQ layer with agent orchestration.

Flow:
1. User message comes in
2. EQ adaptor analyzes emotional state
3. Router recommends which agents should respond
4. Selected agents stream responses in parallel
5. All responses broadcast to room participants
"""

import asyncio
import logging
import time
import json
from typing import Dict, List, Optional, Any, AsyncIterator, Set
from collections import defaultdict, deque
from dataclasses import dataclass, field
import uuid


@dataclass
class RoomState:
    """State of a conversation room"""
    room_id: str
    room_name: str
    created_at: float = field(default_factory=time.time)
    participants: Set[str] = field(default_factory=set)
    active_agents: Set[str] = field(default_factory=set)
    conversation_history: deque = field(default_factory=lambda: deque(maxlen=50))
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamEvent:
    """Event streamed to room participants"""
    event_type: str  # "agent_start", "stream_chunk", "agent_done", "error"
    room_id: str
    agent_id: str
    timestamp: float = field(default_factory=time.time)
    payload: Dict[str, Any] = field(default_factory=dict)
    
    def to_json(self) -> str:
        return json.dumps({
            "type": self.event_type,
            "room_id": self.room_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        })


async def _collect_events(agen):
    """Collect all events from an async generator into a list."""
    events = []
    async for event in agen:
        events.append(event)
    return events


class WiredOrchestrator:
    """
    Main orchestrator connecting EQ adaptor + GPT adapter.
    
    Responsibilities:
    - Room management
    - User emotion tracking (via EQ)
    - Agent routing (via EQ recommendations)
    - Multi-agent streaming
    - Message persistence
    """
    
    def __init__(
        self,
        eq_adaptor,  # EQAdaptor instance
        gpt_adapter,  # GPTAdapter instance
        logger: Optional[logging.Logger] = None,
        max_agents_per_turn: int = 2,
        card_orchestrator=None,  # EQOrchestrator instance (fallback when GPT unavailable)
    ):
        """
        Initialize orchestrator.
        
        Args:
            eq_adaptor: Configured EQAdaptor instance
            gpt_adapter: Configured GPTAdapter instance
            logger: Python logger
            max_agents_per_turn: Max agents responding to each message
            card_orchestrator: EQOrchestrator for card-based fallback responses
        """
        self.eq = eq_adaptor
        self.gpt = gpt_adapter
        self.card_orchestrator = card_orchestrator
        self.logger = logger or logging.getLogger(__name__)
        self.max_agents_per_turn = max_agents_per_turn
        
        # Room management
        self.rooms: Dict[str, RoomState] = {}
        self.room_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        
        # Event subscribers (for WebSocket broadcast)
        self.event_subscribers: Dict[str, Set[callable]] = defaultdict(set)
        
        self.logger.info("✅ Wired Orchestrator initialized")
    
    # ========================================================================
    # ROOM MANAGEMENT
    # ========================================================================
    
    async def create_room(self, room_id: str, room_name: str) -> RoomState:
        """Create a new conversation room"""
        async with self.room_locks[room_id]:
            if room_id in self.rooms:
                return self.rooms[room_id]
            
            room = RoomState(room_id=room_id, room_name=room_name)
            self.rooms[room_id] = room
            self.logger.info(f"🏠 Room created: {room_name} ({room_id})")
            return room
    
    async def join_room(self, room_id: str, user_id: str) -> RoomState:
        """Add participant to room"""
        if room_id not in self.rooms:
            raise ValueError(f"Room {room_id} does not exist")
        
        async with self.room_locks[room_id]:
            room = self.rooms[room_id]
            room.participants.add(user_id)
            self.logger.debug(f"User {user_id} joined {room_id}")
            return room
    
    async def leave_room(self, room_id: str, user_id: str) -> None:
        """Remove participant from room"""
        if room_id not in self.rooms:
            return
        
        async with self.room_locks[room_id]:
            room = self.rooms[room_id]
            room.participants.discard(user_id)
    
    def get_room(self, room_id: str) -> Optional[RoomState]:
        """Get room state without locking (read-only)"""
        return self.rooms.get(room_id)
    
    def list_rooms(self) -> List[Dict[str, Any]]:
        """List all rooms with stats"""
        return [
            {
                "room_id": room.room_id,
                "room_name": room.room_name,
                "participants": len(room.participants),
                "active_agents": list(room.active_agents),
                "created_at": room.created_at,
            }
            for room in self.rooms.values()
        ]
    
    # ========================================================================
    # MESSAGE HANDLING
    # ========================================================================
    
    async def handle_message(
        self,
        room_id: str,
        user_id: str,
        message: str
    ) -> AsyncIterator[StreamEvent]:
        """
        Main entrypoint: handle user message in a room.
        
        Process:
        1. Analyze emotional state with EQ adaptor
        2. Get room conversation history
        3. Select agents based on emotional state
        4. Stream agent responses
        
        Yields:
            StreamEvent objects for each step
        """
        room = self.get_room(room_id)
        if not room:
            raise ValueError(f"Room {room_id} not found")
        
        self.logger.info(f"[{room_id}] {user_id}: {message[:50]}...")

        if not self.eq:
            yield StreamEvent(
                event_type="error",
                room_id=room_id,
                agent_id="system",
                payload={"error": "Emotional intelligence system not available"}
            )
            return

        if not self.gpt and not self.card_orchestrator:
            yield StreamEvent(
                event_type="error",
                room_id=room_id,
                agent_id="system",
                payload={"error": "Response generation system not available"}
            )
            return

        # Get conversation history (convert deque to list)
        history = [json.loads(msg) if isinstance(msg, str) else msg for msg in room.conversation_history]
        
        # Process through EQ adaptor
        eq_result = self.eq.process(
            user_id=user_id,
            message=message,
            history=history
        )
        
        # Store in room history
        async with self.room_locks[room_id]:
            room.conversation_history.append(json.dumps({
                "role": "user",
                "sender_id": user_id,
                "content": message,
                "care_level": eq_result['state']['care_name'],
                "timestamp": time.time(),
            }))
        
        # Log EQ state
        care_name = eq_result['state']['care_name']
        self.logger.info(f"[{room_id}] Emotional state: {care_name}")
        
        # Get recommended agents
        recommended_agents = eq_result['routing']['recommended_agents']
        if not recommended_agents:
            self.logger.warning(f"No agents recommended for care level {care_name}")
            return
        
        # Select agents (respecting max per turn)
        selected_agents = recommended_agents[:self.max_agents_per_turn]
        
        self.logger.info(f"[{room_id}] Selected agents: {selected_agents}")
        
        # Stream responses from each agent
        streaming_tasks = []
        for agent_id in selected_agents:
            task = self._stream_agent_response(
                room_id=room_id,
                agent_id=agent_id,
                user_message=message,
                conversation_history=history,
                eq_result=eq_result,
            )
            streaming_tasks.append(task)
        
        # Run all agent streams concurrently via tasks
        if streaming_tasks:
            tasks = [asyncio.create_task(_collect_events(gen)) for gen in streaming_tasks]
            done, _ = await asyncio.wait(tasks)
            for task in done:
                exc = task.exception()
                if exc:
                    self.logger.error(f"Agent streaming error: {exc}")
                    yield StreamEvent(
                        event_type="error",
                        room_id=room_id,
                        agent_id="system",
                        payload={"error": str(exc)}
                    )
                else:
                    for event in task.result():
                        yield event
    
    async def _stream_agent_response(
        self,
        room_id: str,
        agent_id: str,
        user_message: str,
        conversation_history: List[Dict],
        eq_result: Dict[str, Any],
    ) -> AsyncIterator[StreamEvent]:
        """
        Stream a single agent's response.
        
        Yields:
            StreamEvent for each chunk
        """
        room = self.get_room(room_id)
        if not room:
            return

        # Announce agent start
        agent_name = agent_id
        if self.gpt:
            agent_info = self.gpt.get_agent_info(agent_id)
            if not agent_info:
                yield StreamEvent(
                    event_type="error",
                    room_id=room_id,
                    agent_id=agent_id,
                    payload={"error": f"Unknown agent '{agent_id}'"}
                )
                return
            agent_name = agent_info.get('name', agent_id)

        yield StreamEvent(
            event_type="agent_start",
            room_id=room_id,
            agent_id=agent_id,
            payload={
                "agent_name": agent_name,
                "care_level": eq_result['state']['care_name'],
            }
        )
        
        try:
            response_text = ""

            if self.gpt:
                # Stream from GPT
                async for chunk in self.gpt.stream_response(
                    agent_id=agent_id,
                    user_message=user_message,
                    conversation_history=conversation_history,
                    eq_result=eq_result,
                ):
                    response_text += chunk
                    
                    yield StreamEvent(
                        event_type="stream_chunk",
                        room_id=room_id,
                        agent_id=agent_id,
                        payload={"chunk": chunk}
                    )
                    
                    if len(chunk) > 10:
                        await asyncio.sleep(0.01)

            elif self.card_orchestrator:
                # Fallback: use card-based response system
                try:
                    card_response = self.card_orchestrator.process_message(
                        user_message=user_message,
                        user_id=room_id,
                    )
                    response_text = card_response.response_text
                except Exception as e:
                    self.logger.error(f"Card fallback error: {e}")
                    response_text = "I'm here for you. Tell me more about what's going on."

                # Yield card response as a single chunk
                yield StreamEvent(
                    event_type="stream_chunk",
                    room_id=room_id,
                    agent_id=agent_id,
                    payload={"chunk": response_text}
                )
            
            # Store final response in history
            async with self.room_locks[room_id]:
                room.conversation_history.append(json.dumps({
                    "role": "agent",
                    "agent_id": agent_id,
                    "content": response_text,
                    "care_level": eq_result['state']['care_name'],
                    "timestamp": time.time(),
                }))
            
            # Yield completion event
            yield StreamEvent(
                event_type="agent_done",
                room_id=room_id,
                agent_id=agent_id,
                payload={
                    "response_length": len(response_text),
                    "tokens_estimated": len(response_text) // 4,  # Rough estimate
                }
            )
        
        finally:
            # Mark agent inactive
            async with self.room_locks[room_id]:
                room.active_agents.discard(agent_id)
    
    # ========================================================================
    # MEMORY MANAGEMENT
    # ========================================================================
    
    def store_memory(
        self,
        user_id: str,
        content: str,
        memory_type: str = "episodic",
        tags: Optional[List[str]] = None
    ) -> None:
        """Store a memory about a user"""
        if not self.eq:
            self.logger.warning("EQ adaptor not available — cannot store memory")
            return
        self.eq.store_memory(user_id, content, memory_type, tags)
        self.logger.debug(f"Stored {memory_type} memory for {user_id}")
    
    def recall_memory(self, user_id: str, query: str = "") -> str:
        """Get formatted memory context for a user"""
        if not self.eq:
            return ""
        return self.eq.get_memory_context(user_id, query)
    
    # ========================================================================
    # EMOTION TRACKING
    # ========================================================================
    
    def get_user_emotional_state(self, user_id: str) -> Dict[str, Any]:
        """Get current emotional state for a user"""
        if not self.eq:
            return {"error": "EQ adaptor not available"}
        state = self.eq.jeremy.get_emotional_state(user_id)
        return {
            "care_level": state.care_level,
            "care_name": ["AMBIENT", "ATTENTIVE", "CARE", "TOTAL_CARE_MANDATE"][state.care_level],
            "complexity": state.complexity_score,
            "velocity": state.emotional_velocity,
            "timestamp": state.timestamp,
        }
    
    # ========================================================================
    # EVENT SUBSCRIPTION (for WebSocket broadcast)
    # ========================================================================
    
    def subscribe(self, room_id: str, callback: callable) -> None:
        """Subscribe to room events"""
        self.event_subscribers[room_id].add(callback)
    
    def unsubscribe(self, room_id: str, callback: callable) -> None:
        """Unsubscribe from room events"""
        self.event_subscribers[room_id].discard(callback)
    
    async def broadcast_event(self, event: StreamEvent) -> None:
        """Broadcast event to all subscribers in room"""
        callbacks = self.event_subscribers.get(event.room_id, set())
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                self.logger.error(f"Error in event callback: {e}")
    
    # ========================================================================
    # SYSTEM INFO
    # ========================================================================
    
    def get_system_health(self) -> Dict[str, Any]:
        """Get system health status"""
        total_participants = sum(len(room.participants) for room in self.rooms.values())
        total_active_agents = sum(len(room.active_agents) for room in self.rooms.values())
        
        return {
            "status": "healthy",
            "rooms_active": len(self.rooms),
            "total_participants": total_participants,
            "agents_streaming": total_active_agents,
            "available_agents": self.gpt.list_agents() if self.gpt else [],
        }
