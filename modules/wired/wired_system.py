#!/usr/bin/env python3
"""
WIRED SYSTEM — Jeremy Cricket + BotManager + NudgeQueue
© 2024-2025 Rear View Foresight LLC
"Feic Mo Chroí" — See My Heart

Complete integration of:
- Jeremy Cricket (EQ engine with nudge capability)
- BotManager (bot orchestration)
- NudgeQueue (async event decoupling)
- Orchestrator (message routing)

ARCHITECTURE:
═════════════

User sends message
        ↓
Orchestrator.handle_message()
        ├─ Jeremy analyzes emotional state
        ├─ Decides which bots should respond
        └─ For each bot: await bot_manager.nudge(room_id, hint)
                                ↓
                        NudgeQueue.nudge() (enqueues event)
                                ↓
                        Returns immediately (async)
                                ↓
                        NudgeConsumer picks it up
                                ↓
                        Actually calls BotManager.nudge()
                                ↓
                        Bot starts responding

KEY: Jeremy doesn't wait for bot to actually respond.
It just nudges the queue and moves on. Consumer handles delivery.

USAGE IN main.py:
═════════════════

    from wired_system import (
        create_jeremy_cricket,
        BotManager,
        WiredOrchestrator,
        NudgeQueue,
        NudgeConsumer,
    )

    # Create queue
    nudge_q = NudgeQueue()

    # Create Jeremy (with queue, not bot_manager directly)
    jeremy = await create_jeremy_cricket(
        config=config,
        memory_system=memory,
        bot_manager=nudge_q,  # Pass queue, not actual BotManager
    )

    # Create BotManager
    bot_manager = BotManager(data_dir, hub)

    # Start consumer (background task)
    consumer = NudgeConsumer(nudge_q, bot_manager)
    asyncio.create_task(consumer.run())

    # Create orchestrator
    orchestrator = WiredOrchestrator(jeremy, bot_manager, ...)

    # Now when orchestrator handles a message:
    # 1. Jeremy analyzes emotional state
    # 2. Orchestrator nudges bots via queue (returns immediately)
    # 3. Consumer delivers nudges to actual BotManager
    # 4. Bots respond when ready
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable, AsyncGenerator
from abc import ABC, abstractmethod
from collections import deque, defaultdict

logger = logging.getLogger(__name__)


# ============================================================================
# NUDGE QUEUE (Decoupling Layer)
# ============================================================================

@dataclass
class NudgeEvent:
    """Event representing a nudge to a bot"""
    room_id: str
    hint: str  # "respond_to_emotional_escalation", "join_conversation", etc.
    enqueued_at: float = field(default_factory=time.time)

    def age_seconds(self) -> float:
        return time.time() - self.enqueued_at


class NudgeQueue:
    """
    Async queue that exposes the nudge() interface Jeremy expects.
    
    Jeremy calls: await self._bm.nudge(room_id, hint)
    This object satisfies that contract by enqueuing instead of delivering.
    """

    def __init__(self, maxsize: int = 64) -> None:
        self._queue: asyncio.Queue[NudgeEvent] = asyncio.Queue(maxsize=maxsize)
        logger.info("NudgeQueue: initialized (maxsize=%d)", maxsize)

    async def nudge(self, room_id: str, hint: str) -> bool:
        """
        Enqueue a nudge event.
        
        Returns True if enqueued, False if queue is full.
        Jeremy uses return value to decide whether to apply cooldown:
        - True → nudge accepted, apply cooldown
        - False → queue full, retry sooner
        """
        event = NudgeEvent(room_id=room_id, hint=hint)
        try:
            self._queue.put_nowait(event)
            logger.debug("NudgeQueue: enqueued for room '%s' (hint=%s, qsize=%d)",
                        room_id, hint, self._queue.qsize())
            return True
        except asyncio.QueueFull:
            logger.warning("NudgeQueue: FULL — dropped nudge for room '%s'", room_id)
            return False

    async def get(self) -> NudgeEvent:
        """Get next nudge event (used by consumer)"""
        return await self._queue.get()

    def task_done(self) -> None:
        """Mark task as done (used by consumer)"""
        self._queue.task_done()

    @property
    def qsize(self) -> int:
        """Current queue size"""
        return self._queue.qsize()


class NudgeConsumer:
    """
    Background task that drains NudgeQueue and delivers to BotManager.
    
    Construct once, start with: asyncio.create_task(consumer.run())
    Stop with: consumer.stop() — waits for current delivery to finish.
    """

    def __init__(
        self,
        queue: NudgeQueue,
        bot_manager: Any,  # BotManager instance
        max_age: float = 30.0,  # Discard nudges older than this
    ) -> None:
        self._queue = queue
        self._bm = bot_manager
        self._max_age = max_age
        self._running = False
        logger.info("NudgeConsumer: created (max_age=%.1fs)", max_age)

    async def run(self) -> None:
        """Main consumer loop"""
        self._running = True
        logger.info("NudgeConsumer: started")

        while self._running:
            try:
                # Wait for nudge with timeout so we can respond to stop() signal
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                age = event.age_seconds()

                # Discard stale events
                if age > self._max_age:
                    logger.debug(
                        "NudgeConsumer: discarding stale nudge for '%s' (%.1fs old)",
                        event.room_id, age
                    )
                    continue

                # Deliver to BotManager
                delivered = await self._bm.nudge(event.room_id, event.hint)

                if delivered:
                    logger.info(
                        "NudgeConsumer: delivered nudge to '%s' (hint=%s, age=%.2fs)",
                        event.room_id, event.hint, age
                    )
                else:
                    logger.debug(
                        "NudgeConsumer: no eligible bot in '%s' (hint=%s)",
                        event.room_id, event.hint
                    )

            except Exception as exc:
                logger.error(
                    "NudgeConsumer: delivery error for '%s': %s",
                    event.room_id, exc, exc_info=True
                )
            finally:
                self._queue.task_done()

        logger.info("NudgeConsumer: stopped")

    def stop(self) -> None:
        """Signal consumer to stop"""
        self._running = False


# ============================================================================
# JEREMY CRICKET WITH NUDGE SUPPORT
# ============================================================================

@dataclass
class EmotionalState:
    """User's current emotional state"""
    user_id: str = ""
    care_level: int = 0  # 0=AMBIENT, 1=ATTENTIVE, 2=CARE, 3=CRISIS
    complexity_score: float = 0.5
    emotional_velocity: float = 0.5
    logic_variance: float = 0.5
    timestamp: float = field(default_factory=time.time)
    last_nudge_time: float = 0.0


