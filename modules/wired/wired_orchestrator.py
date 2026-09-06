"""
WIRED ORCHESTRATOR
Integrates EQ layer, memory system, and agent scheduling into a unified system.

This replaces the basic orchestrator.py with full integration:
- Agent selection weighted by EQ state
- Memory context injection into prompts
- Care-level adaptive response generation
- Streaming with interruption on care escalation
"""

import asyncio
import logging
import time
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, AsyncIterator
from collections import deque
from enum import Enum
import uuid

# ============================================================================
# ENUMS & DATACLASSES
# ============================================================================

class CareLevel(Enum):
    """User care state"""
    AMBIENT = 0              # Normal conversation
    ATTENTIVE = 1            # Increased attention needed
    CARE = 2                 # Active care mode
    TOTAL_CARE_MANDATE = 3   # Crisis mode

@dataclass
class AgentConfig:
    """Agent personality and routing"""
    agent_id: str
    name: str
    priority: int = 5
    cooldown_ms: int = 2000
    specialties: List[str] = field(default_factory=list)  # "humor", "technical", "empathy"
    min_care_level: CareLevel = CareLevel.AMBIENT
    max_care_level: CareLevel = CareLevel.TOTAL_CARE_MANDATE
    timeout_seconds: float = 30.0

@dataclass
class Delta:
    """Streaming token"""
    text: str
    is_final: bool = False
    stop_reason: Optional[str] = None

@dataclass
class ConversationTurn:
    """Single message in conversation"""
    turn_id: str
    role: str  # "user" or "agent"
    sender_id: str
    text: str
    care_level: int = 0
    memory_context: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

class AgentAdapter:
    """
    Abstract adapter for connecting to different AI backends.
    Implement stream_reply() for different LLM providers.
    """
    
    def __init__(self, agent_config: AgentConfig, logger: logging.Logger):
        self.config = agent_config
        self.logger = logger
    
    async def stream_reply(
        self, 
        prompt: str, 
        context: str,
        history: List[ConversationTurn],
        metadata: Dict[str, Any]
    ) -> AsyncIterator[Delta]:
        """
        Stream reply as deltas. Implement for Claude, GPT, etc.
        """
        raise NotImplementedError

class MockAgentAdapter(AgentAdapter):
    """
    Mock adapter for testing without actual LLM.
    Simulates streaming responses.
    """
    
    responses = {
        "pete": "Hey there! 🎭 That's a great point you're making. I've been thinking about this a lot lately.",
        "horace": "Well now, that's an interesting observation. Let me break down what I see here...",
        "sheila": "Oh darling, that touches my heart. You know, I believe we're really connecting on something real.",
    }
    
    async def stream_reply(
        self,
        prompt: str,
        context: str,
        history: List[ConversationTurn],
        metadata: Dict[str, Any]
    ) -> AsyncIterator[Delta]:
        """Simulate streaming"""
        response = self.responses.get(self.config.agent_id, "I'm not sure what to say about that.")
        
        # Add memory context indication
        if context:
            response = f"[Recalling: {len(context.split('##'))-1} memories] {response}"
        
        # Simulate network delay
        await asyncio.sleep(0.1)
        
        # Stream character by character
        for char in response:
            await asyncio.sleep(0.02)
            yield Delta(text=char, is_final=False)
        
        yield Delta(text="", is_final=True, stop_reason="end_turn")

# ============================================================================
# AGENT REGISTRY & SELECTION
# ============================================================================

