#!/usr/bin/env python3
"""
EQ ADAPTOR — Emotional Intelligence Middleware
© 2024-2025 Rear View Foresight LLC
"Feic Mo Chroí - See My Heart"

Universal emotional intelligence layer that can be attached to any LLM.
Detects emotional state, manages care escalation, injects context.

This module is deliberately decoupled from the rest of the system.
It's a standalone product that any backend can use.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from enum import Enum
from collections import defaultdict


# ============================================================================
# ENUMS & DATA STRUCTURES
# ============================================================================

class CareLevel(Enum):
    """User emotional care state progression"""
    AMBIENT = 0                # Normal conversation, baseline
    ATTENTIVE = 1              # User showing some emotional signal
    CARE = 2                   # User needs active support
    TOTAL_CARE_MANDATE = 3     # Crisis/escalation mode


@dataclass
class EmotionalState:
    """Snapshot of user's emotional state at a point in time"""
    user_id: str
    care_level: int = 0  # CareLevel.AMBIENT
    complexity_score: float = 0.5  # 0-1, how complex is their thought
    emotional_velocity: float = 0.5  # 0-1, how fast emotions are changing
    logic_variance: float = 0.5  # 0-1, how much they're deviating from their baseline
    timestamp: float = field(default_factory=time.time)
    history_length: int = 0


@dataclass
class Memory:
    """Single stored memory about a user"""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    memory_type: str = "episodic"  # episodic, semantic, procedural, emotional, project, personal
    content: str = ""
    user_id: str = ""
    timestamp: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)
    relevance_score: float = 0.0


@dataclass
class RoutingGuidance:
    """Instructions for which agents should respond"""
    care_level: int
    care_name: str
    recommended_specialties: List[str]  # ["empathy", "technical", "humor"]
    recommended_agents: List[str]  # ["sheila", "horace", "pete"]
    suppress_agents: List[str]  # Don't use these right now
    prompt_modifiers: Dict[str, str]  # How to adjust the prompt


# ============================================================================
# PART 1: INPUT SCORING (Complexity & Velocity)
# ============================================================================

class InputScorer:
    """Analyzes raw text to extract complexity and emotional velocity signals"""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        
        # Complexity indicators
        self.complex_patterns = {
            "abstract": ["maybe", "might", "could", "probably", "seem", "appear"],
            "multi_clause": ["because", "although", "whereas", "however", "furthermore"],
            "emotional": ["feel", "emotion", "upset", "angry", "sad", "happy", "love", "hate"],
            "questioning": ["why", "how", "what if", "what about"],
        }
        
        # Velocity indicators (rapid emotional shifts)
        self.velocity_patterns = {
            "caps": ["!!!!", "????", "ARGH", "WHAT"],
            "emphasis": ["really", "absolutely", "definitely", "so"],
            "short_sentences": True,  # Detected by avg word count
            "contradiction": ["but wait", "actually", "no actually", "hang on"],
        }
    
    def score(self, text: str, history: Optional[List[Dict]] = None) -> tuple[float, float]:
        """
        Score a message for complexity and emotional velocity.
        
        Returns:
            (complexity: 0-1, velocity: 0-1)
        """
        if not text:
            return 0.5, 0.5
        
        # Complexity scoring
        complexity = self._score_complexity(text)
        
        # Velocity scoring (rate of emotional change over time)
        velocity = self._score_velocity(text, history)
        
        return complexity, velocity
    
    def _score_complexity(self, text: str) -> float:
        """0-1, higher = more abstract/complex thought"""
        score = 0.5  # baseline
        text_lower = text.lower()
        word_count = len(text.split())
        
        # Longer messages tend to be more complex
        if word_count > 30:
            score += 0.15
        if word_count > 50:
            score += 0.1
        
        # Check for abstract/complex language
        for pattern_type, patterns in self.complex_patterns.items():
            matches = sum(1 for p in patterns if p in text_lower)
            if matches > 0:
                if pattern_type == "abstract":
                    score += 0.1
                elif pattern_type == "multi_clause":
                    score += 0.15
                elif pattern_type == "emotional":
                    score += 0.08
                elif pattern_type == "questioning":
                    score += 0.12
        
        return min(1.0, score)
    
    def _score_velocity(self, text: str, history: Optional[List[Dict]]) -> float:
        """0-1, higher = faster emotional changes"""
        score = 0.5  # baseline
        text_lower = text.lower()
        
        # Current message velocity signals
        if "!!!" in text or "???" in text or text.isupper():
            score += 0.25
        
        for pattern_type, patterns in self.velocity_patterns.items():
            if pattern_type == "caps":
                for p in patterns:
                    if p in text_lower:
                        score += 0.1
            elif pattern_type == "emphasis":
                for p in patterns:
                    if p in text_lower:
                        score += 0.08
            elif pattern_type == "contradiction":
                for p in patterns:
                    if p in text_lower:
                        score += 0.12
        
        # History velocity (how much tone/topic is shifting)
        if history and len(history) >= 2:
            last_msg = history[-1].get("text", "").lower() if history else ""
            if last_msg and text_lower not in last_msg:
                # Topics shifted
                score += 0.1
        
        return min(1.0, score)