class InputScorer:
    """Scores message complexity and emotional velocity"""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)

    def score(self, text: str, history: Optional[List[Dict]]) -> tuple:
        """Return (complexity: 0-1, velocity: 0-1)"""
        if not text:
            return 0.5, 0.5

        complexity = self._score_complexity(text)
        velocity = self._score_velocity(text, history)
        return complexity, velocity

    def _score_complexity(self, text: str) -> float:
        """Higher = more abstract/complex thought"""
        score = 0.5
        text_lower = text.lower()
        word_count = len(text.split())

        if word_count > 30:
            score += 0.15
        if word_count > 50:
            score += 0.1

        abstract_words = ["maybe", "might", "could", "seem", "appear"]
        for word in abstract_words:
            if word in text_lower:
                score += 0.1

        return min(1.0, score)

    def _score_velocity(self, text: str, history: Optional[List[Dict]]) -> float:
        """Higher = faster emotional changes"""
        score = 0.5

        if "!!!" in text or "???" in text or text.isupper():
            score += 0.25

        emotional_words = ["overwhelm", "struggling", "hurt", "angry", "sad", "happy"]
        for word in emotional_words:
            if word in text.lower():
                score += 0.15

        return min(1.0, score)


class CharacterEngine:
    """State machine for care level transitions"""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.care_threshold = 0.65
        self.state_names = ["AMBIENT", "ATTENTIVE", "CARE", "TOTAL_CARE_MANDATE"]

    def transition(self, current_level: int, logic_variance: float) -> int:
        """Transition to new care level"""
        if logic_variance > self.care_threshold:
            next_level = min(current_level + 1, 3)
        elif logic_variance < self.care_threshold * 0.5:
            next_level = max(current_level - 1, 0)
        else:
            next_level = current_level

        if next_level != current_level:
            self.logger.info(
                "Care transition: %s → %s (variance=%.2f)",
                self.state_names[current_level],
                self.state_names[next_level],
                logic_variance
            )

        return next_level