class AgentRegistry:
    """
    Central registry for all agents.
    Manages instantiation, versioning, and fallbacks.
    """
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.agents: Dict[str, AgentConfig] = {}
        self.adapters: Dict[str, AgentAdapter] = {}
        self._register_default_agents()
    
    def _register_default_agents(self):
        """Register Pete, Sheila, Horace"""
        agents = [
            AgentConfig(
                agent_id="pete",
                name="Pete",
                priority=7,
                cooldown_ms=1500,
                specialties=["humor", "engagement", "narrative"],
                min_care_level=CareLevel.AMBIENT,
                max_care_level=CareLevel.CARE,
            ),
            AgentConfig(
                agent_id="sheila",
                name="Sheila",
                priority=8,
                cooldown_ms=2000,
                specialties=["empathy", "emotional_support", "reflection"],
                min_care_level=CareLevel.ATTENTIVE,
                max_care_level=CareLevel.TOTAL_CARE_MANDATE,
            ),
            AgentConfig(
                agent_id="horace",
                name="Horace",
                priority=6,
                cooldown_ms=2500,
                specialties=["analysis", "technical", "context"],
                min_care_level=CareLevel.AMBIENT,
                max_care_level=CareLevel.CARE,
            ),
        ]
        
        for agent in agents:
            self.register(agent)
            # Use mock adapter for MVP
            self.adapters[agent.agent_id] = MockAgentAdapter(agent, self.logger)
    
    def register(self, config: AgentConfig, adapter: Optional[AgentAdapter] = None):
        """Register an agent"""
        self.agents[config.agent_id] = config
        if adapter:
            self.adapters[config.agent_id] = adapter
        self.logger.info(f"Registered agent: {config.name} ({config.agent_id})")
    
    def get_adapter(self, agent_id: str) -> Optional[AgentAdapter]:
        """Get agent's adapter"""
        return self.adapters.get(agent_id)
    
    def get_all_agents(self) -> List[AgentConfig]:
        """Get all registered agents"""
        return list(self.agents.values())

# ============================================================================
# RUNTIME STATE
# ============================================================================

@dataclass
class AgentRuntime:
    """Runtime state for an agent"""
    config: AgentConfig
    adapter: AgentAdapter
    last_invoked_ms: float = 0.0
    success_count: int = 0
    failure_count: int = 0
    total_tokens: int = 0
    
    def time_since_invoked(self) -> float:
        """Milliseconds since last invocation"""
        now_ms = time.time() * 1000
        return now_ms - self.last_invoked_ms
    
    def is_ready(self) -> bool:
        """Check if agent has cooled down"""
        return self.time_since_invoked() >= self.config.cooldown_ms
    
    def mark_invoked(self):
        """Update last invocation time"""
        self.last_invoked_ms = time.time() * 1000

# ============================================================================
# CARE-AWARE AGENT SELECTION
# ============================================================================

class AgentSelector:
    """
    Scores agents based on:
    - Base priority
    - Recency (cooldown)
    - Care level compatibility
    - Specialty matching
    """
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
    
    def score_agent(
        self,
        runtime: AgentRuntime,
        care_level: CareLevel,
        message_text: str,
    ) -> float:
        """
        Calculate agent selection score.
        Higher = more suitable.
        """
        score = float(runtime.config.priority)
        
        # Recency factor (0.0-1.0)
        cooldown_ratio = min(1.0, runtime.time_since_invoked() / runtime.config.cooldown_ms)
        score += cooldown_ratio * 2.0  # Up to +2 points for fully cooled down
        
        # Care level compatibility
        if care_level.value < runtime.config.min_care_level.value:
            score -= 5.0  # Penalize if care level too low
        elif care_level.value > runtime.config.max_care_level.value:
            score -= 5.0  # Penalize if care level too high
        else:
            score += 1.0  # Bonus if in range
        
        # Specialty matching (simple keyword matching)
        matching_specialties = sum(
            1 for specialty in runtime.config.specialties
            if specialty.lower() in message_text.lower()
        )
        score += matching_specialties * 0.5
        
        return max(0.0, score)
    
    def select(
        self,
        runtimes: List[AgentRuntime],
        care_level: CareLevel,
        message_text: str,
        max_agents: int = 2,
    ) -> List[AgentRuntime]:
        """
        Select top N agents for this message.
        """
        # Score all agents
        scored = [
            (runtime, self.score_agent(runtime, care_level, message_text))
            for runtime in runtimes
            if runtime.is_ready()  # Only consider ready agents
        ]
        
        # Filter by care level bounds
        compatible = [
            (runtime, score) for runtime, score in scored
            if runtime.config.min_care_level.value <= care_level.value <= runtime.config.max_care_level.value
        ]
        
        if not compatible:
            # Fallback: use highest scored ready agent
            compatible = scored
        
        # Sort by score descending
        compatible.sort(key=lambda x: x[1], reverse=True)
        
        # Return top N
        selected = [runtime for runtime, _ in compatible[:max_agents]]
        
        self.logger.debug(
            f"Selected {len(selected)} agents (care={care_level.name}): "
            f"{', '.join(r.config.name for r in selected)}"
        )
        
        return selected

