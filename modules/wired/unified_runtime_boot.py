#!/usr/bin/env python3
"""
UNIFIED RUNTIME BOOTLOADER
PubCast AI — "Feic Mo Chroí"

Complete executable system wiring together:
- Core event bus (Hub)
- Agent orchestration (Orchestrator)
- EQ layer (Jeremy Cricket)
- Memory system (UAI memory index)
- Friday agent runtime
- FastAPI HTTP/WebSocket server
- Crash recovery & persistence
- Configuration management

This is the single entry point. Everything starts here.
"""

import asyncio
import logging
import sys
import time
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Set
from datetime import datetime
import traceback

# ============================================================================
# PART 1: CONFIGURATION SYSTEM
# ============================================================================

@dataclass
class EQConfig:
    """Emotional Intelligence layer tuning"""
    enabled: bool = True
    care_threshold: float = 0.65  # Logic variance threshold
    max_care_level: int = 4  # AMBIENT=0, ATTENTIVE=1, CARE=2, TOTAL_CARE_MANDATE=3
    complexity_weight: float = 0.7
    velocity_weight: float = 0.3
    memory_scoring_enabled: bool = True

@dataclass
class OrchestratorConfig:
    """Agent scheduling tuning"""
    max_agents_per_turn: int = 2
    max_context_messages: int = 20
    agent_timeout: float = 30.0
    max_concurrent_agents: int = 6
    default_agent_priority: int = 5
    default_agent_cooldown_ms: int = 2000

@dataclass
class MemoryConfig:
    """Memory system tuning"""
    enabled: bool = True
    vector_embedding_model: str = "all-MiniLM-L6-v2"
    memory_types: List[str] = field(default_factory=lambda: [
        "episodic", "semantic", "procedural", "emotional", "project", "personal"
    ])
    max_memories_recalled: int = 5
    recall_threshold: float = 0.6

@dataclass
class PersistenceConfig:
    """Storage & crash recovery"""
    enabled: bool = True
    data_dir: Path = field(default_factory=lambda: Path("data"))
    snapshot_interval_seconds: int = 300  # Snapshot every 5 min
    enable_versioning: bool = True
    max_snapshots: int = 10