class JeremyCricket:
    """
    Emotional intelligence engine with nudge capability.
    
    NOW WIRED TO:
    - Accept a NudgeQueue instance (or anything with async nudge() method)
    - Call nudge() when care level escalates
    - Track nudge cooldowns to avoid spam
    """

    def __init__(
        self,
        bot_manager: Any,  # NudgeQueue or BotManager (must have async nudge())
        logger: Optional[logging.Logger] = None,
        nudge_cooldown_seconds: float = 5.0,
    ):
        self.logger = logger or logging.getLogger(__name__)
        self._bm = bot_manager  # NudgeQueue instance
        self._nudge_cooldown = nudge_cooldown_seconds
        self.scorer = InputScorer(self.logger)
        self.engine = CharacterEngine(self.logger)
        self.user_states: Dict[str, EmotionalState] = {}
        self.logger.info("JeremyCricket: initialized (nudge_cooldown=%.1fs)", nudge_cooldown_seconds)

    def process_message(
        self, 
        user_id: str, 
        text: str, 
        history: Optional[List[Dict]] = None,
        room_id: Optional[str] = None,
    ) -> EmotionalState:
        """
        Analyze message and update emotional state.
        
        If care level escalates and cooldown has passed, nudge the bots.
        """
        complexity, velocity = self.scorer.score(text, history)

        # Get or create user state
        if user_id not in self.user_states:
            self.user_states[user_id] = EmotionalState(user_id=user_id)

        state = self.user_states[user_id]
        old_care_level = state.care_level

        state.complexity_score = complexity
        state.emotional_velocity = velocity
        state.logic_variance = velocity  # For now, use velocity as variance
        state.timestamp = time.time()

        # Transition care level
        state.care_level = self.engine.transition(state.care_level, state.logic_variance)

        # If escalated, nudge the bots (and we have a room context)
        if state.care_level > old_care_level and room_id:
            now = time.time()
            if now - state.last_nudge_time >= self._nudge_cooldown:
                hint = f"emotional_escalation_{state.care_level}"
                asyncio.create_task(self._nudge_bots(room_id, user_id, hint, state.care_level))
                state.last_nudge_time = now

        return state

    async def _nudge_bots(self, room_id: str, user_id: str, hint: str, care_level: int) -> None:
        """Nudge bots (fire and forget)"""
        try:
            accepted = await self._bm.nudge(room_id, hint)
            if accepted:
                self.logger.info(
                    "JeremyCricket: nudged bots in '%s' (user=%s, care=%d, hint=%s)",
                    room_id, user_id, care_level, hint
                )
            else:
                self.logger.debug(
                    "JeremyCricket: nudge rejected for '%s' (queue full?)",
                    room_id
                )
        except Exception as exc:
            self.logger.error("JeremyCricket: nudge error: %s", exc, exc_info=True)

    def get_emotional_state(self, user_id: str) -> Dict[str, Any]:
        """Get current emotional state for a user"""
        state = self.user_states.get(user_id, EmotionalState(user_id=user_id))
        return {
            "user_id": user_id,
            "care_level": state.care_level,
            "care_name": ["AMBIENT", "ATTENTIVE", "CARE", "TOTAL_CARE_MANDATE"][state.care_level],
            "complexity": state.complexity_score,
            "velocity": state.emotional_velocity,
            "timestamp": state.timestamp,
        }


# ============================================================================
# BOT MANAGER (Stub for now, you fill in the real implementation)
# ============================================================================