# ============================================================================
# PART 2: EMOTIONAL STATE ENGINE (Jeremy Cricket)
# ============================================================================

class CharacterEngine:
    """State machine that transitions between care levels based on emotional signals"""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.care_threshold = 0.65
        self.state_names = ["AMBIENT", "ATTENTIVE", "CARE", "TOTAL_CARE_MANDATE"]
    
    def transition(self, current_state: int, logic_variance: float) -> int:
        """
        Transition to new care level based on emotional variance.
        
        Args:
            current_state: Current CareLevel (0-3)
            logic_variance: How much user is deviating from baseline (0-1)
        
        Returns:
            New CareLevel (0-3)
        """
        if logic_variance > self.care_threshold:
            # User showing elevated emotional signal → escalate
            next_state = min(current_state + 1, 3)
        elif logic_variance < self.care_threshold * 0.5:
            # User stabilizing → de-escalate
            next_state = max(current_state - 1, 0)
        else:
            # Within threshold → stay
            next_state = current_state
        
        if next_state != current_state:
            self.logger.info(
                f"Care transition: {self.state_names[current_state]} → {self.state_names[next_state]} "
                f"(variance={logic_variance:.2f})"
            )
        
        return next_state


class JeremyCricket:
    """
    Core emotional intelligence engine.
    Monitors user emotional state and provides guidance for how system should respond.
    
    Named after Jeremy Cricket (Pinocchio) who serves as conscience/guide.
    This serves as the system's emotional conscience.
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.scorer = InputScorer(self.logger)
        self.engine = CharacterEngine(self.logger)
        self.user_states: Dict[str, EmotionalState] = {}
        self.logger.info("🦗 Jeremy Cricket EQ engine initialized")
    
    def process_message(
        self, 
        user_id: str, 
        text: str, 
        history: Optional[List[Dict]] = None
    ) -> EmotionalState:
        """
        Analyze incoming message and update user's emotional state.
        
        Args:
            user_id: Unique user identifier
            text: User's message
            history: Previous messages in conversation
        
        Returns:
            Updated EmotionalState for this user
        """
        # Score the message
        complexity, velocity = self.scorer.score(text, history)
        
        # Get or create user state
        if user_id not in self.user_states:
            self.user_states[user_id] = EmotionalState(user_id=user_id)
        
        state = self.user_states[user_id]
        state.complexity_score = complexity
        state.emotional_velocity = velocity
        state.history_length = len(history) if history else 0
        state.timestamp = time.time()
        
        # Calculate logic variance (how much user is deviating)
        logic_variance = velocity if history else 0.5
        state.logic_variance = logic_variance
        
        # Transition care level
        state.care_level = self.engine.transition(state.care_level, logic_variance)
        
        return state
    
    def get_emotional_state(self, user_id: str) -> EmotionalState:
        """Get current emotional state without processing new message"""
        return self.user_states.get(user_id, EmotionalState(user_id=user_id))
    
    def reset_user_state(self, user_id: str) -> None:
        """Reset emotional state (e.g., new session)"""
        if user_id in self.user_states:
            del self.user_states[user_id]


# ============================================================================
# PART 3: MEMORY SYSTEM
# ============================================================================

class MemoryIndex:
    """
    Simple in-memory episodic memory system.
    Stores facts about users and enables context recall.
    
    In production, would integrate with vector DB (FAISS, Pinecone, etc.)
    For now: substring matching + recency ranking.
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.memories: Dict[str, List[Memory]] = defaultdict(list)
        self.logger.info("📚 Memory system initialized")
    
    def store(
        self, 
        user_id: str, 
        content: str, 
        memory_type: str = "episodic",
        tags: Optional[List[str]] = None
    ) -> Memory:
        """
        Store a memory about a user.
        
        Args:
            user_id: User identifier
            content: What to remember
            memory_type: episodic|semantic|procedural|emotional|project|personal
            tags: Optional tags for categorization
        
        Returns:
            The stored Memory object
        """
        memory = Memory(
            user_id=user_id,
            content=content,
            memory_type=memory_type,
            tags=tags or []
        )
        self.memories[user_id].append(memory)
        self.logger.debug(f"💾 Stored {memory_type} memory: {content[:50]}...")
        return memory
    
    def recall(
        self, 
        user_id: str, 
        query: str, 
        limit: int = 5,
        memory_type: Optional[str] = None
    ) -> List[Memory]:
        """
        Recall memories matching a query.
        Simple substring matching (production would use embeddings).
        
        Args:
            user_id: User to recall for
            query: Search query
            limit: Max results
            memory_type: Filter by type (optional)
        
        Returns:
            List of matching memories, sorted by recency
        """
        if user_id not in self.memories:
            return []
        
        candidates = self.memories[user_id]
        
        # Filter by type if specified
        if memory_type:
            candidates = [m for m in candidates if m.memory_type == memory_type]
        
        # Find matches (substring search on content + tags)
        query_terms = query.lower().split()
        matching = []
        
        for memory in candidates:
            content_match = any(term in memory.content.lower() for term in query_terms)
            tags_match = any(term in tag.lower() for tag in memory.tags for term in query_terms)
            
            if content_match or tags_match:
                matching.append(memory)
        
        # Sort by recency (newest first)
        matching.sort(key=lambda m: m.timestamp, reverse=True)
        return matching[:limit]
    
    def get_context_string(
        self, 
        user_id: str, 
        query: str = "",
        limit: int = 5
    ) -> str:
        """
        Get formatted memory context for injection into LLM prompts.
        
        Returns:
            Markdown-formatted memory string or empty string
        """
        memories = self.recall(user_id, query, limit=limit) if query else list(self.memories.get(user_id, []))[-limit:]
        
        if not memories:
            return ""
        
        lines = ["## User Memory Context\n"]
        for mem in memories:
            type_label = mem.memory_type.upper()
            lines.append(f"- **[{type_label}]** {mem.content}")
        
        return "\n".join(lines)
    
    def get_all_memories(self, user_id: str) -> List[Memory]:
        """Get all memories for a user"""
        return self.memories.get(user_id, [])