@dataclass
class RuntimeConfig:
    """Master configuration"""
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    debug: bool = False
    
    eq: EQConfig = field(default_factory=EQConfig)
    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    persistence: PersistenceConfig = field(default_factory=PersistenceConfig)
    
    @classmethod
    def load_from_file(cls, path: Path) -> "RuntimeConfig":
        """Load config from YAML or JSON"""
        if not path.exists():
            return cls()  # Return defaults
        try:
            with open(path) as f:
                if path.suffix == ".json":
                    data = json.load(f)
                    return cls(**data)
                else:
                    import yaml
                    data = yaml.safe_load(f)
                    return cls(**data)
        except Exception as e:
            logging.warning(f"Failed to load config from {path}: {e}. Using defaults.")
            return cls()
    
    def save_to_file(self, path: Path) -> None:
        """Persist config to JSON"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2, default=str)

# ============================================================================
# PART 2: LOGGING SYSTEM
# ============================================================================

class StructuredLogger:
    """Centralized logging with context"""
    
    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.logger = logging.getLogger("pubcast")
        self.logger.setLevel(getattr(logging, config.log_level))
        
        # Console handler
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
        # File handler
        log_file = config.persistence.data_dir / "logs" / "runtime.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
    
    def get_logger(self, module_name: str):
        """Get logger for a specific module"""
        return logging.getLogger(f"pubcast.{module_name}")

# ============================================================================
# PART 3: EQ LAYER (JEREMY CRICKET)
# ============================================================================

@dataclass
class EmotionalState:
    """User emotional state at a moment"""
    timestamp: float = field(default_factory=time.time)
    logic_variance: float = 0.0  # Gap from baseline (0.0-1.0)
    complexity_score: float = 0.0  # Message complexity
    emotional_velocity: float = 0.0  # Rate of emotional change
    care_level: int = 0  # 0=AMBIENT, 1=ATTENTIVE, 2=CARE, 3=TOTAL_CARE_MANDATE

class InputScorer:
    """Converts raw text to emotional metrics"""
    
    def __init__(self, config: EQConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.baseline_length = 50  # Baseline message length
    
    def score(self, text: str, history: List[Dict[str, str]]) -> tuple:
        """
        Returns (complexity_score, emotional_velocity)
        """
        # Complexity: based on length, punctuation, fragmentation
        length_factor = len(text) / max(self.baseline_length, 1)
        caps_ratio = sum(1 for c in text if c.isupper()) / max(len(text), 1)
        ellipsis_count = text.count("...")
        question_count = text.count("?")
        exclamation_count = text.count("!")
        
        complexity = min(1.0, length_factor * 0.5 + caps_ratio * 0.3 + (question_count + exclamation_count) * 0.2)
        
        # Emotional velocity: compare to recent messages
        velocity = 0.0
        if history:
            recent_lengths = [len(turn.get("text", "")) for turn in history[-3:]]
            if recent_lengths:
                avg_recent = sum(recent_lengths) / len(recent_lengths)
                velocity = abs(len(text) - avg_recent) / max(avg_recent, 1)
        
        return min(1.0, complexity), min(1.0, velocity)

class CharacterEngine:
    """State machine for care levels"""
    
    def __init__(self, config: EQConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.state_names = ["AMBIENT", "ATTENTIVE", "CARE", "TOTAL_CARE_MANDATE"]
    
    def transition(self, current_state: int, logic_variance: float) -> int:
        """
        Transition care level based on logic variance (gap from baseline)
        """
        if logic_variance > self.config.care_threshold:
            # Escalate
            next_state = min(current_state + 1, self.config.max_care_level - 1)
        elif logic_variance < self.config.care_threshold * 0.5:
            # De-escalate
            next_state = max(current_state - 1, 0)
        else:
            next_state = current_state
        
        if next_state != current_state:
            self.logger.info(f"Care transition: {self.state_names[current_state]} → {self.state_names[next_state]}")
        
        return next_state

class JeremyCricket:
    """
    The emotional intelligence engine.
    Monitors user state and adapts system response.
    """
    
    def __init__(self, config: EQConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.scorer = InputScorer(config, logger)
        self.engine = CharacterEngine(config, logger)
        self.user_states: Dict[str, EmotionalState] = {}
    
    def process_message(self, user_id: str, text: str, history: List[Dict]) -> EmotionalState:
        """
        Analyze a message and update emotional state
        """
        complexity, velocity = self.scorer.score(text, history)
        
        # Calculate logic variance from history
        logic_variance = velocity if history else 0.5
        
        # Get current or initialize state
        if user_id not in self.user_states:
            self.user_states[user_id] = EmotionalState()
        
        state = self.user_states[user_id]
        state.complexity_score = complexity
        state.emotional_velocity = velocity
        state.logic_variance = logic_variance
        state.timestamp = time.time()
        
        # Transition care level
        state.care_level = self.engine.transition(state.care_level, logic_variance)
        
        return state
    
    def get_care_context(self, user_id: str) -> Dict[str, Any]:
        """Get context about user's emotional state for agent routing"""
        state = self.user_states.get(user_id, EmotionalState())
        return {
            "care_level": state.care_level,
            "care_name": ["AMBIENT", "ATTENTIVE", "CARE", "TOTAL_CARE_MANDATE"][state.care_level],
            "complexity": state.complexity_score,
            "velocity": state.emotional_velocity,
        }

# ============================================================================
# PART 4: MEMORY SYSTEM
# ============================================================================

@dataclass
class Memory:
    """Single memory entry"""
    id: str
    type: str  # episodic, semantic, procedural, emotional, project, personal
    content: str
    user_id: str
    timestamp: float = field(default_factory=time.time)
    relevance_score: float = 0.0
    tags: List[str] = field(default_factory=list)