class BotManager:
    """
    Bot orchestration manager.
    
    This is a STUB. You'll implement the real thing based on your bot_llm_adapter.py
    
    It MUST expose:
    - async def nudge(room_id: str, hint: str) -> bool
    - Any other bot management methods you need
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.active_bots: Dict[str, List[str]] = defaultdict(list)  # room_id -> [bot_ids]
        self.logger.info("BotManager: initialized")

    async def nudge(self, room_id: str, hint: str) -> bool:
        """
        Receive a nudge from Jeremy and decide if bots should respond.
        
        Returns True if a bot accepted the nudge, False otherwise.
        
        IMPLEMENT THIS with your actual bot logic:
        - Look up which bots are in the room
        - Filter by the hint (which specialties should respond?)
        - Start bot responses asynchronously
        - Return True if at least one bot is responding
        """
        self.logger.info("BotManager.nudge: room=%s, hint=%s", room_id, hint)

        # STUB: Just return True for now
        # TODO: Implement real bot selection and startup logic
        return True

    async def bot_response_stream(
        self, 
        bot_id: str, 
        room_id: str, 
        user_message: str,
        hint: str,
    ) -> AsyncGenerator[str, None]:
        """
        Stream a response from a bot.
        
        IMPLEMENT THIS with your bot_llm_adapter.py
        """
        # STUB
        yield "Bot response stub"


# ============================================================================
# WIRED ORCHESTRATOR
# ============================================================================

class WiredOrchestrator:
    """
    Message orchestrator that ties Jeremy + BotManager + NudgeQueue together.
    
    When a user message arrives:
    1. Jeremy analyzes emotional state
    2. If care level escalates, nudge is queued (non-blocking)
    3. Consumer picks up nudge and delivers to BotManager
    4. Bots respond when ready (asynchronously)
    """

    def __init__(
        self,
        jeremy: JeremyCricket,
        bot_manager: BotManager,
        logger: Optional[logging.Logger] = None,
    ):
        self.jeremy = jeremy
        self.bot_manager = bot_manager
        self.logger = logger or logging.getLogger(__name__)
        self.rooms: Dict[str, Dict[str, Any]] = {}
        self.logger.info("WiredOrchestrator: initialized")

    async def handle_message(
        self,
        room_id: str,
        user_id: str,
        message: str,
        history: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Handle incoming user message.
        
        Returns immediately (Jeremy's nudge is async).
        """
        # Ensure room exists
        if room_id not in self.rooms:
            self.rooms[room_id] = {"messages": deque(maxlen=50), "users": set()}

        # Store message
        self.rooms[room_id]["messages"].append({
            "user_id": user_id,
            "text": message,
            "timestamp": time.time(),
        })

        # Process through Jeremy (includes async nudging)
        emotional_state = self.jeremy.process_message(
            user_id=user_id,
            text=message,
            history=history or [],
            room_id=room_id,  # IMPORTANT: pass room_id so Jeremy can nudge
        )

        self.logger.info(
            "Orchestrator: handled message in '%s' from %s (care=%s)",
            room_id, user_id, emotional_state.care_name
        )

        return {
            "ok": True,
            "room_id": room_id,
            "user_id": user_id,
            "emotional_state": self.jeremy.get_emotional_state(user_id),
        }

    def get_room_state(self, room_id: str) -> Dict[str, Any]:
        """Get current state of a room"""
        if room_id not in self.rooms:
            return {"error": "room not found"}

        room = self.rooms[room_id]
        return {
            "room_id": room_id,
            "message_count": len(room["messages"]),
            "users": list(room["users"]),
        }


# ============================================================================
# FACTORY FUNCTIONS
# ============================================================================

async def create_wired_system(
    logger: Optional[logging.Logger] = None,
    nudge_queue_size: int = 64,
    nudge_cooldown: float = 5.0,
) -> tuple:
    """
    Create a complete wired system.
    
    Returns: (jeremy, bot_manager, nudge_queue, nudge_consumer, orchestrator)
    """
    if not logger:
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger("wired_system")

    logger.info("Creating wired system...")

    # 1. Create nudge queue
    nudge_q = NudgeQueue(maxsize=nudge_queue_size)

    # 2. Create Jeremy with queue (NOT bot_manager directly)
    jeremy = JeremyCricket(
        bot_manager=nudge_q,
        logger=logger,
        nudge_cooldown_seconds=nudge_cooldown,
    )

    # 3. Create BotManager
    bot_manager = BotManager(logger=logger)

    # 4. Create consumer (but don't run it yet)
    consumer = NudgeConsumer(nudge_q, bot_manager)

    # 5. Create orchestrator
    orchestrator = WiredOrchestrator(jeremy, bot_manager, logger=logger)

    logger.info("Wired system created successfully")

    return jeremy, bot_manager, nudge_q, consumer, orchestrator


# ============================================================================
# QUICK TEST
# ============================================================================

async def demo():
    """Quick demo of the wired system"""
    logger = logging.getLogger("demo")
    logging.basicConfig(level=logging.DEBUG)

    jeremy, bot_manager, nudge_q, consumer, orchestrator = await create_wired_system()

    # Start consumer in background
    consumer_task = asyncio.create_task(consumer.run())

    # Simulate messages
    room_id = "demo-room"
    user_id = "user1"

    logger.info("\n=== TEST 1: Normal message ===")
    result1 = await orchestrator.handle_message(room_id, user_id, "Hi, how are you?")
    logger.info("Result: %s", result1)
    await asyncio.sleep(0.5)  # Let consumer process

    logger.info("\n=== TEST 2: Emotional escalation ===")
    result2 = await orchestrator.handle_message(
        room_id, user_id,
        "Actually... I'm really struggling. Everything feels overwhelming."
    )
    logger.info("Result: %s", result2)
    await asyncio.sleep(0.5)

    # Check queue
    logger.info("\n=== QUEUE STATUS ===")
    logger.info("Queue size: %d", nudge_q.qsize)

    # Cleanup
    consumer.stop()
    await asyncio.sleep(0.5)
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    logger.info("\n✅ Demo complete")


if __name__ == "__main__":
    asyncio.run(demo())