# ============================================================================
# PART 4: ROUTING GUIDANCE (What agents should do)
# ============================================================================

class RoutingEngine:
    """
    Translates emotional state into actionable agent routing.
    Determines which agents should respond and how.
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        
        # Care level → specialist recommendations
        self.care_routing = {
            0: {  # AMBIENT
                "specialties": ["humor", "engagement", "light"],
                "agents": ["pete"],
                "suppress": ["total_care_agents"],
                "prompt_mod": "Keep it light and engaging.",
            },
            1: {  # ATTENTIVE
                "specialties": ["empathy", "attentive"],
                "agents": ["sheila", "pete"],
                "suppress": ["analytical_only"],
                "prompt_mod": "Show genuine attention and care.",
            },
            2: {  # CARE
                "specialties": ["empathy", "deep_listening"],
                "agents": ["sheila"],
                "suppress": ["humor", "dismissive"],
                "prompt_mod": "This person needs real care and support. Deep listen, validate, help.",
            },
            3: {  # TOTAL_CARE_MANDATE
                "specialties": ["crisis_support", "validation", "expert"],
                "agents": ["sheila"],
                "suppress": ["humor", "light", "dismissive"],
                "prompt_mod": "This is a crisis situation. Validate feelings. Offer concrete support. Consider escalation.",
            },
        }
    
    def get_guidance(
        self, 
        care_level: int,
        user_id: str,
        memory_context: str = ""
    ) -> RoutingGuidance:
        """
        Get routing guidance for a given care level.
        
        Args:
            care_level: Current CareLevel (0-3)
            user_id: User for context
            memory_context: Recalled memories to consider
        
        Returns:
            RoutingGuidance with agent recommendations
        """
        care_name = ["AMBIENT", "ATTENTIVE", "CARE", "TOTAL_CARE_MANDATE"][care_level]
        routing = self.care_routing.get(care_level, self.care_routing[0])
        
        guidance = RoutingGuidance(
            care_level=care_level,
            care_name=care_name,
            recommended_specialties=routing["specialties"],
            recommended_agents=routing["agents"],
            suppress_agents=routing["suppress"],
            prompt_modifiers={
                "tone": routing["prompt_mod"],
                "memory_context": memory_context,
            }
        )
        
        self.logger.debug(f"Routing guidance for {user_id} ({care_name}): {routing['agents']}")
        return guidance


# ============================================================================
# MAIN: EQ ADAPTOR (PUBLIC API)
# ============================================================================

class EQAdaptor:
    """
    Main public interface for EQ middleware.
    Attach to any LLM backend to add emotional intelligence.
    
    Usage:
        adaptor = EQAdaptor()
        result = adaptor.process(user_id="user123", message="I'm feeling bad")
        
        # Use result for routing:
        if result['routing'].recommended_agents:
            agent_id = result['routing'].recommended_agents[0]
            # Route to that agent with prompt modifications
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.jeremy = JeremyCricket(self.logger)
        self.memory = MemoryIndex(self.logger)
        self.router = RoutingEngine(self.logger)
        self.logger.info("✅ EQ Adaptor initialized")
    
    def process(
        self,
        user_id: str,
        message: str,
        history: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Process incoming user message and return routing guidance.
        
        This is the main entrypoint. Call this for every user message.
        
        Args:
            user_id: Unique user identifier
            message: User's message text
            history: Previous conversation (list of dicts with 'role', 'content')
        
        Returns:
            {
                'state': EmotionalState,
                'routing': RoutingGuidance,
                'memory_context': str,
                'prompt_injection': str,
                'debug': {...}
            }
        """
        # Get emotional state
        state = self.jeremy.process_message(user_id, message, history)
        
        # Recall relevant memories
        memory_context = self.memory.get_context_string(user_id, query=message)
        
        # Get routing guidance
        routing = self.router.get_guidance(
            care_level=state.care_level,
            user_id=user_id,
            memory_context=memory_context
        )
        
        # Build prompt injection string
        prompt_injection = self._build_prompt_injection(state, routing, memory_context)
        
        return {
            'state': {
                'care_level': state.care_level,
                'care_name': ["AMBIENT", "ATTENTIVE", "CARE", "TOTAL_CARE_MANDATE"][state.care_level],
                'complexity': state.complexity_score,
                'velocity': state.emotional_velocity,
                'timestamp': state.timestamp,
            },
            'routing': {
                'care_level': routing.care_level,
                'care_name': routing.care_name,
                'recommended_agents': routing.recommended_agents,
                'suppress_agents': routing.suppress_agents,
            },
            'memory_context': memory_context,
            'prompt_injection': prompt_injection,
            'debug': {
                'complexity_score': state.complexity_score,
                'emotional_velocity': state.emotional_velocity,
                'logic_variance': state.logic_variance,
                'history_length': state.history_length,
            }
        }
    
    def store_memory(
        self,
        user_id: str,
        content: str,
        memory_type: str = "episodic",
        tags: Optional[List[str]] = None
    ) -> None:
        """Store a fact about the user for future recall"""
        self.memory.store(user_id, content, memory_type, tags)
    
    def get_memory_context(self, user_id: str, query: str = "") -> str:
        """Get formatted memory context string"""
        return self.memory.get_context_string(user_id, query)
    
    def reset_user_state(self, user_id: str) -> None:
        """Reset emotional state (e.g., new session)"""
        self.jeremy.reset_user_state(user_id)
    
    def _build_prompt_injection(
        self,
        state: EmotionalState,
        routing: RoutingGuidance,
        memory_context: str
    ) -> str:
        """
        Build a string to inject into LLM prompts to guide behavior.
        This is what gets added to the system prompt.
        """
        lines = [
            f"## Emotional Context\n",
            f"User state: {routing.care_name}",
            f"Emotional signal strength: {state.emotional_velocity:.0%}",
            f"Response guidance: {routing.prompt_modifiers.get('tone', '')}",
        ]
        
        if memory_context:
            lines.append(f"\n{memory_context}")
        
        return "\n".join(lines)


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def create_adaptor(log_level: str = "INFO") -> EQAdaptor:
    """Create and configure an EQ adaptor instance"""
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    return EQAdaptor()


if __name__ == "__main__":
    # Quick self-test
    adaptor = create_adaptor("DEBUG")
    
    # Simulate a conversation
    user = "test_user_1"
    
    print("\n=== Testing EQ Adaptor ===\n")
    
    # Message 1: Normal
    result1 = adaptor.process(user, "Hi, how's it going?")
    print(f"Message 1: {result1['state']['care_name']}")
    print(f"Routing: {result1['routing']['recommended_agents']}\n")
    
    # Message 2: Escalating
    result2 = adaptor.process(user, "Actually... I'm really struggling with something. I feel overwhelmed and don't know what to do.", history=[{"role": "user", "content": "Hi"}])
    print(f"Message 2: {result2['state']['care_name']}")
    print(f"Routing: {result2['routing']['recommended_agents']}")
    print(f"Prompt injection:\n{result2['prompt_injection']}\n")
    
    # Store memory
    adaptor.store_memory(user, "User is struggling with work stress", "episodic", tags=["work", "stress"])
    
    # Message 3: Follow-up
    result3 = adaptor.process(user, "The work thing is still on my mind...", history=[{"role": "user", "content": "Actually..."}])
    print(f"Message 3: {result3['state']['care_name']}")
    print(f"Memory recalled:\n{result3['memory_context']}\n")
    
    print("✅ EQ Adaptor tests passed")