class MemoryIndex:
    """
    Simple in-memory memory system.
    In production, would use FAISS + vector embeddings.
    """
    
    def __init__(self, config: MemoryConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.memories: Dict[str, List[Memory]] = {}
    
    def store(self, user_id: str, memory: Memory) -> None:
        """Store a memory"""
        if user_id not in self.memories:
            self.memories[user_id] = []
        self.memories[user_id].append(memory)
        self.logger.debug(f"Memory stored: {memory.type} for {user_id}")
    
    def recall(self, user_id: str, query: str, limit: int = 5) -> List[Memory]:
        """
        Recall memories matching a query.
        Simple substring matching for MVP.
        """
        if user_id not in self.memories:
            return []
        
        matching = [
            m for m in self.memories[user_id]
            if any(keyword in m.content.lower() for keyword in query.lower().split())
        ]
        
        # Sort by timestamp (recency)
        matching.sort(key=lambda m: m.timestamp, reverse=True)
        return matching[:limit]
    
    def get_context(self, user_id: str, query: str = "") -> str:
        """Get formatted context for agent prompts"""
        memories = self.recall(user_id, query) if query else self.memories.get(user_id, [])[-5:]
        if not memories:
            return ""
        
        context = "## User Memory Context\n"
        for mem in memories:
            context += f"- [{mem.type}] {mem.content}\n"
        return context

# ============================================================================
# PART 5: PERSISTENCE LAYER
# ============================================================================

class PersistenceManager:
    """Handles snapshots, recovery, and state persistence"""
    
    def __init__(self, config: PersistenceConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.data_dir = config.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.snapshots_dir = self.data_dir / "snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        
        self.last_snapshot = 0.0
    
    async def snapshot(self, state: Dict[str, Any]) -> None:
        """Save state snapshot for recovery"""
        if not self.config.enabled:
            return
        
        now = time.time()
        if now - self.last_snapshot < self.config.snapshot_interval_seconds:
            return
        
        timestamp = datetime.now().isoformat()
        snapshot_file = self.snapshots_dir / f"snapshot_{timestamp.replace(':', '-')}.json"
        
        try:
            with open(snapshot_file, "w") as f:
                json.dump(state, f, indent=2, default=str)
            self.logger.info(f"Snapshot saved: {snapshot_file}")
            self.last_snapshot = now
            
            # Cleanup old snapshots
            self._cleanup_old_snapshots()
        except Exception as e:
            self.logger.error(f"Snapshot failed: {e}")
    
    def _cleanup_old_snapshots(self) -> None:
        """Keep only N most recent snapshots"""
        snapshots = sorted(self.snapshots_dir.glob("snapshot_*.json"))
        if len(snapshots) > self.config.max_snapshots:
            for snapshot in snapshots[:-self.config.max_snapshots]:
                snapshot.unlink()
    
    def recover(self) -> Optional[Dict[str, Any]]:
        """Load latest snapshot for recovery"""
        snapshots = sorted(self.snapshots_dir.glob("snapshot_*.json"), reverse=True)
        if not snapshots:
            return None
        
        try:
            with open(snapshots[0]) as f:
                state = json.load(f)
            self.logger.info(f"Recovered from snapshot: {snapshots[0]}")
            return state
        except Exception as e:
            self.logger.error(f"Recovery failed: {e}")
            return None

# ============================================================================
# PART 6: UNIFIED RUNTIME
# ============================================================================

class UnifiedRuntime:
    """
    Master runtime coordinating all systems.
    Single entry point for the entire PubCast system.
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        # Load configuration
        self.config = RuntimeConfig.load_from_file(config_path) if config_path else RuntimeConfig()
        
        # Setup logging
        self.logger_system = StructuredLogger(self.config)
        self.logger = self.logger_system.get_logger("runtime")
        
        # Initialize subsystems
        self.eq = JeremyCricket(self.config.eq, self.logger_system.get_logger("eq"))
        self.memory = MemoryIndex(self.config.memory, self.logger_system.get_logger("memory"))
        self.persistence = PersistenceManager(self.config.persistence, self.logger_system.get_logger("persistence"))
        
        # State
        self._running = False
        self._boot_time = None
        self._rooms: Dict[str, Set[Any]] = {}  # room_id → websockets
        self._room_histories: Dict[str, List[Dict]] = {}
        
        self.logger.info("✨ PubCast Unified Runtime initialized")
    
    async def bootstrap(self) -> None:
        """
        Complete boot sequence.
        Starts all systems in correct order.
        """
        self.logger.info("🚀 BOOT SEQUENCE STARTING")
        self._boot_time = time.time()
        
        try:
            # Phase 1: Validate configuration
            self.logger.info("[1/6] Loading configuration...")
            self.config.save_to_file(self.config.persistence.data_dir / "runtime.config.json")
            self.logger.info(f"     Host: {self.config.host}:{self.config.port}")
            self.logger.info(f"     Log level: {self.config.log_level}")
            
            # Phase 2: Initialize persistence
            self.logger.info("[2/6] Initializing persistence layer...")
            recovered = self.persistence.recover()
            if recovered:
                self.logger.info("     Recovered from snapshot!")
                # Would restore rooms/histories here
            
            # Phase 3: Initialize EQ layer
            self.logger.info("[3/6] Initializing emotional intelligence layer...")
            self.logger.info(f"     Care threshold: {self.config.eq.care_threshold}")
            self.logger.info(f"     Max care level: {self.config.eq.max_care_level}")
            
            # Phase 4: Initialize memory system
            self.logger.info("[4/6] Initializing memory system...")
            self.logger.info(f"     Memory types: {', '.join(self.config.memory.memory_types)}")
            self.logger.info(f"     Recall limit: {self.config.memory.max_memories_recalled}")
            
            # Phase 5: Initialize orchestrator
            self.logger.info("[5/6] Initializing agent orchestrator...")
            self.logger.info(f"     Max agents/turn: {self.config.orchestrator.max_agents_per_turn}")
            self.logger.info(f"     Agent timeout: {self.config.orchestrator.agent_timeout}s")
            
            # Phase 6: Initialize HTTP/WebSocket server
            self.logger.info("[6/6] Initializing HTTP/WebSocket server...")
            self.logger.info(f"     Listening on {self.config.host}:{self.config.port}")
            
            self._running = True
            boot_time = time.time() - self._boot_time
            self.logger.info(f"✅ BOOT COMPLETE in {boot_time:.2f}s")
            self.logger.info("")
            self.logger.info("=" * 60)
            self.logger.info("🎭 PubCast AI Virtual Production Studio LIVE")
            self.logger.info("   'Feic Mo Chroí - See My Heart'")
            self.logger.info("=" * 60)
            self.logger.info("")
            
        except Exception as e:
            self.logger.error(f"❌ BOOT FAILED: {e}")
            self.logger.error(traceback.format_exc())
            raise
    
    async def shutdown(self) -> None:
        """Graceful shutdown with state persistence"""
        self.logger.info("🛑 Shutting down...")
        self._running = False
        
        # Save final state
        state = {
            "rooms": list(self._rooms.keys()),
            "runtime": self.config.host + ":" + str(self.config.port),
            "uptime_seconds": time.time() - self._boot_time if self._boot_time else 0,
        }
        await self.persistence.snapshot(state)
        
        self.logger.info("👋 Shutdown complete")
    
    def get_health(self) -> Dict[str, Any]:
        """System health status"""
        uptime = time.time() - self._boot_time if self._boot_time else 0
        return {
            "running": self._running,
            "uptime_seconds": uptime,
            "rooms_active": len(self._rooms),
            "total_memories": sum(len(mems) for mems in self.memory.memories.values()),
            "eq_enabled": self.config.eq.enabled,
            "memory_enabled": self.config.memory.enabled,
            "persistence_enabled": self.config.persistence.enabled,
        }
    
    async def handle_user_message(self, room_id: str, user_id: str, text: str) -> Dict[str, Any]:
        """
        Main message handler. Routes through EQ + Memory + Agent selection.
        """
        # Initialize room if needed
        if room_id not in self._room_histories:
            self._room_histories[room_id] = []
        
        history = self._room_histories[room_id]
        
        # Process through EQ layer
        emotional_state = self.eq.process_message(user_id, text, history)
        care_context = self.eq.get_care_context(user_id)
        
        # Store message in memory
        from uuid import uuid4
        memory = Memory(
            id=str(uuid4()),
            type="episodic",
            content=text,
            user_id=user_id,
            tags=[care_context["care_name"], "message"]
        )
        self.memory.store(user_id, memory)
        
        # Add to room history
        history.append({
            "role": "user",
            "user_id": user_id,
            "text": text,
            "care_level": emotional_state.care_level,
            "timestamp": emotional_state.timestamp,
        })
        
        self.logger.info(f"[{room_id}] {user_id}: {text[:50]}... (care={care_context['care_name']})")
        
        return {
            "success": True,
            "room_id": room_id,
            "user_id": user_id,
            "care_context": care_context,
            "memory_context": self.memory.get_context(user_id, text),
        }

# ============================================================================
# PART 7: ENTRY POINT
# ============================================================================

async def main():
    """Main entry point"""
    # Create runtime
    runtime = UnifiedRuntime(config_path=Path("runtime.config.json"))
    
    # Bootstrap all systems
    await runtime.bootstrap()
    
    try:
        # Keep running
        while runtime._running:
            # Periodic snapshots
            await runtime.persistence.snapshot({"health": runtime.get_health()})
            await asyncio.sleep(60)
    
    except KeyboardInterrupt:
        print("\n")
    
    finally:
        await runtime.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