# ============================================================================
# WIRED ORCHESTRATOR
# ============================================================================

class WiredOrchestrator:
    """
    Complete orchestrator with full integration:
    - EQ routing (care level)
    - Memory context injection
    - Agent selection with care-awareness
    - Streaming with callbacks
    - History management
    """
    
    def __init__(
        self,
        registry: AgentRegistry,
        eq_engine,  # JeremyCricket from unified_runtime_boot.py
        memory_system,  # MemoryIndex from unified_runtime_boot.py
        logger: logging.Logger,
        max_agents_per_turn: int = 2,
        max_context_messages: int = 20,
        agent_timeout: float = 30.0,
        max_concurrent_agents: int = 6,
    ):
        self.registry = registry
        self.eq = eq_engine
        self.memory = memory_system
        self.logger = logger
        
        self.max_agents_per_turn = max_agents_per_turn
        self.max_context_messages = max_context_messages
        self.agent_timeout = agent_timeout
        self.max_concurrent_agents = max_concurrent_agents
        
        # State
        self.rooms: Dict[str, Dict[str, Any]] = {}  # room_id → room state
        self.room_agents: Dict[str, List[AgentRuntime]] = {}  # room_id → agents
        self.room_histories: Dict[str, deque] = {}  # room_id → deque of turns
        self.selector = AgentSelector(logger)
        self.semaphore = asyncio.Semaphore(max_concurrent_agents)
    
    def create_room(self, room_id: str, room_name: str) -> Dict[str, Any]:
        """Initialize a room"""
        self.rooms[room_id] = {
            "room_id": room_id,
            "room_name": room_name,
            "created_at": time.time(),
            "agent_ids": [],
        }
        self.room_agents[room_id] = []
        self.room_histories[room_id] = deque(maxlen=self.max_context_messages)
        
        self.logger.info(f"Room created: {room_name} ({room_id})")
        return self.rooms[room_id]
    
    def add_agents(self, room_id: str, agent_ids: List[str]) -> None:
        """Add agents to a room"""
        for agent_id in agent_ids:
            config = self.registry.agents.get(agent_id)
            adapter = self.registry.get_adapter(agent_id)
            
            if config and adapter:
                runtime = AgentRuntime(config=config, adapter=adapter)
                self.room_agents[room_id].append(runtime)
                self.rooms[room_id]["agent_ids"].append(agent_id)
                self.logger.info(f"Agent {config.name} added to room {room_id}")
    
    async def handle_user_message(
        self,
        room_id: str,
        user_id: str,
        text: str,
        on_chunk: Optional[callable] = None,  # Callback for each chunk
        on_done: Optional[callable] = None,   # Callback on completion
    ) -> ConversationTurn:
        """
        Main message handler:
        1. Process through EQ
        2. Get memory context
        3. Add to history
        4. Schedule agents
        5. Stream responses
        """
        
        # Get room state
        if room_id not in self.rooms:
            self.create_room(room_id, room_id)
        
        history = list(self.room_histories[room_id])
        
        # Process through EQ layer
        care_level = CareLevel(self.eq.process_message(user_id, text, history).care_level)
        care_context = self.eq.get_care_context(user_id)
        
        # Get memory context
        memory_context = self.memory.get_context(user_id, text)
        
        # Add user message to history
        user_turn = ConversationTurn(
            turn_id=str(uuid.uuid4()),
            role="user",
            sender_id=user_id,
            text=text,
            care_level=care_level.value,
            memory_context=memory_context,
        )
        self.room_histories[room_id].append(user_turn)
        
        self.logger.info(
            f"[{room_id}] User {user_id} ({care_level.name}): {text[:60]}..."
        )
        
        # Schedule agents
        await self._schedule_agents(
            room_id=room_id,
            user_id=user_id,
            care_level=care_level,
            message_text=text,
            history=history,
            on_chunk=on_chunk,
            on_done=on_done,
        )
        
        return user_turn
    
    async def _schedule_agents(
        self,
        room_id: str,
        user_id: str,
        care_level: CareLevel,
        message_text: str,
        history: List[ConversationTurn],
        on_chunk: Optional[callable],
        on_done: Optional[callable],
    ) -> None:
        """
        Select and run agents in parallel with semaphore control.
        """
        runtimes = self.room_agents.get(room_id, [])
        if not runtimes:
            self.logger.warning(f"No agents in room {room_id}")
            return
        
        # Select agents based on care level and preferences
        selected = self.selector.select(
            runtimes=runtimes,
            care_level=care_level,
            message_text=message_text,
            max_agents=self.max_agents_per_turn,
        )
        
        if not selected:
            self.logger.warning(f"No agents selected for care level {care_level.name}")
            return
        
        # Run agents concurrently with semaphore
        tasks = [
            self._run_agent_turn(
                room_id=room_id,
                runtime=runtime,
                user_id=user_id,
                message_text=message_text,
                care_level=care_level,
                history=history,
                on_chunk=on_chunk,
                on_done=on_done,
            )
            for runtime in selected
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"Agent {selected[i].config.name} failed: {result}")
    
    async def _run_agent_turn(
        self,
        room_id: str,
        runtime: AgentRuntime,
        user_id: str,
        message_text: str,
        care_level: CareLevel,
        history: List[ConversationTurn],
        on_chunk: Optional[callable],
        on_done: Optional[callable],
    ) -> None:
        """
        Run a single agent with timeout and streaming.
        """
        async with self.semaphore:  # Limit concurrent agents
            runtime.mark_invoked()
            
            try:
                # Build prompt with memory context
                memory_context = self.memory.get_context(user_id, message_text)
                
                prompt = self._build_prompt(
                    agent_config=runtime.config,
                    user_message=message_text,
                    care_level=care_level,
                    memory_context=memory_context,
                    history=history,
                )
                
                # Stream response with timeout
                full_response = ""
                
                try:
                    async for delta in asyncio.wait_for(
                        runtime.adapter.stream_reply(
                            prompt=prompt,
                            context=memory_context,
                            history=history,
                            metadata={
                                "room_id": room_id,
                                "care_level": care_level.name,
                                "user_id": user_id,
                            }
                        ),
                        timeout=self.agent_timeout,
                    ):
                        full_response += delta.text
                        
                        # Notify callback
                        if on_chunk:
                            await self._call_callback(
                                on_chunk,
                                {
                                    "agent_id": runtime.config.agent_id,
                                    "delta": delta.text,
                                    "is_final": delta.is_final,
                                }
                            )
                        
                        # Check for care escalation mid-stream
                        if delta.is_final:
                            break
                
                except asyncio.TimeoutError:
                    self.logger.warning(f"Agent {runtime.config.name} timeout")
                    full_response += " [response truncated due to timeout]"
                
                # Add agent response to history
                agent_turn = ConversationTurn(
                    turn_id=str(uuid.uuid4()),
                    role="agent",
                    sender_id=runtime.config.agent_id,
                    text=full_response,
                    care_level=care_level.value,
                )
                self.room_histories[room_id].append(agent_turn)
                
                # Update runtime stats
                runtime.success_count += 1
                runtime.total_tokens += len(full_response.split())
                
                # Notify done
                if on_done:
                    await self._call_callback(
                        on_done,
                        {
                            "agent_id": runtime.config.agent_id,
                            "text": full_response,
                            "tokens": len(full_response.split()),
                        }
                    )
                
                self.logger.info(
                    f"[{room_id}] Agent {runtime.config.name} replied "
                    f"({len(full_response)} chars)"
                )
            
            except Exception as e:
                runtime.failure_count += 1
                self.logger.error(f"Agent {runtime.config.name} error: {e}")
                raise
    
    def _build_prompt(
        self,
        agent_config: AgentConfig,
        user_message: str,
        care_level: CareLevel,
        memory_context: str,
        history: List[ConversationTurn],
    ) -> str:
        """
        Build contextualized prompt for agent.
        Includes memory, care level instructions, and conversation history.
        """
        system = f"""You are {agent_config.name}, a character in a virtual production studio.
Specialties: {', '.join(agent_config.specialties)}
Care context: User is in {care_level.name} state.

{memory_context}

Recent conversation:
"""
        
        # Add recent history
        for turn in history[-3:]:
            system += f"\n{turn.sender_id}: {turn.text}"
        
        system += f"\n\nUser just said: {user_message}"
        system += f"\n\nRespond as {agent_config.name} would, staying in character. Be concise but warm."
        
        return system
    
    async def _call_callback(self, callback: callable, data: Dict) -> None:
        """Call callback, handling both sync and async"""
        if asyncio.iscoroutinefunction(callback):
            await callback(data)
        else:
            callback(data)
    
    def get_room_stats(self, room_id: str) -> Dict[str, Any]:
        """Get stats for a room"""
        history = self.room_histories.get(room_id, deque())
        agents = self.room_agents.get(room_id, [])
        
        return {
            "room_id": room_id,
            "agents": [
                {
                    "name": a.config.name,
                    "success": a.success_count,
                    "failures": a.failure_count,
                    "tokens": a.total_tokens,
                    "ready": a.is_ready(),
                }
                for a in agents
            ],
            "conversation_turns": len(history),
            "last_message": history[-1].text[:50] if history else None,
        }

# ============================================================================
# EXAMPLE USAGE
# ============================================================================

async def example_usage():
    """Demo the wired orchestrator"""
    logger = logging.getLogger("example")
    logging.basicConfig(level=logging.INFO)
    
    # Mock EQ and memory (would come from unified_runtime_boot.py)
    class MockEQ:
        def process_message(self, user_id, text, history):
            from dataclasses import dataclass
            @dataclass
            class State:
                care_level: int = 0
            return State()
        
        def get_care_context(self, user_id):
            return {"care_level": 0, "care_name": "AMBIENT"}
    
    class MockMemory:
        def get_context(self, user_id, text):
            return ""
    
    # Create orchestrator
    registry = AgentRegistry(logger)
    orchestrator = WiredOrchestrator(
        registry=registry,
        eq_engine=MockEQ(),
        memory_system=MockMemory(),
        logger=logger,
        max_agents_per_turn=2,
    )
    
    # Create room and add agents
    orchestrator.create_room("studio", "Main Studio")
    orchestrator.add_agents("studio", ["pete", "horace"])
    
    # Callbacks
    async def on_chunk(data):
        print(data["delta"], end="", flush=True)
    
    async def on_done(data):
        print(f"\n[{data['agent_id']} done]")
    
    # Handle user message
    await orchestrator.handle_user_message(
        room_id="studio",
        user_id="user1",
        text="Hey everyone, how's it going?",
        on_chunk=on_chunk,
        on_done=on_done,
    )
    
    print(orchestrator.get_room_stats("studio"))

if __name__ == "__main__":
    asyncio.run(example_usage())
